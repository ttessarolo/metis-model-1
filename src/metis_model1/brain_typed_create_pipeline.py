"""One-pass private pipeline for typed Metis Brain CREATE v2.

This boundary deliberately contains no authority issuer and no orchestration
policy.  It accepts an already validated private projection, gives Model 1 only
the compact handle surface, expands the admitted body deterministically, and
performs exactly one candidate compilation.  No whole-source generation or
repair route exists in this module.
"""

from __future__ import annotations

import copy
import hmac
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, NoReturn, Protocol

from metis_model1.brain_create_builder import (
    CreateBuildStats,
    RenderedCreateEndpoint,
    render_create_endpoint,
)
from metis_model1.brain_create_executor_v2 import (
    CreateDeltaPlanV2Execution,
    CreateDeltaPlanV2PermitConsumer,
    CreateDeltaPlanV2ProofInput,
    execute_create_delta_plan_v2,
    issue_create_delta_plan_v2_permit,
)
from metis_model1.brain_create_ir import CreateIrStageProof, create_ir_stage_proof, isolated_ir
from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    CreateDeltaPlanV2,
    admit_create_delta_plan_v2,
    initial_create_endpoint_skeleton,
    validate_compact_authority_projection,
    validate_create_plan_v2_decoder_constraint_membership,
)
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    CreateAuthoritySurfaceError,
    create_authority_history_revision,
)
from metis_model1.brain_model_runtime import (
    MAX_GENERATION_TOKENS,
    BrainModelRuntime,
    CreatePlanV2Candidate,
    CreatePlanV2Request,
    ModelCandidate,
)
from metis_model1.brain_protocol import BrainError, canonical_json, canonical_sha256
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_tools import CandidateCompileResult

TYPED_CREATE_PIPELINE_V2_CONTRACT = "metis-brain-typed-create-pipeline/v2"
MAX_PIPELINE_GENERATION = 20
MAX_IDENTITY_BYTES = 2_048
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HOST_REF_RE = re.compile(r"^hostref:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ENDPOINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,95})*$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\.metis$")
_COMPILE_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "session_id",
        "tenant_alias",
        "context_revision",
        "toolchain_binding",
        "candidate",
        "compiler",
        "claims",
        "receipt_sha256",
    }
)
_COMPILE_CANDIDATE_KEYS = frozenset(
    {"filename", "execution_mode", "endpoint", "source_sha256", "context_revision"}
)
_COMPILE_COMPILER_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "status",
        "diagnostics",
        "endpoint",
        "endpoint_sha256",
        "runtime_context_sha256",
    }
)
_COMPILE_CLAIMS = {
    "archive_snapshot": True,
    "network_denied": True,
    "writes_denied": True,
    "tenant_modified": False,
    "semantic_correctness": False,
}


class TypedCreateV2Model(Protocol):
    """Only the structured planner surface used by this pipeline."""

    @property
    def model_loaded(self) -> bool: ...

    @property
    def model_revision(self) -> str: ...

    @property
    def adapter_sha256(self) -> str: ...

    def plan_create_v2(self, request: CreatePlanV2Request) -> CreatePlanV2Candidate: ...


class TypedCreateV2Compiler(Protocol):
    """Private single-compile bridge; it has no repair method here."""

    @property
    def toolchain_binding(self) -> str: ...

    def compile_candidate(
        self,
        *,
        lease: OperationLease,
        source: Any,
        filename: Any,
        endpoint: Any,
    ) -> CandidateCompileResult: ...


def _fail(code: str, status: int, message: str) -> NoReturn:
    raise BrainError(code, status, message)


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        _fail("CREATE_TYPED_BINDING_INVALID", 500, f"{label} is invalid")
    return value


def _identity(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > MAX_IDENTITY_BYTES
        or any(ord(character) < 32 for character in value)
    ):
        _fail("CREATE_TYPED_IDENTITY_INVALID", 503, f"{label} is invalid")
    return value


