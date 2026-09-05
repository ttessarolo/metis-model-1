from __future__ import annotations

import copy
import threading
from dataclasses import replace

import pytest

import metis_model1.brain_create_authority_provider_impl_v2 as provider_impl
from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_create_authority_provider_impl_v2 import (
    PinnedCreateV2AuthorityProvider,
)
from metis_model1.brain_create_authority_provider_v2 import (
    AskCreateV2Authority,
    ReadyCreateV2Authority,
)
from metis_model1.brain_create_plan_v2 import NodeGrant
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    BoundDecision,
    DialogueBinding,
    PrivateDialogueState,
)
from metis_model1.brain_dialogue_planner import QuantityNeed
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_turns import TurnRequest

TOOLCHAIN = bytes_sha256(b"descriptor-provider-toolchain")
SESSION_ID = "d" * 43


def _inputs(
    messages: tuple[str, ...],
    *,
    tenant: str = "synth-aurora",
    catalog: str = "aurora.signal",
    field: str = "signal_band",
    literal: str = "amber",
    field_state: str = "reviewed",
    value_present: bool = True,
    context_revision: str | None = None,
    duplicate_short_catalog: str | None = None,
) -> tuple[OperationLease, TurnRequest, PrivateDialogueState, RetrievalResult]:
    source = "\n".join(
        f"catalog {name} {{ fields {{ {field} keyword }} }}"
        for name in (catalog, duplicate_short_catalog)
        if name is not None
    ).encode()
    snapshot = ContextSnapshot(
        tenant_alias=tenant,
        tenant_id=f"tenant-{tenant}",
        root_device=1,
        root_inode=2,
        revision=bytes_sha256(f"context:{tenant}".encode()),
        toolchain_binding=TOOLCHAIN,
        files=(SnapshotFile("catalogs/synthetic.metis", source, bytes_sha256(source)),),
        total_bytes=len(source),
    )
    semantic_revision = snapshot.semantic_source_revision()
    history = tuple(
        CreateAuthorityHistoryMessage(index, text, bytes_sha256(text.encode()))
        for index, text in enumerate(messages)
    )
    binding = DialogueBinding(
        context_revision=snapshot.revision,
        semantic_revision=semantic_revision,
        toolchain_binding=TOOLCHAIN,
        history_revision=create_authority_history_revision(history),
        parent_fingerprint=bytes_sha256(b"descriptor-provider-parent"),
    )
    dialogue = PrivateDialogueState(
        conversation_id=bytes_sha256(f"conversation:{tenant}".encode()),
        binding=binding,
        messages=history,
    )
    request = TurnRequest(
        schema_version=2,
        request_id="descriptor-provider-0001",
        expected_context_revision=snapshot.revision,
        expected_semantic_source_revision=semantic_revision,
        intent="create",
        instruction=messages[-1],
        target={
            "mode": "create",
            "relative_path": "brain-drafts/synthetic.metis",
            "endpoint": "synthetic.collection",
            "base_sha256": None,
            "reference": None,
        },
        basis=None,
        clarification_response=None,
        server_dialogue=dialogue,
    )
    domain = {"kind": "enum", "size": 1}
    state = {"state": field_state}
    values = [{"literal": literal, "semantic": {"state": "reviewed"}}] if value_present else []
    selection = {
        "catalog": catalog,
        "field": field,
        "literal": literal,
        "type": "keyword",
        "modifiers": [],
        "domain": domain,
    }
    retrieved = RetrievalResult(
        context={
            "semantic_schema": 2,
            "catalog_reference_roster": [
                name for name in (catalog, duplicate_short_catalog) if name
            ],
            "context_revision": context_revision or snapshot.revision,
            "semantic_source_revision": semantic_revision,
            "toolchain_binding": TOOLCHAIN,
            "catalog": {"name": catalog, "semantic": {"state": "reviewed"}},
            "fields": [
                {
                    "name": field,
                    "type": "keyword",
                    "modifiers": [],
                    "domain": domain,
                    "semantic": state,
                    "values": values,
                }
            ],
        },
        grounding={
            "status": "resolved",
            "catalogs": [catalog],
            "selections": [selection],
            "resolutions": [
                {
                    "catalog": catalog,
                    "field": field,
                    "literal": literal,
                    "review_state": "reviewed",
                }
            ],
            "candidates": [],
            "unresolved": [],
            "lookups": [],
            "lookup": None,
        },
        semantic_source_revision=semantic_revision,
    )
    lease = OperationLease(
        session_id=SESSION_ID,
        client_id="vsix",
        tenant_alias=tenant,
        capabilities=frozenset({"create"}),
        snapshot=snapshot,
        cancellation=threading.Event(),
    )
    return lease, request, dialogue, retrieved


