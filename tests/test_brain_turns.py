from __future__ import annotations

import http.client
import json
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_create_ir import CreateIrStageProof, create_ir_stage_proof
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import BoundChoice, DialogueAnswer, QuestionSlot
from metis_model1.brain_model_runtime import ModelCandidate, StaticModelRuntime
from metis_model1.brain_protocol import CAPABILITIES, BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_server import BrainApplication, BrainRuntime, _ThreadingBrainHTTPServer
from metis_model1.brain_sessions import ClientPolicy, SessionManager
from metis_model1.brain_turns import (
    TYPED_CREATE_CLARIFICATION_RECEIPT_CONTRACT,
    TYPED_CREATE_QUALIFICATION_RECEIPT_CONTRACT,
    ClarificationAnswerRequest,
    TurnRecord,
    TurnRequest,
    TurnStore,
    _OrchestratorTurnRecord,
)


class FakeCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def __init__(self, statuses: list[str] | None = None) -> None:
        self.statuses = statuses or ["ok"]
        self.calls = 0
        self.candidate_sources: list[str] = []

    def compile(self, *, lease: Any, source: str, filename: str, **_kwargs: Any) -> dict[str, Any]:
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        return {
            "schema_version": 1,
            "status": status,
            "diagnostics": [] if status == "ok" else [{"code": "E_TEST"}],
            "toolchain_binding": self.toolchain_binding,
            "receipt_sha256": canonical_sha256({"status": status, "source": source}),
            "session_id": lease.session_id,
            "filename": filename,
        }

    def compile_candidate(
        self,
        *,
        lease: Any,
        source: str,
        filename: str,
        endpoint: str,
    ) -> object:
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        self.candidate_sources.append(source)
        receipt = {
            "schema_version": 1,
            "status": status,
            "compiler": {"status": status, "diagnostics": []},
            "toolchain_binding": self.toolchain_binding,
            "receipt_sha256": canonical_sha256({"status": status, "source": source}),
            "session_id": lease.session_id,
            "filename": filename,
        }
        if status != "ok":
            return SimpleNamespace(receipt=receipt, manifest=None, manifest_sha256=None)
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "endpoint": endpoint,
            "endpoint_sha256": "sha256:" + "1" * 64,
            "containers": [
                {
                    "path": "endpoint",
                    "kind": "endpoint",
                    "name": endpoint,
                    "activation_sha256": None,
                    "output_sha256": None,
                    "fallback_sha256": None,
                    "uses_sha256": None,
                    "semantics_sha256": "sha256:" + "8" * 64,
                    "presentation_sha256": "sha256:" + "2" * 64,
                }
            ],
            "fetches": [
                {
                    "occurrence": 0,
                    "stage_id": "endpoint.take.0",
                    "container_path": "endpoint",
                    "source": {"kind": "catalog", "ref": "video"},
                    "catalog": "video",
                    "count": {"skip": 0, "take": 24},
                    "activation_sha256": None,
                    "ordering_sha256": "sha256:" + "3" * 64,
                    "output_sha256": None,
                    "fallback_sha256": None,
                    "predicates": [],
                    "semantics_sha256": "sha256:" + "4" * 64,
                }
            ],
        }
        return SimpleNamespace(
            receipt=receipt,
            manifest=manifest,
            manifest_sha256=canonical_sha256(manifest),
        )


class FakeRetriever:
    def __init__(
        self,
        *,
        catalogs: tuple[dict[str, str], ...] = ({"catalog": "video", "label": "Video"},),
        grounding_status: str | None = None,
    ) -> None:
        self.catalogs = catalogs
        self.grounding_status = grounding_status

    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        revision = semantic_revision(lease.snapshot)
        grounding = {
            "catalogs": [item["catalog"] for item in self.catalogs],
            "selections": [],
            "resolutions": [],
            "unresolved": [],
        }
        if self.grounding_status is not None:
            grounding["status"] = self.grounding_status
            grounding["candidates"] = [{"field": "tipologia", "literal": "Film"}]
        return RetrievalResult(
            context={"tenant": lease.tenant_alias},
            grounding=grounding,
            semantic_source_revision=revision,
            catalog_candidates=self.catalogs,
        )


