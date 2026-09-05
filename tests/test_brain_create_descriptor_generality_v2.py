"""Metamorphic proof for descriptor-native filtered CREATE authority."""

from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_create_structural_authority_v2 import (
    ReviewedSemanticIndex,
    StructuralIntent,
    filtered_collection_intent,
    reviewed_descriptor_filter_index,
    validate_structural_intent,
)
from metis_model1.brain_create_surface import CreateAuthorityHistoryMessage
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_semantic_retrieval import LoadedProjection, Schema2SnapshotRetriever
from metis_model1.video_catalog_projection import PROJECTION_CONTRACT

POLICY_REVISION = bytes_sha256(b"descriptor-generality-policy")
COUNT = 37


def _revision(label: str) -> str:
    return bytes_sha256(label.encode("utf-8"))


def _messages() -> tuple[CreateAuthorityHistoryMessage, ...]:
    values = (
        "Crea una collezione filtrata dai descrittori revisionati.",
        f"Restituisci esattamente {COUNT} risultati totali.",
    )
    return tuple(
        CreateAuthorityHistoryMessage(
            ordinal=index,
            text=value,
            message_sha256=bytes_sha256(value.encode("utf-8")),
        )
        for index, value in enumerate(values)
    )


def _tenant_retrieval(
    *,
    catalog: str,
    field: str,
    literals: tuple[str, str],
) -> tuple[RetrievalResult, str, str, str]:
    """Return a synthetic Schema2 result plus its immutable bindings.

    ``tipologia`` and ``Film`` deliberately remain reviewed decoys in every
    synthetic snapshot.  They are never selected, so a descriptor-native path
    must not copy them into the output merely because they are familiar names.
    """

    context_revision = _revision(f"context:{catalog}")
    semantic_revision = _revision(f"semantic:{catalog}")
    toolchain_binding = _revision(f"toolchain:{catalog}")
    domain = {"kind": "enum", "size": 2}
    selected_field = {
        "name": field,
        "type": "keyword",
        "modifiers": [],
        "domain": domain,
        "semantic": {"state": "reviewed"},
        "values": [{"literal": literal, "semantic": {"state": "reviewed"}} for literal in literals],
    }
    decoy_field = {
        "name": "tipologia",
        "type": "keyword",
        "modifiers": [],
        "domain": {"kind": "enum", "size": 1},
        "semantic": {"state": "reviewed"},
        "values": [{"literal": "Film", "semantic": {"state": "reviewed"}}],
    }
    selection = {
        "catalog": catalog,
        "field": field,
        "literals": list(literals),
        "value_mode": "any_of",
        "type": "keyword",
        "modifiers": [],
        "domain": domain,
    }
    resolution = {
        "catalog": catalog,
        "field": field,
        "literal": None,
        "review_state": "reviewed",
    }
    return (
        RetrievalResult(
            context={
                "semantic_schema": 2,
                "catalog_reference_roster": [catalog],
                "context_revision": context_revision,
                "semantic_source_revision": semantic_revision,
                "toolchain_binding": toolchain_binding,
                "catalog": {"name": catalog, "semantic": {"state": "reviewed"}},
                "fields": [selected_field, decoy_field],
            },
            grounding={
                "status": "resolved",
                "catalogs": [catalog],
                "selections": [selection],
                "resolutions": [resolution],
                "candidates": [],
                "unresolved": [],
                "lookup": None,
                "lookups": [],
            },
            semantic_source_revision=semantic_revision,
        ),
        context_revision,
        semantic_revision,
        toolchain_binding,
    )


def _index(
    retrieved: RetrievalResult, context_revision: str, semantic_revision: str, toolchain: str
):
    return reviewed_descriptor_filter_index(
        retrieved=retrieved,
        context_revision=context_revision,
        semantic_revision=semantic_revision,
        toolchain_binding=toolchain,
    )


