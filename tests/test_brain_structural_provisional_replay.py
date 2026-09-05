"""Adversarial lifecycle gates for provisional structural continuations.

A resolver-derived ``specify`` choice is procedure, not durable structural
authority.  TurnStore may expose it prospectively to the typed CREATE provider,
but must commit it only when that provider advances beyond the exact issued Ask.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_create_authority_provider_v2 import AskCreateV2Authority
from metis_model1.brain_dialogue_contract import BoundChoice, PrivateDialogueState, QuestionSlot
from metis_model1.brain_dialogue_planner import resolve_dialogue_answer
from metis_model1.brain_model_runtime import StaticModelRuntime
from metis_model1.brain_protocol import CAPABILITIES, BrainError
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_server import BrainApplication, BrainRuntime
from metis_model1.brain_sessions import ClientPolicy, SessionManager
from metis_model1.brain_turns import ClarificationAnswerRequest, TurnRequest

_DIGEST = "0123456789abcdef"
_FIRST = "Crea due pool: 14 episodi dello stesso programma e 18 clip extra; raggruppali per tema."
_SECOND = "Nel pool principale conserva 50 elementi prima del ranking."


class _NoCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def __init__(self) -> None:
        self.calls = 0

    def compile_candidate(self, **_kwargs: Any) -> None:
        self.calls += 1
        raise AssertionError("a structural Ask must not compile")


class _NoModel(StaticModelRuntime):
    def __init__(self) -> None:
        super().__init__("unused")
        self.calls = 0

    def generate(self, _request: Any) -> Any:
        self.calls += 1
        raise AssertionError("a structural Ask must not invoke Model 1")


class _Retriever:
    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        del request
        return RetrievalResult(
            context={"tenant": lease.tenant_alias},
            grounding={"status": "resolved", "catalogs": [], "selections": []},
            semantic_source_revision=semantic_revision(lease.snapshot),
        )


def _structural_slot(*, altered: bool = False) -> QuestionSlot:
    revision = "sha256:" + ("d" if altered else "c") * 64
    return QuestionSlot(
        f"choice.structure.{_DIGEST}",
        "context.pools.contract",
        "structural_choice",
        "Specifica il contratto dei pool." if not altered else "Descrivi i pool richiesti.",
        "option_ref",
        (
            BoundChoice(
                "Specificare il contratto mancante",
                (f"clarification:structure:{_DIGEST}:specify",),
                revision,
                ("scalar",),
            ),
            BoundChoice(
                "Ridurre la richiesta",
                (f"clarification:structure:{_DIGEST}:reduce",),
                revision,
                ("scalar",),
            ),
        ),
    )


def _count_slot() -> QuestionSlot:
    return QuestionSlot(
        "qty.result_count.endpoint.total.any",
        "endpoint.results.total",
        "result_count",
        "Quanti risultati vuoi?",
        "integer",
        minimum=1,
        maximum=100,
        value_contract="total",
    )


class _ScenarioProvider:
    contract_id = "test.structural-provisional.provider"
    policy_revision = "sha256:" + "b" * 64
    inventory_revision = "sha256:" + "c" * 64

    def __init__(self, *steps: str) -> None:
        self.steps = steps
        self.dialogues: list[PrivateDialogueState] = []

    def prepare(self, *, dialogue: PrivateDialogueState, **_kwargs: Any) -> AskCreateV2Authority:
        self.dialogues.append(replace(dialogue))
        step = self.steps[len(self.dialogues) - 1]
        if step == "same":
            return AskCreateV2Authority((_structural_slot(),))
        if step == "different":
            return AskCreateV2Authority((_count_slot(),))
        if step == "altered":
            return AskCreateV2Authority((_structural_slot(altered=True),))
        if step == "multi":
            return AskCreateV2Authority((_structural_slot(), _count_slot()))
        raise AssertionError(f"unknown provider step: {step}")


class _Fixture:
    def __init__(self, tmp_path: Path, provider: _ScenarioProvider) -> None:
        tenant = tmp_path / "tenant"
        tenant.mkdir()
        (tenant / "metis.toml").write_text('[tenant]\nid = "tenant-one"\n', encoding="utf-8")
        (tenant / "main.metis").write_text("metis 0.43\ntenant tenant_one {}\n", encoding="utf-8")
        self.compiler = _NoCompiler()
        self.model = _NoModel()
        self.provider = provider
        self.runtime = BrainRuntime((tmp_path / "runtime").resolve())
        self.registry = TenantRegistry([("demo", "tenant-one", tenant.resolve())])
        self.manager = SessionManager(
            registry=self.registry,
            policies=[ClientPolicy("visix", frozenset({"demo"}), CAPABILITIES)],
            runtime_root=self.runtime.run_dir / "sessions",
            toolchain_binding=self.compiler.toolchain_binding,
        )
        self.app = BrainApplication(
            runtime=self.runtime,
            manager=self.manager,
            compiler=self.compiler,
            model=self.model,
            retriever=_Retriever(),
            dialogue_answer_resolver=resolve_dialogue_answer,
            create_authority_provider=provider,
        )
        self.session = self.manager.create_session(
            client_id="visix", tenant_alias="demo", requested_capabilities=CAPABILITIES
        )
        self.semantic = self.registry.capture(
            "demo", toolchain_binding=self.compiler.toolchain_binding
        ).semantic_source_revision()

    def close(self) -> None:
        self.app.close()
        self.manager.shutdown()
        self.runtime.close()

    def request(self, instruction: str) -> TurnRequest:
        return TurnRequest(
            schema_version=2,
            request_id=str(uuid.uuid4()),
            expected_context_revision=self.session.context_revision,
            expected_semantic_source_revision=self.semantic,
            intent="create",
            instruction=instruction,
            target={
                "mode": "create",
                "relative_path": "brain-drafts/provisional-replay.metis",
                "endpoint": "demo.provisional_replay",
                "base_sha256": None,
            },
            basis=None,
            clarification_response=None,
        )

    def issue(self) -> tuple[Any, dict[str, Any]]:
        record = self.app.turns.submit(
            session_id=self.session.session_id,
            token=self.session.token,
            request=self.request("Crea un endpoint editoriale complesso."),
        )
        terminal = _wait(record)
        assert terminal["outcome"] == "needs_clarification"
        return record, terminal

    def answer(self, *, parent: Any, clarification_id: str, message: str) -> Any:
        return self.app.turns.answer(
            session_id=self.session.session_id,
            token=self.session.token,
            parent_turn_id=parent.turn_id,
            answer=ClarificationAnswerRequest(
                schema_version=2,
                request_id=str(uuid.uuid4()),
                clarification_id=clarification_id,
                message=message,
                answers=(),
            ),
        )


def _wait(record: Any) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    with record.condition:
        while record.terminal is None and time.monotonic() < deadline:
            record.condition.wait(timeout=0.02)
    assert isinstance(record.terminal, dict), "turn did not reach a terminal state"
    return record.public_status()


def _assert_provisional(dialogue: PrivateDialogueState, *, messages: tuple[str, ...]) -> None:
    assert tuple(item.text for item in dialogue.messages) == messages
    assert len(dialogue.decisions) == 1
    decision = dialogue.decisions[0]
    assert decision.kind == "structural_choice"
    assert decision.target_key == "context.pools.contract"
    assert decision.choices[0].authority_keys == (f"clarification:structure:{_DIGEST}:specify",)


def test_same_structural_ask_replays_exact_pending_without_committing(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path, _ScenarioProvider("same", "same", "same"))
    try:
        issued, original_terminal = fixture.issue()
        original_payload = original_terminal["clarification"]
        clarification_id = original_payload["clarification_id"]
        original_pending = fixture.app.turns.clarifications.pending_v2(
            session_id=fixture.session.session_id,
            clarification_id=clarification_id,
        )
        conversation_id = original_pending.conversation_id
        assert original_pending.round_index == 1
        assert (
            fixture.app.turns.clarifications.decisions_v2(
                session_id=fixture.session.session_id,
                conversation_id=conversation_id,
            )
            == ()
        )

        first = fixture.answer(parent=issued, clarification_id=clarification_id, message=_FIRST)
        first_terminal = _wait(first)
        assert first_terminal["outcome"] == "needs_clarification"
        assert first_terminal["clarification"] == original_payload
        assert (
            fixture.app.turns.clarifications.pending_v2(
                session_id=fixture.session.session_id,
                clarification_id=clarification_id,
            )
            == original_pending
        )
        assert (
            fixture.app.turns.clarifications.decisions_v2(
                session_id=fixture.session.session_id,
                conversation_id=conversation_id,
            )
            == ()
        )
        assert first.dialogue_state is not None
        assert tuple(item.text for item in first.dialogue_state.messages) == (
            "Crea un endpoint editoriale complesso.",
            _FIRST,
        )
        assert first.dialogue_state.decisions == ()
        _assert_provisional(
            fixture.provider.dialogues[1],
            messages=("Crea un endpoint editoriale complesso.", _FIRST),
        )

        # The same public ID remains live, but only the latest dialogue head may
        # answer it. Reusing the original parent would fork away the already
        # admitted free-form message and is therefore rejected before provider use.
        with pytest.raises(BrainError) as stale_parent:
            fixture.answer(parent=issued, clarification_id=clarification_id, message=_SECOND)
        assert stale_parent.value.code in {"CLARIFICATION_STALE", "CLARIFICATION_UNAVAILABLE"}
        assert len(fixture.provider.dialogues) == 2

        # The latest parent preserves the first message while a second
        # prospective attempt remains non-durable.
        second = fixture.answer(parent=first, clarification_id=clarification_id, message=_SECOND)
        second_terminal = _wait(second)
        assert second_terminal["outcome"] == "needs_clarification"
        assert second_terminal["clarification"] == original_payload
        assert (
            fixture.app.turns.clarifications.pending_v2(
                session_id=fixture.session.session_id,
                clarification_id=clarification_id,
            )
            == original_pending
        )
        assert (
            fixture.app.turns.clarifications.decisions_v2(
                session_id=fixture.session.session_id,
                conversation_id=conversation_id,
            )
            == ()
        )
        assert second.dialogue_state is not None
        assert tuple(item.text for item in second.dialogue_state.messages) == (
            "Crea un endpoint editoriale complesso.",
            _FIRST,
            _SECOND,
        )
        assert second.dialogue_state.decisions == ()
        _assert_provisional(
            fixture.provider.dialogues[2],
            messages=("Crea un endpoint editoriale complesso.", _FIRST, _SECOND),
        )
        assert fixture.compiler.calls == fixture.model.calls == 0
    finally:
        fixture.close()


def test_different_ask_commits_preview_and_creates_next_round(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path, _ScenarioProvider("same", "different"))
    try:
        issued, original_terminal = fixture.issue()
        clarification_id = original_terminal["clarification"]["clarification_id"]
        original_pending = fixture.app.turns.clarifications.pending_v2(
            session_id=fixture.session.session_id,
            clarification_id=clarification_id,
        )

        resumed = fixture.answer(parent=issued, clarification_id=clarification_id, message=_FIRST)
        terminal = _wait(resumed)
        assert terminal["outcome"] == "needs_clarification"
        assert terminal["clarification"]["clarification_id"] != clarification_id
        assert terminal["clarification"]["round"] == original_pending.round_index + 1 == 2
        assert terminal["clarification"]["questions"][0]["kind"] == "result_count"
        assert resumed.dialogue_state is not None
        _assert_provisional(
            fixture.provider.dialogues[1],
            messages=("Crea un endpoint editoriale complesso.", _FIRST),
        )
        assert resumed.dialogue_state == fixture.provider.dialogues[1]
        decisions = fixture.app.turns.clarifications.decisions_v2(
            session_id=fixture.session.session_id,
            conversation_id=original_pending.conversation_id,
        )
        assert decisions == resumed.dialogue_state.decisions
        assert len(decisions) == 1

        with pytest.raises(BrainError) as replay:
            fixture.app.turns.clarifications.pending_v2(
                session_id=fixture.session.session_id,
                clarification_id=clarification_id,
            )
        assert replay.value.code == "CLARIFICATION_REPLAY"
        with pytest.raises(BrainError) as stale_answer:
            fixture.answer(parent=issued, clarification_id=clarification_id, message=_SECOND)
        assert stale_answer.value.code == "CLARIFICATION_REPLAY"
        assert fixture.compiler.calls == fixture.model.calls == 0
    finally:
        fixture.close()


def test_multislot_structural_roster_abstains_and_never_stages_preview(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path, _ScenarioProvider("multi"))
    try:
        issued, original_terminal = fixture.issue()
        clarification_id = original_terminal["clarification"]["clarification_id"]
        resumed = fixture.answer(parent=issued, clarification_id=clarification_id, message=_FIRST)
        terminal = _wait(resumed)

        assert terminal["outcome"] == "needs_clarification"
        assert terminal["clarification"] == original_terminal["clarification"]
        assert len(fixture.provider.dialogues) == 1
        assert resumed.dialogue_state is not None
        assert resumed.dialogue_state.decisions == ()
        pending = fixture.app.turns.clarifications.pending_v2(
            session_id=fixture.session.session_id,
            clarification_id=clarification_id,
        )
        assert pending.round_index == 1
        assert (
            fixture.app.turns.clarifications.decisions_v2(
                session_id=fixture.session.session_id,
                conversation_id=pending.conversation_id,
            )
            == ()
        )
        assert fixture.compiler.calls == fixture.model.calls == 0
    finally:
        fixture.close()


def test_same_identity_with_altered_template_fails_closed(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, _ScenarioProvider("same", "altered"))
    try:
        issued, original_terminal = fixture.issue()
        clarification_id = original_terminal["clarification"]["clarification_id"]
        resumed = fixture.answer(parent=issued, clarification_id=clarification_id, message=_FIRST)
        terminal = _wait(resumed)

        assert terminal["status"] == "failed"
        assert terminal["error"]["code"] == "CREATE_TYPED_AUTHORITY_INVALID"
        assert (
            fixture.app.turns.clarifications.decisions_v2(
                session_id=fixture.session.session_id,
                conversation_id=issued.conversation_id,
            )
            == ()
        )
        # A failed prospective comparison releases the claim without replacing
        # or retiring the only authoritative pending question.
        assert (
            fixture.app.turns.clarifications.pending_v2(
                session_id=fixture.session.session_id,
                clarification_id=clarification_id,
            ).round_index
            == 1
        )
        assert fixture.compiler.calls == fixture.model.calls == 0
    finally:
        fixture.close()
