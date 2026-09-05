from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

import pytest

from metis_model1.brain_create_authority_issuer import (
    AuthorityCandidate,
    CapabilityInventory,
    CreateAuthorityIssuer,
    DefaultPolicy,
    FlashExactSpan,
    IssuanceSnapshot,
    Issued,
    NeedsClarification,
    PolicyDecision,
    RequirementClaim,
    ReviewedSemanticAuthority,
    RootAuthority,
    SafeReviewedProjection,
    TypedDecision,
    TypedFragment,
    Unsupported,
    capability_inventory_revision,
    clarification_decisions_revision,
    decision_sha256,
    default_policy_revision,
    safe_reviewed_projection_revision,
)
from metis_model1.brain_create_builder import (
    CREATE_ENDPOINT_SPEC_CONTRACT,
    CREATE_ENDPOINT_SPEC_SCHEMA,
)
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_intent_ir import IntentCompileRequest, IntentIR
from metis_model1.brain_output_contract import parse_output_request
from metis_model1.brain_protocol import bytes_sha256, canonical_json

HASH_CONTEXT = "sha256:" + "a" * 64
HASH_SEMANTIC = "sha256:" + "b" * 64
HASH_TOOLCHAIN = "sha256:" + "c" * 64
ZERO_HASH = "sha256:" + "0" * 64
HMAC_KEY = b"issuer-test-key-is-at-least-thirty-two-bytes"
SESSION_A = "session_A_123456789012345678901234567890"
SESSION_B = "session_B_123456789012345678901234567890"
MESSAGES = (
    "Crea un endpoint video.",
    "Aggiungi un blocco principale e un blocco di riserva.",
    "Se non ci sono risultati usa il blocco di riserva.",
    "Restituisci 24 film italiani premiati.",
)


def _history(messages: tuple[str, ...] = MESSAGES) -> tuple[CreateAuthorityHistoryMessage, ...]:
    return tuple(
        CreateAuthorityHistoryMessage(
            ordinal=index,
            text=text,
            message_sha256=bytes_sha256(text.encode("utf-8")),
        )
        for index, text in enumerate(messages)
    )


def _span(message_ordinal: int, needle: str) -> tuple[int, int]:
    text = MESSAGES[message_ordinal]
    character_start = text.index(needle)
    start = len(text[:character_start].encode("utf-8"))
    return start, start + len(needle.encode("utf-8"))


def _candidate(
    key: str,
    roles: tuple[str, ...],
    label: str,
    fragment_type: str,
    value: Any,
    *requirement_keys: str,
) -> AuthorityCandidate:
    return AuthorityCandidate(
        key=key,
        roles=roles,
        label=label,
        fragment=TypedFragment(fragment_type, value),
        requirement_keys=requirement_keys,
    )


def _semantic(
    candidate: AuthorityCandidate,
    *,
    state: str = "reviewed",
    domain: str = "finite",
    resolved: bool = True,
) -> ReviewedSemanticAuthority:
    return ReviewedSemanticAuthority(
        authority=candidate,
        state=state,
        domain=domain,  # type: ignore[arg-type]
        resolved=resolved,
    )


def _with_projection_revision(value: SafeReviewedProjection) -> SafeReviewedProjection:
    return replace(value, projection_revision=safe_reviewed_projection_revision(value))


def _with_inventory_revision(value: CapabilityInventory) -> CapabilityInventory:
    return replace(value, inventory_revision=capability_inventory_revision(value))


def _with_policy_revision(value: DefaultPolicy) -> DefaultPolicy:
    return replace(value, policy_revision=default_policy_revision(value))


def _typed_decision(key: str, kind: str, value: Any) -> TypedDecision:
    return TypedDecision(
        key=key,
        kind=kind,
        value=value,
        context_revision=HASH_CONTEXT,
        semantic_revision=HASH_SEMANTIC,
        decision_sha256=decision_sha256(
            key=key,
            kind=kind,
            value=value,
            context_revision=HASH_CONTEXT,
            semantic_revision=HASH_SEMANTIC,
        ),
    )


