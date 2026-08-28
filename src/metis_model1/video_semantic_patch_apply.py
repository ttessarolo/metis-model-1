"""Fail-closed application of a validated semantic-only catalog patch.

The candidate renderer intentionally cannot write a tenant.  This module is
the separate, narrow mutation boundary: it accepts only an already validated
``video_semantics_patch`` candidate, binds it to a clean Git commit/tree and
exact file preimages, and inserts only the candidate's canonical ``means
draft``/``aka`` grammar.

The renderer below is pure.  Filesystem and Git checks live in
``apply_semantic_patch`` and the actual replacement primitive is explicitly
injected.  The default primitive is a same-directory, mode-preserving atomic
replace guarded by the expected preimage.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantic_patch import validate_candidate_patch

APPLY_CONTRACT = "video-semantics/semantic-patch-apply-v1"
RECEIPT_CONTRACT = "video-semantics/semantic-patch-apply-receipt-v1"
PROMOTION_RECEIPT_CONTRACT = "video-semantics/semantic-review-promotion-receipt-v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 15

_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


class SemanticPatchApplyError(RuntimeError):
    """Payload-free failure at the tenant mutation boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int
    line: int


@dataclass(frozen=True)
class _Node:
    node_kind: str
    catalog: str
    field_path: str | None
    literal: str | None
    start: int
    line: int
    insertion: int
    semantic_start: int | None
    semantic_end: int | None
    catalog_prefix: str = " "


@dataclass(frozen=True)
class SemanticTextEdit:
    offset: int
    text: str
    target: tuple[str, str, str | None, str | None]
    end: int | None = None


@dataclass(frozen=True)
class SemanticPatchFilePlan:
    path: str
    preimage_sha256: str
    postimage_sha256: str
    preimage: bytes
    postimage: bytes
    edits: tuple[SemanticTextEdit, ...]


@dataclass(frozen=True)
class SemanticPatchApplyPlan:
    repository_commit: str
    repository_tree: str
    patch_sha256: str
    files: tuple[SemanticPatchFilePlan, ...]
    operation_count: int


AtomicWriter = Callable[[Path, bytes, int, str], None]


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _identity_hash(value: Any) -> str:
    try:
        return "sha256:" + canonical_json_hash(value)
    except (TypeError, ValueError) as error:
        raise SemanticPatchApplyError("RECEIPT_NOT_CANONICAL") from error


def _safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SemanticPatchApplyError("APPLY_PATH_INVALID")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != value
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or parsed.suffix != ".metis"
    ):
        raise SemanticPatchApplyError("APPLY_PATH_INVALID")
    return value


