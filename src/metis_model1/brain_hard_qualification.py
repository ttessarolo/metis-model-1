"""Headless qualification of the frozen complex Metis Brain prompt corpus.

The runner exercises the real numeric-loopback Brain HTTP protocol.  It never
requests an Apply capability and never writes the canonical tenant.  Detailed
prompts and generated Drafts remain in the ignored local artifact tree; tracked
evidence is limited to aggregate counts and receipt digests.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import secrets
import stat
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from metis_model1.brain_clarifications import CLARIFICATION_KINDS, OPTION_KINDS
from metis_model1.brain_latency_live import capture_model1_guard, capture_tenant_guard
from metis_model1.brain_output_contract import parse_output_request
from metis_model1.brain_protocol import (
    MAX_SOURCE_BYTES,
    BrainError,
    canonical_json,
    canonical_sha256,
    exact_fields,
    parse_json_object,
)
from metis_model1.brain_server import BrainConfig, MetisBrainService, parse_brain_config_bytes
from metis_model1.brain_structural_edit import (
    MAX_EDIT_OPERATIONS,
    STRUCTURAL_LOSSLESS_PROOF_CONTRACT,
)
from metis_model1.brain_turns import validate_target

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/metis-brain-hard-qualification"
EXPECTED_CORPUS_PATH = PROJECT_ROOT / "examples/metis-brain-hard-prompts.play-prod-v1.json"
EXPECTED_PLAN_PATH = PROJECT_ROOT / "examples/metis-brain-hard-qualification.play-prod-v1.json"
EXPECTED_V2_CORPUS_PATH = PROJECT_ROOT / "examples/metis-brain-hard-prompts.play-prod-v2.json"
EXPECTED_V2_PLAN_PATH = PROJECT_ROOT / "examples/metis-brain-hard-qualification.play-prod-v2.json"
EXPECTED_CONFIG_PATH = (
    PROJECT_ROOT / "examples/metis-brain-config.play-prod-hard-qualification.local.json"
)
EXPECTED_CORPUS_SHA256 = "sha256:6022ea8104a0b01deacd81bf4f46bd78d72154a308278081ecddfcc6f1bc119c"
# Filled from the reviewed, tracked bytes immediately before the live run.  A
# qualification plan/config cannot redefine its own oracle or runtime after
# those constants are sealed.
EXPECTED_PLAN_SHA256 = "sha256:f3aa5efbeed73b14f9805ee42b6906faa3bda2fdd8bab498ddc52323af5ccf5c"
EXPECTED_V2_CORPUS_SHA256 = (
    "sha256:656c59004142b6e49b2881da328149c801e8ff280959138507f9650591c12e4a"
)
EXPECTED_V2_PLAN_SHA256 = "sha256:e4f82fe1dd85653af8b537a2f133ae163b170bf9a7d9d59db2a1b1fddb9632a5"
EXPECTED_CONFIG_SHA256 = "sha256:b1e4256a4f1bdd11b3485b7554b6e9c1c8666c034947a99da48c1267f85e2842"
EXPECTED_CLIENT_ID = "brain-hard-qualification"
EXPECTED_MODEL_REVISION = "3e6447f082e89cc7f0bc6e5441afd38dfce760ff"
EXPECTED_ADAPTER_SHA256 = "sha256:5e65a0b48531ce9e2a9751c201f570f8793da87bd2a2a9446f461dbe0589dcfb"
EXPECTED_FLASH_REVISION = "475b9088d29754a3379866cf5aeb6b41acd313c2"
EXPECTED_FLASH_SCHEMA_SHA256 = (
    "sha256:972eb339d8f0f22f4d5dd43aa9f4f74ae49e2a6e2b3b7ff536a60444edd864fa"
)
EXPECTED_FLASH_DECODER = "llguidance-1.8.0"
EXPECTED_TOOLCHAIN_REVISION = "3fde0820c04244b011a2f7a9604c425891424b34"
EXPECTED_TOOLCHAIN_TREE = "432bd3babd9f4c2dfe6349288b12eba917d4fe73"
EXPECTED_NODE_MODULES_SHA256 = (
    "sha256:5ba3b1ef8e399260fa40c840fdeffd255931b37c01d284b4d445c0311533e7e5"
)
EXPECTED_RUNNER_SHA256 = "sha256:5497794fe0bbedf84639e40a2e7a8a9143feb661080510fc3b115642a690f432"
EXPECTED_V2_RUNNER_SHA256 = (
    "sha256:2ab8ebdf1fe74e29807d7ed1cd46e5b82de1cc40fc937f15975005f21738ad34"
)
EXPECTED_CAPABILITIES = frozenset(
    {"chat.read", "chat.turn", "context.read", "session.close", "session.read"}
)
MAX_INPUT_BYTES = 256 * 1024
MAX_HTTP_BYTES = 2 * 1024 * 1024
MAX_TURN_SECONDS = 960.0
MAX_CLARIFICATION_ROUNDS = 3
EXPECTED_DENOMINATOR = {
    "edit_cases": 10,
    "create_journeys": 10,
    "logical_create_turns": 40,
    "assessed_generated_draft_turns": 30,
    "logical_operator_messages": 50,
}
_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ENDPOINT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_CATALOG_SURFACE_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_.-]*)")
_STRUCTURAL_FACT_NAMES = frozenset(
    {
        "endpoint_name",
        "paginate",
        "catalog_refs",
        "context_names",
        "attribute_names",
        "block_names",
        "variant_names",
        "top_level_block_count",
        "variant_count",
        "guarded_variant_count",
        "empty_variant_count",
        "endpoint_take_count",
        "endpoint_take_counts",
        "use_count",
        "use_refs",
        "instance_arg_count",
        "view_all_count",
        "fallback_keys",
        "output_flow_count",
        "output_sequences",
        "ordering_keys",
        "ordering_signatures",
        "meta_templates",
        "search_detail_meta_count",
        "group_count",
        "expanded_take_count",
        "parameterized_block_count",
        "has_input_pipeline",
    }
)


@dataclass(frozen=True)
class HardQualificationProfile:
    profile_id: str
    corpus_path: Path
    corpus_relative_path: str
    corpus_sha256: str
    corpus_artifact_id: str
    corpus_artifact_version: int
    plan_path: Path
    plan_sha256: str
    qualification_id: str
    runner_sha256: str
    tenant_head: str
    tenant_tree: str
    require_structural_lossless_edits: bool
    require_reference_equivalence: bool
    promotable: bool


_V1_PROFILE = HardQualificationProfile(
    profile_id="play-prod-v1",
    corpus_path=EXPECTED_CORPUS_PATH,
    corpus_relative_path="examples/metis-brain-hard-prompts.play-prod-v1.json",
    corpus_sha256=EXPECTED_CORPUS_SHA256,
    corpus_artifact_id="metis-brain-hard-prompts.play-prod-v1",
    corpus_artifact_version=1,
    plan_path=EXPECTED_PLAN_PATH,
    plan_sha256=EXPECTED_PLAN_SHA256,
    qualification_id="metis-brain-hard-headless/play-prod-v1",
    runner_sha256=EXPECTED_RUNNER_SHA256,
    tenant_head="5f56bdfe27e3fb00b735db630a4eb5cdf5ab12c3",
    tenant_tree="03abf1a30603ff6cb59d55c32c3395cef868a218",
    require_structural_lossless_edits=False,
    require_reference_equivalence=True,
    promotable=True,
)
_V2_PROFILE = HardQualificationProfile(
    profile_id="play-prod-v2",
    corpus_path=EXPECTED_V2_CORPUS_PATH,
    corpus_relative_path="examples/metis-brain-hard-prompts.play-prod-v2.json",
    corpus_sha256=EXPECTED_V2_CORPUS_SHA256,
    corpus_artifact_id="metis-brain-hard-prompts.play-prod-v2",
    corpus_artifact_version=2,
    plan_path=EXPECTED_V2_PLAN_PATH,
    plan_sha256=EXPECTED_V2_PLAN_SHA256,
    qualification_id="metis-brain-hard-headless/play-prod-v2",
    runner_sha256=EXPECTED_V2_RUNNER_SHA256,
    tenant_head="98e78407f7286d2a9ac404dceb655fd1f6a9118e",
    tenant_tree="914785f55c2be453ee75a6314f4e9e77010eed25",
    require_structural_lossless_edits=True,
    require_reference_equivalence=False,
    promotable=False,
)
_PROFILES_BY_PATHS = {
    (profile.corpus_path, profile.plan_path): profile for profile in (_V1_PROFILE, _V2_PROFILE)
}


@dataclass(frozen=True)
class HardQualificationSpec:
    profile_id: str
    corpus_path: Path
    corpus_sha256: str
    corpus: dict[str, Any]
    plan_path: Path
    plan_sha256: str
    plan: dict[str, Any]
    config_path: Path
    config_sha256: str
    runtime_identity: dict[str, Any]
    tenant_root: Path
    tenant_alias: str
    tenant_id: str
    tenant_head: str
    tenant_tree: str
    require_structural_lossless_edits: bool
    require_reference_equivalence: bool
    promotable: bool


@dataclass(frozen=True)
class HttpResult:
    status: int
    payload: dict[str, Any]


def _safe_regular_bytes(
    path: Path,
    *,
    label: str,
    maximum: int = MAX_INPUT_BYTES,
    required_mode: int | None = None,
) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or any(part.startswith(".env") for part in candidate.parts):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, f"{label} path is invalid")
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
            or not 1 <= opened.st_size <= maximum
            or (required_mode is not None and stat.S_IMODE(opened.st_mode) != required_mode)
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, f"{label} is invalid")
        chunks: list[bytes] = []
        remaining = opened.st_size + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        named_after = candidate.lstat()
    except BrainError:
        raise
    except OSError as error:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
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
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, f"{label} changed while read")
    return raw


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _safe_relative_path(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or any(part in {"", ".", ".."} or part.startswith(".env") for part in value.split("/"))
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, f"{label} is invalid")
    return value


def _required_text(value: Any, *, label: str, maximum: int = MAX_SOURCE_BYTES) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, f"{label} is invalid")
    return value


def _apply_replacements(source: str, replacements: Sequence[Mapping[str, Any]]) -> str:
    lines = source.splitlines(keepends=True)
    seen: set[int] = set()
    for item in replacements:
        if set(item) != {"line", "before", "after"}:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "edit replacement is invalid")
        line = item["line"]
        before = item["before"]
        after = item["after"]
        if (
            type(line) is not int
            or line < 1
            or line > len(lines)
            or line in seen
            or not isinstance(before, str)
            or not before
            or not isinstance(after, str)
            or not after
            or before == after
            or lines[line - 1].count(before) != 1
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "edit replacement does not bind")
        lines[line - 1] = lines[line - 1].replace(before, after, 1)
        seen.add(line)
    return "".join(lines)


def _validate_corpus(
    value: dict[str, Any], *, profile: HardQualificationProfile
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exact_fields(
        value,
        required={
            "artifact_id",
            "artifact_version",
            "language",
            "purpose",
            "safety_boundary",
            "census",
            "tenant_snapshot",
            "shared_oracle_contract",
            "endpoints",
            "zero_generation_contract",
            "zero_generation_scenarios",
        },
        label="hard prompt corpus",
    )
    if (
        value["artifact_id"] != profile.corpus_artifact_id
        or value["artifact_version"] != profile.corpus_artifact_version
        or value["language"] != "en"
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "hard prompt corpus is unsupported")
    safety = value["safety_boundary"]
    if (
        not isinstance(safety, dict)
        or safety.get("tenant_access") != "read_only"
        or safety.get("model_or_network_execution") is not False
        or safety.get("apply_authorized") is not False
        or safety.get("contains_secrets") is not False
        or safety.get("contains_credentials") is not False
        or safety.get("contains_raw_live_payloads") is not False
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "corpus safety boundary is invalid")
    endpoints = value["endpoints"]
    journeys = value["zero_generation_scenarios"]
    if not isinstance(endpoints, list) or len(endpoints) != 10:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "edit roster is invalid")
    if not isinstance(journeys, list) or len(journeys) != 10:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "journey roster is invalid")
    endpoint_names: list[str] = []
    endpoint_paths: list[str] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "edit case is invalid")
        identity = endpoint.get("endpoint_identity")
        if not isinstance(identity, dict):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "endpoint identity is invalid")
        qualified = identity.get("qualified")
        path = _safe_relative_path(endpoint.get("source_path"), label="source path")
        if not isinstance(qualified, str) or _ENDPOINT_RE.fullmatch(qualified) is None:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "endpoint name is invalid")
        _required_text(endpoint.get("operator_edit_prompt_it"), label="edit prompt")
        source_hash = endpoint.get("source_sha256")
        if not isinstance(source_hash, str) or _HASH_RE.fullmatch(source_hash) is None:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "source hash is invalid")
        lossless = endpoint.get("lossless_path")
        expected_lossless_decision = (
            "fail_closed_fallback"
            if profile.corpus_artifact_version == 1
            else "compiler_owned_structural_lossless"
        )
        if (
            not isinstance(lossless, dict)
            or set(lossless) != {"decision", "reason", "eligible_only_if"}
            or lossless.get("decision") != expected_lossless_decision
            or not isinstance(lossless.get("reason"), str)
            or not lossless["reason"]
            or not isinstance(lossless.get("eligible_only_if"), str)
            or not lossless["eligible_only_if"]
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "lossless decision is invalid")
        endpoint_names.append(qualified)
        endpoint_paths.append(path)
    if len(set(endpoint_names)) != 10 or len(set(endpoint_paths)) != 10:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "edit roster is duplicated")
    journey_names: list[str] = []
    for journey in journeys:
        if not isinstance(journey, dict):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "journey is invalid")
        qualified = journey.get("endpoint_qualified")
        turns = journey.get("turns")
        if qualified not in endpoint_names or not isinstance(turns, list) or len(turns) != 4:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "journey roster is invalid")
        if [item.get("turn") for item in turns if isinstance(item, dict)] != [1, 2, 3, 4]:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "journey order is invalid")
        if [item.get("expected_brain_action") for item in turns] != [
            "clarify",
            "Draft",
            "Draft",
            "Draft",
        ]:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "journey actions are invalid")
        for turn in turns:
            _required_text(turn.get("user_message"), label="journey prompt")
        journey_names.append(qualified)
    if journey_names != endpoint_names:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "journey order differs from edits")
    return endpoints, journeys


def load_hard_qualification(corpus_path: Path, plan_path: Path) -> HardQualificationSpec:
    requested_corpus = Path(corpus_path)
    requested_plan = Path(plan_path)
    profile = _PROFILES_BY_PATHS.get((requested_corpus, requested_plan))
    if profile is None:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "qualification input path differs")
    corpus_raw = _safe_regular_bytes(requested_corpus, label="hard prompt corpus")
    corpus_sha = _sha256(corpus_raw)
    if corpus_sha != profile.corpus_sha256:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "hard prompt corpus hash differs")
    corpus = parse_json_object(corpus_raw, label="hard prompt corpus")
    endpoints, journeys = _validate_corpus(corpus, profile=profile)

    plan_raw = _safe_regular_bytes(requested_plan, label="hard qualification plan")
    plan_sha = _sha256(plan_raw)
    if plan_sha != profile.plan_sha256:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "qualification plan hash differs")
    plan = parse_json_object(plan_raw, label="hard qualification plan")
    exact_fields(
        plan,
        required={
            "schema_version",
            "qualification_id",
            "corpus",
            "authority",
            "config",
            "client",
            "execution_boundary",
            "runtime_identity",
            "edit_oracles",
            "create_targets",
            "create_oracles",
        },
        label="hard qualification plan",
    )
    if plan["schema_version"] != 1 or plan["qualification_id"] != profile.qualification_id:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "qualification plan is unsupported")
    corpus_binding = plan["corpus"]
    if (
        not isinstance(corpus_binding, dict)
        or corpus_binding.get("artifact_id") != corpus["artifact_id"]
        or corpus_binding.get("sha256") != corpus_sha
        or corpus_binding.get("path") != profile.corpus_relative_path
        or (PROJECT_ROOT / corpus_binding["path"]).resolve(strict=True)
        != Path(corpus_path).resolve(strict=True)
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "corpus binding differs")

    config_binding = plan["config"]
    if not isinstance(config_binding, dict):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "config binding is invalid")
    exact_fields(config_binding, required={"path", "sha256"}, label="config binding")
    config_relative = _safe_relative_path(config_binding["path"], label="config path")
    config_path = PROJECT_ROOT / config_relative
    config_sha = config_binding["sha256"]
    if (
        config_relative != "examples/metis-brain-config.play-prod-hard-qualification.local.json"
        or not isinstance(config_sha, str)
        or _HASH_RE.fullmatch(config_sha) is None
        or config_sha != EXPECTED_CONFIG_SHA256
        or config_path != EXPECTED_CONFIG_PATH
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "config binding differs")

    runtime_identity = plan["runtime_identity"]
    expected_runtime = {
        "model": {
            "model_revision": EXPECTED_MODEL_REVISION,
            "adapter_sha256": EXPECTED_ADAPTER_SHA256,
        },
        "intent_compiler": {
            "model_revision": EXPECTED_FLASH_REVISION,
            "schema_sha256": EXPECTED_FLASH_SCHEMA_SHA256,
            "decoder": EXPECTED_FLASH_DECODER,
        },
        "semantic_retrieval": {
            "enabled": True,
            "schema": 2,
            "implementation": "Schema2SnapshotRetriever",
        },
        "toolchain": {
            "revision": EXPECTED_TOOLCHAIN_REVISION,
            "tree": EXPECTED_TOOLCHAIN_TREE,
            "node_modules_sha256": EXPECTED_NODE_MODULES_SHA256,
            "runner_sha256": profile.runner_sha256,
        },
    }
    if runtime_identity != expected_runtime:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "runtime identity differs")

    authority = plan["authority"]
    snapshot = corpus["tenant_snapshot"]
    if not isinstance(authority, dict) or not isinstance(snapshot, dict):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "tenant authority is invalid")
    tenant_root = Path(authority.get("root", ""))
    if (
        not tenant_root.is_absolute()
        or tenant_root.resolve(strict=True) != tenant_root
        or authority.get("root") != snapshot.get("repository")
        or authority.get("head") != snapshot.get("head")
        or authority.get("head") != profile.tenant_head
        or not isinstance(authority.get("tree"), str)
        or len(authority["tree"]) != 40
        or authority.get("tree") != profile.tenant_tree
        or authority.get("tenant_alias") != "play-prod"
        or authority.get("tenant_id") != "play-prod-v2"
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "tenant authority differs")
    client = plan["client"]
    if (
        not isinstance(client, dict)
        or client.get("client_id") != EXPECTED_CLIENT_ID
        or set(client.get("capabilities", [])) != EXPECTED_CAPABILITIES
        or any("apply" in item for item in client.get("capabilities", []))
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "qualification client is invalid")
    boundary = plan["execution_boundary"]
    if boundary != {
        "local_mlx": True,
        "loopback_http": True,
        "external_network": False,
        "apply": False,
        "canonical_tenant_write": False,
        "mandate_date": "2026-09-04",
    }:
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "execution boundary is invalid")

    edit_oracles = plan["edit_oracles"]
    create_targets = plan["create_targets"]
    create_oracles = plan["create_oracles"]
    if (
        not isinstance(edit_oracles, list)
        or not isinstance(create_targets, list)
        or not isinstance(create_oracles, list)
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "qualification rosters are invalid")
    endpoint_map = {item["endpoint_identity"]["qualified"]: item for item in endpoints}
    oracle_names: list[str] = []
    for oracle in edit_oracles:
        if not isinstance(oracle, dict):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "edit oracle is invalid")
        allowed = {"endpoint", "source_path", "replacements", "corpus_erratum"}
        if not {"endpoint", "source_path", "replacements"}.issubset(oracle) or not set(
            oracle
        ).issubset(allowed):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "edit oracle is invalid")
        endpoint = oracle["endpoint"]
        source_path = _safe_relative_path(oracle["source_path"], label="oracle source path")
        corpus_case = endpoint_map.get(endpoint)
        if corpus_case is None or corpus_case["source_path"] != source_path:
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "edit oracle differs")
        source_raw = _safe_regular_bytes(
            tenant_root / source_path,
            label="pinned endpoint source",
            maximum=MAX_SOURCE_BYTES,
        )
        if _sha256(source_raw) != corpus_case["source_sha256"]:
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "endpoint source hash differs")
        try:
            source = source_raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BrainError(
                "HARD_QUALIFICATION_INVALID", 400, "endpoint source is not UTF-8"
            ) from error
        replacements = oracle["replacements"]
        if not isinstance(replacements, list) or not replacements:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "edit replacements are invalid")
        _apply_replacements(source, replacements)
        oracle_names.append(endpoint)
    target_names: list[str] = []
    target_paths: list[str] = []
    for item in create_targets:
        if not isinstance(item, dict):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "create target is invalid")
        exact_fields(
            item,
            required={
                "source_endpoint",
                "reference_source_path",
                "relative_path",
                "endpoint",
            },
            optional={"reference_replacements"},
            label="create target",
        )
        source_endpoint = item["source_endpoint"]
        reference_source_path = _safe_relative_path(
            item["reference_source_path"], label="reference source path"
        )
        target = validate_target(
            {
                "mode": "create",
                "relative_path": item["relative_path"],
                "endpoint": item["endpoint"],
                "base_sha256": None,
            }
        )
        source_case = endpoint_map.get(source_endpoint)
        if (
            source_case is None
            or source_case["source_path"] != reference_source_path
            or target["endpoint"] is None
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "create target differs")
        reference_raw = _safe_regular_bytes(
            tenant_root / reference_source_path,
            label="reference endpoint source",
            maximum=MAX_SOURCE_BYTES,
        )
        if _sha256(reference_raw) != source_case["source_sha256"]:
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "reference source hash differs")
        reference_replacements = item.get("reference_replacements", [])
        if not isinstance(reference_replacements, list):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "reference replacements differ")
        if reference_replacements:
            try:
                reference_text = reference_raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise BrainError(
                    "HARD_QUALIFICATION_INVALID", 400, "reference source is not UTF-8"
                ) from error
            _apply_replacements(reference_text, reference_replacements)
        if (tenant_root / target["relative_path"]).exists():
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "create target already exists")
        target_names.append(source_endpoint)
        target_paths.append(target["relative_path"])

    create_oracle_names: list[str] = []
    for oracle in create_oracles:
        if not isinstance(oracle, dict):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "create oracle is invalid")
        exact_fields(oracle, required={"source_endpoint", "turns"}, label="create oracle")
        source_endpoint = oracle["source_endpoint"]
        turns = oracle["turns"]
        if source_endpoint not in endpoint_map or not isinstance(turns, list) or len(turns) != 3:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "create oracle roster differs")
        if [item.get("turn") for item in turns if isinstance(item, dict)] != [2, 3, 4]:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "create oracle turn order differs")
        check_ids: set[str] = set()
        for turn in turns:
            if not isinstance(turn, dict):
                raise BrainError("HARD_QUALIFICATION_INVALID", 400, "create oracle turn is invalid")
            exact_fields(turn, required={"turn", "checks"}, label="create oracle turn")
            checks = turn["checks"]
            if not isinstance(checks, list) or not checks:
                raise BrainError(
                    "HARD_QUALIFICATION_INVALID", 400, "create oracle checks are absent"
                )
            for check in checks:
                if not isinstance(check, dict) or set(check) != {"id", "fact", "op", "value"}:
                    raise BrainError(
                        "HARD_QUALIFICATION_INVALID", 400, "structural check is invalid"
                    )
                check_id = check["id"]
                fact = check["fact"]
                op = check["op"]
                expected = check["value"]
                if (
                    not isinstance(check_id, str)
                    or not check_id
                    or check_id in check_ids
                    or fact not in _STRUCTURAL_FACT_NAMES
                    or op not in {"equals", "gte", "lte", "contains_all", "excludes_all"}
                    or (op in {"gte", "lte"} and type(expected) is not int)
                    or (op in {"contains_all", "excludes_all"} and not isinstance(expected, list))
                ):
                    raise BrainError(
                        "HARD_QUALIFICATION_INVALID", 400, "structural check is invalid"
                    )
                check_ids.add(check_id)
        create_oracle_names.append(source_endpoint)
    endpoint_names = list(endpoint_map)
    if (
        oracle_names != endpoint_names
        or target_names != endpoint_names
        or create_oracle_names != endpoint_names
        or len(set(target_paths)) != 10
        or [item["endpoint_qualified"] for item in journeys] != endpoint_names
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "qualification rosters differ")
    return HardQualificationSpec(
        profile_id=profile.profile_id,
        corpus_path=Path(corpus_path).resolve(strict=True),
        corpus_sha256=corpus_sha,
        corpus=corpus,
        plan_path=Path(plan_path).resolve(strict=True),
        plan_sha256=plan_sha,
        plan=plan,
        config_path=config_path.resolve(strict=True),
        config_sha256=config_sha,
        runtime_identity=dict(runtime_identity),
        tenant_root=tenant_root,
        tenant_alias=authority["tenant_alias"],
        tenant_id=authority["tenant_id"],
        tenant_head=authority["head"],
        tenant_tree=authority["tree"],
        require_structural_lossless_edits=profile.require_structural_lossless_edits,
        require_reference_equivalence=profile.require_reference_equivalence,
        promotable=profile.promotable,
    )


def validate_hard_config(config: BrainConfig, spec: HardQualificationSpec) -> None:
    policies = [item for item in config.client_policies if item.client_id == EXPECTED_CLIENT_ID]
    tenants = [item for item in config.tenant_grants if item[0] == spec.tenant_alias]
    runtime_root = config.runtime_root
    expected_runtime_root = OUTPUT_ROOT / "runtime"
    if (
        config.host != "127.0.0.1"
        or config.port != 0
        or len(config.tenant_grants) != 1
        or len(tenants) != 1
        or tenants[0] != (spec.tenant_alias, spec.tenant_id, spec.tenant_root)
        or len(config.client_policies) != 1
        or len(policies) != 1
        or policies[0].tenant_aliases != frozenset({spec.tenant_alias})
        or policies[0].capabilities != EXPECTED_CAPABILITIES
        or config.model is None
        or config.model.warmup != "on_start"
        or config.retrieval is None
        or not config.retrieval.schema2
        or config.retrieval.warmup != "on_start"
        or config.intent_compiler is None
        or config.intent_compiler.warmup != "on_start"
        or config.intent_compiler.mode != "assist_on_unresolved"
        or runtime_root != expected_runtime_root
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "Brain config is not qualified")
    if runtime_root.exists() or runtime_root.is_symlink():
        try:
            status = runtime_root.lstat()
        except OSError as error:
            raise BrainError(
                "HARD_QUALIFICATION_INVALID", 400, "runtime root is unavailable"
            ) from error
        if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode):
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "runtime root is not real")


def _qualified_health_identity(
    health: Mapping[str, Any], compiler_pin: Mapping[str, Any]
) -> dict[str, Any]:
    model = health.get("model_identity")
    retrieval = health.get("semantic_retrieval")
    intent = health.get("intent_compiler")
    intent_identity = intent.get("identity") if isinstance(intent, Mapping) else None
    toolchain = {
        key: compiler_pin.get(key)
        for key in ("revision", "tree", "node_modules_sha256", "runner_sha256")
    }
    return {
        "model": dict(model) if isinstance(model, Mapping) else None,
        "intent_compiler": dict(intent_identity) if isinstance(intent_identity, Mapping) else None,
        "semantic_retrieval": {
            key: retrieval.get(key) if isinstance(retrieval, Mapping) else None
            for key in ("enabled", "schema", "implementation")
        },
        "toolchain": toolchain,
    }


def _validate_qualified_health(
    health: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, Any],
    compiler_pin: Mapping[str, Any],
) -> dict[str, Any]:
    retrieval = health.get("semantic_retrieval")
    intent = health.get("intent_compiler")
    model_warmup = health.get("model_warmup")
    identity = _qualified_health_identity(health, compiler_pin)
    if (
        health.get("status") != "ready"
        or health.get("service") != "metis-brain"
        or health.get("model_loaded") is not True
        or not isinstance(model_warmup, Mapping)
        or model_warmup.get("policy") != "on_start"
        or model_warmup.get("status") != "ready"
        or model_warmup.get("prefix_cache_ready") is not True
        or not isinstance(retrieval, Mapping)
        or not isinstance(retrieval.get("warmup"), Mapping)
        or retrieval["warmup"].get("status") != "ready"
        or not isinstance(intent, Mapping)
        or intent.get("enabled") is not True
        or intent.get("mode") != "assist_on_unresolved"
        or intent.get("model_loaded") is not True
        or not isinstance(intent.get("warmup"), Mapping)
        or intent["warmup"].get("status") != "ready"
        or identity != expected_identity
    ):
        raise BrainError("HARD_QUALIFICATION_RUNTIME", 503, "Brain identity is not qualified")
    return identity


class HeadlessBrainClient:
    """Small strict client for the public Brain loopback contract."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        bootstrap_token: str,
        client_id: str = EXPECTED_CLIENT_ID,
        capabilities: frozenset[str] = EXPECTED_CAPABILITIES,
    ) -> None:
        if host != "127.0.0.1" or not 1 <= port <= 65535 or not bootstrap_token:
            raise BrainError("HARD_QUALIFICATION_INVALID", 500, "Brain address is invalid")
        if (
            not isinstance(client_id, str)
            or not client_id
            or len(client_id) > 96
            or type(capabilities) is not frozenset
            or not capabilities
            or any(not isinstance(item, str) or not item for item in capabilities)
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 500, "Brain client is invalid")
        self.host = host
        self.port = port
        self._bootstrap_token = bootstrap_token
        self._client_id = client_id
        self._capabilities = capabilities

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> HttpResult:
        if not path.startswith("/v1/") or "?" in path or "#" in path:
            raise BrainError("HARD_QUALIFICATION_INVALID", 500, "Brain route is invalid")
        headers: dict[str, str] = {}
        raw: bytes | None = None
        if body is not None:
            raw = canonical_json(dict(body))
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request(method, path, body=raw, headers=headers)
            response = connection.getresponse()
            payload_raw = response.read(MAX_HTTP_BYTES + 1)
            if len(payload_raw) > MAX_HTTP_BYTES:
                raise BrainError("HARD_QUALIFICATION_HTTP", 502, "Brain response is too large")
            payload = parse_json_object(payload_raw, label="Brain response") if payload_raw else {}
            return HttpResult(response.status, payload)
        except BrainError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise BrainError("HARD_QUALIFICATION_HTTP", 502, "Brain HTTP request failed") from error
        finally:
            connection.close()

    def health(self) -> dict[str, Any]:
        result = self.request("GET", "/v1/health")
        if result.status != 200:
            raise BrainError("HARD_QUALIFICATION_HTTP", result.status, "Brain health failed")
        return result.payload

    def open_session(self, *, tenant_alias: str) -> dict[str, Any]:
        result = self.request(
            "POST",
            "/v1/sessions",
            token=self._bootstrap_token,
            body={
                "client_id": self._client_id,
                "tenant_alias": tenant_alias,
                "capabilities": sorted(self._capabilities),
            },
        )
        if result.status != 201 or not isinstance(result.payload.get("session"), dict):
            raise BrainError("HARD_QUALIFICATION_HTTP", result.status, "session open failed")
        return dict(result.payload["session"])

    def context(self, session: Mapping[str, Any]) -> dict[str, Any]:
        result = self.request(
            "POST",
            f"/v1/sessions/{session['id']}/context",
            token=str(session["token"]),
            body={"expected_revision": session["context_revision"]},
        )
        if result.status != 200:
            raise BrainError("HARD_QUALIFICATION_HTTP", result.status, "context read failed")
        return result.payload

    def submit(self, session: Mapping[str, Any], body: Mapping[str, Any]) -> str:
        result = self.request(
            "POST",
            f"/v1/sessions/{session['id']}/turns",
            token=str(session["token"]),
            body=body,
        )
        if result.status != 202 or not isinstance(result.payload.get("turn_id"), str):
            code = result.payload.get("error", {}).get("code", "HARD_QUALIFICATION_HTTP")
            raise BrainError(str(code), result.status, "turn submit failed")
        return result.payload["turn_id"]

    def answer(
        self,
        session: Mapping[str, Any],
        *,
        parent_turn_id: str,
        clarification_id: str,
        answer: Mapping[str, Any],
    ) -> str:
        result = self.request(
            "POST",
            f"/v1/sessions/{session['id']}/turns/{parent_turn_id}/answer",
            token=str(session["token"]),
            body={
                "schema_version": 1,
                "request_id": str(uuid.uuid4()),
                "clarification_id": clarification_id,
                "answer": dict(answer),
            },
        )
        if result.status != 202 or not isinstance(result.payload.get("turn_id"), str):
            code = result.payload.get("error", {}).get("code", "HARD_QUALIFICATION_HTTP")
            raise BrainError(str(code), result.status, "clarification answer failed")
        return result.payload["turn_id"]

    def answer_v2(
        self,
        session: Mapping[str, Any],
        *,
        parent_turn_id: str,
        clarification_id: str,
        message: str | None,
        answers: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        """Continue a dialogue with the next operator message through schema 2."""

        result = self.request(
            "POST",
            f"/v1/sessions/{session['id']}/turns/{parent_turn_id}/answer",
            token=str(session["token"]),
            body={
                "schema_version": 2,
                "request_id": str(uuid.uuid4()),
                "clarification_id": clarification_id,
                "message": message,
                "answers": [dict(answer) for answer in answers],
            },
        )
        if result.status != 202 or not isinstance(result.payload.get("turn_id"), str):
            code = result.payload.get("error", {}).get("code", "HARD_QUALIFICATION_HTTP")
            raise BrainError(str(code), result.status, "clarification answer failed")
        return result.payload["turn_id"]

    def wait_terminal(
        self,
        session: Mapping[str, Any],
        turn_id: str,
        *,
        timeout: float = MAX_TURN_SECONDS,
    ) -> tuple[dict[str, Any], int]:
        started = time.monotonic()
        while True:
            result = self.request(
                "GET",
                f"/v1/sessions/{session['id']}/turns/{turn_id}",
                token=str(session["token"]),
                timeout=35.0,
            )
            if result.status != 200:
                raise BrainError("HARD_QUALIFICATION_HTTP", result.status, "turn read failed")
            status = result.payload.get("status")
            if status in {"completed", "failed", "cancelled"}:
                return result.payload, max(0, int((time.monotonic() - started) * 1000))
            if time.monotonic() - started >= timeout:
                raise BrainError("HARD_QUALIFICATION_TIMEOUT", 504, "turn timed out")
            time.sleep(0.2)

    def events(self, session: Mapping[str, Any], turn_id: str) -> list[dict[str, Any]]:
        path = f"/v1/sessions/{session['id']}/turns/{turn_id}/events"
        headers = {"Authorization": f"Bearer {session['token']}"}
        connection = http.client.HTTPConnection(self.host, self.port, timeout=35.0)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_HTTP_BYTES + 1)
            if response.status != 200 or len(raw) > MAX_HTTP_BYTES:
                raise BrainError("HARD_QUALIFICATION_HTTP", response.status, "event read failed")
        except BrainError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise BrainError("HARD_QUALIFICATION_HTTP", 502, "event read failed") from error
        finally:
            connection.close()
        events: list[dict[str, Any]] = []
        for block in raw.decode("utf-8", "strict").strip().split("\n\n"):
            if not block:
                continue
            rows = block.splitlines()
            event = next((row[7:] for row in rows if row.startswith("event: ")), None)
            data = next((row[6:] for row in rows if row.startswith("data: ")), None)
            if event is None or data is None:
                raise BrainError("HARD_QUALIFICATION_HTTP", 502, "event stream is invalid")
            payload = parse_json_object(data.encode("utf-8"), label="Brain event")
            events.append({"event": event, "data": payload})
        return events

    def close_session(self, session: Mapping[str, Any]) -> None:
        result = self.request(
            "DELETE",
            f"/v1/sessions/{session['id']}",
            token=str(session["token"]),
        )
        if result.status != 200:
            raise BrainError("HARD_QUALIFICATION_HTTP", result.status, "session close failed")