def _provider() -> PinnedCreateV2AuthorityProvider:
    return PinnedCreateV2AuthorityProvider(hmac_key=b"d" * 32, toolchain_binding=TOOLCHAIN)


def _bound_filter_choice(
    dialogue: PrivateDialogueState,
    ask: AskCreateV2Authority,
    *,
    choice_index: int = 0,
) -> PrivateDialogueState:
    slot = ask.slots[0]
    choice = replace(slot.choices[choice_index], option_ref="opt_descriptor_filtered")
    first_binding = replace(
        dialogue.binding,
        history_revision=create_authority_history_revision(dialogue.messages[:1]),
    )
    decision = BoundDecision(
        decision_key=slot.decision_key,
        target_key=slot.target_key,
        kind=slot.kind,
        question_ref="q_descriptor_filtered",
        answer_kind="option_ref",
        binding=first_binding,
        choices=(choice,),
    )
    return replace(dialogue, decisions=(decision,))


def _count_decision(
    dialogue: PrivateDialogueState,
    *,
    count: int,
    question_ref: str,
    supersedes: str | None = None,
) -> BoundDecision:
    slot = QuantityNeed(target_key="endpoint.results.total", necessary=True).slot()
    return BoundDecision(
        decision_key=slot.decision_key,
        target_key=slot.target_key,
        kind=slot.kind,
        question_ref=question_ref,
        answer_kind="integer",
        binding=dialogue.binding,
        integer=count,
        supersedes=supersedes,
        value_contract=slot.value_contract,
    )


def _prepare(
    provider: PinnedCreateV2AuthorityProvider,
    inputs: tuple[OperationLease, TurnRequest, PrivateDialogueState, RetrievalResult],
):
    lease, request, dialogue, retrieved = inputs
    return provider.prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=None,
    )