def _canonical_copy(value: Any, *, code: str, label: str) -> Any:
    try:
        return json.loads(canonical_json(value))
    except (
        BrainError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise BrainError(code, 503, f"{label} is invalid") from error


def _same(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True, slots=True, repr=False)
class TypedCreateV2RequestBinding:
    """Exact host-owned request lineage; only message text reaches the model."""

    history: tuple[CreateAuthorityHistoryMessage, ...] = field(repr=False)
    history_revision: str
    context_revision: str
    semantic_revision: str
    candidate_filename: str
    endpoint: str

    def __post_init__(self) -> None:
        if type(self.history) is not tuple:
            _fail("CREATE_TYPED_BINDING_INVALID", 500, "CREATE history is invalid")
        try:
            computed = create_authority_history_revision(self.history)
        except (CreateAuthoritySurfaceError, TypeError, UnicodeError, ValueError) as error:
            raise BrainError(
                "CREATE_TYPED_BINDING_INVALID", 500, "CREATE history is invalid"
            ) from error
        revision = _hash(self.history_revision, label="history revision")
        if not _same(computed, revision):
            _fail("CREATE_TYPED_BINDING_DRIFT", 409, "CREATE history revision differs")
        _hash(self.context_revision, label="context revision")
        _hash(self.semantic_revision, label="semantic revision")
        if (
            not isinstance(self.candidate_filename, str)
            or _FILENAME_RE.fullmatch(self.candidate_filename) is None
        ):
            _fail("CREATE_TYPED_BINDING_INVALID", 500, "candidate filename is invalid")
        path = PurePosixPath(self.candidate_filename)
        raw_parts = self.candidate_filename.split("/")
        if path.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
            _fail("CREATE_TYPED_BINDING_INVALID", 500, "candidate filename is invalid")
        if not isinstance(self.endpoint, str) or _ENDPOINT_RE.fullmatch(self.endpoint) is None:
            _fail("CREATE_TYPED_BINDING_INVALID", 500, "endpoint identity is invalid")
        copied = tuple(
            CreateAuthorityHistoryMessage(
                ordinal=message.ordinal,
                text=str(message.text),
                message_sha256=str(message.message_sha256),
            )
            for message in self.history
        )
        object.__setattr__(self, "history", copied)

    @property
    def instructions(self) -> tuple[str, ...]:
        return tuple(message.text for message in self.history)


@dataclass(frozen=True, slots=True, repr=False)
class TypedCreateV2PipelineResult:
    """Hash-led result; typed spec, manifest, IR and proof stay private."""

    _candidate: ModelCandidate = field(repr=False)
    _compiler_receipt: dict[str, Any] = field(repr=False)
    _spec: dict[str, Any] = field(repr=False)
    _manifest: dict[str, Any] = field(repr=False)
    _ir: dict[str, Any] = field(repr=False)
    _plan: CreateDeltaPlanV2 = field(repr=False)
    _execution_proof: CreateDeltaPlanV2ProofInput = field(repr=False)
    _stage_proof: CreateIrStageProof = field(repr=False)
    spec_sha256: str
    manifest_sha256: str
    ir_sha256: str
    plan_sha256: str
    permit_receipt_sha256: str
    stats: CreateBuildStats
    contract_id: str = TYPED_CREATE_PIPELINE_V2_CONTRACT

    @property
    def candidate(self) -> ModelCandidate:
        candidate = self._candidate
        return ModelCandidate(
            source=candidate.source,
            model_revision=candidate.model_revision,
            adapter_sha256=candidate.adapter_sha256,
            generator=candidate.generator,
            metrics=dict(candidate.metrics),
        )

    @property
    def compiler_receipt(self) -> dict[str, Any]:
        return copy.deepcopy(self._compiler_receipt)

    def private_spec(self) -> dict[str, Any]:
        return copy.deepcopy(self._spec)

    def private_manifest(self) -> dict[str, Any]:
        return copy.deepcopy(self._manifest)

    def private_ir(self) -> dict[str, Any]:
        return copy.deepcopy(self._ir)

    def private_plan(self) -> CreateDeltaPlanV2:
        return copy.deepcopy(self._plan)

    def private_execution_proof(self) -> CreateDeltaPlanV2ProofInput:
        return copy.deepcopy(self._execution_proof)

    def private_stage_proof(self) -> CreateIrStageProof:
        return copy.deepcopy(self._stage_proof)


def _validate_lease(
    lease: OperationLease,
    binding: TypedCreateV2RequestBinding,
    compiler: TypedCreateV2Compiler,
) -> str:
    if type(lease) is not OperationLease:
        _fail("CREATE_TYPED_BINDING_INVALID", 500, "operation lease is invalid")
    if not {"chat.turn", "compile"}.issubset(lease.capabilities):
        _fail("FORBIDDEN", 403, "typed CREATE requires chat and compile capabilities")
    if lease.cancellation.is_set():
        _fail("SESSION_REVOKED", 409, "session was revoked")
    context_revision = _hash(lease.snapshot.revision, label="lease context revision")
    semantic_revision = _hash(
        lease.snapshot.semantic_source_revision(), label="lease semantic revision"
    )
    toolchain_binding = _hash(lease.snapshot.toolchain_binding, label="lease toolchain binding")
    if not _same(context_revision, binding.context_revision):
        _fail("STALE_CONTEXT", 409, "typed CREATE context revision is stale")
    if not _same(semantic_revision, binding.semantic_revision):
        _fail("STALE_SEMANTICS", 409, "typed CREATE semantic revision is stale")
    try:
        compiler_binding = _hash(compiler.toolchain_binding, label="compiler toolchain binding")
    except AttributeError as error:
        raise BrainError(
            "CREATE_TYPED_IDENTITY_INVALID", 503, "compiler identity is unavailable"
        ) from error
    if not _same(toolchain_binding, compiler_binding):
        _fail("STALE_CONTEXT", 409, "typed CREATE compiler binding is stale")
    return toolchain_binding


def _validate_model_candidate(
    candidate: Any,
    *,
    model_revision: str,
    adapter_sha256: str,
) -> CreatePlanV2Candidate:
    if type(candidate) is not CreatePlanV2Candidate:
        _fail("MODEL_OUTPUT_INVALID", 502, "Model 1 returned an invalid CREATE v2 candidate")
    candidate_model_revision = _identity(candidate.model_revision, label="candidate model revision")
    candidate_adapter_sha256 = _identity(
        candidate.adapter_sha256, label="candidate adapter identity"
    )
    if not _same(candidate_model_revision, model_revision) or not _same(
        candidate_adapter_sha256, adapter_sha256
    ):
        _fail("MODEL_IDENTITY_DRIFT", 503, "Model 1 identity changed during CREATE planning")
    metrics = candidate.metrics
    if (
        not metrics
        or metrics.get("finish_reason") != "stop"
        or type(metrics.get("generation_tokens")) is not int
        or not 1 <= metrics["generation_tokens"] <= MAX_GENERATION_TOKENS
    ):
        _fail(
            "MODEL_OUTPUT_TRUNCATED",
            502,
            "Model 1 CREATE v2 output did not finish at EOS within its bound",
        )
    try:
        return CreatePlanV2Candidate(
            body=copy.deepcopy(candidate.body),
            model_revision=candidate_model_revision,
            adapter_sha256=candidate_adapter_sha256,
            generator=candidate.generator,
            metrics=dict(candidate.metrics),
        )
    except (BrainError, TypeError, ValueError) as error:
        raise BrainError(
            "MODEL_OUTPUT_INVALID", 502, "Model 1 returned an unstable CREATE v2 candidate"
        ) from error


def _contains_provenance(value: Any) -> bool:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Mapping):
            if "provenance" in item:
                return True
            stack.extend(item.values())
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            stack.extend(item)
    return False