def _bootstrap_token(service: MetisBrainService) -> str:
    raw = _safe_regular_bytes(
        service.runtime.bootstrap_file,
        label="bootstrap file",
        maximum=256,
        required_mode=0o600,
    )
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise BrainError("HARD_QUALIFICATION_INVALID", 500, "bootstrap token is invalid") from error
    if not token or any(character.isspace() for character in token):
        raise BrainError("HARD_QUALIFICATION_INVALID", 500, "bootstrap token is invalid")
    return token


def _files(context: Mapping[str, Any]) -> dict[str, str]:
    items = context.get("files")
    if not isinstance(items, list):
        raise BrainError("HARD_QUALIFICATION_INVALID", 500, "context file roster is invalid")
    result: dict[str, str] = {}
    for item in items:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or _HASH_RE.fullmatch(item["sha256"]) is None
            or item["path"] in result
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 500, "context file roster is invalid")
        result[item["path"]] = item["sha256"]
    return result


def _turn_body(
    *,
    context: Mapping[str, Any],
    instruction: str,
    intent: str,
    target: Mapping[str, Any],
    basis: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "request_id": str(uuid.uuid4()),
        "expected_context_revision": context["revision"],
        "expected_semantic_source_revision": context["semantic_source_revision"],
        "intent": intent,
        "instruction": instruction,
        "target": dict(target),
        "basis": {"kind": "proposal", "proposal_ref": basis} if basis is not None else None,
        "clarification_response": None,
    }


