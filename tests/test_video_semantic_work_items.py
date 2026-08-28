from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_catalog_projection import PROJECTION_CONTRACT
from metis_model1.video_local_census import build_local_census
from metis_model1.video_semantic_patch import render_candidate_patch, validate_candidate_patch
from metis_model1.video_semantic_work_items import (
    VideoSemanticWorkItemError,
    build_video_semantic_work_items,
)
from metis_model1.video_semantics_contracts import validate_work_item

COMMIT = "a" * 40
CATALOG_PREIMAGE = "sha256:" + "b" * 64
VALUES_PREIMAGE = "sha256:" + "c" * 64
REVISION = "sha256:" + "d" * 64
PREIMAGES = {
    "catalogs/video.metis": CATALOG_PREIMAGE,
    "catalogs/video.values.metis": VALUES_PREIMAGE,
}


def _semantic(state: str, path: str, line: int) -> dict:
    return {"state": state, "at": {"file": path, "line": line}}


def _projection() -> dict:
    catalog_path = "catalogs/video.metis"
    values_path = "catalogs/video.values.metis"
    return {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "demo",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "demo.video",
                "driver": "opensearch",
                "file": catalog_path,
                "semantic": _semantic("unannotated", catalog_path, 1),
                "fields": [
                    {
                        "name": "title",
                        "type": "text",
                        "modifiers": ["required"],
                        "semantic": _semantic("unannotated", catalog_path, 3),
                        "domain": {"kind": "open"},
                    },
                    {
                        "name": "genre",
                        "type": "keyword",
                        "modifiers": ["multi"],
                        "semantic": _semantic("unannotated", catalog_path, 4),
                        "domain": {
                            "kind": "enum",
                            "size": 2,
                            "nature": "reflected",
                            "values": [
                                {
                                    "literal": "Drama",
                                    "semantic": _semantic("unannotated", values_path, 2),
                                },
                                {
                                    "literal": "Comedy",
                                    "semantic": _semantic("unannotated", values_path, 2),
                                },
                            ],
                        },
                    },
                ],
            }
        ],
    }


def _rules() -> dict:
    return {
        "include_when": ["Use only when the evidence establishes this meaning."],
        "exclude_when": [],
        "scope": ["video"],
        "dependencies": [],
        "constraint_gaps": [],
    }


def _proposal(
    field: str,
    literal: str | None,
    *,
    means: str = "Descrizione editoriale candidata.",
    aliases: list[str] | None = None,
) -> dict:
    evidence = ["reserved-unit-001"]
    return {
        "target": {"catalog": "demo.video", "field": field, "literal": literal},
        "means": means,
        "aka": aliases or [],
        "aka_evidence_refs": evidence if aliases else [],
        "evidence_refs": evidence,
        "editorial_rules": _rules(),
        "ambiguities": [],
        "author": "frontier-run-001",
        "reviewer": None,
    }


def _technical_metadata(roster: list[dict]) -> list[dict]:
    return [
        {
            "target": {
                "catalog": item["canonical_locator"]["catalog"],
                "field": item["canonical_locator"]["field_path"],
                "literal": item["canonical_locator"]["literal"],
            },
            "repository_commit": item["canonical_locator"]["repository_commit"],
            "path": item["canonical_locator"]["path"],
            "preimage_sha256": item["canonical_locator"]["preimage_sha256"],
            "technical": deepcopy(item["technical"]),
        }
        for item in roster
    ]


def _build(proposals=None, **kwargs):
    return build_video_semantic_work_items(
        _projection(),
        proposals
        or [
            _proposal("genre", "Drama", aliases=["drammatico"]),
            _proposal("title", None),
        ],
        repository_commit=COMMIT,
        source_preimages=PREIMAGES,
        **kwargs,
    )


def test_projection_materialization_is_ordered_schema_valid_and_patch_ready() -> None:
    bundle = _build()
    assert len(bundle["technical_roster"]) == 5
    assert [item["canonical_locator"]["field_path"] for item in bundle["work_items"]] == [
        "title",
        "genre",
    ]
    assert all(validate_work_item(item) == [] for item in bundle["work_items"])
    title, drama = bundle["work_items"]
    assert title["technical"] == {
        "type": "text",
        "modifiers": ["required"],
        "domain_kind": "open",
        "declared_cardinality": None,
        "observed_cardinality": None,
    }
    assert drama["technical"] == {
        "type": "keyword",
        "modifiers": ["multi"],
        "domain_kind": "enum",
        "declared_cardinality": 2,
        "observed_cardinality": 2,
    }
    assert drama["canonical_locator"]["path"] == "catalogs/video.values.metis"
    assert drama["canonical_locator"]["preimage_sha256"] == VALUES_PREIMAGE
    assert bundle["aka_evidence"] == {drama["work_item_id"]: ["reserved-unit-001"]}

    patch = render_candidate_patch(
        bundle["work_items"],
        bundle["technical_roster"],
        repository_commit=COMMIT,
        aka_evidence=bundle["aka_evidence"],
    )
    assert (
        validate_candidate_patch(
            patch,
            technical_roster=bundle["technical_roster"],
            repository_commit=COMMIT,
        )
        == []
    )


def test_mapping_input_and_proposal_order_do_not_change_materialization() -> None:
    first = _proposal("genre", "Comedy")
    second = _proposal("title", None)
    sequence = _build([first, second])
    mapping = _build({"later": second, "earlier": first})
    assert sequence == mapping


