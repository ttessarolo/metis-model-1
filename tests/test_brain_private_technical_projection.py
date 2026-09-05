"""Model-request privacy checks for the technical descriptor sidecar."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from test_brain_orchestrator import (
    _CountingCompiler,
    _FakeManager,
    _grounded_retrieval,
    _request,
    _SequenceModel,
)

from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_protocol import BrainError
from metis_model1.brain_turns import TurnRecord

_CONTEXT_REVISION = "sha256:" + "a" * 64
_SEMANTIC_REVISION = "sha256:" + "b" * 64
_SESSION_ID = "s" * 32
_TURN_ID = "t" * 24
_PRIVATE_CONTEXT = {
    "technical_authority": {"private": "runner-attested-technical-sidecar"},
    "catalog_reference_roster": ["play-demo.video", "play-demo.archive"],
}


def _run(model: _SequenceModel, compiler: _CountingCompiler, *, max_repairs: int) -> None:
    request = _request(_CONTEXT_REVISION, _SEMANTIC_REVISION)
    record = TurnRecord(_TURN_ID, _SESSION_ID, request, request.payload_hash)
    retrieved = _grounded_retrieval(_CONTEXT_REVISION, _SEMANTIC_REVISION)
    retrieved.context.update(_PRIVATE_CONTEXT)
    lease = SimpleNamespace(
        snapshot=SimpleNamespace(source_map=lambda: {}),
        cancellation=threading.Event(),
    )
    BrainOrchestrator(
        retriever=SimpleNamespace(retrieve=lambda **_kwargs: retrieved),
        model=model,
        compiler=compiler,
        max_repairs=max_repairs,
    ).run(
        manager=_FakeManager(lease),
        session_id=_SESSION_ID,
        token="token-test",
        request=request,
        record=record,
    )


def _assert_private_context_is_never_projected(model: _SequenceModel) -> None:
    assert len(model.requests) == 2
    for request in model.requests:
        assert "technical_authority" not in request.context
        assert "catalog_reference_roster" not in request.context
    assert model.requests[0].previous_source is None
    assert model.requests[1].previous_source is not None


def test_model_source_and_grounding_repair_hide_private_technical_context() -> None:
    model = _SequenceModel(
        [
            '@paesiorigine is "italia"',
            '@paesiorigine in ["ITALIA", "italia"]',
        ]
    )

    _run(model, _CountingCompiler(), max_repairs=1)

    _assert_private_context_is_never_projected(model)
    assert model.requests[1].diagnostics[0]["code"] == "CANDIDATE_GROUNDING_MISMATCH"


def test_model_source_and_compiler_repair_hide_private_technical_context() -> None:
    model = _SequenceModel(
        [
            '@paesiorigine in ["ITALIA", "italia"]',
            '@paesiorigine in ["ITALIA", "italia"]',
        ]
    )

    with pytest.raises(BrainError) as raised:
        _run(model, _CountingCompiler(status="invalid"), max_repairs=1)

    assert raised.value.code == "COMPILER_REJECTED"
    _assert_private_context_is_never_projected(model)
    assert model.requests[1].diagnostics == ()