def _source_catalogs(source: str | None) -> set[str]:
    return set(_CATALOG_SURFACE_RE.findall(source or ""))


def clarification_answer(
    clarification: Mapping[str, Any],
    *,
    evidence: str,
    source_catalogs: set[str] | None = None,
) -> dict[str, Any] | None:
    """Resolve only a choice stated exactly by the current logical message.

    Existing source catalog references may resolve a redundant catalog question;
    they never resolve a semantic value or an output policy.
    """

    kind = clarification.get("kind")
    folded = evidence.casefold()
    options = clarification.get("options")
    if kind == "result_count":
        parsed = parse_output_request(evidence)
        exact_counts = [count for mode, count in parsed.contracts if mode == "count"]
        if len(exact_counts) == 1:
            return {"integer": exact_counts[0]}
        numbers = [int(item) for item in re.findall(r"(?<!\w)([1-9][0-9]{0,3})(?!\w)", evidence)]
        return {"integer": numbers[0]} if len(set(numbers)) == 1 else None
    if kind == "catalog" and clarification.get("answer_schema") == {
        "type": "text",
        "format": "catalog-ref",
        "max_bytes": 256,
    }:
        catalog_refs = clarification.get("catalog_refs")
        if (
            not isinstance(catalog_refs, list)
            or not 6 <= len(catalog_refs) <= 64
            or any(not isinstance(item, str) or not item for item in catalog_refs)
            or len(catalog_refs) != len(set(catalog_refs))
        ):
            return None
        matches: list[str] = []
        for catalog in catalog_refs:
            short = catalog.rsplit(".", 1)[-1]
            explicit = any(
                re.search(pattern, folded)
                for pattern in (
                    rf"(?<!\w)catalog(?:o)?\s+{re.escape(short.casefold())}(?!\w)",
                    rf"(?<!\w)@{re.escape(short.casefold())}(?!\w)",
                    rf"(?<!\w){re.escape(catalog.casefold())}(?!\w)",
                )
            )
            from_source = source_catalogs is not None and (
                short in source_catalogs or catalog in source_catalogs
            )
            if explicit or from_source:
                matches.append(catalog)
        return {"text": matches[0]} if len(matches) == 1 else None
    if not isinstance(options, list) or not options:
        return None
    if kind == "catalog":
        matches: list[Mapping[str, Any]] = []
        for option in options:
            if not isinstance(option, Mapping):
                continue
            catalog = option.get("catalog")
            if not isinstance(catalog, str):
                continue
            short = catalog.rsplit(".", 1)[-1]
            explicit = any(
                re.search(pattern, folded)
                for pattern in (
                    rf"(?<!\w)catalog(?:o)?\s+{re.escape(short.casefold())}(?!\w)",
                    rf"(?<!\w)@{re.escape(short.casefold())}(?!\w)",
                    rf"(?<!\w){re.escape(catalog.casefold())}(?!\w)",
                )
            )
            from_source = source_catalogs is not None and (
                short in source_catalogs or catalog in source_catalogs
            )
            if explicit or from_source:
                matches.append(option)
        if len(matches) == 1 and isinstance(matches[0].get("option_ref"), str):
            return {"option_ref": matches[0]["option_ref"]}
        return None
    if kind == "response_shape":
        wants_page = "per pagina" in folded or "paginazione" in folded
        wants_total = "total" in folded or "complessiv" in folded
        matches = []
        for option in options:
            if not isinstance(option, Mapping) or not isinstance(option.get("label"), str):
                continue
            label = option["label"].casefold()
            if (wants_page and "per pagina" in label) or (
                wants_total and ("complessiv" in label or "totali" in label)
            ):
                matches.append(option)
        if len(matches) == 1 and isinstance(matches[0].get("option_ref"), str):
            return {"option_ref": matches[0]["option_ref"]}
        return None
    if kind == "semantic_choice":
        matches = []
        for option in options:
            if not isinstance(option, Mapping):
                continue
            surfaces = [option.get("label"), option.get("description")]
            if any(
                isinstance(surface, str)
                and len(surface.strip()) >= 3
                and surface.strip().casefold() in folded
                for surface in surfaces
            ):
                matches.append(option)
        if len(matches) == 1 and isinstance(matches[0].get("option_ref"), str):
            return {"option_ref": matches[0]["option_ref"]}
    return None