class BlockingCatalogRetriever:
    """Hold the first retrieval open to exercise cancellation lifecycle races."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        del request
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            assert self.release.wait(timeout=5)
        revision = semantic_revision(lease.snapshot)
        catalogs = (
            {"catalog": "video", "label": "Video"},
            {"catalog": "users", "label": "Utenti"},
        )
        return RetrievalResult(
            context={"tenant": lease.tenant_alias},
            grounding={
                "status": "clarify",
                "catalogs": [],
                "selections": [],
                "resolutions": [],
                "unresolved": [],
            },
            semantic_source_revision=revision,
            catalog_candidates=catalogs,
        )


class BlockingSingleCatalogRetriever(FakeRetriever):
    def __init__(self) -> None:
        super().__init__(catalogs=({"catalog": "video", "label": "Video"},))
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            assert self.release.wait(timeout=5)
        return super().retrieve(lease=lease, request=request)


class CountingStaticModel(StaticModelRuntime):
    def __init__(self) -> None:
        super().__init__("metis 0.43\ntenant candidate {}\n")
        self.calls = 0

    def generate(self, request: Any):
        self.calls += 1
        return super().generate(request)


def _tenant(root: Path) -> Path:
    root.mkdir()
    (root / "metis.toml").write_text(
        '[tenant]\nid = "tenant-one"\n\n[stdlib]\nlanguage = "0.43"\n', encoding="utf-8"
    )
    (root / "main.metis").write_text("metis 0.43\ntenant tenant_one {}\n", encoding="utf-8")
    return root.resolve()


@contextmanager
def _service(tmp_path: Path, *, model: Any, compiler: FakeCompiler, retriever: Any = None):
    runtime = BrainRuntime((tmp_path / "runtime").resolve())
    tenant = _tenant(tmp_path / "tenant")
    manager = SessionManager(
        registry=TenantRegistry([("demo", "tenant-one", tenant)]),
        policies=[ClientPolicy("visix", frozenset({"demo"}), CAPABILITIES)],
        runtime_root=runtime.run_dir / "sessions",
        toolchain_binding=compiler.toolchain_binding,
    )
    app = BrainApplication(
        runtime=runtime,
        manager=manager,
        compiler=compiler,
        model=model,
        retriever=retriever or FakeRetriever(),
    )
    server = _ThreadingBrainHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runtime, app
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.close()
        manager.shutdown()
        runtime.close()


def _request(
    server: Any,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection.request(
        method,
        path,
        body=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    response = connection.getresponse()
    raw = response.read()
    result = json.loads(raw.decode()) if raw else {}
    connection.close()
    return response.status, result, dict(response.getheaders())


def _open(server: Any, runtime: BrainRuntime) -> dict[str, Any]:
    status, payload, _ = _request(
        server,
        "POST",
        "/v1/sessions",
        token=runtime.bootstrap_file.read_text().strip(),
        body={"client_id": "visix", "tenant_alias": "demo", "capabilities": sorted(CAPABILITIES)},
    )
    assert status == 201
    return payload["session"]


def _turn_request(
    session: dict[str, Any], semantic: str, *, request_id: str | None = None
) -> dict[str, Any]:
    return TurnRequest(
        1,
        request_id or str(uuid.uuid4()),
        session["context_revision"],
        semantic,
        "create",
        "crea un endpoint video",
        {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        None,
        None,
    ).payload()


def _wait_turn(server: Any, session: dict[str, Any], turn_id: str) -> dict[str, Any]:
    for _ in range(200):
        status, result, _ = _request(
            server,
            "GET",
            f"/v1/sessions/{session['id']}/turns/{turn_id}",
            token=session["token"],
        )
        assert status == 200
        if result.get("status") in {"completed", "failed", "cancelled"}:
            return result
        time.sleep(0.01)
    raise AssertionError("turn did not reach a terminal state")


def _named_create_request(
    session: dict[str, Any],
    semantic: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    body = _turn_request(session, semantic, request_id=request_id)
    body.update(
        schema_version=2,
        target={**body["target"], "endpoint": "demo.head"},
    )
    return body


def _scripted_proposal(record: Any, request: TurnRequest, ordinal: int) -> dict[str, Any]:
    source = (
        "metis 0.43\n"
        f"// private head {ordinal}\n"
        f"endpoint {request.target['endpoint']} {{ take 24 from @video }}\n"
    )
    manifest = {
        "schema_version": 1,
        "endpoint": request.target["endpoint"],
        "endpoint_sha256": "sha256:" + f"{ordinal:x}"[-1] * 64,
        "containers": [],
        "fetches": [],
    }
    record.candidate_manifest = manifest
    record.candidate_manifest_sha256 = canonical_sha256(manifest)
    return {
        "schema_version": request.schema_version,
        "turn_id": record.turn_id,
        "request_id": request.request_id,
        "status": "completed",
        "route": "local",
        "outcome": "proposed",
        "proposal": {
            "proposal_ref": f"proposal-head-{ordinal}",
            "source": source,
            "source_sha256": bytes_sha256(source.encode("utf-8")),
        },
    }


def _typed_create_state(
    *,
    generation: int,
    parent_ir: Any | None,
    marker: str,
    history_texts: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    spec = {
        "schema_version": 1,
        "contract_id": "metis-brain-create-endpoint-spec/v1",
        "endpoint": {"name": "demo.head", "marker": marker},
    }
    ir = {
        "kind": "Endpoint",
        "name": "demo.head",
        "generation": generation,
        "private_marker": marker,
    }
    proof = create_ir_stage_proof(parent_ir, ir)
    history = _create_history(*(history_texts or (marker,)))
    return {
        "spec": spec,
        "spec_sha256": canonical_sha256(spec),
        "ir": ir,
        "ir_sha256": canonical_sha256(ir),
        "proof": proof,
        "generation": generation,
        "history": history,
        "history_revision": create_authority_history_revision(history),
    }


def _create_history(*messages: str) -> tuple[CreateAuthorityHistoryMessage, ...]:
    return tuple(
        CreateAuthorityHistoryMessage(
            ordinal=ordinal,
            text=message,
            message_sha256=bytes_sha256(message.encode("utf-8")),
        )
        for ordinal, message in enumerate(messages)
    )


def _attach_typed_create_state(record: Any, *, prefix: str, state: dict[str, Any]) -> None:
    if prefix == "candidate":
        basis_history = record.basis_create_history
        instruction = record.request.instruction
        if basis_history is None:
            history = _create_history(instruction)
        elif (
            record.request.clarification_response is not None
            and basis_history[-1].text == instruction
        ):
            history = tuple(basis_history)
        else:
            history = _create_history(*(item.text for item in basis_history), instruction)
        state["history"] = history
        state["history_revision"] = create_authority_history_revision(history)
    setattr(record, f"{prefix}_create_spec", state["spec"])
    setattr(record, f"{prefix}_create_spec_sha256", state["spec_sha256"])
    setattr(record, f"{prefix}_create_ir", state["ir"])
    setattr(record, f"{prefix}_create_ir_sha256", state["ir_sha256"])
    setattr(record, f"{prefix}_create_proof", state["proof"])
    setattr(record, f"{prefix}_create_generation", state["generation"])
    setattr(record, f"{prefix}_create_history", state["history"])
    setattr(record, f"{prefix}_create_history_revision", state["history_revision"])


def _dialogue_script(trace, *, fail_after_answer=False, blocked=None):
    def scripted(orchestrator, **kwargs):
        record, request = kwargs["record"], kwargs["request"]
        state = record.dialogue_state
        assert state == request.server_dialogue
        assert state is not request.server_dialogue
        trace.append(state)
        if not state.decisions:
            choices = tuple(
                BoundChoice(
                    name, (f"private.{name}",), state.binding.semantic_revision, ("catalog",)
                )
                for name in ("Video", "Users")
            )
            slots = (
                QuestionSlot(
                    "catalogs",
                    "endpoint",
                    "catalog",
                    "Quali cataloghi?",
                    "option_refs",
                    choices,
                    maximum=2,
                ),
                QuestionSlot(
                    "count",
                    "row.main",
                    "result_count",
                    "Quanti risultati per riga?",
                    "integer",
                    maximum=100,
                    value_contract="total",
                ),
            )
            pending = orchestrator._clarifications.create_pending_v2(
                session_id=record.session_id,
                parent_turn_id=record.turn_id,
                conversation_id=record.conversation_id,
                binding=state.binding,
                slots=slots,
            )
            return {
                "schema_version": 2,
                "turn_id": record.turn_id,
                "request_id": request.request_id,
                "status": "completed",
                "outcome": "needs_clarification",
                "clarification": pending.payload(),
            }
        if blocked is not None:
            blocked[0].set()
            assert blocked[1].wait(timeout=5)
        if fail_after_answer:
            raise BrainError("TEST_FAILURE", 422, "synthetic failure")
        result = _scripted_proposal(record, request, len(state.messages))
        generation = (
            0 if record.basis_create_generation is None else record.basis_create_generation + 1
        )
        typed = _typed_create_state(
            generation=generation, parent_ir=record.basis_create_ir, marker=f"stage-{generation}"
        )
        _attach_typed_create_state(record, prefix="candidate", state=typed)
        record.candidate_create_history = state.messages
        record.candidate_create_history_revision = state.binding.history_revision
        return result

    return scripted


def _dialogue_answer_body(
    terminal, *, message="Video e users, 24 risultati per riga.", partial=False
):
    questions = terminal["clarification"]["questions"]
    answers = []
    for question in questions:
        if question["kind"] == "catalog":
            answers.append(
                {
                    "question_ref": question["question_ref"],
                    "value": {"option_refs": [item["option_ref"] for item in question["options"]]},
                }
            )
        elif not partial:
            answers.append({"question_ref": question["question_ref"], "value": {"integer": 24}})
    return {
        "schema_version": 2,
        "request_id": str(uuid.uuid4()),
        "clarification_id": terminal["clarification"]["clarification_id"],
        "message": message,
        "answers": answers,
    }


@pytest.mark.parametrize("partial", [False, True])
def test_dialogue_v2_http_history_before_draft_partial_retry_and_refinement(
    tmp_path, monkeypatch, partial
):
    trace = []
    monkeypatch.setattr(
        "metis_model1.brain_orchestrator.BrainOrchestrator.run", _dialogue_script(trace)
    )
    compiler = FakeCompiler()
    with _service(tmp_path, model=StaticModelRuntime("unused"), compiler=compiler) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        semantic = (
            TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")])
            .capture("demo", toolchain_binding=compiler.toolchain_binding)
            .semantic_source_revision()
        )
        collection = f"/v1/sessions/{session['id']}/turns"
        body = _named_create_request(session, semantic)
        body["instruction"] = "Voglio una homepage personalizzata."
        status, accepted, _ = _request(
            server, "POST", collection, token=session["token"], body=body
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["outcome"] == "needs_clarification"
        first_record = app.turns._turns[first["turn_id"]]
        assert [m.text for m in first_record.dialogue_state.messages] == [body["instruction"]]
        assert first_record.dialogue_state.latest_proposal_binding is None
        answer = _dialogue_answer_body(first, partial=partial)
        status, accepted, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=answer,
        )
        assert status == 202
        current = _wait_turn(server, session, accepted["turn_id"])
        second_record = app.turns._turns[current["turn_id"]]
        assert second_record.conversation_id == first_record.conversation_id
        assert second_record.request.request_fingerprint != first_record.request.request_fingerprint
        history = [body["instruction"], answer["message"]]
        assert [m.text for m in second_record.dialogue_state.messages] == history
        status, replay, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=answer,
        )
        assert status == 202 and replay["turn_id"] == second_record.turn_id
        assert [m.text for m in second_record.dialogue_state.messages] == history
        if partial:
            assert current["outcome"] == "needs_clarification"
            assert (
                current["clarification"]["clarification_id"]
                != first["clarification"]["clarification_id"]
            )
            assert current["clarification"]["round"] == 1
            # A button-only answer must not duplicate the previous text.
            remaining = _dialogue_answer_body(current, message=None)
            status, accepted, _ = _request(
                server,
                "POST",
                f"{collection}/{current['turn_id']}/answer",
                token=session["token"],
                body=remaining,
            )
            assert status == 202
            current = _wait_turn(server, session, accepted["turn_id"])
        assert current["outcome"] == "proposed"
        draft_record = app.turns._turns[current["turn_id"]]
        assert [m.text for m in draft_record.candidate_create_history] == history
        assert len(draft_record.dialogue_state.decisions) == 2
        assert draft_record.dialogue_state.latest_proposal_binding is not None
        refine = {
            **body,
            "request_id": str(uuid.uuid4()),
            "instruction": "Aggiungi una riga per le serie.",
            "basis": {"kind": "proposal", "proposal_ref": current["proposal"]["proposal_ref"]},
        }
        status, accepted, _ = _request(
            server, "POST", collection, token=session["token"], body=refine
        )
        assert status == 202
        final = _wait_turn(server, session, accepted["turn_id"])
        assert final["outcome"] == "proposed"
        final_record = app.turns._turns[final["turn_id"]]
        assert [m.text for m in final_record.dialogue_state.messages] == [
            *history,
            refine["instruction"],
        ]
        assert final_record.candidate_create_generation == 1
        encoded = json.dumps(final)
        assert "private.Video" not in encoded and body["instruction"] not in encoded
        assert body["instruction"] not in repr(final_record)
        assert compiler.calls == 0
        manager_session = session["id"]
        app.manager.close(session_id=manager_session, token=session["token"])
        assert all(
            record.dialogue_state is None and record.request.server_dialogue is None
            for record in (first_record, second_record, draft_record, final_record)
        )


@pytest.mark.parametrize("resolve", [False, True])
def test_dialogue_v2_message_only_is_preserved_and_requires_host_adjudication(
    tmp_path, monkeypatch, resolve
):
    trace = []
    monkeypatch.setattr(
        "metis_model1.brain_orchestrator.BrainOrchestrator.run", _dialogue_script(trace)
    )
    compiler = FakeCompiler()
    with _service(tmp_path, model=StaticModelRuntime("unused"), compiler=compiler) as (
        server,
        runtime,
        app,
    ):
        if resolve:

            def host_resolver(*, request, pending, dialogue):
                assert dialogue.messages[-1].text == request.instruction
                return tuple(
                    DialogueAnswer(slot.question_ref, integer=24)
                    if slot.answer_kind == "integer"
                    else DialogueAnswer(
                        slot.question_ref,
                        tuple(choice.option_ref for choice in slot.choices),
                        multiple=True,
                    )
                    for slot in pending.slots
                )

            app.turns._dialogue_answer_resolver = host_resolver
        session = _open(server, runtime)
        semantic = (
            TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")])
            .capture("demo", toolchain_binding=compiler.toolchain_binding)
            .semantic_source_revision()
        )
        collection = f"/v1/sessions/{session['id']}/turns"
        body = _named_create_request(session, semantic)
        _, accepted, _ = _request(server, "POST", collection, token=session["token"], body=body)
        first = _wait_turn(server, session, accepted["turn_id"])
        answer = _dialogue_answer_body(first)
        answer["answers"] = []
        status, accepted, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=answer,
        )
        assert status == 202
        final = _wait_turn(server, session, accepted["turn_id"])
        assert final["outcome"] == ("proposed" if resolve else "needs_clarification")
        state = app.turns._turns[final["turn_id"]].dialogue_state
        assert [m.text for m in state.messages] == [body["instruction"], answer["message"]]
        assert len(state.decisions) == (2 if resolve else 0)
        assert len(trace) == (2 if resolve else 1)


def test_dialogue_v2_carries_server_grounding_across_partial_ask_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _pending_dialogue(tmp_path, monkeypatch) as (
        server,
        app,
        session,
        collection,
        first,
        _trace,
    ):
        grounding = {
            "status": "resolved",
            "catalogs": ["demo.video"],
            "selections": [{"catalog": "demo.video", "field": "tipologia", "literal": "Film"}],
            "semantic_source_revision": "sha256:" + "b" * 64,
        }
        parent = app.turns._turns[first["turn_id"]]
        parent.terminal["grounding"] = deepcopy(grounding)

        status, accepted, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=_dialogue_answer_body(first, partial=True),
        )
        assert status == 202
        second = _wait_turn(server, session, accepted["turn_id"])
        assert second["outcome"] == "needs_clarification"
        second_record = app.turns._turns[second["turn_id"]]
        assert second_record.basis_grounding == grounding
        assert second_record.request.server_basis_grounding == grounding
        assert second_record.basis_grounding is not parent.terminal["grounding"]

        status, accepted, _ = _request(
            server,
            "POST",
            f"{collection}/{second['turn_id']}/answer",
            token=session["token"],
            body=_dialogue_answer_body(second, message=None),
        )
        assert status == 202
        final = _wait_turn(server, session, accepted["turn_id"])
        assert final["outcome"] == "proposed"
        final_record = app.turns._turns[final["turn_id"]]
        assert final_record.basis_grounding == grounding
        assert final_record.request.server_basis_grounding == grounding
        assert final_record.basis_grounding is not second_record.basis_grounding


@contextmanager
def _pending_dialogue(tmp_path, monkeypatch, *, script=None):
    trace = []
    monkeypatch.setattr(
        "metis_model1.brain_orchestrator.BrainOrchestrator.run",
        script or _dialogue_script(trace),
    )
    compiler = FakeCompiler()
    with _service(tmp_path, model=StaticModelRuntime("unused"), compiler=compiler) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        semantic = (
            TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")])
            .capture("demo", toolchain_binding=compiler.toolchain_binding)
            .semantic_source_revision()
        )
        body = _named_create_request(session, semantic)
        collection = f"/v1/sessions/{session['id']}/turns"
        status, accepted, _ = _request(
            server, "POST", collection, token=session["token"], body=body
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["outcome"] == "needs_clarification"
        yield server, app, session, collection, first, trace
        assert compiler.calls == 0


@pytest.mark.parametrize(
    "attack", ["unknown", "duplicate", "cross-slot", "private", "stale", "parent-fingerprint"]
)
def test_dialogue_v2_invalid_roster_is_atomic_and_original_pending_retryable(
    tmp_path, monkeypatch, attack
):
    with _pending_dialogue(tmp_path, monkeypatch) as (
        server,
        app,
        session,
        collection,
        first,
        trace,
    ):
        answer = _dialogue_answer_body(first)
        if attack == "unknown":
            answer["answers"][0]["value"]["option_refs"] = ["option-unknown"]
        elif attack == "duplicate":
            answer["answers"].append(answer["answers"][0])
        elif attack == "cross-slot":
            answer["answers"][0]["question_ref"] = answer["answers"][1]["question_ref"]
            answer["answers"].pop()
        elif attack == "private":
            answer["authority_keys"] = ["private.Users"]
        elif attack == "stale":
            parent = app.turns._turns[first["turn_id"]]
            parent.dialogue_state = replace(
                parent.dialogue_state,
                binding=replace(
                    parent.dialogue_state.binding, toolchain_binding="sha256:" + "f" * 64
                ),
            )
        else:
            parent = app.turns._turns[first["turn_id"]]
            original_request = parent.request
            parent.request = replace(parent.request, instruction="Unrelated replaced parent")
        status, rejected, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=answer,
        )
        assert status in {400, 409}
        assert "error" in rejected
        assert len(trace) == 1
        assert app.turns.clarifications.metrics()["pending"] == 1
        parent = app.turns._turns[first["turn_id"]]
        assert not app.turns.clarifications.decisions_v2(
            session_id=session["id"], conversation_id=parent.conversation_id
        )
        if attack == "stale":
            parent.dialogue_state = replace(trace[0])
        elif attack == "parent-fingerprint":
            parent.request = original_request
        status, accepted, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=_dialogue_answer_body(first),
        )
        assert status == 202
        assert _wait_turn(server, session, accepted["turn_id"])["outcome"] == "proposed"


@pytest.mark.parametrize("lifecycle", ["close", "ttl", "shutdown"])
@pytest.mark.parametrize("partial", [False, True])
def test_dialogue_v2_session_erasure_including_rotated_pending(
    tmp_path, monkeypatch, lifecycle, partial
):
    with _pending_dialogue(tmp_path, monkeypatch) as (
        server,
        app,
        session,
        collection,
        first,
        _trace,
    ):
        if partial:
            status, accepted, _ = _request(
                server,
                "POST",
                f"{collection}/{first['turn_id']}/answer",
                token=session["token"],
                body=_dialogue_answer_body(first, partial=True),
            )
            assert status == 202
            assert (
                _wait_turn(server, session, accepted["turn_id"])["outcome"] == "needs_clarification"
            )
        held = tuple(app.turns._turns.values())
        if lifecycle == "close":
            app.manager.close(session_id=session["id"], token=session["token"])
        elif lifecycle == "ttl":
            now = app.manager._monotonic()
            app.manager._monotonic = lambda: now + 1_201
            assert app.manager.sweep_expired() == 1
        else:
            app.turns.shutdown()
        for record in held:
            assert record.dialogue_state is None and record.dialogue_pending is None
            assert record.request.server_dialogue is None
            assert record.request.instruction == ""
            assert record.request.clarification_response is None
        assert app.turns.clarifications.metrics()["pending"] == 0
        assert app.turns.clarifications.metrics()["decisions"] == 0


@pytest.mark.parametrize("lifecycle", ["failure", "cancel", "mutation"])
def test_dialogue_v2_failed_or_cancelled_answer_erases_state_and_cannot_republish(
    tmp_path, monkeypatch, lifecycle
):
    trace = []
    entered, release = threading.Event(), threading.Event()
    original = _dialogue_script(
        trace,
        fail_after_answer=lifecycle == "failure",
        blocked=(entered, release) if lifecycle == "cancel" else None,
    )
    staged_records = []

    def scripted(orchestrator, **kwargs):
        staged_records.append(kwargs["record"])
        result = original(orchestrator, **kwargs)
        if lifecycle == "mutation" and kwargs["record"].dialogue_state.decisions:
            kwargs["record"].dialogue_state = replace(
                kwargs["record"].dialogue_state,
                generation=kwargs["record"].dialogue_state.generation + 1,
            )
        return result

    with _pending_dialogue(tmp_path, monkeypatch, script=scripted) as (
        server,
        app,
        session,
        collection,
        first,
        _unused,
    ):
        status, accepted, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=_dialogue_answer_body(first),
        )
        assert status == 202
        held = app.turns._turns[accepted["turn_id"]]
        try:
            if lifecycle == "cancel":
                assert entered.wait(timeout=5)
                status, _body, _ = _request(
                    server,
                    "DELETE",
                    f"{collection}/{accepted['turn_id']}",
                    token=session["token"],
                )
                assert status == 200
        finally:
            release.set()
        terminal = _wait_turn(server, session, accepted["turn_id"])
        assert terminal["status"] == ("cancelled" if lifecycle == "cancel" else "failed")
        if lifecycle == "mutation":
            assert terminal["error"]["code"] == "PROPOSAL_STALE"
        app.turns._executor.submit(lambda: None).result(timeout=5)
        assert held.dialogue_state is None and held.dialogue_pending is None
        assert held.request.server_dialogue is None
        assert held.request.instruction == "" and held.request.clarification_response is None
        assert all(record.dialogue_state is None for record in staged_records)
        assert app.turns.clarifications.metrics()["pending"] == 0
        assert "private.Video" not in json.dumps(terminal)


def _assert_no_typed_create_state(record: Any) -> None:
    for prefix in ("basis", "candidate"):
        for suffix in (
            "spec",
            "spec_sha256",
            "ir",
            "ir_sha256",
            "proof",
            "generation",
            "history",
            "history_revision",
        ):
            assert getattr(record, f"{prefix}_create_{suffix}") is None


def test_turn_request_v2_parses_typed_clarification_and_stable_fingerprint() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    base = {
        "schema_version": 2,
        "request_id": str(uuid.uuid4()),
        "expected_context_revision": context,
        "expected_semantic_source_revision": semantic,
        "intent": "create",
        "instruction": "crea un endpoint video",
        "target": {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        "basis": None,
        "clarification_response": None,
    }
    original = TurnRequest.parse(base)
    answered = TurnRequest.parse(
        {
            **base,
            "request_id": str(uuid.uuid4()),
            "clarification_response": {
                "clarification_id": "clarification-123456789012345678901234",
                "answer": {"integer": 24},
                "context_revision": context,
                "semantic_source_revision": semantic,
            },
        }
    )

    assert answered.schema_version == 2
    assert answered.clarification_answer == {"integer": 24}
    assert answered.request_fingerprint == original.request_fingerprint
    assert answered.payload_hash != original.payload_hash


def test_catalog_text_answer_is_additive_for_schema_two_and_answer_endpoint() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    payload = {
        "schema_version": 2,
        "request_id": str(uuid.uuid4()),
        "expected_context_revision": context,
        "expected_semantic_source_revision": semantic,
        "intent": "create",
        "instruction": "crea un endpoint video",
        "target": {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        "basis": None,
        "clarification_response": {
            "clarification_id": "clarification-123456789012345678901234",
            "answer": {"text": "play-prod-v2.video"},
            "context_revision": context,
            "semantic_source_revision": semantic,
        },
    }

    parsed = TurnRequest.parse(payload)
    assert parsed.clarification_answer == {"text": "play-prod-v2.video"}
    standalone = ClarificationAnswerRequest.parse(
        {
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
            "clarification_id": "clarification-123456789012345678901234",
            "answer": {"text": "play-prod-v2.video"},
        }
    )
    assert standalone.answer == {"text": "play-prod-v2.video"}


def test_create_target_reference_is_first_class_and_legacy_payload_normalizes() -> None:
    base = {
        "schema_version": 2,
        "request_id": str(uuid.uuid4()),
        "expected_context_revision": "sha256:" + "a" * 64,
        "expected_semantic_source_revision": "sha256:" + "b" * 64,
        "intent": "create",
        "instruction": "crea endpoint demo.example as brainExample",
        "target": {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": "demo.example",
            "base_sha256": None,
        },
        "basis": None,
        "clarification_response": None,
    }
    legacy = TurnRequest.parse(base)
    with_reference = TurnRequest.parse(
        {
            **base,
            "request_id": str(uuid.uuid4()),
            "target": {**base["target"], "reference": "brainExample"},
        }
    )

    assert legacy.target["reference"] is None
    assert with_reference.target["reference"] == "brainExample"
    assert with_reference.request_fingerprint != legacy.request_fingerprint


@pytest.mark.parametrize(
    "target",
    [
        {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": "demo.example",
            "base_sha256": None,
            "reference": "bad-reference",
        },
        {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
            "reference": "brainExample",
        },
        {
            "mode": "existing",
            "relative_path": "candidate.metis",
            "endpoint": "demo.example",
            "base_sha256": "sha256:" + "c" * 64,
            "reference": "brainExample",
        },
    ],
)
def test_target_reference_rejects_invalid_or_non_create_binding(
    target: dict[str, Any],
) -> None:
    with pytest.raises(BrainError) as raised:
        TurnRequest.parse(
            {
                "schema_version": 2,
                "request_id": str(uuid.uuid4()),
                "expected_context_revision": "sha256:" + "a" * 64,
                "expected_semantic_source_revision": "sha256:" + "b" * 64,
                "intent": "create",
                "instruction": "crea un endpoint",
                "target": target,
                "basis": None,
                "clarification_response": None,
            }
        )
    assert raised.value.code == "INVALID_SCHEMA"


@pytest.mark.parametrize("schema_version", [True, False, 1.0, 2.0, "2"])
def test_turn_request_rejects_non_integer_schema_versions(schema_version: Any) -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    with pytest.raises(BrainError) as raised:
        TurnRequest.parse(
            {
                "schema_version": schema_version,
                "request_id": str(uuid.uuid4()),
                "expected_context_revision": context,
                "expected_semantic_source_revision": semantic,
                "intent": "create",
                "instruction": "crea un endpoint video",
                "target": {
                    "mode": "create",
                    "relative_path": "candidate.metis",
                    "endpoint": None,
                    "base_sha256": None,
                },
                "basis": None,
                "clarification_response": None,
            }
        )
    assert raised.value.code == "INVALID_SCHEMA"


@pytest.mark.parametrize("schema_version", [1, 2])
def test_active_error_and_cancel_payloads_preserve_request_schema_version(
    schema_version: int,
) -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = TurnRequest.parse(
        {
            "schema_version": schema_version,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": context,
            "expected_semantic_source_revision": semantic,
            "intent": "create",
            "instruction": "crea un endpoint video",
            "target": {
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": None,
                "base_sha256": None,
            },
            "basis": None,
            "clarification_response": None,
        }
    )
    record = TurnRecord(
        turn_id="turn_" + "a" * 32,
        session_id="session_" + "a" * 32,
        request=request,
        payload_hash=request.payload_hash,
    )

    assert record.public_status()["schema_version"] == schema_version
    assert (
        TurnStore._error_payload(  # noqa: SLF001
            record,
            BrainError("TEST_ERROR", 500, "test"),
        )["schema_version"]
        == schema_version
    )
    assert TurnStore._cancelled_payload(record)["schema_version"] == schema_version  # noqa: SLF001


def test_private_manifest_publication_requires_the_exact_current_record() -> None:
    request = TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": "sha256:" + "a" * 64,
            "expected_semantic_source_revision": "sha256:" + "b" * 64,
            "intent": "create",
            "instruction": "crea un endpoint",
            "target": {
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": "demo.private",
                "base_sha256": None,
            },
            "basis": None,
            "clarification_response": None,
        }
    )
    turn_id = "turn_" + "p" * 32
    stale = TurnRecord(turn_id, "session_" + "a" * 32, request, request.payload_hash)
    replacement = TurnRecord(turn_id, "session_" + "b" * 32, request, request.payload_hash)
    manifest = {
        "schema_version": 1,
        "endpoint": "demo.private",
        "endpoint_sha256": "sha256:" + "1" * 64,
        "containers": [],
        "fetches": [],
    }
    manifest_sha256 = canonical_sha256(manifest)
    source = "metis 0.43\nendpoint demo.private { take 1 from @video }\n"
    source_sha256 = bytes_sha256(source.encode("utf-8"))
    stale.basis_manifest = dict(manifest)
    stale.basis_manifest_sha256 = manifest_sha256
    stale.candidate_source = source
    stale.candidate_source_sha256 = source_sha256
    staged = SimpleNamespace(
        basis_manifest=dict(manifest),
        basis_manifest_sha256=manifest_sha256,
        candidate_proposal_ref="proposal-private",
        candidate_source=source,
        candidate_source_sha256=source_sha256,
        candidate_manifest=dict(manifest),
        candidate_manifest_sha256=manifest_sha256,
    )
    store = object.__new__(TurnStore)
    store._lock = threading.RLock()  # noqa: SLF001
    store._closed = False  # noqa: SLF001
    store._turns = {turn_id: replacement}  # noqa: SLF001

    assert not store._publish_private_attachments(stale, staged)  # noqa: SLF001
    assert stale.basis_manifest is None
    assert stale.basis_manifest_sha256 is None
    assert stale.candidate_source is None
    assert stale.candidate_source_sha256 is None
    assert stale.candidate_manifest is None
    assert stale.candidate_manifest_sha256 is None
    assert replacement.basis_manifest is None
    assert replacement.candidate_source is None
    assert replacement.candidate_manifest is None


def test_public_status_deep_copies_nested_proposal_authority() -> None:
    request = TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": "sha256:" + "a" * 64,
            "expected_semantic_source_revision": "sha256:" + "b" * 64,
            "intent": "create",
            "instruction": "crea un endpoint",
            "target": {
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": "demo.private",
                "base_sha256": None,
            },
            "basis": None,
            "clarification_response": None,
        }
    )
    source = "metis 0.43\nendpoint demo.private { take 1 from @video }\n"
    source_sha256 = bytes_sha256(source.encode("utf-8"))
    record = TurnRecord(
        "turn_" + "d" * 32,
        "session_" + "d" * 32,
        request,
        request.payload_hash,
        candidate_source=source,
        candidate_source_sha256=source_sha256,
    )
    record.terminal = {
        "status": "completed",
        "outcome": "proposed",
        "proposal": {
            "proposal_ref": "proposal-private",
            "source": source,
            "source_sha256": source_sha256,
            "proposal_basis": {"context_revision": request.expected_context_revision},
        },
    }

    public = record.public_status()
    public["proposal"]["source"] = "mutated"
    public["proposal"]["proposal_basis"]["context_revision"] = "mutated"

    assert record.terminal["proposal"]["source"] == source
    assert (
        record.terminal["proposal"]["proposal_basis"]["context_revision"]
        == request.expected_context_revision
    )
    assert record.candidate_source == source
    assert record.candidate_source_sha256 == source_sha256


def test_latest_head_rejects_old_basis_and_replays_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _scripted_proposal(kwargs["record"], kwargs["request"], calls)

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _named_create_request(session, snapshot.semantic_source_revision())
        status, first_accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        first = _wait_turn(server, session, first_accepted["turn_id"])

        second_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "prima revisione",
            "basis": {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]},
        }
        status, second_accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=second_body,
        )
        assert status == 202
        second = _wait_turn(server, session, second_accepted["turn_id"])
        assert second["outcome"] == "proposed"

        status, replayed_first, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        assert replayed_first["turn_id"] == first_accepted["turn_id"]

        stale_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "ramo vietato",
            "basis": {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]},
        }
        status, stale, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=stale_body,
        )
        assert status == 409 and stale["error"]["code"] == "PROPOSAL_STALE"

        status, replayed, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=second_body,
        )
        assert status == 202
        assert replayed["turn_id"] == second_accepted["turn_id"]
        assert calls == 2
        head = next(iter(app.turns._proposal_heads.values()))  # noqa: SLF001
        assert head.turn_id == second_accepted["turn_id"]

        no_basis = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "secondo inizio sullo stesso target",
        }
        status, rejected, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=no_basis,
        )
        assert status == 409 and rejected["error"]["code"] == "PROPOSAL_STALE"


def test_typed_create_state_isolated_publish_transfer_and_head_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    staged_graphs: list[dict[str, Any]] = []

    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        staged = kwargs["record"]
        parent_ir = staged.basis_create_ir
        state = _typed_create_state(
            generation=calls - 1,
            parent_ir=parent_ir,
            marker=f"private-create-{calls}",
        )
        staged_graphs.append(state)
        _attach_typed_create_state(staged, prefix="candidate", state=state)
        return _scripted_proposal(staged, kwargs["request"], calls)

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        first_public = _wait_turn(server, session, accepted["turn_id"])
        assert first_public["outcome"] == "proposed"
        first = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        assert first.candidate_create_generation == 0
        assert first.candidate_create_proof == create_ir_stage_proof(
            None, first.candidate_create_ir
        )
        assert first.candidate_create_spec is not staged_graphs[0]["spec"]
        assert first.candidate_create_ir is not staged_graphs[0]["ir"]
        assert first.candidate_create_history is not staged_graphs[0]["history"]
        assert first.candidate_create_history == _create_history(first_body["instruction"])
        assert first.candidate_create_history_revision == create_authority_history_revision(
            first.candidate_create_history
        )
        staged_graphs[0]["spec"]["endpoint"]["marker"] = "mutated-after-publish"
        staged_graphs[0]["ir"]["private_marker"] = "mutated-after-publish"
        staged_graphs[0]["history"] = _create_history("mutated-after-publish")
        assert first.candidate_create_spec["endpoint"]["marker"] == "private-create-1"
        assert first.candidate_create_ir["private_marker"] == "private-create-1"
        assert first.candidate_create_history == _create_history(first_body["instruction"])

        refined_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "aggiungi il raffinamento",
            "basis": {
                "kind": "proposal",
                "proposal_ref": first_public["proposal"]["proposal_ref"],
            },
        }
        status, accepted_refined, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=refined_body,
        )
        assert status == 202
        refined_public = _wait_turn(server, session, accepted_refined["turn_id"])
        assert refined_public["outcome"] == "proposed"
        refined = app.turns._turns[accepted_refined["turn_id"]]  # noqa: SLF001
        assert refined.basis_create_spec == first.candidate_create_spec
        assert refined.basis_create_spec is not first.candidate_create_spec
        assert refined.basis_create_ir == first.candidate_create_ir
        assert refined.basis_create_ir is not first.candidate_create_ir
        assert refined.basis_create_history == first.candidate_create_history
        assert refined.basis_create_history is not first.candidate_create_history
        assert refined.basis_create_generation == 0
        assert refined.candidate_create_generation == 1
        assert tuple(item.text for item in refined.candidate_create_history) == (
            first_body["instruction"],
            refined_body["instruction"],
        )
        assert refined.candidate_create_proof.parent_ir_sha256 == first.candidate_create_ir_sha256
        head = next(iter(app.turns._proposal_heads.values()))  # noqa: SLF001
        assert head.create_spec_sha256 == refined.candidate_create_spec_sha256
        assert head.create_ir_sha256 == refined.candidate_create_ir_sha256
        assert head.create_proof == refined.candidate_create_proof
        assert head.create_generation == 1
        assert head.create_history_revision == refined.candidate_create_history_revision

        status, replayed, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=refined_body,
        )
        assert status == 202
        assert replayed["turn_id"] == accepted_refined["turn_id"]
        assert calls == 2
        assert refined.candidate_create_history == _create_history(
            first_body["instruction"], refined_body["instruction"]
        )

        public_wire = json.dumps(
            {"status": refined.public_status(), "events": refined.events},
            sort_keys=True,
        )
        assert "private-create-2" not in public_wire
        assert "candidate_create" not in public_wire


def test_typed_create_qualification_receipt_is_hash_only_and_session_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler_receipt_sha256 = "sha256:" + "c" * 64

    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        staged = kwargs["record"]
        state = _typed_create_state(
            generation=0,
            parent_ir=None,
            marker="private-receipt-marker",
        )
        _attach_typed_create_state(staged, prefix="candidate", state=state)
        result = _scripted_proposal(staged, kwargs["request"], 1)
        result["validation"] = {
            "status": "ok",
            "attempts": 1,
            "compiler_receipt_sha256": compiler_receipt_sha256,
        }
        result["identity"] = {"generation_strategy": "model_create_plan_v2"}
        return result

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        terminal = _wait_turn(server, session, accepted["turn_id"])
        assert terminal["outcome"] == "proposed"

        receipt = app.turns.seal_typed_create_qualification_receipt(
            session_id=session["id"],
            token=session["token"],
            turn_id=accepted["turn_id"],
        )
        assert receipt["contract_id"] == TYPED_CREATE_QUALIFICATION_RECEIPT_CONTRACT
        assert receipt["generation_strategy"] == "model_create_plan_v2"
        assert receipt["compiler_receipt_sha256"] == compiler_receipt_sha256
        assert receipt["receipt_sha256"] == canonical_sha256(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        wire = json.dumps(receipt, sort_keys=True)
        assert "private-receipt-marker" not in wire
        assert "metis 0.43" not in wire
        assert "spec" not in receipt and "ir" not in receipt and "source" not in receipt

        status, _, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )
        assert status == 200
        with pytest.raises(BrainError) as unavailable:
            app.turns.seal_typed_create_qualification_receipt(
                session_id=session["id"],
                token=session["token"],
                turn_id=accepted["turn_id"],
            )
        assert unavailable.value.code == "SESSION_UNAVAILABLE"


def test_typed_create_clarification_receipt_seals_only_the_private_gap_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[Any] = []
    monkeypatch.setattr(
        "metis_model1.brain_orchestrator.BrainOrchestrator.run", _dialogue_script(trace)
    )
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("unused"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        terminal = _wait_turn(server, session, accepted["turn_id"])
        assert terminal["outcome"] == "needs_clarification"

        receipt = app.turns.seal_typed_create_clarification_receipt(
            session_id=session["id"],
            token=session["token"],
            turn_id=accepted["turn_id"],
        )

        assert receipt["contract_id"] == TYPED_CREATE_CLARIFICATION_RECEIPT_CONTRACT
        assert receipt["slot_contracts"] == [
            {
                "decision_key": "catalogs",
                "target_key": "endpoint",
                "kind": "catalog",
                "answer_kind": "option_refs",
                "value_contract": "authority",
                "minimum": 1,
                "maximum": 2,
                "choice_count": 2,
            },
            {
                "decision_key": "count",
                "target_key": "row.main",
                "kind": "result_count",
                "answer_kind": "integer",
                "value_contract": "total",
                "minimum": 1,
                "maximum": 100,
                "choice_count": 0,
            },
        ]
        assert receipt["receipt_sha256"] == canonical_sha256(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        wire = json.dumps(receipt, sort_keys=True)
        assert "Quali cataloghi?" not in wire
        assert "private.Video" not in wire
        assert '"option_ref":' not in wire


def test_typed_create_clarification_receipt_seals_rotated_unanswered_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[Any] = []
    monkeypatch.setattr(
        "metis_model1.brain_orchestrator.BrainOrchestrator.run", _dialogue_script(trace)
    )
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("unused"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        collection = f"/v1/sessions/{session['id']}/turns"
        body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            collection,
            token=session["token"],
            body=body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["outcome"] == "needs_clarification"
        first_receipt = app.turns.seal_typed_create_clarification_receipt(
            session_id=session["id"],
            token=session["token"],
            turn_id=accepted["turn_id"],
        )

        unresolved = _dialogue_answer_body(first, message="Non ho ancora deciso.")
        unresolved["answers"] = []
        status, accepted, _ = _request(
            server,
            "POST",
            f"{collection}/{first['turn_id']}/answer",
            token=session["token"],
            body=unresolved,
        )
        assert status == 202
        repeated = _wait_turn(server, session, accepted["turn_id"])
        assert repeated["outcome"] == "needs_clarification"

        repeated_receipt = app.turns.seal_typed_create_clarification_receipt(
            session_id=session["id"],
            token=session["token"],
            turn_id=accepted["turn_id"],
        )
        assert repeated_receipt["turn_id"] == accepted["turn_id"]
        assert repeated_receipt["round"] == first_receipt["round"] == 1
        assert repeated_receipt["slot_contracts"] == first_receipt["slot_contracts"]
        assert repeated_receipt["binding_sha256"] == first_receipt["binding_sha256"]
        assert repeated_receipt["receipt_sha256"] == canonical_sha256(
            {key: value for key, value in repeated_receipt.items() if key != "receipt_sha256"}
        )


@pytest.mark.parametrize(
    ("clarification_retry", "expected_messages"),
    [(False, 2), (True, 1)],
)
def test_typed_create_history_appends_refinement_but_not_clarification_retry(
    clarification_retry: bool,
    expected_messages: int,
) -> None:
    instruction = "mantieni ventiquattro risultati"
    context_revision = "sha256:" + "a" * 64
    semantic_revision_value = "sha256:" + "b" * 64
    request = TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": context_revision,
            "expected_semantic_source_revision": semantic_revision_value,
            "intent": "create",
            "instruction": instruction,
            "target": {
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": "demo.head",
                "base_sha256": None,
            },
            "basis": {"kind": "proposal", "proposal_ref": "proposal-parent"},
            "clarification_response": (
                {
                    "clarification_id": "clarification-parent",
                    "answer": {"integer": 24},
                    "context_revision": context_revision,
                    "semantic_source_revision": semantic_revision_value,
                }
                if clarification_retry
                else None
            ),
        }
    )
    basis = _typed_create_state(
        generation=0,
        parent_ir=None,
        marker="basis",
        history_texts=(instruction,),
    )
    candidate = _typed_create_state(
        generation=1,
        parent_ir=basis["ir"],
        marker="candidate",
    )
    record = TurnRecord(
        turn_id="turn_" + "a" * 32,
        session_id="session_" + "a" * 32,
        request=request,
        payload_hash=request.payload_hash,
    )
    _attach_typed_create_state(record, prefix="basis", state=basis)
    _attach_typed_create_state(record, prefix="candidate", state=candidate)

    basis_state = TurnStore._create_state_from_record(record, prefix="basis")  # noqa: SLF001
    candidate_state = TurnStore._create_state_from_record(  # noqa: SLF001
        record,
        prefix="candidate",
        parent_ir=basis_state.ir,
        expected_generation=1,
    )
    TurnStore._validate_candidate_create_history(  # noqa: SLF001
        record=record,
        basis=basis_state,
        candidate=candidate_state,
    )

    assert len(candidate_state.history) == expected_messages
    assert tuple(message.text for message in candidate_state.history) == (instruction,) * (
        expected_messages
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "spec_hash",
        "ir_hash",
        "proof",
        "generation",
        "history_hash",
        "history_message",
        "history_lineage",
        "history_partial",
        "partial",
    ],
)
def test_typed_create_state_mismatch_fails_before_any_private_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        staged = kwargs["record"]
        state = _typed_create_state(
            generation=0,
            parent_ir=None,
            marker="must-never-publish",
        )
        if mutation == "spec_hash":
            state["spec_sha256"] = "sha256:" + "0" * 64
        elif mutation == "ir_hash":
            state["ir_sha256"] = "sha256:" + "0" * 64
        elif mutation == "proof":
            state["proof"] = CreateIrStageProof(
                ir_sha256=state["ir_sha256"],
                parent_ir_sha256="sha256:" + "1" * 64,
                delta_sha256=state["proof"].delta_sha256,
                delta_operation_count=state["proof"].delta_operation_count,
            )
        elif mutation == "generation":
            state["generation"] = 1
        elif mutation == "partial":
            state["ir"] = None
        _attach_typed_create_state(staged, prefix="candidate", state=state)
        if mutation == "history_hash":
            staged.candidate_create_history_revision = "sha256:" + "0" * 64
        elif mutation == "history_message":
            staged.candidate_create_history = _create_history("spoofed operator instruction")
        elif mutation == "history_lineage":
            spoofed = _create_history("spoofed operator instruction")
            staged.candidate_create_history = spoofed
            staged.candidate_create_history_revision = create_authority_history_revision(spoofed)
        elif mutation == "history_partial":
            staged.candidate_create_history_revision = None
        return _scripted_proposal(staged, kwargs["request"], 1)

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        terminal = _wait_turn(server, session, accepted["turn_id"])
        assert terminal["status"] == "failed"
        assert terminal["error"]["code"] in {"COMPILER_FAILED", "CREATE_IR_MISMATCH"}
        record = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        assert record.candidate_source is None
        assert record.candidate_manifest is None
        assert record.candidate_create_spec is None
        assert record.candidate_create_ir is None
        assert record.candidate_create_proof is None
        assert record.candidate_create_generation is None
        _assert_no_typed_create_state(record)
        assert app.turns._proposal_heads == {}  # noqa: SLF001


@pytest.mark.parametrize(
    "mutation",
    ["spec", "history_message", "history_revision"],
)
def test_mutated_latest_typed_create_authority_is_not_transferable_as_basis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        staged = kwargs["record"]
        state = _typed_create_state(
            generation=0,
            parent_ir=None,
            marker="private-before-mutation",
        )
        _attach_typed_create_state(staged, prefix="candidate", state=state)
        return _scripted_proposal(staged, kwargs["request"], 1)

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        first_public = _wait_turn(server, session, accepted["turn_id"])
        first = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        if mutation == "spec":
            first.candidate_create_spec["endpoint"]["marker"] = "tampered-in-store"
        elif mutation == "history_message":
            first.candidate_create_history = _create_history("tampered-in-store")
        else:
            first.candidate_create_history_revision = "sha256:" + "0" * 64
        refinement = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "raffina",
            "basis": {
                "kind": "proposal",
                "proposal_ref": first_public["proposal"]["proposal_ref"],
            },
        }
        status, rejected, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=refinement,
        )
        assert status == 409
        assert rejected["error"]["code"] == "PROPOSAL_STALE"


def test_staged_typed_create_basis_cannot_be_rewritten_before_atomic_publish() -> None:
    request = TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": "sha256:" + "a" * 64,
            "expected_semantic_source_revision": "sha256:" + "b" * 64,
            "intent": "create",
            "instruction": "raffina",
            "target": {
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": "demo.head",
                "base_sha256": None,
            },
            "basis": {"kind": "proposal", "proposal_ref": "proposal-parent"},
            "clarification_response": None,
        }
    )
    basis = _typed_create_state(generation=0, parent_ir=None, marker="basis")
    record = TurnRecord(
        turn_id="turn_" + "a" * 32,
        session_id="session_" + "a" * 32,
        request=request,
        payload_hash=request.payload_hash,
    )
    _attach_typed_create_state(record, prefix="basis", state=basis)
    staged = _OrchestratorTurnRecord(record)
    staged.basis_create_spec["endpoint"]["marker"] = "rewritten"
    store = object.__new__(TurnStore)
    store._lock = threading.RLock()  # noqa: SLF001
    store._closed = False  # noqa: SLF001
    store._turns = {record.turn_id: record}  # noqa: SLF001

    with pytest.raises(BrainError) as raised:
        store._publish_private_attachments(record, staged)  # noqa: SLF001
    assert raised.value.code in {"COMPILER_FAILED", "PROPOSAL_STALE"}
    assert record.basis_create_spec["endpoint"]["marker"] == "basis"
    assert record.candidate_create_spec is None


def test_latest_head_serializes_concurrent_refinements_without_branching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        ordinal = calls
        if ordinal == 2:
            entered.set()
            assert release.wait(timeout=5)
        return _scripted_proposal(kwargs["record"], kwargs["request"], ordinal)

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, _app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        basis = {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]}
        winner_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "raffinamento vincente",
            "basis": basis,
        }
        loser_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "raffinamento concorrente",
            "basis": basis,
        }
        status, winner, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=winner_body,
        )
        assert status == 202 and entered.wait(timeout=5)

        status, active, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=loser_body,
        )
        assert status == 409 and active["error"]["code"] == "TURN_ACTIVE"
        release.set()
        assert _wait_turn(server, session, winner["turn_id"])["outcome"] == "proposed"

        status, stale, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=loser_body,
        )
        assert status == 409 and stale["error"]["code"] == "PROPOSAL_STALE"
        status, replayed, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=winner_body,
        )
        assert status == 202 and replayed["turn_id"] == winner["turn_id"]
        assert calls == 2


def test_cancelled_refinement_cannot_replace_latest_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        ordinal = calls
        if ordinal == 2:
            entered.set()
            assert release.wait(timeout=5)
        return _scripted_proposal(kwargs["record"], kwargs["request"], ordinal)

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        first_turn_id = accepted["turn_id"]
        refinement = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "raffinamento da annullare",
            "basis": {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]},
        }
        status, refining, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=refinement,
        )
        assert status == 202 and entered.wait(timeout=5)
        status, _cancelling, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}/turns/{refining['turn_id']}",
            token=session["token"],
        )
        assert status == 200
        release.set()
        assert _wait_turn(server, session, refining["turn_id"])["status"] == "cancelled"
        assert next(iter(app.turns._proposal_heads.values())).turn_id == first_turn_id  # noqa: SLF001

        retry_from_head = {
            **refinement,
            "request_id": str(uuid.uuid4()),
            "instruction": "raffinamento dopo annullamento",
        }
        status, accepted_retry, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=retry_from_head,
        )
        assert status == 202
        assert _wait_turn(server, session, accepted_retry["turn_id"])["outcome"] == "proposed"


@pytest.mark.parametrize("middle_outcome", ["no_change", "failed"])
def test_failed_or_non_proposed_turn_does_not_advance_latest_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    middle_outcome: str,
) -> None:
    calls = 0

    def scripted(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls != 2:
            return _scripted_proposal(kwargs["record"], kwargs["request"], calls)
        if middle_outcome == "failed":
            raise BrainError("TEST_FAILURE", 503, "injected failure")
        request = kwargs["request"]
        return {
            "schema_version": request.schema_version,
            "turn_id": kwargs["record"].turn_id,
            "request_id": request.request_id,
            "status": "completed",
            "route": "local",
            "outcome": "no_change",
            "proposal": None,
        }

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", scripted)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        first_turn_id = accepted["turn_id"]
        basis = {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]}
        middle_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "tentativo senza nuova proposta",
            "basis": basis,
        }
        status, middle, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=middle_body,
        )
        assert status == 202
        terminal = _wait_turn(server, session, middle["turn_id"])
        assert terminal.get("outcome") == "no_change" or terminal["status"] == "failed"
        assert next(iter(app.turns._proposal_heads.values())).turn_id == first_turn_id  # noqa: SLF001

        final_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "raffinamento valido successivo",
            "basis": basis,
        }
        status, final, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=final_body,
        )
        assert status == 202
        assert _wait_turn(server, session, final["turn_id"])["outcome"] == "proposed"
        assert next(iter(app.turns._proposal_heads.values())).turn_id == final["turn_id"]  # noqa: SLF001


@pytest.mark.parametrize("lifecycle", ["close", "ttl"])
def test_session_cleanup_erases_published_latest_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: str,
) -> None:
    def propose(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        return _scripted_proposal(kwargs["record"], kwargs["request"], 1)

    monkeypatch.setattr("metis_model1.brain_orchestrator.BrainOrchestrator.run", propose)
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _named_create_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        assert _wait_turn(server, session, accepted["turn_id"])["outcome"] == "proposed"
        assert len(app.turns._proposal_heads) == 1  # noqa: SLF001

        if lifecycle == "close":
            status, _closed, _ = _request(
                server,
                "DELETE",
                f"/v1/sessions/{session['id']}",
                token=session["token"],
            )
            assert status == 200
        else:
            now = app.manager._monotonic()  # noqa: SLF001
            app.manager._monotonic = lambda: now + 1_201  # type: ignore[method-assign]  # noqa: SLF001
            assert app.manager.sweep_expired() == 1
        assert app.turns._proposal_heads == {}  # noqa: SLF001


def test_heartbeat_is_bounded_replayable_and_contains_no_work_payload() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": context,
            "expected_semantic_source_revision": semantic,
            "intent": "edit",
            "instruction": "marker-segreto-della-sessione",
            "target": {
                "mode": "existing",
                "relative_path": "candidate.metis",
                "endpoint": "demo.candidate",
                "base_sha256": "sha256:" + "c" * 64,
            },
            "basis": None,
            "clarification_response": None,
        }
    )
    record = TurnRecord(
        turn_id="turn_" + "a" * 32,
        session_id="session_" + "a" * 32,
        request=request,
        payload_hash=request.payload_hash,
    )

    with record.heartbeat_while(
        phase="inference_running",
        label="Model 1 sta preparando il draft",
        interval_seconds=0.01,
    ):
        time.sleep(0.035)

    heartbeats = [item for item in record.events if item["event"] == "heartbeat"]
    assert len(heartbeats) >= 2
    assert [item["data"]["sequence"] for item in heartbeats] == list(range(1, len(heartbeats) + 1))
    assert all(item["data"]["phase"] == "inference_running" for item in heartbeats)
    assert all(0 <= item["data"]["elapsed_ms"] <= 1_000_000 for item in heartbeats)
    assert "marker-segreto-della-sessione" not in json.dumps(heartbeats)


def test_terminal_is_last_when_heartbeat_and_finish_race() -> None:
    request = TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": "sha256:" + "a" * 64,
            "expected_semantic_source_revision": "sha256:" + "b" * 64,
            "intent": "edit",
            "instruction": "modifica l'endpoint",
            "target": {
                "mode": "existing",
                "relative_path": "candidate.metis",
                "endpoint": "demo.candidate",
                "base_sha256": "sha256:" + "c" * 64,
            },
            "basis": None,
            "clarification_response": None,
        }
    )
    record = TurnRecord(
        turn_id="turn_" + "c" * 32,
        session_id="session_" + "c" * 32,
        request=request,
        payload_hash=request.payload_hash,
    )
    store = object.__new__(TurnStore)
    store._lock = threading.Lock()  # noqa: SLF001
    store._closed = False  # noqa: SLF001
    store._turns = {record.turn_id: record}  # noqa: SLF001
    store._proposal_heads = {}  # noqa: SLF001
    store._active = {record.session_id}  # noqa: SLF001
    heartbeat_entered = threading.Event()
    release_heartbeat = threading.Event()
    original_emit = record.emit

    def barrier_emit(event: str, phase: str, label: str, **metrics: int | str | bool) -> None:
        if event == "heartbeat":
            heartbeat_entered.set()
            assert release_heartbeat.wait(timeout=2)
        original_emit(event, phase, label, **metrics)

    record.emit = barrier_emit  # type: ignore[method-assign]
    payload = {
        "schema_version": 2,
        "turn_id": record.turn_id,
        "request_id": request.request_id,
        "status": "completed",
        "outcome": "proposed",
        "route": "local",
    }
    with record.heartbeat_while(
        phase="inference_running",
        label="Model 1 sta preparando il draft",
        interval_seconds=0.01,
    ):
        assert heartbeat_entered.wait(timeout=2)
        finisher = threading.Thread(target=store._finish, args=(record, payload))  # noqa: SLF001
        finisher.start()
        time.sleep(0.02)
        release_heartbeat.set()
        finisher.join(timeout=2)
        assert not finisher.is_alive()

    assert record.events[-1]["event"] == "terminal"
    assert [item["event"] for item in record.events].count("terminal") == 1


def test_event_sequence_remains_monotonic_after_bounded_replay_eviction() -> None:
    request = TurnRequest.parse(
        {
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": "sha256:" + "a" * 64,
            "expected_semantic_source_revision": "sha256:" + "b" * 64,
            "intent": "create",
            "instruction": "crea un endpoint",
            "target": {
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": "demo.candidate",
                "base_sha256": None,
            },
            "basis": None,
            "clarification_response": None,
        }
    )
    record = TurnRecord(
        turn_id="turn_" + "b" * 32,
        session_id="session_" + "b" * 32,
        request=request,
        payload_hash=request.payload_hash,
    )

    for index in range(300):
        record.emit("heartbeat", "test_running", "Test in corso", elapsed_ms=index)

    sequences = [item["data"]["sequence"] for item in record.events]
    assert len(sequences) == 256
    assert sequences == list(range(45, 301))


@pytest.mark.parametrize(
    "answer",
    [
        {},
        {"option_ref": "option-a", "integer": 3},
        {"option_ref": "option-a", "text": "video"},
        {"integer": 0},
        {"integer": 2.5},
        {"option_ref": "contains spaces"},
        {"text": "bad\nvalue"},
        {"text": " "},
    ],
)
def test_turn_request_v2_rejects_invalid_typed_answers(answer: dict[str, Any]) -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    with pytest.raises(BrainError) as raised:
        TurnRequest.parse(
            {
                "schema_version": 2,
                "request_id": str(uuid.uuid4()),
                "expected_context_revision": context,
                "expected_semantic_source_revision": semantic,
                "intent": "create",
                "instruction": "crea un endpoint video",
                "target": {
                    "mode": "create",
                    "relative_path": "candidate.metis",
                    "endpoint": None,
                    "base_sha256": None,
                },
                "basis": None,
                "clarification_response": {
                    "clarification_id": "clarification-123456789012345678901234",
                    "answer": answer,
                    "context_revision": context,
                    "semantic_source_revision": semantic,
                },
            }
        )
    assert raised.value.code == "INVALID_SCHEMA"


def test_existing_target_workspace_base_is_bound_to_the_session_snapshot(
    tmp_path: Path,
) -> None:
    tenant = _tenant(tmp_path / "tenant")
    snapshot = TenantRegistry([("demo", "tenant-one", tenant)]).capture(
        "demo",
        toolchain_binding=FakeCompiler.toolchain_binding,
    )
    current = snapshot.source_map()["main.metis"]
    payload = {
        "schema_version": 2,
        "request_id": str(uuid.uuid4()),
        "expected_context_revision": snapshot.revision,
        "expected_semantic_source_revision": snapshot.semantic_source_revision(),
        "intent": "edit",
        "instruction": "modifica l'endpoint esistente",
        "target": {
            "mode": "existing",
            "relative_path": "main.metis",
            "endpoint": "demo.existing",
            "base_sha256": "sha256:" + "f" * 64,
        },
        "basis": None,
        "clarification_response": None,
    }
    request = TurnRequest.parse(payload)

    with pytest.raises(BrainError) as raised:
        TurnStore._validate_target_snapshot(SimpleNamespace(snapshot=snapshot), request)
    assert raised.value.code == "BASE_STALE"

    payload["target"]["base_sha256"] = bytes_sha256(current.encode("utf-8"))
    TurnStore._validate_target_snapshot(
        SimpleNamespace(snapshot=snapshot),
        TurnRequest.parse(payload),
    )


def test_turn_idempotency_compile_repair_and_terminal(tmp_path: Path) -> None:
    compiler = FakeCompiler(["invalid", "ok"])
    model = StaticModelRuntime("metis 0.43\ntenant candidate {}\n")
    with _service(tmp_path, model=model, compiler=compiler) as (server, runtime, _app):
        session = _open(server, runtime)
        revision = semantic_revision(
            TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
                "demo", toolchain_binding=compiler.toolchain_binding
            )
        )
        body = _turn_request(session, revision)
        status, accepted, _ = _request(
            server, "POST", f"/v1/sessions/{session['id']}/turns", token=session["token"], body=body
        )
        assert status == 202
        status, retry, _ = _request(
            server, "POST", f"/v1/sessions/{session['id']}/turns", token=session["token"], body=body
        )
        assert status == 202 and retry["turn_id"] == accepted["turn_id"]
        turn_id = accepted["turn_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, result, _ = _request(
                server,
                "GET",
                f"/v1/sessions/{session['id']}/turns/{turn_id}",
                token=session["token"],
            )
            if result.get("status") == "completed":
                break
            time.sleep(0.02)
        assert status == 200
        assert result["validation"]["attempts"] == 2
        assert result["claims"]["compile_clean"] is True
        assert result["claims"]["semantic_correctness"] is False
        assert compiler.calls == 2
        changed = dict(body, instruction="altra richiesta")
        status, error, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=changed,
        )
        assert status == 409 and error["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_session_options_apply_preflight_and_sse_are_bounded(tmp_path: Path) -> None:
    compiler = FakeCompiler()
    model = StaticModelRuntime("metis 0.43\ntenant candidate {}\n")
    with _service(tmp_path, model=model, compiler=compiler) as (server, runtime, _app):
        bootstrap = runtime.bootstrap_file.read_text().strip()
        status, options, _ = _request(
            server,
            "POST",
            "/v1/session-options",
            token=bootstrap,
            body={"client_id": "visix"},
        )
        assert status == 200
        assert options["tenant_aliases"] == ["demo"]
        assert "root" not in json.dumps(options)
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        turn_id = accepted["turn_id"]
        for _ in range(100):
            status, result, _ = _request(
                server,
                "GET",
                f"/v1/sessions/{session['id']}/turns/{turn_id}",
                token=session["token"],
            )
            if result.get("status") == "completed":
                break
            time.sleep(0.01)
        assert result["outcome"] == "proposed"
        proposal_ref = result["proposal"]["proposal_ref"]
        status, ticket, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns/{turn_id}/apply-preflight",
            token=session["token"],
            body={"schema_version": 1, "proposal_ref": proposal_ref},
        )
        assert status == 200 and ticket["apply_ticket"]
        status, retry, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns/{turn_id}/apply-preflight",
            token=session["token"],
            body={"schema_version": 1, "proposal_ref": proposal_ref},
        )
        assert status == 200 and retry["apply_ticket"] == ticket["apply_ticket"]
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request(
            "GET",
            f"/v1/sessions/{session['id']}/turns/{turn_id}/events",
            headers={"Authorization": f"Bearer {session['token']}"},
        )
        response = connection.getresponse()
        raw = response.read().decode()
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/event-stream"
        assert "terminal" in raw
        assert "metis 0.43" not in raw
        connection.close()

        last_event_id = max(
            int(line.removeprefix("id: ")) for line in raw.splitlines() if line.startswith("id: ")
        )
        reconnect = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        started = time.monotonic()
        reconnect.request(
            "GET",
            f"/v1/sessions/{session['id']}/turns/{turn_id}/events",
            headers={
                "Authorization": f"Bearer {session['token']}",
                "Last-Event-ID": str(last_event_id),
            },
        )
        replay = reconnect.getresponse()
        assert replay.status == 200
        assert replay.read() == b""
        assert time.monotonic() - started < 0.5
        reconnect.close()

        hostile = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        hostile.request(
            "GET",
            f"/v1/sessions/{session['id']}/turns/{turn_id}/events",
            headers={
                "Authorization": f"Bearer {session['token']}",
                "Last-Event-ID": "9" * 5_000,
            },
        )
        rejected = hostile.getresponse()
        assert rejected.status == 400
        assert json.loads(rejected.read())["error"]["code"] == "INVALID_SCHEMA"
        hostile.close()


def test_session_close_erases_volatile_turn_and_conversation_memory(tmp_path: Path) -> None:
    compiler = FakeCompiler()
    model = StaticModelRuntime("metis 0.43\ntenant candidate {}\n")
    with _service(tmp_path, model=model, compiler=compiler) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        for _ in range(100):
            _status, result, _ = _request(
                server,
                "GET",
                f"/v1/sessions/{session['id']}/turns/{accepted['turn_id']}",
                token=session["token"],
            )
            if result.get("status") == "completed":
                break
            time.sleep(0.01)
        assert app.turns.aggregate_metrics() == {
            "turns": 1,
            "conversations": 1,
            "pending": 0,
            "clarification_decisions": 0,
            "clarification_assumptions": 0,
        }

        status, _closed, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )

        assert status == 200
        assert app.turns.aggregate_metrics() == {
            "turns": 0,
            "conversations": 0,
            "pending": 0,
            "clarification_decisions": 0,
            "clarification_assumptions": 0,
        }


def test_close_during_retrieval_cannot_resurrect_pending_memory(tmp_path: Path) -> None:
    compiler = FakeCompiler()
    retriever = BlockingCatalogRetriever()
    model = StaticModelRuntime("metis 0.43\ntenant candidate {}\n")
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        body["schema_version"] = 2
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202 and accepted["turn_id"]
        assert retriever.entered.wait(timeout=5)

        status, closed, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )
        assert status == 200 and closed["session"]["state"] == "closing"
        assert app.turns.aggregate_metrics() == {
            "turns": 0,
            "conversations": 0,
            "pending": 0,
            "clarification_decisions": 0,
            "clarification_assumptions": 0,
        }

        retriever.release.set()
        app.turns._executor.submit(lambda: None).result(timeout=5)  # noqa: SLF001
        assert app.turns.aggregate_metrics() == {
            "turns": 0,
            "conversations": 0,
            "pending": 0,
            "clarification_decisions": 0,
            "clarification_assumptions": 0,
        }
        assert compiler.calls == 0


@pytest.mark.parametrize("lifecycle", ["close", "ttl", "cancel"])
def test_revoked_turn_cannot_republish_staged_private_attachments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle: str,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    staged_records: list[Any] = []
    manifest = {
        "schema_version": 1,
        "endpoint": "demo.private",
        "endpoint_sha256": "sha256:" + "1" * 64,
        "containers": [],
        "fetches": [],
    }
    manifest_sha256 = canonical_sha256(manifest)
    source = "metis 0.43\nendpoint demo.private { take 1 from @video }\n"
    source_sha256 = bytes_sha256(source.encode("utf-8"))
    basis_create = _typed_create_state(
        generation=0,
        parent_ir=None,
        marker="private-lifecycle-basis",
    )
    candidate_create = _typed_create_state(
        generation=1,
        parent_ir=basis_create["ir"],
        marker="private-lifecycle-candidate",
    )

    def stage_after_revocation(_orchestrator: Any, **kwargs: Any) -> dict[str, Any]:
        staged = kwargs["record"]
        request = kwargs["request"]
        staged_records.append(staged)
        entered.set()
        assert release.wait(timeout=5)
        staged.basis_manifest = dict(manifest)
        staged.basis_manifest_sha256 = manifest_sha256
        staged.candidate_source = source
        staged.candidate_source_sha256 = source_sha256
        staged.candidate_manifest = dict(manifest)
        staged.candidate_manifest_sha256 = manifest_sha256
        _attach_typed_create_state(staged, prefix="basis", state=basis_create)
        _attach_typed_create_state(staged, prefix="candidate", state=candidate_create)
        return {
            "schema_version": request.schema_version,
            "turn_id": staged.turn_id,
            "request_id": request.request_id,
            "status": "completed",
            "route": "local",
            "outcome": "proposed",
            "proposal": {
                "proposal_ref": "proposal-private",
                "source": source,
                "source_sha256": source_sha256,
            },
        }

    monkeypatch.setattr(
        "metis_model1.brain_orchestrator.BrainOrchestrator.run",
        stage_after_revocation,
    )
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        assert entered.wait(timeout=5)
        held = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        held.basis_manifest = dict(manifest)
        held.basis_manifest_sha256 = manifest_sha256
        held.candidate_proposal_ref = "proposal-private"
        held.candidate_source = source
        held.candidate_source_sha256 = source_sha256
        held.candidate_manifest = dict(manifest)
        held.candidate_manifest_sha256 = manifest_sha256
        _attach_typed_create_state(held, prefix="basis", state=basis_create)
        _attach_typed_create_state(held, prefix="candidate", state=candidate_create)

        try:
            if lifecycle == "close":
                status, closed, _ = _request(
                    server,
                    "DELETE",
                    f"/v1/sessions/{session['id']}",
                    token=session["token"],
                )
                assert status == 200 and closed["session"]["state"] == "closed"
            elif lifecycle == "ttl":
                now = app.manager._monotonic()  # noqa: SLF001
                app.manager._monotonic = lambda: now + 1_201  # type: ignore[method-assign]  # noqa: SLF001
                assert app.manager.sweep_expired() == 1
            else:
                status, _cancelling, _ = _request(
                    server,
                    "DELETE",
                    f"/v1/sessions/{session['id']}/turns/{accepted['turn_id']}",
                    token=session["token"],
                )
                assert status == 200

            assert held.basis_manifest is None
            assert held.basis_manifest_sha256 is None
            assert held.candidate_proposal_ref is None
            assert held.candidate_source is None
            assert held.candidate_source_sha256 is None
            assert held.candidate_manifest is None
            assert held.candidate_manifest_sha256 is None
            assert held.basis_create_spec is None
            assert held.basis_create_ir is None
            assert held.basis_create_proof is None
            assert held.basis_create_generation is None
            assert held.candidate_create_spec is None
            assert held.candidate_create_ir is None
            assert held.candidate_create_proof is None
            assert held.candidate_create_generation is None
            _assert_no_typed_create_state(held)
        finally:
            release.set()

        app.turns._executor.submit(lambda: None).result(timeout=5)  # noqa: SLF001
        assert held.basis_manifest is None
        assert held.basis_manifest_sha256 is None
        assert held.candidate_proposal_ref is None
        assert held.candidate_source is None
        assert held.candidate_source_sha256 is None
        assert held.candidate_manifest is None
        assert held.candidate_manifest_sha256 is None
        assert held.basis_create_spec is None
        assert held.basis_create_ir is None
        assert held.basis_create_proof is None
        assert held.basis_create_generation is None
        assert held.candidate_create_spec is None
        assert held.candidate_create_ir is None
        assert held.candidate_create_proof is None
        assert held.candidate_create_generation is None
        _assert_no_typed_create_state(held)
        assert staged_records
        assert staged_records[0].basis_manifest is None
        assert staged_records[0].basis_manifest_sha256 is None
        assert staged_records[0].candidate_proposal_ref is None
        assert staged_records[0].candidate_source is None
        assert staged_records[0].candidate_source_sha256 is None
        assert staged_records[0].candidate_manifest is None
        assert staged_records[0].candidate_manifest_sha256 is None
        assert staged_records[0].basis_create_spec is None
        assert staged_records[0].basis_create_ir is None
        assert staged_records[0].basis_create_proof is None
        assert staged_records[0].basis_create_generation is None
        assert staged_records[0].candidate_create_spec is None
        assert staged_records[0].candidate_create_ir is None
        assert staged_records[0].candidate_create_proof is None
        assert staged_records[0].candidate_create_generation is None
        _assert_no_typed_create_state(staged_records[0])
        if lifecycle == "cancel":
            assert app.turns._turns.get(held.turn_id) is held  # noqa: SLF001
            assert held.public_status()["status"] == "cancelled"
        else:
            assert held.turn_id not in app.turns._turns  # noqa: SLF001
        assert app.turns._proposal_heads == {}  # noqa: SLF001


def test_close_before_turn_insertion_revokes_submit_without_resurrecting_record(
    tmp_path: Path,
) -> None:
    class CountingRetriever(FakeRetriever):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
            self.calls += 1
            return super().retrieve(lease=lease, request=request)

    compiler = FakeCompiler()
    retriever = CountingRetriever()
    model = CountingStaticModel()
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        admitted = threading.Event()
        resume = threading.Event()
        original_validate = app.turns._validate_target_snapshot  # noqa: SLF001

        def pause_before_insertion(lease: Any, request: TurnRequest) -> None:
            original_validate(lease, request)
            admitted.set()
            assert resume.wait(timeout=5)

        app.turns._validate_target_snapshot = pause_before_insertion  # type: ignore[method-assign]  # noqa: SLF001
        submitted: list[tuple[int, dict[str, Any], dict[str, str]]] = []

        def submit_turn() -> None:
            submitted.append(
                _request(
                    server,
                    "POST",
                    f"/v1/sessions/{session['id']}/turns",
                    token=session["token"],
                    body=body,
                )
            )

        thread = threading.Thread(target=submit_turn)
        thread.start()
        assert admitted.wait(timeout=5)

        status, closed, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )
        assert status == 200 and closed["session"]["state"] == "closing"
        assert app.turns.aggregate_metrics()["turns"] == 0

        resume.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert len(submitted) == 1
        submit_status, rejected, _headers = submitted[0]
        assert submit_status == 409
        assert rejected["error"]["code"] == "SESSION_REVOKED"
        assert app.turns.aggregate_metrics() == {
            "turns": 0,
            "conversations": 0,
            "pending": 0,
            "clarification_decisions": 0,
            "clarification_assumptions": 0,
        }
        assert app.turns._futures == {}  # noqa: SLF001
        assert app.turns._admitted_work == {}  # noqa: SLF001
        assert app.manager.aggregate_metrics() == {"sessions": 0, "active": 0, "in_flight": 0}
        assert retriever.calls == 0 and model.calls == 0 and compiler.calls == 0


def test_close_cancels_another_sessions_queued_turn_before_work_starts(
    tmp_path: Path,
) -> None:
    compiler = FakeCompiler()
    retriever = BlockingSingleCatalogRetriever()
    model = CountingStaticModel()
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        first_session = _open(server, runtime)
        queued_session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        semantic = snapshot.semantic_source_revision()

        status, first, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{first_session['id']}/turns",
            token=first_session["token"],
            body=_turn_request(first_session, semantic),
        )
        assert status == 202
        assert retriever.entered.wait(timeout=5)

        status, queued, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{queued_session['id']}/turns",
            token=queued_session["token"],
            body=_turn_request(queued_session, semantic),
        )
        assert status == 202
        queued_future = app.turns._futures[queued["turn_id"]]  # noqa: SLF001
        assert not queued_future.running() and not queued_future.done()

        status, closed, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{queued_session['id']}",
            token=queued_session["token"],
        )
        assert status == 200 and closed["session"]["state"] == "closed"
        assert queued_future.cancelled()
        assert queued["turn_id"] not in app.turns._futures  # noqa: SLF001
        assert queued["turn_id"] not in app.turns._admitted_work  # noqa: SLF001

        retriever.release.set()
        app.turns._executor.submit(lambda: None).result(timeout=5)  # noqa: SLF001
        assert _wait_turn(server, first_session, first["turn_id"])["status"] == "completed"
        assert retriever.calls == 1
        assert model.calls == 1
        assert compiler.calls == 1
        assert app.turns._futures == {}  # noqa: SLF001


def test_shutdown_cancels_queued_turn_before_work_starts(tmp_path: Path) -> None:
    compiler = FakeCompiler()
    retriever = BlockingSingleCatalogRetriever()
    model = CountingStaticModel()
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        first_session = _open(server, runtime)
        queued_session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        semantic = snapshot.semantic_source_revision()

        status, _first, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{first_session['id']}/turns",
            token=first_session["token"],
            body=_turn_request(first_session, semantic),
        )
        assert status == 202
        assert retriever.entered.wait(timeout=5)
        status, queued, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{queued_session['id']}/turns",
            token=queued_session["token"],
            body=_turn_request(queued_session, semantic),
        )
        assert status == 202
        queued_future = app.turns._futures[queued["turn_id"]]  # noqa: SLF001

        stopped = threading.Event()

        def shutdown_turns() -> None:
            app.turns.shutdown()
            stopped.set()

        thread = threading.Thread(target=shutdown_turns)
        thread.start()
        for _ in range(100):
            if queued_future.cancelled():
                break
            time.sleep(0.01)
        assert queued_future.cancelled()
        assert queued["turn_id"] not in app.turns._admitted_work  # noqa: SLF001

        retriever.release.set()
        thread.join(timeout=5)
        assert stopped.is_set()
        assert retriever.calls == 1
        assert app.turns._futures == {}  # noqa: SLF001
        assert app.turns._admitted_work == {}  # noqa: SLF001


def test_cancel_during_retrieval_discards_hidden_pending_and_allows_retry(
    tmp_path: Path,
) -> None:
    compiler = FakeCompiler()
    retriever = BlockingCatalogRetriever()
    model = StaticModelRuntime("metis 0.43\ntenant candidate {}\n")
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        body["schema_version"] = 2
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        assert retriever.entered.wait(timeout=5)
        record = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        original_discard = app.turns.clarifications.discard_pending_for_turn

        def discard_before_terminal(**kwargs: Any) -> bool:
            assert record.terminal is None
            return original_discard(**kwargs)

        app.turns.clarifications.discard_pending_for_turn = discard_before_terminal  # type: ignore[method-assign]

        status, _cancelling, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}/turns/{accepted['turn_id']}",
            token=session["token"],
        )
        assert status == 200
        retriever.release.set()
        app.turns._executor.submit(lambda: None).result(timeout=5)  # noqa: SLF001
        status, cancelled, _ = _request(
            server,
            "GET",
            f"/v1/sessions/{session['id']}/turns/{accepted['turn_id']}",
            token=session["token"],
        )
        assert status == 200 and cancelled["status"] == "cancelled"
        assert app.turns.clarifications.metrics() == {
            "sessions": 0,
            "conversations": 0,
            "pending": 0,
            "retired": 0,
            "decisions": 0,
            "assumptions": 0,
        }

        retry = {**body, "request_id": str(uuid.uuid4())}
        status, retried, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=retry,
        )
        assert status == 202
        result = _wait_turn(server, session, retried["turn_id"])
        assert result["outcome"] == "needs_clarification"
        assert result["clarification"]["kind"] == "catalog"
        assert retriever.calls == 2 and compiler.calls == 0


def test_stale_before_answer_admission_erases_pending_session_memory(tmp_path: Path) -> None:
    compiler = FakeCompiler()
    retriever = FakeRetriever(
        catalogs=(
            {"catalog": "video", "label": "Video"},
            {"catalog": "users", "label": "Utenti"},
        )
    )
    model = StaticModelRuntime("metis 0.43\ntenant candidate {}\n")
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        tenant = (tmp_path / "tenant").resolve()
        snapshot = TenantRegistry([("demo", "tenant-one", tenant)]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        body["schema_version"] = 2
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["outcome"] == "needs_clarification"
        assert app.turns.aggregate_metrics()["pending"] == 1

        (tenant / "main.metis").write_text(
            "metis 0.43\ntenant changed {}\n",
            encoding="utf-8",
        )
        answer = {
            **body,
            "request_id": str(uuid.uuid4()),
            "clarification_response": {
                "clarification_id": first["clarification"]["clarification_id"],
                "answer": {"option_ref": first["clarification"]["options"][0]["option_ref"]},
                "context_revision": session["context_revision"],
                "semantic_source_revision": snapshot.semantic_source_revision(),
            },
        }
        status, stale, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=answer,
        )

        assert status == 409 and stale["error"]["code"] == "STALE_CONTEXT"
        assert app.turns.aggregate_metrics() == {
            "turns": 0,
            "conversations": 0,
            "pending": 0,
            "clarification_decisions": 0,
            "clarification_assumptions": 0,
        }
        assert app.manager.aggregate_metrics() == {"sessions": 0, "active": 0, "in_flight": 0}
        assert compiler.calls == 0


def test_ambiguous_metadata_stops_before_model_and_compiler(tmp_path: Path) -> None:
    class MustNotRunModel:
        model_loaded = True
        model_revision = "test"
        adapter_sha256 = "sha256:" + "b" * 64

        def generate(self, _request: Any) -> Any:
            raise AssertionError("ambiguous grounding reached the model")

    compiler = FakeCompiler()
    retriever = FakeRetriever(grounding_status="clarify")
    with _service(tmp_path, model=MustNotRunModel(), compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        _app,
    ):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        for _ in range(100):
            _status, result, _ = _request(
                server,
                "GET",
                f"/v1/sessions/{session['id']}/turns/{accepted['turn_id']}",
                token=session["token"],
            )
            if result.get("status") == "completed":
                break
            time.sleep(0.01)
        assert result["outcome"] == "unsupported_metadata"
        assert result["claims"]["semantic_grounded"] is False
        assert compiler.calls == 0


def test_catalog_clarification_is_server_owned_one_shot_and_session_scoped(
    tmp_path: Path,
) -> None:
    class CatalogRetriever:
        def __init__(self) -> None:
            self.calls = 0

        def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
            self.calls += 1
            semantic = semantic_revision(lease.snapshot)
            decision = request.server_clarification
            selected = (
                decision.get("resolved_value")
                if isinstance(decision, dict) and decision.get("kind") == "catalog"
                else None
            )
            catalogs = (
                ({"catalog": selected, "label": selected.title()},)
                if selected
                else (
                    {
                        "catalog": "video",
                        "label": "Video",
                        "description": "Contenuti video",
                    },
                    {
                        "catalog": "users",
                        "label": "Utenti",
                        "description": "Profili utente",
                    },
                )
            )
            return RetrievalResult(
                context={"tenant": lease.tenant_alias},
                grounding={
                    "status": "resolved" if selected else "clarify",
                    "catalogs": [selected] if selected else [],
                    "selections": [],
                    "candidates": [],
                    "unresolved": [],
                },
                semantic_source_revision=semantic,
                catalog_candidates=catalogs,
            )

    class CountingModel(StaticModelRuntime):
        def __init__(self) -> None:
            super().__init__("metis 0.43\ntenant candidate {}\n")
            self.calls = 0

        def generate(self, request: Any):
            self.calls += 1
            return super().generate(request)

    compiler = FakeCompiler()
    retriever = CatalogRetriever()
    model = CountingModel()
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        other = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        body["schema_version"] = 2
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["outcome"] == "needs_clarification"
        assert first["clarification"]["kind"] == "catalog"
        assert model.calls == 0 and compiler.calls == 0
        assert app.turns.aggregate_metrics()["pending"] == 1
        option = next(
            item for item in first["clarification"]["options"] if item["label"] == "Video"
        )
        unrelated = {**body, "request_id": str(uuid.uuid4()), "instruction": "nuova richiesta"}
        status, blocked, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=unrelated,
        )
        assert status == 409 and blocked["error"]["code"] == "CLARIFICATION_PENDING"
        answer = {
            **body,
            "request_id": str(uuid.uuid4()),
            "clarification_response": {
                "clarification_id": first["clarification"]["clarification_id"],
                "answer": {"option_ref": option["option_ref"]},
                "context_revision": session["context_revision"],
                "semantic_source_revision": snapshot.semantic_source_revision(),
            },
        }

        status, cross, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{other['id']}/turns",
            token=other["token"],
            body=answer,
        )
        assert status == 403 and cross["error"]["code"] == "CLARIFICATION_CROSS_SESSION"
        assert model.calls == 0 and compiler.calls == 0

        original_submit = app.turns._executor.submit  # noqa: SLF001

        def reject_submit(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("executor unavailable")

        app.turns._executor.submit = reject_submit  # type: ignore[method-assign]  # noqa: SLF001
        try:
            status, unavailable, _ = _request(
                server,
                "POST",
                f"/v1/sessions/{session['id']}/turns",
                token=session["token"],
                body=answer,
            )
        finally:
            app.turns._executor.submit = original_submit  # type: ignore[method-assign]  # noqa: SLF001
        assert status == 503 and unavailable["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert app.turns.aggregate_metrics()["pending"] == 1

        original_answer = app.turns.clarifications.answer

        def fail_answer_once(**_kwargs: Any) -> Any:
            raise RuntimeError("worker answer failure")

        app.turns.clarifications.answer = fail_answer_once  # type: ignore[method-assign]
        try:
            status, failed_answer, _ = _request(
                server,
                "POST",
                f"/v1/sessions/{session['id']}/turns",
                token=session["token"],
                body=answer,
            )
            assert status == 202
            failed = _wait_turn(server, session, failed_answer["turn_id"])
        finally:
            app.turns.clarifications.answer = original_answer  # type: ignore[method-assign]
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "INTERNAL_ERROR"
        assert app.turns.aggregate_metrics()["pending"] == 1

        retry_answer = {**answer, "request_id": str(uuid.uuid4())}
        status, resumed, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=retry_answer,
        )
        assert status == 202
        proposed = _wait_turn(server, session, resumed["turn_id"])
        assert proposed["outcome"] == "proposed"
        assert proposed["session_memory"]["persistent"] is False
        assert proposed["session_memory"]["decisions"][0]["kind"] == "catalog"
        assert model.calls == 1 and compiler.calls == 1

        replay = {**answer, "request_id": str(uuid.uuid4())}
        status, rejected, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=replay,
        )
        assert status == 409 and rejected["error"]["code"] == "CLARIFICATION_REPLAY"
        assert retriever.calls == 2 and model.calls == 1 and compiler.calls == 1

        status, _closed, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )
        assert status == 200
        assert app.turns.aggregate_metrics() == {
            "turns": 0,
            "conversations": 0,
            "pending": 0,
            "clarification_decisions": 0,
            "clarification_assumptions": 0,
        }


def test_worker_error_after_question_creation_discards_hidden_pending(tmp_path: Path) -> None:
    catalogs = (
        {"catalog": "video", "label": "Video"},
        {"catalog": "users", "label": "Utenti"},
    )
    compiler = FakeCompiler()
    with _service(
        tmp_path,
        model=StaticModelRuntime("metis 0.43\ntenant candidate {}\n"),
        compiler=compiler,
        retriever=FakeRetriever(catalogs=catalogs),
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        body["schema_version"] = 2
        original_conversation = app.turns.clarifications.conversation

        def fail_after_pending(**_kwargs: Any) -> Any:
            raise RuntimeError("terminal construction failed")

        app.turns.clarifications.conversation = (  # type: ignore[method-assign]
            fail_after_pending
        )
        try:
            status, accepted, _ = _request(
                server,
                "POST",
                f"/v1/sessions/{session['id']}/turns",
                token=session["token"],
                body=body,
            )
            assert status == 202
            failed = _wait_turn(server, session, accepted["turn_id"])
        finally:
            app.turns.clarifications.conversation = (  # type: ignore[method-assign]
                original_conversation
            )
        assert failed["status"] == "failed"
        assert app.turns.aggregate_metrics()["pending"] == 0

        retry = {**body, "request_id": str(uuid.uuid4())}
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=retry,
        )
        assert status == 202
        terminal = _wait_turn(server, session, accepted["turn_id"])
        assert terminal["outcome"] == "needs_clarification"
        assert terminal["clarification"]["kind"] == "catalog"
        assert app.turns.aggregate_metrics()["pending"] == 1


def test_ambiguous_result_count_resumes_with_exact_total_take(tmp_path: Path) -> None:
    class SemanticRetriever:
        def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
            return RetrievalResult(
                context={"tenant": lease.tenant_alias, "semantic_schema": 2},
                grounding={
                    "status": "resolved",
                    "catalogs": ["video"],
                    "selections": [],
                    "candidates": [],
                    "unresolved": [],
                },
                semantic_source_revision=semantic_revision(lease.snapshot),
                catalog_candidates=({"catalog": "video", "label": "Video"},),
            )

    source = """metis 0.43
