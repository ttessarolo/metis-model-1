"""Fail-closed adjudication of finite catalog predicates in Brain candidates.

The model may choose endpoint structure, but it may not choose a different
finite domain or cardinality operator than the reviewed retrieval result.  The
scanner is intentionally smaller than the Metis parser: it recognizes only the
literal-bearing condition surfaces which Brain currently authorizes and sends
everything else through bounded repair before the pinned compiler can run.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from metis_model1.brain_protocol import MAX_SOURCE_BYTES, BrainError

MAX_PREDICATES = 256
MAX_LITERAL_BYTES = 4096
_IDENTIFIER_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENTIFIER_CONTINUATION = _IDENTIFIER_START | frozenset("0123456789.-")
_UNSUPPORTED_FIELD_OPERATORS = (
    "contains",
    "exists",
    "matches",
    "nearest",
    "not",
    "similar",
    "starts",
    "within",
)
_FINITE_DOMAIN_KINDS = frozenset({"enum", "inline", "list"})
_CONDITION_BOUNDARY_WORDS = frozenset(
    {
        "exclude",
        "group",
        "having",
        "include",
        "order",
        "promote",
        "return",
        "skip",
        "take",
        "with",
    }
)


@dataclass(frozen=True)
class CandidateGroundingCheck:
    """One bounded, public-safe result of candidate grounding adjudication."""

    ok: bool
    diagnostic: dict[str, Any] | None = None


@dataclass(frozen=True)
class _Predicate:
    field: str
    operator: str
    literals: tuple[str, ...]


class _ScanFailure(ValueError):
    pass


def _word_at(source: str, index: int, word: str) -> bool:
    end = index + len(word)
    return (
        source.startswith(word, index)
        and (index == 0 or source[index - 1] not in _IDENTIFIER_CONTINUATION)
        and (end == len(source) or source[end] not in _IDENTIFIER_CONTINUATION)
    )


def _skip_trivia(source: str, index: int) -> int:
    """Skip whitespace and comments wherever Metis permits token trivia."""

    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise _ScanFailure("unterminated block comment")
            index = end + 2
            continue
        break
    return index


def _scan_string(source: str, start: int) -> tuple[str, int]:
    if start >= len(source) or source[start] != '"':
        raise _ScanFailure("quoted literal is required")
    index = start + 1
    chars: list[str] = []
    while index < len(source):
        char = source[index]
        if char == '"':
            literal = "".join(chars)
            if not literal:
                raise _ScanFailure("empty literal is not authorized")
            if len(literal.encode("utf-8")) > MAX_LITERAL_BYTES:
                raise _ScanFailure("literal is too large")
            return literal, index + 1
        if char == "\\":
            index += 1
            if index >= len(source):
                raise _ScanFailure("unterminated escape")
            escaped = source[index]
            simple = {
                '"': '"',
                "\\": "\\",
                "/": "/",
                "b": "\b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
            }
            if escaped in simple:
                chars.append(simple[escaped])
                index += 1
                continue
            if escaped == "u" and index + 4 < len(source):
                digits = source[index + 1 : index + 5]
                if all(digit in "0123456789abcdefABCDEF" for digit in digits):
                    codepoint = int(digits, 16)
                    if 0xD800 <= codepoint <= 0xDFFF:
                        raise _ScanFailure("surrogate escapes are not supported")
                    chars.append(chr(codepoint))
                    index += 5
                    continue
            raise _ScanFailure("invalid string escape")
        if char in "\r\n" or ord(char) < 0x20:
            raise _ScanFailure("control character in quoted literal")
        chars.append(char)
        index += 1
    raise _ScanFailure("unterminated quoted literal")


def _scan_list(source: str, start: int) -> tuple[tuple[str, ...], int]:
    if start >= len(source) or source[start] != "[":
        raise _ScanFailure("quoted literal list is required")
    index = _skip_trivia(source, start + 1)
    literals: list[str] = []
    if index < len(source) and source[index] == "]":
        raise _ScanFailure("empty literal list is not authorized")
    while True:
        literal, index = _scan_string(source, index)
        literals.append(literal)
        if len(literals) > MAX_PREDICATES:
            raise _ScanFailure("too many finite literals")
        index = _skip_trivia(source, index)
        if index < len(source) and source[index] == "]":
            if len(literals) != len(set(literals)):
                raise _ScanFailure("duplicate literal in membership list")
            return tuple(sorted(literals)), index + 1
        if index >= len(source) or source[index] != ",":
            raise _ScanFailure("literal list requires commas")
        index = _skip_trivia(source, index + 1)


def _word_after(source: str, index: int) -> tuple[str | None, int]:
    index = _skip_trivia(source, index)
    if index >= len(source) or source[index] not in _IDENTIFIER_START:
        return None, index
    end = index + 1
    while end < len(source) and source[end] in _IDENTIFIER_CONTINUATION:
        end += 1
    return source[index:end], end


def _unsupported_condition_starts_at(source: str, index: int) -> bool:
    """Recognize non-field condition forms without rejecting unrelated keywords."""

    if _word_at(source, index, "ids"):
        word, _end = _word_after(source, index + 3)
        return word == "from"
    if _word_at(source, index, "using"):
        word, _end = _word_after(source, index + 5)
        return isinstance(word, str) and (word == "preset" or word.startswith("preset."))
    if _word_at(source, index, "similar"):
        profile, profile_end = _word_after(source, index + 7)
        if profile is None:
            return False
        word, _end = _word_after(source, profile_end)
        return word == "to"
    if _word_at(source, index, "match"):
        cursor = _skip_trivia(source, index + 5)
        if cursor < len(source) and source[cursor] == "@":
            return True
        profile, profile_end = _word_after(source, cursor)
        if profile is None:
            return False
        cursor = _skip_trivia(source, profile_end)
        return cursor < len(source) and source[cursor] == "@"
    return False


def _scan_field_predicate(source: str, field: str, operator: int) -> tuple[_Predicate | None, int]:
    operator = _skip_trivia(source, operator)
    if _word_at(source, operator, "is"):
        value_start = _skip_trivia(source, operator + 2)
        if _word_at(source, value_start, "not"):
            raise _ScanFailure("negative finite predicates are not authorized")
        literal, end = _scan_string(source, value_start)
        return _Predicate(field, "is", (literal,)), end
    if _word_at(source, operator, "in"):
        value_start = _skip_trivia(source, operator + 2)
        literals, end = _scan_list(source, value_start)
        return _Predicate(field, "in", literals), end
    if _word_at(source, operator, "has"):
        value_start = _skip_trivia(source, operator + 3)
        if _word_at(source, value_start, "any"):
            list_start = _skip_trivia(source, value_start + 3)
            literals, end = _scan_list(source, list_start)
            return _Predicate(field, "has any", literals), end
        if _word_at(source, value_start, "no"):
            raise _ScanFailure("negative finite predicates are not authorized")
        literal, end = _scan_string(source, value_start)
        return _Predicate(field, "has", (literal,)), end
    if source.startswith((">", "<"), operator) or any(
        _word_at(source, operator, word) for word in _UNSUPPORTED_FIELD_OPERATORS
    ):
        raise _ScanFailure("unsupported field predicate operator")
    return None, operator


def _catalog_source_after(source: str, index: int) -> tuple[str | None, int]:
    cursor = _skip_trivia(source, index)
    if _word_at(source, cursor, "all"):
        cursor = _skip_trivia(source, cursor + 3)
    if cursor >= len(source) or source[cursor] != "@":
        return None, cursor
    start = cursor + 1
    if start >= len(source) or source[start] not in _IDENTIFIER_START:
        return None, cursor + 1
    end = start + 1
    while end < len(source) and source[end] in _IDENTIFIER_CONTINUATION:
        end += 1
    return source[start:end], end


def _skip_guard(source: str, index: int) -> tuple[int, bool]:
    """Skip one guard expression without treating its operands as catalog filters.

    A ``{`` at top level starts a standalone GuardBlock.  In that case the
    caller resumes inside the block so its actual content conditions remain
    subject to grounding adjudication.
    """

    depth = 0
    while index < len(source):
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            return (len(source) if newline < 0 else newline + 1), False
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise _ScanFailure("unterminated block comment")
            index = end + 2
            continue
        char = source[index]
        if char == '"':
            _literal, index = _scan_string(source, index)
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            if depth > 0:
                depth -= 1
            index += 1
            continue
        if depth == 0 and char == "{":
            return index + 1, True
        if depth == 0 and char == "}":
            return index, False
        if depth == 0 and char in "\r\n":
            if char == "\r" and index + 1 < len(source) and source[index + 1] == "\n":
                index += 1
            return index + 1, False
        index += 1
    return index, False


def _scan_candidate(source: str) -> tuple[list[_Predicate], list[str]]:
    predicates: list[_Predicate] = []
    catalog_sources: list[str] = []
    index = 0
    literal_count = 0
    condition_surface = False
    while index < len(source):
        if source[index].isspace() or source.startswith(("//", "/*"), index):
            index = _skip_trivia(source, index)
            continue
        char = source[index]
        if char == '"':
            _literal, index = _scan_string(source, index)
            continue
        if _word_at(source, index, "if"):
            index, opened_guard_block = _skip_guard(source, index + 2)
            condition_surface = opened_guard_block
            continue
        if _word_at(source, index, "at"):
            qualifier, qualifier_end = _word_after(source, index + 2)
            condition_surface = qualifier == "least"
            index = qualifier_end
            continue
        boundary_word, boundary_end = _word_after(source, index)
        if boundary_word in _CONDITION_BOUNDARY_WORDS and boundary_end > index:
            condition_surface = boundary_word in {"include", "exclude", "promote"}
            index = boundary_end
            continue
        if _word_at(source, index, "where"):
            condition_surface = True
            index += 5
            continue
        if _word_at(source, index, "from"):
            catalog, next_index = _catalog_source_after(source, index + 4)
            if catalog is not None:
                catalog_sources.append(catalog)
                index = next_index
                continue
        if char == "@":
            field_start = index + 1
            if field_start >= len(source) or source[field_start] not in _IDENTIFIER_START:
                index += 1
                continue
            field_end = field_start + 1
            while field_end < len(source) and source[field_end] in _IDENTIFIER_CONTINUATION:
                field_end += 1
            field = source[field_start:field_end]
            predicate, next_index = _scan_field_predicate(source, field, field_end)
            if predicate is None:
                if condition_surface:
                    raise _ScanFailure("bare field condition is not authorized")
                index = field_end
                continue
            predicates.append(predicate)
            condition_surface = True
            literal_count += len(predicate.literals)
            if len(predicates) > MAX_PREDICATES or literal_count > MAX_PREDICATES:
                raise _ScanFailure("too many finite predicates")
            index = next_index
            continue
        if _unsupported_condition_starts_at(source, index):
            raise _ScanFailure("unsupported condition surface")
        index += 1
    return predicates, catalog_sources


def _selection_predicate(
    selection: Mapping[str, Any], authorized_catalogs: set[str]
) -> _Predicate | None:
    catalog = selection.get("catalog")
    if not isinstance(catalog, str) or not catalog or catalog not in authorized_catalogs:
        raise BrainError("GROUNDING_INVALID", 500, "grounding catalog is invalid")
    field = selection.get("field")
    if (
        not isinstance(field, str)
        or not field
        or len(field) > 256
        or field[0] not in _IDENTIFIER_START
        or any(char not in _IDENTIFIER_CONTINUATION for char in field[1:])
    ):
        raise BrainError("GROUNDING_INVALID", 500, "grounding field is invalid")
    field_type = selection.get("type")
    modifiers = selection.get("modifiers")
    if (
        not isinstance(field_type, str)
        or not field_type
        or not isinstance(modifiers, list)
        or any(not isinstance(item, str) or item not in {"multi", "ordered"} for item in modifiers)
        or len(modifiers) != len(set(modifiers))
    ):
        raise BrainError("GROUNDING_INVALID", 500, "grounding field surface is invalid")
    literal = selection.get("literal")
    literals = selection.get("literals")
    value_mode = selection.get("value_mode")
    if literal is None and literals is None:
        return None
    domain = selection.get("domain")
    if not isinstance(domain, Mapping):
        raise BrainError("GROUNDING_INVALID", 500, "grounding finite domain is invalid")
    domain_kind = domain.get("kind")
    if (
        not isinstance(domain_kind, str)
        or domain_kind not in _FINITE_DOMAIN_KINDS
        or type(domain.get("size")) is not int
        or domain["size"] <= 0
    ):
        raise BrainError("GROUNDING_INVALID", 500, "grounding finite domain is invalid")
    if literal is not None and literals is not None:
        raise BrainError("GROUNDING_INVALID", 500, "grounding selection is ambiguous")
    multi = "multi" in modifiers
    if literal is not None:
        if (
            not isinstance(literal, str)
            or not literal
            or len(literal.encode("utf-8")) > MAX_LITERAL_BYTES
            or value_mode is not None
        ):
            raise BrainError("GROUNDING_INVALID", 500, "grounding literal is invalid")
        return _Predicate(field, "has" if multi else "is", (literal,))
    if (
        not isinstance(literals, list)
        or len(literals) < 2
        or len(literals) > MAX_PREDICATES
        or any(
            not isinstance(item, str) or not item or len(item.encode("utf-8")) > MAX_LITERAL_BYTES
            for item in literals
        )
        or len(literals) != len(set(literals))
        or value_mode != "any_of"
    ):
        raise BrainError("GROUNDING_INVALID", 500, "grounding literals are invalid")
    return _Predicate(field, "has any" if multi else "in", tuple(sorted(literals)))


def _expected_grounding(
    grounding: Mapping[str, Any], authorized_catalogs: set[str]
) -> dict[str, list[_Predicate]]:
    selections = grounding.get("selections")
    if not isinstance(selections, list):
        raise BrainError("GROUNDING_INVALID", 500, "grounding selections are unavailable")
    expected: dict[str, list[_Predicate]] = defaultdict(list)
    value_count = 0
    for selection in selections:
        if not isinstance(selection, Mapping):
            raise BrainError("GROUNDING_INVALID", 500, "grounding selection is invalid")
        predicate = _selection_predicate(selection, authorized_catalogs)
        if predicate is None:
            continue
        value_count += len(predicate.literals)
        if value_count > MAX_PREDICATES:
            raise BrainError("GROUNDING_INVALID", 500, "grounding has too many literals")
        expected[predicate.field].append(predicate)
    return dict(expected)


def _authorized_catalogs(grounding: Mapping[str, Any]) -> set[str]:
    catalogs = grounding.get("catalogs")
    if (
        not isinstance(catalogs, list)
        or not catalogs
        or any(not isinstance(item, str) or not item or len(item) > 256 for item in catalogs)
        or len(catalogs) != len(set(catalogs))
    ):
        raise BrainError("GROUNDING_INVALID", 500, "grounding catalogs are invalid")
    return {name for item in catalogs for name in (item, item.rsplit(".", 1)[-1])}


def _catalog_is_authorized(source: str, authorized: set[str]) -> bool:
    return any(source == name or source.startswith(name + ".") for name in authorized)


def _values(predicates: list[_Predicate]) -> list[str]:
    return [literal for predicate in predicates for literal in predicate.literals]


def _predicate_view(predicate: _Predicate) -> dict[str, Any]:
    return {"operator": predicate.operator, "literals": list(predicate.literals)}


def _field_diagnostic(
    field: str, expected: list[_Predicate], actual: list[_Predicate]
) -> dict[str, Any]:
    expected_values = _values(expected)
    actual_values = _values(actual)
    expected_counts = Counter(expected_values)
    actual_counts = Counter(actual_values)
    missing = list((expected_counts - actual_counts).elements())
    extra = list((actual_counts - expected_counts).elements())
    return {
        "field": field,
        "expected": expected_values,
        "actual": actual_values,
        "missing": missing,
        "extra": extra,
        "expected_predicates": [_predicate_view(item) for item in expected],
        "actual_predicates": [_predicate_view(item) for item in actual],
    }


def adjudicate_candidate(source: str, grounding: Mapping[str, Any]) -> CandidateGroundingCheck:
    """Compare every finite candidate predicate to reviewed grounding exactly."""

    if not isinstance(source, str) or not source:
        raise BrainError("MODEL_INVALID", 503, "local model returned an invalid candidate")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise BrainError("PAYLOAD_TOO_LARGE", 413, "candidate exceeds the byte limit")
    authorized_catalogs = _authorized_catalogs(grounding)
    expected = _expected_grounding(grounding, authorized_catalogs)
    try:
        scanned, catalog_sources = _scan_candidate(source)
    except _ScanFailure as error:
        return CandidateGroundingCheck(
            False,
            {
                "code": "CANDIDATE_GROUNDING_MISMATCH",
                "reason": "candidate finite predicate surface is invalid",
                "parse_error": str(error),
                "fields": [],
                "unauthorized_fields": [],
                "unauthorized_catalogs": [],
            },
        )
    unauthorized_catalogs = sorted(
        {item for item in catalog_sources if not _catalog_is_authorized(item, authorized_catalogs)}
    )[:MAX_PREDICATES]
    actual: dict[str, list[_Predicate]] = defaultdict(list)
    for predicate in scanned:
        actual[predicate.field].append(predicate)
    field_diagnostics = [
        _field_diagnostic(field, expected.get(field, []), actual.get(field, []))
        for field in sorted(set(expected) | set(actual))
        if Counter(expected.get(field, [])) != Counter(actual.get(field, []))
    ]
    if not field_diagnostics and not unauthorized_catalogs:
        return CandidateGroundingCheck(True)
    return CandidateGroundingCheck(
        False,
        {
            "code": "CANDIDATE_GROUNDING_MISMATCH",
            "reason": "candidate finite predicates differ from reviewed grounding",
            "fields": field_diagnostics[:MAX_PREDICATES],
            "unauthorized_fields": sorted(set(actual) - set(expected))[:MAX_PREDICATES],
            "unauthorized_catalogs": unauthorized_catalogs,
        },
    )


def candidate_grounding_diagnostic(
    source: str, grounding: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Return a repair diagnostic, or ``None`` when the candidate is exact."""

    result = adjudicate_candidate(source, grounding)
    return result.diagnostic