def _flash() -> tuple[IntentIR, tuple[FlashExactSpan, ...]]:
    source = "film italiani premiati"
    value = {
        "schema_version": 1,
        "operation": "create",
        "target_scope": "new",
        "concept_logic": "all",
        "concepts": [
            {
                "source": source,
                "query": "opere italiane che hanno ricevuto premi",
                "polarity": "include",
            }
        ],
        "response_format": "unspecified",
        "fallback": "change_requested",
        "ambiguities": [],
    }
    parsed = IntentIR.parse(
        value,
        request=IntentCompileRequest(
            instruction=MESSAGES[-1],
            intent="create",
            target_mode="create",
        ),
    )
    start, end = _span(3, source)
    return parsed, (FlashExactSpan(0, 3, start, end),)


def _snapshot(
    *,
    session_id: str = SESSION_A,
    messages: tuple[str, ...] = MESSAGES,
) -> IssuanceSnapshot:
    history = _history(messages)
    flash, flash_spans = _flash()

    semantic = _with_projection_revision(
        SafeReviewedProjection(
            context_revision=HASH_CONTEXT,
            semantic_revision=HASH_SEMANTIC,
            toolchain_binding=HASH_TOOLCHAIN,
            projection_revision=ZERO_HASH,
            status="resolved",
            authorities=(
                _semantic(
                    _candidate(
                        "semantic.catalog.video",
                        ("catalog",),
                        "Catalogo video",
                        "qualifiedIdentifier",
                        "video",
                        "requirement.semantic",
                    )
                ),
                _semantic(
                    _candidate(
                        "semantic.field.country",
                        ("field",),
                        "Paese di produzione",
                        "identifier",
                        "paesiorigine",
                        "requirement.semantic",
                    )
                ),
                _semantic(
                    _candidate(
                        "semantic.value.italy",
                        ("catalog_value",),
                        "Italia",
                        "value",
                        {"kind": "lit", "lexical": "text", "value": "Italia"},
                        "requirement.semantic",
                    )
                ),
                _semantic(
                    _candidate(
                        "semantic.field.awards",
                        ("field",),
                        "Premi ricevuti",
                        "identifier",
                        "categoriecritichestoriche",
                        "requirement.semantic",
                    ),
                    domain="none",
                ),
            ),
        )
    )
    capabilities = _with_inventory_revision(
        CapabilityInventory(
            toolchain_binding=HASH_TOOLCHAIN,
            inventory_revision=ZERO_HASH,
            operation_kinds=(
                "endpoint.create",
                "block.create",
                "query.set_catalog",
                "query.add_predicate",
                "query.set_take",
                "fallback.set",
                "response.set",
            ),
            authorities=(
                _candidate(
                    "cap.endpoint",
                    ("endpoint_slot", "endpoint"),
                    "Endpoint nuovo",
                    "qualifiedIdentifier",
                    "play.brain_demo",
                    "requirement.create",
                ),
                _candidate(
                    "cap.query",
                    ("query",),
                    "Query principale",
                    "identifier",
                    "primary",
                    "requirement.semantic",
                ),
                _candidate(
                    "cap.block.primary",
                    ("block_slot", "block"),
                    "Blocco principale",
                    "identifier",
                    "main",
                    "requirement.blocks",
                    "requirement.structure",
                ),
                _candidate(
                    "cap.block.reserve",
                    ("block_slot", "block"),
                    "Blocco di riserva",
                    "identifier",
                    "reserve",
                    "requirement.blocks",
                    "requirement.fallback",
                ),
                _candidate(
                    "cap.fallback",
                    ("fallback_slot",),
                    "Fallback controllato",
                    "identifier",
                    "fallback",
                    "requirement.fallback",
                ),
                _candidate(
                    "cap.response.slot",
                    ("response_slot",),
                    "Risposta endpoint",
                    "identifier",
                    "response",
                    "requirement.response",
                ),
                _candidate(
                    "cap.response.blocks",
                    ("response_format",),
                    "Formato a blocchi",
                    "identifier",
                    "blocks",
                    "requirement.response",
                ),
            ),
        )
    )
    policy = _with_policy_revision(
        DefaultPolicy(
            toolchain_binding=HASH_TOOLCHAIN,
            policy_revision=ZERO_HASH,
            entries=(
                PolicyDecision(
                    key="policy.response",
                    kind="response_shape",
                    value={"authority_key": "cap.response.blocks"},
                ),
            ),
        )
    )
    structural = _typed_decision(
        "decision.structure",
        "structural_choice",
        {"authority_key": "cap.block.primary"},
    )
    decisions = (structural,)

    create_start, create_end = _span(0, "Crea un endpoint")
    blocks_start, blocks_end = _span(1, "un blocco principale e un blocco di riserva")
    fallback_start, fallback_end = _span(2, "usa il blocco di riserva")
    semantic_start, semantic_end = _span(3, "film italiani premiati")
    requirements = (
        RequirementClaim(
            key="requirement.create",
            label="Creazione endpoint",
            allowed_kinds=("endpoint.create",),
            authority_keys=("cap.endpoint",),
            origin="operator",
            message_ordinal=0,
            start_utf8=create_start,
            end_utf8=create_end,
        ),
        RequirementClaim(
            key="requirement.blocks",
            label="Due blocchi richiesti",
            allowed_kinds=("block.create",),
            authority_keys=("cap.block.primary", "cap.block.reserve"),
            origin="operator",
            message_ordinal=1,
            start_utf8=blocks_start,
            end_utf8=blocks_end,
        ),
        RequirementClaim(
            key="requirement.fallback",
            label="Fallback richiesto",
            allowed_kinds=("fallback.set",),
            authority_keys=("cap.block.reserve", "cap.fallback"),
            origin="operator",
            message_ordinal=2,
            start_utf8=fallback_start,
            end_utf8=fallback_end,
        ),
        RequirementClaim(
            key="requirement.semantic",
            label="Film italiani premiati",
            allowed_kinds=("query.set_catalog", "query.add_predicate"),
            authority_keys=(
                "semantic.catalog.video",
                "semantic.field.country",
                "semantic.value.italy",
                "semantic.field.awards",
                "cap.query",
            ),
            origin="flash",
            message_ordinal=3,
            start_utf8=semantic_start,
            end_utf8=semantic_end,
        ),
        RequirementClaim(
            key="requirement.structure",
            label="Struttura confermata",
            allowed_kinds=("block.create",),
            authority_keys=("cap.block.primary",),
            origin="clarification",
            evidence_key="decision.structure",
        ),
        RequirementClaim(
            key="requirement.response",
            label="Risposta predefinita",
            allowed_kinds=("response.set",),
            authority_keys=("cap.response.slot", "cap.response.blocks"),
            origin="policy",
            evidence_key="policy.response",
        ),
    )
    return IssuanceSnapshot(
        session_id=session_id,
        history=history,
        history_revision=create_authority_history_revision(history),
        clarification_decisions=decisions,
        clarification_revision=clarification_decisions_revision(decisions),
        flash_intent=flash,
        flash_spans=flash_spans,
        semantic_projection=semantic,
        output_request=parse_output_request(messages[-1]),
        capabilities=capabilities,
        default_policy=policy,
        requirements=requirements,
        target=RootAuthority(
            key="root.target",
            label="Destinazione nuova",
            fragment=TypedFragment("qualifiedIdentifier", "play.brain_demo"),
        ),
        basis=None,
        generation=0,
        context_revision=HASH_CONTEXT,
        semantic_revision=HASH_SEMANTIC,
        toolchain_binding=HASH_TOOLCHAIN,
        ambiguities=("structural_choice",),
    )


