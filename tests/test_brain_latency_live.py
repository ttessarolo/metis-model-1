from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import metis_model1.brain_latency_live as live
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_server import BrainConfig, BrainModelConfig, BrainRetrievalConfig
from metis_model1.brain_sessions import ClientPolicy, SessionLimits

CASE = Path(__file__).parents[1] / "examples/metis-brain-latency.play-demo.json"
EXPECTED_SURFACE = {
    "take": {"mode": "count", "value": 24},
    "order_field": "publication_date",
    "order_direction": "descending",
    "response": "response.expanded",
}
SHAPE_CONTRACT = {
    "endpoint": "demo.a_b_test",
    **EXPECTED_SURFACE,
}


def test_frozen_case_has_the_authoritative_edit_roster() -> None:
    case = live.load_latency_case(CASE)

    assert case.pairs == 6
    assert case.arm_order == ("direct", "prefix")
    assert case.target == {
        "mode": "existing",
        "relative_path": "properties/demo/a_b_test.metis",
        "endpoint": "demo.a_b_test",
    }
    assert case.expected_selections == (
        {"catalog": "play-demo.video", "field": "tipologia", "literal": "Film"},
        {"catalog": "play-demo.video", "field": "mood", "literal": "Romantico"},
        {
            "catalog": "play-demo.video",
            "field": "protagonistaSesso",
            "literal": "Femmina",
        },
        {
            "catalog": "play-demo.video",
            "field": "protagonistaSpecie",
            "literal": "Umano",
        },
    )
    assert case.expected_surface == EXPECTED_SURFACE
    assert case.shape_contract == SHAPE_CONTRACT
    assert case.expected_shape_contract_sha256 == canonical_sha256(SHAPE_CONTRACT)
    assert case.request_sha256.startswith("sha256:")


def test_case_loader_rejects_non_create_or_existing_target(tmp_path: Path) -> None:
    raw = CASE.read_text(encoding="utf-8").replace('"mode": "existing"', '"mode": "update"')
    path = tmp_path / "case.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(BrainError, match="target mode is invalid"):
        live.load_latency_case(path)


def test_case_loader_rejects_invalid_expected_surface(tmp_path: Path) -> None:
    payload = json.loads(CASE.read_text(encoding="utf-8"))
    payload["expected_surface"]["order_direction"] = "sideways"
    path = tmp_path / "case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BrainError, match="surface|shape"):
        live.load_latency_case(path)


def test_case_loader_rejects_malformed_expected_surface_take(tmp_path: Path) -> None:
    payload = json.loads(CASE.read_text(encoding="utf-8"))
    payload["expected_surface"]["take"] = {"mode": "page", "value": 24}
    path = tmp_path / "case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BrainError, match="surface|shape"):
        live.load_latency_case(path)


def test_runtime_arm_is_explicit_and_warmup_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    class FakeRuntime:
        worker_sha256 = live.WORKER_SHA256
        model_revision = "model"
        adapter_sha256 = "adapter"
        prompt_prefix_sha256 = "prefix"
        model_loaded = True
        prefix_cache_ready = False
        warmup_prefix_tokens = 0

        def __init__(self, **kwargs: Any) -> None:
            self.prefix_cache_ready = kwargs["prefix_cache_enabled"]
            self.cache_mode = "prefix" if self.prefix_cache_ready else "disabled"
            self.warmup_prefix_tokens = 60 if self.prefix_cache_ready else 0
            calls.append(kwargs["prefix_cache_enabled"])

        def warmup(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(live, "MlxBrainModelRuntime", FakeRuntime)
    config = SimpleNamespace(
        model=SimpleNamespace(
            python_path=Path("/python"),
            model_path=Path("/model"),
            adapter_path=Path("/adapter"),
            timeout_seconds=1,
        )
    )

    direct = live._runtime(config, arm="direct")
    prefix = live._runtime(config, arm="prefix")

    assert direct.cache_mode == "disabled"
    assert prefix.cache_mode == "prefix"
    assert calls == [False, True]


def test_tenant_guard_rejects_unavailable_root_without_touching_a_tenant(tmp_path: Path) -> None:
    with pytest.raises(BrainError, match="tenant root is unavailable"):
        live.capture_tenant_guard(
            root=tmp_path / "does-not-exist",
            tenant_alias="play-demo",
            tenant_id="play-demo",
            target_path="properties/demo/new.metis",
        )


def test_output_provisioning_is_confined_to_the_fixed_ignored_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = (tmp_path / "model1").resolve()
    project.mkdir()
    root = project / "artifacts/metis-brain-latency"
    monkeypatch.setattr(live, "PROJECT_ROOT", project)
    monkeypatch.setattr(live, "LATENCY_OUTPUT_ROOT", root)
    target = root / "2026-09-01" / "receipt.json"

    live._provision_latency_output_parent(target)

    assert live.validate_latency_output_path(target) == target
    assert target.parent.is_dir()
    with pytest.raises(BrainError, match="outside authority"):
        live._provision_latency_output_parent(project / "outside.json")


def test_output_provisioning_rejects_a_symlinked_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = (tmp_path / "model1").resolve()
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "artifacts").symlink_to(outside, target_is_directory=True)
    root = project / "artifacts/metis-brain-latency"
    monkeypatch.setattr(live, "PROJECT_ROOT", project)
    monkeypatch.setattr(live, "LATENCY_OUTPUT_ROOT", root)

    with pytest.raises(BrainError, match="output root is invalid"):
        live._provision_latency_output_parent(root / "receipt.json")


