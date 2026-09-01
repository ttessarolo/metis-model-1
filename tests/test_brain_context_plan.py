from __future__ import annotations

import pytest

from metis_model1 import brain_context_plan as plans
from metis_model1 import brain_mlx_runtime as runtime_reference


def test_plans_are_monotone_prefixes_of_the_exact_runtime_projection() -> None:
    projection = runtime_reference._pinned_runtime_reference()
    minimal = plans.build_context_plan()
    endpoint = minimal.expand(host_signal="host-needs-endpoint-surface")
    stdlib = endpoint.expand(host_signal="host-needs-stdlib")

    assert minimal.level is plans.ContextLevel.MINIMAL
    assert endpoint.level is plans.ContextLevel.ENDPOINT
    assert stdlib.level is plans.ContextLevel.STDLIB
    assert minimal.reference_sha256 == f"sha256:{runtime_reference.REFERENCE_SHA256}"
    assert minimal.byte_count < endpoint.byte_count < stdlib.byte_count
    assert projection.startswith(minimal.text)
    assert projection.startswith(endpoint.text)
    assert stdlib.text == projection
    assert stdlib.byte_count == len(projection.encode("utf-8"))


def test_host_selectors_choose_smallest_monotone_level() -> None:
    assert plans.build_context_plan().level is plans.ContextLevel.MINIMAL
    assert (
        plans.build_context_plan(needs_endpoint_surface=True).level is plans.ContextLevel.ENDPOINT
    )
    assert plans.build_context_plan(needs_stdlib=True).level is plans.ContextLevel.STDLIB
    assert (
        plans.build_context_plan(needs_endpoint_surface=True, needs_stdlib=True).level
        is plans.ContextLevel.STDLIB
    )
    with pytest.raises(plans.ContextPlanError, match="booleans"):
        plans.build_context_plan(needs_stdlib="yes")  # type: ignore[arg-type]


def test_model_or_arbitrary_expansion_and_nonmonotone_jump_are_rejected() -> None:
    minimal = plans.build_context_plan()
    with pytest.raises(plans.ContextPlanError):
        minimal.expand(host_signal="model-requested-full-reference")
    with pytest.raises(plans.ContextPlanError):
        minimal.expand(host_signal="host-needs-stdlib")
    with pytest.raises(plans.ContextPlanError):
        plans.build_context_plan(needs_endpoint_surface=1)  # type: ignore[arg-type]


def test_v3_hash_drift_fails_closed_through_the_runtime_authority(monkeypatch, tmp_path) -> None:
    altered = tmp_path / "t30-reference-context.md"
    altered.write_bytes(runtime_reference.REFERENCE_PATH.read_bytes() + b"\nattacker section\n")
    monkeypatch.setattr(runtime_reference, "REFERENCE_PATH", altered)
    with pytest.raises(plans.ContextPlanError, match="unavailable or differs"):
        plans.build_context_plan()


def test_missing_or_reordered_runtime_section_fails_closed(monkeypatch) -> None:
    projection = runtime_reference._pinned_runtime_reference()
    monkeypatch.setattr(
        runtime_reference,
        "_pinned_runtime_reference",
        lambda: projection.replace("### Blocks and variants\n", "", 1),
    )
    with pytest.raises(plans.ContextPlanError, match="projection is invalid"):
        plans.build_context_plan()


def test_wire_payload_is_bounded_and_carries_exact_runtime_hash() -> None:
    payload = plans.context_plan_payload(plans.build_context_plan(needs_endpoint_surface=True))
    assert set(payload) == {
        "schema_version",
        "level",
        "reference_sha256",
        "sections",
        "text",
        "byte_count",
    }
    assert payload["schema_version"] == 1
    assert payload["reference_sha256"] == f"sha256:{runtime_reference.REFERENCE_SHA256}"
    assert payload["byte_count"] == len(payload["text"].encode("utf-8"))