def _validate_compile_result(
    result: Any,
    *,
    lease: OperationLease,
    toolchain_binding: str,
    rendered: RenderedCreateEndpoint,
    filename: str,
    endpoint: str,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any], str]:
    if type(result) is not CandidateCompileResult:
        _fail("COMPILER_FAILED", 503, "candidate compiler returned an invalid result")
    receipt = _canonical_copy(result.receipt, code="COMPILER_FAILED", label="compiler receipt")
    manifest = _canonical_copy(
        result.manifest, code="COMPILER_FAILED", label="private compiler manifest"
    )
    ir = _canonical_copy(result.ir, code="COMPILER_FAILED", label="private normalized IR")
    if not isinstance(receipt, dict) or set(receipt) != _COMPILE_RECEIPT_KEYS:
        _fail("COMPILER_FAILED", 503, "candidate compiler receipt shape differs")
    receipt_sha256 = receipt.get("receipt_sha256")
    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "ok"
        or receipt.get("session_id") != lease.session_id
        or receipt.get("tenant_alias") != lease.tenant_alias
        or receipt.get("context_revision") != lease.snapshot.revision
        or receipt.get("toolchain_binding") != toolchain_binding
        or receipt.get("claims") != _COMPILE_CLAIMS
        or not isinstance(receipt_sha256, str)
        or not _same(receipt_sha256, canonical_sha256(receipt_body))
    ):
        _fail("COMPILER_FAILED", 503, "candidate compiler receipt identity differs")
    candidate = receipt.get("candidate")
    compiler = receipt.get("compiler")
    if not isinstance(candidate, dict) or set(candidate) != _COMPILE_CANDIDATE_KEYS:
        _fail("COMPILER_FAILED", 503, "candidate compiler source receipt differs")
    if not isinstance(compiler, dict) or set(compiler) != _COMPILE_COMPILER_KEYS:
        _fail("COMPILER_FAILED", 503, "candidate compiler inner receipt differs")
    if candidate != {
        "filename": filename,
        "execution_mode": "endpoint",
        "endpoint": endpoint,
        "source_sha256": canonical_sha256(rendered.metis_text),
        "context_revision": lease.snapshot.revision,
    }:
        _fail("COMPILER_FAILED", 503, "candidate compiler source identity differs")
    endpoint_sha256 = compiler.get("endpoint_sha256")
    if (
        compiler.get("schema_version") != 1
        or compiler.get("operation") != "compile"
        or compiler.get("status") != "ok"
        or compiler.get("diagnostics") != []
        or compiler.get("endpoint") != endpoint
        or not isinstance(endpoint_sha256, str)
        or _HASH_RE.fullmatch(endpoint_sha256) is None
        or not isinstance(compiler.get("runtime_context_sha256"), str)
        or _HASH_RE.fullmatch(compiler["runtime_context_sha256"]) is None
    ):
        _fail("COMPILER_FAILED", 503, "candidate compiler did not return one valid endpoint")
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "endpoint",
            "endpoint_sha256",
            "containers",
            "fetches",
        }
        or manifest.get("schema_version") != 1
        or manifest.get("endpoint") != endpoint
        or manifest.get("endpoint_sha256") != endpoint_sha256
        or not isinstance(manifest.get("containers"), list)
        or not manifest["containers"]
        or not any(
            isinstance(item, dict) and item.get("path") == "endpoint"
            for item in manifest["containers"]
        )
        or not isinstance(manifest.get("fetches"), list)
    ):
        _fail("COMPILER_FAILED", 503, "private compiler manifest identity differs")
    manifest_sha256 = result.manifest_sha256
    if (
        not isinstance(manifest_sha256, str)
        or _HASH_RE.fullmatch(manifest_sha256) is None
        or not _same(canonical_sha256(manifest), manifest_sha256)
    ):
        _fail("COMPILER_FAILED", 503, "private compiler manifest hash differs")
    if (
        not isinstance(ir, dict)
        or ir.get("node") != "Endpoint"
        or ir.get("name") != endpoint
        or not isinstance(ir.get("irVersion"), str)
        or not ir["irVersion"]
        or _contains_provenance(ir)
    ):
        _fail("COMPILER_FAILED", 503, "private normalized IR identity differs")
    ir_sha256 = result.ir_sha256
    if (
        not isinstance(ir_sha256, str)
        or _HASH_RE.fullmatch(ir_sha256) is None
        or not _same(canonical_sha256(ir), ir_sha256)
    ):
        _fail("COMPILER_FAILED", 503, "private normalized IR hash differs")
    ir = isolated_ir(ir)
    return receipt, manifest, manifest_sha256, ir, ir_sha256