def _normalized_fragment(intent: StructuralIntent, *, field: str, literals: tuple[str, str]) -> Any:
    """Erase only bijectively renamed descriptor identities from a fragment."""

    fragment = copy.deepcopy(intent.mutations[0].fragment)
    catalog = next(
        item.identity["catalog"]
        for item in intent.mutations[0].leaf_evidence
        if item.origin == "reviewed_semantic" and item.identity.get("role") == "catalog"
    )
    replacement = {
        catalog.rsplit(".", 1)[-1]: "CATALOG",
        field: "FIELD",
        literals[0]: "VALUE_1",
        literals[1]: "VALUE_2",
    }

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalize(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [normalize(nested) for nested in value]
        return replacement.get(value, value) if isinstance(value, str) else value

    return normalize(fragment)


def _intent(
    *, catalog: str, field: str, literals: tuple[str, str]
) -> tuple[StructuralIntent, ReviewedSemanticIndex]:
    retrieved, context_revision, semantic_revision, toolchain = _tenant_retrieval(
        catalog=catalog,
        field=field,
        literals=literals,
    )
    semantic = _index(retrieved, context_revision, semantic_revision, toolchain)
    intent = filtered_collection_intent(
        count=COUNT,
        messages=_messages(),
        semantic=semantic,
        policy_revision=POLICY_REVISION,
    )
    return intent, semantic


def _descriptor_semantic(*, path: str, line: int, text: str, aliases: list[str]) -> dict[str, Any]:
    return {
        "state": "reviewed",
        "at": {"file": path, "line": line},
        "means": {"text": text, "at": {"file": path, "line": line + 1}},
        "aka": {"items": aliases, "at": {"file": path, "line": line + 2}},
    }


def _schema2_tenant(
    *, tenant: str, catalog: str, field: str, literal: str
) -> tuple[ContextSnapshot, dict[str, Any]]:
    path = f"catalogs/{catalog}.metis"
    source = f"catalog {catalog} {{}}\n".encode()
    snapshot = ContextSnapshot(
        tenant_alias=tenant,
        tenant_id=tenant,
        root_device=1,
        root_inode=1,
        revision=_revision(f"snapshot:{tenant}"),
        toolchain_binding=_revision(f"grammar:{tenant}"),
        files=(SnapshotFile(path, source, bytes_sha256(source)),),
        total_bytes=len(source),
    )
    value_semantic = _descriptor_semantic(
        path=path,
        line=20,
        text="racconto ambientato tra i ghiacci",
        aliases=["storia artica"],
    )
    projection = {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": tenant,
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": catalog,
                "driver": "opensearch",
                "file": path,
                "semantic": _descriptor_semantic(
                    path=path,
                    line=2,
                    text="archivio di racconti",
                    aliases=["raccolta narrativa"],
                ),
                "fields": [
                    {
                        "name": field,
                        "type": "keyword",
                        "modifiers": [],
                        "semantic": _descriptor_semantic(
                            path=path,
                            line=10,
                            text="ambientazione narrativa",
                            aliases=["luogo del racconto"],
                        ),
                        "domain": {
                            "kind": "enum",
                            "size": 1,
                            "values": [{"literal": literal, "semantic": value_semantic}],
                        },
                    }
                ],
            }
        ],
    }
    return snapshot, projection


def test_renamed_isomorphic_schema2_tenants_have_equivalent_filtered_structure() -> None:
    left_field, left_values = "spectrum_alpha", ("Aurora", "Borealis")
    right_field, right_values = "constellation_beta", ("Orion", "Lyra")
    left, left_semantic = _intent(catalog="north.archive", field=left_field, literals=left_values)
    right, right_semantic = _intent(
        catalog="south.ledger", field=right_field, literals=right_values
    )

    assert (
        validate_structural_intent(
            left,
            policy_revision=POLICY_REVISION,
            semantic_authority=left_semantic,
            result_count=COUNT,
        )
        is left
    )
    assert (
        validate_structural_intent(
            right,
            policy_revision=POLICY_REVISION,
            semantic_authority=right_semantic,
            result_count=COUNT,
        )
        is right
    )
    normalized_left = _normalized_fragment(left, field=left_field, literals=left_values)
    normalized_right = _normalized_fragment(right, field=right_field, literals=right_values)
    assert normalized_left == normalized_right

    for intent, decoys in (
        (left, ("tipologia", "Film", "video")),
        (right, ("tipologia", "Film", "video")),
    ):
        rendered = canonical_json(intent.mutations[0].fragment)
        assert intent.family == "filtered_collection"
        assert intent.mutations[0].fragment["fetches"][0]["clauses"][0]["where"] == [
            {
                "op": "in",
                "field": left_field if intent is left else right_field,
                "value": {
                    "kind": "vals",
                    "items": list(left_values if intent is left else right_values),
                },
            }
        ]
        assert all(decoy.encode("utf-8") not in rendered for decoy in decoys)