def _issue(snapshot: IssuanceSnapshot | None = None):
    return CreateAuthorityIssuer(hmac_key=HMAC_KEY).issue(snapshot or _snapshot())


def test_complex_snapshot_issues_complete_private_surface_without_projection_leakage() -> None:
    result = _issue()
    assert isinstance(result, Issued)
    assert result.context_revision == HASH_CONTEXT
    assert result.semantic_revision == HASH_SEMANTIC
    assert result.toolchain_binding == HASH_TOOLCHAIN
    assert result.generation == 0
    projection = result.surface.model_projection()
    assert projection
    assert all(set(item) <= {"ref", "roles", "label", "allowed_kinds"} for item in projection)
    assert all("fragment" not in item for item in projection)
    serialized = canonical_json(projection).decode("utf-8")
    assert "opere italiane che hanno ricevuto premi" not in serialized
    assert "play.brain_demo" not in serialized
    assert "paesiorigine" not in serialized
    assert "Italia" in serialized  # reviewed, bounded human-readable label only

    private = result.private_registry.resolve("semantic.value.italy", required_role="catalog_value")
    assert private == {
        "fragment_kind": "value",
        "fragment": {"kind": "lit", "lexical": "text", "value": "Italia"},
    }
    requirement_ref = result.private_registry.ref_for("requirement.semantic")
    bound = result.private_registry.authority_refs_for_requirement(requirement_ref)
    assert len(bound) == 5
    assert result.surface.expected_requirement_kinds[requirement_ref] == frozenset(
        {"query.set_catalog", "query.add_predicate"}
    )
    requirement_projection = next(item for item in projection if item["ref"] == requirement_ref)
    assert requirement_projection["allowed_kinds"] == [
        "query.add_predicate",
        "query.set_catalog",
    ]


