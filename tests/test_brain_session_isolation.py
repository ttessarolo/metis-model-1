from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_model_runtime import ModelCandidate, ModelRequest
from metis_model1.brain_protocol import CAPABILITIES, BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_sessions import ClientPolicy, SessionManager
from metis_model1.brain_turns import TurnRequest, TurnStore


class FakeCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def compile(self, *, lease: Any, source: str, filename: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "ok",
            "diagnostics": [],
            "toolchain_binding": self.toolchain_binding,
            "receipt_sha256": canonical_sha256({"source": source}),
            "session_id": lease.session_id,
            "filename": filename,
        }


class RecordingModel:
    model_loaded = True
    model_revision = "test"
    adapter_sha256 = "test"

    def __init__(self, entered: threading.Barrier) -> None:
        self.entered = entered
        self.release = threading.Event()
        self.requests: list[ModelRequest] = []
        self._lock = threading.Lock()

    def generate(self, request: ModelRequest) -> ModelCandidate:
        with self._lock:
            self.requests.append(request)
        self.entered.wait(timeout=5)
        assert self.release.wait(timeout=5)
        reference = f' as "{request.reference}"' if request.reference is not None else ""
        return ModelCandidate(
            f"metis 0.43\nendpoint {request.endpoint}{reference} {{\n"
            "  take 1 from @video {\n"
            "    return response.default\n"
            "  }\n"
            "}\n"
        )


class TenantMarkerRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        del request
        revision = semantic_revision(lease.snapshot)
        with self._lock:
            self.calls.append((lease.tenant_alias, lease.snapshot.tenant_id))
        return RetrievalResult(
            context={
                "tenant_alias": lease.tenant_alias,
                "tenant_id": lease.snapshot.tenant_id,
                "context_revision": lease.snapshot.revision,
                "semantic_source_revision": revision,
                "marker": lease.tenant_alias,
            },
            grounding={"status": "resolved", "catalogs": ["video"], "selections": []},
            semantic_source_revision=revision,
            catalog_candidates=({"catalog": "video", "label": "Video"},),
        )


