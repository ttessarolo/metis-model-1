from __future__ import annotations

import http.client
import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_model_runtime import ModelCandidate, StaticModelRuntime
from metis_model1.brain_protocol import CAPABILITIES, BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_server import BrainApplication, BrainRuntime, _ThreadingBrainHTTPServer
from metis_model1.brain_sessions import ClientPolicy, SessionManager
from metis_model1.brain_turns import TurnRecord, TurnRequest, TurnStore


class FakeCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def __init__(self, statuses: list[str] | None = None) -> None:
        self.statuses = statuses or ["ok"]
        self.calls = 0

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
        {"integer": 0},
        {"integer": 2.5},
        {"option_ref": "contains spaces"},
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
            self.sources = iter(
                [
                    "metis 0.43\nendpoint demo.first { take 24 from @video }\n",
                    "metis 0.43\nendpoint demo.refined { take 24 from @video }\n",
                ]
            )
            self.requests: list[Any] = []

        def generate(self, request: Any) -> ModelCandidate:
            self.requests.append(request)
            return ModelCandidate(next(self.sources), self.model_revision, self.adapter_sha256)

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
        assert refined["outcome"] == "proposed"
        assert model.requests[1].previous_source == first["proposal"]["source"]
        assert retriever.requests[2].server_basis_grounding == first["grounding"]
        assert refined["session_memory"]["rounds_used"] == 1
        assert refined["session_memory"]["decisions"] == first["session_memory"]["decisions"]
        assert app.turns.aggregate_metrics()["conversations"] == 1


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