def test_same_snapshot_is_deterministic_and_session_scopes_every_reference() -> None:
    first = _issue()
    second = _issue()
    other_session = _issue(_snapshot(session_id=SESSION_B))
    assert isinstance(first, Issued)
    assert isinstance(second, Issued)
    assert isinstance(other_session, Issued)
    assert first.surface.surface_revision == second.surface.surface_revision
    assert first.surface.model_projection() == second.surface.model_projection()
    assert first.surface.surface_revision != other_session.surface.surface_revision
    assert {item["ref"] for item in first.surface.model_projection()}.isdisjoint(
        item["ref"] for item in other_session.surface.model_projection()
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "source",
        "path",
        "file",
        "template",
        "golden",
        "endpoint_templates",
        "at",
        "provenance",
    ],
)
def test_recursive_unsafe_semantic_or_capability_keys_fail_closed(forbidden: str) -> None:
    snapshot = _snapshot()
    candidate = snapshot.semantic_projection.authorities[2].authority
    unsafe = replace(
        candidate,
        fragment=TypedFragment(
            "value",
            {
                "kind": "lit",
                "lexical": "text",
                "value": "Italia",
                "nested": {forbidden: "secret"},
            },
        ),
    )
    authorities = list(snapshot.semantic_projection.authorities)
    authorities[2] = replace(authorities[2], authority=unsafe)
    provisional = replace(
        snapshot.semantic_projection,
        authorities=tuple(authorities),
        projection_revision=ZERO_HASH,
    )
    result = _issue(replace(snapshot, semantic_projection=provisional))
    assert isinstance(result, Unsupported)
    assert result.code == "UNSAFE_AUTHORITY"


@pytest.mark.parametrize(
    ("state", "domain", "resolved", "code"),
    [
        ("draft", "finite", True, "SEMANTIC_NOT_REVIEWED"),
        ("unannotated", "finite", True, "SEMANTIC_NOT_REVIEWED"),
        ("reviewed", "finite", False, "SEMANTIC_UNRESOLVED"),
        ("reviewed", "open", False, "OPEN_DOMAIN_UNRESOLVED"),
    ],
)
def test_nonreviewed_and_unresolved_semantics_never_issue_partial_surface(
    state: str,
    domain: str,
    resolved: bool,
    code: str,
) -> None:
    snapshot = _snapshot()
    authorities = list(snapshot.semantic_projection.authorities)
    authorities[0] = replace(
        authorities[0],
        state=state,
        domain=domain,  # type: ignore[arg-type]
        resolved=resolved,
    )
    provisional = replace(
        snapshot.semantic_projection,
        authorities=tuple(authorities),
        projection_revision=ZERO_HASH,
    )
    projection = replace(
        provisional,
        projection_revision=safe_reviewed_projection_revision(provisional),
    )
    result = _issue(replace(snapshot, semantic_projection=projection))
    expected_reason = (
        "semantic authority is not reviewed"
        if state != "reviewed"
        else "semantic authority is unresolved"
    )
    assert result == Unsupported(code, expected_reason)
    assert not isinstance(result, Issued)


