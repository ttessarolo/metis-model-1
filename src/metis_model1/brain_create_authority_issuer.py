"""Pure, fail-closed authority issuer for Metis Brain CREATE planning.

The issuer sits after deterministic adjudication and before Model 1.  It does
not infer intent, read a tenant, call a model, or render Metis.  Its only job is
to validate one complete server-owned snapshot and atomically turn the
admitted facts into opaque, session-scoped grants.

Only the projection returned by :class:`CreateAuthoritySurface` is suitable
for a model.  Typed fragments, clarification/policy payloads, exact evidence
and requirement-to-authority bindings remain in the private registry.
"""

from __future__ import annotations

import copy
import hmac
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from jsonschema import Draft202012Validator

from metis_model1.brain_create_builder import (
    CREATE_ENDPOINT_SPEC_CONTRACT,
    CREATE_ENDPOINT_SPEC_SCHEMA,
)
from metis_model1.brain_create_plan import HOST_REF_ROLES, OPERATION_KINDS
from metis_model1.brain_create_surface import (
    CreateAuthorityGrant,
    CreateAuthorityHistoryMessage,
    CreateAuthoritySurface,
    RequirementEvidence,
    create_authority_history_revision,
)
from metis_model1.brain_intent_ir import IntentCompileRequest, IntentIR
from metis_model1.brain_output_contract import OutputRequestSurface, parse_output_request
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

CREATE_AUTHORITY_ISSUER_CONTRACT = "metis-brain-create-authority-issuer/v1"
SAFE_REVIEWED_PROJECTION_CONTRACT = "metis-brain-create-safe-reviewed-projection/v1"
CAPABILITY_INVENTORY_CONTRACT = "metis-brain-create-capability-inventory/v1"
DEFAULT_POLICY_CONTRACT = "metis-brain-create-default-policy/v1"
CLARIFICATION_DECISIONS_CONTRACT = "metis-brain-create-clarification-decisions/v1"

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{32,96}$")
MAX_AUTHORITIES = 384
MAX_REQUIREMENTS = 64
MAX_DECISIONS = 32
MAX_FLASH_SPANS = 12
MAX_POLICY_ENTRIES = 32
MAX_GENERATION = 10_000
MIN_HMAC_KEY_BYTES = 32
MAX_HMAC_KEY_BYTES = 256

AMBIGUITY_KINDS = (
    "catalog",
    "semantic_choice",
    "result_count",
    "response_shape",
    "fallback",
    "structural_choice",
)
_AMBIGUITY_SET = frozenset(AMBIGUITY_KINDS)
_FLASH_AMBIGUITY_MAP = {
    "catalog": "catalog",
    "semantic": "semantic_choice",
    "format": "response_shape",
    "fallback": "fallback",
    "target": "structural_choice",
}
_DECISION_KINDS = _AMBIGUITY_SET
_FORBIDDEN_KEYS = frozenset(
    {
        "at",
        "code",
        "dsl",
        "endpoint_template",
        "endpoint_templates",
        "file",
        "file_path",
        "golden",
        "golden_endpoint",
        "metis",
        "metis_source",
        "path",
        "provenance",
        "raw",
        "raw_source",
        "reference_endpoint",
        "snippet",
        "source",
        "source_path",
        "source_text",
        "template",
        "template_ref",
    }
)
_SEMANTIC_ROLES = frozenset({"catalog", "field", "catalog_value"})
_ROOT_FRAGMENT_TYPES = frozenset({"identifier", "qualifiedIdentifier"})
_BUILDER_FRAGMENT_TYPES = frozenset(CREATE_ENDPOINT_SPEC_SCHEMA["$defs"])
_BUILDER_SCHEMA_SHA256 = bytes_sha256(canonical_json(CREATE_ENDPOINT_SPEC_SCHEMA))


class CreateAuthorityIssuerError(ValueError):
    """Internal validation failure converted to a closed ``Unsupported`` result."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TypedFragment:
    """One private value validated against a tracked builder schema fragment."""

    fragment_type: str
    value: Any


@dataclass(frozen=True, slots=True)
class AuthorityCandidate:
    """One adjudicated private authority candidate.

    ``requirement_keys`` is not shown to the model.  The private registry keeps
    this binding so the later plan-to-builder bridge can reject a semantically
    role-compatible ref used for the wrong requirement.
    """

    key: str
    roles: Sequence[str]
    label: str
    fragment: TypedFragment
    requirement_keys: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class ReviewedSemanticAuthority:
    authority: AuthorityCandidate
    state: str
    domain: Literal["finite", "open", "none"]
    resolved: bool


@dataclass(frozen=True, slots=True)
class SafeReviewedProjection:
    """Already-pruned semantic authority; never the retriever's raw context."""

    context_revision: str
    semantic_revision: str
    toolchain_binding: str
    projection_revision: str
    status: Literal["resolved", "clarify", "unsupported"]
    authorities: Sequence[ReviewedSemanticAuthority]
    ambiguities: Sequence[str] = ()
    unresolved: Sequence[str] = ()
    contract_id: str = SAFE_REVIEWED_PROJECTION_CONTRACT


@dataclass(frozen=True, slots=True)
class CapabilityInventory:
    """Code/compiler-derived structural inventory for the exact toolchain."""

    toolchain_binding: str
    inventory_revision: str
    operation_kinds: Sequence[str]
    authorities: Sequence[AuthorityCandidate]
    builder_contract: str = CREATE_ENDPOINT_SPEC_CONTRACT
    builder_schema_sha256: str = _BUILDER_SCHEMA_SHA256
    contract_id: str = CAPABILITY_INVENTORY_CONTRACT


@dataclass(frozen=True, slots=True)
class TypedDecision:
    """One TurnStore-reconstructed clarification decision, never client input."""

    key: str
    kind: str
    value: Any
    context_revision: str
    semantic_revision: str
    decision_sha256: str


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """One explicit code-pinned default used only when operator prose is silent."""

    key: str
    kind: str
    value: Any


@dataclass(frozen=True, slots=True)
class DefaultPolicy:
    toolchain_binding: str
    policy_revision: str
    entries: Sequence[PolicyDecision]
    contract_id: str = DEFAULT_POLICY_CONTRACT


@dataclass(frozen=True, slots=True)
class FlashExactSpan:
    """Exact UTF-8 location of one Flash concept in the current operator turn."""

    concept_index: int
    message_ordinal: int
    start_utf8: int
    end_utf8: int


