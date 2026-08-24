from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from metis_model1.accuracy_maintenance import (
    AccuracyMaintenanceError,
    LocalMaintenanceDraft,
    MaintenanceAuthorityUnavailableError,
    VerifiedMaintenanceRoster,
    build_t30_seal,
    canonical_roster_sha256,
    load_maintenance_roster,
    require_verified_maintenance_roster,
    validate_maintenance_roster,
    verify_maintenance_roster,
)

ROOT = Path(__file__).parents[1]
FAMILIES = tuple(f"F-{number}" for number in range(1, 7))


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _json_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _write_json(root: Path, relative: str, value: object) -> dict[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical(value)
    path.write_bytes(payload)
    return {"path": relative, "sha256": _bytes_hash(payload)}


def _counts(tasks: list[dict]) -> dict:
    return {
        **{
            split: {
                "tasks": sum(task["split"] == split for task in tasks),
                "families": {
                    family: sum(
                        task["split"] == split and task["family"] == family for task in tasks
                    )
                    for family in FAMILIES
                },
            }
            for split in ("D18", "T30")
        },
        "total": len(tasks),
    }


def _rehash(roster: dict) -> dict:
    roster["roster_sha256"] = canonical_roster_sha256(roster)
    return roster


def _pending() -> dict:
    roster = {
        "schema_version": 1,
        "roster_id": "maintenance/l77-v1",
        "status": "pending",
        "authority_status": "NO_AUTHORITY_PENDING",
        "model_outputs_observed": False,
        "upstream_pin": None,
        "construct_registry": None,
        "tasks": [],
        "counts": {
            "D18": {"tasks": 0, "families": {family: 0 for family in FAMILIES}},
            "T30": {"tasks": 0, "families": {family: 0 for family in FAMILIES}},
            "total": 0,
        },
        "roster_sha256": "sha256:" + "0" * 64,
    }
    return _rehash(roster)


def _draft(
    root: Path,
    *,
    cross_split_identifier: bool = False,
    cross_split_template_root: bool = False,
    extra_catalog: tuple[str, str, int] | None = None,
    same_split_overlap: str | None = None,
) -> dict:
    revision, tree = "a" * 40, "b" * 40
    probes = {
        "grammar": "pass",
        "validator": "pass",
        "compiler": "pass",
        "ir_contract": "pass",
        "retrieval_contract": "pass",
        "semantic_oracle": "pass",
        "tenant_threshold_setting_keys": "pass",
    }
    probe = {
        "schema_version": 1,
        "evidence_role": "upstream_probe_bundle",
        "repository": "ares-matioska/metis",
        "revision": revision,
        "tree": tree,
        "probes": probes,
        "pre_output": True,
    }
    pin = {
        "repository": "ares-matioska/metis",
        "revision": revision,
        "tree": tree,
        "probe_receipt": _write_json(root, "evidence/upstream/probes.json", probe),
    }
    entries = [
        {
            "construct": "catalog_value_domain",
            "families": ["F-1", "F-6"],
            "catalog_domain": True,
            "oracle_authority": "metis_catalog_oracle",
        },
        {
            "construct": "standard_construct",
            "families": list(FAMILIES),
            "catalog_domain": False,
            "oracle_authority": "metis_standard_oracle",
        },
    ]
    registry = {
        "registry_id": "accuracy-maintenance/constructs-v1",
        "entries": entries,
        "registry_sha256": _json_hash(
            {"registry_id": "accuracy-maintenance/constructs-v1", "entries": entries}
        ),
    }

    tasks: list[dict] = []
    first_d18_identifier: str | None = None
    first_d18_template_root: str | None = None
    overlap_seed: dict[str, Any] = {}
    for split, per_family in (("D18", 3), ("T30", 5)):
        for family in FAMILIES:
            for ordinal in range(1, per_family + 1):
                task_id = f"{split.lower()}-{family.lower().replace('-', '')}-{ordinal:02d}"
                catalog = (family in {"F-1", "F-6"} and ordinal == 1) or (
                    extra_catalog == (split, family, ordinal)
                )
                construct = "catalog_value_domain" if catalog else "standard_construct"
                oracle_authority = "metis_catalog_oracle" if catalog else "metis_standard_oracle"
                prefix = f"evidence/tasks/{task_id}"
                context = {
                    "task_id": task_id,
                    "split": split,
                    "family": family,
                    "construct": construct,
                    "upstream_revision": revision,
                    "upstream_tree": tree,
                }

                prompt_payload = {"instruction": f"solve {task_id}", "catalog": catalog}
                ast_identity = _json_hash({"ast": task_id})
                ir_identity = _json_hash({"ir": task_id})
                expected_output = {"answer": task_id, "catalog": catalog}
                identifier = f"identifier-{task_id}"
                identifiers = [identifier]
                parent_roots = [_json_hash({"parent": task_id})]
                template_roots = [_json_hash({"template": task_id})]
                ast_identities = [ast_identity]
                ir_identities = [ir_identity]

                if split == "D18" and family == "F-1" and ordinal == 1:
                    overlap_seed = {
                        "prompt_payload_sha256": copy.deepcopy(prompt_payload),
                        "expected_output_root_sha256": copy.deepcopy(expected_output),
                        "parent_roots": list(parent_roots),
                        "template_roots": list(template_roots),
                        "identifiers": list(identifiers),
                        "normalized_ast_identities": list(ast_identities),
                        "normalized_ir_identities": list(ir_identities),
                    }
                    first_d18_identifier = identifier
                    first_d18_template_root = template_roots[0]
                elif (
                    split == "D18"
                    and family == "F-1"
                    and ordinal == 2
                    and same_split_overlap is not None
                ):
                    assert same_split_overlap in overlap_seed
                    reused = copy.deepcopy(overlap_seed[same_split_overlap])
                    if same_split_overlap == "prompt_payload_sha256":
                        prompt_payload = reused
                    elif same_split_overlap == "expected_output_root_sha256":
                        expected_output = reused
                    elif same_split_overlap == "parent_roots":
                        parent_roots = reused
                    elif same_split_overlap == "template_roots":
                        template_roots = reused
                    elif same_split_overlap == "identifiers":
                        identifiers = reused
                    elif same_split_overlap == "normalized_ast_identities":
                        ast_identities = reused
                        ast_identity = ast_identities[0]
                    elif same_split_overlap == "normalized_ir_identities":
                        ir_identities = reused
                        ir_identity = ir_identities[0]

                if cross_split_identifier and split == "T30" and family == "F-1" and ordinal == 1:
                    assert first_d18_identifier is not None
                    identifiers.append(first_d18_identifier)
                if (
                    cross_split_template_root
                    and split == "T30"
                    and family == "F-1"
                    and ordinal == 1
                ):
                    assert first_d18_template_root is not None
                    template_roots.append(first_d18_template_root)

                prompt = {
                    "schema_version": 1,
                    "evidence_role": "maintenance_prompt",
                    **context,
                    "payload": prompt_payload,
                    "payload_sha256": _json_hash(prompt_payload),
                    "pre_output": True,
                }
                prompt_ref = _write_json(root, f"{prefix}/prompt.json", prompt)

                truth = {
                    "schema_version": 1,
                    "evidence_role": "maintenance_truth",
                    **context,
                    "prompt_sha256": prompt_ref["sha256"],
                    "expected_output": expected_output,
                    "expected_output_sha256": _json_hash(expected_output),
                    "normalized_ast_sha256": ast_identity,
                    "normalized_ir_sha256": ir_identity,
                    "pre_output": True,
                }
                truth_ref = _write_json(root, f"{prefix}/truth.json", truth)

                oracle_result = {"semantic": "pass", "task": task_id}
                oracle = {
                    "schema_version": 1,
                    "evidence_role": "maintenance_oracle_receipt",
                    **context,
                    "truth_sha256": truth_ref["sha256"],
                    "authority": oracle_authority,
                    "status": "pass",
                    "result": oracle_result,
                    "result_sha256": _json_hash(oracle_result),
                    "normalized_ast_sha256": ast_identity,
                    "normalized_ir_sha256": ir_identity,
                    "pre_output": True,
                }
                oracle_ref = _write_json(root, f"{prefix}/oracle.json", oracle)

                genealogy = {
                    "schema_version": 1,
                    "evidence_role": "maintenance_genealogy",
                    "task_id": task_id,
                    "split": split,
                    "family": family,
                    "construct": construct,
                    "parent_roots": parent_roots,
                    "template_roots": template_roots,
                    "identifiers": identifiers,
                    "normalized_ast_identities": ast_identities,
                    "normalized_ir_identities": ir_identities,
                    "pre_output": True,
                }
                genealogy_ref = _write_json(root, f"{prefix}/genealogy.json", genealogy)

                retrieval_ref: dict[str, str] | None = None
                if catalog:
                    request = {"field": f"field-{task_id}"}
                    result = {"domain_marker": "enum(3)", "value_count": 3}
                    retrieval = {
                        "schema_version": 1,
                        "evidence_role": "maintenance_retrieval_receipt",
                        **context,
                        "prompt_sha256": prompt_ref["sha256"],
                        "authority": "toolchain_per_field_retrieval",
                        "status": "pass",
                        "request": request,
                        "request_sha256": _json_hash(request),
                        "result": result,
                        "result_sha256": _json_hash(result),
                        "tenant_values_materialized_in_prompt": False,
                        "pre_output": True,
                    }
                    retrieval_ref = _write_json(root, f"{prefix}/retrieval.json", retrieval)
                    retrieval_evidence = {"kind": "receipt", **retrieval_ref}
                else:
                    retrieval_evidence = {"kind": "non_catalog", "marker": "non_catalog"}

                genealogy_root = genealogy_ref["sha256"]
                identifier_root = _json_hash(identifiers)
                ast_root = _json_hash(ast_identities)
                ir_root = _json_hash(ir_identities)
                expected_output_root = truth["expected_output_sha256"]
                content_root = _json_hash(
                    {
                        "prompt": prompt_ref["sha256"],
                        "truth": truth_ref["sha256"],
                        "oracle_receipt": oracle_ref["sha256"],
                        "retrieval_evidence": (
                            retrieval_ref["sha256"] if retrieval_ref is not None else "non_catalog"
                        ),
                        "genealogy": genealogy_root,
                    }
                )
                provenance_root = _json_hash(
                    {
                        **context,
                        "parent_roots": parent_roots,
                        "template_roots": template_roots,
                        "content_root_sha256": content_root,
                        "genealogy_root_sha256": genealogy_root,
                        "identifier_root_sha256": identifier_root,
                        "normalized_ast_root_sha256": ast_root,
                        "normalized_ir_root_sha256": ir_root,
                        "expected_output_root_sha256": expected_output_root,
                    }
                )
                tasks.append(
                    {
                        **context,
                        "prompt": prompt_ref,
                        "truth": truth_ref,
                        "oracle_receipt": oracle_ref,
                        "retrieval_evidence": retrieval_evidence,
                        "genealogy": genealogy_ref,
                        "provenance_root_sha256": provenance_root,
                        "content_root_sha256": content_root,
                        "genealogy_root_sha256": genealogy_root,
                        "identifier_root_sha256": identifier_root,
                        "normalized_ast_root_sha256": ast_root,
                        "normalized_ir_root_sha256": ir_root,
                        "expected_output_root_sha256": expected_output_root,
                        "pre_output_status": "local_preoutput_evidence",
                    }
                )

    roster = {
        "schema_version": 1,
        "roster_id": "maintenance/l77-v1",
        "status": "local_unpublished_draft",
        "authority_status": "LOCAL_UNPUBLISHED_DRAFT",
        "model_outputs_observed": False,
        "upstream_pin": pin,
        "construct_registry": registry,
        "tasks": tasks,
        "counts": _counts(tasks),
        "roster_sha256": "sha256:" + "0" * 64,
    }
    return _rehash(roster)


def _replace_json(root: Path, reference: dict, value: object) -> None:
    payload = _canonical(value)
    (root / reference["path"]).write_bytes(payload)
    reference["sha256"] = _bytes_hash(payload)


def test_pending_and_local_draft_are_fixed_schema_valid(tmp_path: Path) -> None:
    schema = json.loads((ROOT / "schemas/accuracy-maintenance-roster.schema.json").read_text())
    Draft202012Validator.check_schema(schema)

    pending = _pending()
    assert list(Draft202012Validator(schema).iter_errors(pending)) == []
    assert validate_maintenance_roster(pending) == pending

    roster = _draft(tmp_path)
    assert list(Draft202012Validator(schema).iter_errors(roster)) == []
    draft = validate_maintenance_roster(roster, tmp_path)
    assert isinstance(draft, LocalMaintenanceDraft)
    assert draft.authority_status == "LOCAL_UNPUBLISHED_DRAFT"
    assert len(draft.task_bindings) == 48
    assert sum(binding.split == "D18" for binding in draft.task_bindings) == 18
    assert sum(binding.split == "T30" for binding in draft.task_bindings) == 30
    assert sum(binding.catalog_domain for binding in draft.task_bindings) == 4


def test_local_draft_cannot_self_seal_or_become_decision_authority(tmp_path: Path) -> None:
    draft = validate_maintenance_roster(_draft(tmp_path), tmp_path)
    assert isinstance(draft, LocalMaintenanceDraft)
    with pytest.raises(MaintenanceAuthorityUnavailableError, match="pushed Git"):
        verify_maintenance_roster(draft)
    with pytest.raises(MaintenanceAuthorityUnavailableError, match="pushed Git"):
        build_t30_seal(draft)
    with pytest.raises(MaintenanceAuthorityUnavailableError, match="pushed-Git"):
        require_verified_maintenance_roster(draft)
    with pytest.raises(TypeError, match="no issuer"):
        VerifiedMaintenanceRoster()


def test_counters_and_flags_cannot_substitute_for_rows(tmp_path: Path) -> None:
    forged = _pending()
    forged["status"] = "local_unpublished_draft"
    forged["authority_status"] = "LOCAL_UNPUBLISHED_DRAFT"
    forged["counts"] = {
        "D18": {"tasks": 18, "families": {family: 3 for family in FAMILIES}},
        "T30": {"tasks": 30, "families": {family: 5 for family in FAMILIES}},
        "total": 48,
    }
    _rehash(forged)
    with pytest.raises(AccuracyMaintenanceError, match="fixed schema violation"):
        validate_maintenance_roster(forged, tmp_path)


def test_arbitrary_real_files_are_not_role_specific_evidence(tmp_path: Path) -> None:
    roster = _draft(tmp_path)
    task = roster["tasks"][0]
    arbitrary = _write_json(tmp_path, "evidence/arbitrary.json", {"real": "file"})
    task["prompt"] = arbitrary
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="must contain exactly"):
        validate_maintenance_roster(roster, tmp_path)