def _source_files(value: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(value, Mapping) or not value:
        raise SemanticPatchApplyError("SOURCE_FILES_INVALID")
    result: dict[str, bytes] = {}
    for raw_path, raw in value.items():
        path = _safe_relative_path(raw_path)
        if path in result or not isinstance(raw, bytes) or not raw or len(raw) > MAX_FILE_BYTES:
            raise SemanticPatchApplyError("SOURCE_FILES_INVALID")
        try:
            decoded = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise SemanticPatchApplyError("SOURCE_FILE_NOT_UTF8") from error
        if "\x00" in decoded:
            raise SemanticPatchApplyError("SOURCE_FILE_NOT_UTF8")
        result[path] = raw
    return result


def _allowlist(value: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray) or not value:
        raise SemanticPatchApplyError("WRITE_ALLOWLIST_INVALID")
    paths = tuple(_safe_relative_path(item) for item in value)
    if len(paths) != len(set(paths)):
        raise SemanticPatchApplyError("WRITE_ALLOWLIST_INVALID")
    return paths


def _raw_roster(value: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    raw: Any = value
    if isinstance(value, Mapping):
        raw = value.get("roster", value.get("nodes"))
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes | bytearray) or not raw:
        raise SemanticPatchApplyError("TECHNICAL_ROSTER_INVALID")
    rows: list[Mapping[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise SemanticPatchApplyError("TECHNICAL_ROSTER_INVALID")
        rows.append(item)
    return rows


def _locator(row: Mapping[str, Any]) -> Mapping[str, Any]:
    locator = row.get("canonical_locator")
    if not isinstance(locator, Mapping):
        locator = row
    required = {
        "repository_commit",
        "path",
        "catalog",
        "field_path",
        "literal",
        "preimage_sha256",
    }
    if not required.issubset(locator):
        raise SemanticPatchApplyError("TECHNICAL_ROSTER_INVALID")
    return locator


def _node_kind(locator: Mapping[str, Any]) -> str:
    field = locator.get("field_path")
    literal = locator.get("literal")
    if field is None and literal is None:
        return "catalog"
    if isinstance(field, str) and field and literal is None:
        return "field"
    if isinstance(field, str) and field and isinstance(literal, str):
        return "value"
    raise SemanticPatchApplyError("TECHNICAL_ROSTER_INVALID")


def _target_key(
    path: str, node_kind: str, catalog: str, field: str | None, literal: str | None
) -> tuple[str, str, str | None, str | None]:
    return (path, catalog, field, literal) if node_kind in {"catalog", "field", "value"} else ()


def _lex(text: str) -> tuple[list[_Token], dict[int, int]]:
    tokens: list[_Token] = []
    index = 0
    line = 1
    size = len(text)
    while index < size:
        char = text[index]
        if char in " \t\r\n":
            if char == "\n":
                line += 1
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            if end < 0:
                break
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise SemanticPatchApplyError("METIS_LEX_UNTERMINATED_COMMENT")
            line += text.count("\n", index, end + 2)
            index = end + 2
            continue
        if char == '"':
            start = index
            token_line = line
            index += 1
            escaped = False
            while index < size:
                current = text[index]
                if current == "\n":
                    raise SemanticPatchApplyError("METIS_LEX_INVALID_STRING")
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    index += 1
                    break
                index += 1
            else:
                raise SemanticPatchApplyError("METIS_LEX_INVALID_STRING")
            raw = text[start:index]
            try:
                import json

                decoded = json.loads(raw)
            except (TypeError, ValueError) as error:
                raise SemanticPatchApplyError("METIS_LEX_INVALID_STRING") from error
            if not isinstance(decoded, str):
                raise SemanticPatchApplyError("METIS_LEX_INVALID_STRING")
            tokens.append(_Token("STRING", decoded, start, index, token_line))
            continue
        match = _IDENT_RE.match(text, index)
        if match is not None:
            tokens.append(_Token("ID", match.group(), index, match.end(), line))
            index = match.end()
            continue
        match = _NUMBER_RE.match(text, index)
        if match is not None:
            tokens.append(_Token("NUMBER", match.group(), index, match.end(), line))
            index = match.end()
            continue
        if char in "{}[](),.@":
            tokens.append(_Token("SYMBOL", char, index, index + 1, line))
            index += 1
            continue
        raise SemanticPatchApplyError("METIS_LEX_UNEXPECTED_TOKEN")

    pairs: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    opposites = {"}": "{", "]": "[", ")": "("}
    for token_index, token in enumerate(tokens):
        if token.value in "{[(":
            stack.append((token.value, token_index))
        elif token.value in "}])":
            if not stack or stack[-1][0] != opposites[token.value]:
                raise SemanticPatchApplyError("METIS_DELIMITERS_INVALID")
            _, opening = stack.pop()
            pairs[opening] = token_index
            pairs[token_index] = opening
    if stack:
        raise SemanticPatchApplyError("METIS_DELIMITERS_INVALID")
    return tokens, pairs


def _qualified(tokens: Sequence[_Token], start: int, stop: int) -> tuple[str, int]:
    if start >= stop or tokens[start].kind != "ID":
        raise SemanticPatchApplyError("METIS_QUALIFIED_NAME_INVALID")
    parts = [tokens[start].value]
    index = start + 1
    while index + 1 < stop and tokens[index].value == "." and tokens[index + 1].kind == "ID":
        parts.append(tokens[index + 1].value)
        index += 2
    return ".".join(parts), index


def _semantic(
    tokens: Sequence[_Token], pairs: Mapping[int, int], start: int
) -> tuple[int, int | None, int | None]:
    index = start
    semantic_start: int | None = None
    semantic_end: int | None = None
    if index < len(tokens) and tokens[index].value == "means":
        semantic_start = tokens[index].start
        index += 1
        if index < len(tokens) and tokens[index].value == "draft":
            index += 1
        if index >= len(tokens) or tokens[index].kind != "STRING":
            raise SemanticPatchApplyError("METIS_EXISTING_SEMANTIC_INVALID")
        semantic_end = tokens[index].end
        index += 1
    if index < len(tokens) and tokens[index].value == "aka":
        if semantic_start is None:
            raise SemanticPatchApplyError("METIS_EXISTING_SEMANTIC_INVALID")
        index += 1
        if index >= len(tokens) or tokens[index].value != "[":
            raise SemanticPatchApplyError("METIS_EXISTING_SEMANTIC_INVALID")
        close = pairs[index]
        cursor = index + 1
        expect_string = True
        while cursor < close:
            token = tokens[cursor]
            if expect_string:
                if token.kind != "STRING":
                    raise SemanticPatchApplyError("METIS_EXISTING_SEMANTIC_INVALID")
                expect_string = False
            elif token.value == ",":
                expect_string = True
            elif token.kind == "STRING":
                # The grammar permits an omitted comma.
                expect_string = False
            else:
                raise SemanticPatchApplyError("METIS_EXISTING_SEMANTIC_INVALID")
            cursor += 1
        if expect_string and close > index + 1:
            raise SemanticPatchApplyError("METIS_EXISTING_SEMANTIC_INVALID")
        semantic_end = tokens[close].end
        index = close + 1
    return index, semantic_start, semantic_end


def _value_items(
    tokens: Sequence[_Token],
    pairs: Mapping[int, int],
    opening: int,
    *,
    catalog: str,
    field_path: str,
) -> tuple[list[_Node], int]:
    if tokens[opening].value != "[":
        raise SemanticPatchApplyError("METIS_VALUE_LIST_INVALID")
    close = pairs[opening]
    nodes: list[_Node] = []
    literals: set[str] = set()
    index = opening + 1
    while index < close:
        if tokens[index].value == ",":
            index += 1
            continue
        literal_token = tokens[index]
        if literal_token.kind != "STRING":
            raise SemanticPatchApplyError("METIS_VALUE_LIST_INVALID")
        if literal_token.value in literals:
            raise SemanticPatchApplyError("METIS_DUPLICATE_VALUE_LITERAL")
        literals.add(literal_token.value)
        next_index, semantic_start, semantic_end = _semantic(tokens, pairs, index + 1)
        nodes.append(
            _Node(
                "value",
                catalog,
                field_path,
                literal_token.value,
                literal_token.start,
                literal_token.line,
                literal_token.end,
                semantic_start,
                semantic_end,
            )
        )
        index = next_index
        if index < close and tokens[index].value == ",":
            index += 1
    return nodes, close + 1


def _field(
    tokens: Sequence[_Token],
    pairs: Mapping[int, int],
    start: int,
    *,
    catalog: str,
    parent: str | None = None,
) -> tuple[_Node, list[_Node], int]:
    if tokens[start].kind != "ID":
        raise SemanticPatchApplyError("METIS_FIELD_INVALID")
    name = tokens[start].value
    field_path = name if parent is None else f"{parent}.{name}"
    index = start + 1
    if index >= len(tokens) or tokens[index].kind != "ID":
        raise SemanticPatchApplyError("METIS_FIELD_INVALID")

    # FieldType.  Object subfields are kept opaque here; the video catalog's
    # authoring surface is top-level and a target inside an opaque object will
    # therefore be absent from the verified roster rather than guessed.
    if tokens[index].value == "ref" and index + 1 < len(tokens) and tokens[index + 1].value == "@":
        _, index = _qualified(tokens, index + 2, len(tokens))
    elif (
        tokens[index].value == "object"
        and index + 1 < len(tokens)
        and tokens[index + 1].value == "{"
    ):
        index = pairs[index + 1] + 1
    else:
        index += 1

    while index < len(tokens):
        value = tokens[index].value
        if value in {"multi", "ordered"}:
            index += 1
        elif value == "sort":
            if index + 1 >= len(tokens) or tokens[index + 1].kind != "ID":
                raise SemanticPatchApplyError("METIS_FIELD_INVALID")
            index += 2
        elif value == "indexed":
            if (
                index + 2 >= len(tokens)
                or tokens[index + 1].value != "as"
                or tokens[index + 2].kind != "STRING"
            ):
                raise SemanticPatchApplyError("METIS_FIELD_INVALID")
            index += 3
        else:
            break

    value_nodes: list[_Node] = []
    if index < len(tokens) and tokens[index].value == "values":
        if index + 1 < len(tokens) and tokens[index + 1].value == "[":
            value_nodes, index = _value_items(
                tokens, pairs, index + 1, catalog=catalog, field_path=field_path
            )
        elif (
            index + 3 < len(tokens)
            and tokens[index + 1].value == "list"
            and tokens[index + 2].value == "."
            and tokens[index + 3].kind == "ID"
        ):
            index += 4
        else:
            raise SemanticPatchApplyError("METIS_FIELD_DOMAIN_INVALID")
    elif index < len(tokens) and tokens[index].value == "[":
        value_nodes, index = _value_items(
            tokens, pairs, index, catalog=catalog, field_path=field_path
        )
    elif index < len(tokens) and tokens[index].value == "enum":
        if (
            index + 3 >= len(tokens)
            or tokens[index + 1].value != "("
            or tokens[index + 2].kind != "NUMBER"
            or tokens[index + 3].value != ")"
        ):
            raise SemanticPatchApplyError("METIS_FIELD_DOMAIN_INVALID")
        index += 4
    elif index < len(tokens) and tokens[index].value == "open":
        index += 1

    insertion = tokens[index - 1].end
    index, semantic_start, semantic_end = _semantic(tokens, pairs, index)
    if index < len(tokens) and tokens[index].value == "fields":
        if index + 1 >= len(tokens) or tokens[index + 1].value != "(":
            raise SemanticPatchApplyError("METIS_FIELD_INVALID")
        index = pairs[index + 1] + 1
    if index < len(tokens) and tokens[index].value == "{":
        index = pairs[index] + 1
    return (
        _Node(
            "field",
            catalog,
            field_path,
            None,
            tokens[start].start,
            tokens[start].line,
            insertion,
            semantic_start,
            semantic_end,
        ),
        value_nodes,
        index,
    )


def _line_indent(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    match = re.match(r"[ \t]*", text[start:offset])
    return match.group() if match is not None else ""


def _catalog_nodes(
    text: str,
    tokens: Sequence[_Token],
    pairs: Mapping[int, int],
    start: int,
) -> tuple[list[_Node], int]:
    catalog, opening = _qualified(tokens, start + 1, len(tokens))
    if opening >= len(tokens) or tokens[opening].value != "{":
        raise SemanticPatchApplyError("METIS_CATALOG_INVALID")
    close = pairs[opening]
    cursor = opening + 1
    anchor = tokens[opening]
    if cursor < close and tokens[cursor].value == "label":
        if cursor + 1 >= close or tokens[cursor + 1].kind != "STRING":
            raise SemanticPatchApplyError("METIS_CATALOG_INVALID")
        anchor = tokens[cursor + 1]
        cursor += 2
    cursor, semantic_start, semantic_end = _semantic(tokens, pairs, cursor)
    next_token = tokens[cursor] if cursor < close else tokens[close]
    if next_token.line > anchor.line:
        newline = "\r\n" if "\r\n" in text else "\n"
        indent = _line_indent(text, next_token.start)
        prefix = newline + indent
    else:
        prefix = " "
    nodes: list[_Node] = [
        _Node(
            "catalog",
            catalog,
            None,
            None,
            tokens[start].start,
            tokens[start].line,
            anchor.end,
            semantic_start,
            semantic_end,
            prefix,
        )
    ]

    fields_keyword: int | None = None
    depth = 0
    for index in range(cursor, close):
        token = tokens[index]
        if token.value == "{":
            depth += 1
        elif token.value == "}":
            depth -= 1
        elif depth == 0 and token.value == "fields":
            fields_keyword = index
            break
    if fields_keyword is not None:
        if fields_keyword + 1 >= close or tokens[fields_keyword + 1].value != "{":
            raise SemanticPatchApplyError("METIS_UNBRACED_FIELDS_UNSUPPORTED")
        fields_close = pairs[fields_keyword + 1]
        index = fields_keyword + 2
        while index < fields_close:
            field_node, values, index = _field(tokens, pairs, index, catalog=catalog)
            if index > fields_close:
                raise SemanticPatchApplyError("METIS_FIELD_INVALID")
            nodes.append(field_node)
            nodes.extend(values)
    return nodes, close + 1


def _value_set_nodes(
    tokens: Sequence[_Token], pairs: Mapping[int, int], start: int
) -> tuple[list[_Node], int]:
    catalog, opening = _qualified(tokens, start + 1, len(tokens))
    if opening >= len(tokens) or tokens[opening].value != "{":
        raise SemanticPatchApplyError("METIS_VALUE_SET_INVALID")
    close = pairs[opening]
    nodes: list[_Node] = []
    index = opening + 1
    fields: set[str] = set()
    while index < close:
        if (
            tokens[index].kind != "ID"
            or index + 2 >= close
            or tokens[index + 1].value not in {"reflected", "editorial"}
            or tokens[index + 2].value != "["
        ):
            raise SemanticPatchApplyError("METIS_VALUE_SET_INVALID")
        field = tokens[index].value
        if field in fields:
            raise SemanticPatchApplyError("METIS_DUPLICATE_VALUE_SET_FIELD")
        fields.add(field)
        values, index = _value_items(tokens, pairs, index + 2, catalog=catalog, field_path=field)
        nodes.extend(values)
    return nodes, close + 1


def _document_nodes(path: str, raw: bytes) -> tuple[str, list[_Node]]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SemanticPatchApplyError("SOURCE_FILE_NOT_UTF8") from error
    tokens, pairs = _lex(text)
    nodes: list[_Node] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.value == "catalog":
            found, index = _catalog_nodes(text, tokens, pairs, index)
            nodes.extend(found)
        elif token.value == "values":
            found, index = _value_set_nodes(tokens, pairs, index)
            nodes.extend(found)
        else:
            index += 1
    identities = [(node.catalog, node.field_path, node.literal, node.node_kind) for node in nodes]
    if len(identities) != len(set(identities)):
        raise SemanticPatchApplyError("METIS_TARGET_IDENTITY_AMBIGUOUS")
    return text, nodes


def _operation_key(operation: Mapping[str, Any]) -> tuple[str, str, str | None, str | None]:
    locator = operation.get("canonical_locator")
    if not isinstance(locator, Mapping):
        raise SemanticPatchApplyError("PATCH_OPERATION_INVALID")
    path = _safe_relative_path(locator.get("path"))
    node_kind = operation.get("node_kind")
    if node_kind not in {"catalog", "field", "value"}:
        raise SemanticPatchApplyError("PATCH_NODE_KIND_UNSUPPORTED")
    expected_kind = _node_kind(locator)
    if node_kind != expected_kind:
        raise SemanticPatchApplyError("PATCH_NODE_KIND_MISMATCH")
    catalog = locator.get("catalog")
    field = locator.get("field_path")
    literal = locator.get("literal")
    if not isinstance(catalog, str) or not catalog:
        raise SemanticPatchApplyError("PATCH_OPERATION_INVALID")
    return _target_key(path, node_kind, catalog, field, literal)


def _discover(
    source_files: Mapping[str, bytes],
) -> tuple[dict[str, str], dict[tuple[str, str, str | None, str | None], _Node]]:
    texts: dict[str, str] = {}
    nodes: dict[tuple[str, str, str | None, str | None], _Node] = {}
    for path, raw in source_files.items():
        text, found = _document_nodes(path, raw)
        texts[path] = text
        for node in found:
            key = _target_key(path, node.node_kind, node.catalog, node.field_path, node.literal)
            if not key or key in nodes:
                raise SemanticPatchApplyError("METIS_TARGET_IDENTITY_AMBIGUOUS")
            nodes[key] = node
    return texts, nodes


def _verify_roster(
    technical_roster: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    repository_commit: str,
    source_files: Mapping[str, bytes],
    discovered: Mapping[tuple[str, str, str | None, str | None], _Node],
    current_preimages: Mapping[str, str] | None = None,
    locator_preimages: Mapping[str, str] | None = None,
) -> None:
    rows = _raw_roster(technical_roster)
    expected_paths = set(source_files)
    orders: set[int] = set()
    positions_by_path: dict[str, list[tuple[int, int]]] = {}
    keys: set[tuple[str, str, str | None, str | None]] = set()
    for row in rows:
        locator = _locator(row)
        if locator.get("repository_commit") != repository_commit:
            raise SemanticPatchApplyError("ROSTER_COMMIT_DRIFT")
        path = _safe_relative_path(locator.get("path"))
        if path not in expected_paths:
            raise SemanticPatchApplyError("ROSTER_PATH_OUTSIDE_SOURCE_SET")
        preimage = locator.get("preimage_sha256")
        if not isinstance(preimage, str) or _HASH_RE.fullmatch(preimage) is None:
            raise SemanticPatchApplyError("TECHNICAL_ROSTER_INVALID")
        if locator_preimages is not None and locator_preimages.get(path) != preimage:
            raise SemanticPatchApplyError("ROSTER_PREIMAGE_BINDING_DRIFT")
        expected_current = preimage
        if current_preimages is not None:
            expected_current = current_preimages.get(path, "")
        if _sha256(source_files[path]) != expected_current:
            raise SemanticPatchApplyError("FILE_PREIMAGE_DRIFT")
        kind = _node_kind(locator)
        catalog = locator.get("catalog")
        if not isinstance(catalog, str) or not catalog:
            raise SemanticPatchApplyError("TECHNICAL_ROSTER_INVALID")
        key = _target_key(path, kind, catalog, locator.get("field_path"), locator.get("literal"))
        if key in keys:
            raise SemanticPatchApplyError("TECHNICAL_ROSTER_DUPLICATE_TARGET")
        keys.add(key)
        node = discovered.get(key)
        if node is None:
            raise SemanticPatchApplyError("ROSTER_TARGET_ABSENT")
        order = row.get("order")
        if type(order) is not int or order < 0 or order in orders:
            raise SemanticPatchApplyError("TECHNICAL_ROSTER_ORDER_INVALID")
        orders.add(order)
        expected_line = row.get("source_line")
        if expected_line is not None and (
            type(expected_line) is not int or expected_line != node.line
        ):
            raise SemanticPatchApplyError("ROSTER_SOURCE_LOCATION_STALE")
        positions_by_path.setdefault(path, []).append((order, node.start))
    for roster in positions_by_path.values():
        by_order = sorted(roster)
        positions = [position for _, position in by_order]
        if positions != sorted(positions):
            raise SemanticPatchApplyError("ROSTER_SOURCE_ORDER_DRIFT")
    if keys != set(discovered):
        raise SemanticPatchApplyError("TECHNICAL_ROSTER_COVERAGE_GAP")


def _apply_text_edits(text: str, edits: Sequence[SemanticTextEdit]) -> str:
    ordered = sorted(edits, key=lambda edit: edit.offset, reverse=True)
    if len({edit.offset for edit in ordered}) != len(ordered):
        raise SemanticPatchApplyError("PATCH_EDITS_OVERLAP")
    spans = sorted((edit.offset, edit.offset if edit.end is None else edit.end) for edit in edits)
    if any(start < 0 or end < start for start, end in spans) or any(
        previous_end > start
        for (_, previous_end), (start, _) in zip(spans, spans[1:], strict=False)
    ):
        raise SemanticPatchApplyError("PATCH_EDITS_OVERLAP")
    output = text
    for edit in ordered:
        end = edit.offset if edit.end is None else edit.end
        output = output[: edit.offset] + edit.text + output[end:]
    return output


def plan_semantic_patch_apply(
    *,
    source_files: Mapping[str, bytes],
    patch: Mapping[str, Any],
    technical_roster: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    repository_commit: str,
    repository_tree: str,
    allowlisted_paths: Sequence[str],
) -> SemanticPatchApplyPlan:
    """Purely render an apply plan from exact preimage bytes."""

    if not _OID_RE.fullmatch(repository_commit) or not _OID_RE.fullmatch(repository_tree):
        raise SemanticPatchApplyError("REPOSITORY_IDENTITY_INVALID")
    files = _source_files(source_files)
    allowed = _allowlist(allowlisted_paths)
    if set(files) != set(allowed):
        raise SemanticPatchApplyError("SOURCE_SET_DIFFERS_FROM_ALLOWLIST")
    errors = validate_candidate_patch(
        patch, technical_roster=technical_roster, repository_commit=repository_commit
    )
    if errors:
        raise SemanticPatchApplyError("CANDIDATE_PATCH_INVALID")
    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        raise SemanticPatchApplyError("CANDIDATE_PATCH_EMPTY")
    receipt = patch.get("receipt")
    if not isinstance(receipt, Mapping):
        raise SemanticPatchApplyError("CANDIDATE_PATCH_INVALID")
    counts = receipt.get("counts")
    if (
        not isinstance(counts, Mapping)
        or any(
            counts.get(key) != len(operations)
            for key in ("items_in", "items_out", "items_distinct")
        )
        or counts.get("items_gaps") != 0
    ):
        raise SemanticPatchApplyError("CANDIDATE_PATCH_COUNT_MISMATCH")

    texts, discovered = _discover(files)
    _verify_roster(
        technical_roster,
        repository_commit=repository_commit,
        source_files=files,
        discovered=discovered,
    )

    edits_by_path: dict[str, list[SemanticTextEdit]] = {}
    orders: list[int] = []
    for operation in operations:
        key = _operation_key(operation)
        path = key[0]
        if path not in allowed:
            raise SemanticPatchApplyError("PATCH_PATH_NOT_ALLOWLISTED")
        node = discovered.get(key)
        if node is None:
            raise SemanticPatchApplyError("PATCH_TARGET_ABSENT")
        if node.semantic_start is not None or node.semantic_end is not None:
            raise SemanticPatchApplyError("PATCH_TARGET_ALREADY_ANNOTATED")
        grammar = operation.get("grammar")
        if not isinstance(grammar, str) or not grammar.startswith("means draft "):
            raise SemanticPatchApplyError("PATCH_GRAMMAR_INVALID")
        prefix = node.catalog_prefix if node.node_kind == "catalog" else " "
        edits_by_path.setdefault(path, []).append(
            SemanticTextEdit(node.insertion, prefix + grammar, key)
        )
        order = operation.get("order")
        if type(order) is not int:
            raise SemanticPatchApplyError("PATCH_OPERATION_INVALID")
        orders.append(order)
    if orders != sorted(orders) or len(orders) != len(set(orders)):
        raise SemanticPatchApplyError("PATCH_OPERATION_ORDER_INVALID")

    plans: list[SemanticPatchFilePlan] = []
    for path in sorted(edits_by_path):
        edits = tuple(sorted(edits_by_path[path], key=lambda edit: edit.offset))
        rendered = _apply_text_edits(texts[path], edits).encode("utf-8")
        _, post_nodes = _discover({path: rendered})
        for operation in operations:
            key = _operation_key(operation)
            if key[0] != path:
                continue
            node = post_nodes.get(key)
            if node is None or node.semantic_start is None or node.semantic_end is None:
                raise SemanticPatchApplyError("POSTIMAGE_SEMANTIC_MISSING")
            post_text = rendered.decode("utf-8")
            if post_text[node.semantic_start : node.semantic_end] != operation["grammar"]:
                raise SemanticPatchApplyError("POSTIMAGE_SEMANTIC_DRIFT")
        plans.append(
            SemanticPatchFilePlan(
                path=path,
                preimage_sha256=_sha256(files[path]),
                postimage_sha256=_sha256(rendered),
                preimage=files[path],
                postimage=rendered,
                edits=edits,
            )
        )
    return SemanticPatchApplyPlan(
        repository_commit=repository_commit,
        repository_tree=repository_tree,
        patch_sha256=patch["patch_sha256"],
        files=tuple(plans),
        operation_count=len(operations),
    )


def _validated_draft_apply_receipt(
    receipt: Any,
    *,
    repository_commit: str,
    repository_tree: str,
    patch_sha256: str,
    operation_count: int,
    allowlisted_paths: Sequence[str],
) -> dict[str, tuple[str, str]]:
    expected_keys = {
        "schema_version",
        "contract_id",
        "repository_commit",
        "repository_tree",
        "patch_sha256",
        "counts",
        "files",
        "payload_redacted",
        "receipt_sha256",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != expected_keys:
        raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("contract_id") != RECEIPT_CONTRACT
        or receipt.get("repository_commit") != repository_commit
        or receipt.get("repository_tree") != repository_tree
        or receipt.get("patch_sha256") != patch_sha256
        or receipt.get("payload_redacted") is not True
    ):
        raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or counts != {
        "files_in": len(allowlisted_paths),
        "files_written": len(allowlisted_paths),
        "operations": operation_count,
        "gaps": 0,
    }:
        raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != len(allowlisted_paths):
        raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
    result: dict[str, tuple[str, str]] = {}
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {
            "path",
            "preimage_sha256",
            "postimage_sha256",
        }:
            raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
        path = _safe_relative_path(item.get("path"))
        before = item.get("preimage_sha256")
        after = item.get("postimage_sha256")
        if (
            path in result
            or not isinstance(before, str)
            or _HASH_RE.fullmatch(before) is None
            or not isinstance(after, str)
            or _HASH_RE.fullmatch(after) is None
            or before == after
        ):
            raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
        result[path] = (before, after)
    if set(result) != set(allowlisted_paths):
        raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
    body = {key: receipt[key] for key in expected_keys if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _identity_hash(body):
        raise SemanticPatchApplyError("DRAFT_APPLY_RECEIPT_INVALID")
    return result


def plan_semantic_review_promotion(
    *,
    source_files: Mapping[str, bytes],
    preimage_files: Mapping[str, bytes],
    patch: Mapping[str, Any],
    technical_roster: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    draft_apply_receipt: Mapping[str, Any],
    repository_commit: str,
    repository_tree: str,
    allowlisted_paths: Sequence[str],
) -> SemanticPatchApplyPlan:
    """Render the exact ``draft`` to ``reviewed`` transition without writing."""

    if not _OID_RE.fullmatch(repository_commit) or not _OID_RE.fullmatch(repository_tree):
        raise SemanticPatchApplyError("REPOSITORY_IDENTITY_INVALID")
    files = _source_files(source_files)
    preimages = _source_files(preimage_files)
    allowed = _allowlist(allowlisted_paths)
    if set(files) != set(allowed) or set(preimages) != set(allowed):
        raise SemanticPatchApplyError("SOURCE_SET_DIFFERS_FROM_ALLOWLIST")
    errors = validate_candidate_patch(
        patch, technical_roster=technical_roster, repository_commit=repository_commit
    )
    if errors:
        raise SemanticPatchApplyError("CANDIDATE_PATCH_INVALID")
    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        raise SemanticPatchApplyError("CANDIDATE_PATCH_EMPTY")
    expected_draft_plan = plan_semantic_patch_apply(
        source_files=preimages,
        patch=patch,
        technical_roster=technical_roster,
        repository_commit=repository_commit,
        repository_tree=repository_tree,
        allowlisted_paths=allowed,
    )
    expected_bindings = {
        item.path: (item.preimage_sha256, item.postimage_sha256)
        for item in expected_draft_plan.files
    }
    if set(expected_bindings) != set(allowed):
        raise SemanticPatchApplyError("DRAFT_POSTIMAGE_SCOPE_GAP")
    bindings = _validated_draft_apply_receipt(
        draft_apply_receipt,
        repository_commit=repository_commit,
        repository_tree=repository_tree,
        patch_sha256=patch["patch_sha256"],
        operation_count=len(operations),
        allowlisted_paths=allowed,
    )
    if bindings != expected_bindings:
        raise SemanticPatchApplyError("DRAFT_POSTIMAGE_BINDING_DRIFT")
    if any(_sha256(files[path]) != pair[1] for path, pair in expected_bindings.items()):
        raise SemanticPatchApplyError("DRAFT_POSTIMAGE_DRIFT")
    locator_preimages = {path: pair[0] for path, pair in bindings.items()}
    current_preimages = {path: pair[1] for path, pair in bindings.items()}
    texts, discovered = _discover(files)
    _verify_roster(
        technical_roster,
        repository_commit=repository_commit,
        source_files=files,
        discovered=discovered,
        current_preimages=current_preimages,
        locator_preimages=locator_preimages,
    )

    operation_by_key: dict[tuple[str, str, str | None, str | None], Mapping[str, Any]] = {}
    orders: list[int] = []
    for operation in operations:
        key = _operation_key(operation)
        if key in operation_by_key:
            raise SemanticPatchApplyError("PATCH_TARGET_DUPLICATE")
        operation_by_key[key] = operation
        order = operation.get("order")
        if type(order) is not int:
            raise SemanticPatchApplyError("PATCH_OPERATION_INVALID")
        orders.append(order)
    if orders != sorted(orders) or len(orders) != len(set(orders)):
        raise SemanticPatchApplyError("PATCH_OPERATION_ORDER_INVALID")
    annotated = {
        key
        for key, node in discovered.items()
        if node.semantic_start is not None or node.semantic_end is not None
    }
    if annotated != set(operation_by_key):
        raise SemanticPatchApplyError("DRAFT_REVIEW_SCOPE_GAP")

    edits_by_path: dict[str, list[SemanticTextEdit]] = {}
    reviewed_grammar: dict[tuple[str, str, str | None, str | None], str] = {}
    for key, operation in operation_by_key.items():
        node = discovered[key]
        if node.semantic_start is None or node.semantic_end is None:
            raise SemanticPatchApplyError("DRAFT_SEMANTIC_MISSING")
        grammar = operation.get("grammar")
        if not isinstance(grammar, str) or not grammar.startswith("means draft "):
            raise SemanticPatchApplyError("PATCH_GRAMMAR_INVALID")
        observed = texts[key[0]][node.semantic_start : node.semantic_end]
        if observed != grammar:
            raise SemanticPatchApplyError("DRAFT_SEMANTIC_DRIFT")
        reviewed = grammar.replace("means draft ", "means ", 1)
        reviewed_grammar[key] = reviewed
        edits_by_path.setdefault(key[0], []).append(
            SemanticTextEdit(node.semantic_start, reviewed, key, node.semantic_end)
        )

    plans: list[SemanticPatchFilePlan] = []
    for path in sorted(edits_by_path):
        edits = tuple(sorted(edits_by_path[path], key=lambda edit: edit.offset))
        rendered = _apply_text_edits(texts[path], edits).encode("utf-8")
        post_texts, post_nodes = _discover({path: rendered})
        for key, expected in reviewed_grammar.items():
            if key[0] != path:
                continue
            node = post_nodes.get(key)
            if node is None or node.semantic_start is None or node.semantic_end is None:
                raise SemanticPatchApplyError("REVIEWED_SEMANTIC_MISSING")
            if post_texts[path][node.semantic_start : node.semantic_end] != expected:
                raise SemanticPatchApplyError("REVIEWED_SEMANTIC_DRIFT")
        if any(
            node.semantic_start is not None
            and post_texts[path][node.semantic_start : node.semantic_end].startswith("means draft ")
            for node in post_nodes.values()
        ):
            raise SemanticPatchApplyError("REVIEWED_POSTIMAGE_CONTAINS_DRAFT")
        plans.append(
            SemanticPatchFilePlan(
                path=path,
                preimage_sha256=_sha256(files[path]),
                postimage_sha256=_sha256(rendered),
                preimage=files[path],
                postimage=rendered,
                edits=edits,
            )
        )
    return SemanticPatchApplyPlan(
        repository_commit=repository_commit,
        repository_tree=repository_tree,
        patch_sha256=patch["patch_sha256"],
        files=tuple(plans),
        operation_count=len(operations),
    )


def _git(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["/usr/bin/git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SemanticPatchApplyError("GIT_IDENTITY_UNAVAILABLE") from error
    if completed.returncode != 0:
        raise SemanticPatchApplyError("GIT_IDENTITY_UNAVAILABLE")
    return completed.stdout


def _git_file(root: Path, commit: str, path: str) -> bytes:
    """Read one allowlisted preimage from the exact repository commit."""

    try:
        return _git(root, "show", f"{commit}:{_safe_relative_path(path)}")
    except SemanticPatchApplyError as error:
        raise SemanticPatchApplyError("GIT_PREIMAGE_UNAVAILABLE") from error


def _safe_root(value: Path) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raise SemanticPatchApplyError("TENANT_ROOT_INVALID")
    absolute = Path(os.path.abspath(os.fspath(raw)))
    try:
        info = absolute.lstat()
        resolved = absolute.resolve(strict=True)
    except OSError as error:
        raise SemanticPatchApplyError("TENANT_ROOT_INVALID") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or resolved != absolute:
        raise SemanticPatchApplyError("TENANT_ROOT_INVALID")
    if _git(absolute, "rev-parse", "--show-toplevel").decode("utf-8").strip() != str(absolute):
        raise SemanticPatchApplyError("TENANT_ROOT_NOT_GIT_TOPLEVEL")
    return absolute


def _safe_target(root: Path, relative: str) -> tuple[Path, int]:
    path = _safe_relative_path(relative)
    cursor = root
    for part in PurePosixPath(path).parts[:-1]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as error:
            raise SemanticPatchApplyError("APPLY_PATH_UNAVAILABLE") from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SemanticPatchApplyError("APPLY_PATH_CROSSES_SYMLINK")
    target = root.joinpath(*PurePosixPath(path).parts)
    try:
        info = target.lstat()
    except OSError as error:
        raise SemanticPatchApplyError("APPLY_PATH_UNAVAILABLE") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SemanticPatchApplyError("APPLY_TARGET_NOT_REGULAR")
    return target, stat.S_IMODE(info.st_mode)


def _verify_clean_checkout(root: Path, commit: str, tree: str) -> None:
    if _git(root, "rev-parse", "HEAD").decode("ascii").strip() != commit:
        raise SemanticPatchApplyError("TENANT_COMMIT_DRIFT")
    if _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip() != tree:
        raise SemanticPatchApplyError("TENANT_TREE_DRIFT")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise SemanticPatchApplyError("TENANT_WORKTREE_NOT_CLEAN")


def _verify_rollback_state(
    root: Path,
    *,
    repository_commit: str,
    repository_tree: str,
    targets: Mapping[str, Path],
    modes: Mapping[str, int],
    plans: Sequence[SemanticPatchFilePlan],
) -> None:
    """Prove that our targets are restored without requiring a clean checkout.

    A failure after publishing may coincide with an unrelated dirty file.  The
    rollback must restore only the targets owned by this operation and must not
    mistake that unrelated work for a rollback failure.
    """

    for file_plan in plans:
        target = targets[file_plan.path]
        try:
            current = target.read_bytes()
        except OSError as error:
            raise SemanticPatchApplyError("APPLY_ROLLBACK_CONTENT_DRIFT") from error
        if current != file_plan.preimage:
            raise SemanticPatchApplyError("APPLY_ROLLBACK_CONTENT_DRIFT")
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
        except OSError as error:
            raise SemanticPatchApplyError("APPLY_ROLLBACK_CONTENT_DRIFT") from error
        if mode != modes[file_plan.path]:
            raise SemanticPatchApplyError("APPLY_ROLLBACK_MODE_DRIFT")
    if _git(root, "rev-parse", "HEAD").decode("ascii").strip() != repository_commit:
        raise SemanticPatchApplyError("APPLY_ROLLBACK_COMMIT_DRIFT")
    if _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip() != repository_tree:
        raise SemanticPatchApplyError("APPLY_ROLLBACK_TREE_DRIFT")


def atomic_replace_if_current(
    target: Path, postimage: bytes, mode: int, expected_preimage_sha256: str
) -> None:
    """Atomically replace one regular file if its exact preimage is current."""

    try:
        before = target.read_bytes()
    except OSError as error:
        raise SemanticPatchApplyError("APPLY_PREIMAGE_UNAVAILABLE") from error
    if _sha256(before) != expected_preimage_sha256:
        raise SemanticPatchApplyError("APPLY_PREIMAGE_RACE")
    descriptor = -1
    temporary = ""
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        os.fchmod(descriptor, mode)
        view = memoryview(postimage)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short atomic write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if target.is_symlink() or _sha256(target.read_bytes()) != expected_preimage_sha256:
            raise SemanticPatchApplyError("APPLY_PREIMAGE_RACE")
        os.replace(temporary, target)
        temporary = ""
        os.chmod(target, mode, follow_symlinks=False)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except SemanticPatchApplyError:
        raise
    except OSError as error:
        raise SemanticPatchApplyError("ATOMIC_WRITE_FAILED") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            with suppress(FileNotFoundError):
                os.unlink(temporary)


def _verify_expected_dirty(root: Path, paths: Sequence[str]) -> None:
    raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = [entry for entry in raw.decode("utf-8", errors="strict").split("\x00") if entry]
    expected = {f" M {path}" for path in paths}
    if set(entries) != expected or len(entries) != len(expected):
        raise SemanticPatchApplyError("POST_APPLY_WORKTREE_SCOPE_DRIFT")


def apply_semantic_patch(
    *,
    tenant_root: Path,
    repository_commit: str,
    repository_tree: str,
    patch: Mapping[str, Any],
    technical_roster: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    allowlisted_paths: Sequence[str],
    atomic_writer: AtomicWriter = atomic_replace_if_current,
) -> dict[str, Any]:
    """Apply a semantic patch to an exact, clean tenant checkout."""

    if not callable(atomic_writer):
        raise SemanticPatchApplyError("ATOMIC_WRITER_INVALID")
    root = _safe_root(tenant_root)
    _verify_clean_checkout(root, repository_commit, repository_tree)
    allowed = _allowlist(allowlisted_paths)
    source_files: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    targets: dict[str, Path] = {}
    for path in allowed:
        target, mode = _safe_target(root, path)
        try:
            raw = target.read_bytes()
        except OSError as error:
            raise SemanticPatchApplyError("APPLY_PREIMAGE_UNAVAILABLE") from error
        source_files[path] = raw
        modes[path] = mode
        targets[path] = target
    plan = plan_semantic_patch_apply(
        source_files=source_files,
        patch=patch,
        technical_roster=technical_roster,
        repository_commit=repository_commit,
        repository_tree=repository_tree,
        allowlisted_paths=allowed,
    )

    # Close the planning window before any mutation, then perform a per-file
    # compare-and-swap through the injected atomic boundary.
    _verify_clean_checkout(root, repository_commit, repository_tree)
    for file_plan in plan.files:
        target, mode = _safe_target(root, file_plan.path)
        if target != targets[file_plan.path] or mode != modes[file_plan.path]:
            raise SemanticPatchApplyError("APPLY_PATH_OR_MODE_DRIFT")
        if _sha256(target.read_bytes()) != file_plan.preimage_sha256:
            raise SemanticPatchApplyError("APPLY_PREIMAGE_RACE")
    written_plans: list[SemanticPatchFilePlan] = []
    active_plan: SemanticPatchFilePlan | None = None
    try:
        for file_plan in plan.files:
            active_plan = file_plan
            atomic_writer(
                targets[file_plan.path],
                file_plan.postimage,
                modes[file_plan.path],
                file_plan.preimage_sha256,
            )
            written_plans.append(file_plan)
            target, mode = _safe_target(root, file_plan.path)
            if mode != modes[file_plan.path]:
                raise SemanticPatchApplyError("POST_APPLY_MODE_DRIFT")
            try:
                written = target.read_bytes()
            except OSError as error:
                raise SemanticPatchApplyError("POST_APPLY_UNAVAILABLE") from error
            if written != file_plan.postimage or _sha256(written) != file_plan.postimage_sha256:
                raise SemanticPatchApplyError("POST_APPLY_CONTENT_DRIFT")
        if _git(root, "rev-parse", "HEAD").decode("ascii").strip() != repository_commit:
            raise SemanticPatchApplyError("POST_APPLY_COMMIT_DRIFT")
        if _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip() != repository_tree:
            raise SemanticPatchApplyError("POST_APPLY_TREE_DRIFT")
        _verify_expected_dirty(root, [item.path for item in plan.files])
    except Exception as original_error:
        # A patch may span the catalog skeleton and its external value set.
        # Restore every changed target in reverse order so a failure on a
        # later file cannot leave a half-applied semantic wave.  A writer may
        # also publish successfully and then fail during its own durability
        # checks, before the caller can record success; inspect that active
        # target and include it in the rollback CAS when its bytes changed.
        try:
            rollback: list[tuple[SemanticPatchFilePlan, str]] = [
                (item, item.postimage_sha256) for item in written_plans
            ]
            if active_plan is not None and active_plan not in written_plans:
                current = targets[active_plan.path].read_bytes()
                if current != active_plan.preimage:
                    rollback.append((active_plan, _sha256(current)))
            for file_plan, expected_current_sha256 in reversed(rollback):
                atomic_writer(
                    targets[file_plan.path],
                    file_plan.preimage,
                    modes[file_plan.path],
                    expected_current_sha256,
                )
            _verify_rollback_state(
                root,
                repository_commit=repository_commit,
                repository_tree=repository_tree,
                targets=targets,
                modes=modes,
                plans=plan.files,
            )
        except Exception as rollback_error:
            raise SemanticPatchApplyError("APPLY_ROLLBACK_FAILED") from rollback_error
        if isinstance(original_error, SemanticPatchApplyError):
            raise original_error
        raise SemanticPatchApplyError("ATOMIC_WRITER_FAILED") from original_error

    files = [
        {
            "path": item.path,
            "preimage_sha256": item.preimage_sha256,
            "postimage_sha256": item.postimage_sha256,
        }
        for item in plan.files
    ]
    body: dict[str, Any] = {
        "schema_version": 1,
        "contract_id": RECEIPT_CONTRACT,
        "repository_commit": repository_commit,
        "repository_tree": repository_tree,
        "patch_sha256": plan.patch_sha256,
        "counts": {
            "files_in": len(source_files),
            "files_written": len(files),
            "operations": plan.operation_count,
            "gaps": 0,
        },
        "files": files,
        "payload_redacted": True,
    }
    return {**body, "receipt_sha256": _identity_hash(body)}


def promote_semantic_patch_review(
    *,
    tenant_root: Path,
    repository_commit: str,
    repository_tree: str,
    patch: Mapping[str, Any],
    technical_roster: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    draft_apply_receipt: Mapping[str, Any],
    review_receipt_sha256: str,
    reviewer: str,
    allowlisted_paths: Sequence[str],
    atomic_writer: AtomicWriter = atomic_replace_if_current,
) -> dict[str, Any]:
    """Promote one completely reviewed candidate from ``draft`` to ``reviewed``."""

    if not callable(atomic_writer):
        raise SemanticPatchApplyError("ATOMIC_WRITER_INVALID")
    if not isinstance(reviewer, str) or _OPAQUE_RE.fullmatch(reviewer) is None:
        raise SemanticPatchApplyError("REVIEWER_INVALID")
    if (
        not isinstance(review_receipt_sha256, str)
        or _HASH_RE.fullmatch(review_receipt_sha256) is None
    ):
        raise SemanticPatchApplyError("REVIEW_RECEIPT_INVALID")
    root = _safe_root(tenant_root)
    if _git(root, "rev-parse", "HEAD").decode("ascii").strip() != repository_commit:
        raise SemanticPatchApplyError("TENANT_COMMIT_DRIFT")
    if _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip() != repository_tree:
        raise SemanticPatchApplyError("TENANT_TREE_DRIFT")
    allowed = _allowlist(allowlisted_paths)
    _verify_expected_dirty(root, allowed)
    source_files: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    targets: dict[str, Path] = {}
    for path in allowed:
        target, mode = _safe_target(root, path)
        try:
            raw = target.read_bytes()
        except OSError as error:
            raise SemanticPatchApplyError("APPLY_PREIMAGE_UNAVAILABLE") from error
        source_files[path] = raw
        modes[path] = mode
        targets[path] = target
    preimage_files = {path: _git_file(root, repository_commit, path) for path in allowed}
    plan = plan_semantic_review_promotion(
        source_files=source_files,
        preimage_files=preimage_files,
        patch=patch,
        technical_roster=technical_roster,
        draft_apply_receipt=draft_apply_receipt,
        repository_commit=repository_commit,
        repository_tree=repository_tree,
        allowlisted_paths=allowed,
    )

    _verify_expected_dirty(root, allowed)
    for file_plan in plan.files:
        target, mode = _safe_target(root, file_plan.path)
        if target != targets[file_plan.path] or mode != modes[file_plan.path]:
            raise SemanticPatchApplyError("APPLY_PATH_OR_MODE_DRIFT")
        if _sha256(target.read_bytes()) != file_plan.preimage_sha256:
            raise SemanticPatchApplyError("APPLY_PREIMAGE_RACE")
    written_plans: list[SemanticPatchFilePlan] = []
    active_plan: SemanticPatchFilePlan | None = None
    try:
        for file_plan in plan.files:
            active_plan = file_plan
            atomic_writer(
                targets[file_plan.path],
                file_plan.postimage,
                modes[file_plan.path],
                file_plan.preimage_sha256,
            )
            written_plans.append(file_plan)
            target, mode = _safe_target(root, file_plan.path)
            if mode != modes[file_plan.path]:
                raise SemanticPatchApplyError("POST_APPLY_MODE_DRIFT")
            written = target.read_bytes()
            if written != file_plan.postimage or _sha256(written) != file_plan.postimage_sha256:
                raise SemanticPatchApplyError("POST_APPLY_CONTENT_DRIFT")
        if _git(root, "rev-parse", "HEAD").decode("ascii").strip() != repository_commit:
            raise SemanticPatchApplyError("POST_APPLY_COMMIT_DRIFT")
        if _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip() != repository_tree:
            raise SemanticPatchApplyError("POST_APPLY_TREE_DRIFT")
        _verify_expected_dirty(root, allowed)
    except Exception as original_error:
        try:
            rollback: list[tuple[SemanticPatchFilePlan, str]] = [
                (item, item.postimage_sha256) for item in written_plans
            ]
            if active_plan is not None and active_plan not in written_plans:
                current = targets[active_plan.path].read_bytes()
                if current != active_plan.preimage:
                    rollback.append((active_plan, _sha256(current)))
            for file_plan, expected_current_sha256 in reversed(rollback):
                atomic_writer(
                    targets[file_plan.path],
                    file_plan.preimage,
                    modes[file_plan.path],
                    expected_current_sha256,
                )
            _verify_rollback_state(
                root,
                repository_commit=repository_commit,
                repository_tree=repository_tree,
                targets=targets,
                modes=modes,
                plans=plan.files,
            )
        except Exception as rollback_error:
            raise SemanticPatchApplyError("APPLY_ROLLBACK_FAILED") from rollback_error
        if isinstance(original_error, SemanticPatchApplyError):
            raise original_error
        raise SemanticPatchApplyError("ATOMIC_WRITER_FAILED") from original_error

    files = [
        {
            "path": item.path,
            "draft_sha256": item.preimage_sha256,
            "reviewed_sha256": item.postimage_sha256,
        }
        for item in plan.files
    ]
    body: dict[str, Any] = {
        "schema_version": 1,
        "contract_id": PROMOTION_RECEIPT_CONTRACT,
        "repository_commit": repository_commit,
        "repository_tree": repository_tree,
        "candidate_patch_sha256": plan.patch_sha256,
        "draft_apply_receipt_sha256": draft_apply_receipt["receipt_sha256"],
        "review_receipt_sha256": review_receipt_sha256,
        "reviewer": reviewer,
        "counts": {
            "files_in": len(source_files),
            "files_written": len(files),
            "reviewed_operations": plan.operation_count,
            "gaps": 0,
        },
        "files": files,
        "payload_redacted": True,
    }
    return {**body, "receipt_sha256": _identity_hash(body)}


__all__ = [
    "APPLY_CONTRACT",
    "PROMOTION_RECEIPT_CONTRACT",
    "RECEIPT_CONTRACT",
    "SemanticPatchApplyError",
    "SemanticPatchApplyPlan",
    "SemanticPatchFilePlan",
    "SemanticTextEdit",
    "apply_semantic_patch",
    "atomic_replace_if_current",
    "plan_semantic_patch_apply",
    "plan_semantic_review_promotion",
    "promote_semantic_patch_review",
]
