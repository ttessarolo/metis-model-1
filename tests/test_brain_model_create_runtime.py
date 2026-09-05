from __future__ import annotations

import math

import pytest

from metis_model1.brain_model_runtime import (
    CreatePlanCandidate,
    CreatePlanRequest,
    StaticModelRuntime,
    UnavailableModelRuntime,
)
from metis_model1.brain_protocol import BrainError

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
TARGET = "hostref:target:" + "d" * 32
BASIS = "hostref:basis:" + "e" * 32
REQUIREMENT = "hostref:requirement:" + "f" * 32
ENDPOINT = "hostref:endpoint:" + "1" * 32


def _request(**changes: object) -> CreatePlanRequest:
    values: dict[str, object] = {
        "instructions": ("crea una riga",),
        "generation": 0,
        "context_revision": SHA_A,
        "semantic_revision": SHA_B,
        "surface_revision": SHA_C,
        "target_ref": TARGET,
        "basis_ref": None,
        "requirement_refs": (REQUIREMENT,),
        "authority_surface": {
            "schema_version": 1,
            "grants": [{"ref": TARGET, "roles": ["target"], "label": "nuovo endpoint"}],
        },
    }
    values.update(changes)
    return CreatePlanRequest(**values)  # type: ignore[arg-type]


def _plan() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": "metis-brain-create-delta-plan/v1",
        "mode": "initial",
        "context_revision": SHA_A,
        "semantic_revision": SHA_B,
        "surface_revision": SHA_C,
        "target_ref": TARGET,
        "basis_ref": None,
        "requirements": [REQUIREMENT],
        "operations": [
            {
                "ordinal": 0,
                "kind": "endpoint.create",
                "depends_on": [],
                "requirement_refs": [REQUIREMENT],
                "endpoint_ref": ENDPOINT,
            }
        ],
    }


def test_create_plan_request_is_bounded_and_copies_the_safe_surface() -> None:
    surface = {"grants": [{"ref": TARGET, "roles": ["target"], "label": "endpoint"}]}
    request = _request(authority_surface=surface)
    surface["grants"][0]["label"] = "mutated"
    assert request.authority_surface["grants"][0]["label"] == "endpoint"


def test_refinement_generation_requires_a_basis_and_complete_history() -> None:
    request = _request(
        instructions=("crea una riga", "aggiungi il fallback"),
        generation=1,
        basis_ref=BASIS,
    )
    assert request.generation == 1
    assert request.basis_ref == BASIS

    for changes in (
        {"generation": 1},
        {"basis_ref": BASIS},
    ):
        with pytest.raises(BrainError) as raised:
            _request(**changes)
        assert raised.value.code == "MODEL_INPUT_INVALID"

    # A typed clarification can add messages before the first proposal; the
    # generation is a Draft-head generation, not a message ordinal.
    initial_after_clarification = _request(
        instructions=("crea una riga", "usa video e dammi 24 risultati"),
        generation=0,
        basis_ref=None,
    )
    assert initial_after_clarification.generation == 0


@pytest.mark.parametrize(
    "forbidden",
    [
        {"source": "metis 0.43"},
        {"nested": {"path": "/private/tenant"}},
        {"grants": [{"endpoint-template": "hidden"}]},
        {"reference_endpoint": "play.hidden"},
    ],
)
def test_create_model_surface_cannot_carry_golden_source_or_paths(
    forbidden: dict[str, object],
) -> None:
    with pytest.raises(BrainError) as raised:
        _request(authority_surface=forbidden)
    assert raised.value.code == "MODEL_INPUT_INVALID"


def test_create_candidate_copies_plan_and_reuses_qualified_metrics_contract() -> None:
    plan = _plan()
    metrics = {
        "worker_load_ms": 0,
        "generation_ms": 5,
        "prompt_tokens": 10,
        "generation_tokens": 2,
        "cached_tokens": 0,
        "prompt_tps": 100.0,
        "generation_tps": 100.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }
    candidate = CreatePlanCandidate(plan, metrics=metrics)
    plan["operations"].append({"kind": "hidden"})  # type: ignore[union-attr]
    metrics["peak_metal_gb"] = math.nan
    assert len(candidate.plan["operations"]) == 1
    assert candidate.metrics["peak_metal_gb"] == 1.0


def test_create_candidate_rejects_a_non_schema_plan_before_admission() -> None:
    with pytest.raises(BrainError) as raised:
        CreatePlanCandidate({"schema_version": 1, "operations": []})
    assert raised.value.code == "MODEL_INVALID"


def test_static_and_unavailable_create_planners_are_explicit() -> None:
    request = _request()
    plan = _plan()
    static = StaticModelRuntime("metis 0.43\n", create_plan=plan)
    assert static.plan_create(request).plan == plan

    for runtime in (StaticModelRuntime("metis 0.43\n"), UnavailableModelRuntime()):
        with pytest.raises(BrainError) as raised:
            runtime.plan_create(request)
        assert raised.value.code == "MODEL_UNAVAILABLE"
