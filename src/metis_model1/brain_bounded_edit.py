"""Fail-closed, lossless bounded edit renderer.

This is intentionally a small source-span engine, not a substitute for the
pinned Metis AST.  It accepts a host-issued edit plan containing only opaque
selection references, replaces one existing ``include where`` body, and
preserves every byte outside that body.  Any surface which cannot be proven
safe is declined with ``None``.

The returned candidate has an explicit local generator name.  The existing
``ModelCandidate`` contract does not yet admit that name; integration should
extend that enum only after this module's source is still checked by the
existing grounding oracle and compiler.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from metis_model1.brain_candidate_grounding import (
    _block_end,
    _endpoint_blocks,
    _scan_string,
    _scan_take_directive,
    _skip_trivia,
    _take_region_end,
    _word_at,
    source_take_contract,
    take_contract,
)
from metis_model1.brain_protocol import MAX_SOURCE_BYTES, bytes_sha256

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_REF = re.compile(r"^[a-z][a-z0-9_]*:[A-Za-z0-9._~-]{1,160}$")
_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_INCLUDE = re.compile(r"\binclude\s+where\s*\{")
_PREDICATE = re.compile(
    r"^\s*@([A-Za-z_][A-Za-z0-9_.-]*)\s+"
    r"(is|in|has|has any)\s+(.+?)\s*$"
)
_SUPPORTED_TAIL = re.compile(
    r"\s*\}\s*(?:order\s+by\s+@[A-Za-z_][A-Za-z0-9_.-]*\s+(?:ascending|descending)\s+)?"
    r"return\s+response\.expanded\s*\}\s*\Z",
    re.DOTALL,
)


@dataclass(frozen=True)
class BoundedEditCandidate:
    """Candidate surface produced without model text or source rewriting."""

    source: str
    model_revision: str = "unavailable"
    adapter_sha256: str = "unavailable"
    generator: str = "bounded_edit_renderer"


def _no_comments(source: str) -> bool:
    """Reject comments in the target region; trivia would make spans ambiguous."""

    return "//" not in source and "/*" not in source and "*/" not in source


def _include_span(source: str, start: int, end: int) -> tuple[int, int] | None:
    matches: list[tuple[int, int]] = []
    index = start
    while index < end:
        if source[index].isspace():
            index += 1
            continue
        if source[index] == '"':
            try:
                _, index = _scan_string(source, index)
            except Exception:
                return None
            continue
        match = _INCLUDE.match(source, index)
        if match is not None and match.end() <= end:
            opening = source.find("{", match.start(), match.end())
            if opening < 0:
                return None
            try:
                closing = _block_end(source, opening)
            except Exception:
                return None
            if closing >= end:
                return None
            matches.append((opening + 1, closing))
            index = closing + 1
            continue
        index += 1
    return matches[0] if len(matches) == 1 else None


def _take_regions(source: str, start: int, end: int) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    index = start
    while index < end:
        if source[index].isspace() or source.startswith(("//", "/*"), index):
            index = _skip_trivia(source, index)
            continue
        if source[index] == '"':
            _, index = _scan_string(source, index)
            continue
        if source[index] == "{":
            index = _block_end(source, index) + 1
            continue
        if _word_at(source, index, "take"):
            _directive, next_index = _scan_take_directive(source, index + 4)
            if _directive is None:
                return []
            regions.append((index, _take_region_end(source, index, end)))
            index = next_index
            continue
        index += 1
    return regions


def _strict_predicate_lines(body: str) -> bool:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines or len(lines) > 32:
        return False
    for line in lines:
        match = _PREDICATE.fullmatch(line)
        if match is None:
            return False
        operator, right = match.group(2), match.group(3)
        try:
            value = json.loads(right)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if operator in {"is", "has"}:
            if not isinstance(value, str) or not value:
                return False
        elif (
            not isinstance(value, list)
            or len(value) < 2
            or len(value) > 64
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value))
        ):
            return False
    return True


def _selection_surface(selection_refs: Sequence[str], grounding: Mapping[str, Any]) -> str | None:
    refs = grounding.get("refs")
    selections = grounding.get("selections")
    if not isinstance(refs, Mapping) or not isinstance(selections, list):
        return None
    fields = refs.get("fields")
    values = refs.get("values")
    if not isinstance(fields, Mapping) or not isinstance(values, Mapping):
        return None
    by_ref = {item.get("selection_ref"): item for item in selections if isinstance(item, Mapping)}
    if len(by_ref) != len(selections) or set(selection_refs) != set(by_ref):
        return None
    rendered: list[str] = []
    for selection in selections:
        selection_ref = selection.get("selection_ref")
        field_ref = selection.get("field_ref")
        value_refs = selection.get("value_refs")
        if (
            not isinstance(selection_ref, str)
            or not _REF.fullmatch(selection_ref)
            or not isinstance(field_ref, str)
            or not _REF.fullmatch(field_ref)
            or not isinstance(value_refs, list)
            or not value_refs
            or len(value_refs) > 64
            or any(not isinstance(item, str) or not _REF.fullmatch(item) for item in value_refs)
        ):
            return None
        field = fields.get(field_ref)
        if (
            not isinstance(field, Mapping)
            or not isinstance(field.get("name"), str)
            or _NAME.fullmatch(field["name"]) is None
            or field.get("type") != "keyword"
            or not isinstance(field.get("modifiers"), list)
            or any(item not in {"multi", "ordered"} for item in field["modifiers"])
            or len(field["modifiers"]) != len(set(field["modifiers"]))
            or not isinstance(field.get("domain"), Mapping)
            or field["domain"].get("kind") not in {"inline", "enum"}
        ):
            return None
        literals: list[str] = []
        for value_ref in value_refs:
            value = values.get(value_ref)
            if (
                not isinstance(value, Mapping)
                or not isinstance(value.get("literal"), str)
                or not value["literal"]
                or value.get("field_ref") != field_ref
                or value.get("state") != "reviewed"
            ):
                return None
            try:
                if len(value["literal"].encode("utf-8")) > MAX_SOURCE_BYTES:
                    return None
            except UnicodeEncodeError:
                return None
            literals.append(value["literal"])
        if len(literals) != len(set(literals)):
            return None
        multi = "multi" in field["modifiers"]
        if len(literals) == 1:
            operator = "has" if multi else "is"
            right = json.dumps(literals[0], ensure_ascii=False)
        else:
            operator = "has any" if multi else "in"
            right = "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in literals) + "]"
        rendered.append(f"@{field['name']} {operator} {right}")
    return "\n".join(f"      {item}" for item in rendered)


def render_bounded_edit(
    *,
    plan: Mapping[str, Any],
    source: str,
    grounding: Mapping[str, Any],
    expected_context_revision: str,
    expected_semantic_source_revision: str,
    model_revision: str = "unavailable",
    adapter_sha256: str = "unavailable",
) -> BoundedEditCandidate | None:
    """Render one exact-ref finite edit, or decline it safely."""

    if (
        not isinstance(plan, Mapping)
        or set(plan)
        != {
            "schema_version",
            "operation",
            "target_endpoint",
            "base_sha256",
            "context_revision",
            "semantic_source_revision",
            "selection_refs",
        }
        or plan.get("schema_version") != 1
        or plan.get("operation") != "edit"
        or not isinstance(plan.get("target_endpoint"), str)
        or _NAME.fullmatch(plan["target_endpoint"]) is None
        or not isinstance(plan.get("base_sha256"), str)
        or not _SHA.fullmatch(plan["base_sha256"])
        or not isinstance(plan.get("context_revision"), str)
        or plan["context_revision"] != expected_context_revision
        or not isinstance(plan.get("semantic_source_revision"), str)
        or plan["semantic_source_revision"] != expected_semantic_source_revision
        or not isinstance(plan.get("selection_refs"), list)
        or not plan["selection_refs"]
        or len(plan["selection_refs"]) > 32
        or any(
            not isinstance(item, str) or not _REF.fullmatch(item) for item in plan["selection_refs"]
        )
        or len(plan["selection_refs"]) != len(set(plan["selection_refs"]))
    ):
        return None
    if (
        not isinstance(source, str)
        or not source
        or len(source.encode("utf-8")) > MAX_SOURCE_BYTES
        or bytes_sha256(source.encode("utf-8")) != plan["base_sha256"]
        or not isinstance(grounding, Mapping)
        or grounding.get("status") != "resolved"
        or grounding.get("context_revision") != expected_context_revision
        or grounding.get("semantic_source_revision") != expected_semantic_source_revision
        or grounding.get("catalogs") is None
        or not isinstance(grounding.get("output_contract"), Mapping)
        or grounding["output_contract"].get("fallback") != {"mode": "none"}
    ):
        return None
    endpoint = plan["target_endpoint"]
    try:
        endpoints = _endpoint_blocks(source)
        matches = [item for item in endpoints if item[0] == endpoint]
        regions = _take_regions(source, matches[0][1], matches[0][2])
        take = source_take_contract(source, endpoint)
        expected_take = take_contract(grounding)
    except Exception:
        return None
    if len(matches) != 1 or len(regions) != 1 or expected_take != take:
        return None
    endpoint_start, endpoint_end = matches[0][1:]
    if not _no_comments(source[endpoint_start:endpoint_end]):
        return None
    take_start, take_end = regions[0]
    include = _include_span(source, take_start, take_end)
    if include is None:
        return None
    include_start, include_end = include
    if not _strict_predicate_lines(source[include_start:include_end]):
        return None
    if not _SUPPORTED_TAIL.fullmatch(source[include_end:take_end]):
        return None
    replacement = _selection_surface(plan["selection_refs"], grounding)
    if replacement is None:
        return None
    rendered = source[:include_start] + "\n" + replacement + source[include_end:]
    try:
        rendered_bytes = rendered.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (
        len(rendered_bytes) > MAX_SOURCE_BYTES
        or bytes_sha256(rendered_bytes) == plan["base_sha256"]
    ):
        return None
    return BoundedEditCandidate(
        source=rendered,
        model_revision=model_revision,
        adapter_sha256=adapter_sha256,
    )


__all__ = ["BoundedEditCandidate", "render_bounded_edit"]
