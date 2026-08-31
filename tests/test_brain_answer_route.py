from __future__ import annotations

import http.client
import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_model_runtime import StaticModelRuntime
from metis_model1.brain_protocol import CAPABILITIES, BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_server import BrainApplication, BrainRuntime, _ThreadingBrainHTTPServer
from metis_model1.brain_sessions import ClientPolicy, SessionManager
from metis_model1.brain_turns import ClarificationAnswerRequest


class CountingCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def __init__(self) -> None:
        self.calls = 0

    def compile(self, *, lease: Any, source: str, filename: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "schema_version": 1,
            "status": "ok",
            "diagnostics": [],
            "toolchain_binding": self.toolchain_binding,
            "receipt_sha256": canonical_sha256({"source": source, "filename": filename}),
            "session_id": lease.session_id,
            "filename": filename,
        }


class CountingModel(StaticModelRuntime):
    def __init__(self) -> None:
        super().__init__(
            """metis 0.43
endpoint candidate as "Candidate" {
  take 24 from @video
  return response.expanded
}
"""
        )
        self.calls = 0

    def generate(self, request: Any):
        self.calls += 1
        return super().generate(request)


def _tenant(root: Path) -> Path:
    root.mkdir()
    (root / "metis.toml").write_text(
        '[tenant]\nid = "tenant-one"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (root / "main.metis").write_text("metis 0.43\ntenant tenant_one {}\n", encoding="utf-8")
    return root.resolve()


class ClarifyingRetriever:
    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        del request
        revision = semantic_revision(lease.snapshot)
        return RetrievalResult(
            context={"tenant": lease.tenant_alias, "semantic_schema": 2},
            grounding={
                "catalogs": ["video"],
                "selections": [],
                "resolutions": [],
                "unresolved": [],
            },
            semantic_source_revision=revision,
            catalog_candidates=({"catalog": "video", "label": "Video"},),
        )


@contextmanager
def _service(tmp_path: Path):
    runtime = BrainRuntime((tmp_path / "runtime").resolve())
    tenant = _tenant(tmp_path / "tenant")
    compiler = CountingCompiler()
    model = CountingModel()
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
        retriever=ClarifyingRetriever(),
    )
    server = _ThreadingBrainHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runtime, compiler, model, tenant
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.close()
        manager.shutdown()
        runtime.close()


