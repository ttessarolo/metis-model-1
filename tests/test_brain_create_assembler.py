from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Any

import pytest

from metis_model1.brain_create_assembler import (
    CreateAuthorityAssemblyError,
    assemble_create_authority_history,
    derive_unique_flash_spans,
    prune_reviewed_retrieval,
    typed_decisions_from_server_request,
)
from metis_model1.brain_create_authority_issuer import clarification_decisions_revision
from metis_model1.brain_create_surface import CreateAuthorityHistoryMessage
from metis_model1.brain_intent_ir import IntentCompileRequest, IntentIR
from metis_model1.brain_protocol import canonical_json
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_turns import TurnRequest

CONTEXT = "sha256:" + "a" * 64
SEMANTIC = "sha256:" + "b" * 64
TOOLCHAIN = "sha256:" + "c" * 64


def _request(
    instruction: str = "Crea un endpoint per Film",
    *,
    clarification: dict[str, Any] | None = None,
) -> TurnRequest:
    return TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": "12345678-1234-4234-9234-123456789abc",
            "expected_context_revision": CONTEXT,
            "expected_semantic_source_revision": SEMANTIC,
            "intent": "create",
            "instruction": instruction,
            "target": {
                "mode": "create",
                "relative_path": "properties/brain_create.metis",
                "endpoint": "play.brain_create",
                "base_sha256": None,
            },
            "basis": None,
            "clarification_response": clarification,
        }
    )