def _terminal_summary(terminal: Mapping[str, Any], elapsed_ms: int) -> dict[str, Any]:
    proposal = terminal.get("proposal")
    validation = terminal.get("validation")
    grounding = terminal.get("grounding")
    identity = terminal.get("identity")
    error = terminal.get("error")
    source = proposal.get("source") if isinstance(proposal, Mapping) else None
    return {
        "status": terminal.get("status"),
        "outcome": terminal.get("outcome"),
        "elapsed_ms": elapsed_ms,
        "error_code": error.get("code") if isinstance(error, Mapping) else None,
        "generation_strategy": (
            identity.get("generation_strategy") if isinstance(identity, Mapping) else None
        ),
        "compile_status": (validation.get("status") if isinstance(validation, Mapping) else None),
        "compile_attempts": (
            validation.get("attempts") if isinstance(validation, Mapping) else None
        ),
        "compiler_receipt_sha256": (
            validation.get("compiler_receipt_sha256") if isinstance(validation, Mapping) else None
        ),
        "grounding_status": grounding.get("status") if isinstance(grounding, Mapping) else None,
        "grounding_sha256": canonical_sha256(grounding) if isinstance(grounding, Mapping) else None,
        "proposal_ref": proposal.get("proposal_ref") if isinstance(proposal, Mapping) else None,
        "proposal_source": source if isinstance(source, str) else None,
        "proposal_source_sha256": (
            proposal.get("source_sha256") if isinstance(proposal, Mapping) else None
        ),
        "claims": dict(terminal.get("claims", {}))
        if isinstance(terminal.get("claims"), Mapping)
        else {},
    }


