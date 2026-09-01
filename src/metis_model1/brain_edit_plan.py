"""Strict host-validated Model 1 EditPlan.

An EditPlan is a proposal over host-issued opaque references.  It is not source
text, a path, a catalog/field/value identifier, or an apply command.  The
pinned AST renderer (a later integration seam) resolves references only after
this contract has passed validation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EDIT_PLAN_SCHEMA_PATH = PROJECT_ROOT / "schemas/metis-brain-edit-plan.schema.json"
EDIT_PLAN_CONTRACT = "metis-brain-edit-plan/v1"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_REF_RE = re.compile(r"^hostref:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_OPERATIONS = 32


class EditPlanError(ValueError):
    """Raised when a proposed edit plan cannot be admitted."""


def _load_schema() -> dict[str, Any]:
    try:
        value = json.loads(EDIT_PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
    except Exception as error:  # noqa: BLE001 - fail closed on a tracked contract
        raise EditPlanError("EditPlan schema is unavailable or invalid") from error
    return value


EDIT_PLAN_SCHEMA = _load_schema()
EDIT_PLAN_SCHEMA_SHA256 = bytes_sha256(canonical_json(EDIT_PLAN_SCHEMA))
_SCHEMA_VALIDATOR = Draft202012Validator(EDIT_PLAN_SCHEMA)


def _schema_errors(value: Any) -> list[str]:
    return [error.message for error in _SCHEMA_VALIDATOR.iter_errors(value)]


def _refs(value: Mapping[str, Any]) -> list[str]:
    refs: list[str] = [value["target_ref"]]
    if value.get("base_ref") is not None:
        refs.append(value["base_ref"])
    for operation in value["operations"]:
        refs.append(operation["target_ref"])
        if operation.get("anchor_ref") is not None:
            refs.append(operation["anchor_ref"])
        if operation.get("payload_ref") is not None:
            refs.append(operation["payload_ref"])
    return refs


def validate_edit_plan(
    value: Any,
    *,
    issued_refs: Collection[str] | Mapping[str, Any],
    expected_context_revision: str,
    expected_source_revision: str,
) -> list[str]:
    """Return deterministic host-validation errors; never resolve a ref."""

    errors = _schema_errors(value)
    if errors:
        return errors
    if not isinstance(value, Mapping):
        return ["EditPlan must be an object"]
    if not HASH_RE.fullmatch(expected_context_revision):
        return ["expected context revision is invalid"]
    if not HASH_RE.fullmatch(expected_source_revision):
        return ["expected source revision is invalid"]
    if value["context_revision"] != expected_context_revision:
        return ["context revision differs from the admitted snapshot"]
    if value["source_revision"] != expected_source_revision:
        return ["source revision differs from the admitted source"]
    known = set(issued_refs)
    refs = _refs(value)
    if any(ref not in known for ref in refs):
        return ["EditPlan contains a reference not issued by the host"]
    if len(refs) != len(set(refs)):
        return ["EditPlan contains duplicate references"]
    operations = value["operations"]
    if len(operations) > MAX_OPERATIONS:
        return ["EditPlan exceeds its operation bound"]
    if [item["ordinal"] for item in operations] != list(range(len(operations))):
        return ["EditPlan operations must be ordered with contiguous ordinals"]
    for operation in operations:
        kind = operation["kind"]
        anchor = operation.get("anchor_ref")
        payload = operation.get("payload_ref")
        if kind == "insert" and (anchor is None or payload is None):
            return ["insert operations require anchor and payload references"]
        if kind == "replace" and (anchor is not None or payload is None):
            return ["replace operations require only a payload reference"]
        if kind == "delete" and (anchor is not None or payload is not None):
            return ["delete operations cannot carry anchor or payload references"]
    return []


def admit_edit_plan(
    value: Any,
    *,
    issued_refs: Collection[str] | Mapping[str, Any],
    expected_context_revision: str,
    expected_source_revision: str,
) -> dict[str, Any]:
    errors = validate_edit_plan(
        value,
        issued_refs=issued_refs,
        expected_context_revision=expected_context_revision,
        expected_source_revision=expected_source_revision,
    )
    if errors:
        raise BrainError("EDIT_PLAN_INVALID", 502, errors[0])
    return deepcopy(dict(value))


__all__ = [
    "EDIT_PLAN_CONTRACT",
    "EDIT_PLAN_SCHEMA",
    "EDIT_PLAN_SCHEMA_PATH",
    "EDIT_PLAN_SCHEMA_SHA256",
    "EditPlanError",
    "HOST_REF_RE",
    "admit_edit_plan",
    "validate_edit_plan",
]
