from __future__ import annotations

import http.client
import json
import os
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_server as brain_server_module
from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_protocol import CAPABILITIES, MAX_JSON_BYTES, BrainError
from metis_model1.brain_semantic_retrieval import Schema2SnapshotRetriever
from metis_model1.brain_server import (
    BrainApplication,
    BrainConfig,
    BrainModelConfig,
    BrainRetrievalConfig,
    BrainRuntime,
    MetisBrainService,
    _ThreadingBrainHTTPServer,
)
from metis_model1.brain_sessions import ClientPolicy, SessionLimits, SessionManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def compile(self, *, lease: Any, source: Any, filename: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "ok",
            "session_id": lease.session_id,
            "context_revision": lease.snapshot.revision,
            "filename": filename,
            "source_bytes": len(source.encode("utf-8")),
        }


class ConstructibleFakeCompiler(FakeCompiler):
    def __init__(self, **_kwargs: Any) -> None:
        self.execution_count = 0


class ClosableFakeModel:
    model_loaded = False
    model_revision = "sha256:" + "1" * 64
    adapter_sha256 = "sha256:" + "2" * 64

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _tenant(root: Path) -> Path:
    root.mkdir()
    (root / "metis.toml").write_text(
        '[tenant]\nid = "tenant-one"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (root / "main.metis").write_text("metis 0.43\ntenant tenant_one {}\n", encoding="utf-8")
    return root.resolve()


@contextmanager
def _service(
    tmp_path: Path, *, clock: FakeClock | None = None
) -> Iterator[tuple[_ThreadingBrainHTTPServer, BrainRuntime]]:
    runtime = BrainRuntime((tmp_path / "runtime").resolve())
    tenant = _tenant(tmp_path / "tenant")
    manager = SessionManager(
        registry=TenantRegistry([("demo", "tenant-one", tenant)]),
        policies=[
            ClientPolicy(
                client_id="visix",
                tenant_aliases=frozenset({"demo"}),
                capabilities=CAPABILITIES,
            )
        ],
        runtime_root=runtime.run_dir / "sessions",
        toolchain_binding=FakeCompiler.toolchain_binding,
        monotonic=clock or time.monotonic,
    )
    app = BrainApplication(runtime=runtime, manager=manager, compiler=FakeCompiler())  # type: ignore[arg-type]
    server = _ThreadingBrainHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runtime
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        manager.shutdown()
        runtime.close()


def _request(
    server: _ThreadingBrainHTTPServer,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | bytes | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    request_headers = dict(headers or {})
    raw: bytes | None
    if isinstance(body, dict):
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    else:
        raw = body
    if raw is not None:
        request_headers.setdefault("Content-Type", "application/json")
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    connection.request(method, path, body=raw, headers=request_headers)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    response_headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, payload, response_headers


def _bootstrap(runtime: BrainRuntime) -> str:
    return runtime.bootstrap_file.read_text(encoding="ascii").strip()


def _open(
    server: _ThreadingBrainHTTPServer,
    runtime: BrainRuntime,
    *,
    token: str | None = None,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    return _request(
        server,
        "POST",
        "/v1/sessions",
        token=token or _bootstrap(runtime),
        body={
            "client_id": "visix",
            "tenant_alias": "demo",
            "capabilities": sorted(CAPABILITIES),
        },
    )


def test_live_http_session_context_compile_status_and_close(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, runtime):
        status, health, headers = _request(server, "GET", "/v1/health")
        assert status == 200
        assert health["status"] == "ready"
        assert health["model_loaded"] is False
        assert "access-control-allow-origin" not in headers

        status, opened, _headers = _open(server, runtime)
        assert status == 201
        session = opened["session"]
        session_id = session["id"]
        token = session["token"]
        revision = session["context_revision"]
        assert token not in json.dumps(health)

        status, context, _headers = _request(
            server,
            "POST",
            f"/v1/sessions/{session_id}/context",
            token=token,
            body={"expected_revision": revision},
        )
        assert status == 200
        assert context["revision"] == revision
        assert {item["path"] for item in context["files"]} == {"metis.toml", "main.metis"}

        source = "metis 0.43\ntenant candidate {}\n"
        status, compiled, _headers = _request(
            server,
            "POST",
            f"/v1/sessions/{session_id}/compile",
            token=token,
            body={
                "expected_revision": revision,
                "source": source,
                "filename": "candidate.metis",
                "execution_mode": "source",
                "endpoint": None,
            },
        )
        assert status == 200
        assert compiled["source_bytes"] == len(source.encode("utf-8"))

        status, current, _headers = _request(
            server, "GET", f"/v1/sessions/{session_id}", token=token
        )
        assert status == 200
        assert "root" not in json.dumps(current)
        assert "token" not in json.dumps(current)

        status, closed, _headers = _request(
            server, "DELETE", f"/v1/sessions/{session_id}", token=token
        )
        assert status == 200
        assert closed["session"]["state"] == "closed"
        status, unavailable, _headers = _request(
            server, "GET", f"/v1/sessions/{session_id}", token=token
        )
        assert status == 401
        assert unavailable["error"]["code"] == "SESSION_UNAVAILABLE"


def test_http_turn_acceptance_mirrors_schema_two(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, runtime):
        status, opened, _headers = _open(server, runtime)
        assert status == 201
        session = opened["session"]
        session_id = session["id"]
        token = session["token"]
        revision = session["context_revision"]
        status, context, _headers = _request(
            server,
            "POST",
            f"/v1/sessions/{session_id}/context",
            token=token,
            body={"expected_revision": revision},
        )
        assert status == 200

        status, accepted, _headers = _request(
            server,
            "POST",
            f"/v1/sessions/{session_id}/turns",
            token=token,
            body={
                "schema_version": 2,
                "request_id": "123e4567-e89b-12d3-a456-426614174001",
                "expected_context_revision": revision,
                "expected_semantic_source_revision": context["semantic_source_revision"],
                "intent": "create",
                "instruction": "crea un endpoint di prova",
                "target": {
                    "mode": "create",
                    "relative_path": "properties/candidate.metis",
                    "endpoint": None,
                    "base_sha256": None,
                },
                "basis": None,
                "clarification_response": None,
            },
        )
        assert status == 202
        assert accepted["schema_version"] == 2


def test_health_exposes_non_sensitive_identity_and_close_closes_model(tmp_path: Path) -> None:
    runtime = BrainRuntime((tmp_path / "runtime").resolve())
    tenant = _tenant(tmp_path / "tenant")
    manager = SessionManager(
        registry=TenantRegistry([("demo", "tenant-one", tenant)]),
        policies=[ClientPolicy("visix", frozenset({"demo"}), CAPABILITIES)],
        runtime_root=runtime.run_dir / "sessions",
        toolchain_binding=FakeCompiler.toolchain_binding,
        limits=SessionLimits(),
    )
    model = ClosableFakeModel()
    retriever = Schema2SnapshotRetriever(lambda _snapshot: None)
    app = BrainApplication(
        runtime=runtime,
        manager=manager,
        compiler=FakeCompiler(),  # type: ignore[arg-type]
        retriever=retriever,
        model=model,
    )
    try:
        health = app.health()
        assert health["turn_schema_versions"] == [1, 2]
        assert health["clarification_answer_schema_versions"] == [1]
        assert health["model_identity"] == {
            "model_revision": model.model_revision,
            "adapter_sha256": model.adapter_sha256,
        }
        assert health["model_warmup"] == {
            "policy": "disabled",
            "status": "disabled",
            "duration_ms": None,
            "worker_load_ms": None,
            "prefix_tokens": None,
            "prefix_cache_ready": False,
        }
        assert health["semantic_retrieval"] == {
            "enabled": True,
            "schema": 2,
            "implementation": "Schema2SnapshotRetriever",
        }
    finally:
        app.close()
        manager.shutdown()
        runtime.close()
    assert model.closed is True


def test_bootstrap_permissions_rotation_and_authority_separation(tmp_path: Path) -> None:
    first_base = (tmp_path / "runtime-one").resolve()
    first = BrainRuntime(first_base)
    first_token = _bootstrap(first)
    try:
        assert stat.S_IMODE(first.run_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(first.bootstrap_file.stat().st_mode) == 0o600
    finally:
        first.close()
    second = BrainRuntime(first_base)
    try:
        assert _bootstrap(second) != first_token
    finally:
        second.close()

    with _service(tmp_path / "service") as (server, runtime):
        status, opened, _headers = _open(server, runtime)
        assert status == 201
        session_id = opened["session"]["id"]
        status, payload, _headers = _request(
            server,
            "GET",
            f"/v1/sessions/{session_id}",
            token=_bootstrap(runtime),
        )
        assert status == 401
        assert payload["error"]["code"] == "SESSION_UNAVAILABLE"


def test_bootstrap_failure_removes_partial_token_and_private_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = (tmp_path / "runtime-failure").resolve()

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("synthetic bootstrap failure")

    monkeypatch.setattr(brain_server_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="synthetic bootstrap failure"):
        BrainRuntime(runtime_root)
    assert runtime_root.is_dir()
    assert list(runtime_root.iterdir()) == []


def test_wrong_bootstrap_cross_session_token_and_capability_fail_closed(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, runtime):
        status, payload, _headers = _open(server, runtime, token="wrong")
        assert status == 401
        assert payload["error"]["code"] == "BOOTSTRAP_UNAUTHORIZED"

        _status, first, _headers = _open(server, runtime)
        _status, second, _headers = _open(server, runtime)
        status, payload, _headers = _request(
            server,
            "GET",
            f"/v1/sessions/{second['session']['id']}",
            token=first["session"]["token"],
        )
        assert status == 401
        assert payload["error"]["code"] == "SESSION_UNAVAILABLE"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Origin": "https://attacker.example"}, "BROWSER_ORIGIN_DENIED"),
        ({"Cookie": "session=attacker"}, "COOKIE_DENIED"),
    ],
)
def test_browser_pivots_are_rejected_without_cors(
    tmp_path: Path, headers: dict[str, str], expected: str
) -> None:
    with _service(tmp_path) as (server, runtime):
        status, payload, response_headers = _request(
            server,
            "POST",
            "/v1/sessions",
            token=_bootstrap(runtime),
            headers=headers,
            body={
                "client_id": "visix",
                "tenant_alias": "demo",
                "capabilities": sorted(CAPABILITIES),
            },
        )
        assert status in {400, 403}
        assert payload["error"]["code"] == expected
        assert "access-control-allow-origin" not in response_headers


def test_query_duplicate_unknown_fields_and_relaxed_content_type_are_rejected(
    tmp_path: Path,
) -> None:
    with _service(tmp_path) as (server, runtime):
        status, payload, _headers = _request(server, "GET", "/v1/health?token=secret")
        assert status == 404
        assert payload["error"]["code"] == "INVALID_ROUTE"

        duplicate = (
            b'{"client_id":"visix","client_id":"other","tenant_alias":"demo",'
            b'"capabilities":["session.read"]}'
        )
        status, payload, _headers = _request(
            server,
            "POST",
            "/v1/sessions",
            token=_bootstrap(runtime),
            body=duplicate,
        )
        assert status == 400
        assert payload["error"]["code"] == "DUPLICATE_FIELD"

        status, payload, _headers = _request(
            server,
            "POST",
            "/v1/sessions",
            token=_bootstrap(runtime),
            headers={"Content-Type": "application/json; charset=utf-8"},
            body={
                "client_id": "visix",
                "tenant_alias": "demo",
                "capabilities": ["session.read"],
            },
        )
        assert status == 415
        assert payload["error"]["code"] == "INVALID_BODY"


def test_bad_host_malformed_auth_and_unsupported_method_are_json_errors(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, _runtime):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.putrequest("GET", "/v1/health", skip_host=True)
        connection.putheader("Host", "attacker.example")
        connection.endheaders()
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        assert response.status == 400
        assert payload["error"]["code"] == "HOST_DENIED"

        status, payload, _headers = _request(
            server,
            "POST",
            "/v1/sessions",
            headers={"Authorization": "Basic nope"},
            body={
                "client_id": "visix",
                "tenant_alias": "demo",
                "capabilities": sorted(CAPABILITIES),
            },
        )
        assert status == 401
        assert payload["error"]["code"] == "UNAUTHORIZED"

        status, payload, headers = _request(server, "OPTIONS", "/v1/health")
        assert status == 405
        assert payload["error"]["code"] == "METHOD_NOT_ALLOWED"
        assert headers["content-type"] == "application/json"


def test_duplicate_security_headers_are_rejected(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, _runtime):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.putrequest("GET", "/v1/health", skip_host=True)
        connection.putheader("Host", f"127.0.0.1:{server.server_address[1]}")
        connection.putheader("Host", "attacker.example")
        connection.endheaders()
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        assert response.status == 400
        assert payload["error"]["code"] == "HOST_DENIED"


def test_duplicate_content_length_and_transfer_encoding_cannot_close_session(
    tmp_path: Path,
) -> None:
    with _service(tmp_path) as (server, runtime):
        _status, opened, _headers = _open(server, runtime)
        session = opened["session"]
        for framing_headers in (
            (("Content-Length", "0"), ("Content-Length", "5")),
            (("Transfer-Encoding", "chunked"),),
        ):
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_address[1], timeout=5
            )
            connection.putrequest("DELETE", f"/v1/sessions/{session['id']}")
            connection.putheader("Authorization", f"Bearer {session['token']}")
            for key, value in framing_headers:
                connection.putheader(key, value)
            connection.endheaders()
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            assert response.status == 400
            assert payload["error"]["code"] == "INVALID_BODY"

        status, payload, _headers = _request(
            server,
            "GET",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )
        assert status == 200
        assert payload["session"]["state"] == "active"


def test_invalid_compile_schema_does_not_refresh_session_ttl(tmp_path: Path) -> None:
    clock = FakeClock()
    with _service(tmp_path, clock=clock) as (server, runtime):
        _status, opened, _headers = _open(server, runtime)
        session = opened["session"]
        clock.advance(1000)
        status, payload, _headers = _request(
            server,
            "POST",
            f"/v1/sessions/{session['id']}/compile",
            token=session["token"],
            body={
                "expected_revision": session["context_revision"],
                "source": "metis 0.43\ntenant candidate {}\n",
                "filename": "../escape.metis",
                "execution_mode": "source",
                "endpoint": None,
            },
        )
        assert status == 400
        assert payload["error"]["code"] == "INVALID_SCHEMA"
        clock.advance(200)
        status, payload, _headers = _request(
            server,
            "GET",
            f"/v1/sessions/{session['id']}",
            token=session["token"],
        )
        assert status == 401
        assert payload["error"]["code"] == "SESSION_UNAVAILABLE"


def test_oversized_body_is_rejected_from_headers_before_dispatch(tmp_path: Path) -> None:
    with _service(tmp_path) as (server, runtime):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.putrequest("POST", "/v1/sessions")
        connection.putheader("Authorization", f"Bearer {_bootstrap(runtime)}")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(MAX_JSON_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        assert response.status == 413
        assert payload["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_runtime_cleanup_never_follows_session_symlink(tmp_path: Path) -> None:
    runtime = BrainRuntime((tmp_path / "runtime").resolve())
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    os.symlink(sentinel, runtime.run_dir / "unrelated-link")
    runtime.close()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def _service_config(tmp_path: Path) -> BrainConfig:
    tenant = _tenant(tmp_path / "configured-tenant")
    metis_root = tmp_path / "metis"
    metis_root.mkdir()
    node_path = tmp_path / "node"
    node_path.write_text("unused", encoding="utf-8")
    return BrainConfig(
        host="127.0.0.1",
        port=0,
        runtime_root=(tmp_path / "configured-runtime").resolve(),
        metis_git_root=metis_root.resolve(),
        node_path=node_path.resolve(),
        compiler_concurrency=1,
        tenant_grants=(("demo", "tenant-one", tenant),),
        client_policies=(
            ClientPolicy(
                client_id="visix",
                tenant_aliases=frozenset({"demo"}),
                capabilities=CAPABILITIES,
            ),
        ),
        limits=SessionLimits(),
    )


def test_constructor_bind_failure_cleans_private_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _service_config(tmp_path)

    class FailingServer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise OSError("synthetic bind failure")

    monkeypatch.setattr(brain_server_module, "BrainCompiler", ConstructibleFakeCompiler)
    monkeypatch.setattr(brain_server_module, "_ThreadingBrainHTTPServer", FailingServer)
    with pytest.raises(OSError, match="synthetic bind failure"):
        MetisBrainService(config)
    assert list(config.runtime_root.glob("run-*")) == []


def test_concurrent_close_waits_for_cleanup_and_removes_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(brain_server_module, "BrainCompiler", ConstructibleFakeCompiler)
    service = MetisBrainService(_service_config(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    original_shutdown = service.app.manager.shutdown

    def delayed_shutdown() -> None:
        entered.set()
        assert release.wait(timeout=5)
        original_shutdown()

    monkeypatch.setattr(service.app.manager, "shutdown", delayed_shutdown)
    first = threading.Thread(target=service.close)
    second = threading.Thread(target=service.close)
    first.start()
    assert entered.wait(timeout=5)
    second.start()
    second.join(timeout=0.05)
    assert second.is_alive()
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert not first.is_alive()
    assert not second.is_alive()
    assert not service.runtime.bootstrap_file.exists()
    assert not service.runtime.run_dir.exists()


def test_service_wires_configured_model_and_schema2_retriever_without_loading_real_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _service_config(tmp_path)
    python_path = tmp_path / "python"
    python_path.write_bytes(b"fake")
    model_path = tmp_path / "model"
    model_path.mkdir()
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    config = replace(
        config,
        model=BrainModelConfig(python_path, model_path, adapter_path, 7.0),
        retrieval=BrainRetrievalConfig(schema2=True),
    )
    calls: dict[str, Any] = {}

    class FakeModel:
        model_loaded = False
        model_revision = "sha256:" + "3" * 64
        adapter_sha256 = "sha256:" + "4" * 64

        def __init__(self, **kwargs: Any) -> None:
            calls["model"] = kwargs

        def close(self) -> None:
            calls["model_closed"] = True

    class FakeLoader:
        def __init__(self, **kwargs: Any) -> None:
            calls["loader"] = kwargs

    class FakeRetriever:
        def __init__(self, loader: Any) -> None:
            calls["retriever_loader"] = loader

    monkeypatch.setattr(brain_server_module, "MlxBrainModelRuntime", FakeModel)
    monkeypatch.setattr(brain_server_module, "PinnedCatalogProjectionLoader", FakeLoader)
    monkeypatch.setattr(brain_server_module, "Schema2SnapshotRetriever", FakeRetriever)
    service = MetisBrainService(config, compiler=ConstructibleFakeCompiler())
    try:
        assert calls["model"] == {
            "python_path": python_path,
            "model_path": model_path,
            "adapter_path": adapter_path,
            "timeout_seconds": 7.0,
        }
        assert calls["loader"] == {
            "metis_root": config.metis_git_root,
            "node_path": config.node_path,
            "max_concurrency": config.compiler_concurrency,
        }
        assert calls["retriever_loader"] is not None
    finally:
        service.close()
    assert calls["model_closed"] is True


def test_service_warms_configured_model_before_binding_and_exposes_safe_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _service_config(tmp_path)
    python_path = tmp_path / "python"
    python_path.write_bytes(b"fake")
    model_path = tmp_path / "model"
    model_path.mkdir()
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    config = replace(
        config,
        model=BrainModelConfig(python_path, model_path, adapter_path, 7.0, warmup="on_start"),
        retrieval=BrainRetrievalConfig(schema2=True),
    )
    calls: list[str] = []

    class WarmFakeModel:
        model_loaded = False
        model_revision = "sha256:" + "3" * 64
        adapter_sha256 = "sha256:" + "4" * 64
        warmup_status = "cold"
        warmup_duration_ms = None
        warmup_worker_load_ms = None
        warmup_prefix_tokens = None
        prefix_cache_ready = False

        def __init__(self, **_kwargs: Any) -> None:
            calls.append("constructed")

        def warmup(self) -> dict[str, int | str]:
            calls.append("warmed")
            self.model_loaded = True
            self.warmup_status = "ready"
            self.warmup_duration_ms = 12
            self.warmup_worker_load_ms = 10
            self.warmup_prefix_tokens = 2048
            self.prefix_cache_ready = True
            return {"status": "ready", "duration_ms": 12, "worker_load_ms": 10}

        def close(self) -> None:
            calls.append("closed")

    class RecordingServer(_ThreadingBrainHTTPServer):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append("bound")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(brain_server_module, "MlxBrainModelRuntime", WarmFakeModel)
    monkeypatch.setattr(brain_server_module, "_ThreadingBrainHTTPServer", RecordingServer)
    service = MetisBrainService(
        config,
        compiler=ConstructibleFakeCompiler(),
        retriever=Schema2SnapshotRetriever(lambda _snapshot: None),
    )
    try:
        assert calls[:3] == ["constructed", "warmed", "bound"]
        assert service.app.health()["model_warmup"] == {
            "policy": "on_start",
            "status": "ready",
            "duration_ms": 12,
            "worker_load_ms": 10,
            "prefix_tokens": 2048,
            "prefix_cache_ready": True,
        }
    finally:
        service.close()
    assert calls[-1] == "closed"


def test_service_warmup_failure_is_fail_closed_and_cleans_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _service_config(tmp_path)
    python_path = tmp_path / "python"
    python_path.write_bytes(b"fake")
    model_path = tmp_path / "model"
    model_path.mkdir()
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    config = replace(
        config,
        model=BrainModelConfig(python_path, model_path, adapter_path, 7.0, warmup="on_start"),
        retrieval=BrainRetrievalConfig(schema2=True),
    )
    calls: list[str] = []

    class FailingWarmModel:
        def __init__(self, **_kwargs: Any) -> None:
            calls.append("constructed")

        def warmup(self) -> None:
            calls.append("warmup_failed")
            raise BrainError("MODEL_RUNTIME_TIMEOUT", 504, "synthetic warmup timeout")

        def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(brain_server_module, "MlxBrainModelRuntime", FailingWarmModel)
    with pytest.raises(BrainError) as raised:
        MetisBrainService(
            config,
            compiler=ConstructibleFakeCompiler(),
            retriever=Schema2SnapshotRetriever(lambda _snapshot: None),
        )
    assert raised.value.code == "MODEL_RUNTIME_TIMEOUT"
    assert calls == ["constructed", "warmup_failed", "closed"]
    assert list(config.runtime_root.glob("run-*")) == []


def test_service_rejects_incomplete_warmup_receipt_before_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _service_config(tmp_path)
    python_path = tmp_path / "python"
    python_path.write_bytes(b"fake")
    model_path = tmp_path / "model"
    model_path.mkdir()
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    config = replace(
        config,
        model=BrainModelConfig(python_path, model_path, adapter_path, 7.0, warmup="on_start"),
        retrieval=BrainRetrievalConfig(schema2=True),
    )
    calls: list[str] = []

    class IncompleteWarmModel:
        model_loaded = False

        def __init__(self, **_kwargs: Any) -> None:
            calls.append("constructed")

        def warmup(self) -> dict[str, int | str]:
            calls.append("warmed")
            return {"status": "ready", "duration_ms": 12, "worker_load_ms": 10}

        def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(brain_server_module, "MlxBrainModelRuntime", IncompleteWarmModel)
    with pytest.raises(BrainError, match="did not complete"):
        MetisBrainService(
            config,
            compiler=ConstructibleFakeCompiler(),
            retriever=Schema2SnapshotRetriever(lambda _snapshot: None),
        )
    assert calls == ["constructed", "warmed", "closed"]
    assert list(config.runtime_root.glob("run-*")) == []


@pytest.mark.parametrize("prefix_tokens", [0, brain_server_module.MAX_PREFIX_CACHE_TOKENS + 1])
def test_service_rejects_ready_cache_with_invalid_prefix_tokens_before_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix_tokens: int
) -> None:
    config = _service_config(tmp_path)
    python_path = tmp_path / "python"
    python_path.write_bytes(b"fake")
    model_path = tmp_path / "model"
    model_path.mkdir()
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    config = replace(
        config,
        model=BrainModelConfig(python_path, model_path, adapter_path, 7.0, warmup="on_start"),
        retrieval=BrainRetrievalConfig(schema2=True),
    )
    calls: list[str] = []

    class EmptyPrefixWarmModel:
        model_loaded = True
        prefix_cache_ready = True
        warmup_prefix_tokens = prefix_tokens

        def __init__(self, **_kwargs: Any) -> None:
            calls.append("constructed")

        def warmup(self) -> dict[str, int | str]:
            calls.append("warmed")
            return {"status": "ready", "duration_ms": 12, "worker_load_ms": 10}

        def close(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(brain_server_module, "MlxBrainModelRuntime", EmptyPrefixWarmModel)
    with pytest.raises(BrainError, match="did not complete"):
        MetisBrainService(
            config,
            compiler=ConstructibleFakeCompiler(),
            retriever=Schema2SnapshotRetriever(lambda _snapshot: None),
        )
    assert calls == ["constructed", "warmed", "closed"]
    assert list(config.runtime_root.glob("run-*")) == []
