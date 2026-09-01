"""Bounded local A/B qualification for the persistent Metis Brain runtime.

The runner exercises the real retriever, Model 1 worker and compiler but never
calls Apply.  Its durable output is the redacted receipt defined in
``brain_latency_benchmark``; session tokens, instructions and generated source
remain process-local and are discarded when each session closes.
"""

from __future__ import annotations

import copy
import hashlib
import os
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_latency_benchmark import (
    ARMS,
    MAX_PROMOTION_PAIRS,
    MIN_PROMOTION_PAIRS,
    LatencyReceiptHandle,
    counterbalanced_schedule_sha256,
    observation_from_terminal,
    seal_latency_receipt,
    selection_roster_sha256,
    write_latency_receipt,
)
from metis_model1.brain_mlx_runtime import WORKER_SHA256, MlxBrainModelRuntime
from metis_model1.brain_protocol import (
    MAX_SOURCE_BYTES,
    BrainError,
    bounded_identifier,
    canonical_sha256,
    exact_fields,
    parse_json_object,
)
from metis_model1.brain_server import BrainConfig, MetisBrainService, load_brain_config
from metis_model1.brain_turns import TurnRequest, validate_target

MAX_CASE_BYTES = 64 * 1024
BENCHMARK_CAPABILITIES = frozenset({"chat.read", "chat.turn", "context.read", "session.close"})
TENANT_GUARD_TOOLCHAIN = "sha256:" + "0" * 64
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LATENCY_OUTPUT_ROOT = PROJECT_ROOT / "artifacts/metis-brain-latency"


@dataclass(frozen=True)
class LatencyCase:
    benchmark_id: str
    client_id: str
    tenant_alias: str
    instruction: str
    intent: str
    target: dict[str, str]
    expected_selections: tuple[dict[str, str], ...]
    expected_surface: dict[str, Any]
    case_sha256: str
    pairs: int
    arm_order: tuple[str, str]
    seed: int

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(
            {
                "schema_version": 1,
                "instruction": self.instruction,
                "intent": self.intent,
                "target": self.target,
                "seed": self.seed,
            }
        )

    @property
    def expected_grounding_sha256(self) -> str:
        return selection_roster_sha256(self.expected_selections)

    @property
    def shape_contract(self) -> dict[str, Any]:
        return {"endpoint": self.target["endpoint"], **self.expected_surface}

    @property
    def expected_shape_contract_sha256(self) -> str:
        return canonical_sha256(self.shape_contract)