def test_schema2_retriever_discovers_isomorphic_renamed_descriptors_from_shared_alias() -> None:
    instruction = "storia artica"
    left_snapshot, left_projection = _schema2_tenant(
        tenant="tenant-north",
        catalog="archive_alpha",
        field="climate_alpha",
        literal="Aurora",
    )
    right_snapshot, right_projection = _schema2_tenant(
        tenant="tenant-south",
        catalog="ledger_beta",
        field="climate_beta",
        literal="Borealis",
    )

    def retrieve(snapshot: ContextSnapshot, projection: dict[str, Any]) -> RetrievalResult:
        retriever = Schema2SnapshotRetriever(
            lambda current: LoadedProjection(
                projection,
                current.revision,
                current.semantic_source_revision(),
            )
        )
        return retriever.retrieve(
            lease=SimpleNamespace(snapshot=snapshot),
            request=SimpleNamespace(instruction=instruction),
        )

    left = retrieve(left_snapshot, left_projection)
    right = retrieve(right_snapshot, right_projection)

    assert left.grounding["status"] == right.grounding["status"] == "resolved"
    assert left.grounding["selections"] == [
        {
            "catalog": "archive_alpha",
            "field": "climate_alpha",
            "literal": "Aurora",
            "domain": {"kind": "enum", "size": 1},
            "matched_by": "reviewed_aka_exact",
            "type": "keyword",
            "modifiers": [],
        }
    ]
    assert right.grounding["selections"] == [
        {
            "catalog": "ledger_beta",
            "field": "climate_beta",
            "literal": "Borealis",
            "domain": {"kind": "enum", "size": 1},
            "matched_by": "reviewed_aka_exact",
            "type": "keyword",
            "modifiers": [],
        }
    ]


def test_same_terminal_catalog_collision_is_preserved_then_rejected_by_filter_index() -> None:
    snapshot, projection = _schema2_tenant(
        tenant="tenant-collision",
        catalog="alpha.shared",
        field="climate_collision",
        literal="Aurora",
    )
    collision_path = "catalogs/beta.shared.metis"
    collision_source = b"catalog beta.shared {}\n"
    collision_snapshot_file = SnapshotFile(
        collision_path,
        collision_source,
        bytes_sha256(collision_source),
    )
    snapshot = replace(
        snapshot,
        files=(*snapshot.files, collision_snapshot_file),
        total_bytes=snapshot.total_bytes + len(collision_source),
    )
    projection["catalogs"].append(
        {
            "name": "beta.shared",
            "driver": "opensearch",
            "file": collision_path,
            "semantic": {
                **_descriptor_semantic(
                    path=collision_path,
                    line=2,
                    text="archivio collisione non revisionato",
                    aliases=["collisione"],
                ),
                "state": "draft",
            },
            "fields": [],
        }
    )
    retriever = Schema2SnapshotRetriever(
        lambda current: LoadedProjection(
            projection,
            current.revision,
            current.semantic_source_revision(),
        )
    )
    result = retriever.retrieve(
        lease=SimpleNamespace(snapshot=snapshot),
        request=SimpleNamespace(instruction="storia artica"),
    )

    assert result.grounding["status"] == "resolved"
    assert result.grounding["catalogs"] == ["alpha.shared"]
    assert result.context["catalog_reference_roster"] == ["alpha.shared", "beta.shared"]
    with pytest.raises(BrainError) as raised:
        _index(
            result,
            snapshot.revision,
            snapshot.semantic_source_revision(),
            snapshot.toolchain_binding,
        )
    assert raised.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("draft", "CREATE_TYPED_AUTHORITY_UNSUPPORTED"),
        ("missing", "CREATE_TYPED_AUTHORITY_UNSUPPORTED"),
        ("open", "CREATE_TYPED_AUTHORITY_UNSUPPORTED"),
        ("stale", "CREATE_TYPED_AUTHORITY_STALE"),
        ("missing_catalog_reference_roster", "CREATE_TYPED_AUTHORITY_UNSUPPORTED"),
        ("duplicate_catalog_reference_roster", "CREATE_TYPED_AUTHORITY_UNSUPPORTED"),
        ("missing_value_mode", "CREATE_STRUCTURAL_AUTHORITY_INVALID"),
        ("repeated_field", "CREATE_TYPED_AUTHORITY_UNSUPPORTED"),
        ("cross_field_duplicate", "CREATE_STRUCTURAL_AUTHORITY_INVALID"),
        ("duplicate_reviewed_and_draft_literal", "CREATE_STRUCTURAL_AUTHORITY_INVALID"),
    ),
)
def test_descriptor_filter_authority_fails_closed_for_invalid_schema2_evidence(
    mutation: str, code: str
) -> None:
    field, literals = "signal_gamma", ("North", "South")
    retrieved, context_revision, semantic_revision, toolchain = _tenant_retrieval(
        catalog="east.index", field=field, literals=literals
    )
    context = copy.deepcopy(retrieved.context)
    grounding = copy.deepcopy(retrieved.grounding)
    invalid = replace(retrieved, context=context, grounding=grounding)

    if mutation == "draft":
        context["fields"][0]["semantic"]["state"] = "draft"
    elif mutation == "missing":
        context["fields"][0]["values"][1]["semantic"]["state"] = "draft"
    elif mutation == "open":
        open_domain = {"kind": "open"}
        context["fields"][0]["domain"] = open_domain
        grounding["selections"][0]["domain"] = open_domain
    elif mutation == "stale":
        context["context_revision"] = _revision("different-snapshot")
    elif mutation == "missing_catalog_reference_roster":
        del context["catalog_reference_roster"]
    elif mutation == "duplicate_catalog_reference_roster":
        context["catalog_reference_roster"].append("east.index")
    elif mutation == "missing_value_mode":
        del grounding["selections"][0]["value_mode"]
    elif mutation == "repeated_field":
        repeated = copy.deepcopy(grounding["selections"][0])
        repeated["literals"] = [literals[1]]
        grounding["selections"].append(repeated)
        grounding["resolutions"].append(
            {
                "catalog": "east.index",
                "field": field,
                "literal": None,
                "review_state": "reviewed",
            }
        )
    elif mutation == "duplicate_reviewed_and_draft_literal":
        context["fields"][0]["values"].append(
            {"literal": literals[0], "semantic": {"state": "draft"}}
        )
    else:
        duplicate = copy.deepcopy(grounding["selections"][0])
        duplicate["field"] = "tipologia"
        duplicate["literals"] = ["Film"]
        duplicate["domain"] = context["fields"][1]["domain"]
        grounding["selections"].append(duplicate)
        grounding["resolutions"].append(
            {
                "catalog": "east.index",
                "field": field,
                "literal": None,
                "review_state": "reviewed",
            }
        )

    with pytest.raises(BrainError) as raised:
        _index(invalid, context_revision, semantic_revision, toolchain)

    assert raised.value.code == code