@pytest.mark.parametrize(
    ("tenant", "catalog", "field", "literal"),
    (
        ("synth-aurora", "aurora.signal", "signal_band", "amber"),
        ("synth-cobalt", "cobalt.archive", "mood_code", "indigo"),
    ),
)
def test_default_descriptor_provider_asks_then_issues_only_the_bound_filtered_collection(
    tenant: str,
    catalog: str,
    field: str,
    literal: str,
) -> None:
    provider = _provider()
    initial = _inputs(
        ("Crea una collezione filtrata con 17 risultati totali.",),
        tenant=tenant,
        catalog=catalog,
        field=field,
        literal=literal,
    )
    ask = _prepare(provider, initial)

    assert type(ask) is AskCreateV2Authority
    assert len(ask.slots) == 1
    assert ask.slots[0].decision_key == "choice.structure.descriptor_filtered_collection"
    assert ask.slots[0].target_key == "structure.descriptor_filtered_collection"
    assert ask.slots[0].answer_kind == "option_ref"
    assert len(ask.slots[0].choices) == 2

    complete = _inputs(
        ("Crea una collezione filtrata con 17 risultati totali.",),
        tenant=tenant,
        catalog=catalog,
        field=field,
        literal=literal,
    )
    complete = (complete[0], complete[1], _bound_filter_choice(complete[2], ask), complete[3])
    assert not hasattr(provider_impl, "presemantic_structural_need")
    ready = _prepare(provider, complete)

    assert type(ready) is ReadyCreateV2Authority
    assert ready.generation == 0
    assert ready.active_requirement_handles == (0, 1)
    assert len(ready.projection.requirements) == 2
    assert len(ready.projection.authorities) == 4
    node = next(item for item in ready.projection.authorities if type(item) is NodeGrant)
    fetch = node.fragment["fetches"][0]
    assert fetch["from"] == {"kind": "catalog", "catalog": catalog.rsplit(".", 1)[-1]}
    assert fetch["cardinality"] == {"mode": "total", "value": 17}
    assert fetch["clauses"] == [
        {
            "intent": "include",
            "where": [
                {
                    "op": "eq",
                    "field": field,
                    "value": {"kind": "lit", "lexical": "text", "value": literal},
                }
            ],
        }
    ]
    assert fetch["over_fetch"] is None
    assert fetch["order"] == []
    assert fetch["group_by"] is None
    assert fetch["output"] is None

    model_payload = ready.projection.model_projection_payload()
    assert model_payload["q"] == [
        {
            "h": 0,
            "l": "Aggiungi collezione filtrata dai descrittori revisionati",
            "o": ["attach"],
        },
        {"h": 1, "l": "Emetti la collezione filtrata nella risposta", "o": ["attach"]},
    ]
    assert model_payload["s"] == [
        {
            "h": 10,
            "l": "Destinazione aggiungi collezione filtrata dai descrittori revisionati",
            "a": ["container"],
            "m": ["attach"],
            "c": "many",
            "i": "append",
            "g": "blocks",
        },
        {
            "h": 12,
            "l": "Destinazione emetti la collezione filtrata nella risposta",
            "a": ["variant"],
            "m": ["attach"],
            "c": "many",
            "i": "append",
            "g": "variants",
        },
    ]
    assert model_payload["n"] == [
        {
            "h": 11,
            "l": "Aggiungi collezione filtrata dai descrittori revisionati",
            "t": "container",
            "s": "new",
            "d": False,
        },
        {
            "h": 13,
            "l": "Emetti la collezione filtrata nella risposta",
            "t": "variant",
            "s": "new",
            "d": False,
        },
    ]
    assert model_payload["r"] == [] and model_payload["w"] == []
    rendered = canonical_json(model_payload).decode("utf-8")
    for domain_identity in (tenant, catalog, field, literal, "hostref:", "fragment", "evidence"):
        assert domain_identity not in rendered


@pytest.mark.parametrize("fault", ("missing", "draft", "stale"))
def test_descriptor_provider_rejects_missing_draft_and_stale_authority(fault: str) -> None:
    initial = _inputs(("Crea una collezione filtrata con 17 risultati totali.",))
    ask = _prepare(_provider(), initial)
    assert type(ask) is AskCreateV2Authority
    complete = _inputs(("Crea una collezione filtrata con 17 risultati totali.",))
    dialogue = _bound_filter_choice(complete[2], ask)
    lease, request, _dialogue, retrieved = complete

    if fault == "missing":
        _lease, _request, dialogue, retrieved = _inputs(
            ("Crea una collezione filtrata con 17 risultati totali.",), value_present=False
        )
        dialogue = _bound_filter_choice(dialogue, ask)
    elif fault == "draft":
        _lease, _request, dialogue, retrieved = _inputs(
            ("Crea una collezione filtrata con 17 risultati totali.",), field_state="draft"
        )
        dialogue = _bound_filter_choice(dialogue, ask)
    elif fault == "stale":
        context = copy.deepcopy(retrieved.context)
        context["context_revision"] = bytes_sha256(b"stale-context")
        retrieved = replace(retrieved, context=context)
    with pytest.raises(BrainError) as caught:
        _provider().prepare(
            session_id=SESSION_ID,
            lease=lease,
            request=request,
            dialogue=dialogue,
            retrieved=retrieved,
            basis=None,
        )

    assert caught.value.code == (
        "CREATE_TYPED_AUTHORITY_STALE" if fault == "stale" else "CREATE_TYPED_AUTHORITY_UNSUPPORTED"
    )


