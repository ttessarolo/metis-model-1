from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import metis_model1.brain_server as brain_server_module
from metis_model1.brain_intent_ir import (
    FLASH_INTENT_SCHEMA_SHA256,
    IntentCompileRequest,
    IntentCompileResult,
    IntentIR,
    StaticIntentCompiler,
)
from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_output_contract import parse_output_request
from metis_model1.brain_protocol import CAPABILITIES, BrainError
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_server import (
    BrainApplication,
    BrainConfig,
    BrainIntentCompilerConfig,
    BrainRetrievalConfig,
    BrainRuntime,
    MetisBrainService,
    load_brain_config,
)
from metis_model1.brain_sessions import ClientPolicy, SessionLimits
from metis_model1.brain_turns import ClarificationAnswerRequest, TurnRecord, TurnRequest, TurnStore

_CONTEXT = "sha256:" + "a" * 64
_SEMANTIC = "sha256:" + "b" * 64
_SESSION = "s" * 32
_TURN = "t" * 24


def _intent_ir(
    source: str = "film italiani",
    *,
    logic: str = "all",
    polarity: str = "include",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "create",
        "target_scope": "new",
        "concept_logic": logic,
        "concepts": [{"source": source, "query": "film prodotti in Italia", "polarity": polarity}],
        "response_format": "unspecified",
        "fallback": "unspecified",
        "ambiguities": [],
    }


class FakeCompiler:
    toolchain_binding = "sha256:" + "c" * 64

    def __init__(self, closed: list[str] | None = None) -> None:
        self.closed = closed if closed is not None else []

    def close(self) -> None:
        self.closed.append("compiler")


class FakeRetriever:
    def __init__(self, results: list[RetrievalResult]) -> None:
        self.results = list(results)
        self.requests: list[Any] = []

    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        del lease
        self.requests.append(request)
        return self.results.pop(0)


class FakeModel:
    model_loaded = True
    model_revision = "model-test"
    adapter_sha256 = "adapter-test"

    def __init__(self, closed: list[str] | None = None) -> None:
        self.closed = closed if closed is not None else []

    def close(self) -> None:
        self.closed.append("model")


class FakeFlash:
    model_loaded = True
    model_revision = "flash-test"
    schema_sha256 = FLASH_INTENT_SCHEMA_SHA256
    decoder = "llguidance-1.8.0"

    def __init__(
        self, result: IntentCompileResult | object, closed: list[str] | None = None
    ) -> None:
        self.result = result
        self.calls: list[IntentCompileRequest] = []
        self.warm_calls = 0
        self.closed = closed if closed is not None else []

    def warmup(self) -> dict[str, int | str]:
        self.warm_calls += 1
        self.closed.append("flash_warm")
        return {"status": "ready", "duration_ms": 1, "worker_load_ms": 1}

    def compile(self, request: IntentCompileRequest) -> object:
        self.calls.append(request)
        if isinstance(self.result, StaticIntentCompiler):
            return self.result.compile(request)
        return self.result

    def close(self) -> None:
        self.closed.append("flash")


class FakeLeaseManager:
    @contextmanager
    def operation(self, **_kwargs: Any):
        yield SimpleNamespace(cancellation=threading.Event())