endpoint demo.candidate as "Candidate" {
  take 24 from @video as items "Items"
  return response.expanded
}
"""

    class CountingModel(StaticModelRuntime):
        def __init__(self) -> None:
            super().__init__(source)
            self.calls = 0

        def generate(self, request: Any):
            self.calls += 1
            return super().generate(request)

    compiler = FakeCompiler()
    model = CountingModel()
    with _service(
        tmp_path,
        model=model,
        compiler=compiler,
        retriever=SemanticRetriever(),
    ) as (server, runtime, _app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        body.update(
            schema_version=2,
            instruction="crea un endpoint con alcuni risultati video",
        )
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["clarification"]["kind"] == "result_count"
        assert first["clarification"]["answer_schema"] == {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
        }
        assert model.calls == 0 and compiler.calls == 0

        answer = {
            **body,
            "request_id": str(uuid.uuid4()),
            "clarification_response": {
                "clarification_id": first["clarification"]["clarification_id"],
                "answer": {"integer": 24},
                "context_revision": session["context_revision"],
                "semantic_source_revision": snapshot.semantic_source_revision(),
            },
        }
        status, resumed, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=answer,
        )
        assert status == 202
        proposed = _wait_turn(server, session, resumed["turn_id"])
        assert proposed["outcome"] == "proposed"
        assert proposed["grounding"]["output_contract"]["take"] == {
            "mode": "count",
            "value": 24,
            "source": "operator_confirmed",
        }
        assert proposed["session_memory"]["decisions"][0]["answer"] == {"integer": 24}
        assert (
            "Il numero complessivo non è ancora stato specificato."
            not in proposed["session_memory"]["assumptions"]
        )
        assert model.calls == 1 and compiler.calls == 1


def test_three_round_dialogue_replays_catalog_semantics_and_total_count(tmp_path: Path) -> None:
    class ThreeRoundRetriever:
        def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
            semantic = semantic_revision(lease.snapshot)
            context = request.server_clarification
            decisions = context.get("decisions", []) if isinstance(context, dict) else []
            kinds = {item.get("kind") for item in decisions if isinstance(item, dict)}
            catalogs = (
                {
                    "catalog": "video",
                    "label": "Video",
                    "description": "Contenuti video",
                },
                {
                    "catalog": "users",
                    "label": "Utenti",
                    "description": "Profili utente",
                },
            )
            if "catalog" not in kinds:
                grounding = {
                    "status": "clarify",
                    "catalogs": [],
                    "selections": [],
                    "candidates": [],
                    "unresolved": [],
                }
            elif "semantic_choice" not in kinds:
                grounding = {
                    "status": "clarify",
                    "catalogs": ["video"],
                    "selections": [],
                    "candidates": [
                        {
                            "catalog": "video",
                            "field": "genre",
                            "option_ref": "semantic-genre",
                            "clause": "genere",
                            "clause_ref": "sha256:" + "c" * 64,
                            "label": "Genere editoriale",
                            "description": "Genere editoriale verificato",
                        },
                        {
                            "catalog": "video",
                            "field": "genre_alt",
                            "option_ref": "semantic-genre-alt",
                            "clause": "genere",
                            "clause_ref": "sha256:" + "c" * 64,
                            "label": "Genere alternativo",
                            "description": "Tassonomia alternativa verificata",
                        },
                    ],
                    "unresolved": [],
                }
            else:
                grounding = {
                    "status": "resolved",
                    "catalogs": ["video"],
                    "selections": [],
                    "candidates": [],
                    "unresolved": [],
                }
            return RetrievalResult(
                context={"tenant": lease.tenant_alias, "semantic_schema": 2},
                grounding=grounding,
                semantic_source_revision=semantic,
                catalog_candidates=catalogs,
            )

    source = """metis 0.43
