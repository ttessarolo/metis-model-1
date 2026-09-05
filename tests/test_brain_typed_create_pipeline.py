"""Adversarial gate for the one-pass private typed CREATE v2 pipeline."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from typing import Any

import pytest

from metis_model1.brain_context import ContextSnapshot, SnapshotFile
from metis_model1.brain_create_ir import create_ir_stage_proof
from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    FragmentLeafBinding,
    NodeGrant,
    RequirementHandle,
    SlotGrant,
    compact_authority_projection_revision,
    initial_create_endpoint_skeleton,
)
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_model_runtime import CreatePlanV2Candidate, ModelCandidate
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json, canonical_sha256
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_tools import CandidateCompileResult
from metis_model1.brain_typed_create_pipeline import (
    TYPED_CREATE_PIPELINE_V2_CONTRACT,
    TypedCreateV2RequestBinding,
    run_typed_create_pipeline_v2,
)

CONTEXT = bytes_sha256(b"typed-create-context")
SNAPSHOT_RAW = b"[tenant]\nid = 'typed-create'\n"
SNAPSHOT_RAW_SHA256 = bytes_sha256(SNAPSHOT_RAW)
SEMANTIC = canonical_sha256(
    {
        "schema_version": 1,
        "context_revision": CONTEXT,
        "files": [],
    }
)
SURFACE = bytes_sha256(b"typed-create-surface")
TOOLCHAIN = bytes_sha256(b"typed-create-toolchain")
TARGET = "hostref:typed-create-target"
BASIS = "hostref:typed-create-basis"
REQUIREMENT = "hostref:typed-create-requirement"
EVIDENCE = "hostref:typed-create-evidence"
SLOT = "hostref:typed-create-needs-time-slot"
NODE = "hostref:typed-create-needs-time-value"
ENDPOINT = "demo.typed_create"
FILENAME = "endpoints/demo.typed-create.metis"
PRIVATE_SENTINEL = "REFERENCE_GOLDEN_SOURCE_PATH_SENTINEL"


def _metrics(*, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "worker_load_ms": 1,
        "generation_ms": 2,
        "prompt_tokens": 20,
        "generation_tokens": 7,
        "cached_tokens": 0,
        "prompt_tps": 100.0,
        "generation_tps": 100.0,
        "finish_reason": finish_reason,
        "peak_metal_gb": 1.0,
    }


def _history(*messages: str) -> tuple[CreateAuthorityHistoryMessage, ...]:
    return tuple(
        CreateAuthorityHistoryMessage(index, message, bytes_sha256(message.encode("utf-8")))
        for index, message in enumerate(messages)
    )


def _binding(*, history: tuple[CreateAuthorityHistoryMessage, ...] | None = None):
    messages = history or _history("Crea un endpoint che richiede il tempo corrente.")
    return TypedCreateV2RequestBinding(
        history=messages,
        history_revision=create_authority_history_revision(messages),
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        candidate_filename=FILENAME,
        endpoint=ENDPOINT,
    )


def _projection(*, generation: int = 0) -> CompactAuthorityProjection:
    requirement = RequirementHandle(
        0,
        REQUIREMENT,
        "The endpoint requires current time",
        frozenset({"set"}),
    )
    slot = SlotGrant(
        10,
        SLOT,
        "current time requirement",
        TARGET,
        "needs_time",
        "one",
        ("boolean",),
        frozenset({"set"}),
        "replace",
        None,
        generation,
    )
    value = NodeGrant(
        20,
        NODE,
        "enable current time",
        "new",
        "boolean",
        True,
        bytes_sha256(canonical_json(True)),
        (
            FragmentLeafBinding(
                "",
                EVIDENCE + ":" + PRIVATE_SENTINEL,
                (REQUIREMENT,),
                "operator",
            ),
        ),
        None,
        None,
        SLOT,
        False,
    )
    authorities = (slot, value)
    return CompactAuthorityProjection(
        compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=(requirement,),
            authorities=authorities,
        ),
        SURFACE,
        (requirement,),
        authorities,
    )


def _body() -> dict[str, Any]:
    return {"o": [{"k": "s", "q": [0], "s": 10, "v": 20}]}


def _snapshot() -> ContextSnapshot:
    record = SnapshotFile("metis.toml", SNAPSHOT_RAW, SNAPSHOT_RAW_SHA256)
    return ContextSnapshot(
        tenant_alias="demo",
        tenant_id="typed-create",
        root_device=1,
        root_inode=2,
        revision=CONTEXT,
        toolchain_binding=TOOLCHAIN,
        files=(record,),
        total_bytes=len(SNAPSHOT_RAW),
    )


def _lease() -> OperationLease:
    return OperationLease(
        session_id="s" * 43,
        client_id="visix",
        tenant_alias="demo",
        capabilities=frozenset({"chat.turn", "compile"}),
        snapshot=_snapshot(),
        cancellation=threading.Event(),
    )


class _Model:
    model_loaded = True

    def __init__(self, *, body: Any = None, finish_reason: str = "stop") -> None:
        self.model_revision = "Qwen3.8-27B-test"
        self.adapter_sha256 = bytes_sha256(b"adapter")
        self.body = _body() if body is None else body
        self.finish_reason = finish_reason
        self.plan_calls = 0
        self.v1_plan_calls = 0
        self.generate_calls = 0
        self.safe_payloads: list[dict[str, Any]] = []
        self.mutate_request = False
        self.drift_identity = False
        self.on_plan: Any = None

    def plan_create_v2(self, request: Any) -> Any:
        self.plan_calls += 1
        payload = request.authority_projection.model_projection_payload()
        self.safe_payloads.append(
            {
                "projection": payload,
                "decoder_constraint": request.decoder_constraint.payload(),
            }
        )
        if self.on_plan is not None:
            self.on_plan()
        if self.mutate_request:
            fragment = request.authority_projection.authorities[1].fragment
            assert fragment is True
            object.__setattr__(request.authority_projection.authorities[1], "fragment", False)
        candidate = CreatePlanV2Candidate(
            self.body,
            self.model_revision,
            self.adapter_sha256,
            metrics=_metrics(finish_reason=self.finish_reason),
        )
        if self.drift_identity:
            self.model_revision = "Qwen3.8-27B-drifted"
        return candidate

    def plan_create(self, _request: Any) -> None:
        self.v1_plan_calls += 1
        raise AssertionError("whole-plan v1 path must not run")

    def generate(self, _request: Any) -> None:
        self.generate_calls += 1
        raise AssertionError("whole-source generation/repair must not run")


def _manifest(endpoint: str, endpoint_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "endpoint": endpoint,
        "endpoint_sha256": endpoint_sha256,
        "containers": [{"path": "endpoint", "kind": "endpoint"}],
        "fetches": [],
    }


class _Compiler:
    def __init__(self) -> None:
        self.toolchain_binding = TOOLCHAIN
        self.calls = 0
        self.sources: list[str] = []
        self.mode = "ok"

    def compile_candidate(self, **kwargs: Any) -> CandidateCompileResult:
        self.calls += 1
        source = kwargs["source"]
        endpoint = kwargs["endpoint"]
        lease = kwargs["lease"]
        self.sources.append(source)
        if self.mode == "partial":
            return CandidateCompileResult({}, None, None, None, None)
        endpoint_sha256 = canonical_sha256({"endpoint": endpoint, "source": source})
        manifest = _manifest(endpoint, endpoint_sha256)
        ir = {
            "node": "Endpoint",
            "name": endpoint,
            "irVersion": "0.43",
            "needsTime": True,
        }
        compiler = {
            "schema_version": 1,
            "operation": "compile",
            "status": "ok",
            "diagnostics": [],
            "endpoint": endpoint,
            "endpoint_sha256": endpoint_sha256,
            "runtime_context_sha256": bytes_sha256(b"runtime-context"),
        }
        candidate = {
            "filename": kwargs["filename"],
            "execution_mode": "endpoint",
            "endpoint": endpoint,
            "source_sha256": canonical_sha256(source),
            "context_revision": lease.snapshot.revision,
        }
        receipt_body = {
            "schema_version": 1,
            "status": "ok",
            "session_id": lease.session_id,
            "tenant_alias": lease.tenant_alias,
            "context_revision": lease.snapshot.revision,
            "toolchain_binding": self.toolchain_binding,
            "candidate": candidate,
            "compiler": compiler,
            "claims": {
                "archive_snapshot": True,
                "network_denied": True,
                "writes_denied": True,
                "tenant_modified": False,
                "semantic_correctness": False,
            },
        }
        receipt = {**receipt_body, "receipt_sha256": canonical_sha256(receipt_body)}
        if self.mode == "invalid":
            invalid_body = {
                **receipt_body,
                "status": "invalid",
                "compiler": {
                    **compiler,
                    "status": "invalid",
                    "diagnostics": [{"message": "invalid candidate"}],
                    "endpoint": None,
                    "endpoint_sha256": None,
                    "runtime_context_sha256": None,
                },
            }
            invalid_receipt = {
                **invalid_body,
                "receipt_sha256": canonical_sha256(invalid_body),
            }
            return CandidateCompileResult(invalid_receipt, None, None, None, None)
        result = CandidateCompileResult(
            receipt,
            manifest,
            canonical_sha256(manifest),
            ir,
            canonical_sha256(ir),
        )
        if self.mode == "bad_manifest_hash":
            result = replace(result, manifest_sha256=bytes_sha256(b"wrong"))
        if self.mode == "drift_binding":
            self.toolchain_binding = bytes_sha256(b"drifted-toolchain")
        return result


def _run(
    *,
    model: _Model | None = None,
    compiler: _Compiler | None = None,
    lease: OperationLease | None = None,
    binding: TypedCreateV2RequestBinding | None = None,
    projection: CompactAuthorityProjection | None = None,
    base_spec: dict[str, Any] | None = None,
    generation: int = 0,
    basis_ref: str | None = None,
    parent_spec_sha256: str | None = None,
    parent_ir: dict[str, Any] | None = None,
    parent_ir_sha256: str | None = None,
):
    return run_typed_create_pipeline_v2(
        model=model or _Model(),
        compiler=compiler or _Compiler(),
        lease=lease or _lease(),
        binding=binding or _binding(),
        projection=projection or _projection(generation=generation),
        active_requirement_handles=(0,),
        base_spec=base_spec or initial_create_endpoint_skeleton(ENDPOINT),
        target_ref=TARGET,
        basis_ref=basis_ref,
        generation=generation,
        parent_spec_sha256=parent_spec_sha256,
        parent_ir=parent_ir,
        parent_ir_sha256=parent_ir_sha256,
    )


def test_pipeline_is_one_model_plan_one_compile_and_keeps_private_authority_out_of_payload() -> (
    None
):
    model = _Model()
    model.mutate_request = True
    compiler = _Compiler()
    projection = _projection()
    result = _run(model=model, compiler=compiler, projection=projection)

    assert model.plan_calls == 1
    assert model.v1_plan_calls == 0
    assert model.generate_calls == 0
    assert compiler.calls == 1
    assert len(compiler.sources) == 1
    assert "needs time" in result.candidate.source
    assert isinstance(result.candidate, ModelCandidate)
    assert result.candidate.generator == "model_create_plan_v2"
    assert result.contract_id == TYPED_CREATE_PIPELINE_V2_CONTRACT
    assert result.compiler_receipt["status"] == "ok"
    payload_text = json.dumps(model.safe_payloads, sort_keys=True)
    assert PRIVATE_SENTINEL not in payload_text
    assert TARGET not in payload_text
    assert FILENAME not in payload_text
    assert "fragment" not in payload_text.casefold()
    assert result.private_spec()["endpoint"]["needs_time"] is True
    assert result.private_stage_proof().ir_sha256 == result.ir_sha256
    assert result.private_stage_proof().parent_ir_sha256 is None

    # Caller and model-side mutations cannot alter the admitted private graph.
    object.__setattr__(projection.authorities[1], "fragment", False)
    spec = result.private_spec()
    spec["endpoint"]["needs_time"] = False
    manifest = result.private_manifest()
    manifest["endpoint"] = "drifted"
    ir = result.private_ir()
    ir["name"] = "drifted"
    receipt = result.compiler_receipt
    receipt["status"] = "invalid"
    assert result.private_spec()["endpoint"]["needs_time"] is True
    assert result.private_manifest()["endpoint"] == ENDPOINT
    assert result.private_ir()["name"] == ENDPOINT
    assert result.compiler_receipt["status"] == "ok"
    assert PRIVATE_SENTINEL not in repr(result)


@pytest.mark.parametrize("finish_reason", ["length", "invalid"])
def test_pipeline_rejects_non_eos_model_output_without_compiling(finish_reason: str) -> None:
    model = _Model(finish_reason=finish_reason)
    compiler = _Compiler()
    if finish_reason == "invalid":
        # The candidate type itself rejects an invalid worker finish reason.
        with pytest.raises(BrainError):
            _run(model=model, compiler=compiler)
    else:
        with pytest.raises(BrainError) as raised:
            _run(model=model, compiler=compiler)
        assert raised.value.code == "MODEL_OUTPUT_TRUNCATED"
    assert model.plan_calls == 1
    assert compiler.calls == 0


def test_pipeline_rejects_model_identity_drift_and_unknown_handle_before_compile() -> None:
    drifting = _Model()
    drifting.drift_identity = True
    compiler = _Compiler()
    with pytest.raises(BrainError) as raised:
        _run(model=drifting, compiler=compiler)
    assert raised.value.code == "CREATE_TYPED_RUNTIME_DRIFT"
    assert compiler.calls == 0

    unknown = _Model(body={"o": [{"k": "s", "q": [0], "s": 11, "v": 20}]})
    with pytest.raises(BrainError) as raised:
        _run(model=unknown, compiler=compiler)
    assert raised.value.code == "CREATE_DELTA_PLAN_V2_INVALID"
    assert compiler.calls == 0


@pytest.mark.parametrize("mode", ["invalid", "partial", "bad_manifest_hash", "drift_binding"])
def test_pipeline_compiles_once_then_fails_closed_on_invalid_private_authority(mode: str) -> None:
    model = _Model()
    compiler = _Compiler()
    compiler.mode = mode
    with pytest.raises(BrainError) as raised:
        _run(model=model, compiler=compiler)
    assert raised.value.code in {"COMPILER_FAILED", "CREATE_TYPED_RUNTIME_DRIFT"}
    assert model.plan_calls == 1
    assert model.generate_calls == 0
    assert compiler.calls == 1


def test_pipeline_rejects_parent_drift_before_model_and_base_drift_before_compile() -> None:
    model = _Model()
    compiler = _Compiler()
    parent_ir = {"node": "Endpoint", "name": ENDPOINT, "irVersion": "0.43"}
    with pytest.raises(BrainError) as raised:
        _run(
            model=model,
            compiler=compiler,
            generation=1,
            basis_ref=BASIS,
            parent_spec_sha256=bytes_sha256(b"parent-spec"),
            parent_ir=parent_ir,
            parent_ir_sha256=bytes_sha256(b"wrong-parent-ir"),
        )
    assert raised.value.code == "CREATE_TYPED_PARENT_DRIFT"
    assert model.plan_calls == 0
    assert compiler.calls == 0

    base = initial_create_endpoint_skeleton(ENDPOINT)
    with pytest.raises(BrainError) as raised_executor:
        _run(
            model=model,
            compiler=compiler,
            base_spec=base,
            generation=1,
            basis_ref=BASIS,
            parent_spec_sha256=bytes_sha256(b"wrong-parent-spec"),
            parent_ir=parent_ir,
            parent_ir_sha256=canonical_sha256(parent_ir),
        )
    assert raised_executor.value.code == "CREATE_TYPED_PARENT_DRIFT"
    assert model.plan_calls == 0
    assert compiler.calls == 0


def test_pipeline_refinement_binds_exact_parent_ir_and_builds_cumulative_proof() -> None:
    base = initial_create_endpoint_skeleton(ENDPOINT)
    parent_ir = {
        "node": "Endpoint",
        "name": ENDPOINT,
        "irVersion": "0.43",
        "needsTime": False,
    }
    result = _run(
        base_spec=base,
        generation=1,
        basis_ref=BASIS,
        parent_spec_sha256=bytes_sha256(canonical_json(base)),
        parent_ir=parent_ir,
        parent_ir_sha256=canonical_sha256(parent_ir),
    )

    expected = create_ir_stage_proof(parent_ir, result.private_ir())
    assert result.private_stage_proof() == expected
    assert result.private_execution_proof().generation == 1
    assert result.private_execution_proof().receipt.receipt_sha256 == result.permit_receipt_sha256


def test_pipeline_snapshots_request_binding_before_calling_injected_model() -> None:
    binding = _binding()
    model = _Model()
    model.on_plan = lambda: object.__setattr__(binding, "endpoint", "demo.drifted")

    result = _run(model=model, binding=binding)

    assert binding.endpoint == "demo.drifted"
    assert result.private_ir()["name"] == ENDPOINT
    assert result.compiler_receipt["candidate"]["endpoint"] == ENDPOINT


def test_pipeline_rejects_history_context_and_target_drift_without_side_effects() -> None:
    messages = _history("Crea un endpoint.")
    with pytest.raises(BrainError) as raised:
        TypedCreateV2RequestBinding(
            history=messages,
            history_revision=bytes_sha256(b"wrong"),
            context_revision=CONTEXT,
            semantic_revision=SEMANTIC,
            candidate_filename=FILENAME,
            endpoint=ENDPOINT,
        )
    assert raised.value.code == "CREATE_TYPED_BINDING_DRIFT"

    model = _Model()
    compiler = _Compiler()
    stale_binding = replace(_binding(), context_revision=bytes_sha256(b"stale"))
    with pytest.raises(BrainError) as raised:
        _run(model=model, compiler=compiler, binding=stale_binding)
    assert raised.value.code == "STALE_CONTEXT"
    assert model.plan_calls == 0
    assert compiler.calls == 0

    stale_semantics = replace(_binding(), semantic_revision=bytes_sha256(b"stale-semantic"))
    with pytest.raises(BrainError) as raised:
        _run(model=model, compiler=compiler, binding=stale_semantics)
    assert raised.value.code == "STALE_SEMANTICS"
    assert model.plan_calls == 0
    assert compiler.calls == 0

    wrong_target = initial_create_endpoint_skeleton("demo.other")
    with pytest.raises(BrainError) as raised:
        _run(model=model, compiler=compiler, base_spec=wrong_target)
    assert raised.value.code == "CREATE_TYPED_BINDING_INVALID"
    assert model.plan_calls == 0
    assert compiler.calls == 0


def test_initial_generation_rejects_noncanonical_base_spec_before_model() -> None:
    model = _Model()
    compiler = _Compiler()
    noncanonical = initial_create_endpoint_skeleton(ENDPOINT)
    noncanonical["endpoint"]["needs_time"] = True

    with pytest.raises(BrainError) as raised:
        _run(model=model, compiler=compiler, base_spec=noncanonical)

    assert raised.value.code == "CREATE_TYPED_BINDING_INVALID"
    assert model.plan_calls == 0
    assert compiler.calls == 0
