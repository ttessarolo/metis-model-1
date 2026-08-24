"""Declassified legacy W3 adapter retained behind a protected-broker STOP.

This adapter still implements the pre-capsule v2 oracle path.  Identity lookup
and evaluation therefore fail before registry, filesystem, or process access
until a separately protected broker and its external receipt consumer exist.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1.oracles import (
    ARTIFACT_ROOT,
    PINNED_METIS_REVISION,
    PINNED_METIS_TREE,
    RUNNER_PATH,
    OracleError,
    build_oracle_request,
    run_oracle,
    verify_oracle_envelope,
)
from metis_model1.provenance import canonical_json_bytes
from metis_model1.w3_oracles import (
    PRODUCTION_EXECUTION_PROFILE_SHA256,
    W3CandidateRejected,
    W3OracleInfrastructureError,
    W3OracleTrustError,
    canonical_hash,
    production_adapter_identity,
    production_execution_profile,
    required_predicates,
    valid_hash,
)
from metis_model1.w3_oracles import (
    _production_runtime_bindings_sha256 as _independent_runtime_bindings_sha256,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-semantic-spec.schema.json"
REGISTERED_W3_SEMANTIC_REGISTRY_SHA256: str | None = None
REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256: str | None = None


def _canonical_copy(value: Any, label: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise W3OracleTrustError(f"{label} is not canonical JSON") from error


def _require_external_production_receipts() -> None:
    if REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256 is None:
        raise W3OracleTrustError(
            "ProductionW3Adapter requires a protected execution broker and external receipts"
        )
    raise W3OracleTrustError("external protected-broker receipt consumption is not implemented")


def _registered_registry(raw: str) -> dict[str, Any]:
    if REGISTERED_W3_SEMANTIC_REGISTRY_SHA256 is None:
        raise W3OracleTrustError("W3 semantic registry authority is unset")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise W3OracleTrustError("W3 semantic registry is malformed JSON") from error
    registry = _canonical_copy(value, "W3 semantic registry")
    if not isinstance(registry, dict):
        raise W3OracleTrustError("W3 semantic registry must be an object")
    try:
        schema = json.loads(SEMANTIC_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise W3OracleTrustError("W3 semantic registry schema is unavailable") from error
    errors = sorted(
        Draft202012Validator(schema).iter_errors(registry), key=lambda item: list(item.path)
    )
    if errors:
        raise W3OracleTrustError(f"W3 semantic registry violates its schema: {errors[0].message}")
    body = {key: item for key, item in registry.items() if key != "manifest_sha256"}
    if registry["manifest_sha256"] != canonical_hash(body):
        raise W3OracleTrustError("W3 semantic registry manifest hash mismatch")
    if registry["manifest_sha256"] != REGISTERED_W3_SEMANTIC_REGISTRY_SHA256:
        raise W3OracleTrustError("W3 semantic registry does not match registered authority")
    specs = registry["specs"]
    candidate_ids = [spec["candidate_id"] for spec in specs]
    families = [spec["family"] for spec in specs]
    if candidate_ids != sorted(candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
        raise W3OracleTrustError("W3 semantic registry roster is not unique and ordered")
    if len(specs) != 3 or set(families) != {"F-1", "F-2", "F-3"}:
        raise W3OracleTrustError("W3 semantic registry must cover F-1/F-2/F-3 exactly")
    expected_counts = {
        "in": len(specs),
        "out": len(specs),
        "distinct": len(set(candidate_ids)),
        "gaps": 0,
    }
    if registry["counts"] != expected_counts:
        raise W3OracleTrustError("W3 semantic registry counts are not exact")
    contracts = {
        "F-1": "F-1-author",
        "F-2": "F-2-minimal-edit",
        "F-3": "F-3-diagnostic-repair",
    }
    for spec in specs:
        spec_body = {key: item for key, item in spec.items() if key != "spec_sha256"}
        if spec["spec_sha256"] != canonical_hash(spec_body):
            raise W3OracleTrustError("W3 semantic registry spec hash mismatch")
        if spec["semantic_spec_sha256"] != canonical_hash(spec["semantic_spec"]):
            raise W3OracleTrustError("W3 semantic registry semantic hash mismatch")
        if spec["semantic_spec"]["contract"] != contracts[spec["family"]]:
            raise W3OracleTrustError("W3 semantic registry family/contract mismatch")
    return registry


def _spec_for_candidate(registry: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict:
    matches = [
        spec for spec in registry["specs"] if spec["candidate_id"] == candidate.get("candidate_id")
    ]
    if len(matches) != 1:
        raise W3OracleTrustError("candidate has no unique registered semantic specification")
    spec = matches[0]
    expected = {
        "family": candidate.get("family"),
        "content_sha256": candidate.get("content_sha256"),
        "semantic_spec_sha256": candidate.get("semantic_spec_sha256"),
        "semantic_spec": candidate.get("semantic_spec"),
    }
    if any(spec[field] != value for field, value in expected.items()):
        raise W3OracleTrustError("candidate differs from its registered semantic specification")
    if not valid_hash(candidate.get("content_sha256")) or not valid_hash(
        candidate.get("semantic_spec_sha256")
    ):
        raise W3OracleTrustError("candidate content/semantic hashes are invalid")
    content_material = _candidate_content_material(candidate)
    if canonical_hash(content_material) != candidate["content_sha256"]:
        raise W3OracleTrustError("candidate content hash does not match its exact content")
    return spec


def _candidate_content_material(candidate: Mapping[str, Any]) -> dict[str, Any]:
    family = candidate.get("family")
    if family == "F-1":
        fields = ("request", "target_source")
    elif family == "F-2":
        fields = ("before_source", "after_source", "expected_delta")
    elif family == "F-3":
        fields = ("mutated_source", "expected_diagnostic", "fixed_source", "mutation_spec")
    else:
        raise W3OracleTrustError("candidate family is not supported by bridge-v1")
    if any(field not in candidate for field in fields):
        raise W3OracleTrustError("candidate content material is incomplete")
    return {field: candidate[field] for field in fields}


def _safe_artifact_namespace(value: str) -> Path:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 2
        or path.parts[0] != "w3-production"
    ):
        raise W3OracleTrustError("production artifact namespace is unsafe")
    return path


def _execution_receipt(
    *,
    candidate: Mapping[str, Any],
    candidate_sha256: str,
    identity_sha256: str,
    role: str,
    source: str,
    request: Mapping[str, Any],
    envelope: Mapping[str, Any],
    artifact_path: Path,
) -> dict[str, Any]:
    evidence = envelope["evidence"]
    try:
        artifact_bytes = artifact_path.read_bytes()
    except OSError as error:
        raise W3OracleTrustError("Oracle artifact was not materialized") from error
    if artifact_bytes != canonical_json_bytes(envelope):
        raise W3OracleTrustError("Oracle artifact differs from the verified envelope")
    body = {
        "schema_version": 1,
        "candidate_sha256": candidate_sha256,
        "adapter_identity_sha256": identity_sha256,
        "semantic_spec_sha256": candidate["semantic_spec_sha256"],
        "execution_profile_sha256": PRODUCTION_EXECUTION_PROFILE_SHA256,
        "family": candidate["family"],
        "role": role,
        "source_sha256": canonical_hash(source),
        "request": _canonical_copy(request, "Oracle request"),
        "envelope": _canonical_copy(envelope, "Oracle envelope"),
        "artifact_path": artifact_path.relative_to(PROJECT_ROOT).as_posix(),
        "artifact_sha256": "sha256:" + hashlib.sha256(artifact_bytes).hexdigest(),
        "result_sha256": canonical_hash(envelope["result"]),
        "diagnostics_sha256": evidence["diagnostics_sha256"],
        "ast_sha256": evidence["ast_sha256"],
        "ir_sha256": evidence["ir_sha256"],
        "runtime_sha256": evidence["runtime_sha256"],
        "runtime_identity": evidence["runtime_identity"],
        "metis_status_sha256": evidence["metis_status_sha256"],
    }
    return {**body, "receipt_sha256": canonical_hash(body)}


def _json_diff_paths(left: Any, right: Any, path: str = "") -> list[str]:
    """Return the exact leaf paths whose canonical JSON values differ."""

    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_json_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(left) or index >= len(right):
                paths.append(child)
            else:
                paths.extend(_json_diff_paths(left[index], right[index], child))
        return paths
    return [] if left == right else [path]


def _semantic_evidence(
    candidate: Mapping[str, Any],
    spec: Mapping[str, Any],
    executions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    family = candidate["family"]
    semantic_spec = spec["semantic_spec"]
    truth = semantic_spec["truth"]
    results = {role: receipt["envelope"]["result"] for role, receipt in executions.items()}
    expected_endpoint = truth["expected_endpoint"]
    if family == "F-1":
        result = results["author"]
        matched = (
            candidate["request"] == truth["request_exact"]
            and all(
                fragment in candidate["target_source"]
                for fragment in truth["required_source_fragments"]
            )
            and result["status"] == "ok"
            and result["endpoint"]["name"] == expected_endpoint
            and result["ir"]["value"] == truth["expected_ir"]
        )
        details = {
            "matched": matched,
            "contract": semantic_spec["contract"],
            "truth_sha256": canonical_hash(truth),
            "roles": ["author"],
        }
    elif family == "F-2":
        before = candidate["before_source"]
        after = candidate["after_source"]
        old_text = truth["old_text"]
        new_text = truth["new_text"]
        exact_edit = before.count(old_text) == truth["occurrences"] and after == before.replace(
            old_text, new_text, truth["occurrences"]
        )
        expected_delta = {"replace": {"old_text": old_text, "new_text": new_text}}
        before_ir = results["before"]["ir"]["value"]
        after_ir = results["after"]["ir"]["value"]
        matched = (
            exact_edit
            and candidate.get("expected_delta") == expected_delta
            and results["before"]["status"] == "ok"
            and results["after"]["status"] == "ok"
            and results["before"]["endpoint"]["name"] == expected_endpoint
            and results["after"]["endpoint"]["name"] == expected_endpoint
            and before_ir == truth["expected_before_ir"]
            and after_ir == truth["expected_after_ir"]
            and _json_diff_paths(before_ir, after_ir) == truth["expected_changed_paths"]
        )
        details = {
            "matched": matched,
            "minimal": exact_edit,
            "contract": semantic_spec["contract"],
            "truth_sha256": canonical_hash(truth),
            "roles": ["before", "after"],
        }
    else:
        mutated = results["mutated"]
        fixed = results["fixed"]
        expected_diagnostic = {
            "failure_kind": truth["expected_failure_kind"],
            "diagnostic_present": truth["expected_diagnostic_present"],
        }
        expected_mutation = {"operation": "remove", "fragment": truth["repair_fragment"]}
        exact_mutation = candidate["fixed_source"].count(
            truth["repair_fragment"]
        ) == 1 and candidate["mutated_source"] == candidate["fixed_source"].replace(
            truth["repair_fragment"], "", 1
        )
        matched = (
            mutated["status"] == "invalid"
            and mutated["failure"] == truth["expected_failure"]
            and mutated["diagnostics"] == truth["expected_diagnostics"]
            and fixed["status"] == "ok"
            and fixed["endpoint"]["name"] == expected_endpoint
            and fixed["ir"]["value"] == truth["expected_fixed_ir"]
            and truth["repair_fragment"] in candidate["fixed_source"]
            and candidate.get("expected_diagnostic") == expected_diagnostic
            and candidate.get("mutation_spec") == expected_mutation
            and exact_mutation
        )
        details = {
            "matched": matched,
            "repaired": matched,
            "contract": semantic_spec["contract"],
            "truth_sha256": canonical_hash(truth),
            "roles": ["mutated", "fixed"],
        }
    if details["matched"] is not True:
        raise W3CandidateRejected("candidate does not satisfy registered semantic truth")
    return details


@dataclass(frozen=True)
class ProductionW3Adapter:
    """Immutable local adapter whose state is included in identity authority."""

    semantic_registry_json: str
    metis_root: str
    runner_path: str = str(RUNNER_PATH)
    artifact_namespace: str = "w3-production/bridge-v1"

    def identity(self) -> Mapping[str, Any]:
        _require_external_production_receipts()
        registry = _registered_registry(self.semantic_registry_json)
        _safe_artifact_namespace(self.artifact_namespace)
        return production_adapter_identity(
            self,
            semantic_registry_sha256=registry["manifest_sha256"],
            runtime_bindings_sha256=_independent_runtime_bindings_sha256(self),
        )

    def evaluate(self, candidate: Mapping[str, Any]) -> Mapping[str, Any]:
        _require_external_production_receipts()
        canonical_candidate = _canonical_copy(dict(candidate), "candidate")
        if not isinstance(canonical_candidate, dict):
            raise W3OracleTrustError("candidate must be an object")
        registry = _registered_registry(self.semantic_registry_json)
        spec = _spec_for_candidate(registry, canonical_candidate)
        semantic_spec = spec["semantic_spec"]
        if semantic_spec["execution_mode"] != "endpoint":
            raise W3OracleTrustError(
                "bridge-v1 production specs must use endpoint mode; "
                "source mode is runner-qualified only"
            )
        namespace = _safe_artifact_namespace(self.artifact_namespace)
        identity_sha256 = canonical_hash(self.identity())
        candidate_sha256 = canonical_hash(canonical_candidate)
        profile = production_execution_profile()
        role_receipts: list[dict[str, Any]] = []
        by_role: dict[str, dict[str, Any]] = {}
        for role_contract in profile["roles"][canonical_candidate["family"]]:
            role = role_contract["role"]
            source = canonical_candidate[role_contract["source_field"]]
            request = build_oracle_request(
                source,
                filename=semantic_spec["filename"],
                execution_mode=semantic_spec["execution_mode"],
                endpoint=semantic_spec["endpoint"],
                workspace_sources=semantic_spec["workspace_sources"],
                revision=PINNED_METIS_REVISION,
                tree=PINNED_METIS_TREE,
            )
            artifact_path = (
                ARTIFACT_ROOT / namespace / canonical_candidate["candidate_id"] / f"{role}.json"
            )
            try:
                envelope = run_oracle(
                    source,
                    metis_root=self.metis_root,
                    runner_path=self.runner_path,
                    output_path=artifact_path,
                    filename=semantic_spec["filename"],
                    execution_mode=semantic_spec["execution_mode"],
                    endpoint=semantic_spec["endpoint"],
                    workspace_sources=semantic_spec["workspace_sources"],
                )
            except OracleError as error:
                raise W3OracleInfrastructureError(
                    f"registered Metis runner failed for role {role}"
                ) from error
            try:
                verify_oracle_envelope(envelope, request=request)
            except OracleError as error:
                raise W3OracleTrustError(
                    f"registered Metis envelope verification failed for role {role}"
                ) from error
            receipt = _execution_receipt(
                candidate=canonical_candidate,
                candidate_sha256=candidate_sha256,
                identity_sha256=identity_sha256,
                role=role,
                source=source,
                request=request,
                envelope=envelope,
                artifact_path=artifact_path,
            )
            role_receipts.append(receipt)
            by_role[role] = receipt
        semantic_details = _semantic_evidence(canonical_candidate, spec, by_role)
        family = canonical_candidate["family"]
        primary_role = {"F-1": "author", "F-2": "after", "F-3": "fixed"}[family]
        primary = by_role[primary_role]
        if primary["ir_sha256"] is None:
            raise W3OracleTrustError("production structural evidence requires compiled IR")
        bundle_body = {
            "schema_version": 2,
            "receipt_mode": "real-runner-envelopes",
            "candidate_sha256": candidate_sha256,
            "adapter_identity_sha256": identity_sha256,
            "semantic_registry_sha256": registry["manifest_sha256"],
            "semantic_spec_sha256": canonical_candidate["semantic_spec_sha256"],
            "execution_profile_sha256": PRODUCTION_EXECUTION_PROFILE_SHA256,
            "executions": role_receipts,
        }
        runtime_receipt = {
            **bundle_body,
            "runtime_receipt_sha256": canonical_hash(bundle_body),
        }
        evidence = {
            name: {
                "candidate_sha256": candidate_sha256,
                "details": {
                    "roles": [receipt["role"] for receipt in role_receipts],
                    "receipt_hashes": [receipt["receipt_sha256"] for receipt in role_receipts],
                },
            }
            for name in ("parse", "link", "validate", "compile")
        }
        evidence["semantic"] = {
            "candidate_sha256": candidate_sha256,
            "semantic_spec_sha256": canonical_candidate["semantic_spec_sha256"],
            "details": semantic_details,
        }
        if family == "F-2":
            evidence["patch_minimality"] = {
                "candidate_sha256": candidate_sha256,
                "before_sha256": canonical_hash(canonical_candidate["before_source"]),
                "after_sha256": canonical_hash(canonical_candidate["after_source"]),
                "delta_sha256": canonical_hash(canonical_candidate["expected_delta"]),
                "details": {"minimal": semantic_details["minimal"]},
            }
        if family == "F-3":
            evidence["diagnostic"] = {
                "candidate_sha256": candidate_sha256,
                "mutated_sha256": canonical_hash(canonical_candidate["mutated_source"]),
                "fixed_sha256": canonical_hash(canonical_candidate["fixed_source"]),
                "expected_diagnostic_sha256": canonical_hash(
                    canonical_candidate["expected_diagnostic"]
                ),
                "mutation_spec_sha256": canonical_hash(canonical_candidate["mutation_spec"]),
                "details": {"repaired": semantic_details["repaired"]},
            }
        evidence["ast"] = {
            "signature": primary["ast_sha256"],
            "evidence": {
                "candidate_sha256": candidate_sha256,
                "role": primary_role,
                "receipt_sha256": primary["receipt_sha256"],
            },
        }
        evidence["ir"] = {
            "signature": primary["ir_sha256"],
            "evidence": {
                "candidate_sha256": candidate_sha256,
                "role": primary_role,
                "receipt_sha256": primary["receipt_sha256"],
            },
        }
        evidence["binding"] = {
            "candidate_sha256": candidate_sha256,
            "content_sha256": canonical_candidate["content_sha256"],
            "semantic_spec_sha256": canonical_candidate["semantic_spec_sha256"],
        }
        return {
            "schema_version": 1,
            "status": "pass",
            "family": family,
            "candidate_sha256": candidate_sha256,
            "adapter_identity_sha256": identity_sha256,
            "receipt_mode": "real-runner-envelopes",
            "runtime_receipt": runtime_receipt,
            "predicates": {name: True for name in required_predicates(family)},
            "evidence": evidence,
        }


__all__ = [
    "ProductionW3Adapter",
    "REGISTERED_PROTECTED_EXECUTION_BROKER_SHA256",
    "REGISTERED_W3_SEMANTIC_REGISTRY_SHA256",
]