def test_descriptor_provider_asks_for_an_exact_total_before_structural_confirmation() -> None:
    result = _prepare(_provider(), _inputs(("Crea una collezione filtrata.",)))

    assert type(result) is AskCreateV2Authority
    assert len(result.slots) == 1
    assert result.slots[0].kind == "result_count"
    assert result.slots[0].target_key == "endpoint.results.total"
    assert result.slots[0].answer_kind == "integer"


def test_descriptor_provider_rejects_a_nonexclusive_bound_choice() -> None:
    initial = _inputs(("Crea una collezione filtrata con 17 risultati totali.",))
    ask = _prepare(_provider(), initial)
    assert type(ask) is AskCreateV2Authority
    lease, request, dialogue, retrieved = _inputs(
        ("Crea una collezione filtrata con 17 risultati totali.",)
    )
    first_binding = replace(
        dialogue.binding,
        history_revision=create_authority_history_revision(dialogue.messages[:1]),
    )
    decision = BoundDecision(
        decision_key=ask.slots[0].decision_key,
        target_key=ask.slots[0].target_key,
        kind=ask.slots[0].kind,
        question_ref="q_descriptor_ambiguous",
        answer_kind="option_refs",
        binding=first_binding,
        choices=tuple(
            replace(choice, option_ref=f"opt_descriptor_{index}")
            for index, choice in enumerate(ask.slots[0].choices)
        ),
    )
    dialogue = replace(dialogue, decisions=(decision,))

    with pytest.raises(BrainError) as caught:
        _provider().prepare(
            session_id=SESSION_ID,
            lease=lease,
            request=request,
            dialogue=dialogue,
            retrieved=retrieved,
            basis=None,
        )

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_INVALID"


def test_descriptor_provider_rejects_a_wrong_bound_decision_kind() -> None:
    initial = _inputs(("Crea una collezione filtrata con 17 risultati totali.",))
    ask = _prepare(_provider(), initial)
    assert type(ask) is AskCreateV2Authority
    lease, request, dialogue, retrieved = _inputs(
        ("Crea una collezione filtrata con 17 risultati totali.",)
    )
    choice = replace(ask.slots[0].choices[0], option_ref="opt_descriptor_wrong_kind")
    decision = BoundDecision(
        decision_key=ask.slots[0].decision_key,
        target_key=ask.slots[0].target_key,
        kind="catalog",
        question_ref="q_descriptor_wrong_kind",
        answer_kind="option_ref",
        binding=dialogue.binding,
        choices=(choice,),
    )
    dialogue = replace(dialogue, decisions=(decision,))

    with pytest.raises(BrainError) as caught:
        _provider().prepare(
            session_id=SESSION_ID,
            lease=lease,
            request=request,
            dialogue=dialogue,
            retrieved=retrieved,
            basis=None,
        )

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_INVALID"


def test_superseded_count_decision_rebinds_the_final_confirmation() -> None:
    initial = _inputs(("Crea una collezione filtrata.",))
    first = _prepare(_provider(), initial)
    assert type(first) is AskCreateV2Authority
    assert first.slots[0].kind == "result_count"
    initial_count = _count_decision(initial[2], count=24, question_ref="q_count_24")

    lease, request, dialogue, retrieved = _inputs(
        ("Crea una collezione filtrata.", "12 risultati totali.")
    )
    replacement = _count_decision(
        dialogue,
        count=12,
        question_ref="q_count_12",
        supersedes=initial_count.decision_sha256,
    )
    dialogue = replace(dialogue, decisions=(initial_count, replacement))

    result = _provider().prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=None,
    )

    assert type(result) is AskCreateV2Authority
    assert len(result.slots) == 1
    assert result.slots[0].kind == "structural_choice"
    assert "12 risultati totali" in result.slots[0].choices[0].description
    assert "24 risultati totali" not in result.slots[0].choices[0].description


