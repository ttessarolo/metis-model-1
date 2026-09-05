"""Integration gate for a procedural structural free-form continuation.

The free-form ``specify`` option is deliberately not structural authority.  It
only releases the currently issued question so that the provider can assess the
new admitted operator message from scratch.  This test keeps model and compiler
unavailable to prove that the lifecycle itself never falls into the historical
pre-model ``COMPILER_FAILED`` path.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from metis_model1.brain_clarifications import ClarificationStore
from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_create_authority_provider_v2 import AskCreateV2Authority
from metis_model1.brain_create_ir import create_ir_stage_proof
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    BoundChoice,
    DialogueBinding,
    PrivateDialogueState,
    QuestionSlot,
)
from metis_model1.brain_dialogue_planner import adjudicate_dialogue_answer, resolve_dialogue_answer
from metis_model1.brain_model_runtime import StaticModelRuntime
from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_protocol import CAPABILITIES, BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_server import BrainApplication, BrainRuntime
from metis_model1.brain_sessions import ClientPolicy, SessionManager
from metis_model1.brain_turns import ClarificationAnswerRequest, TurnRequest


class _NoCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def __init__(self) -> None:
        self.calls = 0

    def compile_candidate(self, **_kwargs: Any) -> None:
        self.calls += 1
        raise AssertionError("structural clarification must not compile")


class _NoModel(StaticModelRuntime):
    def __init__(self) -> None:
        super().__init__("unused")
        self.calls = 0

    def generate(self, _request: Any) -> Any:
        self.calls += 1
        raise AssertionError("structural clarification must not invoke a model")


class _Retriever:
    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        del request
        return RetrievalResult(
            context={"tenant": lease.tenant_alias},
            grounding={"status": "resolved", "catalogs": [], "selections": []},
            semantic_source_revision=semantic_revision(lease.snapshot),
        )


class _ContinuationProvider:
    """Return an issued structural Ask, then prove the provider sees the new text."""

    contract_id = "test.structural-freeform.provider"
    policy_revision = "sha256:" + "b" * 64
    inventory_revision = "sha256:" + "c" * 64

    def __init__(self) -> None:
        self.messages: list[tuple[str, ...]] = []
        self.bases: list[Any] = []

    @staticmethod
    def _structural_slot() -> QuestionSlot:
        digest = "0123456789abcdef"
        return QuestionSlot(
            f"choice.structure.{digest}",
            "context.pools.contract",
            "structural_choice",
            "Specifica il contratto dei pool.",
            "option_ref",
            (
                BoundChoice(
                    "Specificare il contratto mancante",
                    (f"clarification:structure:{digest}:specify",),
                    "sha256:" + "c" * 64,
                    ("scalar",),
                ),
                BoundChoice(
                    "Ridurre la richiesta",
                    (f"clarification:structure:{digest}:reduce",),
                    "sha256:" + "c" * 64,
                    ("scalar",),
                ),
            ),
        )

    def prepare(
        self,
        *,
        dialogue: Any,
        basis: Any,
        **_kwargs: Any,
    ) -> AskCreateV2Authority:
        assert basis is not None
        self.bases.append(basis)
        self.messages.append(tuple(item.text for item in dialogue.messages))
        if len(self.messages) == 1:
            return AskCreateV2Authority((self._structural_slot(),))
        assert dialogue.messages[-1].text == _CONTINUATION
        assert len(dialogue.decisions) == 1
        assert dialogue.decisions[0].choices[0].authority_keys[0].endswith(":specify")
        return AskCreateV2Authority(
            (
                QuestionSlot(
                    "qty.result_count.endpoint.total.any",
                    "endpoint.results.total",
                    "result_count",
                    "Quanti risultati vuoi?",
                    "integer",
                    minimum=1,
                    maximum=100,
                    value_contract="total",
                ),
            )
        )


_CONTINUATION = (
    "Crea due pool: 14 episodi dello stesso programma e 18 clip extra; "
    "raggruppali per tema e conserva 50 elementi per il ranking."
)


def _wait(record: Any) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    with record.condition:
        while record.terminal is None and time.monotonic() < deadline:
            record.condition.wait(timeout=0.02)
    assert isinstance(record.terminal, dict), "turn did not reach a terminal state"
    return record.public_status()


def _request(
    *, session: Any, semantic: str, instruction: str, basis: dict[str, str] | None
) -> TurnRequest:
    return TurnRequest(
        schema_version=2,
        request_id=str(uuid.uuid4()),
        expected_context_revision=session.context_revision,
        expected_semantic_source_revision=semantic,
        intent="create",
        instruction=instruction,
        target={
            "mode": "create",
            "relative_path": "brain-drafts/structural-freeform.metis",
            "endpoint": "demo.structural_freeform",
            "base_sha256": None,
        },
        basis=basis,
        clarification_response=None,
    )


def _install_initial_candidate(record: Any) -> dict[str, Any]:
    history = record.dialogue_state.messages
    spec = {
        "schema_version": 1,
        "contract_id": "metis-brain-create-endpoint-spec/v1",
        "endpoint": {"name": "demo.structural_freeform"},
    }
    ir = {"kind": "Endpoint", "name": "demo.structural_freeform", "generation": 0}
    record.candidate_create_spec = spec
    record.candidate_create_spec_sha256 = canonical_sha256(spec)
    record.candidate_create_ir = ir
    record.candidate_create_ir_sha256 = canonical_sha256(ir)
    record.candidate_create_proof = create_ir_stage_proof(None, ir)
    record.candidate_create_generation = 0
    record.candidate_create_history = history
    record.candidate_create_history_revision = record.dialogue_state.binding.history_revision
    manifest = {"schema_version": 1, "endpoint": "demo.structural_freeform"}
    record.candidate_manifest = manifest
    record.candidate_manifest_sha256 = canonical_sha256(manifest)
    source = "metis 0.43\nendpoint demo.structural_freeform {}\n"
    return {
        "schema_version": 2,
        "turn_id": record.turn_id,
        "request_id": record.request.request_id,
        "status": "completed",
        "outcome": "proposed",
        "route": "local",
        "proposal": {
            "proposal_ref": "proposal-structural-parent",
            "source": source,
            "source_sha256": bytes_sha256(source.encode("utf-8")),
        },
    }


def test_freeform_structural_continuation_consumes_pending_and_reaches_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    (tenant / "metis.toml").write_text('[tenant]\nid = "tenant-one"\n', encoding="utf-8")
    (tenant / "main.metis").write_text("metis 0.43\ntenant tenant_one {}\n", encoding="utf-8")
    compiler, model, provider = _NoCompiler(), _NoModel(), _ContinuationProvider()
    runtime = BrainRuntime((tmp_path / "runtime").resolve())
    manager = SessionManager(
        registry=TenantRegistry([("demo", "tenant-one", tenant.resolve())]),
        policies=[ClientPolicy("visix", frozenset({"demo"}), CAPABILITIES)],
        runtime_root=runtime.run_dir / "sessions",
        toolchain_binding=compiler.toolchain_binding,
    )
    app = BrainApplication(
        runtime=runtime,
        manager=manager,
        compiler=compiler,
        model=model,
        retriever=_Retriever(),
        dialogue_answer_resolver=resolve_dialogue_answer,
        create_authority_provider=provider,
    )
    original_run = BrainOrchestrator.run

    def initial_parent(orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs["request"].basis is None:
            return _install_initial_candidate(kwargs["record"])
        return original_run(orchestrator, **kwargs)

    monkeypatch.setattr(BrainOrchestrator, "run", initial_parent)
    session = manager.create_session(
        client_id="visix", tenant_alias="demo", requested_capabilities=CAPABILITIES
    )
    try:
        semantic = (
            TenantRegistry([("demo", "tenant-one", tenant.resolve())])
            .capture("demo", toolchain_binding=compiler.toolchain_binding)
            .semantic_source_revision()
        )
        parent = app.turns.submit(
            session_id=session.session_id,
            token=session.token,
            request=_request(
                session=session,
                semantic=semantic,
                instruction="Crea il primo endpoint.",
                basis=None,
            ),
        )
        parent_terminal = _wait(parent)
        assert parent_terminal["outcome"] == "proposed"

        issued = app.turns.submit(
            session_id=session.session_id,
            token=session.token,
            request=_request(
                session=session,
                semantic=semantic,
                instruction="Aggiungi una riga clusterizzata.",
                basis={"kind": "proposal", "proposal_ref": "proposal-structural-parent"},
            ),
        )
        issued_terminal = _wait(issued)
        assert issued_terminal["outcome"] == "needs_clarification"
        old_id = issued_terminal["clarification"]["clarification_id"]

        resumed = app.turns.answer(
            session_id=session.session_id,
            token=session.token,
            parent_turn_id=issued.turn_id,
            answer=ClarificationAnswerRequest(
                schema_version=2,
                request_id=str(uuid.uuid4()),
                clarification_id=old_id,
                message=_CONTINUATION,
                answers=(),
            ),
        )
        terminal = _wait(resumed)

        assert terminal["outcome"] == "needs_clarification"
        assert terminal["clarification"]["clarification_id"] != old_id
        assert terminal["clarification"]["questions"][0]["kind"] == "result_count"
        assert provider.messages == [
            ("Crea il primo endpoint.", "Aggiungi una riga clusterizzata."),
            ("Crea il primo endpoint.", "Aggiungi una riga clusterizzata.", _CONTINUATION),
        ]
        assert len(provider.bases) == 2
        assert compiler.calls == 0 and model.calls == 0
        with pytest.raises(BrainError) as replay:
            app.turns.clarifications.pending_v2(
                session_id=session.session_id, clarification_id=old_id
            )
        assert replay.value.code == "CLARIFICATION_REPLAY"
    finally:
        app.close()
        manager.shutdown()
        runtime.close()


@pytest.mark.parametrize("mutation", ("extra_slot", "bad_revision", "bad_decision_key"))
def test_freeform_specify_rejects_noncanonical_procedural_slot(mutation: str) -> None:
    """A malformed provider roster cannot convert arbitrary text into ``specify``."""
    digest = "0123456789abcdef"
    choices = (
        BoundChoice(
            "Specificare il contratto mancante",
            (f"clarification:structure:{digest}:specify",),
            "sha256:" + "a" * 64,
            ("scalar",),
        ),
        BoundChoice(
            "Ridurre la richiesta",
            (f"clarification:structure:{digest}:reduce",),
            "sha256:" + "a" * 64,
            ("scalar",),
        ),
    )
    slot = QuestionSlot(
        f"choice.structure.{digest}",
        "context.pools.contract",
        "structural_choice",
        "Specifica il contratto.",
        "option_ref",
        choices,
    )
    if mutation == "extra_slot":
        slots = (
            slot,
            QuestionSlot(
                "qty.result_count.endpoint.total.any",
                "endpoint.results.total",
                "result_count",
                "Quanti risultati vuoi?",
                "integer",
                minimum=1,
                maximum=100,
                value_contract="total",
            ),
        )
    elif mutation == "bad_revision":
        slots = (
            QuestionSlot(
                slot.decision_key,
                slot.target_key,
                slot.kind,
                slot.question,
                slot.answer_kind,
                (
                    choices[0],
                    BoundChoice(
                        choices[1].label,
                        choices[1].authority_keys,
                        "sha256:" + "b" * 64,
                        choices[1].required_roles,
                    ),
                ),
            ),
        )
    else:
        slots = (
            QuestionSlot(
                "choice.structure.fedcba9876543210",
                slot.target_key,
                slot.kind,
                slot.question,
                slot.answer_kind,
                choices,
            ),
        )
    message = "Aggiungi il fallback deterministico."
    history = (CreateAuthorityHistoryMessage(0, message, bytes_sha256(message.encode())),)
    binding = DialogueBinding(
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
        "sha256:" + "c" * 64,
        create_authority_history_revision(history),
        "sha256:" + "d" * 64,
    )
    state = PrivateDialogueState("sha256:" + "e" * 64, binding, history)
    pending = ClarificationStore().create_pending_v2(
        session_id="session_" + "a" * 32,
        parent_turn_id="turn_" + "a" * 32,
        conversation_id=state.conversation_id,
        binding=binding,
        slots=slots,
    )
    assert adjudicate_dialogue_answer(message=message, pending=pending, dialogue=state) == ()
