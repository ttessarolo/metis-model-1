"""Fail-closed renderer for a semantic-only ``@video`` patch proposal.

This module deliberately does not parse, write, or apply a tenant catalog.  It
joins explicit semantic work items with an immutable technical roster and
returns a candidate plan that a separately authorised tool may review.  The
technical side of every operation is copied from the roster, never from the
model/work-item candidate.  Consequently a semantic author cannot change a
literal, type, domain, modifier, or source order while producing a draft.

The input contract is the work-item contract in
``schemas/video-semantic-work-item.schema.json`` plus a small, host-owned
technical roster.  A roster entry has ``canonical_locator``, ``technical`` and
an integer ``order``.  Optional ``aka_evidence`` is supplied out-of-band so
that an alias cannot be smuggled in merely because a model returned one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantics_contracts import validate_work_item

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PATH_RE = re.compile(r"^(?!/)(?!.*\\)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._@+/-]+$")

PATCH_CONTRACT = "video-semantics/candidate-patch-v1"
RECEIPT_CONTRACT = "video-semantics/candidate-patch-receipt-v1"
TECHNICAL_KEYS = frozenset(
    {"type", "modifiers", "domain_kind", "declared_cardinality", "observed_cardinality"}
)
FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "authorization",
        "bearer",
        "secret",
        "api_key",
        "apikey",
        "private_key",
        "_source",
        "raw_source",
        "source_text",
        "source_payload",
        "document_payload",
        "manual",
        "model_output",
        "raw_output",
        "chain_of_thought",
    }
)
FORBIDDEN_VALUE_RE = re.compile(
    r"(?is)(?:-----begin[^\n]*private key-----|\b(?:authorization|"
    r"bearer(?:\s+token)?|password|secret|api[_-]?key|private[_-]?key)\s*[:=]|"
    r"\b(?:_source|raw[_-]?(?:document|source)|document[_-]?payload|"
    r"source[_-]?payload)\b|^(?:/Users/|/home/|/private/var/|/tmp/|"
    r"[A-Za-z]:[\\/]))"
)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
NODE_KINDS = frozenset({"catalog", "field", "value"})


class SemanticPatchError(ValueError):
    """Raised when a candidate semantic patch cannot be trusted."""


def _hash(value: Any) -> str:
    try:
        return "sha256:" + canonical_json_hash(value)
    except (TypeError, ValueError) as error:
        raise SemanticPatchError("patch material is not canonical JSON") from error


def _hash_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise SemanticPatchError(f"{label} must be a lowercase sha256 identity")
    return value


def _safe_text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SemanticPatchError(f"{label} must be a bounded non-empty string")
    if CONTROL_RE.search(value):
        raise SemanticPatchError(f"{label} contains an unsafe control character")
    return value


def _safe_optional_text(value: Any, label: str, *, maximum: int = 4096) -> str | None:
    if value is None:
        return None
    return _safe_text(value, label, maximum=maximum)


def _assert_sanitized(value: Any, path: str = "$") -> None:
    """Reject raw-source, credential, and control-bearing material recursively."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SemanticPatchError(f"{path} contains a non-string key")
            if key.lower() in FORBIDDEN_KEYS:
                raise SemanticPatchError(f"{path}.{key} is a forbidden raw/sensitive field")
            _assert_sanitized(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_sanitized(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if CONTROL_RE.search(value):
            raise SemanticPatchError(f"{path} contains an unsafe control character")
        if FORBIDDEN_VALUE_RE.search(value):
            raise SemanticPatchError(f"{path} contains a forbidden sensitive/raw value")


def _locator(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticPatchError(f"{label} must be an object")
    required = {
        "repository_commit",
        "path",
        "catalog",
        "field_path",
        "literal",
        "preimage_sha256",
    }
    if set(value) != required:
        raise SemanticPatchError(f"{label} has an unexpected locator shape")
    commit = value["repository_commit"]
    if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
        raise SemanticPatchError(f"{label}.repository_commit is invalid")
    path = value["path"]
    if not isinstance(path, str) or PATH_RE.fullmatch(path) is None:
        raise SemanticPatchError(f"{label}.path is not a safe relative path")
    catalog = value["catalog"]
    if not isinstance(catalog, str) or OPAQUE_RE.fullmatch(catalog) is None:
        raise SemanticPatchError(f"{label}.catalog is not an opaque identifier")
    field_path = value["field_path"]
    if field_path is not None:
        _safe_text(field_path, f"{label}.field_path", maximum=512)
    literal = value["literal"]
    if literal is not None:
        _safe_text(literal, f"{label}.literal", maximum=1024)
    return {
        "repository_commit": commit,
        "path": path,
        "catalog": catalog,
        "field_path": field_path,
        "literal": literal,
        "preimage_sha256": _hash_ref(value["preimage_sha256"], f"{label}.preimage_sha256"),
    }


def _locator_identity(locator: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        locator[key] for key in ("repository_commit", "path", "catalog", "field_path", "literal")
    )


def _technical(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not TECHNICAL_KEYS.issubset(value):
        raise SemanticPatchError(f"{label} is missing technical invariants")
    _assert_sanitized(value, label)
    if set(value) != TECHNICAL_KEYS:
        raise SemanticPatchError(f"{label} has unexpected technical fields")
    result = deepcopy(dict(value))
    if not isinstance(result["type"], str) or not result["type"]:
        raise SemanticPatchError(f"{label}.type is invalid")
    modifiers = result["modifiers"]
    if (
        not isinstance(modifiers, list)
        or len(modifiers) != len(set(modifiers))
        or any(not isinstance(item, str) or not item for item in modifiers)
    ):
        raise SemanticPatchError(f"{label}.modifiers is invalid")
    if not isinstance(result["domain_kind"], str) or not result["domain_kind"]:
        raise SemanticPatchError(f"{label}.domain_kind is invalid")
    for key in ("declared_cardinality", "observed_cardinality"):
        if result[key] is not None and (type(result[key]) is not int or result[key] < 0):
            raise SemanticPatchError(f"{label}.{key} is invalid")
    return result


def _roster_entries(
    roster: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    value: Any = roster
    if isinstance(roster, Mapping):
        value = roster.get("roster", roster.get("nodes"))
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray) or not value:
        raise SemanticPatchError("technical roster must be a non-empty array")
    result: list[dict[str, Any]] = []
    identities: set[tuple[Any, ...]] = set()
    locators: set[str] = set()
    orders: set[int] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise SemanticPatchError(f"technical roster entry {index} is invalid")
        _assert_sanitized(raw, f"roster[{index}]")
        locator = raw.get("canonical_locator")
        if locator is None:
            locator = {
                key: raw.get(key)
                for key in (
                    "repository_commit",
                    "path",
                    "catalog",
                    "field_path",
                    "literal",
                    "preimage_sha256",
                )
            }
        parsed_locator = _locator(locator, f"roster[{index}].canonical_locator")
        identity = _locator_identity(parsed_locator)
        if identity in identities:
            raise SemanticPatchError("technical roster contains duplicate targets")
        identities.add(identity)
        locator_hash = _hash(parsed_locator)
        if locator_hash in locators:
            raise SemanticPatchError("technical roster contains duplicate locators")
        locators.add(locator_hash)
        order = raw.get("order")
        if type(order) is not int or order < 0 or order in orders:
            raise SemanticPatchError("technical roster order must be unique non-negative integers")
        orders.add(order)
        result.append(
            {
                "canonical_locator": parsed_locator,
                "technical": _technical(raw.get("technical"), f"roster[{index}].technical"),
                "order": order,
            }
        )
    return sorted(result, key=lambda item: item["order"])


def _aka_evidence(
    value: Mapping[str, Sequence[str]] | None,
    work_item: Mapping[str, Any],
    index: int,
) -> list[str]:
    aliases = work_item["candidate"]["aka"]
    if not aliases:
        return []
    if value is None:
        raise SemanticPatchError(f"work item {index} has aka without explicit evidence")
    concept_id = work_item["work_item_id"]
    refs = value.get(concept_id)
    if not isinstance(refs, Sequence) or isinstance(refs, str | bytes | bytearray) or not refs:
        raise SemanticPatchError(f"work item {index} has no aka evidence refs")
    refs_list = [_safe_text(item, f"aka evidence {index}", maximum=128) for item in refs]
    if len(refs_list) != len(set(refs_list)):
        raise SemanticPatchError(f"work item {index} aka evidence refs are not distinct")
    if not set(refs_list).issubset(set(work_item["evidence_refs"])):
        raise SemanticPatchError(f"work item {index} aka evidence is outside evidence_refs")
    return refs_list


def _render_grammar(means: str, aliases: Sequence[str]) -> str:
    # JSON string escaping is also valid for the quoted string surface used by
    # the grammar and makes quote/backslash injection impossible.
    import json

    rendered = f"means draft {json.dumps(means, ensure_ascii=False)}"
    if aliases:
        rendered += " aka " + json.dumps(list(aliases), ensure_ascii=False, separators=(",", ":"))
    return rendered


def render_candidate_patch(
    work_items: Sequence[Mapping[str, Any]],
    technical_roster: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    repository_commit: str,
    aka_evidence: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Render a semantic-only candidate patch plan.

    The source roster is authoritative for technical material and ordering.
    ``work_items`` may propose only a non-empty draft ``means`` and explicitly
    evidenced ``aka``.  This function never writes a catalog or returns an
    apply-ready mutation command.
    """

    if not isinstance(work_items, Sequence) or isinstance(work_items, str | bytes | bytearray):
        raise SemanticPatchError("work_items must be an array")
    if not isinstance(repository_commit, str) or COMMIT_RE.fullmatch(repository_commit) is None:
        raise SemanticPatchError("repository_commit is invalid")
    roster = _roster_entries(technical_roster)
    by_identity = {_locator_identity(item["canonical_locator"]): item for item in roster}
    seen_ids: set[str] = set()
    seen_targets: set[tuple[Any, ...]] = set()
    operations: list[dict[str, Any]] = []

    for index, raw in enumerate(work_items):
        if not isinstance(raw, Mapping):
            raise SemanticPatchError(f"work item {index} is not an object")
        _assert_sanitized(raw, f"work_items[{index}]")
        errors = validate_work_item(raw)
        if errors:
            raise SemanticPatchError(f"work item {index} is invalid: {'; '.join(errors)}")
        if raw["node_kind"] not in NODE_KINDS:
            raise SemanticPatchError(f"work item {index} node kind is unsupported")
        item_id = _hash_ref(raw["work_item_id"], f"work item {index}.work_item_id")
        if item_id in seen_ids:
            raise SemanticPatchError("duplicate work item IDs")
        seen_ids.add(item_id)
        candidate = raw["candidate"]
        if candidate["review_state"] != "draft":
            raise SemanticPatchError("reviewed or unannotated work items cannot be promoted")
        means = _safe_text(candidate["means"], f"work item {index}.candidate.means")
        aliases = candidate["aka"]
        for alias_index, alias in enumerate(aliases):
            _safe_text(alias, f"work item {index}.candidate.aka[{alias_index}]", maximum=256)
        _aka_evidence(aka_evidence, raw, index)
        locator = _locator(raw["canonical_locator"], f"work item {index}.canonical_locator")
        if locator["repository_commit"] != repository_commit:
            raise SemanticPatchError("work item repository commit differs from patch preimage")
        identity = _locator_identity(locator)
        source = by_identity.get(identity)
        if source is None:
            raise SemanticPatchError("work item target is absent from the technical roster")
        source_locator = source["canonical_locator"]
        if locator["preimage_sha256"] != source_locator["preimage_sha256"]:
            raise SemanticPatchError("technical preimage drifted after work-item authoring")
        item_technical = _technical(raw["technical"], f"work item {index}.technical")
        if item_technical != source["technical"]:
            raise SemanticPatchError("work item technical invariants differ from the preimage")
        if identity in seen_targets:
            raise SemanticPatchError("duplicate patch target")
        seen_targets.add(identity)
        operations.append(
            {
                "node_kind": raw["node_kind"],
                "canonical_locator": deepcopy(source_locator),
                "technical": deepcopy(source["technical"]),
                "order": source["order"],
                "semantic": {
                    "means": means,
                    "aka": list(aliases),
                    "review_state": "draft",
                },
                "grammar": _render_grammar(means, aliases),
            }
        )

    operations.sort(key=lambda item: item["order"])
    body: dict[str, Any] = {
        "schema_version": 1,
        "contract_id": PATCH_CONTRACT,
        "repository_commit": repository_commit,
        "operations": operations,
    }
    patch_sha256 = _hash(body)
    patch = {**body, "patch_sha256": patch_sha256}
    counts = {
        "items_in": len(work_items),
        "items_out": len(operations),
        "items_distinct": len(seen_targets),
        "items_gaps": len(work_items) - len(operations),
    }
    receipt_body = {
        "schema_version": 1,
        "contract_id": RECEIPT_CONTRACT,
        "patch_sha256": patch_sha256,
        "counts": counts,
        "payload_redacted": True,
    }
    receipt = {**receipt_body, "receipt_sha256": _hash(receipt_body)}
    patch["receipt"] = receipt
    return patch


def validate_candidate_patch(
    patch: Any,
    *,
    technical_roster: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    repository_commit: str | None = None,
) -> list[str]:
    """Return deterministic validation errors for a rendered candidate plan."""

    errors: list[str] = []
    try:
        _assert_sanitized(patch)
    except SemanticPatchError as error:
        errors.append(str(error))
        return errors
    if not isinstance(patch, Mapping):
        return ["patch must be an object"]
    expected_keys = {
        "schema_version",
        "contract_id",
        "repository_commit",
        "operations",
        "patch_sha256",
        "receipt",
    }
    if set(patch) != expected_keys:
        errors.append("patch fields are not the closed candidate contract")
        return errors
    if patch.get("schema_version") != 1 or patch.get("contract_id") != PATCH_CONTRACT:
        errors.append("patch identity is invalid")
    try:
        commit = patch["repository_commit"]
        if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
            raise SemanticPatchError("repository_commit is invalid")
        if repository_commit is not None and commit != repository_commit:
            raise SemanticPatchError("patch repository commit differs from expected commit")
        operations = patch["operations"]
        if not isinstance(operations, list):
            raise SemanticPatchError("operations must be an array")
        if patch["patch_sha256"] != _hash(
            {
                key: patch[key]
                for key in ("schema_version", "contract_id", "repository_commit", "operations")
            }
        ):
            raise SemanticPatchError("patch self-hash is invalid")
        seen_targets: set[tuple[Any, ...]] = set()
        seen_orders: set[int] = set()
        roster_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
        if technical_roster is not None:
            roster_by_identity = {
                _locator_identity(item["canonical_locator"]): item
                for item in _roster_entries(technical_roster)
            }
        for index, operation in enumerate(operations):
            if not isinstance(operation, Mapping):
                raise SemanticPatchError(f"operation {index} is invalid")
            if set(operation) != {
                "node_kind",
                "canonical_locator",
                "technical",
                "order",
                "semantic",
                "grammar",
            }:
                raise SemanticPatchError(f"operation {index} has an unexpected shape")
            if operation["node_kind"] not in NODE_KINDS:
                raise SemanticPatchError(f"operation {index}.node_kind is invalid")
            locator = _locator(
                operation["canonical_locator"], f"operation {index}.canonical_locator"
            )
            identity = _locator_identity(locator)
            if identity in seen_targets:
                raise SemanticPatchError("duplicate patch target")
            seen_targets.add(identity)
            order = operation["order"]
            if type(order) is not int or order < 0 or order in seen_orders:
                raise SemanticPatchError("patch operation order is not distinct")
            seen_orders.add(order)
            technical = _technical(operation["technical"], f"operation {index}.technical")
            semantic = operation["semantic"]
            if not isinstance(semantic, Mapping) or set(semantic) != {
                "means",
                "aka",
                "review_state",
            }:
                raise SemanticPatchError(f"operation {index}.semantic is invalid")
            if semantic["review_state"] != "draft":
                raise SemanticPatchError("candidate patch cannot promote reviewed semantics")
            means = _safe_text(semantic["means"], f"operation {index}.semantic.means")
            aliases = semantic["aka"]
            if not isinstance(aliases, list) or len(aliases) != len(set(aliases)):
                raise SemanticPatchError(f"operation {index}.semantic.aka is invalid")
            for alias in aliases:
                _safe_text(alias, f"operation {index}.semantic.aka", maximum=256)
            if operation["grammar"] != _render_grammar(means, aliases):
                raise SemanticPatchError(f"operation {index}.grammar is not canonical")
            if roster_by_identity:
                source = roster_by_identity.get(identity)
                if source is None:
                    raise SemanticPatchError(f"operation {index} target is absent from roster")
                if locator["preimage_sha256"] != source["canonical_locator"]["preimage_sha256"]:
                    raise SemanticPatchError("technical preimage drifted")
                if technical != source["technical"] or order != source["order"]:
                    raise SemanticPatchError("operation changed technical material or order")
    except (KeyError, TypeError, SemanticPatchError) as error:
        errors.append(str(error))
    try:
        errors.extend(validate_patch_receipt(patch.get("receipt")))
        if isinstance(patch.get("receipt"), Mapping) and patch["receipt"].get(
            "patch_sha256"
        ) != patch.get("patch_sha256"):
            errors.append("receipt patch hash differs from candidate patch")
    except Exception as error:  # validation API must remain list-returning
        errors.append(f"receipt validation failed: {error}")
    return errors


def validate_patch_receipt(receipt: Any) -> list[str]:
    """Validate the payload-free hash/count receipt emitted with a patch."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    if set(receipt) != {
        "schema_version",
        "contract_id",
        "patch_sha256",
        "counts",
        "payload_redacted",
        "receipt_sha256",
    }:
        errors.append("receipt fields are not the closed hash/count contract")
        return errors
    if receipt["schema_version"] != 1 or receipt["contract_id"] != RECEIPT_CONTRACT:
        errors.append("receipt identity is invalid")
    try:
        _hash_ref(receipt["patch_sha256"], "receipt.patch_sha256")
        counts = receipt["counts"]
        if not isinstance(counts, Mapping) or set(counts) != {
            "items_in",
            "items_out",
            "items_distinct",
            "items_gaps",
        }:
            raise SemanticPatchError("receipt counts are invalid")
        if any(type(counts[key]) is not int or counts[key] < 0 for key in counts):
            raise SemanticPatchError("receipt counts are invalid")
        if counts["items_in"] != counts["items_out"] + counts["items_gaps"]:
            raise SemanticPatchError("receipt count arithmetic is invalid")
        if counts["items_distinct"] > counts["items_out"]:
            raise SemanticPatchError("receipt distinct count exceeds output count")
        if receipt["payload_redacted"] is not True:
            raise SemanticPatchError("receipt must be payload-redacted")
        body = {
            key: receipt[key]
            for key in (
                "schema_version",
                "contract_id",
                "patch_sha256",
                "counts",
                "payload_redacted",
            )
        }
        if receipt["receipt_sha256"] != _hash(body):
            raise SemanticPatchError("receipt self-hash is invalid")
    except (KeyError, TypeError, SemanticPatchError) as error:
        errors.append(str(error))
    return errors


# Naming aliases keep the contract discoverable to callers that call the
# artifact a plan instead of a patch.
render_patch_plan = render_candidate_patch
validate_patch_plan = validate_candidate_patch


__all__ = [
    "PATCH_CONTRACT",
    "RECEIPT_CONTRACT",
    "SemanticPatchError",
    "render_candidate_patch",
    "render_patch_plan",
    "validate_candidate_patch",
    "validate_patch_plan",
    "validate_patch_receipt",
]