def test_pin_registry_and_catalog_retrieval_are_cross_bound(tmp_path: Path) -> None:
    roster = _draft(tmp_path)
    roster["tasks"][0]["upstream_revision"] = "c" * 40
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="one upstream pin"):
        validate_maintenance_roster(roster, tmp_path)

    other_root = tmp_path / "catalog-marker"
    roster = _draft(other_root)
    catalog = next(task for task in roster["tasks"] if task["construct"] == "catalog_value_domain")
    catalog["retrieval_evidence"] = {"kind": "non_catalog", "marker": "non_catalog"}
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="lacks retrieval receipt"):
        validate_maintenance_roster(roster, other_root)

    registry_root = tmp_path / "registry"
    roster = _draft(registry_root)
    roster["construct_registry"]["entries"][0]["catalog_domain"] = False
    registry_body = {
        "registry_id": roster["construct_registry"]["registry_id"],
        "entries": roster["construct_registry"]["entries"],
    }
    roster["construct_registry"]["registry_sha256"] = _json_hash(registry_body)
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="one exact catalog-domain construct"):
        validate_maintenance_roster(roster, registry_root)

    family_root = tmp_path / "catalog-family-expansion"
    roster = _draft(family_root)
    roster["construct_registry"]["entries"][0]["families"] = ["F-1", "F-2", "F-6"]
    registry_body = {
        "registry_id": roster["construct_registry"]["registry_id"],
        "entries": roster["construct_registry"]["entries"],
    }
    roster["construct_registry"]["registry_sha256"] = _json_hash(registry_body)
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="authorize exactly F-1 and F-6"):
        validate_maintenance_roster(roster, family_root)