def _tenant(root: Path, tenant_id: str) -> Path:
    root.mkdir()
    (root / "metis.toml").write_text(
        f'[tenant]\nid = "{tenant_id}"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (root / "main.metis").write_text(f"metis 0.43\ntenant {tenant_id.replace('-', '_')} {{}}\n")
    return root.resolve()


def _request(manager: SessionManager, session: Any, request_id: str) -> TurnRequest:
    authenticated = manager._authenticate(  # noqa: SLF001
        session_id=session.session_id, token=session.token, capability="chat.read"
    )
    return TurnRequest(
        2,
        request_id,
        session.context_revision,
        semantic_revision(authenticated.snapshot),
        "create",
        "crea un endpoint video",
        {
            "mode": "create",
            "relative_path": f"{request_id}.metis",
            "endpoint": "demo.endpoint",
            "base_sha256": None,
        },
        None,
        None,
    )


def test_concurrent_sessions_keep_tenant_context_separate(tmp_path: Path) -> None:
    first_root = _tenant(tmp_path / "first", "tenant-first")
    second_root = _tenant(tmp_path / "second", "tenant-second")
    manager = SessionManager(
        registry=TenantRegistry(
            [("first", "tenant-first", first_root), ("second", "tenant-second", second_root)]
        ),
        policies=[ClientPolicy("visix", frozenset({"first", "second"}), CAPABILITIES)],
        runtime_root=(tmp_path / "runtime").resolve(),
        toolchain_binding=FakeCompiler.toolchain_binding,
    )
    retriever = TenantMarkerRetriever()
    model = RecordingModel(threading.Barrier(2))
    store = TurnStore(
        manager=manager,
        retriever=retriever,
        model=model,
        compiler=FakeCompiler(),
        max_workers=2,
    )
    first = manager.create_session(
        client_id="visix", tenant_alias="first", requested_capabilities=CAPABILITIES
    )
    second = manager.create_session(
        client_id="visix", tenant_alias="second", requested_capabilities=CAPABILITIES
    )
    requests = [
        _request(manager, first, "first-request-000000000000000000000000"),
        _request(manager, second, "second-request-000000000000000000000000"),
    ]
    records = [
        store.submit(session_id=opened.session_id, token=opened.token, request=request)
        for opened, request in ((first, requests[0]), (second, requests[1]))
    ]
    entered_deadline = time.monotonic() + 5
    while len(model.requests) < 2 and time.monotonic() < entered_deadline:
        time.sleep(0.01)
    assert len(model.requests) == 2
    observed_contexts = {
        (
            request.target_path,
            request.context.get("tenant_alias"),
            request.context.get("tenant_id"),
            request.context.get("marker"),
        )
        for request in model.requests
    }
    assert observed_contexts == {
        (
            "first-request-000000000000000000000000.metis",
            "first",
            "tenant-first",
            "first",
        ),
        (
            "second-request-000000000000000000000000.metis",
            "second",
            "tenant-second",
            "second",
        ),
    }
    assert all(
        "first" not in str(request.context)
        for request in model.requests
        if request.context["marker"] == "second"
    )
    assert all(
        "second" not in str(request.context)
        for request in model.requests
        if request.context["marker"] == "first"
    )
    model.release.set()
    deadline = time.monotonic() + 5
    while any(record.terminal is None for record in records) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert all(record.terminal is not None for record in records)
    assert set(retriever.calls) == {("first", "tenant-first"), ("second", "tenant-second")}
    manager.close(session_id=first.session_id, token=first.token)
    manager.close(session_id=second.session_id, token=second.token)
    assert store._turns == {}  # noqa: SLF001 - volatile session memory must be erased
    store.shutdown()
    manager.shutdown()


def test_proposal_cannot_cross_session_or_revision(tmp_path: Path) -> None:
    root = _tenant(tmp_path / "tenant", "tenant-one")
    manager = SessionManager(
        registry=TenantRegistry([("demo", "tenant-one", root)]),
        policies=[ClientPolicy("visix", frozenset({"demo"}), CAPABILITIES)],
        runtime_root=(tmp_path / "runtime").resolve(),
        toolchain_binding=FakeCompiler.toolchain_binding,
    )
    store = TurnStore(
        manager=manager,
        retriever=TenantMarkerRetriever(),
        model=RecordingModel(threading.Barrier(1)),
        compiler=FakeCompiler(),
    )
    opened = manager.create_session(
        client_id="visix", tenant_alias="demo", requested_capabilities=CAPABILITIES
    )
    foreign = manager.create_session(
        client_id="visix", tenant_alias="demo", requested_capabilities=CAPABILITIES
    )
    model = store._model  # noqa: SLF001
    model.release.set()
    record = store.submit(
        session_id=opened.session_id,
        token=opened.token,
        request=_request(manager, opened, "proposal-source-000000000000000000000000"),
    )
    deadline = time.monotonic() + 5
    while record.terminal is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert record.terminal is not None
    proposal = record.terminal.get("proposal")
    assert isinstance(proposal, dict), record.terminal
    foreign_snapshot = manager._authenticate(  # noqa: SLF001
        session_id=foreign.session_id, token=foreign.token, capability="chat.read"
    ).snapshot
    with pytest.raises(BrainError, match="proposal is scoped to another session"):
        store.submit(
            session_id=foreign.session_id,
            token=foreign.token,
            request=TurnRequest(
                2,
                "foreign-refine-000000000000000000000000",
                foreign.context_revision,
                semantic_revision(foreign_snapshot),
                "create",
                "refine",
                {
                    "mode": "create",
                    "relative_path": "foreign.metis",
                    "endpoint": "demo.endpoint",
                    "base_sha256": None,
                },
                {"kind": "proposal", "proposal_ref": proposal["proposal_ref"]},
                None,
            ),
        )
    store.shutdown()
    manager.shutdown()
