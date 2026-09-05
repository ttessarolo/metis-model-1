"""Blind, headless qualification for ten complex typed-CREATE conversations.

Only the tracked prompt corpus and opaque target are visible while Brain is
running.  Blueprint bytes are opened after every session and the service have
been closed, then compared to hash-only private typed-CREATE receipts.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import metis_model1.brain_hard_qualification as hard
from metis_model1.brain_create_authority_provider_impl_v2 import (
    CREATE_V2_AUTHORITY_PROVIDER_CONTRACT,
)
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    ANSWER_KINDS,
    KINDS,
    MAX_CHOICES,
    MAX_QUESTIONS,
    VALUE_CONTRACTS,
)
from metis_model1.brain_latency_live import capture_model1_guard, capture_tenant_guard
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256, exact_fields
from metis_model1.brain_server import BrainConfig, MetisBrainService, parse_brain_config_bytes
from metis_model1.brain_turns import (
    TYPED_CREATE_CLARIFICATION_RECEIPT_CONTRACT,
    TYPED_CREATE_QUALIFICATION_RECEIPT_CONTRACT,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLIENT_ID = "brain-complex-create-qualification"
CLIENT_CAPABILITIES = frozenset(
    {"chat.read", "chat.turn", "compile", "context.read", "session.close", "session.read"}
)
EXPECTED_CASES = tuple(f"case_{index:02d}" for index in range(1, 11))
_HASH_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CASE_RE = re.compile(r"case_[0-9]{2}\Z")
_GAP_SELECTOR_RE = re.compile(r"\[([^\]\r\n]{1,96})\]")
_GAP_SEPARATOR_RE = re.compile(r"[^a-z0-9_.:-]+")


@dataclass(frozen=True)
class ComplexCreateProfile:
    """Code-owned, closed input and oracle roster for one qualification cohort."""

    profile_id: str
    qualification_id: str
    prompt_path: Path
    prompt_relative_path: str
    prompt_sha256: str
    prompt_artifact_id: str
    prompt_artifact_version: int
    plan_path: Path
    plan_sha256: str
    config_path: Path
    config_relative_path: str
    config_sha256: str
    tenant_alias: str
    tenant_id: str
    tenant_root: Path
    tenant_head: str
    tenant_tree: str
    target_directory: str
    target_endpoint_prefix: str
    expected_cases: tuple[str, ...]
    scenario_ids: tuple[tuple[str, str], ...]
    initial_gap_targets: tuple[tuple[str, str], ...]
    denominator: tuple[tuple[str, int], ...]
    blueprint_pins: tuple[tuple[str, str, str], ...]

    def initial_gap_map(self) -> dict[str, str]:
        return dict(self.initial_gap_targets)

    def scenario_map(self) -> dict[str, str]:
        return dict(self.scenario_ids)

    def denominator_map(self) -> dict[str, int]:
        return dict(self.denominator)

    def blueprint_map(self) -> dict[str, tuple[str, str]]:
        return {kind: (path, sha256) for kind, path, sha256 in self.blueprint_pins}


_V3_PROFILE = ComplexCreateProfile(
    profile_id="play-prod-v3",
    qualification_id="metis-brain-complex-create/play-prod-v3",
    prompt_path=(PROJECT_ROOT / "examples/metis-brain-complex-create-prompts.play-prod-v3.json"),
    prompt_relative_path="examples/metis-brain-complex-create-prompts.play-prod-v3.json",
    prompt_sha256="sha256:3e32180d42614774cbdef7862a809cab19eeef896fedc658efb53811f672c7c8",
    prompt_artifact_id="metis-brain-complex-create-prompts.play-prod-v3",
    prompt_artifact_version=3,
    plan_path=(
        PROJECT_ROOT / "examples/metis-brain-complex-create-qualification.play-prod-v3.json"
    ),
    plan_sha256="sha256:8f499e87b7faf695e58a34ee8b65494dd7ccb07746a4755fb431359ece1b0249",
    config_path=PROJECT_ROOT / "examples/metis-brain-config.play-prod-complex-create.local.json",
    config_relative_path="examples/metis-brain-config.play-prod-complex-create.local.json",
    config_sha256="sha256:38454eb6db5aaac9adc13875da20d478d98bd846183752f7366db8d2eeeaab24",
    tenant_alias="play-prod",
    tenant_id="play-prod-v2",
    tenant_root=Path("/Users/tommasotessarolo/Developer/metis-tenant-play-prod"),
    tenant_head="98e78407f7286d2a9ac404dceb655fd1f6a9118e",
    tenant_tree="914785f55c2be453ee75a6314f4e9e77010eed25",
    target_directory="properties/brain_qualification_v3",
    target_endpoint_prefix="brain_qualification_v3",
    expected_cases=EXPECTED_CASES,
    scenario_ids=(
        ("case_01", "play.similar_cinema"),
        ("case_02", "play.similar_serie_tv_fiction"),
        ("case_03", "search.filtered_search"),
        ("case_04", "search.detail"),
        ("case_05", "play.multiple_block_compleanno"),
        ("case_06", "play.multiple_block_dem_titoli_momento"),
        ("case_07", "play.tvod_multiple_block"),
        ("case_08", "play.multiple_block4_k"),
        ("case_09", "play.inf_multiple_block_film_serie"),
        ("case_10", "play.similar_intrat_abtest"),
    ),
    initial_gap_targets=(
        ("case_01", "endpoint.results.total"),
        ("case_02", "endpoint.results.total"),
        ("case_03", "endpoint.results.page"),
        ("case_04", "catalog.selection"),
        ("case_05", "catalog.selection"),
        ("case_06", "endpoint.results.total"),
        ("case_07", "endpoint.results.total"),
        ("case_08", "endpoint.results.row"),
        ("case_09", "endpoint.rows.page"),
        ("case_10", "endpoint.results.row"),
    ),
    denominator=(
        ("journeys", 10),
        ("operator_messages", 40),
        ("initial_ask_stages", 10),
        ("assessed_stages", 30),
        ("expected_ready", 6),
        ("expected_blocked", 24),
    ),
    blueprint_pins=(
        (
            "similar",
            "examples/metis-brain-create-blueprints-v3-similar.json",
            "sha256:26d940a76fe0ce24be3cce49a372a5f58c6751cd7c19f7e62338e452f5d42394",
        ),
        (
            "search",
            "examples/metis-brain-create-blueprints-v3-search.json",
            "sha256:878cdbbf0ca6fbd451840a937ffd8628459ecb68efafd75e7034d80c615bcbe0",
        ),
        (
            "multiblock",
            "examples/metis-brain-create-blueprints-v3-multiblock.json",
            "sha256:ceb78b47f49c58fa182e2d4b29a6ab3266c856fa20098427535bc78f97941866",
        ),
    ),
)
_V4_PROFILE = ComplexCreateProfile(
    profile_id="play-prod-v4",
    qualification_id="metis-brain-complex-create/play-prod-v4",
    prompt_path=(PROJECT_ROOT / "examples/metis-brain-complex-create-prompts.play-prod-v4.json"),
    prompt_relative_path="examples/metis-brain-complex-create-prompts.play-prod-v4.json",
    prompt_sha256="sha256:3705c6907206e51d1e379b732f2add46ac5cd48a1e0d4f550edd6fac60e954bf",
    prompt_artifact_id="metis-brain-complex-create-prompts.play-prod-v4",
    prompt_artifact_version=4,
    plan_path=(
        PROJECT_ROOT / "examples/metis-brain-complex-create-qualification.play-prod-v4.json"
    ),
    plan_sha256="sha256:587301308e048b4251212285d33de5e16c87ac39ec381defe02e325a5f869bf5",
    config_path=PROJECT_ROOT / "examples/metis-brain-config.play-prod-complex-create.local.json",
    config_relative_path="examples/metis-brain-config.play-prod-complex-create.local.json",
    config_sha256="sha256:38454eb6db5aaac9adc13875da20d478d98bd846183752f7366db8d2eeeaab24",
    tenant_alias="play-prod",
    tenant_id="play-prod-v2",
    tenant_root=Path("/Users/tommasotessarolo/Developer/metis-tenant-play-prod"),
    tenant_head="98e78407f7286d2a9ac404dceb655fd1f6a9118e",
    tenant_tree="914785f55c2be453ee75a6314f4e9e77010eed25",
    target_directory="properties/brain_qualification_v4",
    target_endpoint_prefix="brain_qualification_v4",
    expected_cases=tuple(f"case_{index:02d}" for index in range(11, 21)),
    scenario_ids=(
        ("case_11", "play.multiple_block_dem_scelti_per_te"),
        ("case_12", "play.subscription_channel_film"),
        ("case_13", "play.inf_smart_block_film"),
        ("case_14", "search.main"),
        ("case_15", "play.new_similar_intrattenimento"),
        ("case_16", "play.enabler_test_film"),
        ("case_17", "play.similar_sport"),
        ("case_18", "play.similar_documentari"),
        ("case_19", "play.fnjwq5_lha2"),
        ("case_20", "play.inf_multiple_block_film"),
    ),
    initial_gap_targets=(
        ("case_11", "endpoint.results.total"),
        ("case_12", "endpoint.results.total"),
        ("case_13", "endpoint.results.total"),
        ("case_14", "endpoint.results.page"),
        ("case_15", "endpoint.results.row"),
        ("case_16", "endpoint.results.total"),
        ("case_17", "endpoint.results.total"),
        ("case_18", "endpoint.results.total"),
        ("case_19", "endpoint.results.total"),
        ("case_20", "endpoint.results.total"),
    ),
    denominator=(
        ("journeys", 10),
        ("operator_messages", 40),
        ("initial_ask_stages", 10),
        ("assessed_stages", 30),
        ("expected_ready", 9),
        ("expected_blocked", 21),
    ),
    blueprint_pins=(
        (
            "cohort2",
            "examples/metis-brain-create-blueprints-v4.json",
            "sha256:536e50115d18f815372339690bead38fefe37c800b0057feeeda8a4bbedd80df",
        ),
    ),
)
_PROFILES_BY_PATHS: dict[tuple[Path, Path], ComplexCreateProfile] = {
    (profile.prompt_path, profile.plan_path): profile for profile in (_V3_PROFILE, _V4_PROFILE)
}

# Stable v3 aliases retained for callers and historical evidence.
PROMPT_PATH = _V3_PROFILE.prompt_path
PLAN_PATH = _V3_PROFILE.plan_path
PROMPT_SHA256 = _V3_PROFILE.prompt_sha256
PLAN_SHA256 = _V3_PROFILE.plan_sha256
CONFIG_SHA256 = _V3_PROFILE.config_sha256
QUALIFICATION_ID = _V3_PROFILE.qualification_id
EXPECTED_INITIAL_GAP_TARGET = _V3_PROFILE.initial_gap_map()
EXPECTED_DENOMINATOR = _V3_PROFILE.denominator_map()
V4_PROMPT_PATH = _V4_PROFILE.prompt_path
V4_PLAN_PATH = _V4_PROFILE.plan_path
V4_PROMPT_SHA256 = _V4_PROFILE.prompt_sha256
V4_PLAN_SHA256 = _V4_PROFILE.plan_sha256
V4_EXPECTED_DENOMINATOR = _V4_PROFILE.denominator_map()


@dataclass(frozen=True)
class ComplexCreateTarget:
    case_id: str
    scenario_id: str
    relative_path: str
    endpoint: str


@dataclass(frozen=True)
class ComplexCreateQualificationSpec:
    profile: ComplexCreateProfile
    prompt_path: Path
    prompt_sha256: str
    prompt: dict[str, Any]
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
    targets: tuple[ComplexCreateTarget, ...]


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = hard._safe_regular_bytes(path, label=label)  # noqa: SLF001
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrainError("COMPLEX_CREATE_INVALID", 400, f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise BrainError("COMPLEX_CREATE_INVALID", 400, f"{label} is invalid")
    return raw, value


def _project_path(value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise BrainError("COMPLEX_CREATE_INVALID", 400, f"{label} path is invalid")
    candidate = PROJECT_ROOT / value
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise BrainError("COMPLEX_CREATE_INVALID", 400, f"{label} is unavailable") from error
    if resolved.parent != PROJECT_ROOT / "examples" or candidate != resolved:
        raise BrainError("COMPLEX_CREATE_INVALID", 400, f"{label} path is invalid")
    return resolved


def _validate_profile(profile: ComplexCreateProfile) -> None:
    cases = profile.expected_cases
    denominator = profile.denominator_map()
    scenario_map = profile.scenario_map()
    gap_map = profile.initial_gap_map()
    blueprint_map = profile.blueprint_map()
    if (
        not profile.profile_id
        or not profile.qualification_id
        or len(cases) != len(set(cases))
        or any(_CASE_RE.fullmatch(case) is None for case in cases)
        or set(scenario_map) != set(cases)
        or len(set(scenario_map.values())) != len(cases)
        or set(gap_map) != set(cases)
        or len(blueprint_map) != len(profile.blueprint_pins)
        or set(denominator)
        != {
            "journeys",
            "operator_messages",
            "initial_ask_stages",
            "assessed_stages",
            "expected_ready",
            "expected_blocked",
        }
        or denominator["journeys"] != len(cases)
        or denominator["operator_messages"] != len(cases) * 4
        or denominator["initial_ask_stages"] != len(cases)
        or denominator["assessed_stages"] != len(cases) * 3
        or denominator["expected_ready"] + denominator["expected_blocked"]
        != denominator["assessed_stages"]
        or not profile.target_directory.startswith("properties/brain_qualification_")
        or not profile.target_endpoint_prefix.startswith("brain_qualification_")
        or any(
            _HASH_RE.fullmatch(value) is None
            for value in (profile.prompt_sha256, profile.plan_sha256, profile.config_sha256)
        )
        or any(
            _HASH_RE.fullmatch(sha256) is None for _kind, _path, sha256 in profile.blueprint_pins
        )
    ):
        raise BrainError("COMPLEX_CREATE_INVALID", 500, "qualification profile is invalid")


def _parse_prompts(
    value: dict[str, Any], *, profile: ComplexCreateProfile
) -> tuple[dict[str, Any], ...]:
    exact_fields(
        value,
        required={
            "artifact_id",
            "artifact_version",
            "language",
            "purpose",
            "safety_boundary",
            "journeys",
        },
        label="complex CREATE prompt corpus",
    )
    boundary = value["safety_boundary"]
    journeys = value["journeys"]
    if (
        value["artifact_id"] != profile.prompt_artifact_id
        or value["artifact_version"] != profile.prompt_artifact_version
        or value["language"] != "it"
        or not isinstance(value["purpose"], str)
        or not isinstance(boundary, dict)
        or boundary
        != {
            "contains_blueprints": False,
            "contains_reference_endpoints": False,
            "contains_expected_specs": False,
            "contains_credentials": False,
            "contains_raw_live_payloads": False,
            "apply_authorized": False,
        }
        or not isinstance(journeys, list)
        or len(journeys) != len(profile.expected_cases)
    ):
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "prompt corpus is not qualified")
    parsed: list[dict[str, Any]] = []
    for expected_case, journey in zip(profile.expected_cases, journeys, strict=True):
        if not isinstance(journey, dict):
            raise BrainError("COMPLEX_CREATE_INVALID", 400, "prompt journey is invalid")
        exact_fields(journey, required={"case_id", "messages"}, label="prompt journey")
        messages = journey["messages"]
        if (
            journey["case_id"] != expected_case
            or not isinstance(messages, list)
            or len(messages) != 4
            or any(
                not isinstance(message, str)
                or not message.strip()
                or len(message.encode("utf-8")) > 8_192
                for message in messages
            )
        ):
            raise BrainError("COMPLEX_CREATE_INVALID", 400, "prompt journey is invalid")
        parsed.append({"case_id": expected_case, "messages": tuple(messages)})
    return tuple(parsed)


def load_complex_create_qualification(
    *,
    prompt_path: Path = PROMPT_PATH,
    plan_path: Path = PLAN_PATH,
) -> ComplexCreateQualificationSpec:
    """Load only prompts, routing metadata and pins; never open a blueprint."""

    prompt_path = Path(prompt_path)
    plan_path = Path(plan_path)
    profile = _PROFILES_BY_PATHS.get((prompt_path, plan_path))
    if profile is None:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "qualification paths differ")
    _validate_profile(profile)
    prompt_raw, prompt = _read_json(prompt_path, label="complex CREATE prompt corpus")
    plan_raw, plan = _read_json(plan_path, label="complex CREATE qualification plan")
    if _sha256(prompt_raw) != profile.prompt_sha256 or _sha256(plan_raw) != profile.plan_sha256:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "qualification input hash differs")
    journeys = _parse_prompts(prompt, profile=profile)
    exact_fields(
        plan,
        required={
            "schema_version",
            "qualification_id",
            "prompt_corpus",
            "config",
            "authority",
            "runtime_identity",
            "execution_boundary",
            "blueprints",
            "targets",
            "denominator",
        },
        label="complex CREATE qualification plan",
    )
    prompt_pin = plan["prompt_corpus"]
    config_pin = plan["config"]
    authority = plan["authority"]
    boundary = plan["execution_boundary"]
    blueprint_pins = plan["blueprints"]
    targets = plan["targets"]
    if any(
        not isinstance(item, dict)
        for item in (prompt_pin, config_pin, authority, boundary, plan["runtime_identity"])
    ):
        raise BrainError("COMPLEX_CREATE_INVALID", 400, "qualification plan is invalid")
    if (
        plan["schema_version"] != 1
        or plan["qualification_id"] != profile.qualification_id
        or prompt_pin
        != {
            "path": profile.prompt_relative_path,
            "sha256": profile.prompt_sha256,
        }
        or boundary
        != {
            "transport": "numeric_loopback_http",
            "one_session_per_journey": True,
            "apply_authorized": False,
            "blueprint_load_phase": "after_service_close",
            "qualification_proof": TYPED_CREATE_QUALIFICATION_RECEIPT_CONTRACT,
            "clarification_proof": TYPED_CREATE_CLARIFICATION_RECEIPT_CONTRACT,
            "required_generation_strategy": "model_create_plan_v2",
        }
        or plan["denominator"] != profile.denominator_map()
        or not isinstance(blueprint_pins, list)
        or len(blueprint_pins) != len(profile.blueprint_pins)
        or not isinstance(targets, list)
        or len(targets) != len(profile.expected_cases)
    ):
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "qualification plan is not qualified")
    runtime_identity = plan["runtime_identity"]
    if set(runtime_identity) != {
        "model",
        "intent_compiler",
        "semantic_retrieval",
        "toolchain",
        "typed_create",
    }:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "runtime identity roster differs")
    _validate_typed_create_identity(runtime_identity.get("typed_create"))
    exact_blueprints = profile.blueprint_map()
    observed_blueprints: dict[str, tuple[str, str]] = {}
    for item in blueprint_pins:
        if not isinstance(item, dict):
            raise BrainError("COMPLEX_CREATE_INVALID", 400, "blueprint pin is invalid")
        exact_fields(item, required={"kind", "path", "sha256"}, label="blueprint pin")
        observed_blueprints[item["kind"]] = (item["path"], item["sha256"])
    if observed_blueprints != exact_blueprints:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "blueprint roster differs")
    parsed_targets: list[ComplexCreateTarget] = []
    scenario_map = profile.scenario_map()
    for expected_case, item in zip(profile.expected_cases, targets, strict=True):
        if not isinstance(item, dict):
            raise BrainError("COMPLEX_CREATE_INVALID", 400, "qualification target is invalid")
        exact_fields(
            item,
            required={"case_id", "scenario_id", "relative_path", "endpoint"},
            label="qualification target",
        )
        expected_path = f"{profile.target_directory}/{expected_case}.metis"
        expected_endpoint = f"{profile.target_endpoint_prefix}.{expected_case}"
        if (
            item["case_id"] != expected_case
            or _CASE_RE.fullmatch(expected_case) is None
            or item["relative_path"] != expected_path
            or item["endpoint"] != expected_endpoint
            or item["scenario_id"] != scenario_map[expected_case]
        ):
            raise BrainError("COMPLEX_CREATE_INVALID", 400, "qualification target is invalid")
        parsed_targets.append(ComplexCreateTarget(**item))
    if tuple(item["case_id"] for item in journeys) != tuple(
        target.case_id for target in parsed_targets
    ):
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "prompt and target rosters differ")
    config_path = _project_path(config_pin.get("path"), label="Brain config")
    if config_pin != {
        "path": profile.config_relative_path,
        "sha256": profile.config_sha256,
    }:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "Brain config pin differs")
    tenant_root = Path(authority.get("root", ""))
    if (
        authority
        != {
            "tenant_alias": profile.tenant_alias,
            "tenant_id": profile.tenant_id,
            "root": str(profile.tenant_root),
            "head": profile.tenant_head,
            "tree": profile.tenant_tree,
        }
        or not tenant_root.is_absolute()
    ):
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "tenant authority differs")
    return ComplexCreateQualificationSpec(
        profile=profile,
        prompt_path=prompt_path,
        prompt_sha256=profile.prompt_sha256,
        prompt=prompt,
        plan_path=plan_path,
        plan_sha256=profile.plan_sha256,
        plan=plan,
        config_path=config_path,
        config_sha256=config_pin["sha256"],
        runtime_identity=deepcopy(plan["runtime_identity"]),
        tenant_root=tenant_root,
        tenant_alias=authority["tenant_alias"],
        tenant_id=authority["tenant_id"],
        tenant_head=authority["head"],
        tenant_tree=authority["tree"],
        targets=tuple(parsed_targets),
    )


def _event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        item.get("event")
        for item in events
        if isinstance(item, dict) and isinstance(item.get("event"), str)
    )
    return {
        "inference": counts["inference.started"],
        "compile": counts["compile.started"],
        "repair": counts["repair.started"],
        "terminal": counts["terminal"],
    }


def _hash_only_terminal_summary(terminal: Mapping[str, Any], elapsed_ms: int) -> dict[str, Any]:
    """Allowlist qualification metadata and never persist generated Draft text."""

    summary = hard._terminal_summary(terminal, elapsed_ms)  # noqa: SLF001
    allowed = (
        "status",
        "outcome",
        "elapsed_ms",
        "error_code",
        "generation_strategy",
        "compile_status",
        "compile_attempts",
        "compiler_receipt_sha256",
        "grounding_status",
        "grounding_sha256",
        "proposal_ref",
        "proposal_source_sha256",
        "claims",
    )
    return {key: summary.get(key) for key in allowed}


def _validate_typed_create_identity(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "enabled",
            "implementation",
            "contract_id",
            "policy_revision",
            "inventory_revision",
        }
        or value.get("enabled") is not True
        or value.get("implementation") != "PinnedCreateV2AuthorityProvider"
        or value.get("contract_id") != CREATE_V2_AUTHORITY_PROVIDER_CONTRACT
        or not isinstance(value.get("policy_revision"), str)
        or _HASH_RE.fullmatch(value["policy_revision"]) is None
        or not isinstance(value.get("inventory_revision"), str)
        or _HASH_RE.fullmatch(value["inventory_revision"]) is None
    ):
        raise BrainError(
            "COMPLEX_CREATE_RUNTIME",
            503,
            "pinned typed CREATE authority identity is invalid",
        )
    return dict(value)


def _validate_typed_create_health(
    health: Mapping[str, Any], *, expected: Mapping[str, Any]
) -> dict[str, Any]:
    typed_create = health.get("typed_create")
    expected_identity = _validate_typed_create_identity(expected)
    if not isinstance(typed_create, Mapping) or dict(typed_create) != expected_identity:
        raise BrainError(
            "COMPLEX_CREATE_RUNTIME",
            503,
            "pinned typed CREATE authority is not enabled",
        )
    return dict(typed_create)


def _normalized_gap_key(value: Any) -> str | None:
    """Normalize blueprint selectors and provider-safe target keys for comparison."""

    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        return None

    def selector(match: re.Match[str]) -> str:
        members = tuple(item.strip() for item in match.group(1).split(","))
        if members == ("*",):
            return ""
        if not members or any(re.fullmatch(r"[a-z0-9_:-]+", item) is None for item in members):
            return ""
        return "." + ".".join(members)

    normalized = _GAP_SELECTOR_RE.sub(selector, value.casefold())
    normalized = _GAP_SEPARATOR_RE.sub(".", normalized)
    normalized = re.sub(r"\.{2,}", ".", normalized).strip(".")
    return normalized or None


def _clarification_gap_targets(
    proof: Any,
    *,
    turn_id: Any,
    expected_binding_sha256: Any,
) -> set[str] | None:
    """Verify a redacted clarification receipt and return its target-key set."""

    if not isinstance(proof, dict):
        return None
    expected_fields = {
        "contract_id",
        "turn_id",
        "round",
        "slot_contracts",
        "slot_contracts_sha256",
        "binding_sha256",
        "receipt_sha256",
    }
    slots = proof.get("slot_contracts")
    body = {key: value for key, value in proof.items() if key != "receipt_sha256"}
    if (
        set(proof) != expected_fields
        or proof.get("contract_id") != TYPED_CREATE_CLARIFICATION_RECEIPT_CONTRACT
        or proof.get("turn_id") != turn_id
        or type(proof.get("round")) is not int
        or not 1 <= proof["round"] <= 3
        or not isinstance(slots, list)
        or not slots
        or len(slots) > MAX_QUESTIONS
        or canonical_sha256(slots) != proof.get("slot_contracts_sha256")
        or canonical_sha256(body) != proof.get("receipt_sha256")
        or proof.get("binding_sha256") != expected_binding_sha256
        or not isinstance(expected_binding_sha256, str)
        or _HASH_RE.fullmatch(expected_binding_sha256) is None
    ):
        return None
    target_keys: set[str] = set()
    expected_slot_fields = {
        "decision_key",
        "target_key",
        "kind",
        "answer_kind",
        "value_contract",
        "minimum",
        "maximum",
        "choice_count",
    }
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != expected_slot_fields:
            return None
        target_key = _normalized_gap_key(slot.get("target_key"))
        if (
            target_key is None
            or not isinstance(slot.get("decision_key"), str)
            or slot.get("kind") not in KINDS
            or slot.get("answer_kind") not in ANSWER_KINDS
            or slot.get("value_contract") not in VALUE_CONTRACTS
            or type(slot.get("minimum")) is not int
            or type(slot.get("maximum")) is not int
            or not 1 <= slot["minimum"] <= slot["maximum"] <= 1_000_000
            or type(slot.get("choice_count")) is not int
            or not 0 <= slot["choice_count"] <= MAX_CHOICES
        ):
            return None
        answer_kind = slot["answer_kind"]
        value_contract = slot["value_contract"]
        choice_count = slot["choice_count"]
        if answer_kind == "integer":
            if (
                choice_count != 0
                or slot["kind"] not in {"result_count", "structural_choice"}
                or value_contract == "authority"
                or (
                    value_contract == "over_fetch"
                    and not 2 <= slot["minimum"] <= slot["maximum"] <= 16
                )
            ):
                return None
        elif (
            value_contract != "authority"
            or choice_count < 1
            or (
                answer_kind == "option_refs"
                and not 1 <= slot["minimum"] <= slot["maximum"] <= choice_count
            )
        ):
            return None
        target_keys.add(target_key)
    return target_keys


def _typed_create_proof_matches(
    proof: Any,
    *,
    record: Mapping[str, Any],
    expected_spec_sha256: str,
    expected_generation: Any,
) -> bool:
    """Verify the complete private Draft receipt, not only its spec digest."""

    if not isinstance(proof, dict):
        return False
    expected_fields = {
        "contract_id",
        "turn_id",
        "generation",
        "source_sha256",
        "manifest_sha256",
        "spec_sha256",
        "ir_sha256",
        "parent_ir_sha256",
        "delta_sha256",
        "delta_operation_count",
        "history_revision",
        "compiler_receipt_sha256",
        "generation_strategy",
        "receipt_sha256",
    }
    body = {key: value for key, value in proof.items() if key != "receipt_sha256"}
    hashes = tuple(
        proof.get(key)
        for key in (
            "source_sha256",
            "manifest_sha256",
            "spec_sha256",
            "ir_sha256",
            "delta_sha256",
            "history_revision",
            "compiler_receipt_sha256",
        )
    )
    parent_ir_sha256 = proof.get("parent_ir_sha256")
    terminal = record.get("terminal")
    return bool(
        set(proof) == expected_fields
        and proof.get("contract_id") == TYPED_CREATE_QUALIFICATION_RECEIPT_CONTRACT
        and proof.get("turn_id") == record.get("turn_id")
        and type(expected_generation) is int
        and proof.get("generation") == expected_generation
        and all(isinstance(value, str) and _HASH_RE.fullmatch(value) for value in hashes)
        and (
            (expected_generation == 0 and parent_ir_sha256 is None)
            or (
                expected_generation > 0
                and isinstance(parent_ir_sha256, str)
                and _HASH_RE.fullmatch(parent_ir_sha256) is not None
            )
        )
        and type(proof.get("delta_operation_count")) is int
        and 0 <= proof["delta_operation_count"] <= 10_000
        and proof.get("spec_sha256") == expected_spec_sha256
        and proof.get("generation_strategy") == "model_create_plan_v2"
        and isinstance(terminal, Mapping)
        and proof.get("source_sha256") == terminal.get("proposal_source_sha256")
        and proof.get("compiler_receipt_sha256") == terminal.get("compiler_receipt_sha256")
        and canonical_sha256(body) == proof.get("receipt_sha256")
    )


def _dialogue_binding_sha256(
    *,
    context: Mapping[str, Any],
    messages: list[str],
    request_fingerprint: str,
) -> str:
    history = tuple(
        CreateAuthorityHistoryMessage(
            ordinal=index,
            text=message,
            message_sha256=bytes_sha256(message.encode("utf-8")),
        )
        for index, message in enumerate(messages)
    )
    return canonical_sha256(
        {
            "context_revision": context["revision"],
            "semantic_revision": context["semantic_source_revision"],
            "toolchain_binding": context["toolchain_binding"],
            "history_revision": create_authority_history_revision(history),
            "parent_fingerprint": request_fingerprint,
        }
    )


def _validate_complex_config(config: BrainConfig, spec: ComplexCreateQualificationSpec) -> None:
    policies = [item for item in config.client_policies if item.client_id == CLIENT_ID]
    tenants = [item for item in config.tenant_grants if item[0] == spec.tenant_alias]
    if (
        config.host != "127.0.0.1"
        or config.port != 0
        or config.runtime_root != hard.OUTPUT_ROOT / "runtime-v3"
        or len(config.tenant_grants) != 1
        or tenants != [(spec.tenant_alias, spec.tenant_id, spec.tenant_root)]
        or len(config.client_policies) != 1
        or len(policies) != 1
        or policies[0].tenant_aliases != frozenset({spec.tenant_alias})
        or policies[0].capabilities != CLIENT_CAPABILITIES
        or config.model is None
        or config.model.warmup != "on_start"
        or config.retrieval is None
        or config.retrieval.schema2 is not True
        or config.retrieval.warmup != "on_start"
        or config.intent_compiler is None
        or config.intent_compiler.warmup != "on_start"
        or config.intent_compiler.mode != "assist_on_unresolved"
        or config.typed_create is not True
    ):
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "Brain config is not qualified")


def _run_journey(
    *,
    service: MetisBrainService,
    client: hard.HeadlessBrainClient,
    spec: ComplexCreateQualificationSpec,
    journey: Mapping[str, Any],
    target: ComplexCreateTarget,
) -> dict[str, Any]:
    session = client.open_session(tenant_alias=spec.tenant_alias)
    records: list[dict[str, Any]] = []
    try:
        context = client.context(session)
        previous_terminal: dict[str, Any] | None = None
        proposal_ref: str | None = None
        dialogue_messages: list[str] = []
        last_request_basis: dict[str, Any] | None = None
        for ordinal, message in enumerate(journey["messages"], start=1):
            dialogue_messages.append(message)
            started = time.monotonic()
            submission = "turn"
            request_sha256: str
            request_fingerprint: str
            if (
                previous_terminal is not None
                and previous_terminal.get("outcome") == "needs_clarification"
            ):
                clarification = previous_terminal.get("clarification")
                if not isinstance(clarification, Mapping) or not isinstance(
                    clarification.get("clarification_id"), str
                ):
                    raise BrainError(
                        "COMPLEX_CREATE_RUNTIME", 503, "clarification authority is unavailable"
                    )
                submission = "answer_v2"
                answer_body = {
                    "schema_version": 2,
                    "clarification_id": clarification["clarification_id"],
                    "message": message,
                    "answers": [],
                }
                request_sha256 = canonical_sha256(answer_body)
                request_fingerprint = canonical_sha256(
                    {
                        "expected_context_revision": context["revision"],
                        "expected_semantic_source_revision": context["semantic_source_revision"],
                        "intent": "create",
                        "instruction": message,
                        "target": {
                            "mode": "create",
                            "relative_path": target.relative_path,
                            "endpoint": target.endpoint,
                            "base_sha256": None,
                            "reference": None,
                        },
                        "basis": last_request_basis,
                    }
                )
                turn_id = client.answer_v2(
                    session,
                    parent_turn_id=str(previous_terminal["turn_id"]),
                    clarification_id=clarification["clarification_id"],
                    message=message,
                    answers=(),
                )
            else:
                body = hard._turn_body(  # noqa: SLF001
                    context=context,
                    instruction=message,
                    intent="create",
                    target={
                        "mode": "create",
                        "relative_path": target.relative_path,
                        "endpoint": target.endpoint,
                        "base_sha256": None,
                        "reference": None,
                    },
                    basis=proposal_ref,
                )
                request_sha256 = canonical_sha256(body)
                request_fingerprint = canonical_sha256(
                    {
                        key: body[key]
                        for key in (
                            "expected_context_revision",
                            "expected_semantic_source_revision",
                            "intent",
                            "instruction",
                            "target",
                            "basis",
                        )
                    }
                )
                last_request_basis = deepcopy(body["basis"])
                turn_id = client.submit(session, body)
            current_dialogue_binding_sha256 = _dialogue_binding_sha256(
                context=context,
                messages=dialogue_messages,
                request_fingerprint=request_fingerprint,
            )
            terminal, _ = client.wait_terminal(session, turn_id)
            dialogue_binding_sha256 = current_dialogue_binding_sha256
            if (
                terminal.get("outcome") == "needs_clarification"
                and previous_terminal is not None
                and previous_terminal.get("outcome") == "needs_clarification"
                and isinstance(terminal.get("clarification"), Mapping)
                and isinstance(previous_terminal.get("clarification"), Mapping)
                and terminal["clarification"].get("clarification_id")
                == previous_terminal["clarification"].get("clarification_id")
                and records
            ):
                # An unresolved free-form answer replays the still-live server
                # question.  Its private binding remains the original issuing
                # turn's binding, not the newly appended dialogue message.
                dialogue_binding_sha256 = records[-1]["dialogue_binding_sha256"]
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            events = client.events(session, turn_id)
            counts = _event_counts(events)
            proof = None
            clarification_proof = None
            proposal = terminal.get("proposal")
            if terminal.get("outcome") == "proposed":
                proof = service.app.turns.seal_typed_create_qualification_receipt(
                    session_id=str(session["id"]),
                    token=str(session["token"]),
                    turn_id=turn_id,
                )
                if not isinstance(proposal, Mapping) or not isinstance(
                    proposal.get("proposal_ref"), str
                ):
                    raise BrainError("COMPLEX_CREATE_RUNTIME", 503, "proposal is unavailable")
                proposal_ref = proposal["proposal_ref"]
            elif terminal.get("outcome") == "needs_clarification":
                clarification_proof = service.app.turns.seal_typed_create_clarification_receipt(
                    session_id=str(session["id"]),
                    token=str(session["token"]),
                    turn_id=turn_id,
                )
            records.append(
                {
                    "turn": ordinal,
                    "submission": submission,
                    "turn_id": turn_id,
                    "request_sha256": request_sha256,
                    "dialogue_binding_sha256": dialogue_binding_sha256,
                    "elapsed_ms": elapsed_ms,
                    "terminal": _hash_only_terminal_summary(terminal, elapsed_ms),
                    "event_counts": counts,
                    "qualification_proof": proof,
                    "clarification_proof": clarification_proof,
                    "clarification_sha256": (
                        canonical_sha256(terminal["clarification"])
                        if isinstance(terminal.get("clarification"), Mapping)
                        else None
                    ),
                }
            )
            previous_terminal = terminal
        return {"case_id": target.case_id, "target": target.endpoint, "turns": records}
    finally:
        client.close_session(session)


def _load_blueprint_stages(spec: ComplexCreateQualificationSpec) -> dict[str, dict[str, Any]]:
    """Open blueprint bytes only from the post-close assessment phase."""

    stages: dict[str, dict[str, Any]] = {}
    for pin in spec.plan["blueprints"]:
        path = _project_path(pin["path"], label="CREATE blueprint")
        raw, value = _read_json(path, label="CREATE blueprint")
        if _sha256(raw) != pin["sha256"]:
            raise BrainError("COMPLEX_CREATE_ORACLE", 409, "blueprint hash differs")
        if pin["kind"] in {"similar", "search"}:
            roster = value.get("stages")
            if not isinstance(roster, list):
                raise BrainError("COMPLEX_CREATE_ORACLE", 400, "blueprint stages are invalid")
            pairs = [(item.get("stage_id"), item) for item in roster if isinstance(item, dict)]
        else:
            scenarios = value.get("scenarios")
            if not isinstance(scenarios, list):
                raise BrainError("COMPLEX_CREATE_ORACLE", 400, "blueprint stages are invalid")
            pairs = []
            for scenario in scenarios:
                if not isinstance(scenario, dict) or not isinstance(scenario.get("stages"), list):
                    raise BrainError("COMPLEX_CREATE_ORACLE", 400, "blueprint stages are invalid")
                for item in scenario["stages"]:
                    if isinstance(item, dict):
                        pairs.append(
                            (f"{scenario.get('scenario_id')}:{item.get('stage_id')}", item)
                        )
        for stage_id, item in pairs:
            if not isinstance(stage_id, str) or stage_id in stages:
                raise BrainError("COMPLEX_CREATE_ORACLE", 400, "blueprint stage roster is invalid")
            stages[stage_id] = deepcopy(item)
    if len(stages) != spec.profile.denominator_map()["assessed_stages"]:
        raise BrainError("COMPLEX_CREATE_ORACLE", 409, "blueprint denominator differs")
    return stages


def _expected_spec_sha256(stage: Mapping[str, Any], *, endpoint: str) -> str:
    source_spec = stage.get("spec")
    if not isinstance(source_spec, dict) or canonical_sha256(source_spec) != stage.get(
        "spec_sha256"
    ):
        raise BrainError("COMPLEX_CREATE_ORACLE", 409, "blueprint spec authority is invalid")
    normalized = deepcopy(source_spec)
    endpoint_spec = normalized.get("endpoint")
    if not isinstance(endpoint_spec, dict) or not isinstance(endpoint_spec.get("name"), str):
        raise BrainError("COMPLEX_CREATE_ORACLE", 400, "blueprint endpoint is invalid")
    endpoint_spec["name"] = endpoint
    return canonical_sha256(normalized)


def assess_complex_create_after_close(
    spec: ComplexCreateQualificationSpec,
    journeys: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess blind observations after Brain and its model worker are closed."""

    denominator = spec.profile.denominator_map()
    stages = _load_blueprint_stages(spec)
    if len(journeys) != denominator["journeys"]:
        raise BrainError("COMPLEX_CREATE_ORACLE", 409, "journey denominator differs")
    initial: list[dict[str, Any]] = []
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    seen_turn_ids: set[str] = set()
    for target, journey in zip(spec.targets, journeys, strict=True):
        records = journey.get("turns") if isinstance(journey, Mapping) else None
        if (
            journey.get("case_id") != target.case_id
            or not isinstance(records, list)
            or len(records) != 4
            or any(not isinstance(record, Mapping) for record in records)
            or [record.get("turn") for record in records] != [1, 2, 3, 4]
        ):
            raise BrainError("COMPLEX_CREATE_ORACLE", 409, "journey roster differs")
        expected_generation = -1
        for record in records:
            turn = record["turn"]
            terminal = record.get("terminal")
            counts = record.get("event_counts")
            turn_id = record.get("turn_id")
            if (
                not isinstance(terminal, Mapping)
                or not isinstance(counts, Mapping)
                or set(counts) != {"inference", "compile", "repair", "terminal"}
                or any(type(value) is not int or value < 0 for value in counts.values())
                or not isinstance(turn_id, str)
                or not turn_id
                or turn_id in seen_turn_ids
                or not isinstance(record.get("request_sha256"), str)
                or _HASH_RE.fullmatch(record["request_sha256"]) is None
                or not isinstance(record.get("dialogue_binding_sha256"), str)
                or _HASH_RE.fullmatch(record["dialogue_binding_sha256"]) is None
            ):
                raise BrainError("COMPLEX_CREATE_ORACLE", 409, "journey record differs")
            seen_turn_ids.add(turn_id)
            if turn == 1:
                clarification_targets = _clarification_gap_targets(
                    record.get("clarification_proof"),
                    turn_id=record.get("turn_id"),
                    expected_binding_sha256=record.get("dialogue_binding_sha256"),
                )
                expected_initial_target = spec.profile.initial_gap_map()[target.case_id]
                passed = (
                    terminal.get("outcome") == "needs_clarification"
                    and counts == {"inference": 0, "compile": 0, "repair": 0, "terminal": 1}
                    and record.get("qualification_proof") is None
                    and clarification_targets == {expected_initial_target}
                )
                initial.append(
                    {
                        "case_id": target.case_id,
                        "turn": 1,
                        "pass": passed,
                        "expected_gap_target": expected_initial_target,
                        "observed_gap_targets": sorted(clarification_targets or ()),
                    }
                )
                continue
            stage_id = f"{target.scenario_id}:T{turn}"
            stage = stages.pop(stage_id, None)
            if stage is None or stage.get("status") not in {"ready", "needs_clarification"}:
                raise BrainError("COMPLEX_CREATE_ORACLE", 409, "blueprint stage differs")
            if stage["status"] == "ready":
                expected_generation += 1
                expected_spec_sha256 = _expected_spec_sha256(stage, endpoint=target.endpoint)
                proof = record.get("qualification_proof")
                passed = (
                    terminal.get("outcome") == "proposed"
                    and terminal.get("generation_strategy") == "model_create_plan_v2"
                    and terminal.get("compile_status") == "ok"
                    and terminal.get("compile_attempts") == 1
                    and counts == {"inference": 1, "compile": 1, "repair": 0, "terminal": 1}
                    and _typed_create_proof_matches(
                        proof,
                        record=record,
                        expected_spec_sha256=expected_spec_sha256,
                        expected_generation=expected_generation,
                    )
                )
                ready.append(
                    {
                        "case_id": target.case_id,
                        "stage_id": stage_id,
                        "pass": passed,
                        "expected_spec_sha256": expected_spec_sha256,
                        "observed_spec_sha256": (
                            proof.get("spec_sha256") if isinstance(proof, dict) else None
                        ),
                    }
                )
            else:
                missing = stage.get("missing")
                if not isinstance(missing, list) or not missing:
                    raise BrainError("COMPLEX_CREATE_ORACLE", 409, "blocked blueprint is invalid")
                expected_targets = {
                    normalized
                    for item in missing
                    if isinstance(item, Mapping)
                    and (normalized := _normalized_gap_key(item.get("slot"))) is not None
                }
                clarification_targets = _clarification_gap_targets(
                    record.get("clarification_proof"),
                    turn_id=record.get("turn_id"),
                    expected_binding_sha256=record.get("dialogue_binding_sha256"),
                )
                passed = (
                    terminal.get("outcome") == "needs_clarification"
                    and counts == {"inference": 0, "compile": 0, "repair": 0, "terminal": 1}
                    and record.get("qualification_proof") is None
                    and bool(expected_targets)
                    and clarification_targets is not None
                    and bool(clarification_targets)
                    and clarification_targets <= expected_targets
                )
                blocked.append(
                    {
                        "case_id": target.case_id,
                        "stage_id": stage_id,
                        "pass": passed,
                        "expected_missing_slots": [item.get("slot") for item in missing],
                        "observed_gap_targets": sorted(clarification_targets or ()),
                        "observed_clarification_sha256": record.get("clarification_sha256"),
                    }
                )
    if (
        stages
        or len(initial) != denominator["initial_ask_stages"]
        or len(ready) != denominator["expected_ready"]
        or len(blocked) != denominator["expected_blocked"]
    ):
        raise BrainError("COMPLEX_CREATE_ORACLE", 409, "assessment denominator differs")
    return {
        "initial_ask": {
            "total": denominator["initial_ask_stages"],
            "passed": sum(item["pass"] is True for item in initial),
            "stages": initial,
        },
        "ready": {
            "total": denominator["expected_ready"],
            "passed": sum(item["pass"] is True for item in ready),
            "stages": ready,
        },
        "authority_blocked": {
            "total": denominator["expected_blocked"],
            "safely_blocked": sum(item["pass"] is True for item in blocked),
            "stages": blocked,
        },
    }