def test_catalog_domain_reservation_is_exact_per_split_and_family(tmp_path: Path) -> None:
    roster = _draft(tmp_path, extra_catalog=("D18", "F-1", 2))
    with pytest.raises(AccuracyMaintenanceError, match="reserve exactly one F-1 and F-6"):
        validate_maintenance_roster(roster, tmp_path)


@pytest.mark.parametrize(
    "identity_field",
    (
        "prompt_payload_sha256",
        "expected_output_root_sha256",
        "parent_roots",
        "template_roots",
        "identifiers",
        "normalized_ast_identities",
        "normalized_ir_identities",
    ),
)
def test_same_split_task_identities_cannot_be_reused(tmp_path: Path, identity_field: str) -> None:
    roster = _draft(tmp_path, same_split_overlap=identity_field)
    with pytest.raises(
        AccuracyMaintenanceError,
        match=rf"D18 {identity_field} identities must be unique across tasks",
    ):
        validate_maintenance_roster(roster, tmp_path)


def test_roots_are_derived_and_cross_split_identity_is_disjoint(tmp_path: Path) -> None:
    roster = _draft(tmp_path)
    roster["tasks"][0]["content_root_sha256"] = "sha256:" + "0" * 64
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="not derived"):
        validate_maintenance_roster(roster, tmp_path)

    overlap_root = tmp_path / "overlap"
    roster = _draft(overlap_root, cross_split_identifier=True)
    with pytest.raises(AccuracyMaintenanceError, match="identifiers.*disjoint"):
        validate_maintenance_roster(roster, overlap_root)

    template_overlap_root = tmp_path / "template-overlap"
    roster = _draft(template_overlap_root, cross_split_template_root=True)
    with pytest.raises(AccuracyMaintenanceError, match="template_roots.*disjoint"):
        validate_maintenance_roster(roster, template_overlap_root)


