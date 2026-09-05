"""Real provider/engine/permit/executor integration on renamed synthetic tenants.

No construction validator is replaced. The retrieval index uses synthetic
Schema2 and technical declarations; parent IR receipts are explicitly synthetic
test receipts, not compiler evidence. L0 separately owns the pinned compiler gate.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import replace
from typing import Any

import pytest
from test_brain_technical_authority import _fixture

from metis_model1.brain_clarifications import ClarificationStore
from metis_model1.brain_context import SnapshotFile
from metis_model1.brain_create_authority_provider_impl_v2 import PinnedCreateV2AuthorityProvider
from metis_model1.brain_create_authority_provider_v2 import (
    AskCreateV2Authority,
    PrivateCreateV2Basis,
    ReadyCreateV2Authority,
)
from metis_model1.brain_create_builder import render_create_endpoint
from metis_model1.brain_create_executor_v2 import (
    CreateDeltaPlanV2PermitConsumer,
    execute_create_delta_plan_v2,
    issue_create_delta_plan_v2_permit,
)
from metis_model1.brain_create_ir import create_ir_stage_proof
from metis_model1.brain_create_plan_v2 import NodeGrant, SlotGrant, admit_create_delta_plan_v2
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    BoundDecision,
    DialogueBinding,
    PrivateDialogueState,
    QuestionSlot,
)
from metis_model1.brain_dialogue_planner import adjudicate_dialogue_answer
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json, canonical_sha256
from metis_model1.brain_semantic_retrieval import LoadedProjection, Schema2SnapshotRetriever
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_technical_authority import bind_technical_authority
from metis_model1.brain_turns import TurnRequest

SESSION = "g" * 43
ENDPOINT = "synthetic.editorial"


class _Journey:
    """In-memory client exercising actual slots and their exact host bindings."""

    def __init__(self, suffix: str = "alpha", *, extra_fields: int = 0) -> None:
        snapshot, projection, raw = _fixture(suffix)
        self.suffix = suffix
        self.literal = f"Polar_{suffix}"
        self.field = f"tag_{suffix}"
        self.catalog = f"{suffix}.archive_{suffix}"
        domain = projection["catalogs"][0]["fields"][2]["domain"]
        domain["values"][0]["literal"] = self.literal
        extra_lines = []
        for index in range(extra_fields):
            field = {
                "name": f"attribute_{suffix}_{index:03d}",
                "type": "number",
                "modifiers": [],
                "domain": {"kind": "none"},
                "semantic": copy.deepcopy(projection["catalogs"][0]["fields"][0]["semantic"]),
            }
            field["semantic"]["means"]["text"] = f"Misura sintetica indipendente {index}"
            projection["catalogs"][0]["fields"].append(field)
            raw["catalogs"][0]["fields"].append(
                {key: copy.deepcopy(field[key]) for key in ("name", "type", "modifiers")}
            )
            extra_lines.append(f' {field["name"]} number means "Misura sintetica {index}"')
        files = []
        for item in snapshot.files:
            source = item.content.decode().replace('"Aurora"', f'"{self.literal}"')
            if item.path.endswith("archive.metis") and extra_lines:
                assert "\n }\n returns {" in source
                source = source.replace(
                    "\n }\n returns {", "\n" + "\n".join(extra_lines) + "\n }\n returns {"
                )
            content = source.encode()
            files.append(SnapshotFile(item.path, content, bytes_sha256(content)))
        self.snapshot = replace(
            snapshot,
            files=tuple(files),
            total_bytes=sum(len(item.content) for item in files),
            revision=canonical_sha256({item.path: item.sha256 for item in files}),
        )
        semantic_revision = self.snapshot.semantic_source_revision()
        sealed = bind_technical_authority(
            raw,
            projection=projection,
            context_revision=self.snapshot.revision,
            semantic_source_revision=semantic_revision,
            toolchain_binding=self.snapshot.toolchain_binding,
            tenant_id=self.snapshot.tenant_id,
        )
        self.retriever = Schema2SnapshotRetriever(
            lambda current: LoadedProjection(
                projection, current.revision, current.semantic_source_revision(), sealed
            )
        )
        self.retrieved = None
        self.basis_grounding = None
        self.retrieval_log: list[tuple[str, dict[str, Any]]] = []
        self.provider = PinnedCreateV2AuthorityProvider(
            hmac_key=b"g" * 32, toolchain_binding=self.snapshot.toolchain_binding
        )
        self.lease = OperationLease(
            session_id=SESSION,
            client_id="vsix",
            tenant_alias=self.snapshot.tenant_alias,
            capabilities=frozenset({"create"}),
            snapshot=self.snapshot,
            cancellation=threading.Event(),
        )
        self.messages: tuple[CreateAuthorityHistoryMessage, ...] = ()
        self.decisions: tuple[BoundDecision, ...] = ()
        self.basis: PrivateCreateV2Basis | None = None
        self.observed_slots: list[QuestionSlot] = []
        self.execution_count = 0
        self.clarifications = ClarificationStore()
        self.rounds_used = 0
        self.natural_answers: list[str] = []

    def close(self) -> None:
        self.provider.close()
        self.clarifications.clear()

    def append(self, text: str) -> None:
        self.messages += (
            CreateAuthorityHistoryMessage(len(self.messages), text, bytes_sha256(text.encode())),
        )

    def state(self) -> PrivateDialogueState:
        binding = DialogueBinding(
            self.snapshot.revision,
            self.snapshot.semantic_source_revision(),
            self.snapshot.toolchain_binding,
            create_authority_history_revision(self.messages),
            self._request().request_fingerprint,
        )
        return PrivateDialogueState(
            conversation_id=bytes_sha256(f"conversation:{self.suffix}".encode()),
            binding=binding,
            messages=self.messages,
            decisions=self.decisions,
            generation=0 if self.basis is None else self.basis.generation + 1,
            latest_proposal_binding=None if self.basis is None else self.basis.spec_sha256,
        )

    def _request(self) -> TurnRequest:
        return TurnRequest(
            schema_version=2,
            request_id=f"generic-integration-{len(self.messages):04d}-{len(self.decisions):04d}",
            expected_context_revision=self.snapshot.revision,
            expected_semantic_source_revision=self.snapshot.semantic_source_revision(),
            intent="create",
            instruction=self.messages[-1].text,
            target={
                "mode": "create",
                "relative_path": "brain-drafts/editorial.metis",
                "endpoint": ENDPOINT,
                "base_sha256": None,
                "reference": None,
            },
            basis=None,
            clarification_response=None,
        )

    def prepare(self) -> AskCreateV2Authority | ReadyCreateV2Authority:
        state = self.state()
        request = replace(
            self._request(),
            server_dialogue=state,
            server_basis_grounding=copy.deepcopy(self.basis_grounding),
        )
        self.retrieved = self.retriever.retrieve(lease=self.lease, request=request)
        self.retrieval_log.append(
            (request.instruction, copy.deepcopy(dict(self.retrieved.grounding)))
        )
        result = self.provider.prepare(
            session_id=SESSION,
            lease=self.lease,
            request=request,
            dialogue=state,
            retrieved=self.retrieved,
            basis=self.basis,
        )
        if type(result) is AskCreateV2Authority:
            assert 1 <= len(result.slots) <= 5
            self.observed_slots.extend(result.slots)
        else:
            assert self.retrieved.grounding["status"] == "resolved"
        return result

    def answer(self, ask: AskCreateV2Authority, labels: dict[str, str], integer: int) -> None:
        phrases = []
        for slot in ask.slots:
            if slot.answer_kind == "integer":
                assert slot.minimum <= integer <= slot.maximum
                phrases.append(str(integer))
            else:
                assert 1 <= len(slot.choices) <= 64
                label = labels.get(slot.decision_key)
                matching = (
                    [choice for choice in slot.choices if choice.label == label]
                    if label is not None
                    else [slot.choices[0]]
                )
                assert len(matching) == 1, (slot.decision_key, label)
                selected = matching[0].label
                phrases.append(
                    f"Scelgo {selected}" if selected == "Ordinamento per campo" else selected
                )
        self.answer_text(ask, "; ".join(phrases))

    def answer_text(self, ask: AskCreateV2Authority, message: str) -> None:
        state = self.state()
        owner = "turn_" + "g" * 32
        pending = self.clarifications.create_pending_v2(
            session_id=SESSION,
            parent_turn_id=owner,
            conversation_id=state.conversation_id,
            binding=state.binding,
            slots=ask.slots,
        )
        self.append(message)
        answers = adjudicate_dialogue_answer(
            message=message, pending=pending, dialogue=self.state()
        )
        assert len(answers) == len(pending.slots), (message, pending.payload())
        args = dict(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            binding=state.binding,
            answers=tuple(answers),
            claim_owner=owner,
        )
        admitted = self.clarifications.validate_answers_v2(**args)
        resolution = self.clarifications.answer_v2(**args)
        assert resolution.accepted == admitted and resolution.remaining is None
        self.decisions = resolution.decisions
        self.rounds_used = pending.round_index
        self.natural_answers.append(message)
        self.state()  # Revalidate the exact decision history, including supersedes.

    def drive(
        self,
        text: str,
        *,
        labels: dict[str, str] | None = None,
        integer: int = 12,
        stop_at_confirmation: bool = False,
    ) -> AskCreateV2Authority | ReadyCreateV2Authority:
        self.append(text)
        for _ in range(12):
            result = self.prepare()
            if type(result) is ReadyCreateV2Authority:
                return result
            if stop_at_confirmation and any(
                slot.decision_key == "choice.general.confirm" for slot in result.slots
            ):
                return result
            self.answer(result, labels or {}, integer)
        pytest.fail("bounded structural dialogue did not converge")

    def execute(self, ready: ReadyCreateV2Authority) -> dict[str, Any]:
        before = copy.deepcopy(ready.base_spec)
        nodes = [item for item in ready.projection.authorities if isinstance(item, NodeGrant)]
        slots = {
            item.ref: item for item in ready.projection.authorities if isinstance(item, SlotGrant)
        }
        operations = []
        for requirement in ready.projection.requirements:
            candidates = [
                node
                for node in nodes
                if node.state == "new"
                and {ref for leaf in node.leaf_bindings for ref in leaf.requirement_refs}
                == {requirement.ref}
            ]
            assert len(candidates) == 1
            node = candidates[0]
            slot = slots[node.parent_slot_ref]
            action = next(iter(requirement.allowed_ops))
            assert action in {"attach", "set"}
            operations.append(
                {
                    "k": "a" if action == "attach" else "s",
                    "q": [requirement.handle],
                    "s": slot.handle,
                    "n" if action == "attach" else "v": node.handle,
                }
            )
        body = {"o": operations}
        model_wire = canonical_json(
            {"authority": ready.projection.model_projection_payload(), "plan": body}
        ).decode()
        for private in (self.catalog, self.literal, self.field, "technical_authority", "hostref:"):
            assert private not in model_wire
        plan = admit_create_delta_plan_v2(
            body,
            projection=ready.projection,
            mode="initial" if ready.generation == 0 else "refinement",
            context_revision=self.snapshot.revision,
            semantic_revision=self.snapshot.semantic_source_revision(),
            target_ref=ready.target_ref,
            basis_ref=ready.basis_ref,
            active_requirement_handles=ready.active_requirement_handles,
        )
        permit = issue_create_delta_plan_v2_permit(
            plan,
            ready.projection,
            base_spec=ready.base_spec,
            toolchain_binding=self.snapshot.toolchain_binding,
            generation=ready.generation,
            parent_spec_sha256=ready.parent_spec_sha256,
        )
        result = execute_create_delta_plan_v2(
            plan,
            ready.projection,
            base_spec=ready.base_spec,
            parent_spec_sha256=ready.parent_spec_sha256,
            permit_consumer=CreateDeltaPlanV2PermitConsumer(permit),
            toolchain_binding=self.snapshot.toolchain_binding,
            generation=ready.generation,
        )
        spec = dict(result.spec)
        source = render_create_endpoint(spec).metis_text
        assert ready.base_spec == before
        # These receipts are synthetic parent bookkeeping, NOT compiled IR.
        ir = {
            "kind": "SyntheticIntegrationReceipt",
            "name": ENDPOINT,
            "rendered_sha256": bytes_sha256(source.encode()),
            "generation": ready.generation,
        }
        self.basis = PrivateCreateV2Basis(
            spec=spec,
            spec_sha256=canonical_sha256(spec),
            ir=ir,
            ir_sha256=canonical_sha256(ir),
            proof=create_ir_stage_proof(None if self.basis is None else self.basis.ir, ir),
            generation=ready.generation,
            history=self.messages,
            history_revision=create_authority_history_revision(self.messages),
            proposal_ref=f"proposal-integration-{ready.generation}",
        )
        self.execution_count += 1
        self.basis_grounding = copy.deepcopy(dict(self.retrieved.grounding))
        return spec


def _ready(value: Any) -> ReadyCreateV2Authority:
    assert type(value) is ReadyCreateV2Authority
    return value


def _initial(journey: _Journey) -> dict[str, Any]:
    return journey.execute(_ready(journey.drive("storia artica, 17 risultati")))


def _complete_journey(suffix: str) -> dict[str, Any]:
    journey = _Journey(suffix)
    try:
        initial = _initial(journey)
        spec = journey.execute(
            _ready(
                journey.drive(
                    "Aggiungi un altro blocco con gli stessi filtri editoriali.",
                    labels={"choice.general.action": "Aggiungi un blocco filtrato"},
                    integer=9,
                )
            )
        )
        assert len(spec["endpoint"]["blocks"]) == 2
        assert spec["endpoint"]["blocks"][0] == initial["endpoint"]["blocks"][0]
        untouched = copy.deepcopy(spec["endpoint"]["blocks"][1])
        spec = journey.execute(
            _ready(
                journey.drive(
                    "Modifica il numero totale nel primo blocco.",
                    labels={"choice.general.action": "Quantità totale"},
                    integer=13,
                )
            )
        )
        assert spec["endpoint"]["blocks"][0]["fetches"][0]["cardinality"] == {
            "mode": "total",
            "value": 13,
        }
        spec = journey.execute(
            _ready(
                journey.drive(
                    "Porta il primo blocco a 12 risultati totali mantenendo i filtri.",
                    labels={
                        "choice.general.action": "Quantità totale",
                    },
                    integer=12,
                )
            )
        )
        assert spec["endpoint"]["blocks"][0]["fetches"][0]["cardinality"] == {
            "mode": "total",
            "value": 12,
        }
        spec = journey.execute(
            _ready(
                journey.drive(
                    "Ordina il primo blocco usando il campo che selezionerò.",
                    labels={
                        "choice.general.action": "Ordinamento per campo",
                        "choice.general.order_field": f"key_{suffix}",
                        "choice.general.order_direction": "Decrescente",
                    },
                )
            )
        )
        assert spec["endpoint"]["blocks"][0]["fetches"][0]["order"] == [
            {"by": "field", "field": f"key_{suffix}", "direction": "descending"}
        ]
        spec = journey.execute(
            _ready(
                journey.drive(
                    "Espandi il formato della risposta del primo blocco.",
                    labels={
                        "choice.general.action": "Formato della risposta",
                        "choice.general.projection": "detail",
                    },
                )
            )
        )
        assert spec["endpoint"]["blocks"][0]["fetches"][0]["output"]["projection"] == "detail"
        spec = journey.execute(
            _ready(
                journey.drive(
                    "Aggiungi in coda il secondo blocco se il primo ha pochi risultati.",
                    labels={
                        "choice.general.action": "Fallback verso un altro blocco",
                        "choice.general.fallback_trigger": "Sotto una soglia",
                        "choice.general.fallback_mode": "Aggiungi in coda",
                    },
                    integer=2,
                )
            )
        )
        main = spec["endpoint"]["blocks"][0]
        assert spec["endpoint"]["blocks"][1] == untouched
        assert main["fetches"][0]["output"]["projection"] == "detail"
        assert main["output"]["projection"] == "default"
        assert main["output"]["fallbacks"] == [
            {
                "kind": "direct",
                "target": untouched["name"],
                "target_kind": "block",
                "trigger": "below",
                "mode": "append",
                "threshold": 2,
            }
        ]
        assert (
            main["fetches"][0]["clauses"]
            == initial["endpoint"]["blocks"][0]["fetches"][0]["clauses"]
        )
        assert "take 12 from" in render_create_endpoint(spec).metis_text
        assert "Scelgo Ordinamento per campo" in journey.natural_answers
        assert journey.execution_count == 7
        assert 3 < journey.rounds_used <= journey.clarifications.max_rounds_v2
        assert len(journey.decisions) <= 32
        assert len(journey.retrieval_log) == journey.rounds_used + journey.execution_count
        assert all(
            grounding["status"] == "resolved"
            for message, grounding in journey.retrieval_log
            if message in journey.natural_answers
        )
        assert all(
            {(item["field"], item["literal"]) for item in grounding["selections"]}
            == {(journey.field, journey.literal)}
            for _, grounding in journey.retrieval_log
            if grounding["status"] == "resolved"
        )
        return spec
    finally:
        journey.close()


@pytest.mark.parametrize("suffix", ("alpha", "beta"))
def test_real_provider_builds_and_refines_two_renamed_descriptor_blocks(suffix: str) -> None:
    assert len(_complete_journey(suffix)["endpoint"]["blocks"]) == 2


def test_complete_provider_journeys_are_isomorphic_after_descriptor_renaming() -> None:
    def normalized(value: Any, names: dict[str, str]) -> Any:
        if isinstance(value, dict):
            return {key: normalized(nested, names) for key, nested in value.items()}
        if isinstance(value, list):
            return [normalized(nested, names) for nested in value]
        return names.get(value, value) if isinstance(value, str) else value

    results = []
    for suffix in ("alpha", "beta"):
        names = {
            f"archive_{suffix}": "renamed_catalog",
            f"key_{suffix}": "renamed_identity",
            f"tag_{suffix}": "renamed_attribute",
            f"Polar_{suffix}": "renamed_literal",
        }
        results.append(normalized(_complete_journey(suffix), names))
    assert results[0] == results[1]


def test_real_provider_correction_before_draft_starts_a_new_bound_choice_round() -> None:
    journey = _Journey()
    try:
        _initial(journey)
        labels = {"choice.general.action": "Quantità totale"}
        pending = journey.drive(
            "Cambia la quantità del primo blocco.",
            labels=labels,
            integer=24,
            stop_at_confirmation=True,
        )
        assert type(pending) is AskCreateV2Authority
        assert journey.execution_count == 1
        old_counts = {item.identity for item in journey.decisions if item.answer_kind == "integer"}
        ready = _ready(
            journey.drive("Correggi: voglio 12 risultati, non 24.", labels=labels, integer=12)
        )
        new_counts = {item.identity for item in journey.decisions if item.answer_kind == "integer"}
        assert len(new_counts - old_counts) == 1
        spec = journey.execute(ready)
        assert spec["endpoint"]["blocks"][0]["fetches"][0]["cardinality"]["value"] == 12
    finally:
        journey.close()


def test_real_provider_can_order_by_the_last_field_beyond_the_first_64() -> None:
    journey = _Journey(extra_fields=66)
    try:
        _initial(journey)
        ready = _ready(
            journey.drive(
                "Scegli l'ultimo campo disponibile per ordinare.",
                labels={
                    "choice.general.action": "Ordinamento per campo",
                    "choice.general.order_field.page": "Scelte 65-69",
                    "choice.general.order_field": "attribute_alpha_065",
                },
            )
        )
        spec = journey.execute(ready)
        assert (
            spec["endpoint"]["blocks"][0]["fetches"][0]["order"][0]["field"]
            == "attribute_alpha_065"
        )
        assert any(
            slot.decision_key == "choice.general.order_field.page"
            for slot in journey.observed_slots
        )
        assert all(len(slot.choices) <= 64 for slot in journey.observed_slots)
    finally:
        journey.close()


def test_natural_defer_then_count_stays_in_the_bound_generic_operation() -> None:
    journey = _Journey()
    try:
        journey.append("storia artica, 17 risultati")
        initial = journey.prepare()
        assert type(initial) is AskCreateV2Authority
        journey.answer_text(initial, "Serve una struttura più articolata")
        action = journey.prepare()
        assert type(action) is AskCreateV2Authority
        assert action.slots[0].decision_key == "choice.general.action"
        journey.answer_text(action, "Aggiungi un blocco filtrato")
        count = journey.prepare()
        assert type(count) is AskCreateV2Authority
        assert count.slots[0].answer_kind == "integer"
        journey.answer_text(count, "24 risultati")
        confirmation = journey.prepare()
        assert type(confirmation) is AskCreateV2Authority
        assert confirmation.slots[0].decision_key == "choice.general.confirm"
        assert "24 risultati totali" in confirmation.slots[0].choices[0].description
        journey.answer_text(confirmation, "Confermo questa operazione")
        ready = _ready(journey.prepare())
        spec = journey.execute(ready)
        assert spec["endpoint"]["blocks"][0]["fetches"][0]["cardinality"] == {
            "mode": "total",
            "value": 24,
        }
        assert journey.rounds_used == 4 and journey.execution_count == 1
        assert journey.natural_answers == [
            "Serve una struttura più articolata",
            "Aggiungi un blocco filtrato",
            "24 risultati",
            "Confermo questa operazione",
        ]
    finally:
        journey.close()


def test_natural_cancel_is_admitted_without_authorizing_a_proposal() -> None:
    journey = _Journey()
    try:
        _initial(journey)
        current_basis = journey.basis
        confirmation = journey.drive(
            "Voglio cambiare la quantità del primo blocco.",
            labels={"choice.general.action": "Quantità totale"},
            integer=24,
            stop_at_confirmation=True,
        )
        assert type(confirmation) is AskCreateV2Authority
        journey.answer_text(confirmation, "Annulla operazione")
        with pytest.raises(BrainError) as raised:
            journey.prepare()
        assert raised.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"
        assert journey.basis == current_basis
        assert journey.execution_count == 1
        assert journey.decisions[-1].choices[0].label == "Annulla operazione"
    finally:
        journey.close()


def test_real_retrieval_does_not_treat_an_unadmitted_answer_as_semantic_authority() -> None:
    journey = _Journey()
    try:
        journey.append("storia artica, 17 risultati")
        assert type(journey.prepare()) is AskCreateV2Authority
        journey.append("Un solo blocco filtrato")  # No resolver/store admission.
        with pytest.raises(BrainError) as raised:
            journey.prepare()
        assert raised.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"
        assert journey.retrieved.grounding["status"] == "unsupported"
        assert journey.decisions == () and journey.basis is None
        assert journey.execution_count == 0
        assert len(journey.retrieval_log) == 2
    finally:
        journey.close()


def test_real_retrieval_stops_admitted_label_plus_unknown_new_filter_before_first_draft() -> None:
    journey = _Journey()
    try:
        journey.append("storia artica, 17 risultati")
        ask = journey.prepare()
        assert type(ask) is AskCreateV2Authority
        journey.answer_text(
            ask, "Un solo blocco filtrato; aggiungi il criterio inesistente nebularia."
        )
        assert len(journey.decisions) == 1  # Label admitted, additional requirement not ignored.
        with pytest.raises(BrainError) as raised:
            journey.prepare()
        assert raised.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"
        assert journey.retrieved.grounding["status"] == "unsupported"
        assert journey.retrieved.grounding["cumulative_dialogue_semantics"]["status"] == "rejected"
        assert journey.retrieved.grounding["selections"] == []
        assert journey.basis is None and journey.basis_grounding is None
        assert journey.execution_count == 0
    finally:
        journey.close()


@pytest.mark.parametrize("fault", ("digest", "context", "tenant"))
def test_real_provider_rejects_tampered_or_resealed_stale_technical_authority(fault: str) -> None:
    journey = _Journey()
    try:
        _initial(journey)
        journey.append("Ordina la bozza.")
        action = journey.prepare()
        assert type(action) is AskCreateV2Authority
        journey.answer_text(action, "Scelgo Ordinamento per campo")
        state = journey.state()
        request = replace(
            journey._request(),
            server_dialogue=state,
            server_basis_grounding=copy.deepcopy(journey.basis_grounding),
        )
        current = journey.retriever.retrieve(lease=journey.lease, request=request)
        assert current.grounding["status"] == "resolved"
        context = copy.deepcopy(current.context)
        technical = context["technical_authority"]
        if fault == "digest":
            technical["sha256"] = bytes_sha256(b"forged")
        else:
            technical["tenant" if fault == "tenant" else "context_revision"] = (
                "foreign-tenant" if fault == "tenant" else bytes_sha256(b"foreign-context")
            )
            technical["sha256"] = canonical_sha256(
                {key: value for key, value in technical.items() if key != "sha256"}
            )
        tampered = replace(current, context=context)
        with pytest.raises(BrainError) as caught:
            journey.provider.prepare(
                session_id=SESSION,
                lease=journey.lease,
                request=request,
                dialogue=state,
                retrieved=tampered,
                basis=journey.basis,
            )
        assert caught.value.code == ("RETRIEVAL_INVALID" if fault == "digest" else "STALE_CONTEXT")
        assert journey.execution_count == 1
    finally:
        journey.close()


def test_real_provider_rejects_a_basis_from_another_target() -> None:
    journey = _Journey()
    try:
        _initial(journey)
        assert journey.basis is not None
        spec = copy.deepcopy(journey.basis.spec)
        spec["endpoint"]["name"] = "synthetic.foreign"
        journey.basis = replace(journey.basis, spec=spec, spec_sha256=canonical_sha256(spec))
        with pytest.raises(BrainError, match="basis target differs"):
            journey.drive("Modifica il numero totale.")
        assert journey.execution_count == 1
    finally:
        journey.close()