def _submit_and_record(
    client: HeadlessBrainClient,
    session: Mapping[str, Any],
    body: Mapping[str, Any],
    *,
    operation: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    turn_id = client.submit(session, body)
    terminal, elapsed_ms = client.wait_terminal(session, turn_id)
    events = client.events(session, turn_id)
    record = {
        "operation": operation,
        "turn_id": turn_id,
        "request_sha256": canonical_sha256(dict(body)),
        "instruction": body["instruction"],
        "basis": dict(body["basis"]) if isinstance(body.get("basis"), Mapping) else None,
        "basis_sha256": canonical_sha256(body.get("basis")),
        "target_sha256": canonical_sha256(body.get("target")),
        "terminal": _terminal_summary(terminal, elapsed_ms),
        "events": events,
    }
    return terminal, record


def _answer_pending(
    client: HeadlessBrainClient,
    session: Mapping[str, Any],
    terminal: dict[str, Any],
    *,
    evidence: str,
    source_catalogs: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    operations: list[dict[str, Any]] = []
    for _round in range(MAX_CLARIFICATION_ROUNDS):
        if terminal.get("outcome") != "needs_clarification":
            return terminal, operations, True
        clarification = terminal.get("clarification")
        if not isinstance(clarification, Mapping):
            return terminal, operations, False
        answer = clarification_answer(
            clarification,
            evidence=evidence,
            source_catalogs=source_catalogs,
        )
        if answer is None:
            operations.append(
                {
                    "operation": "answer.unresolved",
                    "clarification_kind": clarification.get("kind"),
                    "clarification_sha256": canonical_sha256(clarification),
                }
            )
            return terminal, operations, False
        turn_id = client.answer(
            session,
            parent_turn_id=str(terminal["turn_id"]),
            clarification_id=str(clarification["clarification_id"]),
            answer=answer,
        )
        resumed, elapsed_ms = client.wait_terminal(session, turn_id)
        operations.append(
            {
                "operation": "answer",
                "parent_turn_id": terminal["turn_id"],
                "clarification_id_sha256": canonical_sha256(
                    {"clarification_id": clarification["clarification_id"]}
                ),
                "answer_sha256": canonical_sha256(answer),
                "clarification_kind": clarification.get("kind"),
                "answer": answer,
                "turn_id": turn_id,
                "terminal": _terminal_summary(resumed, elapsed_ms),
                "events": client.events(session, turn_id),
            }
        )
        terminal = resumed
    return terminal, operations, terminal.get("outcome") != "needs_clarification"


def _draft_gate(terminal: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    proposal = terminal.get("proposal")
    validation = terminal.get("validation")
    grounding = terminal.get("grounding")
    claims = terminal.get("claims")
    if terminal.get("status") != "completed" or terminal.get("outcome") != "proposed":
        failures.append("no_proposal")
    if not isinstance(proposal, Mapping):
        failures.append("proposal_missing")
    else:
        for key in ("operation", "relative_path", "endpoint", "base_sha256"):
            expected = (
                "create"
                if key == "operation" and target["mode"] == "create"
                else "replace"
                if key == "operation"
                else target.get(key)
            )
            if proposal.get(key) != expected:
                failures.append(f"proposal_{key}")
    if not isinstance(validation, Mapping) or validation.get("status") != "ok":
        failures.append("compile_not_clean")
    elif validation.get("attempts") != 1:
        failures.append("not_first_attempt")
    if (
        not isinstance(grounding, Mapping)
        or grounding.get("status") != "resolved"
        or grounding.get("unresolved")
        or grounding.get("candidates")
    ):
        failures.append("grounding_not_exact")
    elif not _grounding_roster_is_reviewed(grounding):
        failures.append("grounding_roster_not_reviewed")
    if not isinstance(claims, Mapping) or claims.get("tenant_modified") is not False:
        failures.append("tenant_claim")
    if not isinstance(claims, Mapping) or claims.get("semantic_grounded") is not True:
        failures.append("semantic_grounded_claim")
    return not failures, failures


def _edit_route_gate(
    terminal: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    require_structural_lossless: bool,
    expected_touched_count: int | None = None,
) -> tuple[bool, list[str]]:
    """Bind a v2 edit pass to the compiler-owned structural renderer proof."""

    if not require_structural_lossless:
        return True, []

    failures: list[str] = []
    identity = terminal.get("identity")
    if (
        not isinstance(identity, Mapping)
        or identity.get("generation_strategy") != "lossless_renderer"
    ):
        failures.append("edit_generation_not_structural_lossless")

    validation = terminal.get("validation")
    proposal = terminal.get("proposal")
    proof = validation.get("lossless") if isinstance(validation, Mapping) else None
    proposal_source = proposal.get("source") if isinstance(proposal, Mapping) else None
    proposal_source_sha256 = (
        proposal.get("source_sha256") if isinstance(proposal, Mapping) else None
    )
    base_sha256 = target.get("base_sha256")
    proof_fields = {
        "contract",
        "proof_mode",
        "receipt_sha256",
        "sha_before",
        "sha_after",
        "touched_count",
    }
    proof_valid = (
        isinstance(proof, Mapping)
        and set(proof) == proof_fields
        and proof.get("contract") == STRUCTURAL_LOSSLESS_PROOF_CONTRACT
        and proof.get("proof_mode") == "validate"
        and isinstance(proof.get("receipt_sha256"), str)
        and _HASH_RE.fullmatch(proof["receipt_sha256"]) is not None
        and isinstance(base_sha256, str)
        and _HASH_RE.fullmatch(base_sha256) is not None
        and proof.get("sha_before") == base_sha256
        and isinstance(proposal_source, str)
        and isinstance(proposal_source_sha256, str)
        and _HASH_RE.fullmatch(proposal_source_sha256) is not None
        and proposal_source_sha256 == _sha256(proposal_source.encode("utf-8"))
        and proof.get("sha_after") == proposal_source_sha256
        and type(expected_touched_count) is int
        and 1 <= expected_touched_count <= MAX_EDIT_OPERATIONS
        and type(proof.get("touched_count")) is int
        and proof["touched_count"] == expected_touched_count
    )
    if not proof_valid:
        failures.append("edit_structural_lossless_proof_invalid")
    return not failures, failures


def _grounding_roster_is_reviewed(grounding: Mapping[str, Any]) -> bool:
    selections = grounding.get("selections")
    resolutions = grounding.get("resolutions")
    if not isinstance(selections, list) or not isinstance(resolutions, list):
        return False

    def identity(item: Mapping[str, Any]) -> tuple[Any, ...]:
        literals = item.get("literals")
        return (
            item.get("catalog"),
            item.get("field"),
            item.get("literal"),
            tuple(literals) if isinstance(literals, list) else (),
        )

    selection_ids: list[tuple[Any, ...]] = []
    for item in selections:
        if not isinstance(item, Mapping):
            return False
        selected = identity(item)
        if not isinstance(selected[0], str) or not isinstance(selected[1], str):
            return False
        selection_ids.append(selected)
    if len(selection_ids) != len(set(selection_ids)):
        return False
    reviewed = {
        (item.get("catalog"), item.get("field"), item.get("literal"))
        for item in resolutions
        if isinstance(item, Mapping) and item.get("review_state") == "reviewed"
    }
    return all(
        (catalog, field, literal) in reviewed for catalog, field, literal, _ in selection_ids
    )


def _walk_mappings(value: Any) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        result.append(value)
        for member in value.values():
            result.extend(_walk_mappings(member))
    elif isinstance(value, list):
        for member in value:
            result.extend(_walk_mappings(member))
    return result


def _endpoint_tree_mappings(ir: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for key in ("blocks", "variants", "inline"):
        result.extend(_walk_mappings(ir.get(key)))
    return result


def _output_sequence(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("kind"), str):
            return None
        suffix = ""
        if type(item.get("n")) is int:
            suffix = f":{item['n']}"
        result.append(item["kind"] + suffix)
    return "->".join(result)


def _ordering_signature(by: Mapping[str, Any], direction: str) -> str | None:
    kind = by.get("kind")
    if kind == "field" and isinstance(by.get("field"), str):
        return f"field:{by['field']}:{direction}"
    if kind != "similarity":
        return None
    target = by.get("target")
    if (
        isinstance(target, Mapping)
        and set(target) == {"ctx"}
        and isinstance(target.get("ctx"), str)
    ):
        return f"similarity:{direction}:ctx:{target['ctx']}"
    return f"similarity:{direction}:target:{canonical_json(target)}"


def _fallback_key(item: Mapping[str, Any]) -> str | None:
    rule = item.get("rule")
    target = item.get("target")
    if isinstance(rule, Mapping) and isinstance(target, str):
        trigger = rule.get("trigger")
        kind = trigger.get("kind") if isinstance(trigger, Mapping) else None
        mode = rule.get("mode")
        if isinstance(kind, str) and isinstance(mode, str):
            return f"{kind}:{mode}:{target}"
    block = item.get("block")
    endpoint = item.get("endpoint")
    mode = item.get("mode")
    when = item.get("when")
    target_kind: str | None = None
    target_name: str | None = None
    if isinstance(block, str):
        target_kind, target_name = "block", block
    elif isinstance(endpoint, str):
        target_kind, target_name = "endpoint", endpoint
    if target_kind is not None and isinstance(mode, str):
        if isinstance(when, str):
            trigger = when
        elif (
            isinstance(when, Mapping) and set(when) == {"below"} and type(when.get("below")) is int
        ):
            trigger = f"below-{when['below']}"
        else:
            return None
        return f"{trigger}:{mode}:{target_kind}.{target_name}"
    return None


def structural_facts(ir: Mapping[str, Any]) -> dict[str, Any]:
    """Project compiler IR into a closed, formatting-independent fact roster."""

    endpoint_tree = _endpoint_tree_mappings(ir)
    all_nodes = _walk_mappings(ir)
    blocks = [item for item in ir.get("blocks", []) if isinstance(item, Mapping)]
    variants = [item for item in ir.get("variants", []) if isinstance(item, Mapping)]
    takes = [item for item in endpoint_tree if item.get("node") == "Fetch"]
    uses = [
        member
        for item in endpoint_tree
        for member in (item.get("uses") if isinstance(item.get("uses"), list) else [])
        if isinstance(member, Mapping)
    ]
    fallback_keys: set[str] = set()
    for item in [ir, *endpoint_tree]:
        direct = item.get("fallback")
        if isinstance(direct, Mapping):
            key = _fallback_key(direct)
            if key is not None:
                fallback_keys.add(key)
        direct_list = item.get("fallbacks")
        if isinstance(direct_list, list):
            for fallback in direct_list:
                if isinstance(fallback, Mapping):
                    key = _fallback_key(fallback)
                    if key is not None:
                        fallback_keys.add(key)
        materialized = item.get("materializedFallbacks")
        if isinstance(materialized, list):
            for binding in materialized:
                if isinstance(binding, Mapping):
                    key = _fallback_key(binding)
                    if key is not None:
                        fallback_keys.add(key)
    catalog_refs = {
        source["ref"]
        for item in all_nodes
        for source in (item.get("source"),)
        if isinstance(source, Mapping)
        and source.get("kind") == "catalog"
        and isinstance(source.get("ref"), str)
    }
    render_nodes = [ir, *endpoint_tree]
    output_sequences = {
        sequence
        for item in render_nodes
        for sequence in (_output_sequence(item.get("output")),)
        if sequence is not None
    }
    ordering_keys: set[str] = set()
    ordering_signatures: set[str] = set()
    for item in render_nodes:
        for ordering in item.get("ordering", []) if isinstance(item.get("ordering"), list) else []:
            if not isinstance(ordering, Mapping):
                continue
            by = ordering.get("by")
            direction = ordering.get("direction")
            if not isinstance(by, Mapping) or not isinstance(direction, str):
                continue
            if by.get("kind") == "field" and isinstance(by.get("field"), str):
                ordering_keys.add(f"field:{by['field']}:{direction}")
            elif by.get("kind") == "similarity":
                ordering_keys.add(f"similarity:{direction}")
            signature = _ordering_signature(by, direction)
            if signature is not None:
                ordering_signatures.add(signature)
    parameterized_blocks = 0
    for block in blocks:
        if any("arg" in item for item in _walk_mappings(block)):
            parameterized_blocks += 1
    facts: dict[str, Any] = {
        "endpoint_name": ir.get("name"),
        "paginate": ir.get("paginate"),
        "catalog_refs": sorted(catalog_refs),
        "context_names": sorted((ir.get("context") or {}).keys())
        if isinstance(ir.get("context"), Mapping)
        else [],
        "attribute_names": sorted((ir.get("attributes") or {}).keys())
        if isinstance(ir.get("attributes"), Mapping)
        else [],
        "block_names": sorted(item["name"] for item in blocks if isinstance(item.get("name"), str)),
        "variant_names": sorted(
            item["name"] for item in variants if isinstance(item.get("name"), str)
        ),
        "top_level_block_count": len(blocks),
        "variant_count": len(variants),
        "guarded_variant_count": sum(
            isinstance(item.get("activation"), str) or isinstance(item.get("guard"), str)
            for item in variants
        ),
        "empty_variant_count": sum(
            not item.get("takes") and not item.get("blocks") and not item.get("uses")
            for item in variants
        ),
        "endpoint_take_count": len(takes),
        "endpoint_take_counts": sorted(
            item["count"]["take"]
            for item in takes
            if isinstance(item.get("count"), Mapping) and type(item["count"].get("take")) is int
        ),
        "use_count": len(uses),
        "use_refs": sorted(member["ref"] for member in uses if isinstance(member.get("ref"), str)),
        "instance_arg_count": sum(bool(member.get("args")) for member in uses),
        "view_all_count": sum("viewAll" in item for item in endpoint_tree),
        "fallback_keys": sorted(fallback_keys),
        "output_flow_count": sum(
            isinstance(item.get("output"), list) and bool(item["output"]) for item in render_nodes
        ),
        "output_sequences": sorted(output_sequences),
        "ordering_keys": sorted(ordering_keys),
        "ordering_signatures": sorted(ordering_signatures),
        "meta_templates": sorted(
            item["meta"]["template"]
            for item in endpoint_tree
            if isinstance(item.get("meta"), Mapping)
            and isinstance(item["meta"].get("template"), str)
        ),
        "search_detail_meta_count": sum(
            isinstance(item.get("meta"), Mapping) and "searchDetailParams" in item["meta"]
            for item in endpoint_tree
        ),
        "group_count": sum("groupBy" in item for item in all_nodes),
        "expanded_take_count": sum(
            isinstance(item.get("projection"), Mapping)
            and item["projection"].get("ref") == "expanded"
            for item in takes
        ),
        "parameterized_block_count": parameterized_blocks,
        "has_input_pipeline": ir.get("inputPipeline") is not None,
        "input_pipeline": canonical_sha256(ir.get("inputPipeline"))
        if ir.get("inputPipeline") is not None
        else None,
    }
    return facts


def evaluate_structural_checks(
    facts: Mapping[str, Any], checks: Sequence[Mapping[str, Any]]
) -> tuple[bool, list[dict[str, Any]]]:
    outcomes: list[dict[str, Any]] = []
    for check in checks:
        if set(check) != {"id", "fact", "op", "value"}:
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "structural check is invalid")
        check_id = check["id"]
        fact_name = check["fact"]
        op = check["op"]
        expected = check["value"]
        if (
            not isinstance(check_id, str)
            or not check_id
            or not isinstance(fact_name, str)
            or fact_name not in facts
            or op not in {"equals", "gte", "lte", "contains_all", "excludes_all"}
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "structural check is invalid")
        actual = facts[fact_name]
        if op == "equals":
            passed = actual == expected
        elif op in {"gte", "lte"}:
            passed = (
                type(actual) is int
                and type(expected) is int
                and (actual >= expected if op == "gte" else actual <= expected)
            )
        else:
            passed = isinstance(actual, list) and isinstance(expected, list)
            if passed:
                actual_set = {canonical_sha256(item) for item in actual}
                expected_set = {canonical_sha256(item) for item in expected}
                passed = (
                    expected_set.issubset(actual_set)
                    if op == "contains_all"
                    else expected_set.isdisjoint(actual_set)
                )
        outcomes.append(
            {
                "id": check_id,
                "fact": fact_name,
                "op": op,
                "expected": expected,
                "actual": actual,
                "pass": passed,
            }
        )
    return all(item["pass"] for item in outcomes), outcomes


def _safe_failure(terminal: Mapping[str, Any]) -> bool:
    claims = terminal.get("claims")
    if isinstance(claims, Mapping) and claims.get("tenant_modified") is not False:
        return False
    return terminal.get("status") in {"failed", "cancelled"} or terminal.get("outcome") in {
        "unsupported_metadata",
        "needs_clarification",
    }


def _clarification_gate(
    terminal: Mapping[str, Any],
    *,
    expected_turn_id: str,
    next_evidence: str,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    clarification = terminal.get("clarification")
    if terminal.get("turn_id") != expected_turn_id:
        failures.append("clarification_turn_binding")
    if not isinstance(clarification, Mapping):
        return False, [*failures, "clarification_missing"]
    clarification_id = clarification.get("clarification_id")
    kind = clarification.get("kind")
    question = clarification.get("question")
    options = clarification.get("options")
    answer_schema = clarification.get("answer_schema")
    round_index = clarification.get("round")
    max_rounds = clarification.get("max_rounds")
    if not isinstance(clarification_id, str) or not clarification_id:
        failures.append("clarification_id")
    if kind not in CLARIFICATION_KINDS:
        failures.append("clarification_kind")
    if not isinstance(question, str) or not question.strip():
        failures.append("clarification_question")
    if (
        type(round_index) is not int
        or type(max_rounds) is not int
        or not 1 <= round_index <= max_rounds <= MAX_CLARIFICATION_ROUNDS
    ):
        failures.append("clarification_round")
    if kind == "result_count":
        if (
            options != []
            or not isinstance(answer_schema, Mapping)
            or answer_schema.get("type") != "integer"
            or type(answer_schema.get("minimum")) is not int
            or type(answer_schema.get("maximum")) is not int
            or answer_schema["minimum"] < 1
            or answer_schema["maximum"] < answer_schema["minimum"]
        ):
            failures.append("clarification_schema")
    elif kind == "catalog" and answer_schema == {
        "type": "text",
        "format": "catalog-ref",
        "max_bytes": 256,
    }:
        catalog_refs = clarification.get("catalog_refs")
        if (
            options != []
            or not isinstance(catalog_refs, list)
            or not 6 <= len(catalog_refs) <= 64
            or any(not isinstance(item, str) or not item for item in catalog_refs)
            or len(catalog_refs) != len(set(catalog_refs))
        ):
            failures.append("clarification_catalog_roster")
    elif kind in OPTION_KINDS:
        if (
            not isinstance(options, list)
            or not 2 <= len(options) <= 5
            or any(
                not isinstance(option, Mapping)
                or not isinstance(option.get("option_ref"), str)
                or not option.get("option_ref")
                or not isinstance(option.get("label"), str)
                or not option.get("label")
                for option in options
            )
        ):
            failures.append("clarification_options")
        if answer_schema != {"type": "option_ref"}:
            failures.append("clarification_schema")
    if (
        not failures
        and clarification_answer(
            clarification,
            evidence=next_evidence,
            source_catalogs=set(),
        )
        is None
    ):
        failures.append("clarification_not_answerable_by_next_message")
    return not failures, failures


def _rename_endpoint(source: str, before: str, after: str) -> str:
    pattern = re.compile(rf"(?m)^(\s*endpoint\s+){re.escape(before)}(?=\s|\{{)")
    renamed, count = pattern.subn(lambda match: match.group(1) + after, source, count=1)
    if count != 1:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "reference endpoint does not bind")
    return renamed


def _normalized_structural_ir(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("node") != "Endpoint":
        raise BrainError("HARD_QUALIFICATION_ORACLE", 503, "structural IR is invalid")
    normalized = parse_json_object(canonical_json(dict(value)), label="structural IR")
    # The public UX reference is not requested by the create prompts.  All
    # executable behavior, endpoint identity and internal references remain.
    normalized.pop("reference", None)
    return normalized


def _structural_evidence(
    *,
    service: MetisBrainService,
    session: Mapping[str, Any],
    context: Mapping[str, Any],
    terminal: Mapping[str, Any],
    spec: HardQualificationSpec,
    create_target: Mapping[str, Any],
    oracle: Mapping[str, Any],
    final_turn: bool,
    previous_structural_sha256: str | None,
) -> tuple[bool, list[str], dict[str, Any]]:
    proposal = terminal.get("proposal")
    if not isinstance(proposal, Mapping) or not isinstance(proposal.get("source"), str):
        return False, ["proposal_source_missing"], {}
    source = proposal["source"]
    if proposal.get("source_sha256") != _sha256(source.encode("utf-8")):
        return False, ["proposal_source_hash_differs"], {}
    compiler = service.app.compiler
    compile_structure = getattr(compiler, "compile_structure", None)
    if not callable(compile_structure):
        raise BrainError("HARD_QUALIFICATION_ORACLE", 503, "structural compiler is unavailable")
    with service.app.manager.operation(
        session_id=str(session["id"]),
        token=str(session["token"]),
        capability="chat.read",
        expected_revision=str(context["revision"]),
    ) as lease:
        candidate = compile_structure(
            lease=lease,
            source=source,
            filename=create_target["relative_path"],
            endpoint=create_target["endpoint"],
        )
        if candidate.get("status") != "ok":
            return (
                False,
                ["structural_compile_not_clean"],
                {
                    "candidate_status": candidate.get("status"),
                    "candidate_diagnostics_sha256": canonical_sha256(
                        candidate.get("diagnostics", [])
                    ),
                },
            )
        candidate_ir = _normalized_structural_ir(candidate.get("structural_ir"))
        facts = structural_facts(candidate_ir)
        checks = oracle.get("checks")
        if not isinstance(checks, list) or not checks:
            raise BrainError(
                "HARD_QUALIFICATION_INVALID", 400, "structural oracle checks are absent"
            )
        checks_green, outcomes = evaluate_structural_checks(facts, checks)
        candidate_structural_sha256 = canonical_sha256(candidate_ir)
        evidence: dict[str, Any] = {
            "candidate_structural_sha256": candidate_structural_sha256,
            "facts_sha256": canonical_sha256(facts),
            "facts": facts,
            "checks": outcomes,
            "checks_green": checks_green,
            "reference_equivalent": None,
        }
        failures = (
            []
            if checks_green
            else [f"structural:{item['id']}" for item in outcomes if item["pass"] is not True]
        )
        if previous_structural_sha256 == candidate_structural_sha256:
            failures.append("structural:no_delta_from_prior_draft")
        if final_turn and spec.require_reference_equivalence:
            source_path = create_target["reference_source_path"]
            reference_raw = _safe_regular_bytes(
                spec.tenant_root / source_path,
                label="reference endpoint source",
                maximum=MAX_SOURCE_BYTES,
            )
            try:
                reference_source = reference_raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise BrainError(
                    "HARD_QUALIFICATION_INVALID", 400, "reference endpoint is not UTF-8"
                ) from error
            replacements = create_target.get("reference_replacements", [])
            if not isinstance(replacements, list):
                raise BrainError(
                    "HARD_QUALIFICATION_INVALID", 400, "reference replacements are invalid"
                )
            if replacements:
                reference_source = _apply_replacements(reference_source, replacements)
            reference_source = _rename_endpoint(
                reference_source,
                create_target["source_endpoint"],
                create_target["endpoint"],
            )
            reference = compile_structure(
                lease=lease,
                source=reference_source,
                filename=source_path,
                endpoint=create_target["endpoint"],
            )
            if reference.get("status") != "ok":
                raise BrainError(
                    "HARD_QUALIFICATION_ORACLE", 503, "reference structural compile failed"
                )
            reference_ir = _normalized_structural_ir(reference.get("structural_ir"))
            reference_equivalent = candidate_ir == reference_ir
            evidence["reference_structural_sha256"] = canonical_sha256(reference_ir)
            evidence["reference_equivalent"] = reference_equivalent
            if not reference_equivalent:
                failures.append("structural:source_equivalence")
        return not failures, failures, evidence


@contextmanager
def _guarded_session(
    *,
    client: HeadlessBrainClient,
    spec: HardQualificationSpec,
    target_path: str,
) -> Any:
    """Close every case session and prove tenant immutability even on failure."""

    before_guard = capture_tenant_guard(
        root=spec.tenant_root,
        tenant_alias=spec.tenant_alias,
        tenant_id=spec.tenant_id,
        target_path=target_path,
    )
    session: dict[str, Any] | None = None
    body_error: BaseException | None = None
    close_error: BaseException | None = None
    try:
        session = client.open_session(tenant_alias=spec.tenant_alias)
        yield session
    except BaseException as error:
        body_error = error
    finally:
        if session is not None:
            try:
                client.close_session(session)
            except BaseException as error:
                close_error = error
        after_guard = capture_tenant_guard(
            root=spec.tenant_root,
            tenant_alias=spec.tenant_alias,
            tenant_id=spec.tenant_id,
            target_path=target_path,
        )
        if before_guard != after_guard:
            raise BrainError(
                "HARD_QUALIFICATION_DRIFT", 409, "tenant changed during qualification case"
            ) from body_error or close_error
        if body_error is not None:
            raise body_error
        if close_error is not None:
            raise close_error


def _run_edit(
    *,
    client: HeadlessBrainClient,
    spec: HardQualificationSpec,
    case: Mapping[str, Any],
    oracle: Mapping[str, Any],
) -> dict[str, Any]:
    endpoint = case["endpoint_identity"]["qualified"]
    source_path = case["source_path"]
    operations: list[dict[str, Any]] = []
    with _guarded_session(client=client, spec=spec, target_path=source_path) as session:
        context = client.context(session)
        files = _files(context)
        if files.get(source_path) != case["source_sha256"]:
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "edit target hash differs")
        source_raw = _safe_regular_bytes(
            spec.tenant_root / source_path,
            label="edit endpoint source",
            maximum=MAX_SOURCE_BYTES,
        )
        if _sha256(source_raw) != case["source_sha256"]:
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "edit target hash differs")
        try:
            source = source_raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BrainError(
                "HARD_QUALIFICATION_INVALID", 400, "edit endpoint source is not UTF-8"
            ) from error
        expected_source = _apply_replacements(source, oracle["replacements"])
        target = validate_target(
            {
                "mode": "existing",
                "relative_path": source_path,
                "endpoint": endpoint,
                "base_sha256": files[source_path],
            }
        )
        body = _turn_body(
            context=context,
            instruction=case["operator_edit_prompt_it"],
            intent="edit",
            target=target,
            basis=None,
        )
        terminal, submitted = _submit_and_record(client, session, body, operation="edit.submit")
        operations.append(submitted)
        terminal, answers, resolved = _answer_pending(
            client,
            session,
            terminal,
            evidence=case["operator_edit_prompt_it"],
            source_catalogs=_source_catalogs(source),
        )
        operations.extend(answers)
        gate, failures = _draft_gate(terminal, target)
        route_green, route_failures = _edit_route_gate(
            terminal,
            target,
            require_structural_lossless=spec.require_structural_lossless_edits,
            expected_touched_count=len(oracle["replacements"]),
        )
        gate = gate and route_green
        failures.extend(route_failures)
        proposal = terminal.get("proposal")
        proposal_source = proposal.get("source") if isinstance(proposal, Mapping) else None
        exact_edit = isinstance(proposal_source, str) and proposal_source == expected_source
        if gate and exact_edit:
            verdict = "PASS_DRAFT"
        elif gate:
            verdict = "FAIL_SEMANTIC_ORACLE"
            failures.append("candidate_diff_not_exact")
        elif _safe_failure(terminal):
            verdict = "SAFE_FAIL_CLOSED"
            if not resolved:
                failures.append("clarification_not_exactly_answerable")
        else:
            verdict = "FAIL"
        return {
            "kind": "edit",
            "endpoint": endpoint,
            "source_path": source_path,
            "prompt": case["operator_edit_prompt_it"],
            "prompt_sha256": canonical_sha256({"prompt": case["operator_edit_prompt_it"]}),
            "expected_source_sha256": _sha256(expected_source.encode("utf-8")),
            "verdict": verdict,
            "failures": sorted(set(failures)),
            "operations": operations,
            "terminal": _terminal_summary(terminal, 0),
        }


def _run_journey(
    *,
    service: MetisBrainService,
    client: HeadlessBrainClient,
    spec: HardQualificationSpec,
    journey: Mapping[str, Any],
    create_target: Mapping[str, Any],
    create_oracle: Mapping[str, Any],
) -> dict[str, Any]:
    source_endpoint = journey["endpoint_qualified"]
    target = validate_target(
        {
            "mode": "create",
            "relative_path": create_target["relative_path"],
            "endpoint": create_target["endpoint"],
            "base_sha256": None,
        }
    )
    logical_results: list[dict[str, Any]] = []
    oracle_turns = {
        item["turn"]: item for item in create_oracle["turns"] if isinstance(item, Mapping)
    }
    basis: str | None = None
    pending: dict[str, Any] | None = None
    previous_structural_sha256: str | None = None
    blocked = False
    with _guarded_session(
        client=client,
        spec=spec,
        target_path=target["relative_path"],
    ) as session:
        context = client.context(session)
        if target["relative_path"] in _files(context):
            raise BrainError("HARD_QUALIFICATION_INVALID", 409, "create target exists")
        for logical in journey["turns"]:
            turn_no = logical["turn"]
            message = logical["user_message"]
            expected_action = logical["expected_brain_action"]
            operations: list[dict[str, Any]] = []
            if blocked:
                logical_results.append(
                    {
                        "turn": turn_no,
                        "prompt": message,
                        "prompt_sha256": canonical_sha256({"prompt": message}),
                        "expected_action": expected_action,
                        "verdict": "BLOCKED_BY_PREDECESSOR",
                        "failures": ["no_accepted_proposal_basis"],
                        "operations": [],
                    }
                )
                continue
            if pending is not None:
                pending, answers, resolved = _answer_pending(
                    client,
                    session,
                    pending,
                    evidence=message,
                    source_catalogs=set(),
                )
                operations.extend(answers)
                if not resolved or pending.get("outcome") == "needs_clarification":
                    logical_results.append(
                        {
                            "turn": turn_no,
                            "prompt": message,
                            "prompt_sha256": canonical_sha256({"prompt": message}),
                            "expected_action": expected_action,
                            "verdict": "SAFE_FAIL_CLOSED",
                            "failures": ["clarification_not_exactly_answerable"],
                            "operations": operations,
                            "terminal": _terminal_summary(pending, 0),
                        }
                    )
                    blocked = True
                    continue
                proposal = pending.get("proposal")
                if isinstance(proposal, Mapping) and isinstance(proposal.get("proposal_ref"), str):
                    interim_green, interim_failures = _draft_gate(pending, target)
                    if not interim_green:
                        logical_results.append(
                            {
                                "turn": turn_no,
                                "prompt": message,
                                "prompt_sha256": canonical_sha256({"prompt": message}),
                                "expected_action": expected_action,
                                "verdict": "SAFE_FAIL_CLOSED" if _safe_failure(pending) else "FAIL",
                                "failures": [
                                    "clarification_continuation_failed_draft_gate",
                                    *interim_failures,
                                ],
                                "operations": operations,
                                "terminal": _terminal_summary(pending, 0),
                            }
                        )
                        blocked = True
                        continue
                    basis = proposal["proposal_ref"]
                elif pending.get("outcome") == "no_change":
                    logical_results.append(
                        {
                            "turn": turn_no,
                            "prompt": message,
                            "prompt_sha256": canonical_sha256({"prompt": message}),
                            "expected_action": expected_action,
                            "verdict": "SAFE_FAIL_CLOSED",
                            "failures": ["clarification_continuation_has_no_proposal"],
                            "operations": operations,
                            "terminal": _terminal_summary(pending, 0),
                        }
                    )
                    blocked = True
                    continue
                else:
                    logical_results.append(
                        {
                            "turn": turn_no,
                            "prompt": message,
                            "prompt_sha256": canonical_sha256({"prompt": message}),
                            "expected_action": expected_action,
                            "verdict": "SAFE_FAIL_CLOSED" if _safe_failure(pending) else "FAIL",
                            "failures": ["clarification_continuation_has_no_proposal"],
                            "operations": operations,
                            "terminal": _terminal_summary(pending, 0),
                        }
                    )
                    blocked = True
                    continue
                pending = None

            body = _turn_body(
                context=context,
                instruction=message,
                intent="create",
                target=target,
                basis=basis,
            )
            terminal, submitted = _submit_and_record(
                client,
                session,
                body,
                operation=f"journey.turn-{turn_no}.submit",
            )
            operations.append(submitted)
            action_mismatch = False
            structural: dict[str, Any] | None = None
            if terminal.get("outcome") == "needs_clarification":
                if expected_action == "clarify":
                    next_message = (
                        journey["turns"][turn_no]["user_message"]
                        if turn_no < len(journey["turns"])
                        else ""
                    )
                    clarification_green, failures = _clarification_gate(
                        terminal,
                        expected_turn_id=str(submitted["turn_id"]),
                        next_evidence=next_message,
                    )
                    if clarification_green:
                        verdict = "PASS_CLARIFICATION"
                        pending = terminal
                    else:
                        verdict = "FAIL_ACTION_MISMATCH"
                        action_mismatch = True
                        blocked = True
                else:
                    action_mismatch = True
                    terminal, answers, resolved = _answer_pending(
                        client,
                        session,
                        terminal,
                        evidence=message,
                        source_catalogs=set(),
                    )
                    operations.extend(answers)
                    if terminal.get("outcome") == "needs_clarification" or not resolved:
                        verdict = "SAFE_FAIL_CLOSED"
                        failures = ["unexpected_unresolved_clarification"]
                        pending = terminal
                        blocked = True
                    else:
                        gate, failures = _draft_gate(terminal, target)
                        if gate:
                            structural_green, structural_failures, structural = (
                                _structural_evidence(
                                    service=service,
                                    session=session,
                                    context=context,
                                    terminal=terminal,
                                    spec=spec,
                                    create_target=create_target,
                                    oracle=oracle_turns[turn_no],
                                    final_turn=turn_no == 4,
                                    previous_structural_sha256=previous_structural_sha256,
                                )
                            )
                            previous_structural_sha256 = structural.get(
                                "candidate_structural_sha256"
                            )
                            failures.extend(structural_failures)
                            verdict = (
                                "FAIL_ACTION_MISMATCH"
                                if structural_green
                                else "FAIL_SEMANTIC_ORACLE"
                            )
                        else:
                            verdict = "SAFE_FAIL_CLOSED" if _safe_failure(terminal) else "FAIL"
                summary = _terminal_summary(terminal, 0)
            else:
                gate, failures = _draft_gate(terminal, target)
                if expected_action == "clarify":
                    failures.append("required_clarification_missing")
                    verdict = (
                        "FAIL_ACTION_MISMATCH"
                        if gate
                        else ("SAFE_FAIL_CLOSED" if _safe_failure(terminal) else "FAIL")
                    )
                    action_mismatch = True
                elif gate:
                    structural_green, structural_failures, structural = _structural_evidence(
                        service=service,
                        session=session,
                        context=context,
                        terminal=terminal,
                        spec=spec,
                        create_target=create_target,
                        oracle=oracle_turns[turn_no],
                        final_turn=turn_no == 4,
                        previous_structural_sha256=previous_structural_sha256,
                    )
                    previous_structural_sha256 = structural.get("candidate_structural_sha256")
                    failures.extend(structural_failures)
                    verdict = (
                        "PASS_STRUCTURAL_ORACLE" if structural_green else "FAIL_SEMANTIC_ORACLE"
                    )
                elif _safe_failure(terminal):
                    verdict = "SAFE_FAIL_CLOSED"
                else:
                    verdict = "FAIL"
                summary = _terminal_summary(terminal, 0)
            proposal = terminal.get("proposal")
            accepted_verdicts = {"PASS_STRUCTURAL_ORACLE", "FAIL_ACTION_MISMATCH"}
            if verdict in accepted_verdicts and isinstance(proposal, Mapping):
                proposal_ref = proposal.get("proposal_ref")
                if isinstance(proposal_ref, str):
                    basis = proposal_ref
                else:
                    verdict = "FAIL"
                    failures.append("proposal_ref_missing")
                    blocked = True
            elif verdict not in {"PASS_CLARIFICATION"}:
                blocked = True
            if action_mismatch:
                failures.append("unexpected_brain_action")
            logical_results.append(
                {
                    "turn": turn_no,
                    "prompt": message,
                    "prompt_sha256": canonical_sha256({"prompt": message}),
                    "expected_action": expected_action,
                    "verdict": verdict,
                    "failures": sorted(set(failures)),
                    "operations": operations,
                    "terminal": summary,
                    "structural": structural,
                }
            )
        return {
            "kind": "create_journey",
            "source_endpoint": source_endpoint,
            "target": target,
            "turns": logical_results,
            "convergence": journey["convergence"],
            "verdict": (
                "PASS_STRUCTURAL_ORACLE"
                if [item["verdict"] for item in logical_results]
                == [
                    "PASS_CLARIFICATION",
                    "PASS_STRUCTURAL_ORACLE",
                    "PASS_STRUCTURAL_ORACLE",
                    "PASS_STRUCTURAL_ORACLE",
                ]
                else "NOT_CONVERGED"
            ),
        }


def _aggregate(
    edits: Sequence[Mapping[str, Any]],
    journeys: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    edit_verdicts = [item["verdict"] for item in edits]
    logical = [turn for journey in journeys for turn in journey["turns"]]
    logical_verdicts = [item["verdict"] for item in logical]
    return {
        "edits": {
            "total": len(edits),
            "pass_draft": edit_verdicts.count("PASS_DRAFT"),
            "safe_fail_closed": edit_verdicts.count("SAFE_FAIL_CLOSED"),
            "semantic_oracle_fail": edit_verdicts.count("FAIL_SEMANTIC_ORACLE"),
            "unsafe_fail": edit_verdicts.count("FAIL"),
        },
        "create_journeys": {
            "total": len(journeys),
            "converged_structural_oracle": sum(
                item["verdict"] == "PASS_STRUCTURAL_ORACLE" for item in journeys
            ),
            "not_converged": sum(item["verdict"] == "NOT_CONVERGED" for item in journeys),
        },
        "logical_create_turns": {
            "total": len(logical),
            "pass_clarification": logical_verdicts.count("PASS_CLARIFICATION"),
            "pass_structural_oracle": logical_verdicts.count("PASS_STRUCTURAL_ORACLE"),
            "semantic_oracle_fail": logical_verdicts.count("FAIL_SEMANTIC_ORACLE"),
            "action_mismatch": logical_verdicts.count("FAIL_ACTION_MISMATCH"),
            "safe_fail_closed": logical_verdicts.count("SAFE_FAIL_CLOSED"),
            "blocked_by_predecessor": logical_verdicts.count("BLOCKED_BY_PREDECESSOR"),
            "unsafe_fail": logical_verdicts.count("FAIL"),
        },
    }


def _prepare_output(path: Path) -> Path:
    target = Path(path)
    try:
        project = PROJECT_ROOT.lstat()
        artifact_root = OUTPUT_ROOT.parent.lstat()
    except OSError as error:
        raise BrainError(
            "HARD_QUALIFICATION_INVALID", 400, "qualification artifact root is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(project.st_mode)
        or stat.S_ISLNK(project.st_mode)
        or not stat.S_ISDIR(artifact_root.st_mode)
        or stat.S_ISLNK(artifact_root.st_mode)
        or PROJECT_ROOT.resolve(strict=True) != PROJECT_ROOT
        or OUTPUT_ROOT.parent.resolve(strict=True) != OUTPUT_ROOT.parent
    ):
        raise BrainError(
            "HARD_QUALIFICATION_INVALID", 400, "qualification artifact root is not real"
        )
    try:
        OUTPUT_ROOT.mkdir(exist_ok=True, mode=0o700)
        root_status = OUTPUT_ROOT.lstat()
    except OSError as error:
        raise BrainError(
            "HARD_QUALIFICATION_INVALID", 400, "qualification output root is unavailable"
        ) from error
    if (
        not target.is_absolute()
        or target.parent != OUTPUT_ROOT
        or target.exists()
        or target.is_symlink()
        or target.name.startswith(".env")
        or target.suffix != ".json"
        or not stat.S_ISDIR(root_status.st_mode)
        or stat.S_ISLNK(root_status.st_mode)
        or OUTPUT_ROOT.resolve(strict=True) != OUTPUT_ROOT
    ):
        raise BrainError("HARD_QUALIFICATION_INVALID", 400, "output path is invalid")
    os.chmod(OUTPUT_ROOT, 0o700)
    return target


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    raw = canonical_json(dict(receipt))
    pending = f".{path.name}.{secrets.token_hex(16)}.pending"
    parent_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
    )
    descriptor: int | None = None
    try:
        parent_status = os.fstat(parent_fd)
        named_status = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent_status.st_mode)
            or stat.S_ISLNK(named_status.st_mode)
            or (parent_status.st_dev, parent_status.st_ino)
            != (named_status.st_dev, named_status.st_ino)
        ):
            raise BrainError("HARD_QUALIFICATION_INVALID", 400, "receipt parent is invalid")
        descriptor = os.open(
            pending,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        if os.write(descriptor, raw) != len(raw):
            raise OSError("short receipt write")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(pending, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
        os.unlink(pending, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BaseException:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(OSError):
            os.unlink(pending, dir_fd=parent_fd)
        raise
    finally:
        os.close(parent_fd)


def _terminal_failure(
    *,
    tenant_before: Mapping[str, Any],
    tenant_after: Mapping[str, Any] | None,
    model1_before: Mapping[str, Any],
    model1_after: Mapping[str, Any] | None,
    guard_error: BaseException | None,
    guard_error_phase: str | None,
    suite_error: BaseException | None,
    suite_error_phase: str,
    close_error: BaseException | None,
) -> tuple[BaseException | None, str]:
    """Choose one deterministic terminal gate without hiding stronger drift."""

    if tenant_after is not None and tenant_before != tenant_after:
        return (
            BrainError("HARD_QUALIFICATION_DRIFT", 409, "tenant changed during suite"),
            "tenant_guard",
        )
    if model1_after is not None and model1_before != model1_after:
        return (
            BrainError("HARD_QUALIFICATION_DRIFT", 409, "Model 1 tree changed during suite"),
            "model_guard",
        )
    if guard_error is not None:
        return guard_error, guard_error_phase or "guard"
    if suite_error is not None:
        return suite_error, suite_error_phase
    if close_error is not None:
        return close_error, "close"
    return None, "complete"


def run_hard_qualification(
    *,
    config_path: Path,
    corpus_path: Path,
    plan_path: Path,
    output_path: Path,
    authorize_local_model_execution: bool,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if authorize_local_model_execution is not True:
        raise BrainError(
            "HARD_QUALIFICATION_NOT_AUTHORIZED",
            403,
            "local model execution requires the explicit one-run flag",
        )
    output = _prepare_output(Path(output_path))
    spec = load_hard_qualification(Path(corpus_path), Path(plan_path))
    requested_config = Path(config_path)
    try:
        resolved_config = requested_config.resolve(strict=True)
    except OSError as error:
        raise BrainError(
            "HARD_QUALIFICATION_INVALID", 400, "Brain config is unavailable"
        ) from error
    if resolved_config != spec.config_path or requested_config != spec.config_path:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "Brain config path differs")
    config_raw = _safe_regular_bytes(requested_config, label="Brain config")
    if _sha256(config_raw) != spec.config_sha256:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "Brain config hash differs")
    config = parse_brain_config_bytes(config_raw)
    validate_hard_config(config, spec)
    model1_before = capture_model1_guard()
    tenant_before = capture_tenant_guard(
        root=spec.tenant_root,
        tenant_alias=spec.tenant_alias,
        tenant_id=spec.tenant_id,
        target_path=spec.plan["edit_oracles"][0]["source_path"],
    )
    if tenant_before["commit"] != spec.tenant_head or tenant_before["tree"] != spec.tenant_tree:
        raise BrainError("HARD_QUALIFICATION_INVALID", 409, "tenant Git identity differs")
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    edits: list[dict[str, Any]] = []
    journeys: list[dict[str, Any]] = []
    service: MetisBrainService | None = None
    health: dict[str, Any] = {}
    health_after: dict[str, Any] = {}
    health_identity: dict[str, Any] = {}
    suite_error: BaseException | None = None
    suite_error_phase = "startup"
    close_error: BaseException | None = None
    try:
        service = MetisBrainService(config)
        service.start_background()
        client = HeadlessBrainClient(
            service.address[0],
            service.address[1],
            bootstrap_token=_bootstrap_token(service),
        )
        suite_error_phase = "health_before"
        health = client.health()
        compiler_pin = getattr(service.app.compiler, "pin_identity", None)
        if not isinstance(compiler_pin, Mapping):
            raise BrainError("HARD_QUALIFICATION_RUNTIME", 503, "compiler pin is unavailable")
        health_identity = _validate_qualified_health(
            health,
            expected_identity=spec.runtime_identity,
            compiler_pin=compiler_pin,
        )
        if progress is not None:
            progress({"phase": "ready", "elapsed_ms": int((time.monotonic() - started) * 1000)})
        for index, (case, oracle) in enumerate(
            zip(spec.corpus["endpoints"], spec.plan["edit_oracles"], strict=True),
            start=1,
        ):
            suite_error_phase = "edit"
            result = _run_edit(client=client, spec=spec, case=case, oracle=oracle)
            edits.append(result)
            if progress is not None:
                progress(
                    {
                        "phase": "edit",
                        "index": index,
                        "total": 10,
                        "endpoint": result["endpoint"],
                        "verdict": result["verdict"],
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                )
        for index, (journey, create_target, create_oracle) in enumerate(
            zip(
                spec.corpus["zero_generation_scenarios"],
                spec.plan["create_targets"],
                spec.plan["create_oracles"],
                strict=True,
            ),
            start=1,
        ):
            suite_error_phase = "create_journey"
            result = _run_journey(
                service=service,
                client=client,
                spec=spec,
                journey=journey,
                create_target=create_target,
                create_oracle=create_oracle,
            )
            journeys.append(result)
            if progress is not None:
                progress(
                    {
                        "phase": "create_journey",
                        "index": index,
                        "total": 10,
                        "endpoint": result["source_endpoint"],
                        "verdict": result["verdict"],
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                )
        suite_error_phase = "health_after"
        health_after = client.health()
        health_identity_after = _validate_qualified_health(
            health_after,
            expected_identity=spec.runtime_identity,
            compiler_pin=compiler_pin,
        )
        if health_identity_after != health_identity:
            raise BrainError("HARD_QUALIFICATION_DRIFT", 409, "Brain identity changed during suite")
    except BaseException as error:
        suite_error = error
    finally:
        if service is not None:
            try:
                service.close()
            except BaseException as error:
                close_error = error
    tenant_after: dict[str, Any] | None = None
    model1_after: dict[str, Any] | None = None
    guard_error: BaseException | None = None
    guard_error_phase: str | None = None
    try:
        tenant_after = capture_tenant_guard(
            root=spec.tenant_root,
            tenant_alias=spec.tenant_alias,
            tenant_id=spec.tenant_id,
            target_path=spec.plan["edit_oracles"][0]["source_path"],
        )
    except BaseException as error:
        guard_error = error
        guard_error_phase = "tenant_guard"
    try:
        model1_after = capture_model1_guard()
    except BaseException as error:
        if guard_error is None:
            guard_error = error
            guard_error_phase = "model_guard"
    terminal_error, terminal_phase = _terminal_failure(
        tenant_before=tenant_before,
        tenant_after=tenant_after,
        model1_before=model1_before,
        model1_after=model1_after,
        guard_error=guard_error,
        guard_error_phase=guard_error_phase,
        suite_error=suite_error,
        suite_error_phase=suite_error_phase,
        close_error=close_error,
    )
    terminal_code = (
        (
            terminal_error.code
            if isinstance(terminal_error, BrainError)
            else type(terminal_error).__name__
        )
        if terminal_error is not None
        else None
    )
    logical_turns = sum(
        len(item.get("turns", [])) for item in journeys if isinstance(item.get("turns"), list)
    )
    measurement_complete = (
        len(edits) == EXPECTED_DENOMINATOR["edit_cases"]
        and len(journeys) == EXPECTED_DENOMINATOR["create_journeys"]
        and logical_turns == EXPECTED_DENOMINATOR["logical_create_turns"]
    )
    aggregate = _aggregate(edits, journeys)
    qualification_green = (
        spec.promotable
        and terminal_error is None
        and measurement_complete
        and aggregate["edits"]["pass_draft"] == aggregate["edits"]["total"]
        and aggregate["create_journeys"]["converged_structural_oracle"]
        == aggregate["create_journeys"]["total"]
    )
    receipt_target = (
        output
        if measurement_complete
        else output.with_name(f"{output.stem}.incomplete-{uuid.uuid4().hex}.json")
    )
    body = {
        "schema_version": 1,
        "qualification_id": spec.plan["qualification_id"],
        "status": "MEASURED" if measurement_complete else "INCOMPLETE",
        "measurement_status": "COMPLETE" if measurement_complete else "PARTIAL",
        "receipt_path": str(receipt_target),
        "started_at": started_at,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "identity": {
            "corpus_sha256": spec.corpus_sha256,
            "plan_sha256": spec.plan_sha256,
            "config_sha256": _sha256(config_raw),
            "model1": model1_before,
            "tenant": tenant_before,
            "health_before_sha256": canonical_sha256(health) if health else None,
            "health_after_sha256": canonical_sha256(health_after) if health_after else None,
            "runtime_identity": health_identity or None,
            "model1_after_sha256": (
                canonical_sha256(model1_after) if model1_after is not None else None
            ),
            "tenant_after_sha256": (
                canonical_sha256(tenant_after) if tenant_after is not None else None
            ),
        },
        "boundary": {
            "transport": "numeric_loopback_http",
            "local_mlx": True,
            "external_network": False,
            "apply_capability": False,
            "apply_called": False,
            "tenant_modified": (
                tenant_before != tenant_after if tenant_after is not None else None
            ),
            "model1_modified": (
                model1_before != model1_after if model1_after is not None else None
            ),
        },
        "denominator": dict(EXPECTED_DENOMINATOR),
        "completed": {
            "edits": len(edits),
            "create_journeys": len(journeys),
            "logical_create_turns": logical_turns,
        },
        "aggregate": aggregate,
        "terminal_gate": {
            "status": "FAILED" if terminal_error is not None else "PASSED",
            "phase": terminal_phase,
            "code": terminal_code,
        },
        "promotion_gate": {
            "profile_promotable": spec.promotable,
            "status": (
                "NOT_PROMOTABLE"
                if not spec.promotable
                else ("PASSED" if qualification_green else "FAILED")
            ),
            "reason_code": (
                "REFERENCE_EQUIVALENCE_NOT_REQUIRED"
                if not spec.promotable
                else (None if qualification_green else "QUALIFICATION_GATES_NOT_GREEN")
            ),
        },
        "qualification_green": qualification_green,
        "edits": edits,
        "create_journeys": journeys,
    }
    receipt = {**body, "receipt_sha256": canonical_sha256(body)}
    _write_receipt(receipt_target, receipt)
    return receipt


__all__ = [
    "EXPECTED_CAPABILITIES",
    "EXPECTED_DENOMINATOR",
    "EXPECTED_V2_CORPUS_SHA256",
    "EXPECTED_V2_PLAN_SHA256",
    "EXPECTED_V2_RUNNER_SHA256",
    "HardQualificationSpec",
    "HeadlessBrainClient",
    "clarification_answer",
    "load_hard_qualification",
    "run_hard_qualification",
    "validate_hard_config",
]
