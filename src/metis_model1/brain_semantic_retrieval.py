"""Schema-2 catalog retrieval bound to one Brain tenant snapshot.

The runner which obtains a normalized schema-2 projection is deliberately
injected.  This module never executes Node, reads a tenant path, refreshes an
index, or performs a live lookup.  It validates and indexes only the immutable
``OperationLease.snapshot`` supplied by the session manager.

The canonical index used here is the existing deterministic semantic-index v1
projection.  Schema-2 is the input contract; ``resolve_grounding`` remains the
host-owned authority which excludes draft/unannotated values, never materializes
``open`` domains, and asks for clarification on deterministic ties.
"""

from __future__ import annotations

import copy
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from metis_model1.brain_intent_ir import IntentCompileRequest, IntentIR
from metis_model1.brain_output_contract import parse_output_request
from metis_model1.brain_protocol import BrainError, canonical_json, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_sessions import OperationLease
from metis_model1.video_catalog_projection import PROJECTION_CONTRACT
from metis_model1.video_semantic_index import (
    build_semantic_index,
    resolve_grounding,
    validate_semantic_index,
)

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_CATALOGS = 64
MAX_FIELDS = 256
MAX_VALUES_PER_FIELD = 128
MAX_VALUES_TOTAL = 512
MAX_CONTEXT_BYTES = 256 * 1024
MAX_CATALOG_LABEL = 256
MAX_TEMPLATE_BYTES = 16 * 1024
MAX_TEMPLATES = 2
MAX_GROUNDING_PASSES = 16
_CLAUSE_SPLIT_RE = re.compile(r"[,;]|(?<!\w)(?:che|con)(?!\w)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]+")
_INSTRUCTION_STOPWORDS = frozenset(
    {
        "a",
        "abbia",
        "al",
        "alla",
        "anche",
        "avere",
        "che",
        "con",
        "contenuti",
        "contenuto",
        "crea",
        "creare",
        "da",
        "dei",
        "del",
        "della",
        "delle",
        "di",
        "e",
        "ed",
        "endpoint",
        "gli",
        "hanno",
        "i",
        "il",
        "in",
        "la",
        "le",
        "lo",
        "mi",
        "modifica",
        "nel",
        "nella",
        "nuovo",
        "nuova",
        "per",
        "seleziona",
        "selezioni",
        "sia",
        "siano",
        "su",
        "un",
        "una",
        "usando",
        "usa",
        "video",
        "voglio",
    }
)
_STRUCTURAL_REFINEMENT_TOKENS = frozenset(
    {
        "aumenta",
        "default",
        "diminuisci",
        "imposta",
        "limite",
        "numero",
        "pagina",
        "paginazione",
        "paginata",
        "paginato",
        "porta",
        "risultati",
    }
)
_ENDPOINT_LABEL_REFINEMENT_PATTERNS = (
    re.compile(
        r'^rinomina\s+l[\'’]endpoint\s+(?:in|come)\s+"[^"\r\n]{1,128}"$',
        re.IGNORECASE,
    ),
    re.compile(
        r'^cambia\s+l[\'’]etichetta\s+dell[\'’]endpoint\s+(?:in|con)\s+"[^"\r\n]{1,128}"$',
        re.IGNORECASE,
    ),
    re.compile(
        r"^rendi\s+(?:pi[uù]\s+)?(?:chiara|breve|leggibile|descrittiva|esplicita)\s+"
        r"l['’]etichetta\s+dell['’]endpoint$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^rendi\s+l['’]etichetta\s+dell['’]endpoint\s+(?:pi[uù]\s+)?"
        r"(?:chiara|breve|leggibile|descrittiva|esplicita)$",
        re.IGNORECASE,
    ),
)
_AMBIGUOUS_TITLE_REFINEMENT_RE = re.compile(
    r"^(?:rendi|modifica|aggiorna|riscrivi)\s+(?:il\s+)?titolo\s+"
    r"(?:pi[uù]\s+)?(?:chiaro|breve|leggibile|descrittivo|esplicito)$",
    re.IGNORECASE,
)
_SEMANTIC_REFINEMENT_PATTERNS = (
    (
        "replace",
        re.compile(
            r"^sostituisci\s+(?P<old>.+?)\s+con\s+(?P<new>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "replace",
        re.compile(
            r"^cambia\s+(?P<old>.+?)\s+in\s+(?P<new>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "replace",
        re.compile(
            r"^usa\s+(?P<new>.+?)\s+invece\s+di\s+(?P<old>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "replace",
        re.compile(
            r"^rimuovi\s+(?P<old>.+?)\s+e\s+usa\s+(?P<new>.+)$",
            re.IGNORECASE,
        ),
    ),
    ("add", re.compile(r"^aggiungi\s+(?P<new>.+)$", re.IGNORECASE)),
    ("add", re.compile(r"^includi\s+anche\s+(?P<new>.+)$", re.IGNORECASE)),
    ("remove", re.compile(r"^rimuovi\s+(?P<old>.+)$", re.IGNORECASE)),
    ("remove", re.compile(r"^elimina\s+(?P<old>.+)$", re.IGNORECASE)),
)


class SnapshotProjectionLoader(Protocol):
    """Load one normalized schema-2 projection from exactly this snapshot."""

    def __call__(self, snapshot: Any) -> LoadedProjection: ...


@dataclass(frozen=True)
class LoadedProjection:
    """Required loader envelope with explicit stale-snapshot bindings."""

    projection: Mapping[str, Any]
    snapshot_revision: str
    semantic_source_revision: str | None = None


@dataclass(frozen=True)
class _IndexedSnapshot:
    index: dict[str, Any]
    catalogs: tuple[dict[str, Any], ...]
    field_technical: dict[tuple[str, str], dict[str, Any]]


@dataclass(frozen=True)
class _SemanticRefinement:
    operation: str
    old: str | None
    new: str | None


def _fail(code: str, message: str, status: int = 409) -> None:
    raise BrainError(code, status, message)


def _safe_text(value: Any, label: str, maximum: int = 16_384) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail("RETRIEVAL_INVALID", f"{label} is invalid")
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value):
        _fail("RETRIEVAL_INVALID", f"{label} contains a control character")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        _fail("RETRIEVAL_INVALID", f"{label} is invalid")
    return value


def _source_paths(snapshot: Any) -> set[str]:
    files = getattr(snapshot, "files", None)
    if not isinstance(files, tuple):
        _fail("RETRIEVAL_INVALID", "snapshot file roster is invalid")
    paths: set[str] = set()
    for item in files:
        path = getattr(item, "path", None)
        if not isinstance(path, str) or not path or path in paths:
            _fail("RETRIEVAL_INVALID", "snapshot file roster is invalid")
        paths.add(path)
    return paths


def _validate_loader_binding(
    loaded: LoadedProjection,
    snapshot: Any,
    expected_semantic_revision: str,
    source_paths: set[str],
) -> Mapping[str, Any]:
    if not isinstance(loaded, LoadedProjection):
        _fail("STALE_CONTEXT", "semantic projection has no snapshot binding")
    if loaded.snapshot_revision != snapshot.revision:
        _fail("STALE_CONTEXT", "semantic projection belongs to another snapshot")
    if loaded.semantic_source_revision != expected_semantic_revision:
        _fail("STALE_CONTEXT", "semantic projection revision is stale")
    projection = loaded.projection
    if not isinstance(projection, Mapping):
        _fail("RETRIEVAL_INVALID", "semantic loader did not return a projection")
    tenant = projection.get("tenant")
    if tenant not in {snapshot.tenant_id, snapshot.tenant_alias}:
        _fail("STALE_CONTEXT", "semantic projection belongs to another tenant")
    if (
        projection.get("schema") != 2
        or projection.get("projection_contract") != PROJECTION_CONTRACT
    ):
        _fail("RETRIEVAL_INVALID", "semantic projection is not normalized schema 2")
    catalogs = projection.get("catalogs")
    if not isinstance(catalogs, list) or not catalogs or len(catalogs) > MAX_CATALOGS:
        _fail("RETRIEVAL_INVALID", "semantic catalog roster is invalid")

    # The normalized projection contains source locations for effective
    # ``semantics from`` declarations.  All such locations must be in this
    # immutable snapshot; the loader cannot smuggle in another tenant's files.
    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            at = value.get("at")
            if isinstance(at, Mapping) and "file" in at:
                file_ref = at.get("file")
                if not isinstance(file_ref, str) or file_ref not in source_paths:
                    _fail("STALE_CONTEXT", "semantic source is outside the snapshot")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(projection)
    return projection


def _catalog_option_ref(catalog: str) -> str:
    return "catalog-" + canonical_sha256({"catalog": catalog})[7:31]


def _server_decisions(request: Any, kind: str) -> tuple[Mapping[str, Any], ...]:
    """Read decisions reconstructed by TurnStore, never client fields."""

    context = getattr(request, "server_clarification", None)
    if not isinstance(context, Mapping):
        return ()
    decisions = context.get("decisions")
    if isinstance(decisions, list):
        return tuple(
            decision
            for decision in decisions
            if isinstance(decision, Mapping) and decision.get("kind") == kind
        )
    return (context,) if context.get("kind") == kind else ()


def _server_decision(request: Any, kind: str) -> Mapping[str, Any] | None:
    decisions = _server_decisions(request, kind)
    return decisions[-1] if decisions else None


def _current_server_decision(request: Any, kind: str) -> Mapping[str, Any] | None:
    """Read only the decision consumed by the current server-owned turn."""

    context = getattr(request, "server_clarification", None)
    if not isinstance(context, Mapping):
        return None
    current = context.get("current_decision")
    if isinstance(current, Mapping):
        return current if current.get("kind") == kind else None
    if "decisions" not in context and context.get("kind") == kind:
        return context
    return None


def _semantic_option_ref(candidate: Mapping[str, Any]) -> str:
    return (
        "semantic-"
        + canonical_sha256(
            {
                "catalog": candidate.get("catalog"),
                "field": candidate.get("field"),
                "literal": candidate.get("literal"),
                "literals": candidate.get("literals"),
                "matched_by": candidate.get("matched_by"),
                "clause_ref": candidate.get("clause_ref"),
                "matched_surfaces": candidate.get("matched_surfaces"),
            }
        )[7:31]
    )


def _catalog_records(
    index: Mapping[str, Any], projection: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    projected = projection.get("catalogs")
    if not isinstance(projected, list):
        _fail("RETRIEVAL_INVALID", "projection catalog roster is invalid")
    semantic_sources: dict[str, str | None] = {}
    for catalog in projected:
        if not isinstance(catalog, Mapping) or not isinstance(catalog.get("name"), str):
            _fail("RETRIEVAL_INVALID", "projection catalog identity is invalid")
        name = catalog["name"]
        raw_source = catalog.get("semanticSource")
        if raw_source is None:
            semantic_sources[name] = None
        elif isinstance(raw_source, Mapping) and isinstance(raw_source.get("catalog"), str):
            semantic_sources[name] = raw_source["catalog"]
        else:
            _fail("RETRIEVAL_INVALID", "catalog semantic source is invalid")
    for catalog, source in semantic_sources.items():
        if source is None:
            continue
        if (
            source == catalog
            or source not in semantic_sources
            or semantic_sources[source] is not None
        ):
            _fail("RETRIEVAL_INVALID", "catalog semantic source is not one canonical owner")

    records: dict[str, dict[str, Any]] = {}
    for entry in index["entries"]:
        catalog = entry["catalog"]
        if entry["node_kind"] == "catalog":
            records[catalog] = {
                "catalog": catalog,
                "file": entry["at"]["file"],
                "state": entry["state"],
                "label": entry.get("label"),
                "means": entry.get("means"),
                "aka": entry.get("aka"),
                "owner": semantic_sources.get(catalog) is None,
                "semantic_source": semantic_sources.get(catalog),
                "option_ref": _catalog_option_ref(catalog),
            }
    if set(records) != set(semantic_sources):
        _fail("RETRIEVAL_INVALID", "projection and index catalog rosters differ")
    return tuple(records[name] for name in sorted(records))


def _projection_field_technical(
    projection: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Retain the exact field type/modifiers from the normalized projection."""

    result: dict[tuple[str, str], dict[str, Any]] = {}

    def walk(catalog: str, fields: Any, parent: str | None = None) -> None:
        if not isinstance(fields, list):
            _fail("RETRIEVAL_INVALID", "projection field roster is invalid")
        for raw in fields:
            if not isinstance(raw, Mapping):
                _fail("RETRIEVAL_INVALID", "projection field is invalid")
            name = raw.get("name")
            field_type = raw.get("type")
            modifiers = raw.get("modifiers")
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(field_type, str)
                or not field_type
                or not isinstance(modifiers, list)
                or any(not isinstance(item, str) for item in modifiers)
                or len(modifiers) != len(set(modifiers))
                or any(item not in {"multi", "ordered"} for item in modifiers)
            ):
                _fail("RETRIEVAL_INVALID", "projection field technical surface is invalid")
            path = name if parent is None else f"{parent}.{name}"
            key = (catalog, path)
            if key in result:
                _fail("RETRIEVAL_INVALID", "projection field technical roster has duplicates")
            result[key] = {"type": field_type, "modifiers": list(modifiers)}
            if "fields" in raw:
                walk(catalog, raw["fields"], path)

    catalogs = projection.get("catalogs")
    if not isinstance(catalogs, list):
        _fail("RETRIEVAL_INVALID", "projection catalog roster is invalid")
    for raw_catalog in catalogs:
        if not isinstance(raw_catalog, Mapping) or not isinstance(raw_catalog.get("name"), str):
            _fail("RETRIEVAL_INVALID", "projection catalog is invalid")
        walk(raw_catalog["name"], raw_catalog.get("fields"))
    return result


def _explicit_catalog(request: str, records: tuple[dict[str, Any], ...], hint: Any) -> str | None:
    if hint is not None:
        if not isinstance(hint, str) or not hint:
            _fail("RETRIEVAL_INVALID", "catalog hint is invalid", 400)
        for record in records:
            if record["catalog"] == hint or record["option_ref"] == hint:
                return record["catalog"]
        short_matches = [
            record["catalog"] for record in records if record["catalog"].rsplit(".", 1)[-1] == hint
        ]
        if len(short_matches) > 1:
            return "__ambiguous__"
        if short_matches:
            return short_matches[0]
        return "__unknown__"
    folded = request.casefold()
    matches: list[str] = []
    for record in records:
        full = record["catalog"].casefold()
        short = full.rsplit(".", 1)[-1]
        # Bare short names are accepted only with an explicit @ marker or the
        # word catalog, preventing a field/value mention from selecting a
        # mirror accidentally.
        patterns = (
            r"(?<!\w)@" + re.escape(short) + r"(?!\w)",
            r"(?<!\w)catalog(?:o)?\s+" + re.escape(short) + r"(?!\w)",
            r"(?<!\w)" + re.escape(full) + r"(?!\w)",
        )
        if any(re.search(pattern, folded) for pattern in patterns):
            matches.append(record["catalog"])
    if len(set(matches)) > 1:
        return "__ambiguous__"
    return matches[0] if matches else None


def _source_catalog(reference: str, records: tuple[dict[str, Any], ...]) -> str | None:
    """Resolve one scanner-derived ``@catalog(.member)*`` reference exactly."""

    exact = [
        record["catalog"]
        for record in records
        if reference in {record["catalog"], record["catalog"].rsplit(".", 1)[-1]}
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    prefixes = [
        record["catalog"]
        for record in records
        if reference.startswith(record["catalog"] + ".")
        or reference.startswith(record["catalog"].rsplit(".", 1)[-1] + ".")
    ]
    if not prefixes:
        return None
    longest = max(len(item) for item in prefixes)
    winners = [item for item in prefixes if len(item) == longest]
    return winners[0] if len(winners) == 1 else None


def _whole_surface(text: str, surface: str) -> bool:
    normalized = surface.casefold().strip()
    if not normalized:
        return False
    return re.search(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)", text.casefold()) is not None


def _mask_surface(text: str, surface: str) -> str:
    normalized = surface.strip()
    if not normalized:
        return text
    return re.sub(
        r"(?<!\w)" + re.escape(normalized) + r"(?!\w)",
        " ",
        text,
        flags=re.IGNORECASE,
    )


def _tokens(text: str) -> set[str]:
    return {item.casefold() for item in _TOKEN_RE.findall(text)}


def _meaningful(text: str) -> str:
    return " ".join(
        item for item in _TOKEN_RE.findall(text) if item.casefold() not in _INSTRUCTION_STOPWORDS
    )


def _is_structural_refinement(text: str) -> bool:
    raw_tokens = [token.casefold() for token in _TOKEN_RE.findall(text)]
    tokens = {
        token
        for token in raw_tokens
        if token.casefold() not in _INSTRUCTION_STOPWORDS and not token.isdigit()
    }
    return (
        any(token.isdigit() for token in raw_tokens)
        and "risultati" in raw_tokens
        and bool(tokens)
        and tokens.issubset(_STRUCTURAL_REFINEMENT_TOKENS)
    )


def _nonsemantic_refinement(text: str, catalog: str) -> str | None:
    """Classify only bounded refinements which cannot alter catalog filters."""

    scrubbed = text
    short = catalog.rsplit(".", 1)[-1]
    for surface in sorted(
        {
            f"@{catalog}",
            catalog,
            f"catalogo {catalog}",
            f"catalog {catalog}",
            f"@{short}",
            f"catalogo {short}",
            f"catalog {short}",
        },
        key=len,
        reverse=True,
    ):
        scrubbed = _mask_surface(scrubbed, surface)
    normalized = " ".join(scrubbed.split()).strip()
    if _is_structural_refinement(normalized):
        return "cardinality"
    if any(pattern.fullmatch(normalized) for pattern in _ENDPOINT_LABEL_REFINEMENT_PATTERNS):
        return "endpoint_label"
    if _AMBIGUOUS_TITLE_REFINEMENT_RE.fullmatch(normalized):
        return "ambiguous_title"
    return None


def _semantic_refinement(text: str, catalog: str) -> _SemanticRefinement | None:
    """Parse only a small, explicit semantic-delta language.

    The match is deliberately anchored.  Unrecognized prefixes, suffixes, or
    connector words remain part of an operand and must subsequently resolve
    without residue; they are never treated as harmless natural-language
    filler.
    """

    scrubbed = text
    short = catalog.rsplit(".", 1)[-1]
    surfaces = (
        f"@{catalog}",
        catalog,
        f"catalogo {catalog}",
        f"catalog {catalog}",
        f"@{short}",
        f"catalogo {short}",
        f"catalog {short}",
    )
    for surface in sorted(set(surfaces), key=len, reverse=True):
        scrubbed = _mask_surface(scrubbed, surface)
    normalized = " ".join(scrubbed.split()).strip(" \t\r\n.!?")
    if not normalized or len(normalized) > 1_024:
        return None
    for operation, pattern in _SEMANTIC_REFINEMENT_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        old = match.groupdict().get("old")
        new = match.groupdict().get("new")
        old = old.strip() if isinstance(old, str) else None
        new = new.strip() if isinstance(new, str) else None
        if old == "" or new == "":
            return None
        return _SemanticRefinement(operation=operation, old=old, new=new)
    return None


def _field_entry(index: Mapping[str, Any], catalog: str, field: str) -> Mapping[str, Any] | None:
    return next(
        (
            item
            for item in index["entries"]
            if item["node_kind"] == "field"
            and item["catalog"] == catalog
            and item["field"] == field
        ),
        None,
    )


def _candidate_selection(
    index: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any] | None:
    catalog = candidate.get("catalog")
    field = candidate.get("field")
    if not isinstance(catalog, str) or not isinstance(field, str):
        return None
    parent = _field_entry(index, catalog, field)
    if parent is None or parent.get("state") != "reviewed":
        return None
    literal = candidate.get("literal") if isinstance(candidate.get("literal"), str) else None
    literals = candidate.get("literals")
    selected_literals = (
        [literal]
        if literal is not None
        else list(literals)
        if isinstance(literals, list)
        and literals
        and all(isinstance(item, str) for item in literals)
        else []
    )
    for selected_literal in selected_literals:
        reviewed = any(
            item["node_kind"] == "value"
            and item["catalog"] == catalog
            and item["field"] == field
            and item.get("literal") == selected_literal
            and item.get("state") == "reviewed"
            for item in index["entries"]
        )
        if not reviewed:
            return None
    selection: dict[str, Any] = {
        "catalog": catalog,
        "field": field,
        "literal": literal,
        "domain": copy.deepcopy(parent["domain"]),
        "matched_by": "reviewed_semantic_disambiguation",
    }
    if literal is None and selected_literals:
        selection["literals"] = selected_literals
        selection["value_mode"] = "any_of"
    return selection


def _semantic_candidate(
    index: Mapping[str, Any], candidate: Mapping[str, Any], clause: str
) -> dict[str, Any]:
    """Add bounded, reviewed operator-facing semantics to one tied candidate."""

    value = dict(candidate)
    field = value.get("field")
    catalog = value.get("catalog")
    literal = value.get("literal")
    label = f"@{field}" if isinstance(field, str) else "Metadato"
    if isinstance(literal, str):
        label += f' = "{literal}"'
    elif isinstance(value.get("literals"), list):
        joined = ", ".join(str(item) for item in value["literals"][:3])
        label += f" in [{joined}]"
    description: str | None = None
    if isinstance(catalog, str) and isinstance(field, str):
        if isinstance(literal, str):
            entry = next(
                (
                    item
                    for item in index["entries"]
                    if item["node_kind"] == "value"
                    and item["catalog"] == catalog
                    and item["field"] == field
                    and item.get("literal") == literal
                    and item.get("state") == "reviewed"
                ),
                None,
            )
            means = entry.get("means") if isinstance(entry, Mapping) else None
            if isinstance(means, Mapping) and isinstance(means.get("text"), str):
                description = means["text"]
        if description is None:
            parent = _field_entry(index, catalog, field)
            means = parent.get("means") if isinstance(parent, Mapping) else None
            if isinstance(means, Mapping) and isinstance(means.get("text"), str):
                description = means["text"]
    surfaces: set[str] = set()
    if isinstance(field, str):
        surfaces.add(field)
    parent = (
        _field_entry(index, catalog, field)
        if isinstance(catalog, str) and isinstance(field, str)
        else None
    )
    for entry in [parent]:
        if not isinstance(entry, Mapping):
            continue
        means = entry.get("means")
        if isinstance(means, Mapping) and isinstance(means.get("text"), str):
            surfaces.add(means["text"])
        aka = entry.get("aka")
        if isinstance(aka, Mapping):
            surfaces.update(item for item in aka.get("items", []) if isinstance(item, str))
    literals = [literal] if isinstance(literal, str) else []
    if isinstance(value.get("literals"), list):
        literals.extend(item for item in value["literals"] if isinstance(item, str))
    for candidate_literal in literals:
        surfaces.add(candidate_literal)
        entry = next(
            (
                item
                for item in index["entries"]
                if item["node_kind"] == "value"
                and item["catalog"] == catalog
                and item["field"] == field
                and item.get("literal") == candidate_literal
                and item.get("state") == "reviewed"
            ),
            None,
        )
        if not isinstance(entry, Mapping):
            continue
        means = entry.get("means")
        if isinstance(means, Mapping) and isinstance(means.get("text"), str):
            surfaces.add(means["text"])
        aka = entry.get("aka")
        if isinstance(aka, Mapping):
            surfaces.update(item for item in aka.get("items", []) if isinstance(item, str))
    matched_surfaces = sorted(
        (surface for surface in surfaces if _whole_surface(clause, surface)),
        key=lambda surface: (-len(surface), surface.casefold()),
    )
    value.update(
        {
            "label": label[:256],
            "description": (description or "Significato verificato nel catalogo")[:1024],
            "clause": clause[:256],
            "clause_ref": canonical_sha256({"clause": _meaningful(clause)}),
            "matched_surfaces": matched_surfaces,
        }
    )
    value["option_ref"] = _semantic_option_ref(value)
    return value


def _candidate_score(
    index: Mapping[str, Any], instruction: str, candidate: Mapping[str, Any]
) -> tuple[int, int, int, int]:
    catalog = candidate.get("catalog")
    field = candidate.get("field")
    if not isinstance(catalog, str) or not isinstance(field, str):
        return (0, 0, 0, 0)
    parent = _field_entry(index, catalog, field)
    if parent is None or parent.get("state") != "reviewed":
        return (0, 0, 0, 0)
    technical = int(_whole_surface(instruction, field))
    aka = parent.get("aka")
    aliases = aka.get("items", []) if isinstance(aka, Mapping) else []
    alias_hits = sum(_whole_surface(instruction, item) for item in aliases)
    means = parent.get("means")
    means_text = means.get("text", "") if isinstance(means, Mapping) else ""
    semantic_tokens = _tokens(means_text + " " + " ".join(aliases))
    overlap = len((_tokens(instruction) - _INSTRUCTION_STOPWORDS) & semantic_tokens)
    negative_markers = ("legacy", "secondar", "tecnico", "iab")
    penalty = sum(marker in means_text.casefold() for marker in negative_markers)
    literal = candidate.get("literal")
    case_exact = int(
        isinstance(literal, str)
        and re.search(r"(?<!\w)" + re.escape(literal) + r"(?!\w)", instruction) is not None
    )
    return (technical * 100 + alias_hits * 50, case_exact, overlap, -penalty)


def _choose_candidate(
    index: Mapping[str, Any], instruction: str, candidates: list[Any]
) -> dict[str, Any] | None:
    valid = [item for item in candidates if isinstance(item, Mapping)]
    if not valid:
        return None
    candidate_catalogs = {
        item.get("catalog") for item in valid if isinstance(item.get("catalog"), str)
    }
    explicit_fields = {
        (item.get("catalog"), item.get("field"))
        for item in index.get("entries", [])
        if isinstance(item, Mapping)
        and item.get("node_kind") == "field"
        and item.get("state") == "reviewed"
        and item.get("catalog") in candidate_catalogs
        and isinstance(item.get("field"), str)
        and _whole_surface(instruction, item["field"])
    }
    if explicit_fields:
        # A technical field name written by the operator is authority.  A
        # shared literal must never migrate to a semantically different field,
        # including after a Flash segmentation retry.
        valid = [
            item for item in valid if (item.get("catalog"), item.get("field")) in explicit_fields
        ]
        if not valid:
            return None
    scored = [(_candidate_score(index, instruction, item), item) for item in valid]
    best = max(score for score, _item in scored)
    winners = [item for score, item in scored if score == best]
    if len(winners) != 1 or (best[0] == 0 and best[1] == 0 and best[2] == 0):
        return None
    return dict(winners[0])


def _selection_surfaces(index: Mapping[str, Any], selection: Mapping[str, Any]) -> list[str]:
    catalog = selection.get("catalog")
    field = selection.get("field")
    if not isinstance(catalog, str) or not isinstance(field, str):
        return []
    surfaces = {field}
    parent = _field_entry(index, catalog, field)
    if parent is not None and isinstance(parent.get("aka"), Mapping):
        surfaces.update(parent["aka"].get("items", []))
    literals = selection.get("literals")
    selected_literals = set(literals) if isinstance(literals, list) else set()
    literal = selection.get("literal")
    if isinstance(literal, str):
        selected_literals.add(literal)
    for item in index["entries"]:
        if (
            item["node_kind"] != "value"
            or item["catalog"] != catalog
            or item["field"] != field
            or item.get("literal") not in selected_literals
            or item.get("state") != "reviewed"
        ):
            continue
        surfaces.add(item["literal"])
        if isinstance(item.get("aka"), Mapping):
            surfaces.update(item["aka"].get("items", []))
    return sorted(
        (item for item in surfaces if isinstance(item, str) and item),
        key=len,
        reverse=True,
    )


def _selection_identity(item: Mapping[str, Any]) -> tuple[Any, ...]:
    literals = item.get("literals")
    return (
        item.get("catalog"),
        item.get("field"),
        item.get("literal"),
        tuple(literals) if isinstance(literals, list) else (),
    )


def _resolve_clause(
    index: Mapping[str, Any],
    clause: str,
    catalog: str,
    *,
    disambiguation_instruction: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    remaining = clause
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    unresolved_candidates: list[dict[str, Any]] = []
    for _attempt in range(MAX_GROUNDING_PASSES):
        result = resolve_grounding(index, remaining, catalog=catalog)
        new_selections: list[dict[str, Any]] = []
        if result.get("status") == "resolved":
            new_selections = [
                dict(item) for item in result.get("selections", []) if isinstance(item, Mapping)
            ]
        elif result.get("status") == "clarify":
            raw_candidates = result.get("candidates", [])
            chosen = _choose_candidate(
                index,
                disambiguation_instruction or remaining,
                raw_candidates,
            )
            if chosen is None:
                unresolved_candidates = [
                    _semantic_candidate(index, item, remaining)
                    for item in raw_candidates
                    if isinstance(item, Mapping)
                ]
                break
            selection = _candidate_selection(index, chosen)
            if selection is None:
                unresolved_candidates = [_semantic_candidate(index, chosen, remaining)]
                break
            new_selections = [selection]
        if not new_selections:
            break
        before = remaining
        for selection in new_selections:
            selected[_selection_identity(selection)] = selection
            for surface in _selection_surfaces(index, selection):
                if _whole_surface(remaining, surface):
                    remaining = _mask_surface(remaining, surface)
        if remaining == before:
            break
    meaningful = _meaningful(remaining)
    values = list(selected.values())
    if any(
        item.get("literal") is None
        and not item.get("literals")
        and isinstance(item.get("domain"), Mapping)
        and item["domain"].get("kind") == "open"
        for item in values
    ):
        meaningful = meaningful or clause.strip()
    return values, unresolved_candidates, meaningful or None


def _resolve_complete_grounding(
    index: Mapping[str, Any],
    request: str,
    catalog: str,
    *,
    disambiguation_instruction: str | None = None,
) -> dict[str, Any]:
    scrubbed = request
    short = catalog.rsplit(".", 1)[-1]
    # Mask qualified references before their short suffix.  Reversing this
    # order would turn ``@play-demo.video`` into the spurious semantic clause
    # ``play demo`` after masking only ``@video``.
    surfaces = (
        f"@{catalog}",
        catalog,
        f"catalogo {catalog}",
        f"catalog {catalog}",
        f"@{short}",
        f"catalogo {short}",
        f"catalog {short}",
    )
    for surface in sorted(set(surfaces), key=len, reverse=True):
        scrubbed = _mask_surface(scrubbed, surface)
    clauses = [item.strip() for item in _CLAUSE_SPLIT_RE.split(scrubbed) if item.strip()]
    if len(clauses) > MAX_GROUNDING_PASSES:
        return {
            "status": "unsupported",
            "reason": "request has too many semantic clauses",
            "candidates": [],
            "selections": [],
            "lookups": [],
            "lookup": None,
            "unresolved": [request[:256]],
        }
    selections: dict[tuple[Any, ...], dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for clause in clauses:
        clause_selections, clause_candidates, remainder = _resolve_clause(
            index,
            clause,
            catalog,
            disambiguation_instruction=disambiguation_instruction,
        )
        for item in clause_selections:
            selections[_selection_identity(item)] = item
        candidates.extend(clause_candidates)
        if remainder is not None:
            unresolved.append(remainder[:256])
    values = list(selections.values())
    fields_with_values = {
        (item.get("catalog"), item.get("field"))
        for item in values
        if item.get("literal") is not None or item.get("literals")
    }
    values = [
        item
        for item in values
        if item.get("literal") is not None
        or item.get("literals")
        or (item.get("catalog"), item.get("field")) not in fields_with_values
    ]
    if candidates:
        status = "clarify"
        reason = "grounding candidates tie for one semantic clause"
    elif unresolved or not values:
        status = "unsupported"
        reason = "one or more request clauses have no exact reviewed grounding"
    else:
        status = "resolved"
        reason = "all semantic clauses are grounded in reviewed snapshot members"
    lookups = [
        {
            "mode": "exact_on_demand",
            "owner": "retrieval_engine",
            "catalog": item["catalog"],
            "field": item["field"],
            "values": None,
        }
        for item in values
        if item.get("literal") is None
        and not item.get("literals")
        and isinstance(item.get("domain"), Mapping)
        and item["domain"].get("kind") == "open"
    ]
    return {
        "status": status,
        "reason": reason,
        "selected": values[0] if len(values) == 1 else None,
        "selections": values,
        "candidates": candidates,
        "lookup": lookups[0] if len(lookups) == 1 else None,
        "lookups": lookups,
        "unresolved": unresolved,
    }


def _apply_semantic_decision(
    index: Mapping[str, Any], grounding: dict[str, Any], option_ref: str
) -> None:
    candidates = [item for item in grounding.get("candidates", []) if isinstance(item, Mapping)]
    matches = [item for item in candidates if item.get("option_ref") == option_ref]
    if len(matches) != 1:
        raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "semantic option is unavailable")
    chosen = matches[0]
    if chosen.get("candidate_kind") == "refinement_scope":
        clause_ref = chosen.get("clause_ref")
        grounding["candidates"] = [
            dict(item)
            for item in candidates
            if not isinstance(clause_ref, str) or item.get("clause_ref") != clause_ref
        ]
        if chosen.get("scope") == "endpoint_label":
            grounding["status"] = "resolved"
            grounding["reason"] = "endpoint label refinement selected by the operator"
            grounding["unresolved"] = []
            grounding["nonsemantic_refinement"] = {
                "kind": "endpoint_label",
                "source": "server_basis",
            }
            return
        if chosen.get("scope") == "catalog_title_field":
            grounding.update(
                {
                    "status": "unsupported",
                    "reason": "catalog title refinement requires an explicit reviewed delta",
                    "selected": None,
                    "selections": [],
                    "unresolved": [str(chosen.get("clause", "title"))[:256]],
                }
            )
            return
        raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "semantic option is unavailable")
    selection = _candidate_selection(index, chosen)
    if selection is None:
        raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "semantic option is unavailable")
    clause_ref = chosen.get("clause_ref")
    selections = [
        dict(item) for item in grounding.get("selections", []) if isinstance(item, Mapping)
    ]
    selections.append(selection)
    grounding["selections"] = selections
    grounding["candidates"] = [
        dict(item)
        for item in candidates
        if not isinstance(clause_ref, str) or item.get("clause_ref") != clause_ref
    ]
    remaining: list[str] = []
    for raw in grounding.get("unresolved", []):
        if not isinstance(raw, str):
            continue
        text = raw
        if (
            isinstance(clause_ref, str)
            and canonical_sha256({"clause": _meaningful(raw)}) == clause_ref
        ):
            surfaces = list(_selection_surfaces(index, selection))
            surfaces.extend(
                item for item in chosen.get("matched_surfaces", []) if isinstance(item, str)
            )
            for surface in sorted(set(surfaces), key=len, reverse=True):
                text = _mask_surface(text, surface)
        meaningful = _meaningful(text)
        if meaningful:
            remaining.append(meaningful[:256])
    grounding["unresolved"] = remaining
    if grounding["candidates"]:
        grounding["status"] = "clarify"
        grounding["reason"] = "another semantic clause still requires confirmation"
    elif remaining:
        grounding["status"] = "unsupported"
        grounding["reason"] = "one or more request clauses have no exact reviewed grounding"
    else:
        grounding["status"] = "resolved"
        grounding["reason"] = "all semantic clauses are grounded in reviewed snapshot members"


def _basis_selections(
    index: Mapping[str, Any], basis: Any, catalog: str
) -> list[dict[str, Any]] | None:
    """Revalidate prior server-owned selections against the same semantic revision."""

    if (
        not isinstance(basis, Mapping)
        or basis.get("status") not in {None, "resolved"}
        or basis.get("catalogs") != [catalog]
        or basis.get("candidates")
        or basis.get("lookups")
        or basis.get("unresolved")
    ):
        return None
    raw_selections = basis.get("selections")
    if not isinstance(raw_selections, list) or len(raw_selections) > MAX_GROUNDING_PASSES:
        return None
    result: list[dict[str, Any]] = []
    identities: set[tuple[Any, ...]] = set()
    for raw in raw_selections:
        if not isinstance(raw, Mapping):
            return None
        selection = _candidate_selection(index, raw)
        if selection is None:
            return None
        domain = selection.get("domain")
        if isinstance(domain, Mapping) and domain.get("kind") == "open":
            return None
        identity = _selection_identity(selection)
        if identity in identities:
            return None
        identities.add(identity)
        result.append(selection)
    return result


def _refinement_operand_selection(
    index: Mapping[str, Any],
    catalog: str,
    operand: str,
    *,
    allow_field_only: bool,
) -> dict[str, Any] | None:
    """Resolve exactly one reviewed member and reject every lexical residue."""

    resolved = _resolve_complete_grounding(index, operand, catalog)
    if (
        resolved.get("status") != "resolved"
        or resolved.get("candidates")
        or resolved.get("unresolved")
        or resolved.get("lookups")
    ):
        return None
    raw_selections = [item for item in resolved.get("selections", []) if isinstance(item, Mapping)]
    if len(raw_selections) != 1:
        return None
    selection = _candidate_selection(index, raw_selections[0])
    if selection is None:
        return None
    has_value = isinstance(selection.get("literal"), str) or bool(selection.get("literals"))
    if not has_value and not allow_field_only:
        return None
    domain = selection.get("domain")
    if not has_value and (
        not isinstance(domain, Mapping) or domain.get("kind") in {"none", "open"}
    ):
        return None
    return selection


def _resolved_refinement_grounding(selections: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    return {
        "status": "resolved",
        "reason": reason,
        "selected": selections[0] if len(selections) == 1 else None,
        "selections": selections,
        "candidates": [],
        "lookup": None,
        "lookups": [],
        "unresolved": [],
    }


def _ambiguous_title_refinement_grounding(
    index: Mapping[str, Any],
    prior: list[dict[str, Any]],
    catalog: str,
    instruction: str,
) -> dict[str, Any]:
    """Build one server-resolvable scope question without guessing ``title``."""

    has_reviewed_title = any(
        item.get("node_kind") == "field"
        and item.get("catalog") == catalog
        and item.get("field") == "title"
        and item.get("state") == "reviewed"
        for item in index.get("entries", [])
        if isinstance(item, Mapping)
    )
    if not has_reviewed_title:
        return {
            "status": "resolved",
            "reason": "catalog has no reviewed title field competing with endpoint label",
            "selected": prior[0] if len(prior) == 1 else None,
            "selections": prior,
            "candidates": [],
            "lookup": None,
            "lookups": [],
            "unresolved": [],
            "nonsemantic_refinement": {
                "kind": "endpoint_label",
                "source": "server_basis",
            },
        }
    meaningful = _meaningful(instruction) or instruction.strip()
    clause = meaningful[:256]
    clause_ref = canonical_sha256({"clause": meaningful})
    candidates = [
        {
            "candidate_kind": "refinement_scope",
            "scope": "endpoint_label",
            "catalog": catalog,
            "clause": clause,
            "clause_ref": clause_ref,
            "option_ref": canonical_sha256({"clause_ref": clause_ref, "scope": "endpoint_label"}),
            "label": "Etichetta dell'endpoint",
            "description": (
                "Rende più chiaro il titolo mostrato per l'endpoint senza cambiare i filtri."
            ),
        },
        {
            "candidate_kind": "refinement_scope",
            "scope": "catalog_title_field",
            "catalog": catalog,
            "field": "title",
            "clause": clause,
            "clause_ref": clause_ref,
            "option_ref": canonical_sha256(
                {"clause_ref": clause_ref, "scope": "catalog_title_field"}
            ),
            "label": "Metadato @title",
            "description": (
                "Interviene sul filtro del titolo e richiede una modifica semantica esplicita."
            ),
        },
    ]
    return {
        "status": "clarify",
        "reason": "title can mean endpoint label or catalog metadata",
        "selected": None,
        "selections": prior,
        "candidates": candidates,
        "lookup": None,
        "lookups": [],
        "unresolved": [],
    }


def _apply_semantic_refinement(
    index: Mapping[str, Any],
    prior: list[dict[str, Any]],
    catalog: str,
    refinement: _SemanticRefinement,
) -> dict[str, Any] | None:
    new_selection: dict[str, Any] | None = None
    if refinement.new is not None:
        new_selection = _refinement_operand_selection(
            index,
            catalog,
            refinement.new,
            allow_field_only=False,
        )
        if new_selection is None:
            return None

    old_selection: dict[str, Any] | None = None
    old_matches: list[dict[str, Any]] = []
    if refinement.old is not None:
        old_selection = _refinement_operand_selection(
            index,
            catalog,
            refinement.old,
            allow_field_only=refinement.operation == "replace",
        )
        if old_selection is None:
            return None
        old_has_value = isinstance(old_selection.get("literal"), str) or bool(
            old_selection.get("literals")
        )
        if old_has_value:
            old_identity = _selection_identity(old_selection)
            old_matches = [item for item in prior if _selection_identity(item) == old_identity]
        else:
            # A field-only source can replace one prior member only when the
            # destination resolves to that exact field.  This is the sole
            # deterministic same-field shorthand.
            if (
                refinement.operation != "replace"
                or new_selection is None
                or new_selection.get("catalog") != old_selection.get("catalog")
                or new_selection.get("field") != old_selection.get("field")
            ):
                return None
            old_matches = [
                item
                for item in prior
                if item.get("catalog") == old_selection.get("catalog")
                and item.get("field") == old_selection.get("field")
            ]
        if len(old_matches) != 1:
            return None

    if refinement.operation == "add":
        if new_selection is None:
            return None
        result = list(prior)
        if all(_selection_identity(item) != _selection_identity(new_selection) for item in result):
            result.append(new_selection)
        return _resolved_refinement_grounding(
            result, "one explicitly identified reviewed selection was added"
        )

    if refinement.operation == "remove":
        if len(old_matches) != 1:
            return None
        removed = _selection_identity(old_matches[0])
        result = [item for item in prior if _selection_identity(item) != removed]
        return _resolved_refinement_grounding(
            result, "one explicitly identified reviewed selection was removed"
        )

    if refinement.operation == "replace":
        if new_selection is None or len(old_matches) != 1:
            return None
        removed = _selection_identity(old_matches[0])
        result = [item for item in prior if _selection_identity(item) != removed]
        if all(_selection_identity(item) != _selection_identity(new_selection) for item in result):
            result.append(new_selection)
        return _resolved_refinement_grounding(
            result, "one explicit reviewed selection was replaced by another"
        )
    return None


def _reject_semantic_refinement(grounding: dict[str, Any], instruction: str) -> None:
    grounding.update(
        {
            "status": "unsupported",
            "reason": "semantic refinement is not an exact reviewed add/remove/replace delta",
            "selected": None,
            "selections": [],
            "candidates": [],
            "lookup": None,
            "lookups": [],
            "unresolved": [(_meaningful(instruction) or instruction.strip())[:256]],
        }
    )


def _merge_basis_grounding(
    index: Mapping[str, Any],
    grounding: dict[str, Any],
    basis: Any,
    catalog: str,
    instruction: str,
) -> None:
    prior = _basis_selections(index, basis, catalog)
    if prior is None:
        return
    nonsemantic = _nonsemantic_refinement(instruction, catalog)
    if nonsemantic == "ambiguous_title":
        grounding.update(_ambiguous_title_refinement_grounding(index, prior, catalog, instruction))
        return
    if nonsemantic in {"cardinality", "endpoint_label"}:
        grounding.update(
            {
                "status": "resolved",
                "reason": "reviewed selections retained from the session proposal basis",
                "selected": prior[0] if len(prior) == 1 else None,
                "selections": prior,
                "candidates": [],
                "lookup": None,
                "lookups": [],
                "unresolved": [],
            }
        )
        grounding["nonsemantic_refinement"] = {
            "kind": nonsemantic,
            "source": "server_basis",
        }
        return
    refinement = _semantic_refinement(instruction, catalog)
    if refinement is None:
        _reject_semantic_refinement(grounding, instruction)
        return
    refined = _apply_semantic_refinement(index, prior, catalog, refinement)
    if refined is None:
        _reject_semantic_refinement(grounding, instruction)
        return
    grounding.update(refined)


def _semantic_catalog_candidates(
    index: Mapping[str, Any],
    request: str,
    records: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Infer a unique owner only from exact reviewed field/value evidence.

    With several owner catalogs, asking every time would be a false ambiguity:
    a request mentioning video-only reviewed aliases is already deterministic.
    We therefore resolve against every owner, select a unique highest number
    of exact semantic selections, and fail closed to clarification on a tie or
    when no owner has evidence.
    """

    owners = [item for item in records if item["owner"]]
    scored: list[tuple[int, dict[str, Any]]] = []
    for record in owners:
        result = resolve_grounding(index, request, catalog=record["catalog"])
        evidence = result.get("selections")
        if result.get("status") == "clarify":
            evidence = result.get("candidates")
        if isinstance(evidence, list) and evidence:
            identities = {
                (item.get("field"), item.get("literal"))
                for item in evidence
                if isinstance(item, Mapping) and isinstance(item.get("field"), str)
            }
            if identities:
                scored.append((len(identities), record))
    if not scored:
        return owners
    best = max(score for score, _record in scored)
    return [record for score, record in scored if score == best]


def _semantic_view(entry: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"state": entry["state"]}
    if entry["state"] == "reviewed":
        for key in ("means", "aka", "label"):
            if key in entry:
                result[key] = copy.deepcopy(entry[key])
    return result


def _snapshot_templates(snapshot: Any, selected_catalog: str) -> list[dict[str, str]]:
    """Select a tiny source-bound endpoint syntax card from the same snapshot."""

    short = selected_catalog.rsplit(".", 1)[-1]
    candidates: list[tuple[int, str, str]] = []
    for item in snapshot.files:
        path = getattr(item, "path", None)
        raw = getattr(item, "content", None)
        if not isinstance(path, str) or not path.endswith(".metis") or not isinstance(raw, bytes):
            continue
        if len(raw) > MAX_TEMPLATE_BYTES:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not re.search(r"(?m)^\s*endpoint\s+", text):
            continue
        relevance = 0 if f"@{short}" in text else 1
        candidates.append((relevance, path, text))
    return [
        {"path": path, "source": text}
        for _relevance, path, text in sorted(candidates)[:MAX_TEMPLATES]
    ]


def _bounded_context(
    index: Mapping[str, Any],
    field_technical: Mapping[tuple[str, str], Mapping[str, Any]],
    selected_catalog: str,
    grounding: Mapping[str, Any],
    snapshot: Any,
) -> dict[str, Any]:
    entries = [item for item in index["entries"] if item["catalog"] == selected_catalog]
    fields = [item for item in entries if item["node_kind"] == "field"]
    if len(fields) > MAX_FIELDS:
        _fail("RETRIEVAL_TOO_LARGE", "catalog field context exceeds the bound")
    selected_fields = {
        item.get("field")
        for item in grounding.get("selections", [])
        if isinstance(item, Mapping) and isinstance(item.get("field"), str)
    }
    selected_fields.update(
        item.get("field")
        for item in grounding.get("candidates", [])
        if isinstance(item, Mapping) and isinstance(item.get("field"), str)
    )
    selected_literals: dict[str, set[str]] = {}
    for key in ("selections", "candidates"):
        for item in grounding.get(key, []):
            if not isinstance(item, Mapping) or not isinstance(item.get("field"), str):
                continue
            literals: list[str] = []
            if isinstance(item.get("literal"), str):
                literals.append(item["literal"])
            if isinstance(item.get("literals"), list):
                literals.extend(value for value in item["literals"] if isinstance(value, str))
            if literals:
                selected_literals.setdefault(item["field"], set()).update(literals)
    values_by_field: dict[str, list[dict[str, Any]]] = {}
    total_values = 0
    for entry in entries:
        if entry["node_kind"] != "value" or entry["state"] != "reviewed":
            continue
        if entry["field"] not in selected_fields:
            continue
        if entry["literal"] not in selected_literals.get(entry["field"], set()):
            continue
        values = values_by_field.setdefault(entry["field"], [])
        if len(values) >= MAX_VALUES_PER_FIELD or total_values >= MAX_VALUES_TOTAL:
            _fail("RETRIEVAL_TOO_LARGE", "selected value context exceeds the bound")
        value = {"literal": entry["literal"], "semantic": _semantic_view(entry)}
        values.append(value)
        total_values += 1
    field_context: list[dict[str, Any]] = []
    for entry in fields:
        technical = field_technical.get((selected_catalog, entry["field"]))
        if technical is None:
            _fail("RETRIEVAL_INVALID", "selected field technical surface is unavailable")
        domain = dict(entry["domain"])
        field: dict[str, Any] = {
            "name": entry["field"],
            "type": technical["type"],
            "modifiers": list(technical["modifiers"]),
            "domain": domain,
            "semantic": _semantic_view(entry),
        }
        # Open and none domains deliberately have no values.  Finite values
        # are included only for fields the deterministic resolver selected.
        if entry["field"] in values_by_field:
            field["values"] = values_by_field[entry["field"]]
        field_context.append(field)
    catalog_entry = next(item for item in entries if item["node_kind"] == "catalog")
    context: dict[str, Any] = {
        "language_version": "0.43",
        "semantic_schema": 2,
        "tenant_alias": snapshot.tenant_alias,
        "tenant_id": snapshot.tenant_id,
        "context_revision": snapshot.revision,
        "semantic_source_revision": index["semantic_source_revision"],
        "toolchain_binding": snapshot.toolchain_binding,
        "catalog": {
            "name": selected_catalog,
            "file": catalog_entry["at"]["file"],
            "semantic": _semantic_view(catalog_entry),
        },
        "fields": field_context,
        "endpoint_templates": _snapshot_templates(snapshot, selected_catalog),
    }
    if len(canonical_json(context)) > MAX_CONTEXT_BYTES:
        _fail("RETRIEVAL_TOO_LARGE", "model context exceeds the byte bound")
    return context


def _bounded_source_context(
    index: Mapping[str, Any],
    field_technical: Mapping[tuple[str, str], Mapping[str, Any]],
    catalogs: tuple[str, ...],
    grounding: Mapping[str, Any],
    snapshot: Any,
) -> dict[str, Any]:
    """Build one explicit, bounded context for an existing multi-catalog source.

    ``catalogs`` is the server-observed source roster, not an ordered list of
    candidates.  Keeping the catalog identity on every field avoids inventing
    a primary catalog when two source blocks expose the same field name.
    """

    if len(catalogs) < 2 or len(catalogs) > MAX_CATALOGS:
        _fail("RETRIEVAL_INVALID", "source catalog context roster is invalid")
    catalog_context: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    templates: list[dict[str, str]] = []
    template_keys: set[tuple[str, str]] = set()
    for catalog in catalogs:
        local_grounding = {
            "selections": [
                item
                for item in grounding.get("selections", [])
                if isinstance(item, Mapping) and item.get("catalog") == catalog
            ],
            "candidates": [
                item
                for item in grounding.get("candidates", [])
                if isinstance(item, Mapping) and item.get("catalog") == catalog
            ],
        }
        view = _bounded_context(index, field_technical, catalog, local_grounding, snapshot)
        raw_catalog = view.get("catalog")
        raw_fields = view.get("fields")
        raw_templates = view.get("endpoint_templates")
        if (
            not isinstance(raw_catalog, Mapping)
            or not isinstance(raw_fields, list)
            or not isinstance(raw_templates, list)
        ):
            _fail("RETRIEVAL_INVALID", "source catalog context is invalid")
        catalog_context.append(dict(raw_catalog))
        fields.extend({"catalog": catalog, **dict(item)} for item in raw_fields)
        for item in raw_templates:
            if not isinstance(item, Mapping):
                _fail("RETRIEVAL_INVALID", "source endpoint template is invalid")
            path = item.get("path")
            source = item.get("source")
            if not isinstance(path, str) or not isinstance(source, str):
                _fail("RETRIEVAL_INVALID", "source endpoint template is invalid")
            key = (path, source)
            if key not in template_keys:
                template_keys.add(key)
                templates.append({"path": path, "source": source})
    context: dict[str, Any] = {
        "language_version": "0.43",
        "semantic_schema": 2,
        "tenant_alias": snapshot.tenant_alias,
        "tenant_id": snapshot.tenant_id,
        "context_revision": snapshot.revision,
        "semantic_source_revision": index["semantic_source_revision"],
        "toolchain_binding": snapshot.toolchain_binding,
        "catalogs": catalog_context,
        "fields": fields,
        "endpoint_templates": templates[:MAX_TEMPLATES],
    }
    if len(canonical_json(context)) > MAX_CONTEXT_BYTES:
        _fail("RETRIEVAL_TOO_LARGE", "multi-catalog model context exceeds the byte bound")
    return context


class Schema2SnapshotRetriever:
    """Production-facing retriever over a session's immutable source snapshot."""

    def __init__(
        self,
        loader: SnapshotProjectionLoader,
        *,
        cache_size: int = 8,
    ) -> None:
        if not callable(loader) or type(cache_size) is not int or not 1 <= cache_size <= 64:
            raise BrainError("INVALID_CONFIG", 500, "semantic retriever configuration is invalid")
        self._loader = loader
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[str, str, str], _IndexedSnapshot] = OrderedDict()
        self._cache_lock = threading.Lock()

    def close(self) -> None:
        with self._cache_lock:
            self._cache.clear()
        close = getattr(self._loader, "close", None)
        if callable(close):
            close()

    def prewarm(self, snapshot: Any) -> dict[str, str]:
        """Build the immutable snapshot index before the first user turn."""

        indexed = self._indexed(snapshot)
        return {
            "context_revision": snapshot.revision,
            "semantic_source_revision": indexed.index["semantic_source_revision"],
            "toolchain_binding": indexed.index["toolchain_revision"],
        }

    def _indexed(self, snapshot: Any) -> _IndexedSnapshot:
        try:
            semantic_revision = snapshot.semantic_source_revision()
            snapshot_revision = snapshot.revision
            tenant_alias = snapshot.tenant_alias
            toolchain_binding = snapshot.toolchain_binding
        except AttributeError as error:
            _fail("RETRIEVAL_INVALID", "operation lease snapshot is invalid")
            raise AssertionError from error
        _hash(semantic_revision, "snapshot semantic revision")
        _safe_text(snapshot_revision, "snapshot revision")
        _safe_text(tenant_alias, "tenant alias")
        _hash(toolchain_binding, "toolchain binding")
        key = (snapshot_revision, semantic_revision, toolchain_binding)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
        try:
            loaded = self._loader(snapshot)
        except BrainError:
            raise
        except Exception as error:
            raise BrainError(
                "RETRIEVAL_UNAVAILABLE", 503, "semantic projection loader failed"
            ) from error
        projection = _validate_loader_binding(
            loaded,
            snapshot,
            semantic_revision,
            _source_paths(snapshot),
        )
        projection_copy = copy.deepcopy(dict(projection))
        field_technical = _projection_field_technical(projection_copy)
        grammar_revision = canonical_sha256({"grammar": toolchain_binding})
        try:
            built = build_semantic_index(
                projection_copy,
                semantic_source_revision=semantic_revision,
                grammar_revision=grammar_revision,
                toolchain_revision=toolchain_binding,
                tenant_snapshot={
                    "snapshot_id": f"{tenant_alias}-{snapshot_revision}",
                },
            )
        except Exception as error:
            raise BrainError(
                "RETRIEVAL_INVALID", 409, "semantic projection cannot build an index"
            ) from error
        index = built["index"]
        if index["tenant_snapshot"]["snapshot_id"] != f"{tenant_alias}-{snapshot_revision}":
            _fail("RETRIEVAL_INVALID", "semantic index snapshot binding is invalid")
        if index["semantic_source_revision"] != semantic_revision:
            _fail("RETRIEVAL_INVALID", "semantic index revision is not snapshot-bound")
        if index["toolchain_revision"] != toolchain_binding:
            _fail("RETRIEVAL_INVALID", "semantic index toolchain binding is invalid")
        if validate_semantic_index(index):
            _fail("RETRIEVAL_INVALID", "semantic index validation failed")
        indexed_fields = {
            (item["catalog"], item["field"])
            for item in index["entries"]
            if item["node_kind"] == "field"
        }
        if set(field_technical) != indexed_fields:
            _fail("RETRIEVAL_INVALID", "projection field technical roster differs from index")
        records = _catalog_records(index, projection_copy)
        if not records:
            _fail("RETRIEVAL_INVALID", "semantic catalog roster is empty")
        result = _IndexedSnapshot(
            index=index,
            catalogs=records,
            field_technical=field_technical,
        )
        with self._cache_lock:
            existing = self._cache.get(key)
            if existing is not None:
                self._cache.move_to_end(key)
                return existing
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            return result

    def retrieve(self, *, lease: OperationLease, request: Any) -> RetrievalResult:
        snapshot = lease.snapshot
        indexed = self._indexed(snapshot)
        instruction = getattr(request, "instruction", None)
        if not isinstance(instruction, str) or not instruction.strip():
            _fail("RETRIEVAL_INVALID", "request instruction is invalid", 400)
        output_request = parse_output_request(instruction)
        semantic_instruction = output_request.semantic_instruction
        disambiguation_instruction: str | None = None
        flash_value = getattr(request, "server_flash_intent", None)
        if flash_value is not None:
            if (
                not isinstance(flash_value, Mapping)
                or set(flash_value)
                != {
                    "schema_version",
                    "intent_ir",
                    "model_revision",
                    "schema_sha256",
                    "decoder",
                }
                or flash_value.get("schema_version") != 1
            ):
                raise BrainError("FLASH_INTENT_STALE", 409, "session Flash intent is invalid")
            target = getattr(request, "target", None)
            intent = getattr(request, "intent", None)
            if not isinstance(target, Mapping):
                raise BrainError("FLASH_INTENT_STALE", 409, "session Flash intent is invalid")
            compiled = IntentIR.parse(
                flash_value.get("intent_ir"),
                request=IntentCompileRequest(
                    instruction=instruction,
                    intent=intent,
                    target_mode=target.get("mode"),
                ),
            )
            normalized = compiled.exact_semantic_instruction
            if normalized is None:
                raise BrainError(
                    "FLASH_INTENT_UNSUPPORTED",
                    409,
                    "session Flash intent cannot safely drive retrieval",
                )
            disambiguation_instruction = output_request.semantic_instruction
            semantic_instruction = normalized
        # Only the TurnStore may resolve a client answer. Raw clarification
        # fields are intentionally ignored here so the retrieval authority can
        # never be steered with a manufactured option reference.
        basis_grounding = getattr(request, "server_basis_grounding", None)
        catalog_clarification = (
            _current_server_decision(request, "catalog")
            if isinstance(basis_grounding, Mapping)
            else _server_decision(request, "catalog")
        )
        catalog_decision = (
            catalog_clarification.get("resolved_value")
            if catalog_clarification is not None
            else None
        )
        explicit = _explicit_catalog(instruction, indexed.catalogs, None)
        source_catalogs = getattr(request, "server_target_catalogs", ())
        if (
            not isinstance(source_catalogs, tuple)
            or len(source_catalogs) > MAX_CATALOGS
            or any(not isinstance(item, str) or not item for item in source_catalogs)
            or len(source_catalogs) != len(set(source_catalogs))
        ):
            _fail("RETRIEVAL_INVALID", "target catalog roster is invalid", 400)
        if explicit is None and isinstance(catalog_decision, str):
            explicit = _explicit_catalog(instruction, indexed.catalogs, catalog_decision)
        if explicit is None and isinstance(basis_grounding, Mapping):
            basis_catalogs = basis_grounding.get("catalogs")
            if (
                isinstance(basis_catalogs, list)
                and len(basis_catalogs) == 1
                and isinstance(basis_catalogs[0], str)
            ):
                explicit = _explicit_catalog(instruction, indexed.catalogs, basis_catalogs[0])
        source_candidates: list[dict[str, Any]] | None = None
        if source_catalogs:
            resolved_sources: list[str] = []
            for source_catalog in source_catalogs:
                resolved = _source_catalog(source_catalog, indexed.catalogs)
                if resolved is None:
                    _fail("RETRIEVAL_INVALID", "target catalog does not resolve uniquely")
                if resolved not in resolved_sources:
                    resolved_sources.append(resolved)
            records_by_catalog = {item["catalog"]: item for item in indexed.catalogs}
            source_candidates = [records_by_catalog[item] for item in resolved_sources]
            if len(source_candidates) != len(resolved_sources):
                _fail("RETRIEVAL_INVALID", "target catalog roster differs from projection")
            if len(source_candidates) == 1 and explicit is None:
                explicit = source_candidates[0]["catalog"]
        if explicit is None and source_candidates is None:
            client_hint = getattr(request, "catalog_hint", None)
            if client_hint is not None:
                explicit = _explicit_catalog(instruction, indexed.catalogs, client_hint)
        source_routing_blocked = explicit in {"__ambiguous__", "__unknown__"}
        if explicit == "__ambiguous__":
            explicit = None
            true_candidates = [item for item in indexed.catalogs if item["owner"]]
        elif explicit == "__unknown__":
            true_candidates = []
        elif explicit is not None:
            true_candidates = [item for item in indexed.catalogs if item["catalog"] == explicit]
        elif source_candidates is not None:
            true_candidates = source_candidates
        else:
            true_candidates = _semantic_catalog_candidates(
                indexed.index,
                semantic_instruction,
                indexed.catalogs,
            )
        candidate_payload = tuple(
            {
                "catalog": item["catalog"],
                "label": (
                    item["label"]["text"]
                    if item["state"] == "reviewed"
                    and isinstance(item.get("label"), Mapping)
                    and isinstance(item["label"].get("text"), str)
                    else item["catalog"]
                ),
                "option_ref": item["option_ref"],
                "description": (
                    item["means"]["text"]
                    if item["state"] == "reviewed"
                    and isinstance(item.get("means"), Mapping)
                    and isinstance(item["means"].get("text"), str)
                    else "Catalogo autorizzato"
                ),
            }
            for item in true_candidates
        )
        if (
            not source_routing_blocked
            and source_candidates is not None
            and (
                len(source_candidates) > 1
                or (
                    isinstance(explicit, str)
                    and explicit not in {item["catalog"] for item in source_candidates}
                )
            )
        ):
            source_roster = [item["catalog"] for item in source_candidates]
            semantic_records = (
                [item for item in indexed.catalogs if item["catalog"] == explicit]
                if isinstance(explicit, str)
                else source_candidates
            )
            attempts = [
                _resolve_complete_grounding(
                    indexed.index,
                    semantic_instruction,
                    item["catalog"],
                    disambiguation_instruction=disambiguation_instruction,
                )
                for item in semantic_records
            ]
            resolved = [
                value
                for value in attempts
                if value.get("status") == "resolved" and value.get("selections")
            ]
            partial = [
                value
                for value in attempts
                if value.get("status") == "unsupported" and value.get("selections")
            ]
            clarification_candidates = [
                dict(candidate)
                for value in attempts
                for candidate in value.get("candidates", [])
                if isinstance(candidate, Mapping)
            ]
            if len(resolved) == 1 and not clarification_candidates:
                grounding = resolved[0]
            elif len(resolved) > 1:
                tied = [
                    _semantic_candidate(indexed.index, selection, semantic_instruction)
                    for value in resolved
                    for selection in value.get("selections", [])
                    if isinstance(selection, Mapping)
                ]
                grounding = {
                    "status": "clarify",
                    "reason": "reviewed semantics tie across source-authorized catalogs",
                    "selected": None,
                    "selections": [],
                    "candidates": tied,
                    "lookup": None,
                    "lookups": [],
                    "unresolved": [],
                }
            elif clarification_candidates:
                grounding = {
                    "status": "clarify",
                    "reason": "one source-authorized semantic clause requires confirmation",
                    "selected": None,
                    "selections": [],
                    "candidates": clarification_candidates,
                    "lookup": None,
                    "lookups": [],
                    "unresolved": [],
                }
            elif len(partial) == 1:
                # Preserve the partial exact evidence and its residue so the
                # bounded Flash retry can segment the instruction.  Treating
                # this as a generic structural edit would suppress that safe
                # retry and lose an operator-named reviewed member.
                grounding = partial[0]
            else:
                # No reviewed semantic member was requested.  This is the
                # structural-edit path: the complete source roster is still
                # authoritative, while the candidate oracle below prevents
                # the model from introducing an ungrounded finite predicate.
                grounding = {
                    "status": "resolved",
                    "reason": "existing source catalogs authorize a structural edit",
                    "selected": None,
                    "selections": [],
                    "candidates": [],
                    "lookup": None,
                    "lookups": [],
                    "unresolved": [],
                }
            semantic_decisions = (
                tuple(
                    decision
                    for decision in (_current_server_decision(request, "semantic_choice"),)
                    if decision is not None
                )
                if isinstance(basis_grounding, Mapping)
                else _server_decisions(request, "semantic_choice")
            )
            for semantic_clarification in semantic_decisions:
                option_ref = semantic_clarification.get("resolved_value")
                if not isinstance(option_ref, str):
                    raise BrainError(
                        "CLARIFICATION_UNAVAILABLE", 409, "semantic option is unavailable"
                    )
                _apply_semantic_decision(indexed.index, grounding, option_ref)
            enriched_selections: list[dict[str, Any]] = []
            for raw_selection in grounding.get("selections", []):
                if not isinstance(raw_selection, Mapping):
                    _fail("RETRIEVAL_INVALID", "grounding selection is invalid")
                field = raw_selection.get("field")
                catalog = raw_selection.get("catalog")
                technical = indexed.field_technical.get((catalog, field))
                if technical is None:
                    _fail("RETRIEVAL_INVALID", "grounding field technical surface is unavailable")
                enriched_selections.append(
                    {
                        **raw_selection,
                        "type": technical["type"],
                        "modifiers": list(technical["modifiers"]),
                    }
                )
            grounding["selections"] = enriched_selections
            authorized_catalogs = [explicit] if isinstance(explicit, str) else list(source_roster)
            grounding["catalogs"] = authorized_catalogs
            grounding["source_catalogs"] = source_roster
            grounding["catalog_candidates"] = []
            grounding["semantic_source_revision"] = indexed.index["semantic_source_revision"]
            grounding["resolutions"] = [
                {
                    "concept": item.get("literal") or item.get("field"),
                    "catalog": item.get("catalog"),
                    "field": item.get("field"),
                    "literal": item.get("literal"),
                    "review_state": "reviewed",
                }
                for item in enriched_selections
            ]
            context_catalogs = list(source_roster)
            if isinstance(explicit, str) and explicit not in context_catalogs:
                context_catalogs.append(explicit)
            context = _bounded_source_context(
                indexed.index,
                indexed.field_technical,
                tuple(context_catalogs),
                grounding,
                snapshot,
            )
            return RetrievalResult(
                context=context,
                grounding=grounding,
                semantic_source_revision=indexed.index["semantic_source_revision"],
                catalog_candidates=(),
                output_request=output_request,
            )
        if len(true_candidates) != 1:
            status = "clarify" if len(true_candidates) > 1 else "unsupported"
            reason = (
                "multiple catalogs require explicit confirmation"
                if status == "clarify"
                else "no canonical catalog owner is available"
            )
            grounding = {
                "status": status,
                "reason": reason,
                "catalog_candidates": [item["catalog"] for item in candidate_payload],
                "catalogs": [],
                "resolutions": [],
                "unresolved": [instruction[:256]] if status == "unsupported" else [],
                "semantic_source_revision": indexed.index["semantic_source_revision"],
            }
            return RetrievalResult(
                context={
                    "tenant_alias": snapshot.tenant_alias,
                    "tenant_id": snapshot.tenant_id,
                    "context_revision": snapshot.revision,
                    "semantic_source_revision": indexed.index["semantic_source_revision"],
                    "toolchain_binding": snapshot.toolchain_binding,
                    "catalogs": [dict(item) for item in candidate_payload],
                },
                grounding=grounding,
                semantic_source_revision=indexed.index["semantic_source_revision"],
                catalog_candidates=candidate_payload,
                output_request=output_request,
            )
        selected_catalog = true_candidates[0]["catalog"]
        grounding = _resolve_complete_grounding(
            indexed.index,
            semantic_instruction,
            selected_catalog,
            disambiguation_instruction=disambiguation_instruction,
        )
        _merge_basis_grounding(
            indexed.index,
            grounding,
            basis_grounding,
            selected_catalog,
            instruction,
        )
        semantic_decisions = (
            tuple(
                decision
                for decision in (_current_server_decision(request, "semantic_choice"),)
                if decision is not None
            )
            if isinstance(basis_grounding, Mapping)
            else _server_decisions(request, "semantic_choice")
        )
        for semantic_clarification in semantic_decisions:
            option_ref = semantic_clarification.get("resolved_value")
            if not isinstance(option_ref, str):
                raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "semantic option is unavailable")
            _apply_semantic_decision(indexed.index, grounding, option_ref)
        enriched_selections: list[dict[str, Any]] = []
        for raw_selection in grounding.get("selections", []):
            if not isinstance(raw_selection, Mapping):
                _fail("RETRIEVAL_INVALID", "grounding selection is invalid")
            field = raw_selection.get("field")
            catalog = raw_selection.get("catalog")
            technical = indexed.field_technical.get((catalog, field))
            if technical is None:
                _fail("RETRIEVAL_INVALID", "grounding field technical surface is unavailable")
            enriched_selections.append(
                {
                    **raw_selection,
                    "type": technical["type"],
                    "modifiers": list(technical["modifiers"]),
                }
            )
        grounding["selections"] = enriched_selections
        grounding["catalogs"] = [selected_catalog]
        grounding["catalog_candidates"] = []
        grounding["semantic_source_revision"] = indexed.index["semantic_source_revision"]
        grounding["resolutions"] = [
            {
                "concept": item.get("literal") or item.get("field"),
                "catalog": item.get("catalog"),
                "field": item.get("field"),
                "literal": item.get("literal"),
                "review_state": "reviewed",
            }
            for item in grounding.get("selections", [])
            if isinstance(item, Mapping)
        ]
        context = _bounded_context(
            indexed.index,
            indexed.field_technical,
            selected_catalog,
            grounding,
            snapshot,
        )
        return RetrievalResult(
            context=context,
            grounding=grounding,
            semantic_source_revision=indexed.index["semantic_source_revision"],
            catalog_candidates=(
                {
                    "catalog": selected_catalog,
                    "label": candidate_payload[0]["label"],
                    "option_ref": candidate_payload[0]["option_ref"],
                    "description": candidate_payload[0]["description"],
                },
            ),
            output_request=output_request,
        )


__all__ = ["LoadedProjection", "Schema2SnapshotRetriever", "SnapshotProjectionLoader"]