endpoint demo.candidate as "Candidate" {
  take 24 from @video as items "Items"
  return response.expanded
}
"""

    class CountingModel(StaticModelRuntime):
        def __init__(self) -> None:
            super().__init__(source)
            self.calls = 0

        def generate(self, request: Any):
            self.calls += 1
            return super().generate(request)

    compiler = FakeCompiler()
    model = CountingModel()
    with _service(
        tmp_path,
        model=model,
        compiler=compiler,
        retriever=ThreeRoundRetriever(),
    ) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        body.update(schema_version=2, instruction="crea un endpoint per genere")

        def submit(payload: dict[str, Any]) -> dict[str, Any]:
            status, accepted, _ = _request(
                server,
                "POST",
                f"/v1/sessions/{session['id']}/turns",
                token=session["token"],
                body=payload,
            )
            assert status == 202
            return _wait_turn(server, session, accepted["turn_id"])

        first = submit(body)
        assert first["clarification"]["kind"] == "catalog"
        video = next(item for item in first["clarification"]["options"] if item["label"] == "Video")
        second = submit(
            {
                **body,
                "request_id": str(uuid.uuid4()),
                "clarification_response": {
                    "clarification_id": first["clarification"]["clarification_id"],
                    "answer": {"option_ref": video["option_ref"]},
                    "context_revision": session["context_revision"],
                    "semantic_source_revision": snapshot.semantic_source_revision(),
                },
            }
        )
        assert second["clarification"]["kind"] == "semantic_choice"
        semantic_option = second["clarification"]["options"][0]
        third = submit(
            {
                **body,
                "request_id": str(uuid.uuid4()),
                "clarification_response": {
                    "clarification_id": second["clarification"]["clarification_id"],
                    "answer": {"option_ref": semantic_option["option_ref"]},
                    "context_revision": session["context_revision"],
                    "semantic_source_revision": snapshot.semantic_source_revision(),
                },
            }
        )
        assert third["clarification"]["kind"] == "result_count"
        final = submit(
            {
                **body,
                "request_id": str(uuid.uuid4()),
                "clarification_response": {
                    "clarification_id": third["clarification"]["clarification_id"],
                    "answer": {"integer": 24},
                    "context_revision": session["context_revision"],
                    "semantic_source_revision": snapshot.semantic_source_revision(),
                },
            }
        )
        assert final["outcome"] == "proposed"
        assert [item["kind"] for item in final["session_memory"]["decisions"]] == [
            "catalog",
            "semantic_choice",
            "result_count",
        ]
        assert final["grounding"]["output_contract"]["take"] == {
            "mode": "count",
            "value": 24,
            "source": "operator_confirmed",
        }
        assert app.turns.aggregate_metrics()["conversations"] == 1
        assert app.turns.aggregate_metrics()["pending"] == 0
        assert model.calls == 1 and compiler.calls == 1


def test_refinement_uses_server_side_proposal_source_and_grounding_memory(tmp_path: Path) -> None:
    class RecordingRetriever(FakeRetriever):
        def __init__(self) -> None:
            super().__init__()
            self.requests: list[Any] = []

        def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
            self.requests.append(request)
            result = super().retrieve(lease=lease, request=request)
            result.context["semantic_schema"] = 2
            return result

    class SequenceModel:
        model_loaded = True
        model_revision = "model-test"
        adapter_sha256 = "sha256:" + "b" * 64

        def __init__(self) -> None:
            self.sources = [
                "metis 0.43\nendpoint demo.candidate { take 24 from @video }\n",
                (
                    "metis 0.43\n// Presentazione più chiara\n"
                    "endpoint demo.candidate { take 24 from @video }\n"
                ),
            ]
            self.requests: list[Any] = []

        def generate(self, request: Any) -> ModelCandidate:
            self.requests.append(request)
            source = self.sources[min(len(self.requests) - 1, len(self.sources) - 1)]
            return ModelCandidate(source, self.model_revision, self.adapter_sha256)

    compiler = FakeCompiler()
    retriever = RecordingRetriever()
    model = SequenceModel()
    with _service(tmp_path, model=model, compiler=compiler, retriever=retriever) as (
        server,
        runtime,
        app,
    ):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _turn_request(session, snapshot.semantic_source_revision())
        first_body.update(
            schema_version=2,
            instruction="crea un endpoint con alcuni risultati video",
            target={**first_body["target"], "endpoint": "demo.candidate"},
        )
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        clarification = _wait_turn(server, session, accepted["turn_id"])
        assert clarification["clarification"]["kind"] == "result_count"
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body={
                **first_body,
                "request_id": str(uuid.uuid4()),
                "clarification_response": {
                    "clarification_id": clarification["clarification"]["clarification_id"],
                    "answer": {"integer": 24},
                    "context_revision": session["context_revision"],
                    "semantic_source_revision": snapshot.semantic_source_revision(),
                },
            },
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["outcome"] == "proposed"
        first_record = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        assert first_record.candidate_source == first["proposal"]["source"]
        assert first_record.candidate_source_sha256 == first["proposal"]["source_sha256"]
        assert first["session_memory"]["rounds_used"] == 1
        assert first["session_memory"]["decisions"][0]["answer"] == {"integer": 24}

        changed_target = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "rendi il titolo più chiaro",
            "target": {
                **first_body["target"],
                "relative_path": "other-candidate.metis",
            },
            "basis": {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]},
        }
        status, rejected, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=changed_target,
        )
        assert status == 409 and rejected["error"]["code"] == "PROPOSAL_STALE"

        refined_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "rendi il titolo più chiaro",
            "basis": {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]},
        }
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=refined_body,
        )
        assert status == 202
        refined = _wait_turn(server, session, accepted["turn_id"])
        assert refined.get("outcome") == "proposed", refined
        assert model.requests[1].previous_source == first["proposal"]["source"]
        refined_record = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        assert refined_record.basis_source == first_record.candidate_source
        assert refined_record.basis_source_sha256 == first_record.candidate_source_sha256
        assert retriever.requests[2].server_basis_grounding == first["grounding"]
        assert refined["session_memory"]["rounds_used"] == 1
        assert refined["session_memory"]["decisions"] == first["session_memory"]["decisions"]
        assert app.turns.aggregate_metrics()["conversations"] == 1


def test_named_basis_reuses_private_manifest_and_stale_authority_fails_closed(
    tmp_path: Path,
) -> None:
    source = "metis 0.43\nendpoint demo.named { take 24 from @video }\n"

    class SequenceModel:
        model_loaded = True
        model_revision = "model-test"
        adapter_sha256 = "sha256:" + "b" * 64

        def __init__(self) -> None:
            self.requests: list[Any] = []

        def generate(self, request: Any) -> ModelCandidate:
            self.requests.append(request)
            return ModelCandidate(source, self.model_revision, self.adapter_sha256)

    compiler = FakeCompiler()
    model = SequenceModel()
    with _service(tmp_path, model=model, compiler=compiler) as (server, runtime, app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        first_body = _turn_request(session, snapshot.semantic_source_revision())
        first_body.update(
            schema_version=2,
            instruction="crea l'endpoint nominato",
            target={
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": "demo.named",
                "base_sha256": None,
            },
        )
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=first_body,
        )
        assert status == 202
        first = _wait_turn(server, session, accepted["turn_id"])
        assert first["outcome"] == "proposed"
        first_record = app.turns._turns[accepted["turn_id"]]  # noqa: SLF001
        assert first_record.candidate_manifest is not None
        assert compiler.calls == 1
        assert "manifest" not in json.dumps(first).lower()

        refined_body = {
            **first_body,
            "request_id": str(uuid.uuid4()),
            "instruction": "mantieni invariata la struttura",
            "basis": {"kind": "proposal", "proposal_ref": first["proposal"]["proposal_ref"]},
        }
        status, accepted_refined, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=refined_body,
        )
        assert status == 202
        refined = _wait_turn(server, session, accepted_refined["turn_id"])
        assert refined["outcome"] == "no_change"
        refined_record = app.turns._turns[accepted_refined["turn_id"]]  # noqa: SLF001
        assert refined_record.basis_manifest == first_record.candidate_manifest
        assert refined_record.basis_manifest is not first_record.candidate_manifest
        assert compiler.calls == 2
        assert compiler.candidate_sources == [source, source]
        assert model.requests[1].previous_source == source
        assert "manifest" not in json.dumps(refined).lower()
        assert "manifest" not in json.dumps(refined_record.events).lower()

        first_record.candidate_manifest_sha256 = "sha256:" + "0" * 64
        stale_body = {**refined_body, "request_id": str(uuid.uuid4())}
        status, stale, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=stale_body,
        )
        assert status == 409 and stale["error"]["code"] == "PROPOSAL_STALE"

        status, _closed, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )
        assert status == 200
        assert app.turns._proposal_heads == {}  # noqa: SLF001
        for record in (first_record, refined_record):
            assert record.basis_source is None
            assert record.basis_source_sha256 is None
            assert record.basis_manifest is None
            assert record.basis_manifest_sha256 is None
            assert record.head_target_identity is None
            assert record.expected_head_turn_id is None
            assert record.candidate_proposal_ref is None
            assert record.candidate_source is None
            assert record.candidate_source_sha256 is None
            assert record.candidate_manifest is None
            assert record.candidate_manifest_sha256 is None


def test_shutdown_erases_private_manifest_authority(tmp_path: Path) -> None:
    compiler = FakeCompiler()
    model = StaticModelRuntime("metis 0.43\ntenant candidate {}\n")
    held: TurnRecord | None = None
    with _service(tmp_path, model=model, compiler=compiler) as (_server, _runtime, app):
        request = TurnRequest(
            2,
            str(uuid.uuid4()),
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            "create",
            "crea un endpoint",
            {
                "mode": "create",
                "relative_path": "candidate.metis",
                "endpoint": "demo.named",
                "base_sha256": None,
                "reference": None,
            },
            None,
            None,
        )
        manifest = {
            "schema_version": 1,
            "endpoint": "demo.named",
            "endpoint_sha256": "sha256:" + "1" * 64,
            "containers": [],
            "fetches": [],
        }
        basis_create = _typed_create_state(
            generation=0,
            parent_ir=None,
            marker="private-shutdown-basis",
        )
        candidate_create = _typed_create_state(
            generation=1,
            parent_ir=basis_create["ir"],
            marker="private-shutdown-candidate",
        )
        held = TurnRecord(
            turn_id="turn_" + "z" * 32,
            session_id="session_" + "z" * 32,
            request=request,
            payload_hash=request.payload_hash,
            basis_source="private source",
            basis_source_sha256=bytes_sha256(b"private source"),
            basis_grounding={"private": "grounding"},
            basis_manifest=manifest,
            basis_manifest_sha256=canonical_sha256(manifest),
            basis_create_spec=basis_create["spec"],
            basis_create_spec_sha256=basis_create["spec_sha256"],
            basis_create_ir=basis_create["ir"],
            basis_create_ir_sha256=basis_create["ir_sha256"],
            basis_create_proof=basis_create["proof"],
            basis_create_generation=basis_create["generation"],
            basis_create_history=basis_create["history"],
            basis_create_history_revision=basis_create["history_revision"],
            head_target_identity=app.turns._target_identity(request.target),  # noqa: SLF001
            expected_head_turn_id="turn_" + "y" * 32,
            candidate_proposal_ref="proposal-private",
            candidate_source="private candidate",
            candidate_source_sha256=bytes_sha256(b"private candidate"),
            candidate_manifest=manifest,
            candidate_manifest_sha256=canonical_sha256(manifest),
            candidate_create_spec=candidate_create["spec"],
            candidate_create_spec_sha256=candidate_create["spec_sha256"],
            candidate_create_ir=candidate_create["ir"],
            candidate_create_ir_sha256=candidate_create["ir_sha256"],
            candidate_create_proof=candidate_create["proof"],
            candidate_create_generation=candidate_create["generation"],
            candidate_create_history=candidate_create["history"],
            candidate_create_history_revision=candidate_create["history_revision"],
            clarification_decision={"private": "decision"},
        )
        app.turns._turns[held.turn_id] = held  # noqa: SLF001
        app.turns._proposal_heads[(held.session_id, held.head_target_identity)] = (  # noqa: SLF001
            SimpleNamespace(turn_id=held.turn_id)
        )
        assert len(app.turns._proposal_heads) == 1  # noqa: SLF001

    assert held is not None
    assert held.basis_source is None
    assert held.basis_source_sha256 is None
    assert held.basis_grounding is None
    assert held.basis_manifest is None
    assert held.basis_manifest_sha256 is None
    assert held.basis_create_spec is None
    assert held.basis_create_spec_sha256 is None
    assert held.basis_create_ir is None
    assert held.basis_create_ir_sha256 is None
    assert held.basis_create_proof is None
    assert held.basis_create_generation is None
    assert held.basis_create_history is None
    assert held.basis_create_history_revision is None
    assert held.head_target_identity is None
    assert held.expected_head_turn_id is None
    assert held.candidate_proposal_ref is None
    assert held.candidate_source is None
    assert held.candidate_source_sha256 is None
    assert held.candidate_manifest is None
    assert held.candidate_manifest_sha256 is None
    assert held.candidate_create_spec is None
    assert held.candidate_create_spec_sha256 is None
    assert held.candidate_create_ir is None
    assert held.candidate_create_ir_sha256 is None
    assert held.candidate_create_proof is None
    assert held.candidate_create_generation is None
    assert held.candidate_create_history is None
    assert held.candidate_create_history_revision is None
    _assert_no_typed_create_state(held)
    assert held.clarification_decision is None
    assert app.turns._proposal_heads == {}  # noqa: SLF001


def test_http_cancel_interrupts_generation_and_never_reaches_compiler(tmp_path: Path) -> None:
    class BlockingCancellableModel:
        model_loaded = True
        model_revision = "test"
        adapter_sha256 = "sha256:" + "b" * 64

        def __init__(self) -> None:
            self.started = threading.Event()

        def generate(self, request: Any) -> Any:
            self.started.set()
            assert request.cancellation is not None
            assert request.cancellation.wait(timeout=2)
            raise BrainError(
                "MODEL_GENERATION_CANCELLED", 409, "local Model 1 generation was cancelled"
            )

    compiler = FakeCompiler()
    model = BlockingCancellableModel()
    with _service(tmp_path, model=model, compiler=compiler) as (server, runtime, _app):
        session = _open(server, runtime)
        snapshot = TenantRegistry([("demo", "tenant-one", tmp_path / "tenant")]).capture(
            "demo", toolchain_binding=compiler.toolchain_binding
        )
        body = _turn_request(session, snapshot.semantic_source_revision())
        status, accepted, _ = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=session["token"],
            body=body,
        )
        assert status == 202
        assert model.started.wait(timeout=2)

        started = time.monotonic()
        status, cancelled, _ = _request(
            server,
            "DELETE",
            f"/v1/sessions/{session['id']}/turns/{accepted['turn_id']}",
            token=session["token"],
        )
        assert status == 200
        for _ in range(100):
            _status, cancelled, _ = _request(
                server,
                "GET",
                f"/v1/sessions/{session['id']}/turns/{accepted['turn_id']}",
                token=session["token"],
            )
            if cancelled.get("status") == "cancelled":
                break
            time.sleep(0.01)

        assert time.monotonic() - started < 1
        assert cancelled["status"] == "cancelled"
        assert cancelled["error"] == {
            "code": "TURN_CANCELLED",
            "message": "turn was cancelled",
        }
        assert compiler.calls == 0
