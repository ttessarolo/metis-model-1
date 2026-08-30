from __future__ import annotations

import http.client
import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_model_runtime import StaticModelRuntime
from metis_model1.brain_protocol import CAPABILITIES, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_server import BrainApplication, BrainRuntime, _ThreadingBrainHTTPServer
from metis_model1.brain_sessions import ClientPolicy, SessionManager
from metis_model1.brain_turns import TurnRequest


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
    ) -> None:
        self.catalogs = catalogs

    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        revision = semantic_revision(lease.snapshot)
        return RetrievalResult(
            context={"tenant": lease.tenant_alias},
            grounding={
                "catalogs": [item["catalog"] for item in self.catalogs],
                "resolutions": [],
                "unresolved": [],
            },
            semantic_source_revision=revision,
            catalog_candidates=self.catalogs,
        )


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