def _request(
    instruction: str = "crea un endpoint per film italiani con 24 risultati",
) -> TurnRequest:
    return TurnRequest(
        2,
        "123e4567-e89b-12d3-a456-426614174000",
        _CONTEXT,
        _SEMANTIC,
        "create",
        instruction,
        {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        None,
        None,
    )


def _result(status: str, *, instruction: str = "") -> RetrievalResult:
    grounding: dict[str, Any] = {
        "status": status,
        "catalogs": ["video"] if status == "resolved" else [],
    }
    if status == "resolved":
        grounding["selections"] = [
            {"catalog": "video", "field": "paesiorigine", "literal": "ITALIA"}
        ]
    else:
        grounding["unresolved"] = [instruction or "film italiani"]
    return RetrievalResult({"semantic_schema": 2}, grounding, _SEMANTIC, ())


def _orchestrator(retriever: FakeRetriever, flash: Any | None = None) -> BrainOrchestrator:
    return BrainOrchestrator(
        retriever=retriever,
        model=FakeModel(),
        compiler=FakeCompiler(),
        intent_compiler=flash,
    )


def test_config_intent_compiler_is_strict_and_requires_schema2(tmp_path: Path) -> None:
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    metis = tmp_path / "metis"
    metis.mkdir()
    node = tmp_path / "node"
    node.write_bytes(b"node")
    python = tmp_path / "python"
    python.write_bytes(b"python")
    model = tmp_path / "model"
    model.mkdir()
    value: dict[str, Any] = {
        "schema_version": 1,
        "server": {"host": "127.0.0.1", "port": 0, "runtime_root": str(tmp_path / "runtime")},
        "toolchain": {
            "metis_git_root": str(metis),
            "node_path": str(node),
            "compiler_concurrency": 1,
        },
        "tenants": [{"alias": "demo", "tenant_id": "demo", "root": str(tenant)}],
        "clients": [
            {"client_id": "visix", "tenant_aliases": ["demo"], "capabilities": sorted(CAPABILITIES)}
        ],
        "limits": {"global_sessions": 16, "sessions_per_client": 4, "sessions_per_tenant": 4},
        "retrieval": {"schema2": True},
        "intent_compiler": {
            "python_path": str(python),
            "model_path": str(model),
            "timeout_seconds": 30,
            "warmup": "on_start",
            "mode": "assist_on_unresolved",
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    loaded = load_brain_config(path)
    assert loaded.intent_compiler == BrainIntentCompilerConfig(
        python, model, 30.0, "on_start", "assist_on_unresolved"
    )

    value["retrieval"] = {"schema2": False}
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(BrainError, match="requires schema2"):
        load_brain_config(path)

    value["retrieval"] = {"schema2": True}
    value["intent_compiler"]["mode"] = "remote"  # type: ignore[index]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(BrainError, match="mode"):
        load_brain_config(path)


def _service_config(
    tmp_path: Path, *, intent: BrainIntentCompilerConfig | None = None
) -> BrainConfig:
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    metis = tmp_path / "metis"
    metis.mkdir()
    node = tmp_path / "node"
    node.write_bytes(b"node")
    return BrainConfig(
        host="127.0.0.1",
        port=0,
        runtime_root=tmp_path / "runtime",
        metis_git_root=metis,
        node_path=node,
        compiler_concurrency=1,
        tenant_grants=(("demo", "demo", tenant),),
        client_policies=(ClientPolicy("visix", frozenset({"demo"}), CAPABILITIES),),
        limits=SessionLimits(),
        retrieval=BrainRetrievalConfig(schema2=True),
        intent_compiler=intent,
    )


def test_application_health_and_close_expose_only_bounded_flash_identity(tmp_path: Path) -> None:
    runtime = BrainRuntime(tmp_path / "runtime")
    manager = SimpleNamespace(
        aggregate_metrics=lambda: {}, register_cleanup_listener=lambda _fn: None
    )
    flash = FakeFlash(StaticIntentCompiler(_intent_ir()), [])
    app = BrainApplication(
        runtime=runtime,
        manager=manager,
        compiler=FakeCompiler(),
        model=FakeModel(),
        intent_compiler=flash,
    )
    try:
        health = app.health()
        assert health["intent_compiler"]["identity"] == {
            "model_revision": "flash-test",
            "schema_sha256": FLASH_INTENT_SCHEMA_SHA256,
            "decoder": "llguidance-1.8.0",
        }
        assert "path" not in json.dumps(health)
        assert "instruction" not in json.dumps(health)
    finally:
        app.close()
        runtime.close()
    assert flash.closed == ["flash"]


def test_service_warms_flash_before_binding_and_closes_partial_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_root = tmp_path / "ok"
    cfg_root.mkdir()
    order: list[str] = []

    class BindingSentinel:
        server_address = ("127.0.0.1", 43123)

        def __init__(self, _address: tuple[str, int], _app: Any) -> None:
            order.append("bind")

        def server_close(self) -> None:
            order.append("server_close")

        def shutdown(self) -> None:
            order.append("shutdown")

    monkeypatch.setattr(brain_server_module, "_ThreadingBrainHTTPServer", BindingSentinel)
    flash = FakeFlash(StaticIntentCompiler(_intent_ir()), order)
    service = MetisBrainService(
        _service_config(
            cfg_root,
            intent=BrainIntentCompilerConfig(
                Path("/tmp/python"), Path("/tmp/model"), 10, "on_start", "assist_on_unresolved"
            ),
        ),
        compiler=FakeCompiler(order),
        retriever=SimpleNamespace(close=lambda: order.append("retriever")),
        model=FakeModel(order),
        intent_compiler=flash,
    )
    try:
        assert flash.warm_calls == 1
        assert service.address[0] == "127.0.0.1"
    finally:
        service.close()
    assert order.index("flash_warm") < order.index("bind")

    fail_root = tmp_path / "fail"
    fail_root.mkdir()
    closed: list[str] = []
    failing = FakeFlash(StaticIntentCompiler(_intent_ir()), closed)
    failing.warmup = lambda: (_ for _ in ()).throw(
        BrainError("FLASH_RUNTIME_CONFIG", 500, "no warmup")
    )  # type: ignore[method-assign]
    with pytest.raises(BrainError, match="no warmup"):
        MetisBrainService(
            _service_config(
                fail_root,
                intent=BrainIntentCompilerConfig(
                    Path("/tmp/python"), Path("/tmp/model"), 10, "on_start", "assist_on_unresolved"
                ),
            ),
            compiler=FakeCompiler(closed),
            retriever=SimpleNamespace(close=lambda: closed.append("retriever")),
            model=FakeModel(closed),
            intent_compiler=failing,
        )
    assert {"compiler", "retriever", "model", "flash"}.issubset(closed)


def test_orchestrator_bypasses_flash_when_grounding_is_resolved() -> None:
    retriever = FakeRetriever([_result("resolved")])
    flash = FakeFlash(StaticIntentCompiler(_intent_ir()))
    request = _request()
    record = TurnRecord(_TURN, _SESSION, request, request.payload_hash)
    result = _orchestrator(retriever, flash)._retry_with_flash(
        lease=SimpleNamespace(), request=request, retrieved=_result("resolved"), record=record
    )
    assert result[0] == request
    assert flash.calls == []
    assert not any(item["event"].startswith("intent.") for item in record.events)


def test_orchestrator_uses_one_flash_call_and_exact_source_spans_for_retry() -> None:
    request = _request()
    flash = FakeFlash(StaticIntentCompiler(_intent_ir("film italiani")))
    retriever = FakeRetriever(
        [_result("unsupported", instruction=request.instruction), _result("resolved")]
    )
    record = TurnRecord(_TURN, _SESSION, request, request.payload_hash)
    retried_request, retried = _orchestrator(retriever, flash)._retry_with_flash(
        lease=SimpleNamespace(),
        request=request,
        retrieved=retriever.results.pop(0),
        record=record,
    )
    assert retried.grounding["status"] == "resolved"
    assert len(flash.calls) == 1
    assert retried_request.server_flash_intent is not None
    ir = IntentIR.parse(retried_request.server_flash_intent["intent_ir"], request=flash.calls[0])
    assert ir.exact_semantic_instruction == "film italiani"
    assert (
        retriever.requests[-1].server_flash_intent["intent_ir"]["concepts"][0]["query"]
        == "film prodotti in Italia"
    )


def test_flash_retry_does_not_change_raw_count_or_pagination_contract() -> None:
    request = _request()
    before = parse_output_request(request.instruction)
    flash = FakeFlash(StaticIntentCompiler(_intent_ir("film italiani")))
    retriever = FakeRetriever([_result("unsupported"), _result("resolved")])
    record = TurnRecord(_TURN, _SESSION, request, request.payload_hash)
    retried_request, _ = _orchestrator(retriever, flash)._retry_with_flash(
        lease=SimpleNamespace(),
        request=request,
        retrieved=retriever.results.pop(0),
        record=record,
    )
    after = parse_output_request(retried_request.instruction)
    assert before == after
    assert before.contracts == after.contracts


def test_flash_retry_preserves_explicit_metis_take_contract() -> None:
    request = _request("crea film italiani con take 12 from @video")
    before = parse_output_request(request.instruction)
    flash = FakeFlash(StaticIntentCompiler(_intent_ir("film italiani")))
    retriever = FakeRetriever([_result("unsupported"), _result("resolved")])
    record = TurnRecord(_TURN, _SESSION, request, request.payload_hash)
    retried_request, _ = _orchestrator(retriever, flash)._retry_with_flash(
        lease=SimpleNamespace(),
        request=request,
        retrieved=retriever.results.pop(0),
        record=record,
    )
    after = parse_output_request(retried_request.instruction)
    assert before == after
    assert after.contracts == (("count", 12),)
    assert after.semantic_instruction == "crea film italiani con @video"


@pytest.mark.parametrize("logic,polarity", [("mixed", "include"), ("all", "exclude")])
def test_unsupported_flash_logic_or_negative_concept_fails_closed(
    logic: str, polarity: str
) -> None:
    request = _request()
    flash = FakeFlash(
        StaticIntentCompiler(_intent_ir("film italiani", logic=logic, polarity=polarity))
    )
    retriever = FakeRetriever([_result("unsupported")])
    record = TurnRecord(_TURN, _SESSION, request, request.payload_hash)
    returned_request, returned = _orchestrator(retriever, flash)._retry_with_flash(
        lease=SimpleNamespace(),
        request=request,
        retrieved=retriever.results.pop(0),
        record=record,
    )
    assert returned_request == request
    assert returned.grounding["status"] == "unsupported"
    assert len(retriever.requests) == 0
    assert record.events[-1]["event"] == "intent.completed"


def test_invalid_flash_result_fails_closed_and_events_do_not_leak_prompt() -> None:
    instruction = "crea un endpoint per film italiani con 24 risultati"
    request = _request(instruction)
    flash = FakeFlash(object())
    record = TurnRecord(_TURN, _SESSION, request, request.payload_hash)
    with pytest.raises(BrainError, match="invalid"):
        _orchestrator(FakeRetriever([_result("unsupported")]), flash)._retry_with_flash(
            lease=SimpleNamespace(),
            request=request,
            retrieved=_result("unsupported"),
            record=record,
        )
    rendered = json.dumps(record.events)
    assert instruction not in rendered
    assert "film italiani" not in rendered


def test_answer_reuses_server_intent_and_client_cannot_inject_it() -> None:
    request = _request("crea film italiani")
    compiled = StaticIntentCompiler(_intent_ir("film italiani")).compile(
        IntentCompileRequest("crea film italiani", "create", "create")
    )
    server_value = {
        "schema_version": 1,
        "intent_ir": compiled.intent_ir.payload(),
        "model_revision": compiled.model_revision,
        "schema_sha256": compiled.schema_sha256,
        "decoder": compiled.decoder,
    }
    request = request.with_server_flash_intent(server_value)
    original_hash = request.payload_hash
    record = TurnRecord(_TURN, _SESSION, request, original_hash)
    record.terminal = {
        "schema_version": 2,
        "turn_id": _TURN,
        "status": "completed",
        "outcome": "needs_clarification",
        "clarification": {"clarification_id": "clarification-1"},
    }
    manager = SimpleNamespace(register_cleanup_listener=lambda _fn: None)
    store = TurnStore(
        manager=manager, retriever=SimpleNamespace(), model=FakeModel(), compiler=FakeCompiler()
    )
    captured: list[TurnRequest] = []
    store._authenticate_record = lambda **_kwargs: record  # type: ignore[method-assign]
    store.submit = lambda **kwargs: captured.append(kwargs["request"]) or record  # type: ignore[method-assign]
    try:
        store.answer(
            session_id=_SESSION,
            token="token",
            parent_turn_id=_TURN,
            answer=ClarificationAnswerRequest(
                1, "123e4567-e89b-12d3-a456-426614174001", "clarification-1", {"integer": 24}
            ),
        )
    finally:
        store.shutdown()
    assert captured[0].server_flash_intent == server_value
    assert request.with_server_flash_intent(server_value).payload_hash == original_hash

    client_payload = request.payload()
    client_payload["server_flash_intent"] = server_value
    with pytest.raises(BrainError):
        TurnRequest.parse(client_payload)