def test_flash_must_bind_every_concept_to_current_exact_utf8_span() -> None:
    snapshot = _snapshot()
    drifted = replace(snapshot.flash_spans[0], start_utf8=snapshot.flash_spans[0].start_utf8 + 1)
    result = _issue(replace(snapshot, flash_spans=(drifted,)))
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_FLASH"

    unicode_messages = (*MESSAGES[:-1], "Restituisci 24 film premiati è italiani.")
    history = _history(unicode_messages)
    start = len(b"Restituisci 24 film premiati ")
    split = RequirementClaim(
        key="requirement.unicode",
        label="Span unicode",
        allowed_kinds=("query.set_take",),
        authority_keys=(),
        origin="operator",
        message_ordinal=3,
        start_utf8=start,
        end_utf8=start + 1,
    )
    no_flash = replace(
        snapshot,
        history=history,
        history_revision=create_authority_history_revision(history),
        flash_intent=None,
        flash_spans=(),
        output_request=parse_output_request(unicode_messages[-1]),
        requirements=(
            *(
                replace(
                    requirement,
                    origin="operator",
                    start_utf8=start + 2,
                    end_utf8=len(unicode_messages[-1].encode("utf-8")),
                )
                if requirement.key == "requirement.semantic"
                else requirement
                for requirement in snapshot.requirements
            ),
            split,
        ),
    )
    result = _issue(no_flash)
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_EVIDENCE"


@pytest.mark.parametrize(
    "mutation",
    [
        "history",
        "semantic_binding",
        "semantic_projection",
        "capabilities",
        "policy",
        "clarifications",
    ],
)
def test_any_revision_drift_fails_closed(mutation: str) -> None:
    snapshot = _snapshot()
    if mutation == "history":
        snapshot = replace(snapshot, history_revision=ZERO_HASH)
    elif mutation == "semantic_binding":
        snapshot = replace(snapshot, semantic_revision="sha256:" + "d" * 64)
    elif mutation == "semantic_projection":
        snapshot = replace(
            snapshot,
            semantic_projection=replace(
                snapshot.semantic_projection,
                projection_revision=ZERO_HASH,
            ),
        )
    elif mutation == "capabilities":
        snapshot = replace(
            snapshot,
            capabilities=replace(snapshot.capabilities, inventory_revision=ZERO_HASH),
        )
    elif mutation == "policy":
        snapshot = replace(
            snapshot,
            default_policy=replace(snapshot.default_policy, policy_revision=ZERO_HASH),
        )
    else:
        snapshot = replace(snapshot, clarification_revision=ZERO_HASH)
    result = _issue(snapshot)
    assert isinstance(result, Unsupported)
    assert "DRIFT" in result.code


