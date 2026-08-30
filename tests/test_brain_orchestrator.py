from __future__ import annotations

import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from metis_model1.brain_model_runtime import ModelCandidate
from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_protocol import BrainError
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_turns import TurnRecord, TurnRequest


def _request(context: str, semantic: str, clarification=None) -> TurnRequest:
    return TurnRequest(
        1,
        "123e4567-e89b-12d3-a456-426614174000",
        context,
        semantic,
        "create",
        "crea un endpoint",
        {
            "mode": "create",
            "relative_path": "candidate.metis",
            "endpoint": None,
            "base_sha256": None,
        },
        None,
        clarification,
    )


def test_catalog_selection_requires_explicit_revision_bound_option() -> None:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    candidates = (
        {"catalog": "video", "label": "Video", "option_ref": "option-video"},
        {"catalog": "trending", "label": "Tendenze", "option_ref": "option-trending"},
    )
    retrieved = RetrievalResult({}, {}, semantic, candidates)
    request = _request(context, semantic)
    assert BrainOrchestrator._selected_catalog(request, retrieved) is None
    response = {
        "clarification_id": "clarification-123456789012345678901234",
        "option_ref": "option-video",
        "context_revision": context,
        "semantic_source_revision": semantic,
    }
    assert (
        BrainOrchestrator._selected_catalog(_request(context, semantic, response), retrieved)
        == candidates[0]
    )


def test_stale_semantic_revision_fails_closed() -> None:
    context = "sha256:" + "a" * 64
    request = _request(context, "sha256:" + "b" * 64)
    retrieved = RetrievalResult({}, {}, "sha256:" + "c" * 64)
    with pytest.raises(BrainError) as raised:
        BrainOrchestrator._check_semantic_revision(request, retrieved)
    assert raised.value.code == "SEMANTIC_SOURCE_STALE"


class _FakeManager:
    def __init__(self, lease: object) -> None:
        self.lease = lease

    @contextmanager
    def operation(self, **_kwargs: object):
        yield self.lease


class _SequenceModel:
    model_revision = "model-test"
    adapter_sha256 = "adapter-test"

    def __init__(self, sources: list[str]) -> None:
        self.sources = iter(sources)
        self.requests = []

    def generate(self, request: object) -> ModelCandidate:
        self.requests.append(request)
        return ModelCandidate(next(self.sources), self.model_revision, self.adapter_sha256)


class _CountingCompiler:
    toolchain_binding = "sha256:" + "a" * 64

    def __init__(self, status: str = "ok") -> None:
        self.calls = 0
        self.status = status

    def compile(self, **_kwargs: object) -> dict[str, object]:
        self.calls += 1
        return {"status": self.status, "toolchain_binding": self.toolchain_binding}


def _grounded_retrieval(context: str, semantic: str) -> RetrievalResult:
    return RetrievalResult(
        context={},
        grounding={
            "status": "resolved",
            "catalogs": ["play-demo.video"],
            "selections": [
                {
                    "catalog": "play-demo.video",
                    "field": "paesiorigine",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "enum", "size": 2, "nature": "editorial"},
                    "literal": None,
                    "literals": ["ITALIA", "italia"],
                    "value_mode": "any_of",
                }
            ],
            "candidates": [],
            "unresolved": [],
        },
        semantic_source_revision=semantic,
        catalog_candidates=({"catalog": "play-demo.video"},),
    )


def _run_with_model(
    model: _SequenceModel, compiler: _CountingCompiler, *, max_repairs: int
) -> dict:
    context = "sha256:" + "a" * 64
    semantic = "sha256:" + "b" * 64
    request = _request(context, semantic)
    record = TurnRecord("turn-test", "session-test", request, request.payload_hash)
    lease = SimpleNamespace(
        snapshot=SimpleNamespace(source_map=lambda: {}),
        cancellation=threading.Event(),
    )
    return BrainOrchestrator(
        retriever=SimpleNamespace(
            retrieve=lambda **_kwargs: _grounded_retrieval(context, semantic)
        ),
        model=model,
        compiler=compiler,
        max_repairs=max_repairs,
    ).run(
        manager=_FakeManager(lease),
        session_id="session-test",
        token="token-test",
        request=request,
        record=record,
    )


def test_grounding_repair_converges_before_compile() -> None:
    model = _SequenceModel(
        [
            '@paesiorigine is "italia"',
            '@paesiorigine in ["ITALIA", "italia"]',
        ]
    )
    compiler = _CountingCompiler()
    result = _run_with_model(model, compiler, max_repairs=1)
    assert result["outcome"] == "proposed"
    assert result["claims"]["compile_clean"] is True
    assert compiler.calls == 1
    assert len(model.requests) == 2
    assert model.requests[1].diagnostics[0]["code"] == "CANDIDATE_GROUNDING_MISMATCH"


def test_terminal_grounding_mismatch_fails_closed_without_compile() -> None:
    model = _SequenceModel(['@paesiorigine is "italia"', '@paesiorigine is "italia"'])
    compiler = _CountingCompiler()
    with pytest.raises(BrainError) as raised:
        _run_with_model(model, compiler, max_repairs=1)
    assert raised.value.code == "CANDIDATE_GROUNDING_MISMATCH"
    assert compiler.calls == 0


@pytest.mark.parametrize("max_repairs", [0, 1])
def test_invalid_compiler_receipt_never_produces_proposal(max_repairs: int) -> None:
    model = _SequenceModel(['@paesiorigine in ["ITALIA", "italia"]'] * (max_repairs + 1))
    compiler = _CountingCompiler(status="invalid")
    with pytest.raises(BrainError) as raised:
        _run_with_model(model, compiler, max_repairs=max_repairs)
    assert raised.value.code == "COMPILER_REJECTED"
    assert compiler.calls == max_repairs + 1