def _request(
    server: _ThreadingBrainHTTPServer,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    connection.request(
        method,
        path,
        body=json.dumps(body, separators=(",", ":")).encode() if body is not None else None,
        headers=headers,
    )
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, json.loads(raw.decode()) if raw else {}


def _open(server: _ThreadingBrainHTTPServer, runtime: BrainRuntime) -> dict[str, Any]:
    status, payload = _request(
        server,
        "POST",
        "/v1/sessions",
        token=runtime.bootstrap_file.read_text(encoding="ascii").strip(),
        body={"client_id": "visix", "tenant_alias": "demo", "capabilities": sorted(CAPABILITIES)},
    )
    assert status == 201
    return payload["session"]


def _start_pending(
    server: _ThreadingBrainHTTPServer,
    runtime: BrainRuntime,
    tenant: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    session = _open(server, runtime)
    snapshot = TenantRegistry([("demo", "tenant-one", tenant)]).capture(
        "demo", toolchain_binding=CountingCompiler.toolchain_binding
    )
    request = {
        "schema_version": 2,
        "request_id": str(uuid.uuid4()),
        "expected_context_revision": session["context_revision"],
        "expected_semantic_source_revision": snapshot.semantic_source_revision(),
        "intent": "create",
        "instruction": "crea un endpoint con pochi risultati video",
        "target": {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        "basis": None,
        "clarification_response": None,
    }
    status, accepted = _request(
        server,
        "POST",
        f"/v1/sessions/{session['id']}/turns",
        token=session["token"],
        body=request,
    )
    assert status == 202
    terminal = _wait_turn(server, session, accepted["turn_id"])
    assert terminal["outcome"] == "needs_clarification"
    assert terminal["clarification"]["kind"] == "result_count"
    return session, terminal, request


def _wait_turn(
    server: _ThreadingBrainHTTPServer,
    session: dict[str, Any],
    turn_id: str,
) -> dict[str, Any]:
    for _ in range(200):
        status, result = _request(
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


def _answer_body(terminal: dict[str, Any], *, request_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": request_id or str(uuid.uuid4()),
        "clarification_id": terminal["clarification"]["clarification_id"],
        "answer": {"integer": 24},
    }


def test_answer_request_accepts_the_full_server_opaque_reference_surface() -> None:
    opaque = "a" + ".:/-" * 63 + "bcd"
    assert len(opaque) == 256
    parsed = ClarificationAnswerRequest.parse(
        {
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
            "clarification_id": opaque,
            "answer": {"option_ref": "catalog:play-demo.video/value_1"},
        }
    )
    assert parsed.clarification_id == opaque
    assert parsed.answer == {"option_ref": "catalog:play-demo.video/value_1"}

    too_long = "a" * 257
    for field in ("clarification_id", "option_ref"):
        body = {
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
            "clarification_id": "clarification-ok",
            "answer": {"option_ref": "option-ok"},
        }
        if field == "clarification_id":
            body["clarification_id"] = too_long
        else:
            body["answer"] = {"option_ref": too_long}
        with pytest.raises(BrainError):
            ClarificationAnswerRequest.parse(body)


def test_answer_route_reconstructs_parent_and_reaches_proposed_with_idempotent_retry(
    tmp_path: Path,
) -> None:
    with _service(tmp_path) as (server, runtime, compiler, model, tenant):
        session, pending, _original = _start_pending(server, runtime, tenant)
        body = _answer_body(pending, request_id="123e4567-e89b-12d3-a456-426614174001")
        path = f"/v1/sessions/{session['id']}/turns/{pending['turn_id']}/answer"

        status, accepted = _request(server, "POST", path, token=session["token"], body=body)
        assert status == 202
        assert accepted["request_id"] == body["request_id"]
        continuation = _wait_turn(server, session, accepted["turn_id"])
        assert continuation["outcome"] == "proposed"
        assert continuation["grounding"]["output_contract"]["take"] == {
            "mode": "count",
            "value": 24,
            "source": "operator_confirmed",
        }
        assert continuation["session_memory"]["decisions"][0]["answer"] == {"integer": 24}

        status, retry = _request(server, "POST", path, token=session["token"], body=body)
        assert status == 202
        assert retry["turn_id"] == accepted["turn_id"]
        assert compiler.calls == 1
        assert model.calls == 1


def test_answer_route_rejects_unknown_fields_before_model_or_compiler(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, runtime, compiler, model, tenant):
        session, pending, _original = _start_pending(server, runtime, tenant)
        body = {**_answer_body(pending), "extra": "must reject"}
        status, rejected = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns/{pending['turn_id']}/answer",
            token=session["token"],
            body=body,
        )
        assert status == 400
        assert rejected["error"]["code"] == "INVALID_SCHEMA"
        assert compiler.calls == 0
        assert model.calls == 0


def test_answer_route_rejects_wrong_parent_and_cross_session_before_work(
    tmp_path: Path,
) -> None:
    with _service(tmp_path) as (server, runtime, compiler, model, tenant):
        session, pending, _original = _start_pending(server, runtime, tenant)
        wrong_parent_path = f"/v1/sessions/{session['id']}/turns/{'p' * 24}/answer"
        status, rejected = _request(
            server,
            "POST",
            wrong_parent_path,
            token=session["token"],
            body=_answer_body(pending),
        )
        assert status == 404
        assert rejected["error"]["code"] == "TURN_UNAVAILABLE"

        # A valid session token must not make another session's parent turn
        # addressable or permit moving its pending question across tenants.
        other = _open(server, runtime)
        cross_path = f"/v1/sessions/{other['id']}/turns/{pending['turn_id']}/answer"
        status, rejected = _request(
            server,
            "POST",
            cross_path,
            token=other["token"],
            body=_answer_body(pending),
        )
        assert status == 404
        assert rejected["error"]["code"] == "TURN_UNAVAILABLE"
        assert compiler.calls == 0
        assert model.calls == 0


def test_answer_route_rejects_wrong_clarification_and_replay_before_work(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, runtime, compiler, model, tenant):
        session, pending, _original = _start_pending(server, runtime, tenant)
        wrong = _answer_body(pending)
        wrong["clarification_id"] = "clr_unknown"
        status, rejected = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns/{pending['turn_id']}/answer",
            token=session["token"],
            body=wrong,
        )
        assert status == 409
        assert rejected["error"]["code"] == "CLARIFICATION_MISMATCH"
        assert compiler.calls == 0
        assert model.calls == 0

        valid = _answer_body(pending)
        status, accepted = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns/{pending['turn_id']}/answer",
            token=session["token"],
            body=valid,
        )
        assert status == 202
        _wait_turn(server, session, accepted["turn_id"])
        assert compiler.calls == 1
        assert model.calls == 1

        replay = {**valid, "request_id": str(uuid.uuid4())}
        status, rejected = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/turns/{pending['turn_id']}/answer",
            token=session["token"],
            body=replay,
        )
        assert status == 409
        assert rejected["error"]["code"] == "CLARIFICATION_REPLAY"
        assert compiler.calls == 1
        assert model.calls == 1