def test_output_and_unresolved_dimensions_return_closed_clarification_union() -> None:
    snapshot = _snapshot()
    policy = _with_policy_revision(
        replace(snapshot.default_policy, entries=(), policy_revision=ZERO_HASH)
    )
    capabilities = tuple(
        replace(candidate, requirement_keys=())
        if candidate.key in {"cap.response.slot", "cap.response.blocks"}
        else candidate
        for candidate in snapshot.capabilities.authorities
    )
    inventory = _with_inventory_revision(
        replace(
            snapshot.capabilities,
            authorities=capabilities,
            inventory_revision=ZERO_HASH,
        )
    )
    requirements = tuple(
        item for item in snapshot.requirements if item.key != "requirement.response"
    )
    result = _issue(
        replace(
            snapshot,
            default_policy=policy,
            capabilities=inventory,
            requirements=requirements,
        )
    )
    assert result == NeedsClarification(("response_shape",))

    messages = (*MESSAGES[:-1], "Restituisci alcuni film italiani premiati.")
    history = _history(messages)
    source = "film italiani premiati"
    start = len(messages[-1][: messages[-1].index(source)].encode("utf-8"))
    flash_value = copy.deepcopy(snapshot.flash_intent.value)
    flash_value["concepts"][0]["source"] = source
    flash = IntentIR.parse(
        flash_value,
        request=IntentCompileRequest(
            instruction=messages[-1], intent="create", target_mode="create"
        ),
    )
    result = _issue(
        replace(
            snapshot,
            history=history,
            history_revision=create_authority_history_revision(history),
            flash_intent=flash,
            flash_spans=(FlashExactSpan(0, 3, start, start + len(source.encode("utf-8"))),),
            output_request=parse_output_request(messages[-1]),
        )
    )
    assert result == NeedsClarification(("result_count",))


def test_typed_result_count_decision_resolves_ambiguous_operator_output() -> None:
    snapshot = _snapshot()
    messages = (*MESSAGES[:-1], "Restituisci alcuni film italiani premiati.")
    history = _history(messages)
    source = "film italiani premiati"
    start = len(messages[-1][: messages[-1].index(source)].encode("utf-8"))
    flash_value = copy.deepcopy(snapshot.flash_intent.value)
    flash_value["concepts"][0]["source"] = source
    flash = IntentIR.parse(
        flash_value,
        request=IntentCompileRequest(
            instruction=messages[-1], intent="create", target_mode="create"
        ),
    )
    count = _typed_decision(
        "decision.count",
        "result_count",
        {"mode": "count", "value": 24},
    )
    decisions = (*snapshot.clarification_decisions, count)
    requirements = tuple(
        replace(
            requirement,
            start_utf8=start,
            end_utf8=start + len(source.encode("utf-8")),
        )
        if requirement.key == "requirement.semantic"
        else requirement
        for requirement in snapshot.requirements
    )
    result = _issue(
        replace(
            snapshot,
            history=history,
            history_revision=create_authority_history_revision(history),
            clarification_decisions=decisions,
            clarification_revision=clarification_decisions_revision(decisions),
            flash_intent=flash,
            flash_spans=(FlashExactSpan(0, 3, start, start + len(source.encode("utf-8"))),),
            output_request=parse_output_request(messages[-1]),
            requirements=requirements,
        )
    )
    assert isinstance(result, Issued)
    requirement_ref = result.private_registry.ref_for("output.contract")
    assert result.surface.expected_requirement_kinds[requirement_ref] == frozenset(
        {"query.set_take"}
    )


def test_page_decision_never_grants_total_take_authority() -> None:
    snapshot = _snapshot()
    messages = (*MESSAGES[:-1], "Restituisci alcuni film italiani premiati.")
    history = _history(messages)
    source = "film italiani premiati"
    start = len(messages[-1][: messages[-1].index(source)].encode("utf-8"))
    flash_value = copy.deepcopy(snapshot.flash_intent.value)
    flash_value["concepts"][0]["source"] = source
    flash = IntentIR.parse(
        flash_value,
        request=IntentCompileRequest(
            instruction=messages[-1], intent="create", target_mode="create"
        ),
    )
    page = _typed_decision("decision.page", "result_count", {"mode": "page", "value": 24})
    decisions = (*snapshot.clarification_decisions, page)
    capabilities = _with_inventory_revision(
        replace(
            snapshot.capabilities,
            operation_kinds=(*snapshot.capabilities.operation_kinds, "query.set_pagination"),
            inventory_revision=ZERO_HASH,
        )
    )
    requirements = tuple(
        replace(
            requirement,
            start_utf8=start,
            end_utf8=start + len(source.encode("utf-8")),
        )
        if requirement.key == "requirement.semantic"
        else requirement
        for requirement in snapshot.requirements
    )
    result = _issue(
        replace(
            snapshot,
            history=history,
            history_revision=create_authority_history_revision(history),
            clarification_decisions=decisions,
            clarification_revision=clarification_decisions_revision(decisions),
            flash_intent=flash,
            flash_spans=(FlashExactSpan(0, 3, start, start + len(source.encode("utf-8"))),),
            output_request=parse_output_request(messages[-1]),
            requirements=requirements,
            capabilities=capabilities,
        )
    )
    assert isinstance(result, Issued)
    requirement_ref = result.private_registry.ref_for("output.contract")
    assert result.surface.expected_requirement_kinds[requirement_ref] == frozenset(
        {"query.set_pagination"}
    )


