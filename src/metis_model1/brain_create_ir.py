"""Private canonical normalized-IR and cumulative delta proof for Brain CREATE.

The pinned compiler owns the normalized IR.  This module does not parse or
render Metis and never exposes IR through the public protocol.  It gives the
host and the qualification runner one deterministic way to seal an exact
stage and its exact parent-to-child change without relying on lossy structural
fact counts.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from metis_model1.brain_protocol import BrainError, canonical_json, canonical_sha256

CREATE_IR_DELTA_CONTRACT = "metis-brain-create-ir-delta/v1"
MAX_IR_BYTES = 4 * 1024 * 1024
MAX_IR_DEPTH = 128
MAX_IR_NODES = 100_000


@dataclass(frozen=True, slots=True)
class CreateIrStageProof:
    """Hash-only private proof for one exact cumulative compiler stage."""

    ir_sha256: str
    parent_ir_sha256: str | None
    delta_sha256: str
    delta_operation_count: int


def _invalid(message: str) -> BrainError:
    return BrainError("CREATE_IR_INVALID", 502, message)


def _bounded_json(value: Any, *, label: str) -> Any:
    """Return an isolated canonical-JSON value under strict resource bounds."""

    count = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_IR_NODES or depth > MAX_IR_DEPTH:
            raise _invalid(f"{label} exceeds the IR structure bound")
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise _invalid(f"{label} contains a non-string key")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            stack.extend((child, depth + 1) for child in item)
        elif (
            item is None
            or type(item) in {str, int, bool}
            or (type(item) is float and math.isfinite(item))
        ):
            continue
        else:
            raise _invalid(f"{label} contains a non-JSON value")
    try:
        raw = canonical_json(value)
    except BrainError as error:
        raise _invalid(f"{label} is not canonical JSON") from error
    if not raw or len(raw) > MAX_IR_BYTES:
        raise _invalid(f"{label} exceeds the IR byte bound")
    try:
        isolated = json.loads(raw)
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid(f"{label} is invalid") from error

    count = 0
    stack = [(isolated, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_IR_NODES or depth > MAX_IR_DEPTH:
            raise _invalid(f"{label} exceeds the IR structure bound")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise _invalid(f"{label} contains a non-string key")
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in {str, int, float, bool}:
            raise _invalid(f"{label} contains a non-JSON value")
    return isolated


def _pointer(parent: str, token: str) -> str:
    escaped = token.replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}" if parent else f"/{escaped}"


def _node_sha256(value: Any) -> str:
    return canonical_sha256(value)


def _operation(
    *,
    kind: Literal["add", "remove", "replace"],
    path: str,
    before: Any | None,
    after: Any | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": path,
        "before_sha256": None if kind == "add" else _node_sha256(before),
        "after_sha256": None if kind == "remove" else _node_sha256(after),
    }


def _diff(parent: Any, child: Any, *, path: str, output: list[dict[str, Any]]) -> None:
    if type(parent) is not type(child):
        output.append(_operation(kind="replace", path=path, before=parent, after=child))
        return
    if isinstance(parent, dict):
        parent_keys = set(parent)
        child_keys = set(child)
        for key in sorted(parent_keys - child_keys):
            output.append(
                _operation(
                    kind="remove",
                    path=_pointer(path, key),
                    before=parent[key],
                    after=None,
                )
            )
        for key in sorted(child_keys - parent_keys):
            output.append(
                _operation(
                    kind="add",
                    path=_pointer(path, key),
                    before=None,
                    after=child[key],
                )
            )
        for key in sorted(parent_keys & child_keys):
            _diff(parent[key], child[key], path=_pointer(path, key), output=output)
        return
    if isinstance(parent, list):
        # Compiler arrays are source-order semantic collections.  Treating an
        # unequal array as one exact replacement avoids an index-shift diff
        # that could hide reordering as a sequence of unrelated edits.
        if parent != child:
            output.append(_operation(kind="replace", path=path, before=parent, after=child))
        return
    if parent != child:
        output.append(_operation(kind="replace", path=path, before=parent, after=child))


def canonical_ir_delta(parent_ir: Any | None, child_ir: Any) -> dict[str, Any]:
    """Build the exact hash-only delta from an optional parent to one child IR."""

    child = _bounded_json(child_ir, label="child normalized IR")
    child_sha256 = _node_sha256(child)
    if parent_ir is None:
        parent = None
        operations = [
            _operation(kind="add", path="", before=None, after=child),
        ]
        parent_sha256 = None
    else:
        parent = _bounded_json(parent_ir, label="parent normalized IR")
        parent_sha256 = _node_sha256(parent)
        operations: list[dict[str, Any]] = []
        _diff(parent, child, path="", output=operations)
    return {
        "schema_version": 1,
        "contract_id": CREATE_IR_DELTA_CONTRACT,
        "parent_ir_sha256": parent_sha256,
        "child_ir_sha256": child_sha256,
        "operations": operations,
    }


def create_ir_stage_proof(parent_ir: Any | None, child_ir: Any) -> CreateIrStageProof:
    """Seal one private stage using full IR identity and its canonical delta."""

    delta = canonical_ir_delta(parent_ir, child_ir)
    return CreateIrStageProof(
        ir_sha256=delta["child_ir_sha256"],
        parent_ir_sha256=delta["parent_ir_sha256"],
        delta_sha256=canonical_sha256(delta),
        delta_operation_count=len(delta["operations"]),
    )


def verify_ir_stage(
    *,
    parent_ir: Any | None,
    child_ir: Any,
    expected: CreateIrStageProof,
) -> CreateIrStageProof:
    """Return the recomputed proof or fail on any extra, omission or reordering."""

    if type(expected) is not CreateIrStageProof:
        raise _invalid("expected CREATE IR proof is invalid")
    actual = create_ir_stage_proof(parent_ir, child_ir)
    if actual != expected:
        raise BrainError(
            "CREATE_IR_MISMATCH",
            502,
            "normalized IR or cumulative structural delta differs",
        )
    return actual


def isolated_ir(value: Any) -> Any:
    """Return a bounded deep copy for private staging and lifecycle erasure."""

    return deepcopy(_bounded_json(value, label="normalized IR"))


__all__ = [
    "CREATE_IR_DELTA_CONTRACT",
    "MAX_IR_BYTES",
    "MAX_IR_DEPTH",
    "MAX_IR_NODES",
    "CreateIrStageProof",
    "canonical_ir_delta",
    "create_ir_stage_proof",
    "isolated_ir",
    "verify_ir_stage",
]
