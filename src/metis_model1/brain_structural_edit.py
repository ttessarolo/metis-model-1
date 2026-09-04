"""Compiler-owned, lossless scalar edits for complex existing endpoints.

The operator instruction is evidence, never authority by itself.  This module
admits only four closed scalar edit families, resolves them against the pinned
compiler's occurrence-aware edit surface, seals a one-shot private
``DeltaPermit``, and asks the existing lossless renderer to apply whole-node
replacements.  Everything outside those constraints fails closed before Model
1 can regenerate a large endpoint from scratch.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from metis_model1.brain_delta_permit import (
    DELTA_CONSUMPTION_CONTRACT,
    DELTA_PERMIT_CONTRACT,
    DeltaPermitError,
    DeltaPermitTranslator,
    issue_delta_permit,
)
from metis_model1.brain_lossless_edit import (
    LOSSLESS_PLAN_CONTRACT,
    LOSSLESS_RECEIPT_CONTRACT,
    LosslessRenderResult,
)
from metis_model1.brain_model_runtime import ModelCandidate
from metis_model1.brain_protocol import (
    MAX_SOURCE_BYTES,
    BrainError,
    bounded_source,
    bytes_sha256,
    canonical_sha256,
)

EDIT_SURFACE_CONTRACT = "metis-brain-edit-surface/v1"
STRUCTURAL_LOSSLESS_PROOF_CONTRACT = "metis-brain-structural-lossless-proof/v1"
MAX_EDIT_ITEMS = 256
MAX_EDIT_OPERATIONS = 32
MAX_EDIT_TEXT_UNITS = 512
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NODE_RE = re.compile(r"^\$(?:/[A-Za-z_][A-Za-z0-9_]*(?:@[0-9]+)?)*$")
_CATALOG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_QUALIFIED_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z_][A-Za-z0-9_-]*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_-]*)+(?![A-Za-z0-9_-])"
)
_PRIMITIVES = frozenset(
    {
        "take_cardinality",
        "output_limit",
        "display_label_or_title",
        "block_argument_list",
    }
)
_PRESERVATION_SEGMENT = re.compile(
    r"(?:,\s*|\be\s+)?(?:\b(?:non\s+cambiare|non\s+modificare|non\s+toccare|"
    r"mantieni|conserva|"
    r"preserva(?:ndo)?|lascia(?:ndo)?(?:\s+invariat[ioe])?|"
    r"senza\s+(?:cambiare|modificare|toccare|aggiungere|rimuovere|usare))\b"
    r"[^.;\n]*|\b(?:il|la|i|le)\s+[^,.;\n]{1,100}?\s+"
    r"(?:rest(?:a|ano)\s+invariat[ioe]|devono\s+restare\s+identic(?:o|a|i|he))\b"
    r"[^.;\n]*)(?:[.;\n]|$)",
    re.IGNORECASE,
)
_UNSUPPORTED_MUTATION = re.compile(
    r"\b(?:"
    r"aggiungi|aggiungere|inserisci|inserire|crea|creare|imposta|impostare|"
    r"abilita|abilitare|collega|collegare|attiva|attivare|introduci|introdurre"
    r")\b[^.;\n]{0,80}\b(?:"
    r"filtr\w*|condizion\w*|fallback|ordinament\w*|catalog\w*|"
    r"metadat\w*|variant\w*|blocc\w*|view[ -]?all|paginaz\w*|"
    r"response|risposta|deduplic\w*"
    r")\b|(?:\be\b|\bpoi\b|[.;:])\s*(?!non\b)(?:"
    r"cambia|cambiare|modifica|modificare"
    r")\b[^.;\n]{0,80}\b(?:"
    r"filtr\w*|condizion\w*|fallback|ordinament\w*|catalog\w*|"
    r"metadat\w*|variant\w*|blocc\w*|view[ -]?all|paginaz\w*|"
    r"response|risposta|deduplic\w*"
    r")\b|\b(?:"
    r"rimuovi|rimuovere|elimina|eliminare|escludi|escludere|"
    r"filtra|filtrare|ordina|ordinare|promuovi|promuovere|"
    r"duplica|duplicare|sposta|spostare|applica|applicare|usa|usare|"
    r"includi|includere|crea|creare|imposta|impostare|abilita|abilitare|"
    r"collega|collegare|attiva|attivare|disattiva|disattivare|introduci|"
    r"introdurre|azzera|azzerare|dimezza|dimezzare|raddoppia|raddoppiare|"
    r"togli|togliere|configura|configurare|riusa|riusare|combina|combinare|"
    r"definisci|definire"
    r")\b",
    re.IGNORECASE,
)
_SEMANTIC_LIMIT = re.compile(
    r"\b(?:limita|limitare|restringi|restringere)\b\s+"
    r"(?:a|ai|al|alla|alle|agli|solo\s+a|soltanto\s+a)\b",
    re.IGNORECASE,
)
_PROTECTED_MUTATION_OBJECT = re.compile(
    r"\b(?:fallback|filtr(?:o|i|a|are|ato|ata|ando|aggio)\w*|catalog\w*|"
    r"view[ -]?all|paginaz\w*|"
    r"deduplic\w*|ordinament\w*|response|risposta|metadat\w*|shuffle|"
    r"smart[ -]?order|template|seed|finestr\w*|guardi[ae]|sorgent\w*|"
    r"candidat\w*|alternativ\w*|pool)\b",
    re.IGNORECASE,
)
_SCOPE_KIND_RE = re.compile(r"\b(ramo|variante|blocco|istanza|riga|righe)\b", re.I)
_SCOPE_BOUNDARY_RE = re.compile(
    r"[,;:.]|\b(?:porta|portalo|portala|modifica|cambia|sostituisci|rinomina|"
    r"rendi|aggiungi|prende|prendi|voglio|aggiorna|lascia|mantieni|conserva|"
    r"che|oggi|da|usata|usato|utilizzata|utilizzato)\b|"
    r"\b(?:del|della|nel|nella)\s+(?:ramo|variante|blocco|istanza|riga)\b|"
    r"\bdi\s+[A-Za-z_][A-Za-z0-9_.-]*\s*:",
    re.I,
)
_SCOPE_PREFIX_WORDS = frozenset(
    {
        "di",
        "del",
        "della",
        "il",
        "la",
        "solo",
        "sola",
        "parametrica",
        "parametrico",
        "movable",
    }
)
_ACTION_RE = re.compile(
    r"\b(?:modifica|modificare|cambia|cambiare|porta|portalo|portala|prende|prendi|"
    r"voglio|aggiorna|aggiornare|rendi|rendere|sostituisci|sostituire|rinomina|"
    r"rinominare|aggiungi|aggiungere|aumenta|aumentare|riduci|ridurre|seleziona|"
    r"selezionare|inserisci|inserire|crea|creare|imposta|impostare|abilita|"
    r"abilitare|collega|collegare|"
    r"attiva|attivare|disattiva|disattivare|introduci|introdurre|rimuovi|rimuovere|"
    r"elimina|eliminare|"
    r"escludi|escludere|filtra|filtrare|ordina|ordinare|promuovi|promuovere|"
    r"duplica|duplicare|sposta|spostare|applica|applicare|usa|usare|includi|"
    r"includere|limita|limitare|restringi|restringere)\b",
    re.I,
)
_PRESERVATION_CONTINUATION_WORDS = frozenset(
    {
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "l",
        "un",
        "una",
        "tutti",
        "tutte",
        "tutto",
        "ogni",
        "altro",
        "altra",
        "altri",
        "altre",
        "senza",
        "non",
        "lasciando",
        "limite",
        "mantenendo",
        "conservando",
        "titolo",
    }
)
_PRESERVATION_LEDGER_WORDS = frozenset(
    {
        "all",
        "alternative",
        "altre",
        "altri",
        "anonima",
        "append",
        "argomento",
        "azione",
        "best",
        "blocchi",
        "blocco",
        "cambiare",
        "candidate",
        "candidati",
        "cinque",
        "cluster",
        "condiviso",
        "conserva",
        "conteggio",
        "contesto",
        "da",
        "default",
        "della",
        "devono",
        "di",
        "dichiarazione",
        "doppio",
        "e",
        "errore",
        "expanded",
        "fallback",
        "fiction",
        "filtri",
        "finale",
        "finestre",
        "full",
        "fuzzy",
        "genere",
        "generi",
        "gli",
        "hdr",
        "i",
        "identiche",
        "il",
        "invariati",
        "invariato",
        "istanze",
        "l",
        "la",
        "lascia",
        "lasciando",
        "le",
        "limite",
        "lo",
        "mantieni",
        "mcm",
        "metadati",
        "modificare",
        "most",
        "near",
        "non",
        "nove",
        "o",
        "order",
        "ordinamenti",
        "ordinamento",
        "pagina",
        "parametri",
        "parametrica",
        "parametrico",
        "per",
        "plus",
        "poster",
        "preservando",
        "principale",
        "quattro",
        "query",
        "recent",
        "restare",
        "resta",
        "ricerca",
        "riga",
        "righe",
        "rilevanza",
        "sdr",
        "searchdetailparams",
        "secondo",
        "senza",
        "serie",
        "shuffle",
        "similarita",
        "smart",
        "sorgenti",
        "statica",
        "take",
        "template",
        "titolo",
        "toccare",
        "tutte",
        "tutti",
        "tv",
        "variante",
        "varianti",
        "variazioni",
        "verso",
        "view",
    }
)
_POSITIVE_LEDGER_WORDS = frozenset(
    {
        "a",
        "ad",
        "ai",
        "al",
        "alla",
        "alle",
        "allo",
        "con",
        "da",
        "dal",
        "dalla",
        "dalle",
        "dallo",
        "de",
        "dei",
        "del",
        "dell",
        "della",
        "delle",
        "dello",
        "di",
        "e",
        "ed",
        "gli",
        "i",
        "il",
        "in",
        "l",
        "la",
        "le",
        "lo",
        "na",
        "nel",
        "nell",
        "nella",
        "nelle",
        "nello",
        "o",
        "per",
        "su",
        "sul",
        "sull",
        "sulla",
        "sulle",
        "aggiorna",
        "aggiornare",
        "aggiungi",
        "aggiungere",
        "cambia",
        "cambiare",
        "modifica",
        "modificare",
        "porta",
        "portalo",
        "portala",
        "prende",
        "prendi",
        "rendi",
        "rendere",
        "rinomina",
        "rinominare",
        "sostituisci",
        "sostituire",
        "voglio",
        "argomento",
        "blocco",
        "chiara",
        "chiaro",
        "che",
        "complessivi",
        "complessivo",
        "default",
        "draft",
        "elementi",
        "elemento",
        "entrambe",
        "entrambi",
        "etichetta",
        "finale",
        "genere",
        "istanza",
        "lista",
        "limite",
        "mostrata",
        "mostrato",
        "movable",
        "oggi",
        "parametrica",
        "parametrico",
        "parametro",
        "page",
        "pagina",
        "percento",
        "percentuale",
        "piu",
        "prima",
        "primo",
        "ramo",
        "relativo",
        "riga",
        "righe",
        "risultati",
        "risultato",
        "seconda",
        "secondo",
        "sola",
        "sole",
        "soli",
        "solo",
        "take",
        "titolo",
        "totale",
        "totali",
        "usata",
        "usato",
        "utilizzata",
        "utilizzato",
        "variante",
        "visibile",
    }
)


class StructuralEditInapplicable(ValueError):
    """The instruction does not ask for one of the closed edit families."""


@dataclass(frozen=True, slots=True)
class _Replacement:
    item: dict[str, Any]
    new_value: int | str
    evidence_sha256: str
    evidence_key: tuple[str, int, int] | None = None


@dataclass(frozen=True, slots=True)
class _NumericTransition:
    old: int
    new: int
    evidence: str
    clause: str
    clause_start: int
    clause_end: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _StringTransition:
    old: str
    new: str
    evidence: str
    clause: str
    clause_start: int
    clause_end: int
    start: int
    end: int


def _host_ref(role: str) -> str:
    return f"hostref:{role}:{secrets.token_hex(16)}"


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_like))


def _active_instruction(instruction: str) -> str:
    """Remove explicit preserve-roster clauses from positive target evidence."""

    def remove_or_retain_positive(match: re.Match[str]) -> str:
        segment = match.group(0)
        connector = re.search(
            r"\b(?:ma|però|pero|tuttavia|poi|quindi|inoltre)\b",
            segment,
            re.IGNORECASE,
        ) or re.search(
            r"\be\s+" rf"(?={_ACTION_RE.pattern})",
            segment,
            re.IGNORECASE,
        )
        preservation_only = segment[: connector.start()] if connector is not None else segment
        residue = _fold(preservation_only).split()
        if any(
            word not in _PRESERVATION_LEDGER_WORDS and re.fullmatch(r"[0-9]+[a-z]?", word) is None
            for word in residue
        ):
            raise BrainError(
                "STRUCTURAL_EDIT_MIXED_INTENT",
                422,
                "preservation clause contains prose outside the bounded grammar",
            )
        for continuation in re.finditer(
            r"\b(?:e|ma|però|pero|poi|quindi|inoltre)\s+([A-Za-zÀ-ÖØ-öø-ÿ][\wÀ-ÖØ-öø-ÿ-]*)",
            segment,
            re.IGNORECASE,
        ):
            word = _fold(continuation.group(1))
            if connector is not None and continuation.start() >= connector.start():
                continue
            if word not in _PRESERVATION_CONTINUATION_WORDS:
                raise BrainError(
                    "STRUCTURAL_EDIT_MIXED_INTENT",
                    422,
                    "preservation clause contains an unconsumed continuation",
                )
        return f" {segment[connector.start() :]}" if connector is not None else " "

    return _PRESERVATION_SEGMENT.sub(remove_or_retain_positive, instruction)


def _sha(value: bytes) -> str:
    return bytes_sha256(value)


def _utf_boundaries(source: str) -> tuple[dict[int, int], set[int]]:
    utf16 = 0
    byte = 0
    utf16_to_byte = {0: 0}
    byte_boundaries = {0}
    for character in source:
        utf16 += len(character.encode("utf-16-le")) // 2
        byte += len(character.encode("utf-8"))
        utf16_to_byte[utf16] = byte
        byte_boundaries.add(byte)
    return utf16_to_byte, byte_boundaries


def _explicit_span(
    value: Any,
    *,
    utf16_to_byte: Mapping[int, int],
    byte_boundaries: set[int],
) -> dict[str, dict[str, int]]:
    if not isinstance(value, Mapping) or set(value) != {"utf16", "utf8_bytes"}:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface span is invalid")
    utf16 = value["utf16"]
    utf8 = value["utf8_bytes"]
    if (
        not isinstance(utf16, Mapping)
        or set(utf16) != {"start", "end"}
        or not isinstance(utf8, Mapping)
        or set(utf8) != {"start", "end"}
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface span is invalid")
    u_start, u_end = utf16["start"], utf16["end"]
    b_start, b_end = utf8["start"], utf8["end"]
    if (
        any(type(item) is not int or item < 0 for item in (u_start, u_end, b_start, b_end))
        or u_start > u_end
        or b_start > b_end
        or u_start not in utf16_to_byte
        or u_end not in utf16_to_byte
        or utf16_to_byte[u_start] != b_start
        or utf16_to_byte[u_end] != b_end
        or b_start not in byte_boundaries
        or b_end not in byte_boundaries
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface span differs from source")
    return {
        "utf16": {"start": u_start, "end": u_end},
        "utf8_bytes": {"start": b_start, "end": b_end},
    }


def _bounded_string(value: Any, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-16-le")) // 2 > MAX_EDIT_TEXT_UNITS
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface text is invalid")
    return value


def _validate_surface(
    envelope: Any,
    *,
    source: str,
    relative_path: str,
    endpoint: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    expected_envelope = {
        "schema_version",
        "operation",
        "status",
        "diagnostics",
        "relative_path",
        "endpoint",
        "edit_surface",
        "edit_surface_sha256",
    }
    if not isinstance(envelope, Mapping) or set(envelope) != expected_envelope:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface envelope is invalid")
    if (
        envelope.get("schema_version") != 1
        or envelope.get("operation") != "edit-surface"
        or envelope.get("relative_path") != relative_path
        or envelope.get("endpoint") != endpoint
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface identity differs")
    if envelope.get("status") != "ok":
        if (
            envelope.get("edit_surface") is not None
            or envelope.get("edit_surface_sha256") is not None
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "invalid edit surface leaked authority")
        raise BrainError("EDIT_SURFACE_UNAVAILABLE", 422, "compiler could not project edit surface")
    if envelope.get("diagnostics") != []:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "successful edit surface has diagnostics")
    surface = envelope.get("edit_surface")
    surface_sha = envelope.get("edit_surface_sha256")
    if (
        not isinstance(surface, Mapping)
        or set(surface)
        != {"contract", "relative_path", "source_sha256", "endpoint", "items", "counts"}
        or surface.get("contract") != EDIT_SURFACE_CONTRACT
        or surface.get("relative_path") != relative_path
        or surface.get("source_sha256") != _sha(source.encode("utf-8"))
        or not isinstance(surface_sha, str)
        or _HASH_RE.fullmatch(surface_sha) is None
        or canonical_sha256(dict(surface)) != surface_sha
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface seal differs")
    utf16_to_byte, byte_boundaries = _utf_boundaries(source)
    raw = source.encode("utf-8")
    endpoint_surface = surface["endpoint"]
    if (
        not isinstance(endpoint_surface, Mapping)
        or set(endpoint_surface) != {"name", "node_id", "preimage_sha256", "span"}
        or endpoint_surface.get("name") != endpoint
        or not isinstance(endpoint_surface.get("node_id"), str)
        or _NODE_RE.fullmatch(endpoint_surface["node_id"]) is None
        or not isinstance(endpoint_surface.get("preimage_sha256"), str)
        or _HASH_RE.fullmatch(endpoint_surface["preimage_sha256"]) is None
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface endpoint is invalid")
    endpoint_span = _explicit_span(
        endpoint_surface["span"],
        utf16_to_byte=utf16_to_byte,
        byte_boundaries=byte_boundaries,
    )
    endpoint_start = endpoint_span["utf8_bytes"]["start"]
    endpoint_end = endpoint_span["utf8_bytes"]["end"]
    if _sha(raw[endpoint_start:endpoint_end]) != endpoint_surface["preimage_sha256"]:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface endpoint preimage differs")
    items = surface["items"]
    counts = surface["counts"]
    if (
        not isinstance(items, list)
        or not 1 <= len(items) <= MAX_EDIT_ITEMS
        or not isinstance(counts, Mapping)
        or set(counts) != {"items", *_PRIMITIVES}
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface roster is invalid")
    validated: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    seen_properties: set[tuple[int, int]] = set()
    primitive_counts: dict[str, int] = defaultdict(int)
    previous_end = -1
    for ordinal, raw_item in enumerate(items):
        if not isinstance(raw_item, Mapping) or set(raw_item) != {
            "ordinal",
            "edit_ref",
            "primitive",
            "owner",
            "property",
            "scope",
            "old_value",
            "authority",
        }:
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface item is invalid")
        item = dict(raw_item)
        primitive = item["primitive"]
        edit_ref = item["edit_ref"]
        if (
            item["ordinal"] != ordinal
            or primitive not in _PRIMITIVES
            or not isinstance(edit_ref, str)
            or _HASH_RE.fullmatch(edit_ref) is None
            or edit_ref in seen_refs
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface item identity is invalid")
        owner = item["owner"]
        if (
            not isinstance(owner, Mapping)
            or set(owner) != {"node_id", "node_type", "preimage_sha256", "span"}
            or not isinstance(owner.get("node_id"), str)
            or _NODE_RE.fullmatch(owner["node_id"]) is None
            or not isinstance(owner.get("node_type"), str)
            or not owner["node_type"]
            or not isinstance(owner.get("preimage_sha256"), str)
            or _HASH_RE.fullmatch(owner["preimage_sha256"]) is None
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface owner is invalid")
        owner_span = _explicit_span(
            owner["span"],
            utf16_to_byte=utf16_to_byte,
            byte_boundaries=byte_boundaries,
        )
        owner_start = owner_span["utf8_bytes"]["start"]
        owner_end = owner_span["utf8_bytes"]["end"]
        if (
            not endpoint_start <= owner_start <= owner_end <= endpoint_end
            or _sha(raw[owner_start:owner_end]) != owner["preimage_sha256"]
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface owner preimage differs")
        prop = item["property"]
        if (
            not isinstance(prop, Mapping)
            or set(prop) != {"ast_node_id", "path", "preimage_sha256", "span"}
            or (
                prop.get("ast_node_id") is not None
                and (
                    not isinstance(prop["ast_node_id"], str)
                    or _NODE_RE.fullmatch(prop["ast_node_id"]) is None
                )
            )
            or not isinstance(prop.get("path"), str)
            or not prop["path"]
            or not isinstance(prop.get("preimage_sha256"), str)
            or _HASH_RE.fullmatch(prop["preimage_sha256"]) is None
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface property is invalid")
        prop_span = _explicit_span(
            prop["span"],
            utf16_to_byte=utf16_to_byte,
            byte_boundaries=byte_boundaries,
        )
        prop_start = prop_span["utf8_bytes"]["start"]
        prop_end = prop_span["utf8_bytes"]["end"]
        if (
            not owner_start <= prop_start < prop_end <= owner_end
            or _sha(raw[prop_start:prop_end]) != prop["preimage_sha256"]
            or (prop_start, prop_end) in seen_properties
            or prop_start < previous_end
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface property preimage differs")
        scope = _validate_scope(item["scope"], endpoint=endpoint)
        old_value = _validate_old_value(primitive, item["old_value"])
        authority = _validate_authority(primitive, item["authority"])
        normalized = {
            **item,
            "owner": {**dict(owner), "span": owner_span},
            "property": {**dict(prop), "span": prop_span},
            "scope": scope,
            "old_value": old_value,
            "authority": authority,
        }
        expected_ref = canonical_sha256(
            {
                "contract": EDIT_SURFACE_CONTRACT,
                "source_sha256": surface["source_sha256"],
                "primitive": primitive,
                "owner_node_id": owner["node_id"],
                "property": prop,
                "scope": item["scope"],
                "authority": item["authority"],
            }
        )
        if expected_ref != edit_ref:
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface item seal differs")
        validated.append(normalized)
        seen_refs.add(edit_ref)
        seen_properties.add((prop_start, prop_end))
        primitive_counts[primitive] += 1
        previous_end = prop_end
    expected_counts = {"items": len(validated), **primitive_counts}
    for primitive in _PRIMITIVES:
        expected_counts.setdefault(primitive, 0)
    if dict(counts) != expected_counts:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface counts differ")
    return dict(surface), validated, surface_sha


def _validate_scope(value: Any, *, endpoint: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"ancestors", "stage", "occurrence"}:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface scope is invalid")
    ancestors = value["ancestors"]
    stage = value["stage"]
    occurrence = value["occurrence"]
    if (
        not isinstance(ancestors, list)
        or not 1 <= len(ancestors) <= 16
        or type(occurrence) is not int
        or not 0 <= occurrence <= MAX_EDIT_ITEMS
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface scope is invalid")
    checked_ancestors: list[dict[str, Any]] = []
    for index, ancestor in enumerate(ancestors):
        if (
            not isinstance(ancestor, Mapping)
            or set(ancestor) != {"kind", "node_id", "name", "label"}
            or ancestor.get("kind") not in {"endpoint", "variant", "block", "use_instance"}
            or not isinstance(ancestor.get("node_id"), str)
            or _NODE_RE.fullmatch(ancestor["node_id"]) is None
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface ancestor is invalid")
        name = _bounded_string(ancestor.get("name"), nullable=True)
        label = _bounded_string(ancestor.get("label"), nullable=True)
        if index == 0 and (ancestor["kind"] != "endpoint" or name != endpoint):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface endpoint scope differs")
        checked_ancestors.append({**dict(ancestor), "name": name, "label": label})
    if (
        not isinstance(stage, Mapping)
        or set(stage) != {"kind", "node_id", "identifier", "activation_sha256", "selectors"}
        or stage.get("kind") not in {"take", "return_flow", "use_block", "use_instance"}
        or not isinstance(stage.get("node_id"), str)
        or _NODE_RE.fullmatch(stage["node_id"]) is None
        or (
            stage.get("activation_sha256") is not None
            and (
                not isinstance(stage["activation_sha256"], str)
                or _HASH_RE.fullmatch(stage["activation_sha256"]) is None
            )
        )
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface stage is invalid")
    identifier = _bounded_string(stage.get("identifier"), nullable=True)
    selectors = stage["selectors"]
    if not isinstance(selectors, Mapping) or set(selectors) != {
        "identifiers",
        "string_literals",
    }:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface selectors are invalid")
    checked_selectors: dict[str, list[str]] = {}
    for key in ("identifiers", "string_literals"):
        sequence = selectors[key]
        if (
            not isinstance(sequence, list)
            or len(sequence) > 128
            or len(sequence) != len(set(sequence))
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface selectors are invalid")
        checked_selectors[key] = [str(_bounded_string(item)) for item in sequence]
    return {
        "ancestors": checked_ancestors,
        "stage": {**dict(stage), "identifier": identifier, "selectors": checked_selectors},
        "occurrence": occurrence,
    }


def _validate_old_value(primitive: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface old value is invalid")
    item = dict(value)
    if primitive == "take_cardinality":
        valid = (
            set(item) == {"type", "mode", "value"}
            and item.get("type") == "positive_integer"
            and item.get("mode") in {"count", "page_default"}
            and type(item.get("value")) is int
            and 1 <= item["value"] <= 1_000_000
        )
    elif primitive == "output_limit":
        valid = (
            set(item) == {"type", "unit", "value"}
            and item.get("type") == "non_negative_integer"
            and item.get("unit") in {"items", "percent"}
            and type(item.get("value")) is int
            and 0 <= item["value"] <= 1_000_000
        )
    elif primitive == "display_label_or_title":
        valid = set(item) == {"type", "value"} and item.get("type") == "string"
    else:
        valid = (
            set(item) == {"type", "argument", "value"}
            and item.get("type") == "string"
            and isinstance(item.get("argument"), str)
            and bool(item["argument"])
        )
    if not valid:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "edit surface old value shape differs")
    if isinstance(item.get("value"), str):
        _bounded_string(item["value"])
    return item


def _validate_authority(primitive: str, value: Any) -> dict[str, Any] | None:
    if primitive != "block_argument_list":
        if value is not None:
            raise BrainError("EDIT_SURFACE_INVALID", 503, "unexpected edit authority")
        return None
    if not isinstance(value, Mapping) or set(value) != {"bindings"}:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "block argument authority is invalid")
    bindings = value["bindings"]
    if not isinstance(bindings, list) or len(bindings) > 32:
        raise BrainError("EDIT_SURFACE_INVALID", 503, "block argument authority is invalid")
    checked: list[dict[str, str]] = []
    for binding in bindings:
        if (
            not isinstance(binding, Mapping)
            or set(binding) != {"catalog", "field"}
            or not isinstance(binding.get("catalog"), str)
            or _CATALOG_RE.fullmatch(binding["catalog"]) is None
            or not isinstance(binding.get("field"), str)
            or _FIELD_RE.fullmatch(binding["field"]) is None
        ):
            raise BrainError("EDIT_SURFACE_INVALID", 503, "block argument binding is invalid")
        checked.append({"catalog": binding["catalog"], "field": binding["field"]})
    expected = sorted(checked, key=lambda item: (item["catalog"], item["field"]))
    if checked != expected or len({(item["catalog"], item["field"]) for item in checked}) != len(
        checked
    ):
        raise BrainError("EDIT_SURFACE_INVALID", 503, "block argument bindings differ")
    return {"bindings": checked}


def _clause_at(instruction: str, start: int, end: int) -> tuple[str, int, int]:
    separators = list(re.finditer(r";|\n|\.\s+(?=[A-ZÀ-ÖØ-Þ])", instruction))
    clause_start = 0
    clause_end = len(instruction)
    for separator in separators:
        if separator.end() <= start:
            clause_start = separator.end()
        elif separator.start() >= end:
            clause_end = separator.start()
            break
    return instruction[clause_start:clause_end].strip(), clause_start, clause_end


def _numeric_transition_matches(instruction: str) -> list[_NumericTransition]:
    transitions: dict[tuple[int, int, int, int, int, int], _NumericTransition] = {}
    patterns = (
        re.compile(
            r"\bda\s+(?P<old>[1-9][0-9]{0,6})\b"
            r"(?:\s+(?:risultat[oi]|element[oi])(?:\s+(?:total[ei]|complessiv[oi]))?)?"
            r"\s+(?:a|ad)\s+(?P<new>[1-9][0-9]{0,6})\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?P<new>[1-9][0-9]{0,6})\s+risultati"
            r"(?:\s+(?:total[ei]|complessiv[oi]))?\s+invece\s+"
            r"(?:di|dei|delle?)\s+(?P<old>[1-9][0-9]{0,6})\b(?:\s+attual[ei])?",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:prende|prendi)\s+(?P<old>[1-9][0-9]{0,6})\s+"
            r"(?:risultat[oi]|element[oi])(?:\s+(?:total[ei]|complessiv[oi]))?"
            r"(?:\s+e\s+include\s+[A-Za-z_][A-Za-z0-9_.-]*"
            r"(?:\s+[A-Za-z_][A-Za-z0-9_.-]*){0,8})?\s*:?\s*"
            r"porta(?:lo|la)?\s+(?:a|ad)\s+(?P<new>[1-9][0-9]{0,6})\b",
            re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        for match in pattern.finditer(instruction):
            old = int(match.group("old"))
            new = int(match.group("new"))
            if old != new:
                clause, clause_start, clause_end = _clause_at(
                    instruction, match.start(), match.end()
                )
                key = (old, new, clause_start, clause_end, match.start(), match.end())
                candidate = _NumericTransition(
                    old=old,
                    new=new,
                    evidence=match.group(0),
                    clause=clause,
                    clause_start=clause_start,
                    clause_end=clause_end,
                    start=match.start(),
                    end=match.end(),
                )
                previous = transitions.get(key)
                if previous is None or len(candidate.evidence) < len(previous.evidence):
                    transitions[key] = candidate
    return sorted(transitions.values(), key=lambda item: (item.start, item.end))


def _numeric_transitions(instruction: str) -> set[tuple[int, int]]:
    return {(item.old, item.new) for item in _numeric_transition_matches(instruction)}


def _embedded_numeric_selectors(transition: _NumericTransition) -> tuple[str, ...]:
    match = re.search(
        r"\be\s+include\s+(?P<selectors>[A-Za-z_][A-Za-z0-9_.-]*"
        r"(?:\s+[A-Za-z_][A-Za-z0-9_.-]*){0,8})\s*:?\s*porta",
        transition.evidence,
        re.IGNORECASE,
    )
    return () if match is None else tuple(match.group("selectors").split())


def _transition_segment(
    instruction: str,
    transition: _NumericTransition,
    transitions: Sequence[_NumericTransition],
) -> str:
    """Bind a numeric transition to its local action segment."""

    siblings = [
        item
        for item in transitions
        if item.clause_start == transition.clause_start and item.clause_end == transition.clause_end
    ]
    if len(siblings) <= 1:
        return transition.clause
    siblings.sort(key=lambda item: (item.start, item.end))
    index = siblings.index(transition)
    start = transition.clause_start
    end = transition.clause_end
    if index:
        gap = instruction[siblings[index - 1].end : transition.start]
        separators = list(re.finditer(r"\b(?:e|poi)\b|,", gap, re.IGNORECASE))
        if separators:
            start = siblings[index - 1].end + separators[-1].end()
    if index + 1 < len(siblings):
        gap = instruction[transition.end : siblings[index + 1].start]
        separator = re.search(r"\b(?:e|poi)\b|,", gap, re.IGNORECASE)
        if separator is not None:
            end = transition.end + separator.start()
    return instruction[start:end].strip()


def _string_transition_matches(instruction: str, old: str) -> list[_StringTransition]:
    """Parse delimiter-bounded string changes.

    Free text has no trustworthy natural-language end marker.  The structural
    fast path therefore requires exact backtick delimiters; undelimited label
    prose remains available to the normal Model 1 route instead of guessing a
    mutation boundary.
    """

    escaped = re.escape(old)
    patterns = (
        re.compile(
            rf"(?i:\bda\s+)`{escaped}`(?i:\s+(?:a|ad)\s+)"
            rf"`(?P<new>[^`\n]{{1,512}})`"
        ),
        re.compile(
            rf"(?i:\bsostituisci\s+)`{escaped}`(?i:\s+con\s+)"
            rf"`(?P<new>[^`\n]{{1,512}})`"
        ),
    )
    matches: list[_StringTransition] = []
    for pattern in patterns:
        for match in pattern.finditer(instruction):
            candidate = match.group("new")
            if candidate != candidate.strip():
                raise BrainError(
                    "STRUCTURAL_EDIT_INVALID",
                    422,
                    "backtick replacement must not contain boundary whitespace",
                )
            if candidate and candidate != old:
                clause, clause_start, clause_end = _clause_at(
                    instruction, match.start(), match.end()
                )
                matches.append(
                    _StringTransition(
                        old=old,
                        new=candidate,
                        evidence=match.group(0),
                        clause=clause,
                        clause_start=clause_start,
                        clause_end=clause_end,
                        start=match.start(),
                        end=match.end(),
                    )
                )
    return sorted(matches, key=lambda item: (item.start, item.end))


def _assert_endpoint_identity(instruction: str, endpoint: str) -> None:
    """Bind every qualified endpoint token to the request target.

    The closed structural path cannot infer whether another qualified name is
    descriptive context or a second mutation target. It therefore accepts
    only the exact target identity and sends every other case fail-closed.
    """

    mentioned = {match.group(0) for match in _QUALIFIED_NAME_RE.finditer(instruction)}
    if mentioned - {endpoint}:
        raise BrainError(
            "STRUCTURAL_EDIT_TARGET_MISMATCH",
            422,
            "structural edit names an endpoint outside the exact request target",
        )


def _string_transition_segment(
    instruction: str,
    transition: _StringTransition,
    transitions: Sequence[_StringTransition],
) -> str:
    siblings = [
        item
        for item in transitions
        if item.clause_start == transition.clause_start and item.clause_end == transition.clause_end
    ]
    if len(siblings) <= 1:
        return transition.clause
    siblings.sort(key=lambda item: (item.start, item.end))
    index = siblings.index(transition)
    start = transition.clause_start
    end = transition.clause_end
    if index:
        gap = instruction[siblings[index - 1].end : transition.start]
        separators = list(re.finditer(r"\b(?:e|poi)\b|,", gap, re.IGNORECASE))
        if separators:
            start = siblings[index - 1].end + separators[-1].end()
    if index + 1 < len(siblings):
        gap = instruction[transition.end : siblings[index + 1].start]
        separator = re.search(r"\b(?:e|poi)\b|,", gap, re.IGNORECASE)
        if separator is not None:
            end = transition.end + separator.start()
    return instruction[start:end].strip()


def _intent_primitives(instruction: str) -> frozenset[str]:
    folded = _fold(instruction)
    primitives: set[str] = set()
    if re.search(r"\b(?:etichetta|titolo visibile|rinomina|sostituisci)\b", folded):
        primitives.add("display_label_or_title")
    argument_change = re.search(
        r"\baggiungi\b.{0,100}\b(?:lista|argomento|parametro)\b", folded
    ) or re.search(r"\b(?:lista|argomento|parametro)\b.{0,100}\b(?:cambia|modifica)\b", folded)
    if argument_change:
        primitives.add("block_argument_list")
    if re.search(r"\b(?:take|risultati|elementi|riga consumer|righe hdr|righe sdr)\b", folded):
        primitives.add("take_cardinality")
    if re.search(r"\blimit(?:e|a|ato|are|i)?\b", folded):
        primitives.add("output_limit")
    return frozenset(primitives)


def _numeric_intent_primitives(instruction: str) -> frozenset[str]:
    """Classify numeric objects without letting generic result words bleed."""

    folded = _fold(instruction)
    explicit_take = bool(
        re.search(
            r"\b(?:take|prende|prendi|riga consumer|righe hdr|righe sdr)\b",
            folded,
        )
    )
    explicit_limit = bool(re.search(r"\blimit(?:e|i|ato|are|a)?\b", folded))
    primitives: set[str] = set()
    if explicit_take:
        primitives.add("take_cardinality")
    if explicit_limit:
        primitives.add("output_limit")
    if not primitives and re.search(r"\b(?:risultati|elementi|totale|totali)\b", folded):
        primitives.add("take_cardinality")
    return frozenset(primitives)


def _string_intent_primitives(instruction: str) -> frozenset[str]:
    folded = _fold(instruction)
    primitives: set[str] = set()
    if re.search(r"\b(?:lista|argomento|parametro)\b", folded):
        primitives.add("block_argument_list")
    if re.search(r"\b(?:etichetta|titolo visibile|rinomina|rendi)\b", folded):
        primitives.add("display_label_or_title")
    return frozenset(primitives)


def _requested_take_mode(instruction: str) -> str | None:
    folded = _fold(instruction)
    if re.search(r"\b(?:page default|per pagina|paginazione|pagina)\b", folded):
        return "page_default"
    if re.search(r"\b(?:totale|totali|complessiv[ioa]|in tutto)\b", folded):
        return "count"
    return None


def _requested_limit_unit(instruction: str) -> str | None:
    folded = _fold(instruction)
    if "%" in instruction or re.search(r"\bpercent(?:o|uale|uali)?\b", folded):
        return "percent"
    if re.search(r"\blimit(?:e|a|ato|are|i)?\b", folded):
        return "items"
    return None


def structural_edit_requested(instruction: str) -> bool:
    """Return whether the instruction enters the closed structural-edit path."""

    raw_primitives = _intent_primitives(instruction)
    if not raw_primitives:
        return False
    raw_requested = bool(
        (
            _numeric_transitions(instruction)
            and raw_primitives.intersection({"take_cardinality", "output_limit"})
        )
        or (
            raw_primitives.intersection({"display_label_or_title", "block_argument_list"})
            and (
                re.search(
                    r"\bda\s+`[^`\n]{1,512}`\s+(?:a|ad)\s+`[^`\n]{1,512}`",
                    instruction,
                    re.I,
                )
                or re.search(
                    r"\bsostituisci\s+`[^`\n]{1,512}`\s+con\s+`[^`\n]{1,512}`",
                    instruction,
                    re.I,
                )
            )
        )
    )
    if not raw_requested:
        return False
    active_instruction = _active_instruction(instruction)
    primitives = _intent_primitives(active_instruction)
    if not primitives:
        return False
    requested = bool(
        (
            _numeric_transitions(active_instruction)
            and primitives.intersection({"take_cardinality", "output_limit"})
        )
        or (
            primitives.intersection({"display_label_or_title", "block_argument_list"})
            and (
                re.search(
                    r"\bda\s+`[^`\n]{1,512}`\s+(?:a|ad)\s+`[^`\n]{1,512}`",
                    active_instruction,
                    re.I,
                )
                or re.search(
                    r"\bsostituisci\s+`[^`\n]{1,512}`\s+con\s+`[^`\n]{1,512}`",
                    active_instruction,
                    re.I,
                )
            )
        )
    )
    if requested:
        _assert_no_unsupported_mutation(active_instruction)
    return requested


def _assert_no_unsupported_mutation(instruction: str) -> None:
    """Reject mixed requests instead of applying only their scalar subset."""

    if _SEMANTIC_LIMIT.search(instruction) or _PROTECTED_MUTATION_OBJECT.search(instruction):
        raise BrainError(
            "STRUCTURAL_EDIT_MIXED_INTENT",
            422,
            "structural edit contains an unsupported additional mutation",
        )
    if _UNSUPPORTED_MUTATION.search(instruction):
        raise BrainError(
            "STRUCTURAL_EDIT_MIXED_INTENT",
            422,
            "structural edit contains an unsupported additional mutation",
        )


def _scope_values(item: Mapping[str, Any]) -> list[str]:
    return [value for _kind, value in _scope_entries(item)]


def _scope_entries(item: Mapping[str, Any]) -> list[tuple[str, str]]:
    scope = item["scope"]
    values: list[tuple[str, str]] = []
    for ancestor in scope["ancestors"][1:]:
        for key in ("name", "label"):
            value = ancestor.get(key)
            if isinstance(value, str):
                values.append((ancestor["kind"], value))
    stage = scope["stage"]
    if isinstance(stage.get("identifier"), str):
        values.append((f"stage_identifier:{stage['kind']}", stage["identifier"]))
    values.extend(("stage_selector", value) for value in stage["selectors"]["identifiers"])
    values.extend(("stage_selector", value) for value in stage["selectors"]["string_literals"])
    old = item["old_value"]
    if isinstance(old.get("argument"), str):
        values.append(("argument", old["argument"]))
    return values


def _scope_score(instruction: str, item: Mapping[str, Any]) -> int:
    raw_folded = instruction.casefold()
    folded = _fold(instruction)
    score = 0
    for value in _scope_values(item):
        raw = value.casefold()
        alternatives = {raw, raw.removeprefix("block."), raw.replace("_", " ")}
        if any(
            len(candidate) >= 3
            and re.search(rf"(?<![\w]){re.escape(candidate)}(?![\w])", raw_folded)
            for candidate in alternatives
        ):
            score += 20 + min(40, len(value))
            if any(f"`{candidate}`" in raw_folded for candidate in alternatives):
                score += 80
            continue
        normalized = _fold(value)
        if len(normalized) >= 3 and re.search(rf"(?:^|\s){re.escape(normalized)}(?:\s|$)", folded):
            score += 15 + min(30, len(normalized))
            continue
    return score


def _explicit_scope_query_spans(instruction: str) -> list[tuple[str, str, int, int]]:
    """Extract every explicitly named compiler scope from active prose."""

    queries: list[tuple[str, str, int, int]] = []
    for match in _SCOPE_KIND_RE.finditer(instruction):
        kind = _fold(match.group(1))
        tail = instruction[match.end() :]
        boundary = _SCOPE_BOUNDARY_RE.search(tail)
        raw_body = tail[: boundary.start()] if boundary is not None else tail
        body = raw_body
        body = body.strip().strip('`"“”()[] ')
        words = body.split()
        while words and _fold(words[0]) in _SCOPE_PREFIX_WORDS:
            words.pop(0)
        body = " ".join(words).strip().strip('`"“”()[] ')
        if not body:
            continue
        parts = re.split(r"\s+(?:e|/)\s+", body, flags=re.IGNORECASE) if kind == "righe" else [body]
        for part in parts:
            query = part.strip().strip('`"“”()[] ')
            if query:
                relative = raw_body.find(part)
                if relative < 0:
                    relative = raw_body.find(query)
                start = match.end() + max(0, relative)
                query_relative = instruction[start : match.end() + len(raw_body)].find(query)
                start += max(0, query_relative)
                queries.append((kind, query, start, start + len(query)))
    return queries


def _explicit_scope_queries(instruction: str) -> list[tuple[str, str]]:
    return [(kind, query) for kind, query, _start, _end in _explicit_scope_query_spans(instruction)]


def _scope_query_matches(kind: str, query: str, item: Mapping[str, Any]) -> bool:
    expected = _fold(query)
    if not expected:
        return False
    expected_tokens = expected.split()
    accepted_kinds = {
        "variante": {"variant"},
        "blocco": {"block"},
        "istanza": {
            "use_instance",
            "stage_identifier:use_block",
            "stage_identifier:use_instance",
        },
        "riga": {
            "stage_identifier:take",
            "stage_identifier:return_flow",
            "stage_selector",
        },
        "righe": {
            "stage_identifier:take",
            "stage_identifier:return_flow",
            "stage_selector",
        },
        "ramo": {"stage_selector"},
    }.get(kind, set())
    for entry_kind, value in _scope_entries(item):
        if entry_kind not in accepted_kinds:
            continue
        observed = _fold(value)
        if not observed:
            continue
        if expected == observed:
            return True
        if (
            len(expected_tokens) == 1
            and expected_tokens[0] in {"hdr", "sdr"}
            and observed
            in {
                f"4k {expected_tokens[0]}",
                f"4k{expected_tokens[0]}",
                f"uhd {expected_tokens[0]}",
                f"uhd{expected_tokens[0]}",
            }
        ):
            return True
    return False


def _segment_scopes_match(segment: str, item: Mapping[str, Any]) -> bool:
    grouped: dict[str, list[str]] = defaultdict(list)
    for kind, query in _explicit_scope_queries(segment):
        grouped[kind].append(query)
    for kind, queries in grouped.items():
        if (
            item["primitive"] == "output_limit"
            and kind in {"riga", "righe", "ramo"}
            and re.search(r"\brelativo\s+limite(?:\s+finale)?\b", _fold(segment))
        ):
            continue
        matches = [_scope_query_matches(kind, query, item) for query in queries]
        if (
            kind == "righe"
            and len(queries) > 1
            and re.search(r"\b(?:entrambe|entrambi)\b", _fold(segment))
        ):
            if not any(matches):
                return False
        elif not all(matches):
            return False
    return True


def _assert_all_scopes_resolved(
    instruction: str,
    replacements: Sequence[_Replacement],
) -> None:
    for kind, query in _explicit_scope_queries(instruction):
        if not any(
            _scope_query_matches(kind, query, replacement.item) for replacement in replacements
        ):
            raise BrainError(
                "STRUCTURAL_EDIT_SCOPE_UNRESOLVED",
                422,
                "explicit structural scope has no compiler-owned match",
            )


def _assert_action_ledger(
    instruction: str,
    numeric: Sequence[_NumericTransition],
    strings: Sequence[_StringTransition],
    replacements: Sequence[_Replacement],
) -> None:
    """Require every admitted action to own exact transition evidence."""

    actions = list(_ACTION_RE.finditer(instruction))
    for index, action in enumerate(actions):
        right = actions[index + 1].start() if index + 1 < len(actions) else len(instruction)
        punctuation = re.search(
            r";|:|\n|\.(?:\s+(?=[A-ZÀ-ÖØ-Þ])|\s*$)",
            instruction[action.end() : right],
        )
        if punctuation is not None:
            right = action.end() + punctuation.start()
        left = (
            max(
                instruction.rfind(".", 0, action.start()),
                instruction.rfind(";", 0, action.start()),
                instruction.rfind(":", 0, action.start()),
                instruction.rfind("\n", 0, action.start()),
            )
            + 1
        )
        prefix = instruction[left : action.start()]
        connector = re.search(r"\b(?:e|ma|pero|però|poi)\s*$", prefix, re.IGNORECASE)
        if connector is not None:
            left += connector.end()
        unit = instruction[left:right]
        verb = _fold(action.group(0))
        if (
            index == 0
            and action.start() == 0
            and re.fullmatch(
                r"\s*modifica\s+[A-Za-z_][A-Za-z0-9_-]*"
                r"(?:\.[A-Za-z_][A-Za-z0-9_-]*)+\s*",
                unit,
                re.IGNORECASE,
            )
            and any(transition.start > action.end() for transition in [*numeric, *strings])
        ):
            continue
        if any(
            transition.start < right and transition.end > action.start()
            for transition in [*numeric, *strings]
        ):
            continue
        if verb in {"modifica", "modificare", "rendi", "rendere"} and index + 1 < len(actions):
            next_start = actions[index + 1].start()
            if any(transition.start == next_start for transition in [*numeric, *strings]):
                continue
        if verb in {"aggiorna", "aggiornare"} and any(
            re.fullmatch(
                rf"\s*aggiorna(?:re)?\s+(?:il\s+)?(?:relativo\s+)?"
                rf"limite(?:\s+finale)?\s+(?:a|ad)\s+{transition.new}\s*",
                unit,
                re.IGNORECASE,
            )
            for transition in numeric
        ):
            continue
        if verb in {"aggiungi", "aggiungere"}:
            for replacement in replacements:
                if replacement.item["primitive"] != "block_argument_list":
                    continue
                evidence_kind, evidence_start, evidence_end = replacement.evidence_key
                transition = next(
                    (
                        candidate
                        for candidate in strings
                        if evidence_kind == "string"
                        and candidate.start == evidence_start
                        and candidate.end == evidence_end
                        and action.start() < candidate.start
                        and candidate.clause_start <= action.start() < candidate.clause_end
                    ),
                    None,
                )
                if transition is None:
                    continue
                old = replacement.item["old_value"]
                argument = old.get("argument")
                old_parts = [part.strip() for part in str(old.get("value", "")).split(",")]
                new_parts = [part.strip() for part in str(replacement.new_value).split(",")]
                added = [part for part in new_parts if part not in old_parts]
                if len(added) != 1 or not isinstance(argument, str):
                    continue
                if re.search(
                    rf"\baggiung(?:i|ere)\s+{re.escape(added[0])}\s+alla\s+lista\s+"
                    rf"{re.escape(argument)}\b",
                    unit,
                    re.IGNORECASE,
                ):
                    break
            else:
                raise BrainError(
                    "STRUCTURAL_EDIT_MIXED_INTENT",
                    422,
                    "block argument action lacks exact replacement evidence",
                )
            continue
        raise BrainError(
            "STRUCTURAL_EDIT_MIXED_INTENT",
            422,
            "structural edit contains an unconsumed action",
        )


def _assert_numeric_suffixes(
    instruction: str,
    transitions: Sequence[_NumericTransition],
    replacements: Sequence[_Replacement],
) -> None:
    """Admit only closed suffixes after explicit numeric evidence."""

    selected_numeric = [
        replacement
        for replacement in replacements
        if replacement.item["primitive"] in {"take_cardinality", "output_limit"}
    ]
    clauses: dict[tuple[int, int], list[_NumericTransition]] = defaultdict(list)
    for transition in transitions:
        clauses[(transition.clause_start, transition.clause_end)].append(transition)
    for (_clause_start, clause_end), members in clauses.items():
        members.sort(key=lambda item: (item.start, item.end))
        for transition in members:
            bound_primitives = {
                replacement.item["primitive"]
                for replacement in selected_numeric
                if replacement.evidence_key == ("numeric", transition.start, transition.end)
                and replacement.item["old_value"]["value"] == transition.old
                and replacement.new_value == transition.new
            }
            if bound_primitives == {"take_cardinality", "output_limit"}:
                shared_limit = re.compile(
                    rf"\be\s+(?:(?:aggiorna|aggiornare)\s+)?(?:il\s+)?"
                    rf"(?:relativo\s+)?limite(?:\s+finale)?\s+(?:a|ad)\s+{transition.new}\b",
                    re.IGNORECASE,
                )
                if shared_limit.search(instruction[transition.end : clause_end]) is None:
                    raise BrainError(
                        "STRUCTURAL_EDIT_MIXED_INTENT",
                        422,
                        "shared numeric replacement lacks exact limit evidence",
                    )
        suffix = instruction[members[-1].end : clause_end]
        last = members[-1]
        suffix = re.sub(
            rf"\be\s+(?:(?:aggiorna|aggiornare)\s+)?(?:il\s+)?"
            rf"(?:relativo\s+)?limite(?:\s+finale)?\s+(?:a|ad)\s+{last.new}\b",
            " ",
            suffix,
            flags=re.IGNORECASE,
        )
        suffix = re.sub(
            r"\b(?:nel|nella|nello|nell['’]|sul|sulla)\s+"
            r"(?:ramo|variante|blocco|istanza|riga)\s+[^,.;\n]+",
            " ",
            suffix,
            flags=re.IGNORECASE,
        )
        allowed = {
            "risultato",
            "risultati",
            "elemento",
            "elementi",
            "totale",
            "totali",
            "complessivo",
            "complessivi",
            "attuale",
            "attuali",
            "per",
            "pagina",
            "nel",
            "in",
            "tutto",
            "percento",
            "percentuale",
        }
        if any(token not in allowed for token in _fold(suffix).split()):
            raise BrainError(
                "STRUCTURAL_EDIT_MIXED_INTENT",
                422,
                "numeric edit has unconsumed trailing content",
            )


def _assert_positive_language_ledger(
    instruction: str,
    numeric: Sequence[_NumericTransition],
    strings: Sequence[_StringTransition],
    replacements: Sequence[_Replacement],
) -> None:
    """Fail closed unless all active prose belongs to the bounded edit grammar."""

    mask = list(instruction)

    def erase(start: int, end: int) -> None:
        for index in range(max(0, start), min(len(mask), end)):
            mask[index] = " "

    for transition in [*numeric, *strings]:
        erase(transition.start, transition.end)
    for match in re.finditer(
        r"(?<![A-Za-z0-9_-])[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)+"
        r"(?![A-Za-z0-9_-])",
        instruction,
    ):
        erase(match.start(), match.end())
    for transition in numeric:
        paired_limit = re.compile(
            rf"\be\s+(?:(?:aggiorna|aggiornare)\s+)?(?:il\s+)?"
            rf"(?:relativo\s+)?limite(?:\s+finale)?\s+(?:a|ad)\s+{transition.new}\b",
            re.IGNORECASE,
        )
        for match in paired_limit.finditer(instruction, transition.end, transition.clause_end):
            erase(match.start(), match.end())
    for _kind, _query, start, end in _explicit_scope_query_spans(instruction):
        erase(start, end)
    for replacement in replacements:
        old = replacement.item["old_value"]
        if replacement.item["primitive"] == "block_argument_list":
            argument = old.get("argument")
            old_parts = [part.strip() for part in str(old.get("value", "")).split(",")]
            new_parts = [part.strip() for part in str(replacement.new_value).split(",")]
            for added in (part for part in new_parts if part not in old_parts):
                prefix = re.compile(
                    rf"\baggiungi\s+(?P<literal>{re.escape(added)})\s+alla\s+lista\s+"
                    rf"(?P<argument>{re.escape(str(argument))})\b",
                    re.IGNORECASE,
                )
                for match in prefix.finditer(instruction):
                    erase(match.start("literal"), match.end("literal"))
                    erase(match.start("argument"), match.end("argument"))
        for _kind, selector in _scope_entries(replacement.item):
            if len(selector) < 3:
                continue
            object_name = re.compile(
                rf"\b(?:lista|argomento|parametro|take|limite|riga|righe)\s+"
                rf"(?P<selector>{re.escape(selector)})\b",
                re.IGNORECASE,
            )
            for match in object_name.finditer(instruction):
                erase(match.start("selector"), match.end("selector"))
            included = re.compile(
                rf"\binclude\s+(?P<selector>{re.escape(selector)})\b",
                re.IGNORECASE,
            )
            for match in included.finditer(instruction):
                erase(match.start("selector"), match.end("selector"))
    residue = _fold("".join(mask))
    unsupported = [word for word in residue.split() if word not in _POSITIVE_LEDGER_WORDS]
    if unsupported:
        raise BrainError(
            "STRUCTURAL_EDIT_MIXED_INTENT",
            422,
            "structural edit contains prose outside the bounded grammar",
        )


def _reviewed_values(grounding: Mapping[str, Any]) -> frozenset[tuple[str, str, str]]:
    values: set[tuple[str, str, str]] = set()
    resolutions = grounding.get("resolutions")
    if isinstance(resolutions, Sequence) and not isinstance(resolutions, (str, bytes)):
        for item in resolutions:
            if (
                isinstance(item, Mapping)
                and item.get("review_state") == "reviewed"
                and isinstance(item.get("catalog"), str)
                and isinstance(item.get("field"), str)
                and isinstance(item.get("literal"), str)
            ):
                values.add((item["catalog"], item["field"], item["literal"]))
    return frozenset(values)


def _block_argument_grants(
    *,
    replacement: _Replacement,
    items: Sequence[Mapping[str, Any]],
    reviewed: frozenset[tuple[str, str, str]],
) -> tuple[tuple[str, str, str, str, str | None], ...]:
    """Resolve every binding from review or an exact same-snapshot witness."""

    old_items = [part.strip() for part in str(replacement.item["old_value"]["value"]).split(",")]
    new_items = [part.strip() for part in str(replacement.new_value).split(",")]
    added = [part for part in new_items if part not in old_items]
    witnesses: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for item in items:
        if item.get("primitive") != "block_argument_list":
            continue
        authority = item.get("authority")
        old_value = item.get("old_value")
        if not isinstance(authority, Mapping) or not isinstance(old_value, Mapping):
            continue
        value = old_value.get("value")
        edit_ref = item.get("edit_ref")
        if not isinstance(value, str) or not isinstance(edit_ref, str):
            continue
        literals = [part.strip() for part in value.split(",") if part.strip()]
        for binding in authority.get("bindings", []):
            if not isinstance(binding, Mapping):
                continue
            catalog = binding.get("catalog")
            field = binding.get("field")
            if not isinstance(catalog, str) or not isinstance(field, str):
                continue
            for literal in literals:
                witnesses[(catalog, field, literal)].add(edit_ref)
    grants: list[tuple[str, str, str, str, str | None]] = []
    for binding in replacement.item["authority"]["bindings"]:
        for literal in added:
            key = (binding["catalog"], binding["field"], literal)
            if key in reviewed:
                grants.append(("reviewed_catalog_value", *key, None))
                continue
            refs = sorted(witnesses.get(key, ()))
            if not refs:
                raise BrainError(
                    "STRUCTURAL_EDIT_AUTHORITY_MISSING",
                    422,
                    "new argument value has no reviewed or source-witness authority",
                )
            grants.append(("same_snapshot_source_witness", *key, refs[0]))
    if not added or not grants:
        raise BrainError(
            "STRUCTURAL_EDIT_AUTHORITY_MISSING",
            422,
            "new argument value has no reviewed or source-witness authority",
        )
    return tuple(grants)


def _select_replacements(
    instruction: str,
    items: Sequence[dict[str, Any]],
    grounding: Mapping[str, Any],
) -> list[_Replacement]:
    active_instruction = _active_instruction(instruction)
    _assert_no_unsupported_mutation(active_instruction)
    numeric_matches = _numeric_transition_matches(active_instruction)
    candidates: dict[
        tuple[str, int, int, str, int | str, int | str],
        list[tuple[int, dict[str, Any], str, str]],
    ] = defaultdict(list)
    expected_numeric: set[tuple[str, int, int, str, int | str, int | str]] = set()
    expected_string: set[tuple[str, int, int, str, int | str, int | str]] = set()

    for transition in numeric_matches:
        segment = _transition_segment(active_instruction, transition, numeric_matches)
        transition_primitives = _numeric_intent_primitives(segment)
        if not transition_primitives:
            raise BrainError(
                "STRUCTURAL_EDIT_UNRESOLVED",
                422,
                "numeric transition has no closed compiler primitive",
            )
        requested_take_mode = _requested_take_mode(segment)
        requested_limit_unit = _requested_limit_unit(segment)
        for primitive in transition_primitives:
            key = (
                "numeric",
                transition.start,
                transition.end,
                primitive,
                transition.old,
                transition.new,
            )
            expected_numeric.add(key)
            for item in items:
                if item["primitive"] != primitive:
                    continue
                old = item["old_value"]["value"]
                if type(old) is not int or old != transition.old:
                    continue
                if (
                    primitive == "take_cardinality"
                    and requested_take_mode is not None
                    and item["old_value"]["mode"] != requested_take_mode
                ) or (
                    primitive == "output_limit"
                    and requested_limit_unit is not None
                    and item["old_value"]["unit"] != requested_limit_unit
                ):
                    continue
                if not _segment_scopes_match(segment, item):
                    continue
                embedded = _embedded_numeric_selectors(transition)
                selectors = {
                    *item["scope"]["stage"]["selectors"]["identifiers"],
                    *item["scope"]["stage"]["selectors"]["string_literals"],
                }
                if any(selector not in selectors for selector in embedded):
                    continue
                evidence = f"{transition.start}:{transition.end}:{transition.evidence}"
                score_context = segment.replace(transition.evidence, " ", 1)
                candidates[key].append(
                    (
                        _scope_score(score_context, item),
                        item,
                        evidence,
                        segment,
                    )
                )

    old_strings = {
        item["old_value"]["value"]
        for item in items
        if isinstance(item["old_value"].get("value"), str)
    }
    string_matches = sorted(
        (
            transition
            for old in old_strings
            for transition in _string_transition_matches(active_instruction, old)
        ),
        key=lambda item: (item.start, item.end, item.old),
    )
    for old in old_strings:
        surface_primitives = {
            item["primitive"]
            for item in items
            if item["old_value"].get("value") == old
            and item["primitive"] in {"display_label_or_title", "block_argument_list"}
        }
        for transition in (item for item in string_matches if item.old == old):
            segment = _string_transition_segment(
                active_instruction,
                transition,
                string_matches,
            )
            clause_primitives = _string_intent_primitives(segment)
            if len(clause_primitives) > 1:
                raise BrainError(
                    "STRUCTURAL_EDIT_AMBIGUOUS",
                    422,
                    "string edit names more than one compiler primitive",
                )
            if clause_primitives:
                intended_primitives = clause_primitives
            else:
                if surface_primitives != {"display_label_or_title"}:
                    raise BrainError(
                        "STRUCTURAL_EDIT_AMBIGUOUS",
                        422,
                        "string edit object is not explicit",
                    )
                intended_primitives = frozenset({"display_label_or_title"})
            for primitive in intended_primitives:
                key = (
                    "string",
                    transition.start,
                    transition.end,
                    primitive,
                    old,
                    transition.new,
                )
                expected_string.add(key)
                for item in items:
                    if item["primitive"] != primitive or item["old_value"].get("value") != old:
                        continue
                    if not _segment_scopes_match(segment, item):
                        continue
                    score_context = segment.replace(transition.evidence, " ", 1)
                    candidates[key].append(
                        (
                            _scope_score(score_context, item),
                            item,
                            transition.evidence,
                            segment,
                        )
                    )
    if not candidates:
        if not numeric_matches and not _intent_primitives(active_instruction):
            raise StructuralEditInapplicable("instruction has no closed structural edit intent")
        if _explicit_scope_queries(active_instruction):
            raise BrainError(
                "STRUCTURAL_EDIT_SCOPE_UNRESOLVED",
                422,
                "explicit structural scope has no compiler-owned match",
            )
        raise BrainError(
            "STRUCTURAL_EDIT_UNRESOLVED",
            422,
            "structural edit has no exact old-to-new operator evidence",
        )
    if (expected_numeric | expected_string) - set(candidates):
        if _explicit_scope_queries(active_instruction):
            raise BrainError(
                "STRUCTURAL_EDIT_SCOPE_UNRESOLVED",
                422,
                "explicit structural scope has no compiler-owned match",
            )
        raise BrainError(
            "STRUCTURAL_EDIT_UNRESOLVED",
            422,
            "one or more numeric objects have no compiler-owned target",
        )
    selected: list[_Replacement] = []
    reviewed = _reviewed_values(grounding)
    for (_kind, _start, _end, primitive, old, new), group in candidates.items():
        best = max(item[0] for item in group)
        winners = [item for item in group if item[0] == best]
        context = group[0][3]
        plural = bool(re.search(r"\b(?:entrambe|entrambi)\b", _fold(context)))
        if plural and primitive == "take_cardinality":
            row_queries = [
                query for kind, query in _explicit_scope_queries(context) if kind == "righe"
            ]
            exact_plural = len(winners) == 2
            if exact_plural and len(row_queries) > 1:
                matrix = [
                    [_scope_query_matches("righe", query, winner[1]) for query in row_queries]
                    for winner in winners
                ]
                exact_plural = all(sum(row) == 1 for row in matrix) and all(
                    sum(row[column] for row in matrix) == 1 for column in range(len(row_queries))
                )
            if not exact_plural:
                raise BrainError(
                    "STRUCTURAL_EDIT_AMBIGUOUS",
                    422,
                    "plural structural edit does not bind exactly two take occurrences",
                )
        elif len(winners) > 1:
            raise BrainError(
                "STRUCTURAL_EDIT_AMBIGUOUS",
                422,
                "structural edit matches more than one compiler occurrence",
            )
        added: list[str] = []
        if primitive == "block_argument_list":
            if not isinstance(old, str) or not isinstance(new, str):
                raise BrainError("STRUCTURAL_EDIT_INVALID", 422, "argument edit is invalid")
            old_items = [part.strip() for part in old.split(",")]
            new_items = [part.strip() for part in new.split(",")]
            if (
                not old_items
                or not new_items
                or any(not part or len(part) > 256 for part in [*old_items, *new_items])
                or len(new_items) != len(set(new_items))
                or [part for part in new_items if part in old_items] != old_items
            ):
                raise BrainError("STRUCTURAL_EDIT_INVALID", 422, "argument list is invalid")
            added = [part for part in new_items if part not in old_items]
            if not added:
                raise BrainError(
                    "STRUCTURAL_EDIT_AUTHORITY_MISSING",
                    422,
                    "new argument value has no reviewed catalog authority",
                )
        for _score, item, evidence, _context in winners:
            replacement = _Replacement(
                item=item,
                new_value=new,
                evidence_sha256=_sha(evidence.encode("utf-8")),
                evidence_key=(_kind, _start, _end),
            )
            if primitive == "block_argument_list":
                _block_argument_grants(
                    replacement=replacement,
                    items=items,
                    reviewed=reviewed,
                )
            selected.append(replacement)
    selected.sort(key=lambda item: item.item["property"]["span"]["utf8_bytes"]["start"])
    if len({item.item["edit_ref"] for item in selected}) != len(selected):
        raise BrainError(
            "STRUCTURAL_EDIT_AMBIGUOUS",
            422,
            "a compiler occurrence received more than one replacement",
        )
    selected_primitives = {item.item["primitive"] for item in selected}
    explicitly_named_primitives = {
        *_numeric_intent_primitives(active_instruction),
        *_string_intent_primitives(active_instruction),
    }
    if explicitly_named_primitives - selected_primitives:
        raise BrainError(
            "STRUCTURAL_EDIT_MIXED_INTENT",
            422,
            "structural edit mentions an object without exact transition authority",
        )
    _assert_numeric_suffixes(active_instruction, numeric_matches, selected)
    _assert_positive_language_ledger(
        active_instruction,
        numeric_matches,
        string_matches,
        selected,
    )
    _assert_action_ledger(active_instruction, numeric_matches, string_matches, selected)
    _assert_all_scopes_resolved(active_instruction, selected)
    if not 1 <= len(selected) <= MAX_EDIT_OPERATIONS:
        raise BrainError("STRUCTURAL_EDIT_LIMIT", 422, "structural edit operation bound exceeded")
    return selected


def _token_for(item: Mapping[str, Any], new_value: int | str) -> bytes:
    primitive = item["primitive"]
    if primitive in {"take_cardinality", "output_limit"}:
        if type(new_value) is not int or not 0 <= new_value <= 1_000_000:
            raise BrainError("STRUCTURAL_EDIT_INVALID", 422, "numeric replacement is invalid")
        if primitive == "take_cardinality" and new_value == 0:
            raise BrainError("STRUCTURAL_EDIT_INVALID", 422, "take replacement must be positive")
        return str(new_value).encode("ascii")
    if (
        not isinstance(new_value, str)
        or not new_value
        or len(new_value.encode("utf-16-le")) // 2 > MAX_EDIT_TEXT_UNITS
        or any(ord(char) < 0x20 for char in new_value)
    ):
        raise BrainError("STRUCTURAL_EDIT_INVALID", 422, "text replacement is invalid")
    return json.dumps(new_value, ensure_ascii=False).encode("utf-8")


def _build_compiler_plan(
    *,
    source: str,
    replacements: Sequence[_Replacement],
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    raw = source.encode("utf-8")
    groups: dict[tuple[int, int, str], list[_Replacement]] = defaultdict(list)
    owners: dict[tuple[int, int, str], dict[str, Any]] = {}
    for replacement in replacements:
        owner = replacement.item["owner"]
        span = owner["span"]["utf8_bytes"]
        key = (span["start"], span["end"], owner["node_id"])
        groups[key].append(replacement)
        owners[key] = owner
    ordered_keys = sorted(groups)
    for left, right in zip(ordered_keys, ordered_keys[1:], strict=False):
        if left[1] > right[0]:
            raise BrainError("STRUCTURAL_EDIT_AMBIGUOUS", 422, "editable owners overlap")
    operations: list[dict[str, Any]] = []
    owner_payloads: list[dict[str, Any]] = []
    for ordinal, key in enumerate(ordered_keys):
        start, end, node_id = key
        owner = owners[key]
        payload = raw[start:end]
        local_changes: list[tuple[int, int, bytes]] = []
        for replacement in groups[key]:
            prop = replacement.item["property"]["span"]["utf8_bytes"]
            p_start, p_end = prop["start"], prop["end"]
            if not start <= p_start < p_end <= end:
                raise BrainError("EDIT_SURFACE_INVALID", 503, "property escaped its owner")
            token = raw[p_start:p_end]
            old = replacement.item["old_value"]["value"]
            if isinstance(old, int):
                if token != str(old).encode("ascii"):
                    raise BrainError("EDIT_SURFACE_INVALID", 503, "numeric preimage differs")
            else:
                try:
                    decoded = json.loads(token.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise BrainError(
                        "EDIT_SURFACE_INVALID", 503, "string preimage differs"
                    ) from error
                if decoded != old:
                    raise BrainError("EDIT_SURFACE_INVALID", 503, "string preimage differs")
            local_changes.append(
                (
                    p_start - start,
                    p_end - start,
                    _token_for(replacement.item, replacement.new_value),
                )
            )
        for local_start, local_end, token in sorted(local_changes, reverse=True):
            payload = payload[:local_start] + token + payload[local_end:]
        operation = {
            "kind": "replace",
            "ordinal": ordinal,
            "targetId": node_id,
            "preimageSha256": owner["preimage_sha256"],
            "text": payload.decode("utf-8"),
        }
        operations.append(operation)
        owner_payloads.append(
            {
                "start": start,
                "end": end,
                "owner": owner,
                "payload": payload,
                "operation": operation,
            }
        )
    rendered = raw
    for item in reversed(owner_payloads):
        rendered = rendered[: item["start"]] + item["payload"] + rendered[item["end"] :]
    if len(rendered) > MAX_SOURCE_BYTES:
        raise BrainError("STRUCTURAL_EDIT_LIMIT", 422, "rendered source exceeds its limit")
    return (
        rendered.decode("utf-8"),
        {
            "contract": LOSSLESS_PLAN_CONTRACT,
            "baseSha256": _sha(raw),
            "operations": operations,
        },
        owner_payloads,
    )


def _permit_operations(
    *,
    replacements: Sequence[_Replacement],
    items: Sequence[Mapping[str, Any]],
    grounding: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    reviewed = _reviewed_values(grounding)
    operations: list[dict[str, Any]] = []
    roles: dict[str, str] = {}
    registry: dict[str, Any] = {}
    for ordinal, replacement in enumerate(replacements):
        surface_ref = _host_ref("surface")
        value_ref = _host_ref("value")
        evidence_ref = _host_ref("evidence")
        grant_ref: str | None = None
        if replacement.item["primitive"] == "block_argument_list":
            grants = _block_argument_grants(
                replacement=replacement,
                items=items,
                reviewed=reviewed,
            )
            grant_ref = _host_ref("block_argument_authority")
            roles[grant_ref] = "block_argument_authority"
            registry[grant_ref] = grants
        roles.update(
            {
                surface_ref: "surface",
                value_ref: "value",
                evidence_ref: "evidence",
            }
        )
        registry[surface_ref] = replacement.item
        registry[value_ref] = replacement.new_value
        registry[evidence_ref] = replacement.evidence_sha256
        operations.append(
            {
                "ordinal": ordinal,
                "kind": "replace_scalar",
                "primitive": replacement.item["primitive"],
                "surface_ref": surface_ref,
                "value_ref": value_ref,
                "evidence_ref": evidence_ref,
                "authority_grant_ref": grant_ref,
            }
        )
    return operations, roles, registry


def _authorized_replacements(
    *,
    authorized: Any,
    registry: Mapping[str, Any],
) -> list[_Replacement]:
    """Translate consumed opaque references back into the exact host plan."""

    replacements: list[_Replacement] = []
    for expected_ordinal, operation in enumerate(authorized.operations):
        if operation.ordinal != expected_ordinal:
            raise BrainError("DELTA_PERMIT_INVALID", 503, "authorized delta order differs")
        item = registry.get(operation.surface_ref)
        value = registry.get(operation.value_ref)
        evidence = registry.get(operation.evidence_ref)
        if (
            not isinstance(item, Mapping)
            or item.get("primitive") != operation.primitive
            or not isinstance(value, (str, int))
            or isinstance(value, bool)
            or not isinstance(evidence, str)
            or _HASH_RE.fullmatch(evidence) is None
        ):
            raise BrainError("DELTA_PERMIT_INVALID", 503, "authorized delta reference differs")
        if operation.primitive == "block_argument_list":
            grant = registry.get(operation.authority_grant_ref)
            if not isinstance(grant, tuple) or not grant:
                raise BrainError(
                    "DELTA_PERMIT_INVALID",
                    503,
                    "authorized catalog grant is unavailable",
                )
        elif operation.authority_grant_ref is not None:
            raise BrainError("DELTA_PERMIT_INVALID", 503, "unexpected catalog grant")
        replacements.append(
            _Replacement(item=dict(item), new_value=value, evidence_sha256=evidence)
        )
    return replacements


def _validate_apply_receipt(
    envelope: Any,
    *,
    original: str,
    expected: str,
    relative_path: str,
    endpoint: str,
    plan: Mapping[str, Any],
    owners: Sequence[Mapping[str, Any]],
    delta_receipt_sha256: str,
    expected_toolchain: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(envelope, Mapping)
        or set(envelope)
        != {
            "schema_version",
            "operation",
            "status",
            "relative_path",
            "endpoint",
            "proof_mode",
            "receipt",
        }
        or envelope.get("schema_version") != 1
        or envelope.get("operation") != "lossless-apply"
        or envelope.get("status") != "ok"
        or envelope.get("relative_path") != relative_path
        or envelope.get("endpoint") != endpoint
        or envelope.get("proof_mode") != "validate"
    ):
        raise BrainError("LOSSLESS_REJECTED", 422, "compiler lossless edit was rejected")
    receipt = envelope["receipt"]
    if (
        not isinstance(receipt, Mapping)
        or set(receipt)
        != {
            "contract",
            "outcome",
            "toolchain",
            "shaBefore",
            "shaAfter",
            "touchedSpans",
            "diagnostics",
            "reasons",
            "renderedText",
        }
        or receipt.get("contract") != LOSSLESS_RECEIPT_CONTRACT
        or receipt.get("outcome") != "APPLIED"
        or receipt.get("shaBefore") != plan["baseSha256"]
        or receipt.get("shaAfter") != _sha(expected.encode("utf-8"))
        or receipt.get("renderedText") != expected
        or receipt.get("diagnostics") != []
        or receipt.get("reasons") != []
        or receipt.get("toolchain") != expected_toolchain
        or not isinstance(receipt.get("touchedSpans"), list)
        or len(receipt["touchedSpans"]) != len(owners)
    ):
        raise BrainError("LOSSLESS_INVALID", 503, "compiler lossless receipt is invalid")
    for ordinal, (touched, owner_payload) in enumerate(
        zip(receipt["touchedSpans"], owners, strict=True)
    ):
        owner = owner_payload["owner"]
        operation = owner_payload["operation"]
        span = owner["span"]
        expected_before = {
            "offset": span["utf16"]["start"],
            "end": span["utf16"]["end"],
            "byteOffset": span["utf8_bytes"]["start"],
            "byteEnd": span["utf8_bytes"]["end"],
        }
        if (
            not isinstance(touched, Mapping)
            or set(touched) != {"ordinal", "kind", "targetId", "before", "afterByteLength"}
            or touched.get("ordinal") != ordinal
            or touched.get("kind") != "replace"
            or touched.get("targetId") != operation["targetId"]
            or touched.get("before") != expected_before
            or touched.get("afterByteLength") != len(owner_payload["payload"])
        ):
            raise BrainError("LOSSLESS_INVALID", 503, "compiler touched span differs")
    compiler_receipt_sha = canonical_sha256(dict(receipt))
    return {
        "contract": STRUCTURAL_LOSSLESS_PROOF_CONTRACT,
        "proof_mode": "validate",
        "receipt_sha256": canonical_sha256(
            {
                "compiler_receipt_sha256": compiler_receipt_sha,
                "delta_receipt_sha256": delta_receipt_sha256,
            }
        ),
        "sha_before": _sha(original.encode("utf-8")),
        "sha_after": _sha(expected.encode("utf-8")),
        "touched_count": len(owners),
    }


def render_structural_existing(
    *,
    compiler: Any,
    lease: Any,
    request: Any,
    record: Any,
    grounding: Mapping[str, Any],
    source: str | None,
) -> LosslessRenderResult | None:
    """Render a complex existing-endpoint scalar edit without model generation."""

    target = request.target
    endpoint = target.get("endpoint")
    if target.get("mode") != "existing" or not isinstance(endpoint, str) or source is None:
        return None
    try:
        primitives = _intent_primitives(request.instruction)
        if not primitives:
            return None
        if not callable(getattr(compiler, "edit_surface", None)) or not callable(
            getattr(compiler, "lossless_apply", None)
        ):
            raise BrainError(
                "EDIT_SURFACE_UNAVAILABLE",
                503,
                "compiler structural edit surface is unavailable",
            )
        expected_toolchain = getattr(compiler, "lossless_toolchain_identity", None)
        if not isinstance(expected_toolchain, Mapping):
            raise BrainError(
                "TOOLCHAIN_UNAVAILABLE",
                503,
                "lossless toolchain identity is unavailable",
            )
        source = bounded_source(source)
        _assert_endpoint_identity(request.instruction, endpoint)
        source_sha = _sha(source.encode("utf-8"))
        workspace_source = lease.snapshot.source_map().get(target["relative_path"])
        workspace_sha = (
            _sha(workspace_source.encode("utf-8")) if isinstance(workspace_source, str) else None
        )
        if workspace_sha != target.get("base_sha256"):
            raise BrainError("STALE_CONTEXT", 409, "structural edit workspace revision is stale")
        if request.basis is None:
            if source_sha != workspace_sha:
                raise BrainError("STALE_CONTEXT", 409, "structural edit source revision is stale")
        elif record.basis_source != source:
            raise BrainError("PROPOSAL_STALE", 409, "structural edit proposal basis differs")
        envelope = compiler.edit_surface(
            lease=lease,
            source=source,
            filename=target["relative_path"],
            endpoint=endpoint,
        )
        _surface, items, surface_sha = _validate_surface(
            envelope,
            source=source,
            relative_path=target["relative_path"],
            endpoint=endpoint,
        )
        replacements = _select_replacements(request.instruction, items, grounding)
        operations, roles, registry = _permit_operations(
            replacements=replacements,
            items=items,
            grounding=grounding,
        )
        permit_id = _host_ref("permit")
        nonce = _host_ref("nonce")
        target_ref = _host_ref("target")
        roles.update({permit_id: "permit", nonce: "nonce", target_ref: "target"})
        basis_ref: str | None = None
        basis_sha: str | None = None
        if isinstance(request.basis, Mapping):
            basis_ref = _host_ref("basis")
            basis_sha = canonical_sha256(dict(request.basis))
            roles[basis_ref] = "basis"
        binding = {
            "session_id": record.session_id,
            "turn_id": record.turn_id,
            "request_sha256": request.payload_hash,
            "instruction_sha256": _sha(request.instruction.encode("utf-8")),
            "tenant_snapshot_revision": lease.snapshot.revision,
            "source_sha256": source_sha,
            "target_ref": target_ref,
            "target_identity_sha256": canonical_sha256(dict(target)),
            "basis_ref": basis_ref,
            "basis_sha256": basis_sha,
            "edit_surface_sha256": surface_sha,
        }
        now_ms = int(time.time() * 1000)
        permit_spec = {
            "schema_version": 1,
            "contract_id": DELTA_PERMIT_CONTRACT,
            "permit_id": permit_id,
            "nonce": nonce,
            "issued_at_ms": now_ms,
            "expires_at_ms": now_ms + 60_000,
            "binding": binding,
            "operations": operations,
        }
        permit = issue_delta_permit(permit_spec, issued_ref_roles=roles)
        translator = DeltaPermitTranslator(permit, issued_ref_roles=roles)
        consumption = {
            "schema_version": 1,
            "contract_id": DELTA_CONSUMPTION_CONTRACT,
            "permit_id": permit_id,
            "nonce": nonce,
            "permit_sha256": permit.permit_sha256,
            "operations": operations,
        }
        authorized = translator.consume(consumption, current_binding=binding, now_ms=now_ms)
        admitted_replacements = _authorized_replacements(
            authorized=authorized,
            registry=registry,
        )
        expected, compiler_plan, owners = _build_compiler_plan(
            source=source,
            replacements=admitted_replacements,
        )
        response = compiler.lossless_apply(
            lease=lease,
            source=source,
            filename=target["relative_path"],
            endpoint=endpoint,
            plan=compiler_plan,
        )
        proof = _validate_apply_receipt(
            response,
            original=source,
            expected=expected,
            relative_path=target["relative_path"],
            endpoint=endpoint,
            plan=compiler_plan,
            owners=owners,
            delta_receipt_sha256=authorized.receipt.receipt_sha256,
            expected_toolchain=expected_toolchain,
        )
        return LosslessRenderResult(
            ModelCandidate(expected, "not_used", "not_used", "lossless_renderer"),
            proof,
        )
    except StructuralEditInapplicable:
        return None
    except DeltaPermitError as error:
        raise BrainError(error.code, 503, "private structural edit permit failed") from error


__all__ = [
    "EDIT_SURFACE_CONTRACT",
    "STRUCTURAL_LOSSLESS_PROOF_CONTRACT",
    "StructuralEditInapplicable",
    "render_structural_existing",
    "structural_edit_requested",
]