def _safe_case_bytes(path: Path) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or any(part.startswith(".env") for part in candidate.parts):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark case path is invalid")
    descriptor: int | None = None
    try:
        before = candidate.lstat()
        descriptor = os.open(
            candidate,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not 1 <= opened.st_size <= MAX_CASE_BYTES
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark case is invalid")
        raw = os.read(descriptor, opened.st_size + 1)
        after = os.fstat(descriptor)
        named_after = candidate.lstat()
    except BrainError:
        raise
    except OSError as error:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark case is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda value: (  # noqa: E731 - compact stable file identity
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        len(raw) != opened.st_size
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(named_after)
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark case changed while read")
    return raw


def load_latency_case(path: Path) -> LatencyCase:
    raw = _safe_case_bytes(path)
    value = parse_json_object(raw, label="benchmark case")
    exact_fields(
        value,
        required={
            "schema_version",
            "benchmark_id",
            "client_id",
            "tenant_alias",
            "instruction",
            "intent",
            "target",
            "expected_selections",
            "expected_surface",
            "pairs",
            "arm_order",
            "seed",
        },
        label="benchmark case",
    )
    if value["schema_version"] != 1:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark case version is unsupported")
    benchmark_id = value["benchmark_id"]
    instruction = value["instruction"]
    if (
        not isinstance(benchmark_id, str)
        or not benchmark_id
        or len(benchmark_id.encode()) > 128
        or not isinstance(instruction, str)
        or not instruction.strip()
        or len(instruction.encode()) > MAX_SOURCE_BYTES
        or value["intent"] not in {"create", "edit", "repair", "review", "migrate"}
        or type(value["pairs"]) is not int
        or not MIN_PROMOTION_PAIRS <= value["pairs"] <= MAX_PROMOTION_PAIRS
        or value["pairs"] % 2
        or value["arm_order"] not in (["direct", "prefix"], ["prefix", "direct"])
        or value["seed"] != 17
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark case is invalid")
    target = value["target"]
    if not isinstance(target, dict):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark target is invalid")
    exact_fields(
        target,
        required={"mode", "relative_path", "endpoint"},
        label="benchmark target",
    )
    base = None if target.get("mode") == "create" else "sha256:" + "0" * 64
    checked_target = validate_target({**target, "base_sha256": base})
    expected = value["expected_selections"]
    if not isinstance(expected, list) or not expected or len(expected) > 32:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark oracle is invalid")
    normalized: list[dict[str, str]] = []
    for item in expected:
        if not isinstance(item, dict):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark oracle is invalid")
        exact_fields(item, required={"catalog", "field", "literal"}, label="benchmark selection")
        if any(not isinstance(item[key], str) or not item[key] for key in item):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark oracle is invalid")
        normalized.append(dict(item))
    selection_roster_sha256(normalized)
    expected_surface = value["expected_surface"]
    expected_take = expected_surface.get("take") if isinstance(expected_surface, dict) else None
    if (
        not isinstance(expected_surface, dict)
        or set(expected_surface) != {"take", "order_field", "order_direction", "response"}
        or not isinstance(expected_take, dict)
        or set(expected_take) != {"mode", "value"}
        or expected_take.get("mode") != "count"
        or type(expected_take.get("value")) is not int
        or not 1 <= expected_take["value"] <= 1_000_000
        or not isinstance(expected_surface.get("order_field"), str)
        or not expected_surface["order_field"]
        or not expected_surface["order_field"].isascii()
        or not expected_surface["order_field"].replace("_", "a").isalnum()
        or not (
            expected_surface["order_field"][0].isalpha()
            or expected_surface["order_field"][0] == "_"
        )
        or expected_surface.get("order_direction") not in {"ascending", "descending"}
        or expected_surface.get("response") != "response.expanded"
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark shape oracle is invalid")
    return LatencyCase(
        benchmark_id=benchmark_id,
        client_id=bounded_identifier(value["client_id"], kind="client"),
        tenant_alias=bounded_identifier(value["tenant_alias"], kind="tenant"),
        instruction=instruction,
        intent=value["intent"],
        target={
            "mode": checked_target["mode"],
            "relative_path": checked_target["relative_path"],
            "endpoint": checked_target["endpoint"],
        },
        expected_selections=tuple(normalized),
        expected_surface=dict(expected_surface),
        case_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        pairs=value["pairs"],
        arm_order=tuple(value["arm_order"]),  # type: ignore[arg-type]
        seed=17,
    )


def _git(root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BrainError("BENCHMARK_INVALID", 400, "tenant Git guard is unavailable") from error
    if completed.returncode != 0 or len(completed.stdout) > 4 * 1024 * 1024:
        raise BrainError("BENCHMARK_INVALID", 400, "tenant Git guard failed")
    return completed.stdout


def capture_model1_guard() -> dict[str, str]:
    """Bind the benchmark harness to one committed, clean Model 1 tree."""

    root = PROJECT_ROOT.resolve(strict=True)
    if root != PROJECT_ROOT:
        raise BrainError("BENCHMARK_INVALID", 400, "Model 1 root is invalid")
    top = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve(strict=True)
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    commit = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    tree = _git(root, "rev-parse", "--verify", "HEAD^{tree}").decode().strip()
    if (
        top != root
        or status
        or any(
            len(value) != 40 or any(char not in "0123456789abcdef" for char in value)
            for value in (commit, tree)
        )
    ):
        raise BrainError("BENCHMARK_INVALID", 409, "Model 1 worktree is not sealed")
    return {"commit": commit, "tree": tree}


def capture_tenant_guard(
    *, root: Path, tenant_alias: str, tenant_id: str, target_path: str
) -> dict[str, str]:
    try:
        canonical_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise BrainError("BENCHMARK_INVALID", 400, "tenant root is unavailable") from error
    top = Path(_git(canonical_root, "rev-parse", "--show-toplevel").decode().strip()).resolve(
        strict=True
    )
    if top != canonical_root:
        raise BrainError("BENCHMARK_INVALID", 400, "tenant root is not the Git worktree root")
    status = _git(canonical_root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status:
        raise BrainError("BENCHMARK_INVALID", 409, "tenant worktree is not clean")
    commit = _git(canonical_root, "rev-parse", "--verify", "HEAD").decode().strip()
    tree = _git(canonical_root, "rev-parse", "--verify", "HEAD^{tree}").decode().strip()
    if any(
        len(value) != 40 or any(char not in "0123456789abcdef" for char in value)
        for value in (commit, tree)
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "tenant Git identity is invalid")
    snapshot = TenantRegistry([(tenant_alias, tenant_id, canonical_root)]).capture(
        tenant_alias,
        toolchain_binding=TENANT_GUARD_TOOLCHAIN,
    )
    roster = [
        {"path": item.path, "bytes": len(item.content), "sha256": item.sha256}
        for item in snapshot.files
    ]
    targets = [item for item in snapshot.files if item.path == target_path]
    if len(targets) > 1:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark target roster is invalid")
    target_sha256 = (
        targets[0].sha256
        if targets
        else canonical_sha256({"target": target_path, "state": "absent"})
    )
    return {
        "commit": commit,
        "tree": tree,
        "status_sha256": canonical_sha256({"porcelain_v1_z": status.hex()}),
        "roster_sha256": canonical_sha256(roster),
        "target_sha256": target_sha256,
    }


def _grant(config: BrainConfig, case: LatencyCase) -> tuple[str, str, Path]:
    matches = [item for item in config.tenant_grants if item[0] == case.tenant_alias]
    policies = [item for item in config.client_policies if item.client_id == case.client_id]
    if (
        len(matches) != 1
        or len(policies) != 1
        or case.tenant_alias not in policies[0].tenant_aliases
        or not BENCHMARK_CAPABILITIES.issubset(policies[0].capabilities)
        or config.model is None
        or config.retrieval is None
        or not config.retrieval.schema2
        or config.retrieval.warmup != "on_start"
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark config authority is invalid")
    return matches[0]


def _runtime(config: BrainConfig, *, arm: str) -> MlxBrainModelRuntime:
    if config.model is None or arm not in ARMS:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark model arm is invalid")
    runtime: MlxBrainModelRuntime | None = None
    try:
        runtime = MlxBrainModelRuntime(
            python_path=config.model.python_path,
            model_path=config.model.model_path,
            adapter_path=config.model.adapter_path,
            timeout_seconds=config.model.timeout_seconds,
            prefix_cache_enabled=arm == "prefix",
        )
        if runtime.worker_sha256 != WORKER_SHA256:
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark worker is not qualified")
        runtime.warmup()
        if (
            runtime.model_loaded is not True
            or runtime.cache_mode != ("prefix" if arm == "prefix" else "disabled")
            or (arm == "prefix" and runtime.prefix_cache_ready is not True)
            or (arm == "direct" and runtime.prefix_cache_ready is not False)
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark warmup state is invalid")
        return runtime
    except BaseException:
        if runtime is not None:
            runtime.close()
        raise


def _provision_latency_output_root() -> None:
    """Create only the fixed ignored artifact directories, never an arbitrary path."""

    expected_root = PROJECT_ROOT / "artifacts/metis-brain-latency"
    if expected_root != LATENCY_OUTPUT_ROOT or PROJECT_ROOT.resolve(strict=True) != PROJECT_ROOT:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output authority is invalid")
    for candidate in (expected_root.parent, expected_root):
        try:
            os.mkdir(candidate, 0o700)
        except FileExistsError:
            pass
        except OSError as error:
            raise BrainError(
                "BENCHMARK_INVALID", 400, "benchmark output root is unavailable"
            ) from error
        try:
            candidate_stat = candidate.lstat()
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise BrainError(
                "BENCHMARK_INVALID", 400, "benchmark output root is unavailable"
            ) from error
        if (
            not stat.S_ISDIR(candidate_stat.st_mode)
            or stat.S_ISLNK(candidate_stat.st_mode)
            or resolved != candidate
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark output root is invalid")


def _provision_latency_output_parent(path: Path) -> None:
    _provision_latency_output_root()
    target = Path(path)
    if not target.is_absolute() or ".." in target.parts:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output path is invalid")
    try:
        relative_parent = target.parent.relative_to(LATENCY_OUTPUT_ROOT)
    except ValueError as error:
        raise BrainError(
            "BENCHMARK_INVALID", 400, "benchmark output path is outside authority"
        ) from error
    current = LATENCY_OUTPUT_ROOT
    for part in relative_parent.parts:
        if not part or part.startswith(".env"):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark output path is invalid")
        current = current / part
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            pass
        except OSError as error:
            raise BrainError(
                "BENCHMARK_INVALID", 400, "benchmark output parent is unavailable"
            ) from error
        try:
            current_stat = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as error:
            raise BrainError(
                "BENCHMARK_INVALID", 400, "benchmark output parent is unavailable"
            ) from error
        if (
            not stat.S_ISDIR(current_stat.st_mode)
            or stat.S_ISLNK(current_stat.st_mode)
            or resolved != current
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark output parent is invalid")


def validate_latency_output_path(path: Path) -> Path:
    """Confine the create-only receipt to Model 1's ignored latency artifact root."""

    target = Path(path)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output path is invalid")
    try:
        root_stat = LATENCY_OUTPUT_ROOT.lstat()
        root = LATENCY_OUTPUT_ROOT.resolve(strict=True)
        parent = target.parent.resolve(strict=True)
    except OSError as error:
        raise BrainError(
            "BENCHMARK_INVALID", 400, "benchmark output root is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_ISLNK(root_stat.st_mode)
        or parent != target.parent
        or parent != root
        and root not in parent.parents
        or target.name.startswith(".env")
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output path is outside authority")
    return parent / target.name


def _turn(
    *,
    service: MetisBrainService,
    runtime: MlxBrainModelRuntime,
    case: LatencyCase,
    pair: int,
    arm: str,
    tenant_id: str,
    tenant_root: Path,
    timeout_seconds: float,
    ordinal: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manager = service.app.manager
    before = capture_tenant_guard(
        root=tenant_root,
        tenant_alias=case.tenant_alias,
        tenant_id=tenant_id,
        target_path=case.target["relative_path"],
    )
    opened = manager.create_session(
        client_id=case.client_id,
        tenant_alias=case.tenant_alias,
        requested_capabilities=BENCHMARK_CAPABILITIES,
    )
    try:
        with manager.operation(
            session_id=opened.session_id,
            token=opened.token,
            capability="context.read",
            expected_revision=opened.context_revision,
        ) as lease:
            context = lease.snapshot.public_payload()
        files = {
            item["path"]: item["sha256"]
            for item in context["files"]
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
        }
        current_target = files.get(case.target["relative_path"])
        if (case.target["mode"] == "existing") != (current_target is not None):
            raise BrainError("BENCHMARK_INVALID", 409, "benchmark target state differs")
        target = validate_target(
            {
                **case.target,
                "base_sha256": current_target if case.target["mode"] == "existing" else None,
            }
        )
        request = TurnRequest.parse(
            {
                "schema_version": 2,
                "request_id": str(uuid.uuid4()),
                "expected_context_revision": context["revision"],
                "expected_semantic_source_revision": context["semantic_source_revision"],
                "intent": case.intent,
                "instruction": case.instruction,
                "target": target,
                "basis": None,
                "clarification_response": None,
            }
        )
        started = time.monotonic()
        record = service.app.turns.submit(
            session_id=opened.session_id,
            token=opened.token,
            request=request,
        )
        with record.condition:
            completed = record.condition.wait_for(
                lambda: record.terminal is not None,
                timeout=timeout_seconds,
            )
        turn_ms = max(0, int((time.monotonic() - started) * 1000))
        if not completed or record.terminal is None:
            raise BrainError("BENCHMARK_INVALID", 504, "benchmark turn timed out")
        terminal = copy.deepcopy(record.terminal)
        events = copy.deepcopy(record.events)
        after = capture_tenant_guard(
            root=tenant_root,
            tenant_alias=case.tenant_alias,
            tenant_id=tenant_id,
            target_path=case.target["relative_path"],
        )
        observation = observation_from_terminal(
            pair=pair,
            arm=arm,
            # ``request_id`` is intentionally unique per isolated session.  The
            # product-owned fingerprint binds every other client request field,
            # including both authority revisions and the exact target base hash.
            request_sha256=request.request_fingerprint,
            runtime_identity={
                "model_revision": runtime.model_revision,
                "adapter_sha256": runtime.adapter_sha256,
                "worker_sha256": runtime.worker_sha256,
                "prompt_prefix_sha256": runtime.prompt_prefix_sha256,
            },
            tenant_before=before,
            tenant_after=after,
            terminal=terminal,
            events=events,
            turn_ms=turn_ms,
            shape_contract=case.shape_contract,
            ordinal=ordinal,
        )
        return observation, context
    finally:
        manager.close(session_id=opened.session_id, token=opened.token)


def run_latency_benchmark(
    *, config_path: Path, case_path: Path, output_path: Path
) -> dict[str, Any]:
    _provision_latency_output_parent(Path(output_path))
    output = validate_latency_output_path(Path(output_path))
    config = load_brain_config(Path(config_path))
    case = load_latency_case(Path(case_path))
    model1_guard = capture_model1_guard()
    _alias, tenant_id, tenant_root = _grant(config, case)
    if config.model is None:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark model is unavailable")
    lazy_config = replace(config, port=0, model=replace(config.model, warmup="lazy"))
    initial_guard = capture_tenant_guard(
        root=tenant_root,
        tenant_alias=case.tenant_alias,
        tenant_id=tenant_id,
        target_path=case.target["relative_path"],
    )
    observations: list[dict[str, Any]] = []
    frozen_context: dict[str, Any] | None = None
    frozen_runtime: dict[str, str] | None = None
    decode_preflight_sha256: str | None = None
    decode_preflight_evidence: list[dict[str, Any]] | None = None
    decode_preflight_source_sha256: str | None = None
    decode_preflight_compiled_endpoint_sha256: str | None = None
    decode_preflight_processing_route: str | None = None
    decode_preflight_intent_compiler_sha256: str | None = None
    timeout_seconds = min(900.0, config.model.timeout_seconds + 300.0)
    retrieval_prewarm_ms: int | None = None
    # One persistent, prefix-qualified worker is the common physical runtime.
    # Each adjacent pair alternates AB/BA on that exact worker; the direct arm
    # declines the public-prefix clone while leaving every other variable fixed.
    runtime = _runtime(config, arm="prefix")
    try:
        runtime_identity = {
            "model_revision": runtime.model_revision,
            "adapter_sha256": runtime.adapter_sha256,
            "worker_sha256": runtime.worker_sha256,
            "prompt_prefix_sha256": runtime.prompt_prefix_sha256,
        }
        warmup_prefix_tokens = runtime.warmup_prefix_tokens
        if type(warmup_prefix_tokens) is not int or warmup_prefix_tokens < 1:
            raise BrainError("BENCHMARK_INVALID", 409, "prefix token roster is unavailable")
        frozen_runtime = runtime_identity
        with MetisBrainService(lazy_config, model=runtime) as service:
            retrieval_warmup = service.app.health()["semantic_retrieval"]["warmup"]
            if (
                not isinstance(retrieval_warmup, dict)
                or retrieval_warmup.get("policy") != "on_start"
                or retrieval_warmup.get("status") != "ready"
                or retrieval_warmup.get("tenant_count") != len(config.tenant_grants)
                or type(retrieval_warmup.get("duration_ms")) is not int
                or not 0 <= retrieval_warmup["duration_ms"] <= 600_000
            ):
                raise BrainError("BENCHMARK_INVALID", 409, "retrieval prewarm is unavailable")
            retrieval_prewarm_ms = retrieval_warmup["duration_ms"]
            preflights: list[dict[str, Any]] = []
            preflight_contexts: list[dict[str, Any]] = []
            for preflight_ordinal, preflight_arm in enumerate(ARMS, start=1):
                runtime._set_cache_mode_for_qualification(  # noqa: SLF001
                    "prefix" if preflight_arm == "prefix" else "disabled"
                )
                preflight, preflight_context = _turn(
                    service=service,
                    runtime=runtime,
                    case=case,
                    pair=1,
                    arm=preflight_arm,
                    tenant_id=tenant_id,
                    tenant_root=tenant_root,
                    timeout_seconds=timeout_seconds,
                    ordinal=preflight_ordinal,
                )
                preflights.append(preflight)
                preflight_contexts.append(preflight_context)
            frozen_context = preflight_contexts[0]
            if any(
                context.get(key) != frozen_context.get(key)
                for context in preflight_contexts[1:]
                for key in ("revision", "semantic_source_revision", "toolchain_binding")
            ):
                raise BrainError("BENCHMARK_INVALID", 409, "decode preflight context drifted")
            preflight_fixed = (
                "request_sha256",
                "source_sha256",
                "compiled_endpoint_sha256",
                "grounding_selections_sha256",
                "shape_contract_sha256",
                "processing_route",
                "intent_compiler_sha256",
                "event_roster_sha256",
                "model_revision",
                "adapter_sha256",
                "worker_sha256",
                "prompt_prefix_sha256",
            )
            if (
                any(
                    preflight[key] != preflights[0][key]
                    for preflight in preflights[1:]
                    for key in preflight_fixed
                )
                or preflights[0]["grounding_selections_sha256"] != case.expected_grounding_sha256
                or preflights[0]["shape_contract_sha256"] != case.expected_shape_contract_sha256
            ):
                raise BrainError("BENCHMARK_INVALID", 409, "decode preflights failed their oracle")
            decode_preflight_source_sha256 = preflights[0]["source_sha256"]
            decode_preflight_compiled_endpoint_sha256 = preflights[0]["compiled_endpoint_sha256"]
            decode_preflight_processing_route = preflights[0]["processing_route"]
            decode_preflight_intent_compiler_sha256 = preflights[0]["intent_compiler_sha256"]
            decode_preflight_evidence = [
                {
                    "arm": preflight["arm"],
                    **{key: preflight[key] for key in preflight_fixed},
                }
                for preflight in preflights
            ]
            decode_preflight_sha256 = canonical_sha256(decode_preflight_evidence)
            ordinal = 0
            for pair in range(1, case.pairs + 1):
                pair_order = case.arm_order if pair % 2 else tuple(reversed(case.arm_order))
                for arm in pair_order:
                    ordinal += 1
                    runtime._set_cache_mode_for_qualification(  # noqa: SLF001 - bounded A/B seam
                        "prefix" if arm == "prefix" else "disabled"
                    )
                    observation, context = _turn(
                        service=service,
                        runtime=runtime,
                        case=case,
                        pair=pair,
                        arm=arm,
                        tenant_id=tenant_id,
                        tenant_root=tenant_root,
                        timeout_seconds=timeout_seconds,
                        ordinal=ordinal,
                    )
                    if any(
                        context.get(key) != frozen_context.get(key)
                        for key in (
                            "revision",
                            "semantic_source_revision",
                            "toolchain_binding",
                        )
                    ):
                        raise BrainError("BENCHMARK_INVALID", 409, "benchmark context drifted")
                    observations.append(observation)
    finally:
        runtime.close()
    if runtime.model_loaded:
        raise BrainError("BENCHMARK_INVALID", 500, "benchmark worker did not close")
    final_guard = capture_tenant_guard(
        root=tenant_root,
        tenant_alias=case.tenant_alias,
        tenant_id=tenant_id,
        target_path=case.target["relative_path"],
    )
    if (
        final_guard != initial_guard
        or capture_model1_guard() != model1_guard
        or frozen_context is None
        or frozen_runtime is None
        or retrieval_prewarm_ms is None
        or decode_preflight_sha256 is None
        or decode_preflight_evidence is None
        or decode_preflight_source_sha256 is None
        or decode_preflight_compiled_endpoint_sha256 is None
        or decode_preflight_processing_route is None
        or decode_preflight_intent_compiler_sha256 is None
    ):
        raise BrainError("BENCHMARK_INVALID", 409, "benchmark authority changed")
    identity = {
        "benchmark_id": case.benchmark_id,
        "case_sha256": case.case_sha256,
        "model1_commit": model1_guard["commit"],
        "model1_tree": model1_guard["tree"],
        "seed": case.seed,
        "pairs": case.pairs,
        "arm_order": list(case.arm_order),
        "schedule_sha256": counterbalanced_schedule_sha256(
            pairs=case.pairs, arm_order=case.arm_order
        ),
        **frozen_runtime,
        "expected_prefix_tokens": warmup_prefix_tokens,
        "retrieval_prewarm_ms": retrieval_prewarm_ms,
        "decode_preflight_count": len(ARMS),
        "decode_preflights": decode_preflight_evidence,
        "decode_preflight_sha256": decode_preflight_sha256,
        "decode_preflight_source_sha256": decode_preflight_source_sha256,
        "decode_preflight_compiled_endpoint_sha256": (decode_preflight_compiled_endpoint_sha256),
        "tenant_commit": initial_guard["commit"],
        "tenant_tree": initial_guard["tree"],
        "tenant_roster_sha256": initial_guard["roster_sha256"],
        "tenant_status_sha256": initial_guard["status_sha256"],
        "target_sha256": initial_guard["target_sha256"],
        "context_revision": frozen_context["revision"],
        "semantic_source_revision": frozen_context["semantic_source_revision"],
        "toolchain_binding": frozen_context["toolchain_binding"],
        "request_sha256": observations[0]["request_sha256"],
        "expected_grounding_selections_sha256": case.expected_grounding_sha256,
        "expected_shape_contract_sha256": case.expected_shape_contract_sha256,
        "expected_processing_route": decode_preflight_processing_route,
        "expected_intent_compiler_sha256": decode_preflight_intent_compiler_sha256,
    }
    receipt = seal_latency_receipt(identity=identity, observations=observations)
    if validate_latency_output_path(output) != output:
        raise BrainError("BENCHMARK_INVALID", 409, "benchmark output authority changed")
    receipt_handle: LatencyReceiptHandle | None = None
    try:
        receipt_handle = write_latency_receipt(
            output,
            receipt,
            authority_root=LATENCY_OUTPUT_ROOT,
            hold_parent=True,
        )
        if receipt_handle is None:
            raise BrainError("BENCHMARK_INVALID", 500, "benchmark receipt handle is unavailable")
        post_write_guard = capture_tenant_guard(
            root=tenant_root,
            tenant_alias=case.tenant_alias,
            tenant_id=tenant_id,
            target_path=case.target["relative_path"],
        )
        if post_write_guard != initial_guard:
            raise BrainError("BENCHMARK_INVALID", 409, "tenant changed while writing receipt")
        if capture_model1_guard() != model1_guard:
            raise BrainError("BENCHMARK_INVALID", 409, "Model 1 changed while writing receipt")
        receipt_handle.commit()
    except BaseException:
        if receipt_handle is not None:
            receipt_handle.discard()
        raise
    return receipt


__all__ = [
    "LatencyCase",
    "capture_tenant_guard",
    "load_latency_case",
    "run_latency_benchmark",
    "validate_latency_output_path",
]