def test_refinement_preserves_latest_exact_output_contract_from_cumulative_history() -> None:
    snapshot = _snapshot()
    messages = (*MESSAGES, "Rendi il titolo del blocco principale più chiaro.")
    history = _history(messages)
    requirements = tuple(
        replace(requirement, origin="operator")
        if requirement.key == "requirement.semantic"
        else requirement
        for requirement in snapshot.requirements
    )
    result = _issue(
        replace(
            snapshot,
            history=history,
            history_revision=create_authority_history_revision(history),
            flash_intent=None,
            flash_spans=(),
            output_request=parse_output_request(messages[-1]),
            requirements=requirements,
        )
    )
    assert isinstance(result, Issued)
    requirement_ref = result.private_registry.ref_for("output.contract")
    assert result.surface.expected_requirement_kinds[requirement_ref] == frozenset(
        {"query.set_take"}
    )


def test_clarification_decisions_are_revision_and_role_bound() -> None:
    snapshot = _snapshot()
    wrong_role = _typed_decision(
        "decision.structure",
        "structural_choice",
        {"authority_key": "semantic.value.italy"},
    )
    decisions = (wrong_role,)
    result = _issue(
        replace(
            snapshot,
            clarification_decisions=decisions,
            clarification_revision=clarification_decisions_revision(decisions),
        )
    )
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_DECISION"

    original = snapshot.clarification_decisions[0]
    foreign_context = "sha256:" + "d" * 64
    stale = replace(
        original,
        context_revision=foreign_context,
        decision_sha256=decision_sha256(
            key=original.key,
            kind=original.kind,
            value=original.value,
            context_revision=foreign_context,
            semantic_revision=original.semantic_revision,
        ),
    )
    decisions = (stale,)
    result = _issue(
        replace(
            snapshot,
            clarification_decisions=decisions,
            clarification_revision=clarification_decisions_revision(decisions),
        )
    )
    assert isinstance(result, Unsupported)
    assert result.code == "REVISION_DRIFT"


def test_every_flash_concept_requires_an_exact_flash_requirement() -> None:
    snapshot = _snapshot()
    requirements = tuple(
        replace(requirement, origin="operator")
        if requirement.key == "requirement.semantic"
        else requirement
        for requirement in snapshot.requirements
    )
    result = _issue(replace(snapshot, requirements=requirements))
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_FLASH"


def test_active_clarification_kinds_are_unique_and_selected_authority_is_bound() -> None:
    snapshot = _snapshot()
    duplicate_kind = _typed_decision(
        "decision.structure.second",
        "structural_choice",
        {"authority_key": "cap.block.reserve"},
    )
    decisions = (*snapshot.clarification_decisions, duplicate_kind)
    result = _issue(
        replace(
            snapshot,
            clarification_decisions=decisions,
            clarification_revision=clarification_decisions_revision(decisions),
        )
    )
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_DECISION"

    requirements = tuple(
        replace(requirement, authority_keys=("cap.block.reserve",))
        if requirement.key == "requirement.structure"
        else requirement
        for requirement in snapshot.requirements
    )
    capabilities = tuple(
        replace(
            candidate,
            requirement_keys=tuple(
                item for item in candidate.requirement_keys if item != "requirement.structure"
            ),
        )
        if candidate.key == "cap.block.primary"
        else replace(
            candidate,
            requirement_keys=(*candidate.requirement_keys, "requirement.structure"),
        )
        if candidate.key == "cap.block.reserve"
        else candidate
        for candidate in snapshot.capabilities.authorities
    )
    inventory = _with_inventory_revision(
        replace(
            snapshot.capabilities,
            authorities=capabilities,
            inventory_revision=ZERO_HASH,
        )
    )
    result = _issue(replace(snapshot, requirements=requirements, capabilities=inventory))
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_EVIDENCE"


