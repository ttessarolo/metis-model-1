from __future__ import annotations

from dataclasses import replace

import pytest

from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    FragmentLeafBinding,
    NodeGrant,
    RequirementHandle,
    SlotGrant,
    compact_authority_projection_revision,
)
from metis_model1.brain_model_runtime import (
    CreatePlanV2Candidate,
    CreatePlanV2Request,
    StaticModelRuntime,
    UnavailableModelRuntime,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

CONTEXT = "sha256:" + "a" * 64
SEMANTIC = "sha256:" + "b" * 64
SURFACE = "sha256:" + "c" * 64
REQUIREMENT = "hostref:requirement"
SLOT = "hostref:slot"
NODE = "hostref:node"


def _projection() -> CompactAuthorityProjection:
    requirement = RequirementHandle(0, REQUIREMENT, "ventiquattro risultati", frozenset({"attach"}))
    slot = SlotGrant(
        handle=10,
        ref=SLOT,
        label="risultati endpoint",
        anchor_ref="hostref:anchor",
        member="output",
        cardinality="many",
        accepts=("value",),
        mutations=frozenset({"attach"}),
        insertion="append",
        basis_spec_sha256=None,
        generation=0,
    )
    fragment = {"kind": "lit", "lexical": "number", "value": 24}
    node = NodeGrant(
        handle=20,
        ref=NODE,
        label="quantita richiesta",
        state="new",
        fragment_type="value",
        fragment=fragment,
        fragment_sha256=bytes_sha256(canonical_json(fragment)),
        leaf_bindings=(
            FragmentLeafBinding("/kind", "hostref:evidence", (REQUIREMENT,), "operator"),
            FragmentLeafBinding("/lexical", "hostref:evidence", (REQUIREMENT,), "operator"),
            FragmentLeafBinding("/value", "hostref:evidence", (REQUIREMENT,), "operator"),
        ),
        basis_spec_sha256=None,
        basis_path=None,
        parent_slot_ref=SLOT,
        removable=False,
    )
    requirements = (requirement,)
    authorities = (slot, node)
    revision = compact_authority_projection_revision(
        surface_revision=SURFACE,
        requirements=requirements,
        authorities=authorities,
    )
    return CompactAuthorityProjection(revision, SURFACE, requirements, authorities)


def _request(**changes: object) -> CreatePlanV2Request:
    values: dict[str, object] = {
        "instructions": ("Crea un endpoint con ventiquattro risultati.",),
        "generation": 0,
        "context_revision": CONTEXT,
        "semantic_revision": SEMANTIC,
        "active_requirement_handles": (0,),
        "authority_projection": _projection(),
    }
    values.update(changes)
    return CreatePlanV2Request(**values)  # type: ignore[arg-type]


def _body() -> dict[str, object]:
    return {"o": [{"k": "a", "q": [0], "s": 10, "n": 20}]}


def test_v2_request_validates_active_handles_and_defensively_copies_projection() -> None:
    projection = _projection()
    request = _request(authority_projection=projection)
    fragment = projection.authorities[1].fragment
    assert isinstance(fragment, dict)
    fragment["value"] = 99
    copied = request.authority_projection.authorities[1].fragment
    assert isinstance(copied, dict) and copied["value"] == 24

    with pytest.raises(BrainError) as raised:
        _request(active_requirement_handles=(1,))
    assert raised.value.code == "MODEL_INPUT_INVALID"

    with pytest.raises(BrainError) as raised:
        _request(active_requirement_handles=(0, 0))
    assert raised.value.code == "MODEL_INPUT_INVALID"


def test_v2_request_rejects_invalid_private_projection_before_serialization() -> None:
    projection = _projection()
    bad = replace(projection, projection_revision="sha256:" + "f" * 64)
    with pytest.raises(BrainError) as raised:
        _request(authority_projection=bad)
    assert raised.value.code == "MODEL_INPUT_INVALID"


def test_v2_candidate_is_authoritatively_schema_validated_and_copied() -> None:
    body = _body()
    candidate = CreatePlanV2Candidate(body)
    body["o"].append({"k": "hidden"})  # type: ignore[union-attr]
    assert candidate.body == _body()
    assert candidate.generator == "model_create_plan_v2"

    for invalid in (
        {"o": []},
        {"o": [{"k": "a", "q": [0, 0], "s": 10, "n": 20}]},
        {"o": [{"k": "a", "q": [0], "s": 10, "n": 20, "extra": True}]},
    ):
        with pytest.raises(BrainError) as raised:
            CreatePlanV2Candidate(invalid)
        assert raised.value.code == "MODEL_INVALID"


def test_static_and_unavailable_v2_planners_are_explicit_without_changing_v1() -> None:
    request = _request()
    static = StaticModelRuntime("metis 0.43\n", create_plan_v2=_body())
    assert static.plan_create_v2(request).body == _body()

    for runtime in (StaticModelRuntime("metis 0.43\n"), UnavailableModelRuntime()):
        with pytest.raises(BrainError) as raised:
            runtime.plan_create_v2(request)
        assert raised.value.code == "MODEL_UNAVAILABLE"