def test_duplicate_task_and_evidence_paths_fail_closed(tmp_path: Path) -> None:
    roster = _draft(tmp_path)
    roster["tasks"][1] = copy.deepcopy(roster["tasks"][0])
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="duplicate task_id"):
        validate_maintenance_roster(roster, tmp_path)

    other_root = tmp_path / "duplicate-path"
    roster = _draft(other_root)
    roster["tasks"][1]["prompt"] = copy.deepcopy(roster["tasks"][0]["prompt"])
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError):
        validate_maintenance_roster(roster, other_root)


def test_escape_symlink_hardlink_and_hash_drift_fail_closed(tmp_path: Path) -> None:
    escape_root = tmp_path / "escape"
    roster = _draft(escape_root)
    roster["tasks"][0]["prompt"]["path"] = "../outside.json"
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="fixed schema violation"):
        validate_maintenance_roster(roster, escape_root)

    symlink_root = tmp_path / "symlink"
    roster = _draft(symlink_root)
    relative = roster["tasks"][0]["oracle_receipt"]["path"]
    evidence_path = symlink_root / relative
    outside = tmp_path / "outside-oracle.json"
    outside.write_bytes(evidence_path.read_bytes())
    evidence_path.unlink()
    evidence_path.symlink_to(outside)
    with pytest.raises(AccuracyMaintenanceError, match="traverses a symlink"):
        validate_maintenance_roster(roster, symlink_root)

    hardlink_root = tmp_path / "hardlink"
    roster = _draft(hardlink_root)
    relative = roster["tasks"][0]["truth"]["path"]
    evidence_path = hardlink_root / relative
    linked = hardlink_root / "evidence/hardlink-copy.json"
    os.link(evidence_path, linked)
    with pytest.raises(AccuracyMaintenanceError, match="hard-linked"):
        validate_maintenance_roster(roster, hardlink_root)

    drift_root = tmp_path / "drift"
    roster = _draft(drift_root)
    path = drift_root / roster["tasks"][0]["prompt"]["path"]
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(AccuracyMaintenanceError, match="hash drift"):
        validate_maintenance_roster(roster, drift_root)