def _server_envelope(
    request: TurnRequest,
    *decisions: dict[str, Any],
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert decisions
    latest = decisions[-1]
    result = {
        **copy.deepcopy(latest),
        "conversation": {
            "request_fingerprint": request.request_fingerprint,
            "context_revision": CONTEXT,
            "semantic_source_revision": SEMANTIC,
            "rounds_used": len(decisions),
            "max_rounds": 3,
            "decisions": [
                {
                    key: copy.deepcopy(value)
                    for key, value in item.items()
                    if key != "resolved_value"
                }
                for item in decisions
            ],
            "assumptions": [],
            "latest_proposal_ref": None,
        },
        "decisions": [copy.deepcopy(item) for item in decisions],
    }
    if current is not None:
        result["current_decision"] = copy.deepcopy(current)
    return result


def _catalog_decision() -> dict[str, Any]:
    return {
        "kind": "catalog",
        "question_key": "catalog-choice",
        "round": 1,
        "answer": {"text": "video"},
        "resolved_value": "video",
        "label": "video",
    }


def test_history_appends_each_real_refinement_even_when_text_is_repeated() -> None:
    request = _request("Aggiungi un fallback")
    first = assemble_create_authority_history(request=request)
    second = assemble_create_authority_history(request=request, parent_history=first.messages)

    assert [item.text for item in second.messages] == [
        "Aggiungi un fallback",
        "Aggiungi un fallback",
    ]
    assert [item.ordinal for item in second.messages] == [0, 1]
    assert second.appended is True
    assert second.history_revision != first.history_revision


def test_history_does_not_duplicate_instruction_on_server_owned_answer_retry() -> None:
    original = _request()
    first = assemble_create_authority_history(request=original)
    decision = _catalog_decision()
    retry = _request(
        clarification={
            "clarification_id": "clarification_123456789012345",
            "answer": {"text": "video"},
            "context_revision": CONTEXT,
            "semantic_source_revision": SEMANTIC,
        }
    )
    retry = retry.with_server_clarification(_server_envelope(retry, decision, current=decision))
    resumed = assemble_create_authority_history(request=retry, parent_history=first.messages)

    assert resumed.messages == first.messages
    assert resumed.history_revision == first.history_revision
    assert resumed.current_message_ordinal == 0
    assert resumed.appended is False


def test_client_shaped_answer_alone_cannot_suppress_history_append() -> None:
    original = _request()
    first = assemble_create_authority_history(request=original)
    spoof = _request(
        clarification={
            "clarification_id": "clarification_123456789012345",
            "answer": {"text": "video"},
            "context_revision": CONTEXT,
            "semantic_source_revision": SEMANTIC,
        }
    )
    resumed = assemble_create_authority_history(request=spoof, parent_history=first.messages)
    assert len(resumed.messages) == 2


def test_history_rejects_noncontiguous_or_hash_drifted_parent() -> None:
    bad = (CreateAuthorityHistoryMessage(0, "prima", "sha256:" + "0" * 64),)
    with pytest.raises(CreateAuthorityAssemblyError) as raised:
        assemble_create_authority_history(request=_request(), parent_history=bad)
    assert raised.value.code == "CREATE_HISTORY_INVALID"


def test_typed_server_decisions_bind_exact_revisions_and_choice_authority() -> None:
    decision = _catalog_decision()
    request = _request().with_server_clarification(_server_envelope(_request(), decision))
    result = typed_decisions_from_server_request(
        request=request,
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        authority_keys_by_choice={
            ("catalog", "video"): "semantic.catalog.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
    )

    assert len(result.decisions) == 1
    typed = result.decisions[0]
    assert typed.kind == "catalog"
    assert typed.value == {"authority_key": "semantic.catalog.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
    assert typed.context_revision == CONTEXT
    assert typed.semantic_revision == SEMANTIC
    assert result.decisions_revision == clarification_decisions_revision(result.decisions)
    assert result.current_decision_key is None


def test_typed_result_count_requires_explicit_total_or_page_mode() -> None:
    decision = {
        "kind": "result_count",
        "question_key": "result-count",
        "round": 1,
        "answer": {"integer": 24},
        "resolved_value": None,
    }
    request = _request().with_server_clarification(_server_envelope(_request(), decision))
    with pytest.raises(CreateAuthorityAssemblyError) as missing:
        typed_decisions_from_server_request(
            request=request,
            context_revision=CONTEXT,
            semantic_revision=SEMANTIC,
        )
    assert missing.value.code == "CREATE_DECISION_MAPPING_INVALID"

    result = typed_decisions_from_server_request(
        request=request,
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        result_count_modes={"result-count": "count"},
    )
    assert result.decisions[0].value == {"mode": "count", "value": 24}


@pytest.mark.parametrize(
    "server_value",
    [
        {"kind": "catalog", "resolved_value": "video"},
        {"decisions": [_catalog_decision()]},
    ],
)
def test_flat_or_partial_server_decision_shapes_are_rejected_as_spoofed(
    server_value: dict[str, Any],
) -> None:
    request = _request().with_server_clarification(server_value)
    with pytest.raises(CreateAuthorityAssemblyError) as raised:
        typed_decisions_from_server_request(
            request=request,
            context_revision=CONTEXT,
            semantic_revision=SEMANTIC,
            authority_keys_by_choice={
                ("catalog", "video"): "semantic.catalog.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            },
        )
    assert raised.value.code == "CREATE_DECISION_SPOOFED"


def test_client_answer_without_server_decision_is_rejected() -> None:
    request = _request(
        clarification={
            "clarification_id": "clarification_123456789012345",
            "answer": {"text": "video"},
            "context_revision": CONTEXT,
            "semantic_source_revision": SEMANTIC,
        }
    )
    with pytest.raises(CreateAuthorityAssemblyError) as raised:
        typed_decisions_from_server_request(
            request=request,
            context_revision=CONTEXT,
            semantic_revision=SEMANTIC,
        )
    assert raised.value.code == "CREATE_DECISION_SPOOFED"


def _flash(instruction: str, source: str) -> IntentIR:
    return IntentIR.parse(
        {
            "schema_version": 1,
            "operation": "create",
            "target_scope": "new",
            "concept_logic": "all",
            "concepts": [{"source": source, "query": source, "polarity": "include"}],
            "response_format": "preserve",
            "fallback": "preserve",
            "ambiguities": [],
        },
        request=IntentCompileRequest(
            instruction=instruction,
            intent="create",
            target_mode="create",
        ),
    )


def test_flash_span_uses_utf8_byte_offsets_for_unique_multibyte_source() -> None:
    instruction = "Crea café ambientati in città"
    request = _request(instruction)
    history = assemble_create_authority_history(request=request)
    spans = derive_unique_flash_spans(
        request=request,
        history=history,
        flash_intent=_flash(instruction, "città"),
    )

    assert len(spans) == 1
    assert spans[0].start_utf8 == len("Crea café ambientati in ".encode())
    raw = instruction.encode("utf-8")
    assert raw[spans[0].start_utf8 : spans[0].end_utf8].decode("utf-8") == "città"


def test_flash_duplicate_source_substring_fails_closed() -> None:
    instruction = "film premiati e film italiani"
    request = _request(instruction)
    history = assemble_create_authority_history(request=request)
    with pytest.raises(CreateAuthorityAssemblyError) as raised:
        derive_unique_flash_spans(
            request=request,
            history=history,
            flash_intent=_flash(instruction, "film"),
        )
    assert raised.value.code == "CREATE_FLASH_SOURCE_AMBIGUOUS"


def test_flash_missing_source_fails_closed_before_any_span_is_issued() -> None:
    instruction = "film premiati"
    request = _request(instruction)
    history = assemble_create_authority_history(request=request)
    unbound = IntentIR(
        {
            "schema_version": 1,
            "operation": "create",
            "target_scope": "new",
            "concept_logic": "all",
            "concepts": [
                {"source": "film italiani", "query": "film italiani", "polarity": "include"}
            ],
            "response_format": "preserve",
            "fallback": "preserve",
            "ambiguities": [],
        }
    )
    with pytest.raises(CreateAuthorityAssemblyError) as raised:
        derive_unique_flash_spans(request=request, history=history, flash_intent=unbound)
    assert raised.value.code == "CREATE_FLASH_INVALID"


def _retrieval(
    *,
    domain: dict[str, Any] | None = None,
    literal: str | None = "Film",
) -> RetrievalResult:
    domain = {"kind": "enum", "size": 2, "nature": "editorial"} if domain is None else domain
    field: dict[str, Any] = {
        "name": "genre",
        "type": "keyword",
        "modifiers": [],
        "domain": copy.deepcopy(domain),
        "semantic": {
            "state": "reviewed",
            "means": {
                "text": "genere editoriale",
                "at": {"file": "catalogs/private-source.metis", "line": 10},
            },
        },
    }
    if literal is not None and domain.get("kind") in {"enum", "inline"}:
        field["values"] = [
            {
                "literal": literal,
                "semantic": {
                    "state": "reviewed",
                    "means": {
                        "text": "opera cinematografica",
                        "at": {"file": "catalogs/private-source.metis", "line": 11},
                    },
                },
            }
        ]
    selection = {
        "catalog": "video",
        "field": "genre",
        "literal": literal,
        "domain": copy.deepcopy(domain),
        "matched_by": "reviewed_semantics",
        "type": "keyword",
        "modifiers": [],
        "source": "SENTINEL_SELECTION_SOURCE",
    }
    resolution = {
        "concept": literal or "genre",
        "catalog": "video",
        "field": "genre",
        "literal": literal,
        "review_state": "reviewed",
        "provenance": "SENTINEL_RESOLUTION_PROVENANCE",
    }
    return RetrievalResult(
        context={
            "language_version": "0.43",
            "semantic_schema": 2,
            "tenant_alias": "play-prod",
            "tenant_id": "tenant-one",
            "context_revision": CONTEXT,
            "semantic_source_revision": SEMANTIC,
            "toolchain_binding": TOOLCHAIN,
            "catalog": {
                "name": "video",
                "file": "SENTINEL_PRIVATE_PATH",
                "semantic": {"state": "reviewed"},
            },
            "fields": [field],
            "endpoint_templates": [
                {
                    "path": "SENTINEL_TEMPLATE_PATH",
                    "source": "SENTINEL_TEMPLATE_SOURCE",
                }
            ],
        },
        grounding={
            "status": "resolved",
            "catalogs": ["video"],
            "selections": [selection],
            "resolutions": [resolution],
            "candidates": [],
            "unresolved": [],
            "lookup": None,
            "lookups": [],
        },
        semantic_source_revision=SEMANTIC,
    )


def _bindings(
    *,
    literal: str | None = "Film",
    requirement: str = "requirement.semantic",
) -> dict[tuple[str, ...], list[str]]:
    result = {
        ("catalog", "video"): [requirement],
        ("field", "video", "genre"): [requirement],
    }
    if literal is not None:
        result[("catalog_value", "video", "genre", literal)] = [requirement]
    return result


def _prune(
    retrieved: RetrievalResult,
    bindings: dict[tuple[str, ...], list[str]] | None = None,
):
    return prune_reviewed_retrieval(
        retrieved=retrieved,
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        toolchain_binding=TOOLCHAIN,
        authority_requirement_keys=_bindings() if bindings is None else bindings,
    )


def test_pruner_rebuilds_only_reviewed_catalog_field_value_without_private_sentinels() -> None:
    projection = _prune(_retrieval())
    assert projection.status == "resolved"
    assert [item.authority.roles for item in projection.authorities] == [
        ("catalog",),
        ("field",),
        ("catalog_value",),
    ]
    assert [item.domain for item in projection.authorities] == ["none", "finite", "finite"]
    assert all(
        item.authority.requirement_keys == ("requirement.semantic",)
        for item in projection.authorities
    )
    serialized = canonical_json(asdict(projection)).decode("utf-8")
    for sentinel in (
        "SENTINEL_PRIVATE_PATH",
        "SENTINEL_TEMPLATE_PATH",
        "SENTINEL_TEMPLATE_SOURCE",
        "SENTINEL_SELECTION_SOURCE",
        "SENTINEL_RESOLUTION_PROVENANCE",
        "private-source.metis",
    ):
        assert sentinel not in serialized


def test_requirement_bindings_are_exact_per_authority_without_cross_grants() -> None:
    bindings = {
        ("catalog", "video"): ["requirement.catalog"],
        ("field", "video", "genre"): ["requirement.field"],
        ("catalog_value", "video", "genre", "Film"): ["requirement.value"],
    }
    projection = _prune(_retrieval(), bindings)
    by_role = {
        item.authority.roles[0]: item.authority.requirement_keys for item in projection.authorities
    }
    assert by_role == {
        "catalog": ("requirement.catalog",),
        "field": ("requirement.field",),
        "catalog_value": ("requirement.value",),
    }

    missing = copy.deepcopy(bindings)
    missing.pop(("field", "video", "genre"))
    with pytest.raises(CreateAuthorityAssemblyError) as absent:
        _prune(_retrieval(), missing)
    assert absent.value.code == "CREATE_REQUIREMENT_MISSING"

    extra = copy.deepcopy(bindings)
    extra[("field", "video", "unused")] = ["requirement.extra"]
    with pytest.raises(CreateAuthorityAssemblyError) as surplus:
        _prune(_retrieval(), extra)
    assert surplus.value.code == "CREATE_REQUIREMENT_EXTRA"


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ({"kind": "open"}, "open"),
        ({"kind": "none"}, "none"),
        ({"kind": "inline", "size": 0}, "finite"),
    ],
)
def test_pruner_preserves_open_none_and_finite_field_domain(
    domain: dict[str, Any], expected: str
) -> None:
    projection = _prune(_retrieval(domain=domain, literal=None), _bindings(literal=None))
    assert projection.status == "resolved"
    field = next(item for item in projection.authorities if item.authority.roles == ("field",))
    assert field.domain == expected
    assert all(item.authority.roles != ("catalog_value",) for item in projection.authorities)


def test_open_or_none_domain_can_never_materialize_a_catalog_value() -> None:
    projection = _prune(_retrieval(domain={"kind": "open"}, literal="Drammatico"))
    assert projection.status == "unsupported"
    assert projection.unresolved == ("value_without_finite_domain",)
    assert projection.authorities == ()


def test_resolution_review_state_and_one_to_one_identity_are_mandatory() -> None:
    retrieved = _retrieval()
    retrieved.grounding["resolutions"][0]["review_state"] = "draft"
    with pytest.raises(CreateAuthorityAssemblyError) as review:
        _prune(retrieved)
    assert review.value.code == "CREATE_SEMANTIC_REVIEW_INVALID"

    retrieved = _retrieval()
    retrieved.grounding["resolutions"][0]["field"] = "mood"
    with pytest.raises(CreateAuthorityAssemblyError) as identity:
        _prune(retrieved)
    assert identity.value.code == "CREATE_SEMANTIC_REVIEW_INVALID"


def test_field_domain_or_technical_drift_fails_closed() -> None:
    retrieved = _retrieval()
    retrieved.grounding["selections"][0]["domain"] = {"kind": "open"}
    with pytest.raises(CreateAuthorityAssemblyError) as domain:
        _prune(retrieved)
    assert domain.value.code == "CREATE_SEMANTIC_BINDING_DRIFT"

    retrieved = _retrieval()
    retrieved.grounding["selections"][0]["modifiers"] = ["multi"]
    with pytest.raises(CreateAuthorityAssemblyError) as technical:
        _prune(retrieved)
    assert technical.value.code == "CREATE_SEMANTIC_BINDING_DRIFT"


def test_unreviewed_selected_nodes_are_not_copied_as_authority() -> None:
    retrieved = _retrieval()
    retrieved.context["fields"][0]["semantic"]["state"] = "unannotated"
    projection = _prune(retrieved)
    assert projection.status == "unsupported"
    assert projection.authorities == ()
    assert projection.unresolved == ("field_not_reviewed",)


def test_projection_and_decisions_are_isolated_from_mutable_inputs() -> None:
    requirements = ["requirement.semantic"]
    bindings = _bindings()
    bindings[("catalog", "video")] = requirements
    retrieved = _retrieval()
    projection = _prune(retrieved, bindings)
    before = asdict(projection)
    requirements[0] = "requirement.mutated"
    retrieved.context["fields"][0]["values"][0]["literal"] = "MUTATED"
    retrieved.grounding["selections"][0]["literal"] = "MUTATED"
    assert asdict(projection) == before

    decision = _catalog_decision()
    request = _request().with_server_clarification(_server_envelope(_request(), decision))
    bindings = {("catalog", "video"): "semantic.catalog.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
    typed = typed_decisions_from_server_request(
        request=request,
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        authority_keys_by_choice=bindings,
    )
    bindings[("catalog", "video")] = "semantic.catalog.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    decision["resolved_value"] = "users"
    assert typed.decisions[0].value == {
        "authority_key": "semantic.catalog.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }


def test_projection_revision_changes_with_explicit_requirement_binding() -> None:
    first = _prune(_retrieval(), _bindings(requirement="requirement.one"))
    second = _prune(_retrieval(), _bindings(requirement="requirement.two"))
    assert first.projection_revision != second.projection_revision