@dataclass
class _Lease:
    snapshot: Any


class _Record:
    terminal = {"status": "completed", "outcome": "proposed"}
    events: list[dict[str, Any]] = []

    class _Condition:
        def __enter__(self) -> _Record._Condition:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def wait_for(self, predicate: Any, timeout: float) -> bool:
            del timeout
            return bool(predicate())

    condition = _Condition()


class _Manager:
    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context
        self.closed = False
        self.submitted: Any = None

    def create_session(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(session_id="session", token="token", context_revision="revision")

    @contextmanager
    def operation(self, **_kwargs: Any) -> Any:
        yield _Lease(SimpleNamespace(public_payload=lambda: self.context))

    def close(self, **_kwargs: Any) -> None:
        self.closed = True


def test_turn_orchestration_is_create_only_and_never_calls_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = live.LatencyCase(
        benchmark_id="offline",
        client_id="visix",
        tenant_alias="play-demo",
        instruction="crea un endpoint di prova",
        intent="create",
        target={
            "mode": "create",
            "relative_path": "properties/latency_probe.metis",
            "endpoint": "demo.latency_probe",
        },
        expected_selections=(
            {"catalog": "play-demo.video", "field": "mood", "literal": "Romantico"},
        ),
        case_sha256=canonical_sha256("case"),
        expected_surface=EXPECTED_SURFACE,
        pairs=6,
        arm_order=("direct", "prefix"),
        seed=17,
    )
    context = {
        "revision": "sha256:" + "1" * 64,
        "semantic_source_revision": "sha256:" + "2" * 64,
        "toolchain_binding": "sha256:" + "3" * 64,
        "files": [],
    }
    manager = _Manager(context)
    service = SimpleNamespace(app=SimpleNamespace(manager=manager, turns=SimpleNamespace()))
    submitted: list[Any] = []

    def submit(**kwargs: Any) -> _Record:
        submitted.append(kwargs["request"])
        return _Record()

    service.app.turns.submit = submit
    monkeypatch.setattr(
        live,
        "capture_tenant_guard",
        lambda **_kwargs: {
            "commit": "commit",
            "tree": "tree",
            "status_sha256": canonical_sha256("status"),
            "roster_sha256": canonical_sha256("roster"),
            "target_sha256": canonical_sha256("target"),
        },
    )
    monkeypatch.setattr(live, "observation_from_terminal", lambda **_kwargs: {"arm": "direct"})
    runtime = SimpleNamespace(
        model_revision="model",
        adapter_sha256="adapter",
        worker_sha256="worker",
        prompt_prefix_sha256="prefix",
    )

    observation, _context = live._turn(
        service=service,
        runtime=runtime,
        case=case,
        pair=1,
        arm="direct",
        tenant_id="play-demo",
        tenant_root=Path("/read-only/tenant"),
        timeout_seconds=1,
        ordinal=1,
    )

    assert observation == {"arm": "direct"}
    assert len(submitted) == 1
    assert submitted[0].target["mode"] == "create"
    assert manager.closed is True
    assert not hasattr(service.app, "apply")


def test_live_runner_uses_one_worker_two_decode_preflights_and_counterbalanced_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = (tmp_path / "model1").resolve()
    project.mkdir()
    output_root = project / "artifacts/metis-brain-latency"
    monkeypatch.setattr(live, "PROJECT_ROOT", project)
    monkeypatch.setattr(live, "LATENCY_OUTPUT_ROOT", output_root)
    tenant_root = tmp_path / "tenant"
    tenant_root.mkdir()
    model = BrainModelConfig(
        python_path=tmp_path / "python",
        model_path=tmp_path / "model",
        adapter_path=tmp_path / "adapter",
        timeout_seconds=30,
        warmup="on_start",
    )
    config = BrainConfig(
        host="127.0.0.1",
        port=0,
        runtime_root=tmp_path / "runtime",
        metis_git_root=tmp_path / "metis",
        node_path=tmp_path / "node",
        compiler_concurrency=1,
        tenant_grants=(("play-demo", "play-demo", tenant_root),),
        client_policies=(
            ClientPolicy(
                "visix",
                frozenset({"play-demo"}),
                live.BENCHMARK_CAPABILITIES,
            ),
        ),
        limits=SessionLimits(),
        model=model,
        retrieval=BrainRetrievalConfig(schema2=True, warmup="on_start"),
    )
    case = live.LatencyCase(
        benchmark_id="offline-runner",
        client_id="visix",
        tenant_alias="play-demo",
        instruction="modifica l'endpoint con 24 film romantici",
        intent="edit",
        target={
            "mode": "existing",
            "relative_path": "properties/demo/a_b_test.metis",
            "endpoint": "demo.a_b_test",
        },
        expected_selections=(
            {"catalog": "play-demo.video", "field": "mood", "literal": "Romantico"},
        ),
        case_sha256=canonical_sha256("case"),
        expected_surface=EXPECTED_SURFACE,
        pairs=6,
        arm_order=("direct", "prefix"),
        seed=17,
    )
    guard = {
        "commit": "a" * 40,
        "tree": "b" * 40,
        "status_sha256": canonical_sha256("status"),
        "roster_sha256": canonical_sha256("roster"),
        "target_sha256": canonical_sha256("target"),
    }
    context = {
        "revision": canonical_sha256("context"),
        "semantic_source_revision": canonical_sha256("semantic"),
        "toolchain_binding": canonical_sha256("toolchain"),
    }
    source_sha256 = canonical_sha256("source")
    event_roster_sha256 = canonical_sha256("events")
    intent_compiler_sha256 = canonical_sha256({"processing_route": "direct", "identity": None})
    model1_guard = {
        "commit": "c" * 40,
        "tree": "d" * 40,
    }
    mode_calls: list[str] = []
    turn_calls: list[tuple[int, str, int]] = []
    service_calls: list[str] = []

    class FakeRuntime:
        model_loaded = True
        model_revision = "qualified-model"
        adapter_sha256 = canonical_sha256("adapter")
        worker_sha256 = live.WORKER_SHA256
        prompt_prefix_sha256 = canonical_sha256("prefix")
        warmup_prefix_tokens = 60

        def _set_cache_mode_for_qualification(self, mode: str) -> None:
            mode_calls.append(mode)

        def close(self) -> None:
            self.model_loaded = False

    runtime = FakeRuntime()

    class FakeService:
        def __init__(self, supplied_config: BrainConfig, *, model: Any) -> None:
            assert supplied_config.model is not None
            assert supplied_config.model.warmup == "lazy"
            assert model is runtime
            self.app = SimpleNamespace(
                health=lambda: {
                    "semantic_retrieval": {
                        "warmup": {
                            "policy": "on_start",
                            "status": "ready",
                            "duration_ms": 123,
                            "tenant_count": 1,
                        }
                    }
                }
            )
            service_calls.append("constructed")

        def __enter__(self) -> FakeService:
            service_calls.append("entered")
            return self

        def __exit__(self, *_args: Any) -> None:
            service_calls.append("closed")

    def fake_turn(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        turn_calls.append((kwargs["pair"], kwargs["arm"], kwargs["ordinal"]))
        return (
            {
                "pair": kwargs["pair"],
                "arm": kwargs["arm"],
                "ordinal": kwargs["ordinal"],
                "source_sha256": source_sha256,
                "compiled_endpoint_sha256": canonical_sha256("compiled"),
                "shape_contract_sha256": case.expected_shape_contract_sha256,
                "grounding_selections_sha256": case.expected_grounding_sha256,
                "event_roster_sha256": event_roster_sha256,
                "processing_route": "direct",
                "intent_compiler_sha256": intent_compiler_sha256,
                "model_revision": runtime.model_revision,
                "adapter_sha256": runtime.adapter_sha256,
                "worker_sha256": runtime.worker_sha256,
                "prompt_prefix_sha256": runtime.prompt_prefix_sha256,
                "request_sha256": case.request_sha256,
            },
            dict(context),
        )

    def fake_seal(
        *, identity: dict[str, Any], observations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        assert identity["retrieval_prewarm_ms"] == 123
        assert identity["decode_preflight_count"] == 2
        assert [item["arm"] for item in identity["decode_preflights"]] == [
            "direct",
            "prefix",
        ]
        assert identity["decode_preflight_sha256"] == canonical_sha256(
            identity["decode_preflights"]
        )
        assert identity["decode_preflight_source_sha256"] == source_sha256
        assert identity["decode_preflight_compiled_endpoint_sha256"].startswith("sha256:")
        assert identity["expected_shape_contract_sha256"] == case.expected_shape_contract_sha256
        assert identity["expected_processing_route"] == "direct"
        assert identity["expected_intent_compiler_sha256"] == intent_compiler_sha256
        assert "expected_compiled_endpoint_sha256" not in identity
        assert len(observations) == 12
        return {
            "schema_version": 1,
            "status": "MEASURED_NOT_PROMOTED",
            "identity": identity,
            "observations": observations,
        }

    class FakeReceiptHandle:
        def __init__(self, path: Path) -> None:
            self.path = path

        def commit(self) -> None:
            return None

        def discard(self) -> None:
            self.path.unlink(missing_ok=True)

    def fake_write(path: Path, _receipt: dict[str, Any], **_kwargs: Any) -> FakeReceiptHandle:
        path.write_text("sealed\n", encoding="utf-8")
        return FakeReceiptHandle(path)

    monkeypatch.setattr(live, "load_brain_config", lambda _path: config)
    monkeypatch.setattr(live, "load_latency_case", lambda _path: case)
    monkeypatch.setattr(live, "capture_tenant_guard", lambda **_kwargs: dict(guard))
    monkeypatch.setattr(live, "capture_model1_guard", lambda: dict(model1_guard))
    monkeypatch.setattr(live, "_runtime", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(live, "MetisBrainService", FakeService)
    monkeypatch.setattr(live, "_turn", fake_turn)
    monkeypatch.setattr(live, "seal_latency_receipt", fake_seal)
    monkeypatch.setattr(live, "write_latency_receipt", fake_write)
    output = output_root / "2026-09-01" / "receipt.json"

    receipt = live.run_latency_benchmark(
        config_path=tmp_path / "config.json",
        case_path=tmp_path / "case.json",
        output_path=output,
    )

    assert receipt["status"] == "MEASURED_NOT_PROMOTED"
    assert output.read_text(encoding="utf-8") == "sealed\n"
    assert service_calls == ["constructed", "entered", "closed"]
    assert turn_calls[:2] == [(1, "direct", 1), (1, "prefix", 2)]
    assert turn_calls[2:] == [
        (1, "direct", 1),
        (1, "prefix", 2),
        (2, "prefix", 3),
        (2, "direct", 4),
        (3, "direct", 5),
        (3, "prefix", 6),
        (4, "prefix", 7),
        (4, "direct", 8),
        (5, "direct", 9),
        (5, "prefix", 10),
        (6, "prefix", 11),
        (6, "direct", 12),
    ]
    assert mode_calls == ["disabled", "prefix"] + [
        "prefix" if item[1] == "prefix" else "disabled" for item in turn_calls[2:]
    ]
    assert runtime.model_loaded is False

    runtime.model_loaded = True
    guard_calls = 0

    def failing_post_write_guard(**_kwargs: Any) -> dict[str, str]:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 3:
            raise BrainError("BENCHMARK_INVALID", 409, "synthetic post-write drift")
        return dict(guard)

    monkeypatch.setattr(live, "capture_tenant_guard", failing_post_write_guard)
    failed_output = output_root / "2026-09-01" / "failed-receipt.json"
    with pytest.raises(BrainError, match="post-write drift"):
        live.run_latency_benchmark(
            config_path=tmp_path / "config.json",
            case_path=tmp_path / "case.json",
            output_path=failed_output,
        )
    assert not failed_output.exists()