def run_typed_create_pipeline_v2(
    *,
    model: TypedCreateV2Model | BrainModelRuntime,
    compiler: TypedCreateV2Compiler,
    lease: OperationLease,
    binding: TypedCreateV2RequestBinding,
    projection: CompactAuthorityProjection,
    active_requirement_handles: tuple[int, ...],
    base_spec: Mapping[str, Any],
    target_ref: str,
    basis_ref: str | None,
    generation: int,
    parent_spec_sha256: str | None,
    parent_ir: Mapping[str, Any] | None,
    parent_ir_sha256: str | None,
    progress: Callable[[str], None] | None = None,
) -> TypedCreateV2PipelineResult:
    """Execute the only admitted compact CREATE v2 path exactly once."""

    if not isinstance(binding, TypedCreateV2RequestBinding):
        _fail("CREATE_TYPED_BINDING_INVALID", 500, "typed CREATE request binding is invalid")
    # Snapshot the entire request binding before invoking any injected
    # dependency.  A caller cannot rewrite history, target filename or endpoint
    # identity while the model is running.
    binding_copy = TypedCreateV2RequestBinding(
        history=tuple(binding.history),
        history_revision=binding.history_revision,
        context_revision=binding.context_revision,
        semantic_revision=binding.semantic_revision,
        candidate_filename=binding.candidate_filename,
        endpoint=binding.endpoint,
    )
    if type(generation) is not int or not 0 <= generation <= MAX_PIPELINE_GENERATION:
        _fail("CREATE_TYPED_BINDING_INVALID", 500, "typed CREATE generation is invalid")
    if not isinstance(target_ref, str) or _HOST_REF_RE.fullmatch(target_ref) is None:
        _fail("CREATE_TYPED_BINDING_INVALID", 500, "typed CREATE target ref is invalid")
    if basis_ref is not None and (
        not isinstance(basis_ref, str) or _HOST_REF_RE.fullmatch(basis_ref) is None
    ):
        _fail("CREATE_TYPED_BINDING_INVALID", 500, "typed CREATE basis ref is invalid")
    initial = generation == 0
    if initial:
        if any(
            value is not None
            for value in (basis_ref, parent_spec_sha256, parent_ir, parent_ir_sha256)
        ):
            _fail("CREATE_TYPED_PARENT_DRIFT", 409, "initial CREATE carries parent authority")
        mode = "initial"
        parent_ir_copy = None
    else:
        if (
            basis_ref is None
            or parent_spec_sha256 is None
            or parent_ir is None
            or parent_ir_sha256 is None
        ):
            _fail("CREATE_TYPED_PARENT_DRIFT", 409, "refinement lacks parent authority")
        _hash(parent_spec_sha256, label="parent spec sha256")
        _hash(parent_ir_sha256, label="parent IR sha256")
        parent_ir_copy = isolated_ir(parent_ir)
        if not _same(canonical_sha256(parent_ir_copy), parent_ir_sha256):
            _fail("CREATE_TYPED_PARENT_DRIFT", 409, "refinement parent IR differs")
        mode = "refinement"
    if type(active_requirement_handles) is not tuple:
        _fail("CREATE_TYPED_BINDING_INVALID", 500, "active requirement roster is invalid")
    try:
        projection_copy = copy.deepcopy(projection)
        validate_compact_authority_projection(projection_copy)
    except (BrainError, TypeError, ValueError) as error:
        raise BrainError(
            "CREATE_TYPED_BINDING_INVALID", 500, "private authority projection is invalid"
        ) from error
    base_copy = _canonical_copy(
        base_spec, code="CREATE_TYPED_BINDING_INVALID", label="base typed CREATE spec"
    )
    if initial and base_copy != initial_create_endpoint_skeleton(binding_copy.endpoint):
        _fail(
            "CREATE_TYPED_BINDING_INVALID",
            500,
            "initial CREATE base spec is not the canonical endpoint skeleton",
        )
    if parent_spec_sha256 is not None and not _same(
        canonical_sha256(base_copy), parent_spec_sha256
    ):
        _fail("CREATE_TYPED_PARENT_DRIFT", 409, "refinement parent spec differs")
    toolchain_binding = _validate_lease(lease, binding_copy, compiler)
    if getattr(model, "model_loaded", None) is not True:
        _fail("MODEL_UNAVAILABLE", 503, "local Model 1 runtime is unavailable")
    try:
        model_revision = _identity(model.model_revision, label="model revision")
        adapter_sha256 = _identity(model.adapter_sha256, label="adapter identity")
    except AttributeError as error:
        raise BrainError(
            "CREATE_TYPED_IDENTITY_INVALID", 503, "Model 1 identity is unavailable"
        ) from error

    if progress is not None and not callable(progress):
        _fail("CREATE_TYPED_BINDING_INVALID", 500, "typed CREATE progress hook is invalid")
    request = CreatePlanV2Request(
        instructions=binding_copy.instructions,
        generation=generation,
        context_revision=binding_copy.context_revision,
        semantic_revision=binding_copy.semantic_revision,
        active_requirement_handles=tuple(active_requirement_handles),
        authority_projection=projection_copy,
        cancellation=lease.cancellation,
    )
    if progress is not None:
        progress("model.started")
    raw_candidate = model.plan_create_v2(request)
    candidate = _validate_model_candidate(
        raw_candidate,
        model_revision=model_revision,
        adapter_sha256=adapter_sha256,
    )
    if progress is not None:
        progress("model.completed")
    if (
        lease.cancellation.is_set()
        or lease.snapshot.revision != binding_copy.context_revision
        or lease.snapshot.semantic_source_revision() != binding_copy.semantic_revision
        or lease.snapshot.toolchain_binding != toolchain_binding
        or compiler.toolchain_binding != toolchain_binding
        or model.model_revision != model_revision
        or model.adapter_sha256 != adapter_sha256
    ):
        _fail("CREATE_TYPED_RUNTIME_DRIFT", 409, "typed CREATE authority changed after planning")

    # The worker grammar is projection-derived, but its response is still
    # untrusted.  Recheck exact direct-operation membership on the host before
    # the fuller private admission/permit boundary below.
    validate_create_plan_v2_decoder_constraint_membership(
        copy.deepcopy(candidate.body),
        request.decoder_constraint,
    )
    plan = admit_create_delta_plan_v2(
        copy.deepcopy(candidate.body),
        projection=projection_copy,
        mode=mode,  # type: ignore[arg-type]
        context_revision=binding_copy.context_revision,
        semantic_revision=binding_copy.semantic_revision,
        target_ref=target_ref,
        basis_ref=basis_ref,
        active_requirement_handles=active_requirement_handles,
    )
    permit = issue_create_delta_plan_v2_permit(
        plan,
        projection_copy,
        base_spec=base_copy,
        toolchain_binding=toolchain_binding,
        generation=generation,
        parent_spec_sha256=parent_spec_sha256,
    )
    execution: CreateDeltaPlanV2Execution = execute_create_delta_plan_v2(
        plan,
        projection_copy,
        base_spec=base_copy,
        parent_spec_sha256=parent_spec_sha256,
        permit_consumer=CreateDeltaPlanV2PermitConsumer(permit),
        toolchain_binding=toolchain_binding,
        generation=generation,
    )
    rendered = render_create_endpoint(execution.spec)
    if rendered.spec_sha256 != execution.spec_sha256:
        _fail("CREATE_TYPED_RUNTIME_DRIFT", 503, "rendered spec identity differs")
    endpoint = execution.spec.get("endpoint")
    if not isinstance(endpoint, Mapping) or endpoint.get("name") != binding_copy.endpoint:
        _fail("CREATE_TYPED_TARGET_DRIFT", 409, "typed CREATE endpoint identity differs")
    if lease.cancellation.is_set():
        _fail("SESSION_REVOKED", 409, "session was revoked")

    # This is intentionally the sole compiler call in the function.  Invalid
    # output fails closed; there is no repair generation and no second compile.
    if progress is not None:
        progress("compile.started")
    compile_result = compiler.compile_candidate(
        lease=lease,
        source=rendered.metis_text,
        filename=binding_copy.candidate_filename,
        endpoint=binding_copy.endpoint,
    )
    if (
        lease.cancellation.is_set()
        or lease.snapshot.revision != binding_copy.context_revision
        or lease.snapshot.semantic_source_revision() != binding_copy.semantic_revision
        or lease.snapshot.toolchain_binding != toolchain_binding
        or compiler.toolchain_binding != toolchain_binding
        or model.model_revision != model_revision
        or model.adapter_sha256 != adapter_sha256
    ):
        _fail("CREATE_TYPED_RUNTIME_DRIFT", 409, "typed CREATE authority changed while compiling")
    receipt, manifest, manifest_sha256, ir, ir_sha256 = _validate_compile_result(
        compile_result,
        lease=lease,
        toolchain_binding=toolchain_binding,
        rendered=rendered,
        filename=binding_copy.candidate_filename,
        endpoint=binding_copy.endpoint,
    )
    if progress is not None:
        progress("compile.completed")
    stage_proof = create_ir_stage_proof(parent_ir_copy, ir)
    if not _same(stage_proof.ir_sha256, ir_sha256):
        _fail("COMPILER_FAILED", 503, "normalized IR proof identity differs")
    if parent_ir_sha256 is not None and not _same(
        stage_proof.parent_ir_sha256 or "", parent_ir_sha256
    ):
        _fail("CREATE_TYPED_PARENT_DRIFT", 409, "normalized parent IR proof differs")

    draft = ModelCandidate(
        source=rendered.metis_text,
        model_revision=candidate.model_revision,
        adapter_sha256=candidate.adapter_sha256,
        generator="model_create_plan_v2",
        metrics=dict(candidate.metrics),
    )
    spec = _canonical_copy(
        execution.spec, code="CREATE_TYPED_RUNTIME_DRIFT", label="executed typed CREATE spec"
    )
    return TypedCreateV2PipelineResult(
        _candidate=draft,
        _compiler_receipt=receipt,
        _spec=spec,
        _manifest=manifest,
        _ir=ir,
        _plan=copy.deepcopy(plan),
        _execution_proof=copy.deepcopy(execution.proof_input),
        _stage_proof=stage_proof,
        spec_sha256=execution.spec_sha256,
        manifest_sha256=manifest_sha256,
        ir_sha256=ir_sha256,
        plan_sha256=execution.proof_input.plan_sha256,
        permit_receipt_sha256=execution.proof_input.receipt.receipt_sha256,
        stats=rendered.stats,
    )


__all__ = [
    "TYPED_CREATE_PIPELINE_V2_CONTRACT",
    "TypedCreateV2Compiler",
    "TypedCreateV2Model",
    "TypedCreateV2PipelineResult",
    "TypedCreateV2RequestBinding",
    "run_typed_create_pipeline_v2",
]
