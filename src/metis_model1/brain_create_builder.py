"""Pure, private and fail-closed renderer for typed Metis CREATE specs.

The input of this module is assembled by trusted host code after reference
resolution.  It is deliberately not a model/client contract.  The schema has
no escape hatch for source text, snippets, expressions, file-system paths or
templates.  Every Metis token is emitted by a closed renderer and every name
or string passes a grammar-aware validator.

This module performs no I/O apart from loading its tracked JSON Schema at
import time.  It never calls the compiler, a tenant, the network or a model.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

from metis_model1.brain_protocol import canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREATE_ENDPOINT_SPEC_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas/metis-brain-create-endpoint-spec.schema.json"
)
CREATE_ENDPOINT_SPEC_CONTRACT = "metis-brain-create-endpoint-spec/v1"
METIS_LANGUAGE_VERSION = "0.43"

MAX_SPEC_BYTES = 1024 * 1024
MAX_RENDERED_BYTES = 512 * 1024
MAX_TREE_DEPTH = 64
MAX_TREE_NODES = 20_000

# Frozen ten-reference maxima plus deliberately small, explicit headroom.
MAX_CONTEXT_BINDINGS = 12  # observed 11
MAX_TOP_BLOCKS = 12  # observed 11
MAX_VARIANTS = 10  # observed 9
MAX_CONTAINERS = 84  # observed 76
MAX_NESTED_DEPTH = 2  # endpoint -> variant -> named block
MAX_FETCHES = 36  # observed 32
MAX_CLAUSES = 480  # observed 428
MAX_PREDICATES = 512  # observed 451
MAX_OUTPUT_STEPS = 20  # observed 16
MAX_FALLBACKS = 8  # observed 7
MAX_EXPANDED_USES = 16  # observed 12
MAX_ARGUMENT_BINDINGS = 24  # observed 22
MAX_PARAMETERIZED_BLOCKS = 5  # observed 4
MAX_PARAMETERS_PER_BLOCK = 3  # observed 2
MAX_MATRIX_ROWS = 12  # observed 11
MAX_MATRIX_COLUMNS = 3  # observed 2

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}$")
_QUALIFIED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,95})*$")
_DURATION_RE = re.compile(r"^(?:0|[1-9][0-9]{0,8})(?:ms|s|m|h|d|w|M|y)$")
_FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "code",
        "dsl",
        "expression",
        "file",
        "file_path",
        "metis",
        "metis_source",
        "path",
        "raw",
        "raw_source",
        "snippet",
        "source",
        "source_path",
        "source_text",
        "template",
    }
)

_VALUE_KINDS = frozenset({"lit", "bool", "list_ref", "ctx", "input", "arg", "vals"})
_PREDICATE_OPS = frozenset(
    {
        "eq",
        "in",
        "contains",
        "gt",
        "gte",
        "lte",
        "similar",
        "within",
        "exists",
        "match",
        "ids",
        "and",
        "or",
        "group",
    }
)
_COMPARE_SURFACE = {
    "eq": "is",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}
_GUARD_SURFACE = {
    "truthy": "",
    "eq": "is",
    "neq": "is not",
    "in": "in",
    "not_in": "not in",
    "contains": "contains",
    "not_contains": "not contains",
    "contains_any": "contains any",
    "contains_no": "contains no",
    "exists": "exists",
    "empty": "is empty",
    "not_empty": "is not empty",
    "starts_with": "starts with",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}
_CONTAINS_SURFACE = frozenset(
    {
        "contains",
        "not_contains",
        "contains_any",
        "contains_no",
        "has",
        "has_any",
        "has_no",
    }
)
_SCALE_LABELS = frozenset(
    {
        "auto",
        "quick",
        "standard",
        "slow",
        "soon",
        "late",
        "subtle",
        "light",
        "medium",
        "strong",
        "heavy",
    }
)


class CreateBuilderError(ValueError):
    """One bounded failure while admitting or rendering a typed CREATE spec."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CreateBuildStats:
    containers: int
    fetches: int
    clauses: int
    predicates: int
    output_steps: int
    fallbacks: int
    expanded_uses: int
    argument_bindings: int
    parameterized_blocks: int


@dataclass(frozen=True, slots=True)
class RenderedCreateEndpoint:
    """Private renderer result; callers must not expose ``metis_text`` to a model."""

    metis_text: str
    metis_sha256: str
    spec_sha256: str
    stats: CreateBuildStats


