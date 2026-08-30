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


def _explicit_catalog(request: str, records: tuple[dict[str, Any], ...], hint: Any) -> str | None:
    if hint is not None:
        if not isinstance(hint, str) or not hint:
            _fail("RETRIEVAL_INVALID", "catalog hint is invalid", 400)
        for record in records:
            if record["catalog"] == hint or record["option_ref"] == hint:
                return record["catalog"]
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
    selection: dict[str, Any] = {
        "catalog": catalog,
        "field": field,
        "literal": candidate.get("literal") if isinstance(candidate.get("literal"), str) else None,
        "domain": copy.deepcopy(parent["domain"]),
        "matched_by": "reviewed_semantic_disambiguation",
    }
    literals = candidate.get("literals")
    if isinstance(literals, list) and literals and all(isinstance(item, str) for item in literals):
        selection["literals"] = list(literals)
        selection["value_mode"] = "any_of"
    return selection


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
    index: Mapping[str, Any], clause: str, catalog: str
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
            chosen = _choose_candidate(index, remaining, raw_candidates)
            if chosen is None:
                unresolved_candidates = [
                    dict(item) for item in raw_candidates if isinstance(item, Mapping)
                ]
                break
            selection = _candidate_selection(index, chosen)
            if selection is None:
                unresolved_candidates = [chosen]
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
    index: Mapping[str, Any], request: str, catalog: str
) -> dict[str, Any]:
    scrubbed = request
    short = catalog.rsplit(".", 1)[-1]
    for surface in (f"@{short}", catalog, f"catalogo {short}", f"catalog {short}"):
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
        clause_selections, clause_candidates, remainder = _resolve_clause(index, clause, catalog)
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
        domain = dict(entry["domain"])
        field: dict[str, Any] = {
            "name": entry["field"],
            "type": entry.get("type"),
            "modifiers": list(entry.get("modifiers", [])),
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
        records = _catalog_records(index, projection_copy)
        if not records:
            _fail("RETRIEVAL_INVALID", "semantic catalog roster is empty")
        result = _IndexedSnapshot(index=index, catalogs=records)
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
        clarification = getattr(request, "clarification_response", None)
        if isinstance(clarification, Mapping) and (
            clarification.get("context_revision") != snapshot.revision
            or clarification.get("semantic_source_revision")
            != indexed.index["semantic_source_revision"]
        ):
            raise BrainError("SEMANTIC_SOURCE_STALE", 409, "clarification revision is stale")
        clarification_hint = (
            clarification.get("option_ref") if isinstance(clarification, Mapping) else None
        )
        catalog_hint = clarification_hint or getattr(request, "catalog_hint", None)
        explicit = _explicit_catalog(
            instruction,
            indexed.catalogs,
            catalog_hint,
        )
        if explicit == "__ambiguous__":
            explicit = None
            true_candidates = [item for item in indexed.catalogs if item["owner"]]
        elif explicit == "__unknown__":
            true_candidates = []
        elif explicit is not None:
            true_candidates = [item for item in indexed.catalogs if item["catalog"] == explicit]
        else:
            true_candidates = _semantic_catalog_candidates(
                indexed.index,
                instruction,
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
            )
        selected_catalog = true_candidates[0]["catalog"]
        grounding = _resolve_complete_grounding(indexed.index, instruction, selected_catalog)
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
        context = _bounded_context(indexed.index, selected_catalog, grounding, snapshot)
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
        )


__all__ = ["LoadedProjection", "Schema2SnapshotRetriever", "SnapshotProjectionLoader"]