def test_descriptor_defer_choice_is_an_explicit_unsupported_outcome() -> None:
    initial = _inputs(("Crea una collezione filtrata con 17 risultati totali.",))
    ask = _prepare(_provider(), initial)
    assert type(ask) is AskCreateV2Authority
    complete = _inputs(("Crea una collezione filtrata con 17 risultati totali.",))
    complete = (
        complete[0],
        complete[1],
        _bound_filter_choice(complete[2], ask, choice_index=1),
        complete[3],
    )

    with pytest.raises(BrainError) as caught:
        _prepare(_provider(), complete)

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"


def test_duplicate_terminal_catalog_reference_is_not_authorized() -> None:
    inputs = _inputs(
        ("Crea una collezione filtrata con 17 risultati totali.",),
        catalog="aurora.signal",
        duplicate_short_catalog="cobalt.signal",
    )

    with pytest.raises(BrainError) as caught:
        _prepare(_provider(), inputs)

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"


def test_descriptor_choice_cannot_be_reused_after_the_selected_value_changes() -> None:
    initial = _inputs(("Crea una collezione filtrata con 17 risultati totali.",), literal="amber")
    ask = _prepare(_provider(), initial)
    assert type(ask) is AskCreateV2Authority
    lease, request, dialogue, retrieved = _inputs(
        ("Crea una collezione filtrata con 17 risultati totali.",), literal="indigo"
    )
    dialogue = _bound_filter_choice(dialogue, ask)

    with pytest.raises(BrainError) as caught:
        _provider().prepare(
            session_id=SESSION_ID,
            lease=lease,
            request=request,
            dialogue=dialogue,
            retrieved=retrieved,
            basis=None,
        )

    assert caught.value.code == "CREATE_TYPED_AUTHORITY_INVALID"


def test_descriptor_choice_is_reasked_after_later_structure_text() -> None:
    initial = _inputs(("Crea una collezione filtrata con 17 risultati totali.",))
    ask = _prepare(_provider(), initial)
    assert type(ask) is AskCreateV2Authority
    lease, request, dialogue, retrieved = _inputs(
        (
            "Crea una collezione filtrata con 17 risultati totali.",
            "Aggiungi paginazione e fallback.",
        )
    )
    dialogue = _bound_filter_choice(dialogue, ask)

    result = _provider().prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=None,
    )

    assert type(result) is AskCreateV2Authority
    assert len(result.slots) == 1
    assert result.slots[0].decision_key == "choice.structure.descriptor_filtered_collection"


def test_descriptor_choice_accepts_only_a_pure_appended_label_response() -> None:
    first_text = "Crea una collezione filtrata con 17 risultati totali."
    initial = _inputs((first_text,))
    ask = _prepare(_provider(), initial)
    assert type(ask) is AskCreateV2Authority
    label = ask.slots[0].choices[0].label
    lease, request, dialogue, retrieved = _inputs((first_text, label))
    dialogue = _bound_filter_choice(dialogue, ask)

    accepted = _provider().prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=None,
    )

    assert type(accepted) is ReadyCreateV2Authority

    lease, request, dialogue, retrieved = _inputs(
        (first_text, label, "Aggiungi paginazione e fallback.")
    )
    dialogue = _bound_filter_choice(dialogue, ask)
    reasked = _provider().prepare(
        session_id=SESSION_ID,
        lease=lease,
        request=request,
        dialogue=dialogue,
        retrieved=retrieved,
        basis=None,
    )

    assert type(reasked) is AskCreateV2Authority
    assert reasked.slots[0].decision_key == "choice.structure.descriptor_filtered_collection"