def _load_schema() -> dict[str, Any]:
    try:
        value = json.loads(CREATE_ENDPOINT_SPEC_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
    except Exception as error:  # noqa: BLE001 - tracked contract must fail closed
        raise CreateBuilderError(
            "SCHEMA_UNAVAILABLE", "typed CREATE schema is unavailable or invalid"
        ) from error
    if not isinstance(value, dict):
        raise CreateBuilderError("SCHEMA_UNAVAILABLE", "typed CREATE schema is invalid")
    return value


CREATE_ENDPOINT_SPEC_SCHEMA = _load_schema()
_VALIDATOR = Draft202012Validator(CREATE_ENDPOINT_SPEC_SCHEMA)


def _fail(code: str, message: str) -> NoReturn:
    raise CreateBuilderError(code, message)


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("INVALID_SPEC", f"{label} must be an object")
    return value


def _items(value: Any, *, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("INVALID_SPEC", f"{label} must be an array")
    return value


def _identifier(value: Any, *, label: str = "identifier") -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail("INVALID_TOKEN", f"{label} is not a safe Metis identifier")
    return value


def _qualified(value: Any, *, label: str = "qualified identifier") -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 256:
        _fail("INVALID_TOKEN", f"{label} is not a safe Metis qualified identifier")
    if _QUALIFIED_RE.fullmatch(value) is None:
        _fail("INVALID_TOKEN", f"{label} is not a safe Metis qualified identifier")
    return value


def quote_metis_string(value: Any) -> str:
    """Quote one grammar-safe Metis string, failing instead of inventing escapes.

    Metis 0.43's ``STRING`` terminal has no escape production.  Quotes,
    backslashes, line breaks and control characters therefore cannot be made
    lossless by JSON-style escaping and are rejected.
    """

    if not isinstance(value, str):
        _fail("INVALID_STRING", "Metis string must be text")
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CreateBuilderError("INVALID_STRING", "Metis string must be UTF-8") from error
    if len(raw) > 2048:
        _fail("INVALID_STRING", "Metis string exceeds the byte limit")
    if '"' in value or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        _fail("INVALID_STRING", "Metis string contains an unsupported character")
    return f'"{value}"'


def _number(value: Any, *, label: str = "number") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("INVALID_TOKEN", f"{label} must be a finite number")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        _fail("INVALID_TOKEN", f"{label} must be a finite integer")
    integer = int(value)
    if not 0 <= integer <= 1_000_000_000:
        _fail("LIMIT_EXCEEDED", f"{label} exceeds the numeric bound")
    return str(integer)


def _positive(value: Any, *, label: str, minimum: int = 1, maximum: int = 10_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail("INVALID_SPEC", f"{label} is outside its allowed range")
    return value


def _segments(value: Any, *, label: str = "context reference") -> tuple[str, ...]:
    parts = tuple(_identifier(item, label=label) for item in _items(value, label=label))
    if not parts or len(parts) > 16:
        _fail("LIMIT_EXCEEDED", f"{label} has an invalid segment count")
    return parts


def _context_ref(value: Any, *, label: str = "context reference") -> str:
    return "context." + ".".join(_segments(value, label=label))


def _reject_forbidden_keys(value: Any, *, depth: int = 0, count: list[int] | None = None) -> None:
    if count is None:
        count = [0]
    if depth > MAX_TREE_DEPTH:
        _fail("LIMIT_EXCEEDED", "typed CREATE tree is too deep")
    count[0] += 1
    if count[0] > MAX_TREE_NODES:
        _fail("LIMIT_EXCEEDED", "typed CREATE tree has too many nodes")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in _FORBIDDEN_INPUT_KEYS:
                _fail("FORBIDDEN_FIELD", "typed CREATE contains a forbidden field")
            _reject_forbidden_keys(item, depth=depth + 1, count=count)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_forbidden_keys(item, depth=depth + 1, count=count)


def _render_value(value: Any) -> str:
    item = _mapping(value, label="value")
    kind = item.get("kind")
    if kind not in _VALUE_KINDS:
        _fail("INVALID_SPEC", "value kind is not supported")
    if kind == "lit":
        lexical = item.get("lexical")
        literal = item.get("value")
        if lexical == "text":
            return quote_metis_string(literal)
        if lexical == "number":
            return _number(literal, label="literal number")
        if lexical == "duration":
            if not isinstance(literal, str) or _DURATION_RE.fullmatch(literal) is None:
                _fail("INVALID_TOKEN", "duration literal is invalid")
            return literal
        if lexical == "name":
            return _identifier(literal, label="literal name")
        if lexical == "time":
            return "time." + _identifier(literal, label="time member")
        _fail("INVALID_SPEC", "literal lexical form is invalid")
    if kind == "bool":
        literal = item.get("value")
        if not isinstance(literal, bool):
            _fail("INVALID_SPEC", "boolean value is invalid")
        return "true" if literal else "false"
    if kind == "list_ref":
        return "list." + _qualified(item.get("name"), label="list reference")
    if kind == "ctx":
        return _context_ref(item.get("segments"))
    if kind == "input":
        return "$" + _identifier(item.get("name"), label="input reference")
    if kind == "arg":
        return "arg." + _identifier(item.get("name"), label="argument reference")
    values = _items(item.get("items"), label="literal list")
    if not 1 <= len(values) <= 64:
        _fail("LIMIT_EXCEEDED", "literal list has an invalid item count")
    return "[" + ", ".join(quote_metis_string(entry) for entry in values) + "]"


def _render_operand(value: Any) -> str:
    item = _mapping(value, label="guard operand")
    kind = item.get("kind")
    if kind == "ctx":
        if set(item) != {"kind", "segments"}:
            _fail("INVALID_SPEC", "context operand has an invalid field roster")
        return _context_ref(item.get("segments"))
    if set(item) != {"kind", "name"}:
        _fail("INVALID_SPEC", "guard operand has an invalid field roster")
    name = _identifier(item.get("name"), label="guard operand")
    prefix = {
        "input": "$",
        "arg": "arg.",
        "attr": "#",
        "field": "@",
        "time": "time.",
        "name": "",
    }.get(kind)
    if prefix is None:
        _fail("INVALID_SPEC", "guard operand kind is not supported")
    return prefix + name


def _render_guard(value: Any, *, depth: int = 0) -> str:
    if depth > 16:
        _fail("LIMIT_EXCEEDED", "guard nesting is too deep")
    item = _mapping(value, label="guard")
    kind = item.get("kind")
    if kind in {"and", "or"}:
        if set(item) != {"kind", "items"}:
            _fail("INVALID_SPEC", "boolean guard has an invalid field roster")
        members = _items(item.get("items"), label="boolean guard items")
        if not 2 <= len(members) <= 32:
            _fail("LIMIT_EXCEEDED", "boolean guard has an invalid item count")
        rendered = f" {kind} ".join(_render_guard(entry, depth=depth + 1) for entry in members)
        return f"({rendered})"
    if kind == "not":
        if set(item) != {"kind", "item"}:
            _fail("INVALID_SPEC", "not guard has an invalid field roster")
        return "not " + _render_guard(item.get("item"), depth=depth + 1)
    if kind not in {"compare", "size"}:
        _fail("INVALID_SPEC", "guard kind is not supported")
    allowed = {"kind", "left", "op", "right"}
    if not set(item).issubset(allowed) or not {"kind", "left", "op"}.issubset(item):
        _fail("INVALID_SPEC", "comparison guard has an invalid field roster")
    left = _render_operand(item.get("left"))
    if kind == "size":
        left = "size of " + left
    op = item.get("op")
    surface = _GUARD_SURFACE.get(op)
    if surface is None:
        _fail("INVALID_SPEC", "guard operator is not supported")
    unary = op in {"truthy", "exists", "empty", "not_empty"}
    if unary != ("right" not in item):
        _fail("INVALID_SPEC", "guard operator has an invalid arity")
    if unary:
        return left if op == "truthy" else f"{left} {surface}"
    return f"{left} {surface} {_render_value(item.get('right'))}"


def _render_title(value: Any) -> str:
    item = _mapping(value, label="title")
    kind = item.get("kind")
    if kind == "literal":
        if set(item) != {"kind", "value"}:
            _fail("INVALID_SPEC", "literal title has an invalid field roster")
        return quote_metis_string(item.get("value"))
    if kind != "context_parts" or set(item) != {"kind", "parts", "fallback"}:
        _fail("INVALID_SPEC", "title kind is not supported")
    parts = _items(item.get("parts"), label="title parts")
    if not 1 <= len(parts) <= 16:
        _fail("LIMIT_EXCEEDED", "title has an invalid part count")
    rendered: list[str] = []
    for part_value in parts:
        part = _mapping(part_value, label="title part")
        if part.get("kind") == "text" and set(part) == {"kind", "value"}:
            text = part.get("value")
            quote_metis_string(text)
            if any(char in text for char in ("`", "{", "}")):
                _fail("INVALID_STRING", "interpolated title text is unsafe")
            rendered.append(text)
        elif part.get("kind") == "ctx" and set(part) == {"kind", "segments"}:
            rendered.append("{" + _context_ref(part.get("segments")) + "}")
        else:
            _fail("INVALID_SPEC", "title part is invalid")
    fallback = quote_metis_string(item.get("fallback"))
    return "`" + "".join(rendered) + "` else " + fallback


def _boost(value: Any) -> str:
    if isinstance(value, str):
        return _identifier(value, label="boost label")
    return _number(value, label="boost")


def _predicate_suffix(item: Mapping[str, Any]) -> str:
    parts: list[str] = []
    if "boost" in item:
        parts.append("with boost " + _boost(item.get("boost")))
    if "guard" in item:
        parts.append("if " + _render_guard(item.get("guard")))
    return (" " + " ".join(parts)) if parts else ""


def _render_predicate(value: Any, *, depth: int = 0) -> str:
    if depth > 16:
        _fail("LIMIT_EXCEEDED", "predicate nesting is too deep")
    item = _mapping(value, label="predicate")
    op = item.get("op")
    if op not in _PREDICATE_OPS:
        _fail("INVALID_SPEC", "predicate operator is not supported")
    common = {"op", "boost", "guard"}
    if op in {"and", "or"}:
        if set(item) != {"op", "items"}:
            _fail("INVALID_SPEC", "composite predicate has an invalid field roster")
        members = _items(item.get("items"), label="predicate items")
        if not 2 <= len(members) <= 64:
            _fail("LIMIT_EXCEEDED", "composite predicate has an invalid item count")
        result = f" {op} ".join(_render_predicate(entry, depth=depth + 1) for entry in members)
        return f"({result})"
    if op == "group":
        expected = {"op", "strategy", "items"}
        strategy = item.get("strategy")
        if strategy == "best_plus":
            expected.add("coefficient")
        elif strategy == "at_least":
            expected.add("threshold")
        if set(item) != expected:
            _fail("INVALID_SPEC", "group predicate has an invalid field roster")
        members = _items(item.get("items"), label="group alternatives")
        if not 2 <= len(members) <= 64:
            _fail("LIMIT_EXCEEDED", "group predicate has an invalid item count")
        if strategy == "any":
            head = "any of"
        elif strategy == "best":
            head = "only best of"
        elif strategy == "best_plus":
            head = (
                "best plus "
                + _identifier(item.get("coefficient"), label="alternative coefficient")
                + " from alternatives"
            )
        elif strategy == "at_least":
            head = (
                "at least "
                + str(_positive(item.get("threshold"), label="group threshold", maximum=64))
                + " of"
            )
        else:
            _fail("INVALID_SPEC", "group strategy is not supported")
        body = " ".join(_render_predicate(entry, depth=depth + 1) for entry in members)
        return f"{head} {{ {body} }}"
    if op == "ids":
        if not set(item).issubset(common | {"segments"}) or "segments" not in item:
            _fail("INVALID_SPEC", "ids predicate has an invalid field roster")
        return "ids from " + _context_ref(item.get("segments")) + _predicate_suffix(item)
    if op == "similar" and item.get("form") == "record":
        required = {"op", "form", "profile", "target"}
        if not required.issubset(item) or not set(item).issubset(required | {"boost", "guard"}):
            _fail("INVALID_SPEC", "record similarity has an invalid field roster")
        target = _mapping(item.get("target"), label="record similarity target")
        if target.get("kind") != "ctx":
            _fail("INVALID_SPEC", "record similarity requires a context target")
        return (
            "similar "
            + _identifier(item.get("profile"), label="similarity profile")
            + " to "
            + _render_value(target)
            + _predicate_suffix(item)
        )
    if op == "match":
        required = {"op", "field", "value"}
        allowed = required | {"profile", "fuzzy", "min", "boost", "guard"}
        if not required.issubset(item) or not set(item).issubset(allowed):
            _fail("INVALID_SPEC", "match predicate has an invalid field roster")
        result = "match "
        if "profile" in item:
            result += _identifier(item.get("profile"), label="match profile") + " "
        result += "@" + _identifier(item.get("field"), label="match field")
        result += " " + _render_value(item.get("value"))
        if "fuzzy" in item:
            fuzzy = item.get("fuzzy")
            if fuzzy is True:
                result += " fuzzy"
            elif fuzzy == "auto":
                result += " fuzzy auto"
            elif isinstance(fuzzy, int) and not isinstance(fuzzy, bool):
                result += " fuzzy " + str(_positive(fuzzy, label="match fuzzy", maximum=10_000))
            elif fuzzy is not False:
                _fail("INVALID_SPEC", "match fuzzy flag is invalid")
        if "min" in item:
            minimum = item.get("min")
            if (
                isinstance(minimum, bool)
                or not isinstance(minimum, int)
                or not 0 <= minimum <= 10_000
            ):
                _fail("INVALID_SPEC", "match minimum is invalid")
            result += " min " + str(minimum)
        return result + _predicate_suffix(item)
    if op == "exists":
        required = {"op", "field"}
        if not required.issubset(item) or not set(item).issubset(required | {"boost", "guard"}):
            _fail("INVALID_SPEC", "exists predicate has an invalid field roster")
        return (
            "@"
            + _identifier(item.get("field"), label="predicate field")
            + " exists"
            + _predicate_suffix(item)
        )
    if op == "within":
        required = {"op", "field", "amount", "target"}
        if not required.issubset(item) or not set(item).issubset(required | {"boost", "guard"}):
            _fail("INVALID_SPEC", "within predicate has an invalid field roster")
        amount = _mapping(item.get("amount"), label="within amount")
        if amount.get("kind") != "lit" or amount.get("lexical") not in {"number", "duration"}:
            _fail("INVALID_SPEC", "within amount must be a numeric or duration literal")
        return (
            "@"
            + _identifier(item.get("field"), label="predicate field")
            + " within "
            + _render_value(amount)
            + " of "
            + _render_value(item.get("target"))
            + _predicate_suffix(item)
        )
    if op == "contains":
        required = {"op", "field", "value", "membership"}
        if not required.issubset(item) or not set(item).issubset(required | {"boost", "guard"}):
            _fail("INVALID_SPEC", "membership predicate has an invalid field roster")
        membership = item.get("membership")
        if membership not in _CONTAINS_SURFACE:
            _fail("INVALID_SPEC", "membership surface is not supported")
        surface = str(membership).replace("_", " ")
        return (
            "@"
            + _identifier(item.get("field"), label="predicate field")
            + " "
            + surface
            + " "
            + _render_value(item.get("value"))
            + _predicate_suffix(item)
        )
    if op == "similar":
        required = {"op", "form", "field", "value"}
        if item.get("form") != "field" or not required.issubset(item):
            _fail("INVALID_SPEC", "field similarity has an invalid field roster")
        if not set(item).issubset(required | {"fuzzy", "boost", "guard"}):
            _fail("INVALID_SPEC", "field similarity has an invalid field roster")
        result = (
            "@"
            + _identifier(item.get("field"), label="predicate field")
            + " similar to "
            + _render_value(item.get("value"))
        )
        if "fuzzy" in item:
            fuzzy = item.get("fuzzy")
            if fuzzy is True:
                result += " fuzzy"
            elif fuzzy == "auto":
                result += " fuzzy auto"
            elif isinstance(fuzzy, int) and not isinstance(fuzzy, bool):
                result += " fuzzy " + str(
                    _positive(fuzzy, label="similarity fuzzy", maximum=10_000)
                )
            elif fuzzy is not False:
                _fail("INVALID_SPEC", "similarity fuzzy setting is invalid")
        return result + _predicate_suffix(item)
    required = {"op", "field", "value"}
    if not required.issubset(item) or not set(item).issubset(required | {"boost", "guard"}):
        _fail("INVALID_SPEC", "field predicate has an invalid field roster")
    surface = {"in": "in", **_COMPARE_SURFACE}.get(str(op))
    if surface is None:
        _fail("INVALID_SPEC", "field predicate operator is not supported")
    return (
        "@"
        + _identifier(item.get("field"), label="predicate field")
        + " "
        + surface
        + " "
        + _render_value(item.get("value"))
        + _predicate_suffix(item)
    )


def _render_clause(value: Any, *, indent: int) -> list[str]:
    item = _mapping(value, label="clause")
    intent = item.get("intent")
    if intent not in {"include", "exclude", "promote"}:
        _fail("INVALID_SPEC", "clause intent is not supported")
    prefix = " " * indent
    if set(item) == {"intent", "presets"}:
        presets = _items(item.get("presets"), label="preset references")
        rendered = " and ".join(
            "preset." + _qualified(entry, label="preset reference") for entry in presets
        )
        return [f"{prefix}{intent} using {rendered}"]
    if set(item) != {"intent", "where"}:
        _fail("INVALID_SPEC", "clause has an invalid field roster")
    predicates = _items(item.get("where"), label="clause predicates")
    if len(predicates) == 1:
        return [f"{prefix}{intent} where {_render_predicate(predicates[0])}"]
    lines = [f"{prefix}{intent} where {{"]
    lines.extend(" " * (indent + 2) + _render_predicate(predicate) for predicate in predicates)
    lines.append(prefix + "}")
    return lines


def _render_order(value: Any, *, allow_guard: bool) -> str:
    item = _mapping(value, label="order")
    allowed = {"by", "direction", "field", "target", "guard"}
    if not set(item).issubset(allowed):
        _fail("INVALID_SPEC", "order has an invalid field roster")
    by = item.get("by")
    direction = item.get("direction")
    if direction not in {"ascending", "descending"}:
        _fail("INVALID_SPEC", "order direction is not supported")
    if by == "field" and set(item) - {"guard"} == {"by", "direction", "field"}:
        criterion = "@" + _identifier(item.get("field"), label="order field")
    elif by == "similarity" and set(item) - {"guard"} == {"by", "direction", "target"}:
        criterion = "similarity to " + _render_value(item.get("target"))
    elif by in {"relevance", "count"} and set(item) - {"guard"} == {"by", "direction"}:
        criterion = str(by)
    else:
        _fail("INVALID_SPEC", "order criterion has an invalid field roster")
    result = f"{criterion} {direction}"
    if "guard" in item:
        if not allow_guard:
            _fail("INVALID_SPEC", "guarded order is not valid in this position")
        result += " if " + _render_guard(item.get("guard"))
    return result


def _render_group_by(value: Any, *, indent: int) -> list[str]:
    item = _mapping(value, label="group by")
    fields = _items(item.get("fields"), label="group fields")
    field_surface = " and ".join("@" + _identifier(field, label="group field") for field in fields)
    orders = _items(item.get("member_order"), label="group member order")
    member_limit = item.get("member_limit")
    having = item.get("having")
    prefix = " " * indent
    lines: list[str]
    if orders or member_limit is not None:
        lines = [f"{prefix}group by {field_surface} {{"]
        for order in orders:
            lines.append(" " * (indent + 2) + "order by " + _render_order(order, allow_guard=False))
        if member_limit is not None:
            lines.append(
                " " * (indent + 2)
                + "limit to "
                + str(_positive(member_limit, label="group member limit"))
            )
        closing = prefix + "}"
        if having is not None:
            closing += " " + _render_having(having)
        lines.append(closing)
        return lines
    line = f"{prefix}group by {field_surface}"
    if having is not None:
        line += " " + _render_having(having)
    return [line]


def _render_having(value: Any) -> str:
    item = _mapping(value, label="group having")
    if set(item) != {"op", "value"} or item.get("op") not in _COMPARE_SURFACE:
        _fail("INVALID_SPEC", "group having is invalid")
    number = item.get("value")
    if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 10_000:
        _fail("INVALID_SPEC", "group having value is invalid")
    return f"having count {_COMPARE_SURFACE[str(item.get('op'))]} {number}"


def _render_meta_entry(value: Any, *, indent: int, nested: bool = False) -> list[str]:
    item = _mapping(value, label="metadata entry")
    prefix = " " * indent
    kind = item.get("kind")
    if kind == "ui_preset" and set(item) == {"kind", "value"} and not nested:
        return [prefix + "template " + quote_metis_string(item.get("value"))]
    if kind == "entry" and set(item) == {"kind", "key", "value"}:
        return [
            prefix
            + _identifier(item.get("key"), label="metadata key")
            + " "
            + _render_value(item.get("value"))
        ]
    if kind == "object" and set(item) == {"kind", "name", "entries"} and not nested:
        lines = [prefix + _identifier(item.get("name"), label="metadata object") + " {"]
        entries = _items(item.get("entries"), label="metadata object entries")
        for entry in entries:
            if _mapping(entry, label="metadata object entry").get("kind") != "entry":
                _fail("INVALID_SPEC", "metadata objects may contain only typed key/value entries")
            lines.extend(_render_meta_entry(entry, indent=indent + 2, nested=True))
        lines.append(prefix + "}")
        return lines
    _fail("INVALID_SPEC", "metadata entry is invalid")


def _render_presentation(value: Any, *, indent: int) -> list[str]:
    item = _mapping(value, label="presentation")
    lines: list[str] = []
    prefix = " " * indent
    pinned = item.get("pinned")
    if pinned is not None:
        lines.append(prefix + "pinned = " + _render_value(pinned))
    view_all = item.get("view_all")
    if view_all is not None:
        target = _mapping(view_all, label="view-all target")
        kind = target.get("kind")
        if kind == "endpoint":
            rendered = "endpoint." + _qualified(target.get("name"), label="endpoint reference")
        elif kind == "arg":
            rendered = "arg." + _identifier(target.get("name"), label="view-all argument")
        else:
            _fail("INVALID_SPEC", "view-all target is invalid")
        lines.append(prefix + "view-all using " + rendered)
    entries = _items(item.get("meta"), label="metadata entries")
    if entries:
        head = "meta per item" if item.get("meta_per_item") else "meta"
        if len(entries) == 1:
            entry_lines = _render_meta_entry(entries[0], indent=0)
            if len(entry_lines) == 1:
                lines.append(prefix + head + " " + entry_lines[0].lstrip())
                return lines
        lines.append(prefix + head + " {")
        for entry in entries:
            lines.extend(_render_meta_entry(entry, indent=indent + 2))
        lines.append(prefix + "}")
    return lines


def _render_output_step(value: Any) -> str:
    item = _mapping(value, label="output step")
    kind = item.get("kind")
    if kind == "deduplicate" and set(item).issubset({"kind", "field"}):
        suffix = ""
        if "field" in item:
            suffix = " using @" + _identifier(item.get("field"), label="deduplicate field")
        return "deduplicate" + suffix
    if kind == "max" and set(item) == {"kind", "count"}:
        return "limit to " + str(_positive(item.get("count"), label="output maximum"))
    if kind == "shuffle" and set(item) == {"kind"}:
        return "shuffle"
    if kind == "limit" and set(item) == {"kind", "field", "count", "op", "value"}:
        op = item.get("op")
        if op not in _COMPARE_SURFACE:
            _fail("INVALID_SPEC", "conditional limit operator is invalid")
        return (
            "limit to "
            + str(_positive(item.get("count"), label="conditional output limit"))
            + " where @"
            + _identifier(item.get("field"), label="conditional limit field")
            + " "
            + _COMPARE_SURFACE[str(op)]
            + " "
            + _render_value(item.get("value"))
        )
    if kind == "limit_per" and set(item) == {"kind", "field", "count"}:
        return (
            "limit to "
            + str(_positive(item.get("count"), label="per-field output limit"))
            + " per @"
            + _identifier(item.get("field"), label="per-field limit field")
        )
    if kind == "order" and set(item) == {"kind", "orders"}:
        orders = _items(item.get("orders"), label="output orders")
        if not orders:
            _fail("INVALID_SPEC", "output order must not be empty")
        return "order by " + " then by ".join(
            _render_order(order, allow_guard=False) for order in orders
        )
    _fail("INVALID_SPEC", "output step has an invalid field roster")


def _render_fallback(value: Any) -> str:
    item = _mapping(value, label="fallback")
    kind = item.get("kind")
    mode = item.get("mode")
    if mode not in {"substitute", "append"}:
        _fail("INVALID_SPEC", "fallback mode is invalid")
    trigger = item.get("trigger")
    threshold = item.get("threshold")
    if kind == "direct":
        allowed = {"kind", "target", "target_kind", "trigger", "threshold", "mode"}
        if not set(item).issubset(allowed) or "target_kind" not in item:
            _fail("INVALID_SPEC", "direct fallback has an invalid field roster")
        target_kind = item.get("target_kind")
        target = _qualified(item.get("target"), label="fallback target")
        if target_kind == "block":
            target_surface = "block." + target
        elif target_kind == "endpoint":
            target_surface = "endpoint." + target
        else:
            _fail("INVALID_SPEC", "direct fallback target kind is invalid")
        trigger_surface = {
            "empty": "when empty",
            "error": "when on error",
            "no_valid_block": "when no valid block",
        }.get(trigger)
        if trigger == "below":
            trigger_surface = "when below " + str(_positive(threshold, label="fallback threshold"))
        elif threshold is not None:
            _fail("INVALID_SPEC", "fallback threshold is not valid for this trigger")
        if trigger_surface is None:
            _fail("INVALID_SPEC", "direct fallback trigger is invalid")
        return f"fallback to {target_surface} {trigger_surface} {mode}"
    if kind == "materialized":
        allowed = {"kind", "target", "trigger", "threshold", "mode"}
        if not set(item).issubset(allowed) or "target_kind" in item:
            _fail("INVALID_SPEC", "materialized fallback has an invalid field roster")
        target = _qualified(item.get("target"), label="materialized fallback target")
        if trigger in {"page_blocks_below", "on_error"} and mode != "substitute":
            _fail(
                "INVALID_SPEC",
                "page-block and on-error materialized fallbacks require substitute",
            )
        if trigger == "on_error":
            if threshold is not None:
                _fail("INVALID_SPEC", "on-error fallback cannot have a threshold")
            trigger_surface = "on error"
        else:
            prefix = {
                "page_blocks_below": "page blocks below",
                "nested_flat_items_below": "nested flat items below",
            }.get(trigger)
            if prefix is None:
                _fail("INVALID_SPEC", "materialized fallback trigger is invalid")
            trigger_surface = (
                prefix + " " + str(_positive(threshold, label="materialized fallback threshold"))
            )
        return f"fallback to materialized.{target} when {trigger_surface} {mode}"
    _fail("INVALID_SPEC", "fallback kind is invalid")


def _render_return(value: Any, *, indent: int) -> str:
    item = _mapping(value, label="return flow")
    projection = item.get("projection")
    if projection == "default":
        result = "return response"
    else:
        result = "return response." + _identifier(projection, label="response projection")
    for step in _items(item.get("steps"), label="output steps"):
        result += " -> " + _render_output_step(step)
    for fallback in _items(item.get("fallbacks"), label="fallbacks"):
        result += " " + _render_fallback(fallback)
    return " " * indent + result


class _Renderer:
    def __init__(self) -> None:
        self.containers = 0
        self.fetches = 0
        self.clauses = 0
        self.predicates = 0
        self.output_steps = 0
        self.fallbacks = 0
        self.expanded_uses = 0
        self.argument_bindings = 0
        self.parameterized_blocks = 0

    def _count_predicate(self, value: Any) -> None:
        self.predicates += 1
        if self.predicates > MAX_PREDICATES:
            _fail("LIMIT_EXCEEDED", "predicate count exceeds the CREATE bound")
        item = _mapping(value, label="predicate")
        if item.get("op") in {"and", "or", "group"}:
            for child in _items(item.get("items"), label="predicate items"):
                self._count_predicate(child)

    def _count_return(self, value: Any) -> None:
        item = _mapping(value, label="return flow")
        self.output_steps += len(_items(item.get("steps"), label="output steps"))
        self.fallbacks += len(_items(item.get("fallbacks"), label="fallbacks"))
        if self.output_steps > MAX_OUTPUT_STEPS:
            _fail("LIMIT_EXCEEDED", "output-step count exceeds the CREATE bound")
        if self.fallbacks > MAX_FALLBACKS:
            _fail("LIMIT_EXCEEDED", "fallback count exceeds the CREATE bound")

    def render_fetch(self, value: Any, *, indent: int) -> list[str]:
        self.fetches += 1
        if self.fetches > MAX_FETCHES:
            _fail("LIMIT_EXCEEDED", "fetch count exceeds the CREATE bound")
        item = _mapping(value, label="fetch")
        cardinality = _mapping(item.get("cardinality"), label="fetch cardinality")
        mode = cardinality.get("mode")
        result = "take"
        if mode == "none" and set(cardinality) == {"mode"}:
            pass
        elif mode == "total" and set(cardinality) == {"mode", "value"}:
            result += " " + str(_positive(cardinality.get("value"), label="fetch total"))
        elif mode == "page" and set(cardinality) == {"mode"}:
            result += " page"
        elif mode == "page_default" and set(cardinality) == {"mode", "value"}:
            result += " page default " + str(
                _positive(cardinality.get("value"), label="fetch page default")
            )
        else:
            _fail("INVALID_SPEC", "fetch cardinality is invalid")
        factor = item.get("over_fetch")
        if factor is not None:
            if mode != "total":
                _fail("INVALID_SPEC", "over-fetch requires total fetch cardinality")
            result += " * " + str(
                _positive(factor, label="over-fetch factor", minimum=2, maximum=16)
            )
        origin = _mapping(item.get("from"), label="fetch origin")
        if origin.get("kind") == "catalog" and set(origin) == {"kind", "catalog"}:
            result += " from @" + _identifier(origin.get("catalog"), label="catalog reference")
        elif origin.get("kind") == "context" and set(origin) == {"kind", "segments"}:
            result += " from " + _context_ref(origin.get("segments"))
        else:
            _fail("INVALID_SPEC", "fetch origin is invalid")
        alias = item.get("alias")
        if alias is not None:
            result += " as " + _identifier(alias, label="fetch alias")
        title = item.get("title")
        if title is not None:
            result += " " + _render_title(title)
        activation = item.get("activation")
        if activation is not None:
            result += " if " + _render_guard(activation)
        clauses = _items(item.get("clauses"), label="fetch clauses")
        self.clauses += len(clauses)
        if self.clauses > MAX_CLAUSES:
            _fail("LIMIT_EXCEEDED", "clause count exceeds the CREATE bound")
        for clause in clauses:
            clause_item = _mapping(clause, label="clause")
            if "where" in clause_item:
                for predicate in _items(clause_item.get("where"), label="clause predicates"):
                    self._count_predicate(predicate)
        presentation = _render_presentation(item.get("presentation"), indent=indent + 2)
        group_by = item.get("group_by")
        orders = _items(item.get("order"), label="fetch order")
        output = item.get("output")
        if output is not None:
            self._count_return(output)
        body: list[str] = []
        for clause in clauses:
            body.extend(_render_clause(clause, indent=indent + 2))
        if group_by is not None:
            body.extend(_render_group_by(group_by, indent=indent + 2))
        for order in orders:
            body.append(" " * (indent + 2) + "order by " + _render_order(order, allow_guard=True))
        body.extend(presentation)
        if output is not None:
            body.append(_render_return(output, indent=indent + 2))
        prefix = " " * indent
        if not body:
            return [prefix + result]
        return [prefix + result + " {", *body, prefix + "}"]

    def _render_parameters(self, value: Any) -> str:
        parameters = _items(value, label="block parameters")
        if not parameters:
            return ""
        self.parameterized_blocks += 1
        if self.parameterized_blocks > MAX_PARAMETERIZED_BLOCKS:
            _fail("LIMIT_EXCEEDED", "parameterized-block count exceeds the CREATE bound")
        if len(parameters) > MAX_PARAMETERS_PER_BLOCK:
            _fail("LIMIT_EXCEEDED", "block parameter count exceeds the CREATE bound")
        names: set[str] = set()
        rendered: list[str] = []
        for parameter_value in parameters:
            parameter = _mapping(parameter_value, label="block parameter")
            name = _identifier(parameter.get("name"), label="block parameter")
            if name in names:
                _fail("INVALID_SPEC", "block parameter names must be unique")
            names.add(name)
            required = parameter.get("required")
            if not isinstance(required, bool):
                _fail("INVALID_SPEC", "block parameter required flag is invalid")
            default = parameter.get("default")
            if required and default is not None:
                _fail("INVALID_SPEC", "required block parameter cannot have a default")
            part = name + ("!" if required else "")
            parameter_type = parameter.get("type")
            if parameter_type is not None:
                part += " " + _identifier(parameter_type, label="block parameter type")
            if default is not None:
                part += " = " + _render_value(default)
            rendered.append(part)
        return "(" + ", ".join(rendered) + ")"

    def _render_use_instance(self, value: Any, *, block_override: str | None = None) -> str:
        item = _mapping(value, label="block use")
        block = block_override or _identifier(item.get("block"), label="block use target")
        args = _items(item.get("args", []), label="block use arguments")
        rendered = block
        if args:
            names: set[str] = set()
            bindings: list[str] = []
            for argument_value in args:
                argument = _mapping(argument_value, label="block argument")
                name = _identifier(argument.get("name"), label="block argument")
                if name in names:
                    _fail("INVALID_SPEC", "block argument names must be unique")
                names.add(name)
                bindings.append(name + " = " + _render_value(argument.get("value")))
            self.argument_bindings += len(bindings)
            if self.argument_bindings > MAX_ARGUMENT_BINDINGS:
                _fail("LIMIT_EXCEEDED", "argument-binding count exceeds the CREATE bound")
            rendered += "(" + ", ".join(bindings) + ")"
        alias = item.get("alias")
        if alias is not None:
            rendered += " as " + _identifier(alias, label="block use alias")
        title = item.get("title")
        if title is not None:
            rendered += " " + _render_title(title)
        return rendered

    def render_uses(self, value: Any, *, indent: int) -> list[str]:
        uses = _items(value, label="block uses")
        direct: list[str] = []
        instances: list[str] = []
        prefix = " " * indent
        for use_value in uses:
            use = _mapping(use_value, label="block use")
            kind = use.get("kind")
            block = _identifier(use.get("block"), label="block use target")
            if kind == "direct":
                if not set(use).issubset({"kind", "block", "title"}):
                    _fail("INVALID_SPEC", "direct block use has an invalid field roster")
                rendered = "use block." + block
                if "title" in use:
                    rendered += " " + _render_title(use.get("title"))
                direct.append(prefix + rendered)
                self.expanded_uses += 1
            elif kind == "instance":
                if "rows" in use:
                    _fail("INVALID_SPEC", "block instance cannot contain matrix rows")
                instances.append(self._render_use_instance(use))
                self.expanded_uses += 1
            elif kind == "matrix":
                if set(use) != {"kind", "block", "rows"}:
                    _fail("INVALID_SPEC", "matrix block use has an invalid field roster")
                rows = _items(use.get("rows"), label="matrix rows")
                if not 1 <= len(rows) <= MAX_MATRIX_ROWS:
                    _fail("LIMIT_EXCEEDED", "matrix row count exceeds the CREATE bound")
                column_roster: tuple[str, ...] | None = None
                for row_value in rows:
                    row = _mapping(row_value, label="matrix row")
                    args = _items(row.get("args"), label="matrix bindings")
                    if not 1 <= len(args) <= MAX_MATRIX_COLUMNS:
                        _fail("LIMIT_EXCEEDED", "matrix width exceeds the CREATE bound")
                    names = tuple(
                        _identifier(
                            _mapping(argument, label="matrix binding").get("name"),
                            label="matrix parameter",
                        )
                        for argument in args
                    )
                    if len(set(names)) != len(names):
                        _fail("INVALID_SPEC", "matrix parameter names must be unique")
                    if column_roster is None:
                        column_roster = names
                    elif names != column_roster:
                        _fail("INVALID_SPEC", "matrix rows must bind the same ordered columns")
                    expanded = {
                        "kind": "instance",
                        "block": block,
                        "alias": row.get("alias"),
                        "args": list(args),
                    }
                    if row.get("title") is not None:
                        expanded["title"] = row.get("title")
                    instances.append(self._render_use_instance(expanded))
                    self.expanded_uses += 1
            else:
                _fail("INVALID_SPEC", "block use kind is invalid")
            if self.expanded_uses > MAX_EXPANDED_USES:
                _fail("LIMIT_EXCEEDED", "expanded-use count exceeds the CREATE bound")
        if not instances:
            return direct
        if len(instances) == 1:
            direct.append(prefix + "use blocks " + instances[0])
            return direct
        direct.append(prefix + "use blocks {")
        direct.extend(" " * (indent + 2) + instance for instance in instances)
        direct.append(prefix + "}")
        return direct

    def render_container(
        self,
        value: Any,
        *,
        indent: int,
        variant: bool,
        nested_depth: int,
    ) -> list[str]:
        self.containers += 1
        if self.containers > MAX_CONTAINERS:
            _fail("LIMIT_EXCEEDED", "container count exceeds the CREATE bound")
        if nested_depth > MAX_NESTED_DEPTH:
            _fail("LIMIT_EXCEEDED", "container nesting exceeds the CREATE bound")
        item = _mapping(value, label="container")
        name = _identifier(item.get("name"), label="container name")
        prefix = " " * indent
        if variant and item.get("empty") is True:
            if any(
                (
                    item.get("fetches"),
                    item.get("blocks"),
                    item.get("uses"),
                    item.get("output"),
                    _items(item.get("presentation", {}).get("meta", []), label="metadata"),
                )
            ):
                _fail("INVALID_SPEC", "empty variant cannot contain executable members")
            head = "variant " + name
            if item.get("title") is not None:
                head += " " + _render_title(item.get("title"))
            if item.get("activation") is not None:
                head += " if " + _render_guard(item.get("activation"))
            return [prefix + head + " empty"]
        head = ("variant " if variant else "block ") + name
        if not variant:
            head += self._render_parameters(item.get("parameters"))
        if item.get("title") is not None:
            head += " " + _render_title(item.get("title"))
        if item.get("activation") is not None:
            head += " if " + _render_guard(item.get("activation"))
        lines = [prefix + head + " {"]
        lines.extend(_render_presentation(item.get("presentation"), indent=indent + 2))
        for fetch in _items(item.get("fetches"), label="container fetches"):
            lines.extend(self.render_fetch(fetch, indent=indent + 2))
        nested = _items(item.get("blocks"), label="nested blocks")
        if nested and not variant:
            _fail("INVALID_SPEC", "named blocks cannot contain nested named blocks")
        for block in nested:
            lines.extend(
                self.render_container(
                    block,
                    indent=indent + 2,
                    variant=False,
                    nested_depth=nested_depth + 1,
                )
            )
        lines.extend(self.render_uses(item.get("uses"), indent=indent + 2))
        output = item.get("output")
        if output is not None:
            self._count_return(output)
            lines.append(_render_return(output, indent=indent + 2))
        lines.append(prefix + "}")
        return lines

    def stats(self) -> CreateBuildStats:
        return CreateBuildStats(
            containers=self.containers,
            fetches=self.fetches,
            clauses=self.clauses,
            predicates=self.predicates,
            output_steps=self.output_steps,
            fallbacks=self.fallbacks,
            expanded_uses=self.expanded_uses,
            argument_bindings=self.argument_bindings,
            parameterized_blocks=self.parameterized_blocks,
        )


def _render_scale_ref(value: Any, *, label: str) -> str:
    item = _mapping(value, label=label)
    if item.get("kind") != "lit" or set(item) != {"kind", "lexical", "value"}:
        _fail("INVALID_SPEC", f"{label} is invalid")
    lexical = item.get("lexical")
    literal = item.get("value")
    if lexical == "duration":
        return _render_value(item)
    if lexical == "number":
        return _render_value(item)
    if lexical == "text" and literal in _SCALE_LABELS:
        return str(literal)
    _fail("INVALID_SPEC", f"{label} must be a closed scale label, number or duration")


def _render_params(value: Any, *, indent: int) -> list[str]:
    item = _mapping(value, label="endpoint params")
    entries: list[str] = []
    timeout = item.get("timeout")
    if timeout is not None:
        timeout_item = _mapping(timeout, label="timeout")
        if set(timeout_item) != {"kind", "value"}:
            _fail("INVALID_SPEC", "timeout has an invalid field roster")
        if timeout_item.get("kind") == "duration":
            value_text = timeout_item.get("value")
            if not isinstance(value_text, str) or _DURATION_RE.fullmatch(value_text) is None:
                _fail("INVALID_SPEC", "timeout duration is invalid")
            rendered = value_text
        elif timeout_item.get("kind") == "scale":
            value_text = timeout_item.get("value")
            if value_text not in _SCALE_LABELS:
                _fail("INVALID_SPEC", "timeout scale is invalid")
            rendered = str(value_text)
        else:
            _fail("INVALID_SPEC", "timeout kind is invalid")
        entries.append("timeout " + rendered)
    expires = item.get("expires")
    if expires is not None:
        expires_item = _mapping(expires, label="expires")
        result = "expires " + _render_scale_ref(expires_item.get("value"), label="expiry")
        guard = expires_item.get("guard")
        otherwise = expires_item.get("else")
        if guard is None and otherwise is not None:
            _fail("INVALID_SPEC", "expiry else requires a guard")
        if guard is not None:
            result += " if " + _render_guard(guard)
            if otherwise is not None:
                result += " else " + _render_scale_ref(otherwise, label="expiry else")
        entries.append(result)
    paginate = item.get("paginate")
    if paginate is not None:
        if paginate not in {"snapshot", "windowed"}:
            _fail("INVALID_SPEC", "pagination mode is invalid")
        entries.append("paginate " + str(paginate))
    if not entries:
        return []
    prefix = " " * indent
    if len(entries) == 1:
        return [prefix + "params " + entries[0]]
    return [prefix + "params {", *(" " * (indent + 2) + entry for entry in entries), prefix + "}"]


def _render_inputs(value: Any, *, indent: int) -> list[str]:
    inputs = _items(value, label="endpoint inputs")
    if not inputs:
        return []
    names: set[str] = set()
    rendered: list[str] = []
    for input_value in inputs:
        item = _mapping(input_value, label="endpoint input")
        name = _identifier(item.get("name"), label="input name")
        if name in names:
            _fail("INVALID_SPEC", "input names must be unique")
        names.add(name)
        line = name
        if item.get("required") is True:
            line += "!"
        elif item.get("required") is not False:
            _fail("INVALID_SPEC", "input required flag is invalid")
        line += " " + _identifier(item.get("type"), label="input type")
        if item.get("not_empty") is True:
            line += " not empty"
        elif item.get("not_empty") is not False:
            _fail("INVALID_SPEC", "input not-empty flag is invalid")
        if item.get("default") is not None:
            line += " default " + _render_value(item.get("default"))
        rendered.append(line)
    prefix = " " * indent
    if len(rendered) == 1:
        return [prefix + "input " + rendered[0]]
    return [prefix + "inputs {", *(" " * (indent + 2) + line for line in rendered), prefix + "}"]


def _render_attributes(value: Any, *, indent: int) -> list[str]:
    attributes = _items(value, label="attributes")
    if not attributes:
        return []
    names: set[str] = set()
    rendered: list[str] = []
    for attribute_value in attributes:
        item = _mapping(attribute_value, label="attribute")
        name = _identifier(item.get("name"), label="attribute name")
        if name in names:
            _fail("INVALID_SPEC", "attribute names must be unique")
        names.add(name)
        rendered.append(name + " = " + _render_guard(item.get("guard")))
    prefix = " " * indent
    if len(rendered) == 1:
        return [prefix + "attributes " + rendered[0]]
    return [
        prefix + "attributes {",
        *(" " * (indent + 2) + line for line in rendered),
        prefix + "}",
    ]


def _render_pipeline(value: Any, *, direction: str, indent: int) -> list[str]:
    steps = _items(value, label=f"{direction} pipeline")
    if not steps:
        return []
    rendered = " -> ".join(
        "transformer." + _identifier(step, label="pipeline transformer") for step in steps
    )
    return [" " * indent + direction + " -> " + rendered]


def _render_inheritance(value: Any, *, direction: str, indent: int) -> list[str]:
    item = _mapping(value, label="pipeline inheritance")
    if direction not in {"in", "out"}:
        raise AssertionError("pipeline inheritance direction is invalid")
    lines: list[str] = []
    key = "without_input" if direction == "in" else "without_output"
    for target in _items(item.get(key), label=f"{direction} inheritance opt-outs"):
        lines.append(
            " " * indent
            + "without "
            + direction
            + "."
            + _identifier(target, label="inherited transformer")
        )
    return lines


def render_create_endpoint(spec: Any) -> RenderedCreateEndpoint:
    """Validate and deterministically render one private host-resolved spec."""

    _reject_forbidden_keys(spec)
    try:
        spec_bytes = canonical_json(spec)
    except Exception as error:  # canonical helper uses a public protocol error
        raise CreateBuilderError(
            "INVALID_SPEC", "typed CREATE spec is not canonical JSON"
        ) from error
    if len(spec_bytes) > MAX_SPEC_BYTES:
        _fail("LIMIT_EXCEEDED", "typed CREATE spec exceeds the byte limit")
    errors = sorted(_VALIDATOR.iter_errors(spec), key=lambda error: list(error.absolute_path))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "root"
        _fail("INVALID_SPEC", f"typed CREATE schema violation at {location}")
    root = _mapping(spec, label="typed CREATE spec")
    endpoint = _mapping(root.get("endpoint"), label="endpoint")
    renderer = _Renderer()
    name = _qualified(endpoint.get("name"), label="endpoint name")
    head = "endpoint " + name
    reference = endpoint.get("reference")
    if reference is not None:
        head += " as " + quote_metis_string(reference)
    lines = [f"metis {METIS_LANGUAGE_VERSION}", "", head + " {"]
    lines.extend(_render_params(endpoint.get("params"), indent=2))
    lines.extend(_render_inputs(endpoint.get("inputs"), indent=2))
    lines.extend(_render_pipeline(endpoint.get("input_pipeline"), direction="in", indent=2))
    lines.extend(_render_inheritance(endpoint.get("inheritance"), direction="in", indent=2))
    if endpoint.get("needs_time") is True:
        lines.append("  needs time")
    elif endpoint.get("needs_time") is not False:
        _fail("INVALID_SPEC", "needs-time flag is invalid")
    context = _items(endpoint.get("context"), label="context bindings")
    if len(context) > MAX_CONTEXT_BINDINGS:
        _fail("LIMIT_EXCEEDED", "context-binding count exceeds the CREATE bound")
    if context:
        context_names: set[str] = set()
        lines.append("  context {")
        for binding_value in context:
            binding = _mapping(binding_value, label="context binding")
            binding_name = _identifier(binding.get("name"), label="context binding name")
            if binding_name in context_names:
                _fail("INVALID_SPEC", "context binding names must be unique")
            context_names.add(binding_name)
            if binding.get("kind") == "fetch" and set(binding) == {"kind", "name", "fetch"}:
                fetch_lines = renderer.render_fetch(binding.get("fetch"), indent=0)
                first, *rest = fetch_lines
                lines.append("    " + binding_name + " = " + first)
                lines.extend("    " + line for line in rest)
            elif binding.get("kind") == "transform" and set(binding) == {
                "kind",
                "name",
                "value",
                "transformer",
            }:
                lines.append(
                    "    "
                    + binding_name
                    + " = "
                    + _render_value(binding.get("value"))
                    + " -> transformer."
                    + _identifier(binding.get("transformer"), label="context transformer")
                )
            else:
                _fail("INVALID_SPEC", "context binding is invalid")
        lines.append("  }")
    lines.extend(_render_attributes(endpoint.get("attributes"), indent=2))
    blocks = _items(endpoint.get("blocks"), label="top-level blocks")
    if len(blocks) > MAX_TOP_BLOCKS:
        _fail("LIMIT_EXCEEDED", "top-level block count exceeds the CREATE bound")
    block_names: set[str] = set()
    for block in blocks:
        block_name = _identifier(_mapping(block, label="block").get("name"), label="block name")
        if block_name in block_names:
            _fail("INVALID_SPEC", "top-level block names must be unique")
        block_names.add(block_name)
        lines.extend(renderer.render_container(block, indent=2, variant=False, nested_depth=1))
    variants = _items(endpoint.get("variants"), label="variants")
    if len(variants) > MAX_VARIANTS:
        _fail("LIMIT_EXCEEDED", "variant count exceeds the CREATE bound")
    variant_names: set[str] = set()
    for variant in variants:
        variant_name = _identifier(
            _mapping(variant, label="variant").get("name"), label="variant name"
        )
        if variant_name in variant_names:
            _fail("INVALID_SPEC", "variant names must be unique")
        variant_names.add(variant_name)
        lines.extend(renderer.render_container(variant, indent=2, variant=True, nested_depth=1))
    lines.extend(_render_pipeline(endpoint.get("output_pipeline"), direction="out", indent=2))
    lines.extend(_render_inheritance(endpoint.get("inheritance"), direction="out", indent=2))
    output = endpoint.get("output")
    if output is not None:
        renderer._count_return(output)
        lines.append(_render_return(output, indent=2))
    lines.append("}")
    text = "\n".join(lines) + "\n"
    text_bytes = text.encode("utf-8")
    if len(text_bytes) > MAX_RENDERED_BYTES:
        _fail("LIMIT_EXCEEDED", "rendered Metis exceeds the byte limit")
    return RenderedCreateEndpoint(
        metis_text=text,
        metis_sha256=_sha256(text_bytes),
        spec_sha256=_sha256(spec_bytes),
        stats=renderer.stats(),
    )


__all__ = [
    "CREATE_ENDPOINT_SPEC_CONTRACT",
    "CREATE_ENDPOINT_SPEC_SCHEMA",
    "CREATE_ENDPOINT_SPEC_SCHEMA_PATH",
    "CreateBuildStats",
    "CreateBuilderError",
    "RenderedCreateEndpoint",
    "quote_metis_string",
    "render_create_endpoint",
]
