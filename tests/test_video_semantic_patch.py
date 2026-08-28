from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantic_patch import (
    SemanticPatchError,
    render_candidate_patch,
    validate_candidate_patch,
    validate_patch_receipt,
)

COMMIT = "a" * 40
PREIMAGE = "sha256:" + "b" * 64


def _item(
    *,
    item_id: str = "sha256:" + "1" * 64,
    field: str = "visual.tone",
    means: str | None = "Descrive la proprietà visiva curata editorialmente.",
    aliases: list[str] | None = None,
    state: str = "draft",
) -> dict:
    return {
        "schema_version": 1,
        "work_item_id": item_id,
        "node_kind": "field",
        "canonical_locator": {
            "repository_commit": COMMIT,
            "path": "catalogs/video.metis",
            "catalog": "video",
            "field_path": field,
            "literal": None,
            "preimage_sha256": PREIMAGE,
        },
        "technical": {
            "type": "keyword",
            "modifiers": ["multi"],
            "domain_kind": "enum",
            "declared_cardinality": None,
            "observed_cardinality": 2,
        },
        "candidate": {"means": means, "aka": aliases or [], "review_state": state},
        "editorial_rules": {
            "include_when": [],
            "exclude_when": [],
            "scope": ["video"],
            "dependencies": [],
            "constraint_gaps": [],
        },
        "evidence_refs": ["manual-page-1"],
        "ambiguities": [],
        "author": "frontier-run-1",
        "reviewer": None,
    }


def _roster(*, preimage: str = PREIMAGE, order: int = 4) -> list[dict]:
    return [
        {
            "canonical_locator": {
                "repository_commit": COMMIT,
                "path": "catalogs/video.metis",
                "catalog": "video",
                "field_path": "visual.tone",
                "literal": None,
                "preimage_sha256": preimage,
            },
            "technical": {
                "type": "keyword",
                "modifiers": ["multi"],
                "domain_kind": "enum",
                "declared_cardinality": None,
                "observed_cardinality": 2,
            },
            "order": order,
        }
    ]


def test_renderer_copies_technical_preimage_and_emits_only_draft() -> None:
    patch = render_candidate_patch([_item()], _roster(), repository_commit=COMMIT)
    operation = patch["operations"][0]
    assert operation["technical"] == _roster()[0]["technical"]
    assert operation["canonical_locator"]["preimage_sha256"] == PREIMAGE
    assert operation["order"] == 4
    assert operation["semantic"]["review_state"] == "draft"
    assert operation["grammar"].startswith("means draft ")
    assert (
        validate_candidate_patch(patch, technical_roster=_roster(), repository_commit=COMMIT) == []
    )
    assert validate_patch_receipt(patch["receipt"]) == []
    assert patch["receipt"]["counts"] == {
        "items_in": 1,
        "items_out": 1,
        "items_distinct": 1,
        "items_gaps": 0,
    }


def test_renderer_orders_operations_by_technical_roster_not_input_order() -> None:
    first = _item(item_id="sha256:" + "1" * 64)
    second = _item(item_id="sha256:" + "2" * 64, field="editorial.label")
    roster = [
        _roster(order=8)[0],
        {
            **_roster(order=2)[0],
            "canonical_locator": {
                **_roster(order=2)[0]["canonical_locator"],
                "field_path": "editorial.label",
            },
        },
    ]
    patch = render_candidate_patch([first, second], roster, repository_commit=COMMIT)
    assert [operation["order"] for operation in patch["operations"]] == [2, 8]


def test_alias_requires_out_of_band_evidence_bound_to_work_item_refs() -> None:
    item = _item(aliases=["monocromatico"])
    with pytest.raises(SemanticPatchError, match="aka without explicit evidence"):
        render_candidate_patch([item], _roster(), repository_commit=COMMIT)
    with pytest.raises(SemanticPatchError, match="outside evidence_refs"):
        render_candidate_patch(
            [item],
            _roster(),
            repository_commit=COMMIT,
            aka_evidence={item["work_item_id"]: ["other-page-2"]},
        )
    patch = render_candidate_patch(
        [item],
        _roster(),
        repository_commit=COMMIT,
        aka_evidence={item["work_item_id"]: ["manual-page-1"]},
    )
    assert patch["operations"][0]["semantic"]["aka"] == ["monocromatico"]


