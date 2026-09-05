"""Prompt-only stage authority and hidden-oracle fixture for CREATE v3.

The tracked artifact loaded here is a qualification fixture, not production
tenant authority.  It is derived only from the operator messages in the frozen
zero-generation prompt corpus.  Endpoint source, prior endpoint templates,
tenant data and compiler output are outside this contract.

The model projection is intentionally one-way: it contains the instruction,
requirement labels and a bounded candidate roster, but never the selected
handles or any oracle assertion.  The hidden oracle is joined by a digest only
after inference.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREATE_STAGE_AUTHORITY_PATH = (
    PROJECT_ROOT / "examples/metis-brain-create-stage-authority.play-prod-v3.json"
)
CREATE_STAGE_AUTHORITY_CONTRACT = "metis-brain-create-stage-authority/v3"
CREATE_STAGE_MODEL_PROJECTION_CONTRACT = "metis-brain-create-stage-projection/v3"

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,255}:T[234]$")
_QUALIFIED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,95})*$")
_CANDIDATE_KINDS = frozenset(
    {
        "attribute",
        "block_roster",
        "cardinality",
        "catalog",
        "context",
        "fallback",
        "fetch_roster",
        "input",
        "instance_roster",
        "metadata",
        "order",
        "output",
        "pagination",
        "parameter",
        "pipeline",
        "presentation",
        "route_roster",
        "temporal_window",
    }
)
_MODEL_FORBIDDEN_KEYS = frozenset(
    {
        "expected",
        "golden",
        "oracle",
        "selected",
        "source",
        "source_path",
        "template",
    }
)
_TOP_KEYS = frozenset(
    {
        "schema_version",
        "contract_id",
        "provenance",
        "authority_set_sha256",
        "oracle_set_sha256",
        "authority_stages",
        "oracle_stages",
    }
)
_PROVENANCE_KEYS = frozenset(
    {
        "derivation",
        "prompt_corpus_path",
        "prompt_scope",
        "prompt_scope_sha256",
        "endpoint_source_used",
        "tenant_used",
        "compiler_used",
    }
)
_AUTHORITY_KEYS = frozenset(
    {
        "stage_id",
        "endpoint_qualified",
        "turn",
        "generation",
        "parent_stage_id",
        "instructions",
        "instruction_sha256",
        "requirements",
        "candidates",
        "authority_sha256",
    }
)
_ORACLE_KEYS = frozenset(
    {
        "stage_id",
        "authority_sha256",
        "selected_candidate_handles",
        "exact_delta",
        "cumulative_assertions",
        "preserve_assertions",
        "oracle_sha256",
    }
)


class CreateStageAuthorityError(ValueError):
    """One fail-closed error in the tracked prompt-only qualification fixture."""


@dataclass(frozen=True, slots=True)
class CreateStageAuthority:
    stage_id: str
    endpoint_qualified: str
    turn: int
    generation: int
    parent_stage_id: str | None
    instructions: str
    instruction_sha256: str
    requirements: tuple[dict[str, Any], ...]
    candidates: tuple[dict[str, Any], ...]
    authority_sha256: str


@dataclass(frozen=True, slots=True)
class CreateStageOracle:
    stage_id: str
    authority_sha256: str
    selected_candidate_handles: tuple[int, ...]
    exact_delta: dict[str, Any]
    cumulative_assertions: tuple[str, ...]
    preserve_assertions: tuple[str, ...]
    oracle_sha256: str


@dataclass(frozen=True, slots=True)
class CreateStageAuthorityBundle:
    provenance: dict[str, Any]
    authorities: tuple[CreateStageAuthority, ...]
    oracles: tuple[CreateStageOracle, ...]
    authority_set_sha256: str
    oracle_set_sha256: str

    def authority(self, stage_id: str) -> CreateStageAuthority:
        for authority in self.authorities:
            if authority.stage_id == stage_id:
                return authority
        raise CreateStageAuthorityError("unknown CREATE stage authority")

    def oracle(self, stage_id: str) -> CreateStageOracle:
        for oracle in self.oracles:
            if oracle.stage_id == stage_id:
                return oracle
        raise CreateStageAuthorityError("unknown CREATE stage oracle")


def _fail(message: str) -> NoReturn:
    raise CreateStageAuthorityError(message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise CreateStageAuthorityError("fixture contains non-canonical JSON") from error


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _array(value: Any, *, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail(f"{label} must be an array")
    return value


def _text(value: Any, *, label: str, limit: int = 2048) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > limit
        or any(ord(character) < 32 for character in value)
    ):
        _fail(f"{label} is invalid")
    return value


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        _fail(f"{label} is invalid")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], *, label: str) -> None:
    if set(value) != expected:
        _fail(f"{label} has an invalid field roster")


def _requirement(value: Any) -> dict[str, Any]:
    item = _mapping(value, label="requirement")
    if set(item) != {"handle", "label"}:
        _fail("requirement has an invalid field roster")
    handle = item.get("handle")
    if isinstance(handle, bool) or not isinstance(handle, int) or not 0 <= handle <= 63:
        _fail("requirement handle is invalid")
    return {
        "handle": handle,
        "label": _text(item.get("label"), label="requirement label", limit=160),
    }


def _candidate(value: Any, requirement_handles: frozenset[int]) -> dict[str, Any]:
    item = _mapping(value, label="candidate")
    if set(item) != {"handle", "kind", "label", "requirement_handles"}:
        _fail("candidate has an invalid field roster")
    handle = item.get("handle")
    if isinstance(handle, bool) or not isinstance(handle, int) or not 0 <= handle <= 255:
        _fail("candidate handle is invalid")
    kind = item.get("kind")
    if kind not in _CANDIDATE_KINDS:
        _fail("candidate kind is invalid")
    refs = tuple(_array(item.get("requirement_handles"), label="candidate requirement handles"))
    if not refs or len(refs) > 8 or len(set(refs)) != len(refs):
        _fail("candidate requirement handles are invalid")
    if any(
        isinstance(ref, bool) or not isinstance(ref, int) or ref not in requirement_handles
        for ref in refs
    ):
        _fail("candidate references an unknown requirement")
    return {
        "handle": handle,
        "kind": kind,
        "label": _text(item.get("label"), label="candidate label", limit=200),
        "requirement_handles": list(refs),
    }


def _strings(value: Any, *, label: str, maximum: int) -> tuple[str, ...]:
    items = tuple(_array(value, label=label))
    if not items or len(items) > maximum:
        _fail(f"{label} has an invalid item count")
    output = tuple(_text(item, label=label, limit=512) for item in items)
    if len(set(output)) != len(output):
        _fail(f"{label} contains duplicates")
    return output


def _assert_model_safe(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or key.casefold() in _MODEL_FORBIDDEN_KEYS:
                _fail("model projection contains a hidden-authority key")
            _assert_model_safe(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            _assert_model_safe(nested)
    elif value is None or type(value) in {str, int, float, bool}:
        return
    else:
        _fail("model projection is not strict JSON")


def _load_authority(value: Any) -> tuple[CreateStageAuthority, dict[str, Any]]:
    item = _mapping(value, label="authority stage")
    _exact_keys(item, _AUTHORITY_KEYS, label="authority stage")
    stage_id = _text(item.get("stage_id"), label="stage id", limit=260)
    if _STAGE_RE.fullmatch(stage_id) is None:
        _fail("stage id is invalid")
    endpoint = _text(item.get("endpoint_qualified"), label="endpoint", limit=256)
    if _QUALIFIED_RE.fullmatch(endpoint) is None or not stage_id.startswith(endpoint + ":"):
        _fail("stage endpoint identity is invalid")
    turn = item.get("turn")
    generation = item.get("generation")
    if isinstance(turn, bool) or turn not in {2, 3, 4} or generation != turn - 2:
        _fail("stage turn/generation is invalid")
    parent = item.get("parent_stage_id")
    expected_parent = None if turn == 2 else f"{endpoint}:T{turn - 1}"
    if parent != expected_parent:
        _fail("stage parent is invalid")
    instructions = _text(item.get("instructions"), label="stage instructions", limit=4096)
    instruction_sha256 = _hash(item.get("instruction_sha256"), label="instruction hash")
    if instruction_sha256 != _sha256(instructions):
        _fail("instruction hash differs")
    requirements = tuple(
        _requirement(entry) for entry in _array(item.get("requirements"), label="requirements")
    )
    if not 1 <= len(requirements) <= 16:
        _fail("requirement roster is outside bounds")
    requirement_handles = tuple(entry["handle"] for entry in requirements)
    if len(set(requirement_handles)) != len(requirement_handles):
        _fail("requirement handles are duplicated")
    candidates = tuple(
        _candidate(entry, frozenset(requirement_handles))
        for entry in _array(item.get("candidates"), label="candidates")
    )
    if not 3 <= len(candidates) <= 24:
        _fail("candidate roster is outside bounds")
    candidate_handles = tuple(entry["handle"] for entry in candidates)
    if len(set(candidate_handles)) != len(candidate_handles):
        _fail("candidate handles are duplicated")
    supplied_hash = _hash(item.get("authority_sha256"), label="authority hash")
    canonical = {key: item[key] for key in item if key != "authority_sha256"}
    if supplied_hash != _sha256(canonical):
        _fail("authority stage hash differs")
    authority = CreateStageAuthority(
        stage_id=stage_id,
        endpoint_qualified=endpoint,
        turn=turn,
        generation=generation,
        parent_stage_id=parent,
        instructions=instructions,
        instruction_sha256=instruction_sha256,
        requirements=requirements,
        candidates=candidates,
        authority_sha256=supplied_hash,
    )
    return authority, dict(item)


def _strict_json(value: Any, *, depth: int = 0, count: list[int] | None = None) -> Any:
    if count is None:
        count = [0]
    count[0] += 1
    if depth > 24 or count[0] > 4096:
        _fail("oracle delta exceeds its structural bound")
    if isinstance(value, Mapping):
        if not value:
            _fail("oracle delta contains an empty object")
        return {
            _text(key, label="oracle delta key", limit=96): _strict_json(
                nested, depth=depth + 1, count=count
            )
            for key, nested in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            _fail("oracle delta contains an empty array")
        return [_strict_json(nested, depth=depth + 1, count=count) for nested in value]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    _fail("oracle delta is not strict JSON")


def _load_oracle(
    value: Any, authority: CreateStageAuthority
) -> tuple[CreateStageOracle, dict[str, Any]]:
    item = _mapping(value, label="oracle stage")
    _exact_keys(item, _ORACLE_KEYS, label="oracle stage")
    if item.get("stage_id") != authority.stage_id:
        _fail("oracle stage identity differs")
    authority_sha256 = _hash(item.get("authority_sha256"), label="oracle authority hash")
    if authority_sha256 != authority.authority_sha256:
        _fail("oracle authority binding differs")
    selected = tuple(
        _array(item.get("selected_candidate_handles"), label="selected candidate handles")
    )
    if not selected or len(set(selected)) != len(selected):
        _fail("selected candidate handle roster is invalid")
    candidate_handles = {candidate["handle"] for candidate in authority.candidates}
    if any(
        isinstance(handle, bool) or not isinstance(handle, int) or handle not in candidate_handles
        for handle in selected
    ):
        _fail("oracle selects an unknown candidate")
    if len(candidate_handles - set(selected)) < 2:
        _fail("stage has fewer than two measurable distractors")
    delta = _strict_json(item.get("exact_delta"))
    if not isinstance(delta, dict) or set(delta) != {"mode", "operations"}:
        _fail("exact delta has an invalid field roster")
    if delta.get("mode") != "create":
        _fail("exact delta mode is invalid")
    operations = delta.get("operations")
    if not isinstance(operations, list) or not operations:
        _fail("exact delta operations are invalid")
    cumulative = _strings(
        item.get("cumulative_assertions"), label="cumulative assertions", maximum=32
    )
    preserve = _strings(item.get("preserve_assertions"), label="preserve assertions", maximum=24)
    supplied_hash = _hash(item.get("oracle_sha256"), label="oracle hash")
    canonical = {key: item[key] for key in item if key != "oracle_sha256"}
    if supplied_hash != _sha256(canonical):
        _fail("oracle stage hash differs")
    oracle = CreateStageOracle(
        stage_id=authority.stage_id,
        authority_sha256=authority_sha256,
        selected_candidate_handles=selected,
        exact_delta=delta,
        cumulative_assertions=cumulative,
        preserve_assertions=preserve,
        oracle_sha256=supplied_hash,
    )
    return oracle, dict(item)


def load_create_stage_authority(
    path: Path = CREATE_STAGE_AUTHORITY_PATH,
) -> CreateStageAuthorityBundle:
    """Load and fully validate the tracked 10 x 3 prompt-only stage fixture."""

    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CreateStageAuthorityError("CREATE stage fixture is unavailable or invalid") from error
    root = _mapping(payload, label="fixture")
    _exact_keys(root, _TOP_KEYS, label="fixture")
    if (
        root.get("schema_version") != 3
        or root.get("contract_id") != CREATE_STAGE_AUTHORITY_CONTRACT
    ):
        _fail("fixture contract is invalid")
    provenance = _mapping(root.get("provenance"), label="provenance")
    _exact_keys(provenance, _PROVENANCE_KEYS, label="provenance")
    if (
        provenance.get("derivation") != "operator-prompts-only"
        or provenance.get("prompt_corpus_path")
        != "examples/metis-brain-hard-prompts.play-prod-v2.json"
        or provenance.get("prompt_scope")
        != "zero_generation_scenarios[].{endpoint_qualified,turns[].{turn,user_message}}"
        or provenance.get("endpoint_source_used") is not False
        or provenance.get("tenant_used") is not False
        or provenance.get("compiler_used") is not False
    ):
        _fail("fixture provenance is invalid")
    _hash(provenance.get("prompt_scope_sha256"), label="prompt scope hash")
    authority_values = tuple(_array(root.get("authority_stages"), label="authority stages"))
    oracle_values = tuple(_array(root.get("oracle_stages"), label="oracle stages"))
    if len(authority_values) != 30 or len(oracle_values) != 30:
        _fail("fixture must contain exactly 30 authority/oracle stages")
    loaded_authorities = tuple(_load_authority(value) for value in authority_values)
    authorities = tuple(item[0] for item in loaded_authorities)
    authority_dicts = tuple(item[1] for item in loaded_authorities)
    stage_ids = tuple(authority.stage_id for authority in authorities)
    if len(set(stage_ids)) != 30:
        _fail("authority stage identities are duplicated")
    endpoints = {authority.endpoint_qualified for authority in authorities}
    if len(endpoints) != 10:
        _fail("fixture must contain exactly ten endpoint journeys")
    for endpoint in endpoints:
        if {
            authority.turn for authority in authorities if authority.endpoint_qualified == endpoint
        } != {
            2,
            3,
            4,
        }:
            _fail("each endpoint journey must contain T2, T3 and T4")
    authority_set_sha256 = _hash(root.get("authority_set_sha256"), label="authority set hash")
    if authority_set_sha256 != _sha256(authority_dicts):
        _fail("authority set hash differs")
    authorities_by_id = {authority.stage_id: authority for authority in authorities}
    oracle_pairs: list[tuple[CreateStageOracle, dict[str, Any]]] = []
    for value in oracle_values:
        mapping = _mapping(value, label="oracle stage")
        stage_id = mapping.get("stage_id")
        authority = authorities_by_id.get(stage_id)
        if authority is None:
            _fail("oracle has no matching authority")
        oracle_pairs.append(_load_oracle(value, authority))
    oracles = tuple(pair[0] for pair in oracle_pairs)
    oracle_dicts = tuple(pair[1] for pair in oracle_pairs)
    if {oracle.stage_id for oracle in oracles} != set(stage_ids):
        _fail("oracle stage roster differs from authority roster")
    oracle_set_sha256 = _hash(root.get("oracle_set_sha256"), label="oracle set hash")
    if oracle_set_sha256 != _sha256(oracle_dicts):
        _fail("oracle set hash differs")
    return CreateStageAuthorityBundle(
        provenance=dict(provenance),
        authorities=authorities,
        oracles=oracles,
        authority_set_sha256=authority_set_sha256,
        oracle_set_sha256=oracle_set_sha256,
    )


def create_stage_model_payload(bundle: CreateStageAuthorityBundle, stage_id: str) -> dict[str, Any]:
    """Return the only model-visible projection for one qualification stage."""

    authority = bundle.authority(stage_id)
    payload = {
        "contract_id": CREATE_STAGE_MODEL_PROJECTION_CONTRACT,
        "stage_id": authority.stage_id,
        "generation": authority.generation,
        "instructions": authority.instructions,
        "requirements": [dict(requirement) for requirement in authority.requirements],
        "candidates": [dict(candidate) for candidate in authority.candidates],
        "projection_revision": authority.authority_sha256,
    }
    _assert_model_safe(payload)
    return payload


__all__ = [
    "CREATE_STAGE_AUTHORITY_CONTRACT",
    "CREATE_STAGE_AUTHORITY_PATH",
    "CREATE_STAGE_MODEL_PROJECTION_CONTRACT",
    "CreateStageAuthority",
    "CreateStageAuthorityBundle",
    "CreateStageAuthorityError",
    "CreateStageOracle",
    "create_stage_model_payload",
    "load_create_stage_authority",
]