def test_local_census_requires_complete_exact_technical_metadata() -> None:
    projection_bundle = _build([_proposal("genre", "Drama")])
    census = build_local_census(_projection(), semantic_source_revision=REVISION)
    metadata = _technical_metadata(projection_bundle["technical_roster"])
    from_census = build_video_semantic_work_items(
        census,
        [_proposal("genre", "Drama")],
        repository_commit=COMMIT,
        source_preimages=PREIMAGES,
        technical_metadata=metadata,
    )
    assert from_census == projection_bundle

    with pytest.raises(VideoSemanticWorkItemError, match="technical_metadata is required"):
        build_video_semantic_work_items(
            census,
            [_proposal("genre", "Drama")],
            repository_commit=COMMIT,
            source_preimages=PREIMAGES,
        )
    with pytest.raises(VideoSemanticWorkItemError, match="roster differs"):
        build_video_semantic_work_items(
            census,
            [_proposal("genre", "Drama")],
            repository_commit=COMMIT,
            source_preimages=PREIMAGES,
            technical_metadata=metadata[:-1],
        )


def test_targets_must_resolve_once_and_duplicate_targets_are_rejected() -> None:
    with pytest.raises(VideoSemanticWorkItemError, match="exactly one"):
        _build([_proposal("missing", None)])
    duplicate = _proposal("title", None)
    with pytest.raises(VideoSemanticWorkItemError, match="duplicate targets"):
        _build([duplicate, deepcopy(duplicate)])
    malformed = _proposal("title", None)
    malformed["target"]["literal"] = "not-a-field"
    with pytest.raises(VideoSemanticWorkItemError, match="exactly one"):
        _build([malformed])


def test_alias_requires_separate_explicit_evidence_inside_evidence_roster() -> None:
    proposal = _proposal("genre", "Drama", aliases=["drammatico"])
    proposal["aka_evidence_refs"] = []
    with pytest.raises(VideoSemanticWorkItemError, match="aka without explicit evidence"):
        _build([proposal])
    proposal["aka_evidence_refs"] = ["other-unit-002"]
    with pytest.raises(VideoSemanticWorkItemError, match="outside evidence_refs"):
        _build([proposal])


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda records: records[0].update(repository_commit="e" * 40), "commit drift"),
        (lambda records: records[0].update(path="catalogs/other.metis"), "path/preimage drift"),
        (
            lambda records: records[0].update(preimage_sha256="sha256:" + "e" * 64),
            "path/preimage drift",
        ),
        (
            lambda records: records[1]["technical"].update(type="keyword"),
            "changes projection invariants",
        ),
        (
            lambda records: records[1]["technical"].update(domain_kind="none"),
            "changes projection invariants",
        ),
        (
            lambda records: records[1]["technical"].update(modifiers=[]),
            "changes projection invariants",
        ),
        (
            lambda records: records[1]["technical"].update(observed_cardinality=99),
            "changes projection invariants",
        ),
    ],
)
def test_supplied_projection_metadata_cannot_drift_or_change_invariants(
    mutation, message: str
) -> None:
    baseline = _build([_proposal("title", None)])
    records = _technical_metadata(baseline["technical_roster"])
    mutation(records)
    with pytest.raises(VideoSemanticWorkItemError, match=message):
        _build([_proposal("title", None)], technical_metadata=records)


def test_closed_inputs_reject_unknown_technical_mutation_and_raw_material() -> None:
    baseline = _build([_proposal("title", None)])
    records = _technical_metadata(baseline["technical_roster"])
    records[0]["technical"]["new_literal"] = "mutated"
    with pytest.raises(VideoSemanticWorkItemError, match="technical keys"):
        _build([_proposal("title", None)], technical_metadata=records)

    proposal = _proposal("title", None)
    proposal["type"] = "keyword"
    with pytest.raises(VideoSemanticWorkItemError, match="unknown or missing fields"):
        _build([proposal])

    proposal = _proposal("title", None)
    proposal["editorial_rules"]["source_text"] = "reserved raw payload"
    with pytest.raises(VideoSemanticWorkItemError, match="forbidden raw/sensitive"):
        _build([proposal])


def test_preimage_roster_and_census_receipt_are_fail_closed() -> None:
    missing = {"catalogs/video.metis": CATALOG_PREIMAGE}
    with pytest.raises(VideoSemanticWorkItemError, match="preimage roster"):
        build_video_semantic_work_items(
            _projection(),
            [_proposal("title", None)],
            repository_commit=COMMIT,
            source_preimages=missing,
        )
    extra = {**PREIMAGES, "catalogs/extra.metis": "sha256:" + "e" * 64}
    with pytest.raises(VideoSemanticWorkItemError, match="preimage roster"):
        build_video_semantic_work_items(
            _projection(),
            [_proposal("title", None)],
            repository_commit=COMMIT,
            source_preimages=extra,
        )

    census = build_local_census(_projection(), semantic_source_revision=REVISION)
    metadata = _technical_metadata(_build()["technical_roster"])
    census["roster"].reverse()
    with pytest.raises(VideoSemanticWorkItemError, match="roster differs"):
        build_video_semantic_work_items(
            census,
            [_proposal("title", None)],
            repository_commit=COMMIT,
            source_preimages=PREIMAGES,
            technical_metadata=metadata,
        )
