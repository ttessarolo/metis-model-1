"""Deterministic fast path for fully reviewed finite create requests.

The semantic retriever has already done the language-to-catalog work before
this renderer runs.  This module merely serializes that closed, reviewed
selection into the smallest canonical endpoint surface.  It deliberately
returns ``None`` for edits, open domains, unsupported types, incomplete
context, or any ambiguity so the qualified model path remains authoritative
for those cases.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from metis_model1.brain_candidate_grounding import take_contract
from metis_model1.brain_model_runtime import ModelCandidate

_QUALIFIED_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_ENDPOINT_REFERENCE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,95}$")
_CATALOG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_FINITE_DOMAIN_KINDS = frozenset({"inline", "enum"})


def _reviewed(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("state") == "reviewed"


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _field_context(context: Mapping[str, Any], field: str) -> Mapping[str, Any] | None:
    fields = context.get("fields")
    if not isinstance(fields, list):
        return None
    matches = [item for item in fields if isinstance(item, Mapping) and item.get("name") == field]
    return matches[0] if len(matches) == 1 else None


def _selected_literals(selection: Mapping[str, Any]) -> tuple[str, ...] | None:
    literal = selection.get("literal")
    literals = selection.get("literals")
    if (
        isinstance(literal, str)
        and literal
        and literals is None
        and selection.get("value_mode") is None
    ):
        return (literal,)
    if (
        literal is None
        and isinstance(literals, list)
        and 2 <= len(literals) <= 64
        and all(isinstance(item, str) and item for item in literals)
        and len(literals) == len(set(literals))
        and selection.get("value_mode") == "any_of"
    ):
        return tuple(literals)
    return None


def _predicate(selection: Mapping[str, Any], context: Mapping[str, Any]) -> str | None:
    field = selection.get("field")
    catalog = selection.get("catalog")
    field_type = selection.get("type")
    modifiers = selection.get("modifiers")
    domain = selection.get("domain")
    if (
        not isinstance(field, str)
        or _FIELD_RE.fullmatch(field) is None
        or not isinstance(catalog, str)
        or field_type != "keyword"
        or not isinstance(modifiers, list)
        or any(item not in {"multi", "ordered"} for item in modifiers)
        or len(modifiers) != len(set(modifiers))
        or not isinstance(domain, Mapping)
        or domain.get("kind") not in _FINITE_DOMAIN_KINDS
    ):
        return None
    literals = _selected_literals(selection)
    if literals is None:
        return None

    projected = _field_context(context, field)
    if (
        projected is None
        or projected.get("type") != field_type
        or projected.get("modifiers") != modifiers
        or projected.get("domain") != dict(domain)
        or not _reviewed(projected.get("semantic"))
    ):
        return None
    values = projected.get("values")
    if not isinstance(values, list):
        return None
    reviewed_literals = {
        item.get("literal")
        for item in values
        if isinstance(item, Mapping) and _reviewed(item.get("semantic"))
    }
    if set(literals) - reviewed_literals:
        return None

    multi = "multi" in modifiers
    if len(literals) == 1:
        operator = "has" if multi else "is"
        right = _quoted(literals[0])
    else:
        operator = "has any" if multi else "in"
        right = "[" + ", ".join(_quoted(item) for item in literals) + "]"
    return f"@{field} {operator} {right}"


def render_grounded_create(
    *,
    request: Any,
    retrieved: Any,
    model_revision: str,
    adapter_sha256: str,
) -> ModelCandidate | None:
    """Render one safe create candidate or decline the fast path."""

    target = getattr(request, "target", None)
    if (
        getattr(request, "intent", None) != "create"
        or not isinstance(target, Mapping)
        or target.get("mode") != "create"
        or target.get("base_sha256") is not None
    ):
        return None
    endpoint = target.get("endpoint")
    if not isinstance(endpoint, str) or _QUALIFIED_NAME_RE.fullmatch(endpoint) is None:
        return None
    reference = target.get("reference")
    if reference is not None and (
        not isinstance(reference, str) or _ENDPOINT_REFERENCE_RE.fullmatch(reference) is None
    ):
        return None

    context = getattr(retrieved, "context", None)
    grounding = getattr(retrieved, "grounding", None)
    if (
        not isinstance(context, Mapping)
        or context.get("semantic_schema") != 2
        or context.get("language_version") != "0.43"
        or context.get("context_revision") != getattr(request, "expected_context_revision", None)
        or context.get("semantic_source_revision")
        != getattr(request, "expected_semantic_source_revision", None)
        or not isinstance(context.get("toolchain_binding"), str)
        or not context["toolchain_binding"].startswith("sha256:")
        or not isinstance(grounding, Mapping)
        or grounding.get("status") != "resolved"
        or grounding.get("candidates") not in (None, [])
        or grounding.get("unresolved") not in (None, [])
    ):
        return None
    catalogs = grounding.get("catalogs")
    catalog_context = context.get("catalog")
    if (
        not isinstance(catalogs, list)
        or len(catalogs) != 1
        or not isinstance(catalogs[0], str)
        or not isinstance(catalog_context, Mapping)
        or catalog_context.get("name") != catalogs[0]
        or not _reviewed(catalog_context.get("semantic"))
    ):
        return None
    catalog = catalogs[0]
    if _CATALOG_RE.fullmatch(catalog) is None:
        return None

    selections = grounding.get("selections")
    if not isinstance(selections, list) or not selections or len(selections) > 32:
        return None
    predicates: list[str] = []
    for selection in selections:
        if not isinstance(selection, Mapping) or selection.get("catalog") != catalogs[0]:
            return None
        predicate = _predicate(selection, context)
        if predicate is None:
            return None
        predicates.append(predicate)

    output = grounding.get("output_contract")
    if not isinstance(output, Mapping) or output.get("fallback") != {"mode": "none"}:
        return None
    take = take_contract(grounding)
    if take is None:
        return None
    if take.mode == "count":
        if take.value is None:
            return None
        take_surface = f"take {take.value}"
    elif take.value is None:
        take_surface = "take page"
    else:
        take_surface = f"take page default {take.value}"

    condition_lines = "\n".join(f"      {item}" for item in predicates)
    reference_surface = f" as {_quoted(reference)}" if reference is not None else ""
    source = (
        "metis 0.43\n\n"
        f"endpoint {endpoint}{reference_surface} {{\n"
        f"  {take_surface} from @{catalog} {{\n"
        "    include where {\n"
        f"{condition_lines}\n"
        "    }\n"
        "    return response.default\n"
        "  }\n"
        "}\n"
    )
    return ModelCandidate(
        source=source,
        model_revision=model_revision,
        adapter_sha256=adapter_sha256,
        generator="grounded_renderer",
    )


__all__ = ["render_grounded_create"]
