from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_catalog_projection import PROJECTION_CONTRACT
from metis_model1.video_semantic_index import (
    SemanticIndexError,
    build_semantic_index,
    canonical_index_bytes,
    cas_replace_index,
    index_revision,
    rollback_index,
    validate_semantic_index,
    validate_semantic_index_receipt,
)

REV = "sha256:" + "1" * 64
GRAMMAR = "sha256:" + "2" * 64
TOOLCHAIN = "sha256:" + "3" * 64


def _semantic(
    state: str, line: int, *, means: str | None = None, aka: list[str] | None = None
) -> dict:
    result = {"state": state, "at": {"file": "catalogs/video.metis", "line": line}}
    if means is not None:
        result["means"] = {"text": means, "at": {"file": "catalogs/video.metis", "line": line + 1}}
    if aka is not None:
        result["aka"] = {"items": aka, "at": {"file": "catalogs/video.metis", "line": line + 2}}
    return result


def _projection(*, second_catalog: bool = False) -> dict:
    catalog = {
        "name": "public.video",
        "driver": "opensearch",
        "file": "catalogs/video.metis",
        "fields": [
            {
                "name": "genre",
                "type": "keyword",
                "modifiers": [],
                "domain": {
                    "kind": "enum",
                    "size": 1,
                    "nature": "editorial",
                    "values": [
                        {
                            "literal": "Film",
                            "semantic": _semantic("reviewed", 12, means="film"),
                        }
                    ],
                },
                "semantic": _semantic("reviewed", 10, means="genere", aka=["categoria"]),
            },
            {
                "name": "title",
                "type": "keyword",
                "modifiers": [],
                "domain": {"kind": "open"},
                "semantic": _semantic("unannotated", 20),
            },
            {
                "name": "plot",
                "type": "keyword",
                "modifiers": [],
                "domain": {"kind": "none"},
                "semantic": _semantic("draft", 30, means="trama"),
            },
        ],
        "semantic": _semantic("reviewed", 2, means="contenuti video"),
    }
    catalogs = [catalog]
    if second_catalog:
        other = deepcopy(catalog)
        other["name"] = "public.people"
        other["fields"][0]["name"] = "name"
        catalogs.append(other)
    return {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "demo",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": catalogs,
    }


def _build(*, second_catalog: bool = False) -> dict:
    return build_semantic_index(
        _projection(second_catalog=second_catalog),
        semantic_source_revision=REV,
        grammar_revision=GRAMMAR,
        toolchain_revision=TOOLCHAIN,
        tenant_snapshot={"snapshot_id": "snapshot-001", "membership_sha256": REV},
    )


def test_index_is_canonical_complete_and_open_domains_are_lazy() -> None:
    result = _build()
    index = result["index"]
    assert canonical_index_bytes(index) == canonical_index_bytes(deepcopy(index))
    assert index["revision"] == index_revision(index)
    assert validate_semantic_index(index) == []
    assert result["receipt"]["counts"] == {
        "entries_in": 5,
        "entries_out": 5,
        "entries_distinct": 5,
        "entries_gaps": 0,
        "catalogs": 1,
        "fields": 3,
        "values": 1,
    }
    title = next(item for item in index["entries"] if item["field"] == "title")
    assert title["domain"] == {"kind": "open"}
    assert not any(item.get("literal") for item in index["entries"] if item["field"] == "title")
    assert validate_semantic_index(result["index"]) == []
    assert validate_semantic_index_receipt(result["receipt"]) == []


def test_index_receipt_rejects_unknown_fields_and_false_redaction() -> None:
    receipt = _build()["receipt"]
    attacked = deepcopy(receipt)
    attacked["values_redacted"] = False
    assert validate_semantic_index_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["content"] = "synthetic-unapproved-content"
    assert validate_semantic_index_receipt(attacked)


@pytest.mark.parametrize("mutation", ["snapshot", "annotation", "open_value", "duplicate"])
def test_index_rejects_membership_or_annotation_incoherence(mutation: str) -> None:
    projection = _projection()
    if mutation == "snapshot":
        with pytest.raises(SemanticIndexError, match="snapshot"):
            build_semantic_index(
                projection,
                semantic_source_revision=REV,
                grammar_revision=GRAMMAR,
                toolchain_revision=TOOLCHAIN,
                tenant_snapshot={},
            )
        return
    if mutation == "annotation":
        del projection["catalogs"][0]["fields"][0]["domain"]["values"][0]["semantic"]
    elif mutation == "open_value":
        projection["catalogs"][0]["fields"][1]["domain"] = {"kind": "open", "values": ["x"]}
    else:
        projection["catalogs"].append(deepcopy(projection["catalogs"][0]))
    with pytest.raises(SemanticIndexError):
        build_semantic_index(
            projection,
            semantic_source_revision=REV,
            grammar_revision=GRAMMAR,
            toolchain_revision=TOOLCHAIN,
            tenant_snapshot="snapshot-001",
        )


def test_cas_replacement_stale_detection_and_rollback() -> None:
    first = _build()["index"]
    second = _build(second_catalog=True)["index"]
    transaction = cas_replace_index(first, second, expected_revision=first["revision"])
    assert transaction["index"]["revision"] == second["revision"]
    with pytest.raises(SemanticIndexError, match="stale"):
        cas_replace_index(first, second, expected_revision="sha256:" + "f" * 64)
    restored = rollback_index(
        transaction["index"], transaction["transaction"], expected_revision=second["revision"]
    )
    assert restored["index"]["revision"] == first["revision"]
    tampered = deepcopy(transaction["transaction"])
    tampered["preimage"]["entries"].reverse()
    with pytest.raises(SemanticIndexError, match="preimage"):
        rollback_index(transaction["index"], tampered, expected_revision=second["revision"])