def test_logical_namespaces_cannot_overwrite_private_registry_entries() -> None:
    snapshot = _snapshot()
    result = _issue(replace(snapshot, target=replace(snapshot.target, key="cap.endpoint")))
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_AUTHORITY"


def test_requirement_omission_wrong_authority_or_unsupported_operation_fails_closed() -> None:
    snapshot = _snapshot()
    omitted = replace(snapshot, requirements=snapshot.requirements[:-1])
    result = _issue(omitted)
    assert isinstance(result, Unsupported)
    assert result.code in {"INVALID_AUTHORITY", "MISSING_REQUIREMENT"}

    wrong = list(snapshot.requirements)
    wrong[0] = replace(wrong[0], authority_keys=("semantic.value.italy",))
    result = _issue(replace(snapshot, requirements=tuple(wrong)))
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_AUTHORITY"

    unsupported = list(snapshot.requirements)
    unsupported[0] = replace(unsupported[0], allowed_kinds=("input.declare",))
    result = _issue(replace(snapshot, requirements=tuple(unsupported)))
    assert isinstance(result, Unsupported)
    assert result.code == "UNSUPPORTED_OPERATION"


def test_toolchain_inventory_is_exactly_builder_pinned_and_no_reference_bytes_are_allowed() -> None:
    snapshot = _snapshot()
    assert snapshot.capabilities.builder_contract == CREATE_ENDPOINT_SPEC_CONTRACT
    assert snapshot.capabilities.builder_schema_sha256 == bytes_sha256(
        canonical_json(CREATE_ENDPOINT_SPEC_SCHEMA)
    )
    drift = replace(snapshot.capabilities, toolchain_binding="sha256:" + "d" * 64)
    result = _issue(replace(snapshot, capabilities=drift))
    assert isinstance(result, Unsupported)
    assert result.code == "TOOLCHAIN_DRIFT"

    capabilities = list(snapshot.capabilities.authorities)
    capabilities[0] = replace(
        capabilities[0],
        fragment=TypedFragment("qualifiedIdentifier", {"source": "endpoint hidden"}),
    )
    provisional = replace(
        snapshot.capabilities,
        authorities=tuple(capabilities),
        inventory_revision=ZERO_HASH,
    )
    # Revision helpers also apply the recursive no-leak policy.
    with pytest.raises(Exception, match="forbidden private-source key"):
        capability_inventory_revision(provisional)


def test_generation_requires_exact_basis_and_root_fragments_are_builder_typed() -> None:
    snapshot = _snapshot()
    result = _issue(replace(snapshot, generation=1))
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_LINEAGE"

    basis = RootAuthority(
        key="root.basis",
        label="Bozza precedente",
        fragment=TypedFragment("qualifiedIdentifier", "play.brain_demo"),
    )
    result = _issue(replace(snapshot, generation=1, basis=basis))
    assert isinstance(result, Issued)
    assert result.surface.basis_ref is not None

    unsafe_root = replace(
        snapshot.target,
        fragment=TypedFragment("value", {"kind": "lit", "lexical": "text", "value": "x"}),
    )
    result = _issue(replace(snapshot, target=unsafe_root))
    assert isinstance(result, Unsupported)
    assert result.code == "INVALID_FRAGMENT"


def test_public_boundary_converts_malformed_objects_to_unsupported_without_surface() -> None:
    assert isinstance(_issue("not-a-snapshot"), Unsupported)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="HMAC key"):
        CreateAuthorityIssuer(hmac_key=b"short")
