from __future__ import annotations

import pytest

from metis_model1.brain_orchestrator import BrainOrchestrator
from metis_model1.brain_protocol import BrainError
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_turns import TurnRequest


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