@dataclass(frozen=True, slots=True)
class RequirementClaim:
    """Adjudicated requirement with exactly one private evidence origin."""

    key: str
    label: str
    allowed_kinds: Sequence[str]
    authority_keys: Sequence[str]
    origin: Literal["operator", "flash", "clarification", "policy"]
    message_ordinal: int | None = None
    start_utf8: int | None = None
    end_utf8: int | None = None
    evidence_key: str | None = None


@dataclass(frozen=True, slots=True)
class RootAuthority:
    key: str
    label: str
    fragment: TypedFragment


@dataclass(frozen=True, slots=True)
class IssuanceSnapshot:
    """Complete immutable input reconstructed by trusted Brain host code."""

    session_id: str
    history: Sequence[CreateAuthorityHistoryMessage]
    history_revision: str
    clarification_decisions: Sequence[TypedDecision]
    clarification_revision: str
    flash_intent: IntentIR | None
    flash_spans: Sequence[FlashExactSpan]
    semantic_projection: SafeReviewedProjection
    output_request: OutputRequestSurface
    capabilities: CapabilityInventory
    default_policy: DefaultPolicy
    requirements: Sequence[RequirementClaim]
    target: RootAuthority
    basis: RootAuthority | None
    generation: int
    context_revision: str
    semantic_revision: str
    toolchain_binding: str
    ambiguities: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class NeedsClarification:
    kinds: tuple[str, ...]
    code: str = "CREATE_AUTHORITY_NEEDS_CLARIFICATION"


@dataclass(frozen=True, slots=True)
class Unsupported:
    code: str
    reason: str


class PrivateAuthorityRegistry:
    """Private key/ref/binding index over one immutable authority surface."""

    __slots__ = ("_key_to_ref", "_requirement_authorities", "_surface")

    def __init__(
        self,
        *,
        surface: CreateAuthoritySurface,
        key_to_ref: Mapping[str, str],
        requirement_authorities: Mapping[str, Sequence[str]],
    ) -> None:
        self._surface = surface
        self._key_to_ref = MappingProxyType(dict(key_to_ref))
        self._requirement_authorities = MappingProxyType(
            {key: tuple(values) for key, values in requirement_authorities.items()}
        )

    @property
    def surface_revision(self) -> str:
        return self._surface.surface_revision

    def ref_for(self, key: str) -> str:
        try:
            return self._key_to_ref[key]
        except KeyError as error:
            raise BrainError(
                "CREATE_AUTHORITY_KEY_UNKNOWN", 502, "create authority key is unknown"
            ) from error

    def authority_refs_for_requirement(self, requirement_ref: str) -> tuple[str, ...]:
        try:
            return tuple(self._requirement_authorities[requirement_ref])
        except KeyError as error:
            raise BrainError(
                "CREATE_AUTHORITY_REQUIREMENT_UNKNOWN",
                502,
                "create requirement authority is unknown",
            ) from error

    def resolve(self, key: str, *, required_role: str) -> Any:
        return self._surface.resolve(
            self.ref_for(key),
            required_role=required_role,
            expected_surface_revision=self._surface.surface_revision,
        )


@dataclass(frozen=True, slots=True)
class Issued:
    surface: CreateAuthoritySurface
    context_revision: str
    semantic_revision: str
    toolchain_binding: str
    generation: int
    private_registry: PrivateAuthorityRegistry = field(repr=False)


IssueResult: TypeAlias = Issued | NeedsClarification | Unsupported


def _fail(code: str, message: str) -> None:
    raise CreateAuthorityIssuerError(code, message)


def _strict_hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        _fail("INVALID_REVISION", f"{label} is invalid")
    return value