def test_truth_oracle_and_bool_count_forgery_fail_closed(tmp_path: Path) -> None:
    truth_root = tmp_path / "truth"
    roster = _draft(truth_root)
    reference = roster["tasks"][0]["truth"]
    body = json.loads((truth_root / reference["path"]).read_text())
    body["expected_output_sha256"] = "sha256:" + "0" * 64
    _replace_json(truth_root, reference, body)
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="expected-output hash drift"):
        validate_maintenance_roster(roster, truth_root)

    oracle_root = tmp_path / "oracle"
    roster = _draft(oracle_root)
    reference = roster["tasks"][0]["oracle_receipt"]
    body = json.loads((oracle_root / reference["path"]).read_text())
    body["authority"] = "invented_oracle"
    _replace_json(oracle_root, reference, body)
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="authority registry drift"):
        validate_maintenance_roster(roster, oracle_root)

    count_root = tmp_path / "bool-count"
    roster = _draft(count_root)
    roster["counts"]["total"] = True
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="fixed schema violation"):
        validate_maintenance_roster(roster, count_root)


def test_unknown_fields_output_state_and_load_symlink_are_rejected(tmp_path: Path) -> None:
    roster = _draft(tmp_path)
    roster["invented"] = True
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="must contain exactly"):
        validate_maintenance_roster(roster, tmp_path)

    output_root = tmp_path / "output"
    roster = _draft(output_root)
    roster["model_outputs_observed"] = True
    _rehash(roster)
    with pytest.raises(AccuracyMaintenanceError, match="fixed schema violation"):
        validate_maintenance_roster(roster, output_root)

    roster_path = tmp_path / "pending.json"
    roster_path.write_text(json.dumps(_pending()), encoding="utf-8")
    assert load_maintenance_roster(roster_path) == _pending()
    link = tmp_path / "pending-link.json"
    link.symlink_to(roster_path)
    with pytest.raises(AccuracyMaintenanceError, match="must not be a symlink"):
        load_maintenance_roster(link)