@pytest.mark.parametrize("state", ["reviewed", "unannotated"])
def test_renderer_rejects_review_promotion_or_missing_draft(state: str) -> None:
    with pytest.raises(SemanticPatchError, match="promote|unannotated"):
        render_candidate_patch([_item(state=state)], _roster(), repository_commit=COMMIT)


def test_renderer_rejects_preimage_drift_and_technical_mutation() -> None:
    with pytest.raises(SemanticPatchError, match="preimage"):
        render_candidate_patch(
            [_item()], _roster(preimage="sha256:" + "c" * 64), repository_commit=COMMIT
        )
    item = _item()
    item["technical"]["domain_kind"] = "open"
    with pytest.raises(SemanticPatchError, match="technical invariants"):
        render_candidate_patch([item], _roster(), repository_commit=COMMIT)


def test_renderer_rejects_duplicate_targets_and_raw_fields() -> None:
    item = _item()
    with pytest.raises(SemanticPatchError, match="duplicate work item IDs"):
        render_candidate_patch([item, deepcopy(item)], _roster(), repository_commit=COMMIT)
    raw = _item()
    raw["source_text"] = "must never enter a work item"
    with pytest.raises(SemanticPatchError, match="forbidden"):
        render_candidate_patch([raw], _roster(), repository_commit=COMMIT)


def test_validator_catches_tampered_semantics_or_receipt() -> None:
    patch = render_candidate_patch([_item()], _roster(), repository_commit=COMMIT)
    patch["operations"][0]["semantic"]["means"] = "tampered"
    assert validate_candidate_patch(patch)
    clean = render_candidate_patch([_item()], _roster(), repository_commit=COMMIT)
    clean["receipt"]["counts"]["items_out"] = 3
    assert validate_candidate_patch(clean)


def test_validator_rejects_rehashed_sensitive_semantic_values() -> None:
    patch = render_candidate_patch([_item()], _roster(), repository_commit=COMMIT)
    patch["operations"][0]["semantic"]["means"] = "password: leaked"
    patch["operations"][0]["grammar"] = 'means draft "password: leaked"'
    patch["patch_sha256"] = "sha256:" + canonical_json_hash(
        {
            key: patch[key]
            for key in ("schema_version", "contract_id", "repository_commit", "operations")
        }
    )
    patch["receipt"]["patch_sha256"] = patch["patch_sha256"]
    receipt_body = {
        key: patch["receipt"][key]
        for key in ("schema_version", "contract_id", "patch_sha256", "counts", "payload_redacted")
    }
    patch["receipt"]["receipt_sha256"] = "sha256:" + canonical_json_hash(receipt_body)
    assert validate_candidate_patch(patch, technical_roster=_roster(), repository_commit=COMMIT)


def test_renderer_rejects_unsupported_list_entry_kind() -> None:
    item = _item()
    item["node_kind"] = "list_entry"
    with pytest.raises(SemanticPatchError, match="unsupported"):
        render_candidate_patch([item], _roster(), repository_commit=COMMIT)


def test_validator_rejects_rehashed_list_entry_operation() -> None:
    patch = render_candidate_patch([_item()], _roster(), repository_commit=COMMIT)
    patch["operations"][0]["node_kind"] = "list_entry"
    patch["patch_sha256"] = "sha256:" + canonical_json_hash(
        {
            key: patch[key]
            for key in ("schema_version", "contract_id", "repository_commit", "operations")
        }
    )
    patch["receipt"]["patch_sha256"] = patch["patch_sha256"]
    receipt_body = {
        key: patch["receipt"][key]
        for key in ("schema_version", "contract_id", "patch_sha256", "counts", "payload_redacted")
    }
    patch["receipt"]["receipt_sha256"] = "sha256:" + canonical_json_hash(receipt_body)
    assert validate_candidate_patch(patch, technical_roster=_roster(), repository_commit=COMMIT)