def _key(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or KEY_RE.fullmatch(value) is None:
        _fail("INVALID_AUTHORITY", f"{label} is invalid")
    return value


def _strict_json_copy(value: Any, *, label: str) -> Any:
    _reject_unsafe_keys(value)
    try:
        return copy.deepcopy(__import__("json").loads(canonical_json(value)))
    except (BrainError, UnicodeError, ValueError, TypeError) as error:
        raise CreateAuthorityIssuerError("INVALID_AUTHORITY", f"{label} is invalid") from error


def _reject_unsafe_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            if not isinstance(raw_key, str):
                _fail("UNSAFE_AUTHORITY", "authority contains a non-string key")
            normalized = raw_key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                _fail("UNSAFE_AUTHORITY", "authority contains a forbidden private-source key")
            _reject_unsafe_keys(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            _reject_unsafe_keys(nested)


def _fragment_validator(fragment_type: str) -> Draft202012Validator:
    if fragment_type not in _BUILDER_FRAGMENT_TYPES:
        _fail("INVALID_FRAGMENT", "authority fragment type is not builder-owned")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{fragment_type}",
        "$defs": CREATE_ENDPOINT_SPEC_SCHEMA["$defs"],
    }
    return Draft202012Validator(schema)


def _validate_fragment(fragment: TypedFragment, *, root: bool = False) -> dict[str, Any]:
    if not isinstance(fragment, TypedFragment):
        _fail("INVALID_FRAGMENT", "authority fragment is not typed")
    if root and fragment.fragment_type not in _ROOT_FRAGMENT_TYPES:
        _fail("INVALID_FRAGMENT", "root authority must be a builder identifier")
    value = _strict_json_copy(fragment.value, label="authority fragment")
    errors = sorted(
        _fragment_validator(fragment.fragment_type).iter_errors(value),
        key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
    )
    if errors:
        _fail("INVALID_FRAGMENT", "authority fragment does not match its builder type")
    return {"fragment_kind": fragment.fragment_type, "fragment": value}


def _candidate_manifest(candidate: AuthorityCandidate) -> dict[str, Any]:
    return {
        "key": candidate.key,
        "roles": sorted(candidate.roles),
        "label": candidate.label,
        "fragment": {
            "fragment_type": candidate.fragment.fragment_type,
            "value": _strict_json_copy(candidate.fragment.value, label="authority fragment"),
        },
        "requirement_keys": sorted(candidate.requirement_keys),
    }


def safe_reviewed_projection_revision(
    projection: SafeReviewedProjection,
) -> str:
    manifest = {
        "contract_id": projection.contract_id,
        "context_revision": projection.context_revision,
        "semantic_revision": projection.semantic_revision,
        "toolchain_binding": projection.toolchain_binding,
        "status": projection.status,
        "authorities": [
            {
                "authority": _candidate_manifest(item.authority),
                "state": item.state,
                "domain": item.domain,
                "resolved": item.resolved,
            }
            for item in projection.authorities
        ],
        "ambiguities": list(projection.ambiguities),
        "unresolved": list(projection.unresolved),
    }
    return bytes_sha256(canonical_json(manifest))


def capability_inventory_revision(inventory: CapabilityInventory) -> str:
    manifest = {
        "contract_id": inventory.contract_id,
        "toolchain_binding": inventory.toolchain_binding,
        "builder_contract": inventory.builder_contract,
        "builder_schema_sha256": inventory.builder_schema_sha256,
        "operation_kinds": sorted(inventory.operation_kinds),
        "authorities": [_candidate_manifest(item) for item in inventory.authorities],
    }
    return bytes_sha256(canonical_json(manifest))


def default_policy_revision(policy: DefaultPolicy) -> str:
    manifest = {
        "contract_id": policy.contract_id,
        "toolchain_binding": policy.toolchain_binding,
        "entries": [
            {
                "key": entry.key,
                "kind": entry.kind,
                "value": _strict_json_copy(entry.value, label="policy value"),
            }
            for entry in policy.entries
        ],
    }
    return bytes_sha256(canonical_json(manifest))


def clarification_decisions_revision(decisions: Sequence[TypedDecision]) -> str:
    manifest = {
        "contract_id": CLARIFICATION_DECISIONS_CONTRACT,
        "decisions": [
            {
                "key": decision.key,
                "kind": decision.kind,
                "value": _strict_json_copy(decision.value, label="clarification value"),
                "context_revision": decision.context_revision,
                "semantic_revision": decision.semantic_revision,
                "decision_sha256": decision.decision_sha256,
            }
            for decision in decisions
        ],
    }
    return bytes_sha256(canonical_json(manifest))


def decision_sha256(
    *,
    key: str,
    kind: str,
    value: Any,
    context_revision: str,
    semantic_revision: str,
) -> str:
    """Return the exact digest TurnStore/adjudication must bind for one decision."""

    return bytes_sha256(
        canonical_json(
            {
                "key": key,
                "kind": kind,
                "value": _strict_json_copy(value, label="clarification value"),
                "context_revision": context_revision,
                "semantic_revision": semantic_revision,
            }
        )
    )


def _validate_candidate(candidate: AuthorityCandidate, *, semantic: bool) -> dict[str, Any]:
    if not isinstance(candidate, AuthorityCandidate):
        _fail("INVALID_AUTHORITY", "authority candidate is invalid")
    _key(candidate.key, label="authority key")
    if isinstance(candidate.roles, str) or not isinstance(candidate.roles, Collection):
        _fail("INVALID_AUTHORITY", "authority roles are invalid")
    roles = tuple(candidate.roles)
    if (
        not roles
        or any(not isinstance(role, str) for role in roles)
        or len(roles) != len(set(roles))
        or not set(roles).issubset(HOST_REF_ROLES)
        or "requirement" in roles
        or "target" in roles
        or "basis" in roles
    ):
        _fail("INVALID_AUTHORITY", "authority roles are invalid")
    if semantic:
        if len(roles) != 1 or roles[0] not in _SEMANTIC_ROLES:
            _fail("INVALID_SEMANTICS", "semantic authority role is invalid")
    elif set(roles) & _SEMANTIC_ROLES:
        _fail("INVALID_CAPABILITY", "semantic roles cannot come from toolchain capabilities")
    if not isinstance(candidate.label, str) or not candidate.label:
        _fail("INVALID_AUTHORITY", "authority label is invalid")
    requirement_keys = tuple(candidate.requirement_keys)
    if len(requirement_keys) != len(set(requirement_keys)) or any(
        KEY_RE.fullmatch(item) is None for item in requirement_keys
    ):
        _fail("INVALID_AUTHORITY", "authority requirement binding is invalid")
    return _validate_fragment(candidate.fragment)


def _validate_decision_value(
    kind: str,
    value: Any,
    *,
    authority_roles: Mapping[str, frozenset[str]],
) -> Any:
    copied = _strict_json_copy(value, label="decision value")
    if kind == "result_count":
        if (
            not isinstance(copied, dict)
            or set(copied) != {"mode", "value"}
            or copied["mode"] not in {"count", "page"}
            or type(copied["value"]) is not int
            or not 1 <= copied["value"] <= 10_000
        ):
            _fail("INVALID_DECISION", "result-count decision is invalid")
        return copied
    authority_keys = set(authority_roles)
    if (
        not isinstance(copied, dict)
        or set(copied) != {"authority_key"}
        or not isinstance(copied["authority_key"], str)
        or copied["authority_key"] not in authority_keys
    ):
        _fail("INVALID_DECISION", "clarification decision does not select issued authority")
    selected_roles = authority_roles[copied["authority_key"]]
    expected_roles = {
        "catalog": frozenset({"catalog"}),
        "semantic_choice": frozenset({"catalog", "field", "catalog_value"}),
        "response_shape": frozenset({"response_format"}),
        "fallback": frozenset({"fallback_slot", "block", "query", "result"}),
        "structural_choice": HOST_REF_ROLES
        - frozenset({"basis", "catalog", "catalog_value", "field", "requirement", "target"}),
    }[kind]
    if selected_roles.isdisjoint(expected_roles):
        _fail("INVALID_DECISION", "clarification decision selects an incompatible authority")
    return copied


def _utf8_span(
    history: Sequence[CreateAuthorityHistoryMessage],
    *,
    message_ordinal: Any,
    start_utf8: Any,
    end_utf8: Any,
) -> bytes:
    if (
        type(message_ordinal) is not int
        or not 0 <= message_ordinal < len(history)
        or type(start_utf8) is not int
        or type(end_utf8) is not int
    ):
        _fail("INVALID_EVIDENCE", "operator evidence coordinates are invalid")
    raw = history[message_ordinal].text.encode("utf-8")
    if not 0 <= start_utf8 < end_utf8 <= len(raw):
        _fail("INVALID_EVIDENCE", "operator evidence span is outside its message")
    span = raw[start_utf8:end_utf8]
    try:
        span.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CreateAuthorityIssuerError(
            "INVALID_EVIDENCE", "operator evidence splits a UTF-8 character"
        ) from error
    return span


def _hmac_ref(
    secret: bytes,
    *,
    session_id: str,
    namespace: str,
    identity: Mapping[str, Any],
) -> str:
    material = canonical_json(
        {
            "contract_id": CREATE_AUTHORITY_ISSUER_CONTRACT,
            "session_id": session_id,
            "namespace": namespace,
            "identity": identity,
        }
    )
    digest = hmac.new(secret, material, sha256).hexdigest()
    return f"hostref:{namespace}:{digest[:48]}"


def _ordered_ambiguities(values: Collection[str]) -> tuple[str, ...]:
    return tuple(kind for kind in AMBIGUITY_KINDS if kind in values)


class CreateAuthorityIssuer:
    """Validate and issue one complete authority snapshot atomically."""

    __slots__ = ("_secret",)

    def __init__(self, *, hmac_key: bytes) -> None:
        if (
            not isinstance(hmac_key, bytes)
            or not MIN_HMAC_KEY_BYTES <= len(hmac_key) <= MAX_HMAC_KEY_BYTES
        ):
            raise ValueError("CREATE authority HMAC key is invalid")
        self._secret = bytes(hmac_key)

    def issue(self, snapshot: IssuanceSnapshot) -> IssueResult:
        try:
            return self._issue(snapshot)
        except CreateAuthorityIssuerError as error:
            return Unsupported(code=error.code, reason=str(error))
        except Exception:  # noqa: BLE001 - the public issuer boundary must fail closed
            return Unsupported(
                code="INVALID_AUTHORITY_SNAPSHOT",
                reason="create authority snapshot failed closed",
            )

    def _issue(self, snapshot: IssuanceSnapshot) -> IssueResult:
        if not isinstance(snapshot, IssuanceSnapshot):
            _fail("INVALID_SNAPSHOT", "create authority snapshot is invalid")
        # Frozen dataclasses may still contain caller-owned lists/dicts.  Take
        # one defensive snapshot before validating revisions, preventing a
        # validate/use race with another orchestration thread.
        snapshot = copy.deepcopy(snapshot)
        if (
            not isinstance(snapshot.session_id, str)
            or SESSION_RE.fullmatch(snapshot.session_id) is None
        ):
            _fail("INVALID_SESSION", "create authority session is invalid")
        revisions = (
            (snapshot.history_revision, "history revision"),
            (snapshot.clarification_revision, "clarification revision"),
            (snapshot.context_revision, "context revision"),
            (snapshot.semantic_revision, "semantic revision"),
            (snapshot.toolchain_binding, "toolchain binding"),
        )
        for value, label in revisions:
            _strict_hash(value, label=label)
        computed_history = create_authority_history_revision(snapshot.history)
        if not hmac.compare_digest(computed_history, snapshot.history_revision):
            _fail("REVISION_DRIFT", "history revision differs")
        history = tuple(snapshot.history)
        if (
            type(snapshot.generation) is not int
            or not 0 <= snapshot.generation <= MAX_GENERATION
            or (snapshot.generation == 0) != (snapshot.basis is None)
        ):
            _fail("INVALID_LINEAGE", "create generation and basis are incompatible")

        target_payload = self._root_payload(snapshot.target, label="target")
        basis_payload = (
            self._root_payload(snapshot.basis, label="basis")
            if snapshot.basis is not None
            else None
        )
        if snapshot.basis is not None and snapshot.target.key == snapshot.basis.key:
            _fail("INVALID_LINEAGE", "target and basis keys must differ")

        semantic = snapshot.semantic_projection
        if not isinstance(semantic, SafeReviewedProjection):
            _fail("INVALID_SEMANTICS", "safe semantic projection is invalid")
        if semantic.contract_id != SAFE_REVIEWED_PROJECTION_CONTRACT:
            _fail("INVALID_SEMANTICS", "safe semantic projection contract differs")
        if (
            semantic.context_revision != snapshot.context_revision
            or semantic.semantic_revision != snapshot.semantic_revision
            or semantic.toolchain_binding != snapshot.toolchain_binding
        ):
            _fail("REVISION_DRIFT", "safe semantic projection binding differs")
        _strict_hash(semantic.projection_revision, label="semantic projection revision")
        if not hmac.compare_digest(
            safe_reviewed_projection_revision(semantic), semantic.projection_revision
        ):
            _fail("REVISION_DRIFT", "safe semantic projection revision differs")
        if semantic.status == "unsupported":
            return Unsupported("SEMANTIC_UNSUPPORTED", "semantic authority is unsupported")
        if semantic.status not in {"resolved", "clarify"}:
            _fail("INVALID_SEMANTICS", "semantic status is invalid")
        if semantic.unresolved:
            return Unsupported("SEMANTIC_UNRESOLVED", "semantic authority is unresolved")

        capabilities = snapshot.capabilities
        if not isinstance(capabilities, CapabilityInventory):
            _fail("INVALID_CAPABILITY", "capability inventory is invalid")
        if (
            capabilities.contract_id != CAPABILITY_INVENTORY_CONTRACT
            or capabilities.toolchain_binding != snapshot.toolchain_binding
            or capabilities.builder_contract != CREATE_ENDPOINT_SPEC_CONTRACT
            or capabilities.builder_schema_sha256 != _BUILDER_SCHEMA_SHA256
        ):
            _fail("TOOLCHAIN_DRIFT", "capability inventory toolchain binding differs")
        _strict_hash(capabilities.inventory_revision, label="capability inventory revision")
        if not hmac.compare_digest(
            capability_inventory_revision(capabilities), capabilities.inventory_revision
        ):
            _fail("REVISION_DRIFT", "capability inventory revision differs")
        operation_kinds = tuple(capabilities.operation_kinds)
        if (
            not operation_kinds
            or len(operation_kinds) != len(set(operation_kinds))
            or not set(operation_kinds).issubset(OPERATION_KINDS)
        ):
            _fail("INVALID_CAPABILITY", "capability operation roster is invalid")

        policy = snapshot.default_policy
        if not isinstance(policy, DefaultPolicy):
            _fail("INVALID_POLICY", "default policy is invalid")
        if (
            policy.contract_id != DEFAULT_POLICY_CONTRACT
            or policy.toolchain_binding != snapshot.toolchain_binding
        ):
            _fail("TOOLCHAIN_DRIFT", "default policy toolchain binding differs")
        _strict_hash(policy.policy_revision, label="default policy revision")
        if not hmac.compare_digest(default_policy_revision(policy), policy.policy_revision):
            _fail("REVISION_DRIFT", "default policy revision differs")

        semantic_candidates = tuple(semantic.authorities)
        capability_candidates = tuple(capabilities.authorities)
        if (
            not semantic_candidates
            or len(semantic_candidates) + len(capability_candidates) > MAX_AUTHORITIES
        ):
            _fail("INVALID_AUTHORITY", "authority roster is empty or exceeds its bound")
        all_candidates: list[AuthorityCandidate] = []
        for entry in semantic_candidates:
            if not isinstance(entry, ReviewedSemanticAuthority):
                _fail("INVALID_SEMANTICS", "semantic authority is invalid")
            if entry.state != "reviewed":
                return Unsupported("SEMANTIC_NOT_REVIEWED", "semantic authority is not reviewed")
            if entry.domain not in {"finite", "open", "none"}:
                _fail("INVALID_SEMANTICS", "semantic domain is invalid")
            if not entry.resolved:
                code = "OPEN_DOMAIN_UNRESOLVED" if entry.domain == "open" else "SEMANTIC_UNRESOLVED"
                return Unsupported(code, "semantic authority is unresolved")
            _validate_candidate(entry.authority, semantic=True)
            all_candidates.append(entry.authority)
        for candidate in capability_candidates:
            _validate_candidate(candidate, semantic=False)
            all_candidates.append(candidate)
        keys = [candidate.key for candidate in all_candidates]
        if len(keys) != len(set(keys)):
            _fail("INVALID_AUTHORITY", "authority keys are duplicated")
        authority_roles = {
            candidate.key: frozenset(candidate.roles) for candidate in all_candidates
        }

        decisions = self._decisions(snapshot, authority_roles)
        policy_entries = self._policy_entries(policy, authority_roles)
        flash_spans = self._flash_spans(snapshot, history)
        output_requirement = self._output_requirement(
            snapshot,
            history,
            decisions=decisions,
            policy_entries=policy_entries,
        )

        pending = set(snapshot.ambiguities)
        pending.update(semantic.ambiguities)
        if semantic.status == "clarify" and not semantic.ambiguities:
            pending.add("semantic_choice")
        requested_kinds = {
            kind
            for requirement in snapshot.requirements
            if isinstance(requirement, RequirementClaim)
            for kind in requirement.allowed_kinds
        }
        if snapshot.flash_intent is not None:
            pending.update(
                _FLASH_AMBIGUITY_MAP[item] for item in snapshot.flash_intent.value["ambiguities"]
            )
            response_state = snapshot.flash_intent.value["response_format"]
            fallback_state = snapshot.flash_intent.value["fallback"]
            if response_state == "ambiguous" or (
                response_state == "unspecified"
                and not requested_kinds & {"response.set", "output.set_pipeline"}
            ):
                pending.add("response_shape")
            if fallback_state == "ambiguous" or (
                fallback_state == "unspecified" and "fallback.set" not in requested_kinds
            ):
                pending.add("fallback")
        else:
            if not requested_kinds & {"response.set", "output.set_pipeline"}:
                pending.add("response_shape")
            if "fallback.set" not in requested_kinds:
                pending.add("fallback")
        pending.update(self._output_ambiguities(snapshot.output_request, output_requirement))
        if any(kind not in _AMBIGUITY_SET for kind in pending):
            _fail("INVALID_AMBIGUITY", "authority ambiguity kind is invalid")
        resolved_kinds = set(decision.kind for decision in snapshot.clarification_decisions)
        resolved_kinds.update(entry.kind for entry, _value in policy_entries.values())
        pending.difference_update(resolved_kinds)
        if pending:
            return NeedsClarification(_ordered_ambiguities(pending))

        requirements = list(snapshot.requirements)
        if output_requirement is not None:
            requirements.append(output_requirement)
        if not requirements or len(requirements) > MAX_REQUIREMENTS:
            _fail("INVALID_REQUIREMENT", "requirement roster is empty or exceeds its bound")
        requirement_keys = [item.key for item in requirements if isinstance(item, RequirementClaim)]
        if len(requirement_keys) != len(requirements) or len(requirement_keys) != len(
            set(requirement_keys)
        ):
            _fail("INVALID_REQUIREMENT", "requirement keys are invalid or duplicated")
        requirement_key_set = set(requirement_keys)
        logical_keys = [snapshot.target.key, *keys, *requirement_keys]
        if snapshot.basis is not None:
            logical_keys.append(snapshot.basis.key)
        if len(logical_keys) != len(set(logical_keys)):
            _fail("INVALID_AUTHORITY", "authority namespaces contain duplicate logical keys")
        requirements_by_key = {item.key: item for item in requirements}
        for candidate in all_candidates:
            if not set(candidate.requirement_keys).issubset(requirement_key_set):
                _fail("INVALID_AUTHORITY", "authority binds an unknown requirement")
            for requirement_key in candidate.requirement_keys:
                if candidate.key not in requirements_by_key[requirement_key].authority_keys:
                    _fail("INVALID_AUTHORITY", "authority binding is not reciprocal")
        candidates_by_key = {candidate.key: candidate for candidate in all_candidates}
        for requirement in requirements:
            for authority_key in requirement.authority_keys:
                candidate = candidates_by_key.get(authority_key)
                if candidate is None or requirement.key not in candidate.requirement_keys:
                    _fail("INVALID_REQUIREMENT", "requirement authority binding is not reciprocal")
        admitted_flash_spans = {
            (item.message_ordinal, item.start_utf8, item.end_utf8)
            for item in requirements
            if item.origin == "flash"
        }
        if admitted_flash_spans != set(flash_spans):
            _fail("INVALID_FLASH", "Flash concepts and admitted requirements differ")

        if snapshot.flash_intent is not None:
            requested_kinds = {
                kind for requirement in requirements for kind in requirement.allowed_kinds
            }
            if snapshot.flash_intent.value[
                "response_format"
            ] == "change_requested" and not requested_kinds & {
                "response.set",
                "output.set_pipeline",
            }:
                _fail("MISSING_REQUIREMENT", "requested response change has no requirement")
            if (
                snapshot.flash_intent.value["fallback"] == "change_requested"
                and "fallback.set" not in requested_kinds
            ):
                _fail("MISSING_REQUIREMENT", "requested fallback has no requirement")

        target_ref = self._ref(
            snapshot,
            "target",
            {"key": snapshot.target.key, "payload": target_payload},
        )
        basis_ref = (
            self._ref(
                snapshot,
                "basis",
                {"key": snapshot.basis.key, "payload": basis_payload},
            )
            if snapshot.basis is not None
            else None
        )
        grants: list[CreateAuthorityGrant] = [
            self._grant(target_ref, ("target",), snapshot.target.label, target_payload)
        ]
        key_to_ref: dict[str, str] = {snapshot.target.key: target_ref}
        if snapshot.basis is not None and basis_ref is not None and basis_payload is not None:
            grants.append(self._grant(basis_ref, ("basis",), snapshot.basis.label, basis_payload))
            key_to_ref[snapshot.basis.key] = basis_ref

        for candidate in all_candidates:
            payload = _validate_fragment(candidate.fragment)
            ref = self._ref(
                snapshot,
                "grant",
                {"key": candidate.key, "roles": sorted(candidate.roles), "payload": payload},
            )
            key_to_ref[candidate.key] = ref
            grants.append(self._grant(ref, tuple(candidate.roles), candidate.label, payload))

        requirement_authorities: dict[str, tuple[str, ...]] = {}
        for requirement in requirements:
            requirement_ref, grant = self._requirement_grant(
                snapshot,
                history,
                requirement,
                key_to_ref=key_to_ref,
                decisions=decisions,
                policy_entries=policy_entries,
                flash_spans=flash_spans,
                operation_kinds=frozenset(operation_kinds),
            )
            key_to_ref[requirement.key] = requirement_ref
            requirement_authorities[requirement_ref] = tuple(
                key_to_ref[item] for item in requirement.authority_keys
            )
            grants.append(grant)

        surface = CreateAuthoritySurface(
            history=history,
            history_revision=snapshot.history_revision,
            target_ref=target_ref,
            basis_ref=basis_ref,
            grants=grants,
        )
        registry = PrivateAuthorityRegistry(
            surface=surface,
            key_to_ref=key_to_ref,
            requirement_authorities=requirement_authorities,
        )
        return Issued(
            surface=surface,
            context_revision=snapshot.context_revision,
            semantic_revision=snapshot.semantic_revision,
            toolchain_binding=snapshot.toolchain_binding,
            generation=snapshot.generation,
            private_registry=registry,
        )

    @staticmethod
    def _root_payload(root: RootAuthority | None, *, label: str) -> dict[str, Any]:
        if not isinstance(root, RootAuthority):
            _fail("INVALID_LINEAGE", f"{label} authority is invalid")
        _key(root.key, label=f"{label} key")
        if not isinstance(root.label, str) or not root.label:
            _fail("INVALID_LINEAGE", f"{label} label is invalid")
        return _validate_fragment(root.fragment, root=True)

    def _ref(
        self,
        snapshot: IssuanceSnapshot,
        namespace: str,
        identity: Mapping[str, Any],
    ) -> str:
        return _hmac_ref(
            self._secret,
            session_id=snapshot.session_id,
            namespace=namespace,
            identity={
                "history_revision": snapshot.history_revision,
                "context_revision": snapshot.context_revision,
                "semantic_revision": snapshot.semantic_revision,
                "toolchain_binding": snapshot.toolchain_binding,
                "semantic_projection_revision": snapshot.semantic_projection.projection_revision,
                "capability_inventory_revision": snapshot.capabilities.inventory_revision,
                "clarification_revision": snapshot.clarification_revision,
                "default_policy_revision": snapshot.default_policy.policy_revision,
                "generation": snapshot.generation,
                **identity,
            },
        )

    @staticmethod
    def _grant(
        ref: str,
        roles: Sequence[str],
        label: str,
        payload: Any,
        *,
        requirement: RequirementEvidence | None = None,
    ) -> CreateAuthorityGrant:
        copied = _strict_json_copy(payload, label="grant payload")
        return CreateAuthorityGrant(
            ref=ref,
            roles=tuple(roles),
            label=label,
            payload=copied,
            payload_sha256=bytes_sha256(canonical_json(copied)),
            requirement=requirement,
        )

    @staticmethod
    def _decisions(
        snapshot: IssuanceSnapshot,
        authority_roles: Mapping[str, frozenset[str]],
    ) -> dict[str, tuple[TypedDecision, Any]]:
        decisions = tuple(snapshot.clarification_decisions)
        if len(decisions) > MAX_DECISIONS:
            _fail("INVALID_DECISION", "clarification decision roster exceeds its bound")
        _strict_hash(snapshot.clarification_revision, label="clarification revision")
        if not hmac.compare_digest(
            clarification_decisions_revision(decisions), snapshot.clarification_revision
        ):
            _fail("REVISION_DRIFT", "clarification decision revision differs")
        result: dict[str, tuple[TypedDecision, Any]] = {}
        kinds: set[str] = set()
        for decision in decisions:
            if not isinstance(decision, TypedDecision):
                _fail("INVALID_DECISION", "clarification decision is invalid")
            _key(decision.key, label="clarification decision key")
            if (
                decision.key in result
                or decision.kind not in _DECISION_KINDS
                or decision.kind in kinds
            ):
                _fail("INVALID_DECISION", "clarification decision key or kind is invalid")
            kinds.add(decision.kind)
            if (
                decision.context_revision != snapshot.context_revision
                or decision.semantic_revision != snapshot.semantic_revision
            ):
                _fail("REVISION_DRIFT", "clarification decision authority binding differs")
            _strict_hash(decision.decision_sha256, label="clarification decision hash")
            expected = decision_sha256(
                key=decision.key,
                kind=decision.kind,
                value=decision.value,
                context_revision=decision.context_revision,
                semantic_revision=decision.semantic_revision,
            )
            if not hmac.compare_digest(expected, decision.decision_sha256):
                _fail("REVISION_DRIFT", "clarification decision hash differs")
            value = _validate_decision_value(
                decision.kind,
                decision.value,
                authority_roles=authority_roles,
            )
            result[decision.key] = (decision, value)
        return result

    @staticmethod
    def _policy_entries(
        policy: DefaultPolicy,
        authority_roles: Mapping[str, frozenset[str]],
    ) -> dict[str, tuple[PolicyDecision, Any]]:
        entries = tuple(policy.entries)
        if len(entries) > MAX_POLICY_ENTRIES:
            _fail("INVALID_POLICY", "default policy roster exceeds its bound")
        result: dict[str, tuple[PolicyDecision, Any]] = {}
        kinds: set[str] = set()
        for entry in entries:
            if not isinstance(entry, PolicyDecision):
                _fail("INVALID_POLICY", "default policy entry is invalid")
            _key(entry.key, label="default policy key")
            if entry.key in result or entry.kind not in _DECISION_KINDS or entry.kind in kinds:
                _fail("INVALID_POLICY", "default policy entry is duplicated or invalid")
            kinds.add(entry.kind)
            value = _validate_decision_value(
                entry.kind,
                entry.value,
                authority_roles=authority_roles,
            )
            result[entry.key] = (entry, value)
        return result

    @staticmethod
    def _flash_spans(
        snapshot: IssuanceSnapshot,
        history: Sequence[CreateAuthorityHistoryMessage],
    ) -> dict[tuple[int, int, int], bytes]:
        spans = tuple(snapshot.flash_spans)
        if snapshot.flash_intent is None:
            if spans:
                _fail("INVALID_FLASH", "Flash spans exist without an admitted Flash intent")
            return {}
        if not isinstance(snapshot.flash_intent, IntentIR):
            _fail("INVALID_FLASH", "Flash intent is invalid")
        current = history[-1]
        parsed = IntentIR.parse(
            snapshot.flash_intent.value,
            request=IntentCompileRequest(
                instruction=current.text,
                intent="create",
                target_mode="create",
            ),
        )
        concepts = parsed.value["concepts"]
        if len(spans) != len(concepts) or len(spans) > MAX_FLASH_SPANS:
            _fail("INVALID_FLASH", "Flash exact-span roster differs from its concepts")
        result: dict[tuple[int, int, int], bytes] = {}
        indexes: set[int] = set()
        for span in spans:
            if not isinstance(span, FlashExactSpan) or span.concept_index in indexes:
                _fail("INVALID_FLASH", "Flash exact span is invalid or duplicated")
            indexes.add(span.concept_index)
            if span.concept_index < 0 or span.concept_index >= len(concepts):
                _fail("INVALID_FLASH", "Flash concept index is invalid")
            if span.message_ordinal != len(history) - 1:
                _fail("INVALID_FLASH", "Flash evidence is not from the current operator turn")
            raw = _utf8_span(
                history,
                message_ordinal=span.message_ordinal,
                start_utf8=span.start_utf8,
                end_utf8=span.end_utf8,
            )
            if raw.decode("utf-8") != concepts[span.concept_index]["source"]:
                _fail("INVALID_FLASH", "Flash concept differs from its exact operator span")
            result[(span.message_ordinal, span.start_utf8, span.end_utf8)] = raw
        if indexes != set(range(len(concepts))):
            _fail("INVALID_FLASH", "Flash concept roster is incomplete")
        return result

    @staticmethod
    def _output_requirement(
        snapshot: IssuanceSnapshot,
        history: Sequence[CreateAuthorityHistoryMessage],
        *,
        decisions: Mapping[str, tuple[TypedDecision, Any]],
        policy_entries: Mapping[str, tuple[PolicyDecision, Any]],
    ) -> RequirementClaim | None:
        output = snapshot.output_request
        if not isinstance(output, OutputRequestSurface):
            _fail("INVALID_OUTPUT", "output request surface is invalid")
        current = history[-1].text
        if output != parse_output_request(current):
            _fail("REVISION_DRIFT", "output request differs from current operator turn")
        if output.invalid_numeric_output or output.invalid_numeric_pagination:
            _fail("INVALID_OUTPUT", "output request contains an invalid numeric contract")
        effective_output = output
        effective_ordinal = len(history) - 1
        current_is_silent = (
            not output.contracts and not output.ambiguous_count and not output.generic_pagination
        )
        if current_is_silent:
            # Refinements preserve the latest exact cumulative output contract.
            # Scan parsed operator turns, never generated summaries.
            for ordinal in range(len(history) - 2, -1, -1):
                candidate = parse_output_request(history[ordinal].text)
                if candidate.invalid_numeric_output or candidate.invalid_numeric_pagination:
                    _fail("INVALID_OUTPUT", "history contains an invalid numeric contract")
                if candidate.contracts or candidate.ambiguous_count or candidate.generic_pagination:
                    effective_output = candidate
                    effective_ordinal = ordinal
                    break
        resolved: tuple[str, str, dict[str, Any]] | None = None
        clarification_values = [
            (key, value)
            for key, (decision, value) in decisions.items()
            if decision.kind == "result_count"
        ]
        if len(clarification_values) > 1:
            _fail("INVALID_DECISION", "multiple result-count decisions are active")
        if clarification_values:
            key, value = clarification_values[0]
            resolved = ("clarification", key, value)
        policy_values = [
            (key, value)
            for key, (entry, value) in policy_entries.items()
            if entry.kind == "result_count"
        ]
        if len(policy_values) > 1:
            _fail("INVALID_POLICY", "multiple result-count defaults are active")
        if resolved is None and policy_values:
            key, value = policy_values[0]
            resolved = ("policy", key, value)

        if effective_output.ambiguous_count or len(effective_output.contracts) != 1:
            if resolved is None:
                return None
            origin, evidence_key, selected = resolved
            mode = selected["mode"]
            value = selected["value"]
            return RequirementClaim(
                key="output.contract",
                label=f"{value} per pagina" if mode == "page" else f"{value} risultati",
                allowed_kinds=(
                    ("query.set_pagination",) if mode == "page" else ("query.set_take",)
                ),
                authority_keys=(),
                origin=origin,
                evidence_key=evidence_key,
            )
        mode, value = effective_output.contracts[0]
        if resolved is not None:
            _origin, _key_value, selected = resolved
            if (selected["mode"], selected["value"]) != (mode, value):
                _fail("REVISION_DRIFT", "result-count decision differs from operator contract")
        matching = [
            mention
            for mention in effective_output.mentions
            if mention.mode == mode and mention.value == value
        ]
        if not matching:
            _fail("INVALID_OUTPUT", "output contract has no exact operator span")
        mention = matching[0]
        evidence_text = history[effective_ordinal].text
        start_utf8 = len(evidence_text[: mention.start].encode("utf-8"))
        end_utf8 = len(evidence_text[: mention.end].encode("utf-8"))
        return RequirementClaim(
            key="output.contract",
            label=f"{value} per pagina" if mode == "page" else f"{value} risultati",
            allowed_kinds=(("query.set_pagination",) if mode == "page" else ("query.set_take",)),
            authority_keys=(),
            origin="operator",
            message_ordinal=effective_ordinal,
            start_utf8=start_utf8,
            end_utf8=end_utf8,
        )

    @staticmethod
    def _output_ambiguities(
        output: OutputRequestSurface,
        output_requirement: RequirementClaim | None,
    ) -> set[str]:
        if output_requirement is None:
            return {"result_count"}
        return set()

    def _requirement_grant(
        self,
        snapshot: IssuanceSnapshot,
        history: Sequence[CreateAuthorityHistoryMessage],
        requirement: RequirementClaim,
        *,
        key_to_ref: Mapping[str, str],
        decisions: Mapping[str, tuple[TypedDecision, Any]],
        policy_entries: Mapping[str, tuple[PolicyDecision, Any]],
        flash_spans: Mapping[tuple[int, int, int], bytes],
        operation_kinds: frozenset[str],
    ) -> tuple[str, CreateAuthorityGrant]:
        if not isinstance(requirement, RequirementClaim):
            _fail("INVALID_REQUIREMENT", "requirement is invalid")
        _key(requirement.key, label="requirement key")
        if not isinstance(requirement.label, str) or not requirement.label:
            _fail("INVALID_REQUIREMENT", "requirement label is invalid")
        kinds = tuple(requirement.allowed_kinds)
        if not kinds or len(kinds) != len(set(kinds)) or not set(kinds).issubset(operation_kinds):
            _fail("UNSUPPORTED_OPERATION", "requirement exceeds the toolchain capability roster")
        authority_keys = tuple(requirement.authority_keys)
        if len(authority_keys) != len(set(authority_keys)) or any(
            item not in key_to_ref for item in authority_keys
        ):
            _fail("INVALID_REQUIREMENT", "requirement authority binding is invalid")
        payload = {
            "requirement_key": requirement.key,
            "authority_refs": [key_to_ref[item] for item in authority_keys],
        }
        evidence_payload: Any | None = None
        if requirement.origin in {"operator", "flash"}:
            if requirement.evidence_key is not None:
                _fail("INVALID_EVIDENCE", "operator evidence cannot name a decision")
            span = _utf8_span(
                history,
                message_ordinal=requirement.message_ordinal,
                start_utf8=requirement.start_utf8,
                end_utf8=requirement.end_utf8,
            )
            coordinates = (
                requirement.message_ordinal,
                requirement.start_utf8,
                requirement.end_utf8,
            )
            if requirement.origin == "flash" and flash_spans.get(coordinates) != span:
                _fail("INVALID_FLASH", "Flash requirement is not an exact admitted concept span")
            evidence = RequirementEvidence(
                origin="operator",
                message_ordinal=requirement.message_ordinal,
                start_utf8=requirement.start_utf8,
                end_utf8=requirement.end_utf8,
                evidence_sha256=bytes_sha256(span),
                allowed_kinds=kinds,
            )
        elif requirement.origin == "clarification":
            if (
                requirement.evidence_key is None
                or requirement.evidence_key not in decisions
                or any(
                    item is not None
                    for item in (
                        requirement.message_ordinal,
                        requirement.start_utf8,
                        requirement.end_utf8,
                    )
                )
            ):
                _fail("INVALID_EVIDENCE", "clarification evidence is invalid")
            decision, value = decisions[requirement.evidence_key]
            selected_authority = value.get("authority_key")
            if selected_authority is not None and selected_authority not in authority_keys:
                _fail(
                    "INVALID_EVIDENCE",
                    "clarification selection is not bound to its requirement",
                )
            evidence_payload = {
                "decision_key": decision.key,
                "kind": decision.kind,
                "value": value,
                "decision_sha256": decision.decision_sha256,
            }
            evidence = RequirementEvidence(
                origin="clarification",
                message_ordinal=None,
                start_utf8=None,
                end_utf8=None,
                evidence_sha256=bytes_sha256(canonical_json(evidence_payload)),
                allowed_kinds=kinds,
                evidence_payload=evidence_payload,
            )
        elif requirement.origin == "policy":
            if (
                requirement.evidence_key is None
                or requirement.evidence_key not in policy_entries
                or any(
                    item is not None
                    for item in (
                        requirement.message_ordinal,
                        requirement.start_utf8,
                        requirement.end_utf8,
                    )
                )
            ):
                _fail("INVALID_EVIDENCE", "policy evidence is invalid")
            policy, value = policy_entries[requirement.evidence_key]
            selected_authority = value.get("authority_key")
            if selected_authority is not None and selected_authority not in authority_keys:
                _fail("INVALID_EVIDENCE", "policy selection is not bound to its requirement")
            evidence_payload = {
                "policy_key": policy.key,
                "kind": policy.kind,
                "value": value,
                "policy_revision": snapshot.default_policy.policy_revision,
            }
            evidence = RequirementEvidence(
                origin="policy",
                message_ordinal=None,
                start_utf8=None,
                end_utf8=None,
                evidence_sha256=bytes_sha256(canonical_json(evidence_payload)),
                allowed_kinds=kinds,
                evidence_payload=evidence_payload,
            )
        else:
            _fail("INVALID_EVIDENCE", "requirement evidence origin is invalid")
        requirement_ref = self._ref(
            snapshot,
            "requirement",
            {
                "key": requirement.key,
                "allowed_kinds": sorted(kinds),
                "payload": payload,
                "evidence_sha256": evidence.evidence_sha256,
            },
        )
        return requirement_ref, self._grant(
            requirement_ref,
            ("requirement",),
            requirement.label,
            payload,
            requirement=evidence,
        )


__all__ = [
    "AMBIGUITY_KINDS",
    "CAPABILITY_INVENTORY_CONTRACT",
    "CLARIFICATION_DECISIONS_CONTRACT",
    "CREATE_AUTHORITY_ISSUER_CONTRACT",
    "DEFAULT_POLICY_CONTRACT",
    "SAFE_REVIEWED_PROJECTION_CONTRACT",
    "AuthorityCandidate",
    "CapabilityInventory",
    "CreateAuthorityIssuer",
    "CreateAuthorityIssuerError",
    "DefaultPolicy",
    "FlashExactSpan",
    "IssueResult",
    "Issued",
    "IssuanceSnapshot",
    "NeedsClarification",
    "PolicyDecision",
    "PrivateAuthorityRegistry",
    "RequirementClaim",
    "ReviewedSemanticAuthority",
    "RootAuthority",
    "SafeReviewedProjection",
    "TypedDecision",
    "TypedFragment",
    "Unsupported",
    "capability_inventory_revision",
    "clarification_decisions_revision",
    "decision_sha256",
    "default_policy_revision",
    "safe_reviewed_projection_revision",
]