def run_complex_create_qualification(
    *,
    config_path: Path,
    prompt_path: Path = PROMPT_PATH,
    plan_path: Path = PLAN_PATH,
    output_path: Path,
    authorize_local_model_execution: bool,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run 10x4 prompts, close Brain, and only then load blueprint oracles."""

    if authorize_local_model_execution is not True:
        raise BrainError(
            "COMPLEX_CREATE_NOT_AUTHORIZED", 403, "local model execution requires authorization"
        )
    output = hard._prepare_output(Path(output_path))  # noqa: SLF001
    spec = load_complex_create_qualification(prompt_path=prompt_path, plan_path=plan_path)
    requested_config = Path(config_path)
    if requested_config != spec.config_path:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "Brain config path differs")
    config_raw = hard._safe_regular_bytes(requested_config, label="Brain config")  # noqa: SLF001
    if _sha256(config_raw) != spec.config_sha256:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "Brain config hash differs")
    config: BrainConfig = parse_brain_config_bytes(config_raw)
    _validate_complex_config(config, spec)
    model1_before = capture_model1_guard()
    tenant_before = capture_tenant_guard(
        root=spec.tenant_root,
        tenant_alias=spec.tenant_alias,
        tenant_id=spec.tenant_id,
        target_path=spec.targets[0].relative_path,
    )
    if tenant_before["commit"] != spec.tenant_head or tenant_before["tree"] != spec.tenant_tree:
        raise BrainError("COMPLEX_CREATE_INVALID", 409, "tenant Git identity differs")
    started_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    service: MetisBrainService | None = None
    journeys: list[dict[str, Any]] = []
    health_before: dict[str, Any] = {}
    health_after: dict[str, Any] = {}
    suite_error: BaseException | None = None
    suite_error_phase = "startup"
    close_error: BaseException | None = None
    try:
        service = MetisBrainService(config)
        service.start_background()
        client = hard.HeadlessBrainClient(
            service.address[0],
            service.address[1],
            bootstrap_token=hard._bootstrap_token(service),  # noqa: SLF001
            client_id=CLIENT_ID,
            capabilities=CLIENT_CAPABILITIES,
        )
        health_before = client.health()
        suite_error_phase = "health_before"
        typed_create_identity = _validate_typed_create_health(
            health_before,
            expected=spec.runtime_identity["typed_create"],
        )
        compiler_pin = getattr(service.app.compiler, "pin_identity", None)
        if not isinstance(compiler_pin, Mapping):
            raise BrainError("COMPLEX_CREATE_RUNTIME", 503, "compiler pin is unavailable")
        identity = hard._validate_qualified_health(  # noqa: SLF001
            health_before,
            expected_identity={
                key: deepcopy(value)
                for key, value in spec.runtime_identity.items()
                if key != "typed_create"
            },
            compiler_pin=compiler_pin,
        )
        for index, (journey, target) in enumerate(
            zip(
                _parse_prompts(spec.prompt, profile=spec.profile),
                spec.targets,
                strict=True,
            ),
            start=1,
        ):
            suite_error_phase = "journey"
            journeys.append(
                _run_journey(
                    service=service,
                    client=client,
                    spec=spec,
                    journey=journey,
                    target=target,
                )
            )
            if progress is not None:
                progress(
                    {
                        "phase": "journey",
                        "index": index,
                        "total": spec.profile.denominator_map()["journeys"],
                    }
                )
        health_after = client.health()
        suite_error_phase = "health_after"
        if (
            _validate_typed_create_health(
                health_after,
                expected=spec.runtime_identity["typed_create"],
            )
            != typed_create_identity
        ):
            raise BrainError("COMPLEX_CREATE_DRIFT", 409, "typed CREATE identity changed")
        if (
            hard._validate_qualified_health(  # noqa: SLF001
                health_after,
                expected_identity={
                    key: deepcopy(value)
                    for key, value in spec.runtime_identity.items()
                    if key != "typed_create"
                },
                compiler_pin=compiler_pin,
            )
            != identity
        ):
            raise BrainError("COMPLEX_CREATE_DRIFT", 409, "Brain identity changed")
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
            target_path=spec.targets[0].relative_path,
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
    denominator = spec.profile.denominator_map()
    complete = (
        len(journeys) == denominator["journeys"]
        and sum(len(item["turns"]) for item in journeys) == denominator["operator_messages"]
    )
    guards_clean = (
        guard_error is None and tenant_after == tenant_before and model1_after == model1_before
    )
    assessment: dict[str, Any] | None = None
    if complete and suite_error is None and close_error is None and guards_clean:
        try:
            # The model worker and all sessions are erased before this first blueprint read.
            assessment = assess_complex_create_after_close(spec, journeys)
        except BaseException as error:
            if suite_error is None:
                suite_error = error
                suite_error_phase = "oracle"
    terminal_error: BaseException | None
    terminal_phase: str
    if tenant_after is not None and tenant_after != tenant_before:
        terminal_error = BrainError(
            "COMPLEX_CREATE_DRIFT", 409, "tenant changed during qualification"
        )
        terminal_phase = "tenant_guard"
    elif model1_after is not None and model1_after != model1_before:
        terminal_error = BrainError(
            "COMPLEX_CREATE_DRIFT", 409, "Model 1 tree changed during qualification"
        )
        terminal_phase = "model_guard"
    elif guard_error is not None:
        terminal_error = guard_error
        terminal_phase = guard_error_phase or "guard"
    elif suite_error is not None:
        terminal_error = suite_error
        terminal_phase = suite_error_phase
    elif close_error is not None:
        terminal_error = close_error
        terminal_phase = "close"
    else:
        terminal_error = None
        terminal_phase = "complete"
    terminal_code = (
        terminal_error.code
        if isinstance(terminal_error, BrainError)
        else type(terminal_error).__name__
        if terminal_error is not None
        else None
    )
    green = (
        complete
        and terminal_error is None
        and assessment is not None
        and assessment["initial_ask"]["passed"] == denominator["initial_ask_stages"]
        and assessment["ready"]["passed"] == denominator["expected_ready"]
        and assessment["authority_blocked"]["safely_blocked"] == denominator["expected_blocked"]
    )
    receipt_target = (
        output
        if complete
        else output.with_name(f"{output.stem}.incomplete-{uuid.uuid4().hex}.json")
    )
    body = {
        "schema_version": 1,
        "qualification_id": spec.profile.qualification_id,
        "profile_id": spec.profile.profile_id,
        "status": "MEASURED" if complete else "INCOMPLETE",
        "measurement_status": "COMPLETE" if complete else "PARTIAL",
        "receipt_path": str(receipt_target),
        "started_at": started_at,
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
        "identity": {
            "prompt_sha256": spec.prompt_sha256,
            "plan_sha256": spec.plan_sha256,
            "config_sha256": spec.config_sha256,
            "health_before_sha256": (canonical_sha256(health_before) if health_before else None),
            "health_after_sha256": canonical_sha256(health_after) if health_after else None,
            "tenant_guard_sha256": canonical_sha256(tenant_before),
            "model1_guard_sha256": canonical_sha256(model1_before),
            "tenant_after_sha256": (
                canonical_sha256(tenant_after) if tenant_after is not None else None
            ),
            "model1_after_sha256": (
                canonical_sha256(model1_after) if model1_after is not None else None
            ),
        },
        "boundary": {
            "transport": "numeric_loopback_http",
            "blueprints_loaded": assessment is not None,
            "blueprint_load_phase": "after_service_close" if assessment is not None else None,
            "apply_capability": False,
            "apply_called": False,
            "tenant_modified": (
                tenant_before != tenant_after if tenant_after is not None else None
            ),
            "model1_modified": (
                model1_before != model1_after if model1_after is not None else None
            ),
        },
        "denominator": denominator,
        "completed": {
            "journeys": len(journeys),
            "operator_messages": sum(len(item.get("turns", [])) for item in journeys),
        },
        "assessment": assessment,
        "terminal_gate": {
            "status": "FAILED" if terminal_error is not None else "PASSED",
            "phase": terminal_phase,
            "code": terminal_code,
        },
        "qualification_green": green,
        "journeys": journeys,
    }
    receipt = {**body, "receipt_sha256": canonical_sha256(body)}
    hard._write_receipt(receipt_target, receipt)  # noqa: SLF001
    return receipt


__all__ = [
    "EXPECTED_DENOMINATOR",
    "PLAN_PATH",
    "PLAN_SHA256",
    "PROMPT_PATH",
    "PROMPT_SHA256",
    "V4_EXPECTED_DENOMINATOR",
    "V4_PLAN_PATH",
    "V4_PLAN_SHA256",
    "V4_PROMPT_PATH",
    "V4_PROMPT_SHA256",
    "ComplexCreateProfile",
    "ComplexCreateQualificationSpec",
    "assess_complex_create_after_close",
    "load_complex_create_qualification",
    "run_complex_create_qualification",
]
