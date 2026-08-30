"""Executable contract for reviewed semantic equivalence groups.

This file locks the production resolver contract.  A repeated reviewed ``aka``
is an OR-group only when every member is in one catalog and field and the
proposed roster is complete.  Draft, cross-field, omitted, and extra members
remain non-executable.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_brain_grounding_v2 import (
    BrainGroundingV2Error,
    adjudicate_grounding_proposal_v2,
    build_brain_semantic_context_v2,
)
from metis_model1.video_catalog_projection import PROJECTION_CONTRACT
from metis_model1.video_local_census import build_local_census
from metis_model1.video_semantic_crosswalk import build_preliminary_crosswalk
from metis_model1.video_semantic_index import build_semantic_index, resolve_grounding
from metis_model1.video_semantic_index_v2 import (
    build_semantic_index_v2,
    constraint_ledger_revision,
)
from metis_model1.video_semantics_contracts import semantic_concept_id

REVISION = "sha256:" + "1" * 64
GRAMMAR_REVISION = "sha256:" + "2" * 64
TOOLCHAIN_REVISION = "sha256:" + "3" * 64
CONSTRAINT_ID = "sha256:" + "4" * 64


def _hash(value: object) -> str:
    return "sha256:" + canonical_json_hash(value)


def _semantic(
    state: str,
    line: int,
    *,
    means: str | None = None,
    aka: Iterable[str] = (),
    source_file: str = "catalogs/video.metis",
) -> dict:
    result = {"state": state, "at": {"file": source_file, "line": line}}
    if means is not None:
        result["means"] = {
            "text": means,
            "at": {"file": source_file, "line": line + 1},
        }
    aliases = list(aka)
    if aliases:
        result["aka"] = {
            "items": aliases,
            "at": {"file": source_file, "line": line + 2},
        }
    return result


def _v1_projection(fields: list[dict]) -> dict:
    return {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "public-synthetic",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "public.video",
                "driver": "opensearch",
                "file": "catalogs/video.metis",
                "semantic": _semantic("reviewed", 2, means="contenuti video"),
                "fields": fields,
            }
        ],
    }


def _field(
    name: str,
    values: list[tuple[str, str, list[str]]],
    line: int,
    *,
    source_file: str = "catalogs/video.metis",
) -> dict:
    return {
        "name": name,
        "type": "keyword",
        "modifiers": [],
        "semantic": _semantic("reviewed", line, means=f"campo {name}", source_file=source_file),
        "domain": {
            "kind": "enum",
            "size": len(values),
            "nature": "editorial",
            "values": [
                {
                    "literal": literal,
                    "semantic": _semantic(
                        state,
                        line + offset,
                        means=meaning,
                        aka=aliases,
                        source_file=source_file,
                    ),
                }
                for offset, (literal, state, aliases) in enumerate(values, start=1)
                for meaning in [f"valore {literal}"]
            ],
        },
    }


def _v1_index(fields: list[dict]) -> dict:
    return build_semantic_index(
        _v1_projection(fields),
        semantic_source_revision=REVISION,
        grammar_revision=GRAMMAR_REVISION,
        toolchain_revision=TOOLCHAIN_REVISION,
        tenant_snapshot={"snapshot_id": "snapshot-001", "membership_sha256": REVISION},
    )["index"]


@pytest.mark.parametrize(
    ("field", "phrase", "values"),
    [
        (
            "paesiorigine",
            "prodotto in Italia",
            [
                ("Italia", "reviewed", ["prodotto in Italia"]),
                ("ITALIA", "reviewed", ["prodotto in Italia"]),
            ],
        ),
        (
            "paesiorigine",
            "prodotti in Italia",
            [
                ("Italia", "reviewed", ["prodotti in Italia"]),
                ("ITALIA", "reviewed", ["prodotti in Italia"]),
            ],
        ),
        (
            "paesiorigine",
            "prodotti negli Stati Uniti d'America",
            [
                ("USA", "reviewed", ["prodotti negli Stati Uniti d'America"]),
                (
                    "STATI UNITI D AMERICA",
                    "reviewed",
                    ["prodotti negli Stati Uniti d'America"],
                ),
            ],
        ),
        (
            "subtitle_language",
            "sottotitoli inglesi",
            [
                ("ENG", "reviewed", ["sottotitoli inglesi"]),
                ("eng", "reviewed", ["sottotitoli inglesi"]),
            ],
        ),
    ],
)
def test_v1_repeated_reviewed_aka_resolves_one_complete_or_group(
    field: str, phrase: str, values: list[tuple[str, str, list[str]]]
) -> None:
    index = _v1_index([_field(field, values, 10)])

    grounding = resolve_grounding(index, phrase)

    assert grounding["status"] == "resolved"
    assert len(grounding["selections"]) == 1
    selection = grounding["selections"][0]
    assert selection["field"] == field
    assert selection["literal"] is None
    assert selection["literals"] == sorted(value[0] for value in values)
    assert selection["value_mode"] == "any_of"
    assert selection["matched_by"] == "reviewed_aka_group"


def test_v1_incomplete_group_fails_closed_when_a_member_is_draft() -> None:
    index = _v1_index(
        [
            _field(
                "paesiorigine",
                [
                    ("Italia", "reviewed", ["prodotto in Italia"]),
                    ("ITALIA", "reviewed", ["prodotto in Italia"]),
                    ("Italy legacy", "draft", ["prodotto in Italia"]),
                ],
                10,
            )
        ]
    )

    grounding = resolve_grounding(index, "prodotto in Italia")

    assert grounding["status"] in {"clarify", "unsupported"}
    assert grounding["selections"] == []
    assert "Italy legacy" not in str(grounding)


def test_v1_draft_storage_artifact_without_alias_does_not_poison_reviewed_group() -> None:
    index = _v1_index(
        [
            _field(
                "paesiorigine",
                [
                    ("ITALIA", "reviewed", ["prodotti in Italia"]),
                    ("Italia", "reviewed", ["prodotti in Italia"]),
                    ("italia", "reviewed", ["prodotti in Italia"]),
                    ("val ITALIA val", "draft", []),
                ],
                10,
            )
        ]
    )

    grounding = resolve_grounding(index, "prodotti in Italia")

    assert grounding["status"] == "resolved"
    assert len(grounding["selections"]) == 1
    assert grounding["selections"][0]["literals"] == ["ITALIA", "Italia", "italia"]
    assert "val ITALIA val" not in str(grounding)


def test_v1_cross_field_repeated_aka_fails_closed() -> None:
    index = _v1_index(
        [
            _field(
                "paesiorigine",
                [("Italia", "reviewed", ["prodotto in Italia"])],
                10,
            ),
            _field(
                "subtitle_language",
                [("Italia", "reviewed", ["prodotto in Italia"])],
                20,
            ),
        ]
    )

    grounding = resolve_grounding(index, "prodotto in Italia")

    assert grounding["status"] == "clarify"
    assert grounding["selections"] == []


def test_v1_group_cannot_escape_explicit_catalog_scope() -> None:
    projection = _v1_projection([_field("tipologia", [("Film", "reviewed", [])], 10)])
    projection["catalogs"].append(
        {
            "name": "public.users",
            "driver": "opensearch",
            "file": "catalogs/users.metis",
            "semantic": _semantic(
                "reviewed", 30, means="utenti", source_file="catalogs/users.metis"
            ),
            "fields": [
                _field(
                    "country",
                    [
                        ("Italia", "reviewed", ["residenti in Italia"]),
                        ("IT", "reviewed", ["residenti in Italia"]),
                    ],
                    40,
                    source_file="catalogs/users.metis",
                )
            ],
        }
    )
    index = build_semantic_index(
        projection,
        semantic_source_revision=REVISION,
        grammar_revision=GRAMMAR_REVISION,
        toolchain_revision=TOOLCHAIN_REVISION,
        tenant_snapshot={"snapshot_id": "snapshot-001", "membership_sha256": REVISION},
    )["index"]

    grounding = resolve_grounding(index, "residenti in Italia", catalog="public.video")

    assert grounding["status"] == "unsupported"
    assert grounding["selections"] == []


def test_v1_disjoint_groups_and_singleton_resolve_in_one_request() -> None:
    index = _v1_index(
        [
            _field(
                "paesiorigine",
                [
                    ("Italia", "reviewed", ["prodotti in Italia"]),
                    ("ITALIA", "reviewed", ["prodotti in Italia"]),
                ],
                10,
            ),
            _field(
                "audio_language",
                [("ita", "reviewed", ["audio in italiano"])],
                20,
            ),
            _field(
                "subtitle_language",
                [
                    ("ENG", "reviewed", ["sottotitoli inglesi"]),
                    ("eng", "reviewed", ["sottotitoli inglesi"]),
                ],
                30,
            ),
        ]
    )

    grounding = resolve_grounding(
        index,
        "prodotti in Italia con audio in italiano e sottotitoli inglesi",
    )

    assert grounding["status"] == "resolved"
    assert [item["field"] for item in grounding["selections"]] == [
        "paesiorigine",
        "audio_language",
        "subtitle_language",
    ]
    assert grounding["selections"][0]["literals"] == ["ITALIA", "Italia"]
    assert grounding["selections"][1]["literal"] == "ita"
    assert grounding["selections"][2]["literals"] == ["ENG", "eng"]


def _concept(label: str, source_locator: str) -> dict:
    concept = {
        "schema_version": 1,
        "concept_id": "",
        "editorial_source_ref": "approved-source-a",
        "source_locator": source_locator,
        "editorial_variant": "shared",
        "scope": ["content"],
        "source_label": label,
        "definition": f"Definition of {label}",
        "include_when": [f"include {label}"],
        "exclude_when": [f"exclude {label}"],
        "cardinality": {"kind": "one", "min": 0, "max": 1},
        "parents": [],
        "children": [],
        "dependencies": [],
        "exclusive_with": [],
        "examples": [],
        "source_quality": "explicit",
        "notes": [],
        "review_state": "reviewed",
    }
    concept["concept_id"] = semantic_concept_id(concept)
    return concept


def _constraint_ledger(fields: list[str]) -> dict:
    ledger = {
        "schema_version": 1,
        "constraint_revision": "sha256:" + "0" * 64,
        "constraints": [
            {
                "constraint_id": CONSTRAINT_ID,
                "rule": "Apply one reviewed semantic equivalence group per clause.",
                "fields": fields,
                "grammar_expressed": True,
                "validator_verifiable": True,
                "editorial_oracle": True,
                "brain_behavior": "apply",
                "future_grammar_decision": None,
                "evidence_refs": ["approved-source-a:constraint-1"],
                "review_state": "reviewed",
            }
        ],
    }
    ledger["constraint_revision"] = constraint_ledger_revision(ledger)
    return ledger


def _v2_bundle(*, include_draft: bool = True, include_cross_field_alias: bool = False) -> dict:
    fields = [
        _field(
            "paesiorigine",
            [
                ("Italia", "reviewed", ["prodotto in Italia"]),
                ("ITALIA", "reviewed", ["prodotto in Italia"]),
                *([("Italy legacy", "draft", ["prodotto in Italia"])] if include_draft else []),
                ("Italy", "reviewed", []),
            ],
            10,
        ),
        _field(
            "subtitle_language",
            [
                ("ENG", "reviewed", ["sottotitoli inglesi"]),
                ("eng", "reviewed", ["sottotitoli inglesi"]),
            ],
            20,
        ),
        _field(
            "country_code",
            [
                (
                    "IT",
                    "reviewed",
                    ["prodotto in Italia" if include_cross_field_alias else "codice paese Italia"],
                )
            ],
            30,
        ),
    ]
    projection = _v1_projection(fields)
    value_count = sum(len(field["domain"]["values"]) for field in fields)
    projection_receipt = {
        "schema_version": 1,
        "receipt_id": "video-semantics/catalog-projection-receipt-v1",
        "projection_sha256": _hash(projection),
        "describe_sha256": _hash({"source": "synthetic-describe"}),
        "values_projection_sha256": sorted(_hash({"field": field["name"]}) for field in fields),
        "counts": {
            "catalogs": 1,
            "fields": len(fields),
            "finite_fields_expected": len(fields),
            "values_responses": len(fields),
            "values": value_count,
            "semantic_values": value_count,
            "gaps": 0,
        },
        "payload_redacted": True,
    }
    projection_receipt["receipt_sha256"] = _hash(
        {key: value for key, value in projection_receipt.items() if key != "receipt_sha256"}
    )
    census = build_local_census(
        projection,
        semantic_source_revision=REVISION,
        tenant_ref="public-synthetic",
    )
    target_values = [
        item
        for item in census["roster"]
        if item["node_kind"] == "value" and item["state"] == "reviewed"
    ]
    concepts = [
        _concept(item["literal"], f"approved-source-a:{index}")
        for index, item in enumerate(target_values)
    ]
    decisions = [
        {
            "concept_id": concept["concept_id"],
            "catalog": item["catalog"],
            "field": item["field"],
            "literal": item["literal"],
            "relation": "exact",
            "field_status": "declared-observed",
            "reason": "Reviewed synthetic target.",
            "evidence_refs": [f"approved-source-a:{index}"],
            "validated_usages": [],
            "decision_required": False,
            "reviewer": "editor-a",
            "decision_state": "reviewed",
        }
        for index, (concept, item) in enumerate(zip(concepts, target_values, strict=True))
    ]
    crosswalk = build_preliminary_crosswalk(
        concepts, census, decisions, semantic_source_revision=REVISION
    )
    ledger = _constraint_ledger([field["name"] for field in fields])
    snapshot = {
        "snapshot_id": "snapshot-001",
        "membership_sha256": census["receipt"]["roster_sha256"],
        "tenant_revision": _hash({"tenant": "public-synthetic"}),
        "catalog_projection_sha256": projection_receipt["projection_sha256"],
    }
    index = build_semantic_index_v2(
        projection,
        projection_receipt,
        census,
        concepts,
        crosswalk,
        ledger,
        semantic_source_revision=REVISION,
        grammar_revision=GRAMMAR_REVISION,
        toolchain_revision=TOOLCHAIN_REVISION,
        tenant_snapshot=snapshot,
    )["index"]
    context_bundle = build_brain_semantic_context_v2(index, concepts, crosswalk, ledger)
    return {"index": index, **context_bundle}


def _v2_proposal(
    bundle: dict,
    *,
    request: str,
    targets: list[str],
    refs: list[str],
) -> dict:
    return {
        "schema_version": 1,
        "proposal_id": "proposal-equivalence-1",
        "index_revision": bundle["index"]["revision"],
        "context_revision": bundle["context"]["revision"],
        "request_sha256": _hash(request),
        "clauses": [
            {
                "clause_id": "clause-equivalence-1",
                "surface": request,
                "resolution": "resolved",
                "semantic_refs": sorted(refs),
                "target_locators": sorted(targets),
                "candidate_locators": [],
                "requested_value": None,
                "reason_code": "REVIEWED_AKA_GROUP",
            }
        ],
    }


def _adjudicate(bundle: dict, proposal: dict, request: str) -> dict:
    return adjudicate_grounding_proposal_v2(
        bundle["index"],
        bundle["context"],
        request,
        proposal,
        context_receipt=bundle["receipt"],
        context_manifest=bundle["manifest"],
        expected_context_manifest_sha256=bundle["manifest"]["manifest_sha256"],
        catalog="public.video",
    )["grounding"]


def _group_targets(bundle: dict, field: str, literals: set[str]) -> list[str]:
    entries = [
        item
        for item in bundle["index"]["entries"]
        if item["node_kind"] == "value"
        and item["field"] == field
        and item.get("literal") in literals
    ]
    return [item["canonical_locator"] for item in entries]


def test_v2_reviewed_aka_group_accepts_complete_same_field_roster() -> None:
    bundle = _v2_bundle(include_draft=False)
    targets = _group_targets(bundle, "paesiorigine", {"Italia", "ITALIA"})
    proposal = _v2_proposal(
        bundle,
        request="prodotto in Italia",
        targets=targets,
        refs=[],
    )

    grounding = _adjudicate(bundle, proposal, "prodotto in Italia")

    assert grounding["status"] == "resolved"
    selected = grounding["clauses"][0]["selected"]
    assert [item["canonical_locator"] for item in selected] == sorted(targets)
    assert {item["field"] for item in selected} == {"paesiorigine"}
    assert {item["literal"] for item in selected} == {"Italia", "ITALIA"}


def test_v2_reviewed_aka_group_rejects_hidden_cross_field_alias_carrier() -> None:
    bundle = _v2_bundle(include_draft=False, include_cross_field_alias=True)
    targets = _group_targets(bundle, "paesiorigine", {"Italia", "ITALIA"})
    proposal = _v2_proposal(
        bundle,
        request="prodotto in Italia",
        targets=targets,
        refs=[],
    )

    with pytest.raises(BrainGroundingV2Error):
        _adjudicate(bundle, proposal, "prodotto in Italia")


@pytest.mark.parametrize("mutation", ["omitted", "extra", "cross_field", "draft"])
def test_v2_reviewed_aka_group_rejects_incomplete_or_unsafe_rosters(mutation: str) -> None:
    bundle = _v2_bundle()
    group_targets = _group_targets(bundle, "paesiorigine", {"Italia", "ITALIA"})
    entries = {
        item["literal"]: item for item in bundle["index"]["entries"] if item["node_kind"] == "value"
    }
    if mutation == "omitted":
        targets = group_targets[:1]
        refs = []
    elif mutation == "extra":
        targets = [*group_targets, entries["Italy"]["canonical_locator"]]
        refs = []
    elif mutation == "cross_field":
        targets = [*group_targets, entries["IT"]["canonical_locator"]]
        refs = []
    else:
        targets = [*group_targets, entries["Italy legacy"]["canonical_locator"]]
        refs = []
    proposal = _v2_proposal(
        bundle,
        request="prodotto in Italia",
        targets=targets,
        refs=refs,
    )

    with pytest.raises(BrainGroundingV2Error):
        _adjudicate(bundle, proposal, "prodotto in Italia")


def test_v2_contextual_english_subtitle_group_uses_both_physical_literals() -> None:
    bundle = _v2_bundle()
    targets = _group_targets(bundle, "subtitle_language", {"ENG", "eng"})
    proposal = _v2_proposal(
        bundle,
        request="sottotitoli inglesi",
        targets=targets,
        refs=[],
    )

    grounding = _adjudicate(bundle, proposal, "sottotitoli inglesi")

    assert grounding["status"] == "resolved"
    assert {item["literal"] for item in grounding["clauses"][0]["selected"]} == {
        "ENG",
        "eng",
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [("resolution", []), ("reason_code", {})],
)
def test_v2_malformed_group_enums_fail_with_contract_error(key: str, value: object) -> None:
    bundle = _v2_bundle(include_draft=False)
    targets = _group_targets(bundle, "paesiorigine", {"Italia", "ITALIA"})
    proposal = _v2_proposal(
        bundle,
        request="prodotto in Italia",
        targets=targets,
        refs=[],
    )
    proposal["clauses"][0][key] = value

    with pytest.raises(BrainGroundingV2Error):
        _adjudicate(bundle, proposal, "prodotto in Italia")