def test_descriptor_filter_validator_rejects_a_tampered_legacy_decoy_field() -> None:
    intent, semantic = _intent(
        catalog="west.records",
        field="facet_delta",
        literals=("Cobalt", "Copper"),
    )
    tampered = copy.deepcopy(intent.mutations[0].fragment)
    tampered["fetches"][0]["clauses"][0]["where"][0]["field"] = "tipologia"
    forged = replace(intent, mutations=(replace(intent.mutations[0], fragment=tampered),))

    with pytest.raises(BrainError) as raised:
        validate_structural_intent(
            forged,
            policy_revision=POLICY_REVISION,
            semantic_authority=semantic,
            result_count=COUNT,
        )

    assert raised.value.code == "CREATE_STRUCTURAL_AUTHORITY_INVALID"


def test_descriptor_filter_validator_reopens_the_original_result_count() -> None:
    intent, semantic = _intent(
        catalog="west.counts",
        field="facet_zeta",
        literals=("Gold", "Silver"),
    )
    fragment = copy.deepcopy(intent.mutations[0].fragment)
    fragment["fetches"][0]["cardinality"]["value"] = COUNT + 1
    forged = replace(intent, mutations=(replace(intent.mutations[0], fragment=fragment),))

    with pytest.raises(BrainError) as raised:
        validate_structural_intent(
            forged,
            policy_revision=POLICY_REVISION,
            semantic_authority=semantic,
            result_count=COUNT,
        )

    assert raised.value.code == "CREATE_STRUCTURAL_AUTHORITY_INVALID"


@pytest.mark.parametrize("tamper", ("literal_and_evidence", "semantic_origin_to_policy"))
def test_descriptor_filter_validator_reopens_the_original_semantic_authority(tamper: str) -> None:
    intent, semantic = _intent(
        catalog="central.entries",
        field="facet_epsilon",
        literals=("Amber", "Azure"),
    )
    mutation = intent.mutations[0]
    fragment = copy.deepcopy(mutation.fragment)
    evidence = list(mutation.leaf_evidence)
    literal_evidence_index = next(
        index
        for index, item in enumerate(evidence)
        if item.origin == "reviewed_semantic" and item.identity.get("role") == "catalog_value"
    )
    literal_evidence = evidence[literal_evidence_index]

    if tamper == "literal_and_evidence":
        fragment["fetches"][0]["clauses"][0]["where"][0]["value"]["items"][0] = "Forged"
        evidence[literal_evidence_index] = replace(
            literal_evidence,
            identity={**literal_evidence.identity, "literal": "Forged"},
        )
    else:
        evidence[literal_evidence_index] = replace(
            literal_evidence,
            origin="policy",
            identity={
                "policy_revision": POLICY_REVISION,
                "structural_pointer": literal_evidence.json_pointer,
            },
        )
    forged_mutation = replace(mutation, fragment=fragment, leaf_evidence=tuple(evidence))
    forged = replace(intent, mutations=(forged_mutation,))

    with pytest.raises(BrainError) as raised:
        validate_structural_intent(
            forged,
            policy_revision=POLICY_REVISION,
            semantic_authority=semantic,
            result_count=COUNT,
        )

    assert raised.value.code == "CREATE_STRUCTURAL_AUTHORITY_INVALID"
