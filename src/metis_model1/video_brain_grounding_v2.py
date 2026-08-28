"""Brain handoff and deterministic adjudication for semantic-index v2.

The language model is allowed to *propose* a clause-by-clause interpretation.
This module remains the authority for snapshot membership, reviewed semantic
references, ambiguity, unsupported metadata, and lazy value lookup.  The
payload-bearing context and grounding stay in the ignored private store; their
receipts contain hashes and counts only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantic_crosswalk import validate_crosswalk_receipt
from metis_model1.video_semantic_index_v2 import (
    constraint_ledger_revision,
    validate_semantic_index_v2,
)
from metis_model1.video_semantics_contracts import (
    validate_concepts,
    validate_constraints,
    validate_crosswalk,
)

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAPPED_RELATIONS = frozenset({"exact", "renamed", "synonym", "split", "merged"})
RESOLVED_REASONS = frozenset(
    {
        "EXACT_SNAPSHOT_MEMBER",
        "SEMANTIC_SNAPSHOT_MEMBER",
        "OPEN_LOOKUP_REQUIRED",
        "REVIEWED_AKA_GROUP",
    }
)
CLARIFY_REASONS = frozenset(
    {
        "AMBIGUOUS_SEMANTIC_ROLE",
        "LEGACY_LITERAL_NOT_EQUIVALENT",
        "MULTIPLE_CANDIDATES",
        "UNCLASSIFIED_DOMAIN_LOOKUP",
        "UNMAPPED_REQUEST_SURFACE",
    }
)
UNSUPPORTED_REASONS = frozenset({"UNSUPPORTED_METADATA"})
CONTEXT_SEMANTIC_KEYS = frozenset(
    {
        "label",
        "definition",
        "include_when",
        "exclude_when",
        "scope",
        "cardinality",
        "parents",
        "children",
        "dependencies",
        "exclusive_with",
        "examples",
        "review_state",
    }
)


class BrainGroundingV2Error(ValueError):
    """Raised when a v2 context or proposed grounding is not authoritative."""


# These are linguistic glue or operation words already represented by the
# structured Brain request (create/modify/select endpoint), not metadata
# constraints.  Every other substantive request token must be covered by a
# clause surface; unknown material must be classified explicitly as an
# UNMAPPED_REQUEST_SURFACE clarification.
REQUEST_STOPWORDS = frozenset(
    {
        "a",
        "ad",
        "al",
        "alla",
        "alle",
        "an",
        "and",
        "as",
        "at",
        "che",
        "con",
        "crea",
        "creare",
        "da",
        "dammi",
        "dei",
        "del",
        "della",
        "di",
        "e",
        "endpoint",
        "for",
        "from",
        "gli",
        "i",
        "il",
        "in",
        "la",
        "le",
        "lo",
        "modifica",
        "modificare",
        "of",
        "on",
        "or",
        "per",
        "plus",
        "su",
        "seleziona",
        "selezionare",
        "selezioni",
        "the",
        "to",
        "un",
        "una",
        "voglio",
        "vorrei",
        "with",
    }
)


def _normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


def _lexical_tokens(value: str, *, expand_pairs: bool = False) -> set[str]:
    raw = [item for item in _normalized_phrase(value).split() if item not in REQUEST_STOPWORDS]

    def stem(token: str) -> str:
        # This is intentionally a tiny language-independent normalization, not
        # a semantic oracle.  It only joins trivial Italian/English inflection
        # variants such as ``vinto``/``vinti``; the reviewed semantic ref still
        # supplies the authority.
        return token[:-1] if len(token) >= 5 and token[-1] in "aeiou" else token

    tokens = [stem(item) for item in raw]
    result = set(tokens)
    if expand_pairs:
        result.update(left + right for left, right in zip(tokens, tokens[1:], strict=False))
    return result


def _surface_span(request: str, surface: str, occupied: list[tuple[int, int]]) -> tuple[int, int]:
    folded_request = request.casefold()
    folded_surface = surface.casefold().strip()
    pattern = re.compile(r"(?<!\w)" + re.escape(folded_surface) + r"(?!\w)")
    for match in pattern.finditer(folded_request):
        span = match.span()
        if not any(span[0] < end and start < span[1] for start, end in occupied):
            return span
    raise BrainGroundingV2Error("proposal clause surfaces overlap or are not anchored")


def _missing_request_tokens(request: str, spans: Sequence[tuple[int, int]]) -> list[str]:
    folded_request = request.casefold()
    missing: list[str] = []
    for match in re.finditer(r"\w+", folded_request, flags=re.UNICODE):
        token = match.group(0)
        if token in REQUEST_STOPWORDS:
            continue
        start, end = match.span()
        if not any(left <= start and end <= right for left, right in spans):
            missing.append(token)
    return missing


def _entry_surfaces(entry: Mapping[str, Any]) -> set[str]:
    surfaces: set[str] = set()
    field = entry.get("field")
    literal = entry.get("literal")
    if isinstance(field, str):
        surfaces.add(field)
        surfaces.add(field.rsplit(".", 1)[-1])
    if isinstance(literal, str):
        surfaces.add(literal)
    if entry.get("state") == "reviewed":
        means = entry.get("means")
        if isinstance(means, Mapping) and isinstance(means.get("text"), str):
            surfaces.add(means["text"])
        aka = entry.get("aka")
        if isinstance(aka, Mapping) and isinstance(aka.get("items"), list):
            surfaces.update(item for item in aka["items"] if isinstance(item, str))
    return surfaces


def _semantic_surfaces(context: Mapping[str, Any], refs: Sequence[str]) -> set[str]:
    wanted = set(refs)
    surfaces: set[str] = set()
    for item in context.get("concepts", []):
        if not isinstance(item, Mapping) or item.get("semantic_ref") not in wanted:
            continue
        semantic = item.get("semantic")
        if not isinstance(semantic, Mapping):
            continue
        for key in ("label", "definition"):
            if isinstance(semantic.get(key), str):
                surfaces.add(semantic[key])
        for key in ("include_when", "exclude_when", "examples"):
            values = semantic.get(key)
            if isinstance(values, list):
                surfaces.update(value for value in values if isinstance(value, str))
    return surfaces


def _surface_supported(
    surface: str,
    entry: Mapping[str, Any],
    context: Mapping[str, Any],
    refs: Sequence[str],
    *,
    extra_surfaces: Sequence[str] = (),
    allow_partial: bool = False,
) -> bool:
    normalized = _normalized_phrase(surface)
    if not normalized:
        return False
    candidates = {
        _normalized_phrase(value)
        for value in (
            *_entry_surfaces(entry),
            *_semantic_surfaces(context, refs),
            *extra_surfaces,
        )
    }
    if normalized in candidates:
        return True
    surface_tokens = _lexical_tokens(normalized)
    if not surface_tokens:
        return False
    candidate_tokens: set[str] = set()
    for candidate in candidates:
        candidate_tokens.update(_lexical_tokens(candidate, expand_pairs=True))
    remaining = set(candidate_tokens)
    shared = 0
    for token in sorted(surface_tokens):
        match = next(
            (
                candidate
                for candidate in sorted(remaining)
                if candidate == token
                or (min(len(candidate), len(token)) >= 6 and candidate[:4] == token[:4])
            ),
            None,
        )
        if match is not None:
            shared += 1
            remaining.remove(match)
    # At least two thirds of the substantive surface must be grounded.  This
    # permits bounded inflection/paraphrase while preventing one valid phrase
    # from swallowing unrelated request clauses.
    if allow_partial:
        # Clarification is non-executable.  One lexical anchor is sufficient to
        # surface a reviewed ambiguity, but never to produce ``resolved``.
        return shared >= 1
    minimum = 1 if len(surface_tokens) == 1 else 2
    return shared >= minimum and shared * 3 >= len(surface_tokens) * 2


def _reviewed_aka_group(
    surface: str,
    targets: Sequence[Mapping[str, Any]],
    all_entries: Sequence[Mapping[str, Any]],
) -> bool:
    """Prove that targets are the complete same-field roster for one alias.

    Repeating one reviewed ``aka`` across physical values is the tenant-owned
    declaration that the natural surface expands to all of them.  The proof is
    exact and closed: one field only, value nodes only, every alias carrier
    reviewed, and no omitted member.
    """

    if len(targets) < 2:
        return False
    first = targets[0]
    if any(
        item.get("node_kind") != "value"
        or item.get("state") != "reviewed"
        or item.get("catalog") != first.get("catalog")
        or item.get("field") != first.get("field")
        for item in targets
    ):
        return False
    surface_key = surface.casefold().strip()

    def carries_alias(entry: Mapping[str, Any]) -> bool:
        aka = entry.get("aka")
        return isinstance(aka, Mapping) and any(
            isinstance(item, str) and item.casefold().strip() == surface_key
            for item in aka.get("items", [])
        )

    if not all(carries_alias(item) for item in targets):
        return False
    catalog_carriers = [
        item
        for item in all_entries
        if item.get("catalog") == first.get("catalog") and carries_alias(item)
    ]
    if any(
        item.get("node_kind") != "value" or item.get("field") != first.get("field")
        for item in catalog_carriers
    ):
        return False
    complete = catalog_carriers
    if len(complete) < 2 or any(item.get("state") != "reviewed" for item in complete):
        return False
    return {item["canonical_locator"] for item in targets} == {
        item["canonical_locator"] for item in complete
    }


def _hash(value: Any) -> str:
    try:
        return "sha256:" + canonical_json_hash(value)
    except (TypeError, ValueError) as error:
        raise BrainGroundingV2Error("value is not canonical JSON") from error


def _hash_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise BrainGroundingV2Error(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _text(
    value: Any,
    label: str,
    *,
    maximum: int = 16_384,
    allow_layout: bool = False,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise BrainGroundingV2Error(f"{label} must be a bounded non-empty string")
    allowed_layout = {"\t", "\n", "\r"} if allow_layout else set()
    if any(
        (ord(char) < 0x20 and char not in allowed_layout) or 0x7F <= ord(char) <= 0x9F
        for char in value
    ):
        raise BrainGroundingV2Error(f"{label} contains a control character")
    return value


def _hash_roster(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or HASH_RE.fullmatch(item) is None for item in value)
        or value != sorted(value)
        or len(value) != len(set(value))
    ):
        raise BrainGroundingV2Error(f"{label} must be a sorted distinct hash roster")
    return list(value)


def _locator_roster(value: Any, label: str) -> list[str]:
    return _hash_roster(value, label)


def _contract(label: str, errors: Sequence[str]) -> None:
    if errors:
        raise BrainGroundingV2Error(f"{label} is invalid: {'; '.join(errors)}")


def brain_context_v2_revision(context: Mapping[str, Any]) -> str:
    """Return the self-identity of a private Brain semantic context."""

    if not isinstance(context, Mapping):
        raise BrainGroundingV2Error("context must be an object")
    return _hash({key: value for key, value in context.items() if key != "revision"})


def _validated_sources(
    index: Mapping[str, Any],
    concepts: Sequence[Mapping[str, Any]],
    crosswalk_bundle: Mapping[str, Any],
    constraint_ledger: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], Mapping[str, Any], list[Mapping[str, Any]]]:
    _contract("semantic index v2", validate_semantic_index_v2(index))
    concept_items = list(concepts)
    _contract("concepts", validate_concepts(concept_items))
    if any(item.get("review_state") != "reviewed" for item in concept_items):
        raise BrainGroundingV2Error("all context concepts must be reviewed")
    ordered = sorted(concept_items, key=lambda item: item["concept_id"])
    if _hash({"schema_version": 1, "concepts": ordered}) != index["concepts_sha256"]:
        raise BrainGroundingV2Error("context concepts differ from the index source")

    if not isinstance(crosswalk_bundle, Mapping) or set(crosswalk_bundle) != {
        "crosswalk",
        "receipt",
    }:
        raise BrainGroundingV2Error("crosswalk must be the closed document-and-receipt bundle")
    crosswalk = crosswalk_bundle["crosswalk"]
    receipt = crosswalk_bundle["receipt"]
    _contract(
        "crosswalk",
        validate_crosswalk(
            crosswalk,
            concept_ids={item["concept_id"] for item in concept_items},
            semantic_source_revision_ref=index["semantic_source_revision"],
        ),
    )
    _contract("crosswalk receipt", validate_crosswalk_receipt(receipt))
    if (
        _hash(crosswalk) != index["crosswalk_sha256"]
        or receipt.get("crosswalk_sha256") != index["crosswalk_sha256"]
        or receipt.get("semantic_source_revision") != index["semantic_source_revision"]
    ):
        raise BrainGroundingV2Error("context crosswalk differs from the index source")

    _contract("constraint ledger", validate_constraints(constraint_ledger))
    if (
        constraint_ledger_revision(constraint_ledger) != index["constraint_revision"]
        or constraint_ledger.get("constraint_revision") != index["constraint_revision"]
        or any(item.get("review_state") != "reviewed" for item in constraint_ledger["constraints"])
    ):
        raise BrainGroundingV2Error("context constraints differ from the reviewed index source")
    return ordered, crosswalk, list(constraint_ledger["constraints"])


def build_brain_semantic_context_v2(
    index: Mapping[str, Any],
    concepts: Sequence[Mapping[str, Any]],
    crosswalk: Mapping[str, Any],
    constraint_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the private reviewed registry Model 1 receives beside index v2."""

    concept_items, crosswalk_document, constraints = _validated_sources(
        index, concepts, crosswalk, constraint_ledger
    )
    entries_by_locator = {item["canonical_locator"]: item for item in index["entries"]}
    rows = crosswalk_document["rows"]
    rows_by_ref = {item["concept_id"]: item for item in rows}
    if len(rows_by_ref) != len(rows) or set(rows_by_ref) != set(index["semantic_ref_roster"]):
        raise BrainGroundingV2Error("crosswalk concept coverage differs from the index")

    context_concepts: list[dict[str, Any]] = []
    for concept in concept_items:
        semantic_ref = concept["concept_id"]
        row = rows_by_ref[semantic_ref]
        if row["relation"] == "absent":
            if semantic_ref not in index["terminal_absent_semantic_refs"]:
                raise BrainGroundingV2Error("absent concept is not terminal in the index")
            target = {"status": "absent", "relation": "absent"}
        else:
            locator = row["canonical_locator"]
            entry = entries_by_locator.get(locator)
            if (
                row["relation"] not in MAPPED_RELATIONS
                or entry is None
                or semantic_ref not in entry["semantic_refs"]
                or entry["state"] != "reviewed"
            ):
                raise BrainGroundingV2Error("mapped concept is not reviewed index membership")
            target = {
                "status": "mapped",
                "relation": row["relation"],
                "canonical_locator": locator,
            }
        semantic = {
            "label": concept["source_label"],
            "definition": concept["definition"],
            "include_when": list(concept["include_when"]),
            "exclude_when": list(concept["exclude_when"]),
            "scope": list(concept["scope"]),
            "cardinality": dict(concept["cardinality"]),
            "parents": list(concept["parents"]),
            "children": list(concept["children"]),
            "dependencies": list(concept["dependencies"]),
            "exclusive_with": list(concept["exclusive_with"]),
            "examples": list(concept["examples"]),
            "review_state": "reviewed",
        }
        context_concepts.append(
            {"semantic_ref": semantic_ref, "semantic": semantic, "target": target}
        )

    context_constraints = [
        {
            "constraint_ref": item["constraint_id"],
            "rule": item["rule"],
            "fields": list(item["fields"]),
            "grammar_expressed": item["grammar_expressed"],
            "validator_verifiable": item["validator_verifiable"],
            "editorial_oracle": item["editorial_oracle"],
            "brain_behavior": item["brain_behavior"],
        }
        for item in sorted(constraints, key=lambda item: item["constraint_id"])
    ]
    body: dict[str, Any] = {
        "schema_version": 1,
        "context_id": "video-semantics/brain-context-v2",
        "index_revision": index["revision"],
        "semantic_source_revision": index["semantic_source_revision"],
        "concepts_sha256": index["concepts_sha256"],
        "crosswalk_sha256": index["crosswalk_sha256"],
        "constraint_revision": index["constraint_revision"],
        "concepts": context_concepts,
        "constraints": context_constraints,
    }
    context = {**body, "revision": brain_context_v2_revision(body)}
    _contract(
        "generated Brain semantic context v2", validate_brain_semantic_context_v2(index, context)
    )
    counts = {
        "concepts": len(context_concepts),
        "mapped": sum(item["target"]["status"] == "mapped" for item in context_concepts),
        "absent": sum(item["target"]["status"] == "absent" for item in context_concepts),
        "constraints": len(context_constraints),
        "gaps": 0,
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "video-semantics/brain-context-v2-receipt-v1",
        "context_sha256": _hash(context),
        "context_revision": context["revision"],
        "index_revision": index["revision"],
        "concepts_sha256": index["concepts_sha256"],
        "crosswalk_sha256": index["crosswalk_sha256"],
        "constraint_revision": index["constraint_revision"],
        "counts": counts,
        "payload_redacted": True,
        "reasoning_present": False,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    _contract(
        "generated Brain context receipt",
        validate_brain_context_v2_receipt(receipt, context=context),
    )
    manifest = build_brain_context_v2_manifest(context, receipt)
    return {"context": context, "receipt": receipt, "manifest": manifest}


def validate_brain_semantic_context_v2(index: Any, context: Any) -> list[str]:
    """Validate the private context against one exact index snapshot."""

    index_errors = validate_semantic_index_v2(index)
    if index_errors:
        return [f"semantic index v2: {error}" for error in index_errors]
    if not isinstance(context, Mapping):
        return ["context must be an object"]
    errors: list[str] = []
    required = {
        "schema_version",
        "context_id",
        "index_revision",
        "semantic_source_revision",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
        "concepts",
        "constraints",
        "revision",
    }
    if set(context) != required:
        errors.append("context fields are not the closed v2 contract")
    if (
        context.get("schema_version") != 1
        or context.get("context_id") != "video-semantics/brain-context-v2"
    ):
        errors.append("context identity is invalid")
    for key in (
        "index_revision",
        "semantic_source_revision",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
        "revision",
    ):
        try:
            _hash_ref(context.get(key), f"context.{key}")
        except BrainGroundingV2Error as error:
            errors.append(str(error))
    for key in (
        "index_revision",
        "semantic_source_revision",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
    ):
        index_key = "revision" if key == "index_revision" else key
        if context.get(key) != index.get(index_key):
            errors.append(f"context {key} differs from the index")

    entries_by_locator = {
        item["canonical_locator"]: item
        for item in index["entries"]
        if isinstance(item, Mapping) and isinstance(item.get("canonical_locator"), str)
    }
    concept_items = context.get("concepts")
    seen_refs: list[str] = []
    mapped_refs: list[str] = []
    absent_refs: list[str] = []
    if not isinstance(concept_items, list) or not concept_items:
        errors.append("context concepts are missing")
    else:
        for item in concept_items:
            if not isinstance(item, Mapping) or set(item) != {
                "semantic_ref",
                "semantic",
                "target",
            }:
                errors.append("context concept shape is invalid")
                continue
            semantic_ref = item.get("semantic_ref")
            if not isinstance(semantic_ref, str) or HASH_RE.fullmatch(semantic_ref) is None:
                errors.append("context concept semantic ref is invalid")
                continue
            seen_refs.append(semantic_ref)
            semantic = item.get("semantic")
            if (
                not isinstance(semantic, Mapping)
                or set(semantic) != CONTEXT_SEMANTIC_KEYS
                or semantic.get("review_state") != "reviewed"
            ):
                errors.append("context concept semantic payload is invalid")
            target = item.get("target")
            if not isinstance(target, Mapping) or target.get("status") not in {
                "mapped",
                "absent",
            }:
                errors.append("context concept target is invalid")
                continue
            if target["status"] == "absent":
                if set(target) != {"status", "relation"} or target.get("relation") != "absent":
                    errors.append("context absent target is invalid")
                absent_refs.append(semantic_ref)
            else:
                if (
                    set(target) != {"status", "relation", "canonical_locator"}
                    or target.get("relation") not in MAPPED_RELATIONS
                ):
                    errors.append("context mapped target is invalid")
                    continue
                entry = entries_by_locator.get(target.get("canonical_locator"))
                if entry is None or semantic_ref not in entry["semantic_refs"]:
                    errors.append("context mapped target is not index membership")
                mapped_refs.append(semantic_ref)
        if seen_refs != sorted(seen_refs) or len(seen_refs) != len(set(seen_refs)):
            errors.append("context concept roster is not sorted and distinct")
        if set(seen_refs) != set(index["semantic_ref_roster"]):
            errors.append("context concept roster differs from the index")
        if set(absent_refs) != set(index["terminal_absent_semantic_refs"]):
            errors.append("context terminal absence roster differs from the index")
        if set(mapped_refs) | set(absent_refs) != set(seen_refs):
            errors.append("context concept targets are not closed")

    constraints = context.get("constraints")
    constraint_refs: list[str] = []
    if not isinstance(constraints, list):
        errors.append("context constraints are invalid")
    else:
        required_constraint = {
            "constraint_ref",
            "rule",
            "fields",
            "grammar_expressed",
            "validator_verifiable",
            "editorial_oracle",
            "brain_behavior",
        }
        for item in constraints:
            if not isinstance(item, Mapping) or set(item) != required_constraint:
                errors.append("context constraint shape is invalid")
                continue
            ref = item.get("constraint_ref")
            if not isinstance(ref, str) or HASH_RE.fullmatch(ref) is None:
                errors.append("context constraint ref is invalid")
                continue
            constraint_refs.append(ref)
        if constraint_refs != sorted(constraint_refs) or len(constraint_refs) != len(
            set(constraint_refs)
        ):
            errors.append("context constraint roster is not sorted and distinct")
        if set(constraint_refs) != set(index["constraint_ref_roster"]):
            errors.append("context constraint roster differs from the index")
    try:
        if context.get("revision") != brain_context_v2_revision(context):
            errors.append("context revision is stale or tampered")
    except BrainGroundingV2Error as error:
        errors.append(str(error))
    return errors


def validate_brain_context_v2_receipt(
    receipt: Any, *, context: Mapping[str, Any] | None = None
) -> list[str]:
    """Validate the payload-free receipt for one private Brain context."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    required = {
        "schema_version",
        "receipt_id",
        "context_sha256",
        "context_revision",
        "index_revision",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
        "counts",
        "payload_redacted",
        "reasoning_present",
        "receipt_sha256",
    }
    if set(receipt) != required:
        errors.append("receipt fields are not the closed context contract")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("receipt_id") != "video-semantics/brain-context-v2-receipt-v1"
    ):
        errors.append("receipt identity is invalid")
    for key in (
        "context_sha256",
        "context_revision",
        "index_revision",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
        "receipt_sha256",
    ):
        value = receipt.get(key)
        if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
            errors.append(f"receipt {key} is invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "concepts",
        "mapped",
        "absent",
        "constraints",
        "gaps",
    }:
        errors.append("receipt counts are invalid")
    elif (
        any(type(value) is not int or value < 0 for value in counts.values())
        or counts["concepts"] != counts["mapped"] + counts["absent"]
        or counts["gaps"] != 0
    ):
        errors.append("receipt counts are not closed")
    if receipt.get("payload_redacted") is not True or receipt.get("reasoning_present") is not False:
        errors.append("receipt redaction markers are invalid")
    if context is not None:
        try:
            if receipt.get("context_sha256") != _hash(context):
                errors.append("receipt context payload hash differs from context")
        except BrainGroundingV2Error as error:
            errors.append(str(error))
    expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash(expected):
        errors.append("receipt self-hash is invalid")
    return errors


def build_brain_context_v2_manifest(
    context: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Create the detached CAS marker stored beside a private context bundle.

    The manifest is intentionally separate from both payload files.  A loader
    must retain this marker immutably (for example via the private store's
    no-replace bundle manifest) and pass it to
    :func:`validate_brain_context_v2_manifest`; recomputing a context revision
    alone is not an integrity proof.
    """

    if not isinstance(context, Mapping) or not isinstance(receipt, Mapping):
        raise BrainGroundingV2Error("context and receipt are required for the CAS manifest")
    _hash_ref(context.get("revision"), "context.revision")
    _hash_ref(receipt.get("receipt_sha256"), "receipt.receipt_sha256")
    body = {
        "schema_version": 1,
        "manifest_id": "video-semantics/brain-context-v2-manifest-v1",
        "context_sha256": _hash(context),
        "context_revision": context["revision"],
        "receipt_sha256": receipt["receipt_sha256"],
        "index_revision": context.get("index_revision"),
    }
    manifest = {**body, "manifest_sha256": _hash(body)}
    _contract(
        "generated Brain context manifest",
        validate_brain_context_v2_manifest(None, context, receipt, manifest, check_index=False),
    )
    return manifest


def validate_brain_context_v2_manifest(
    index: Mapping[str, Any] | None,
    context: Mapping[str, Any],
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    check_index: bool = True,
    expected_manifest_sha256: str | None = None,
) -> list[str]:
    """Validate the detached immutable CAS marker for a context bundle."""

    errors: list[str] = []
    if check_index and index is not None:
        errors.extend(validate_brain_semantic_context_v2(index, context))
    errors.extend(validate_brain_context_v2_receipt(receipt, context=context))
    required = {
        "schema_version",
        "manifest_id",
        "context_sha256",
        "context_revision",
        "receipt_sha256",
        "index_revision",
        "manifest_sha256",
    }
    if not isinstance(manifest, Mapping) or set(manifest) != required:
        return [*errors, "context manifest fields are not the closed CAS contract"]
    if manifest.get("schema_version") != 1 or manifest.get("manifest_id") != (
        "video-semantics/brain-context-v2-manifest-v1"
    ):
        errors.append("context manifest identity is invalid")
    for key in (
        "context_sha256",
        "context_revision",
        "receipt_sha256",
        "index_revision",
        "manifest_sha256",
    ):
        try:
            _hash_ref(manifest.get(key), f"manifest.{key}")
        except BrainGroundingV2Error as error:
            errors.append(str(error))
    if manifest.get("context_sha256") != _hash(context):
        errors.append("context manifest payload hash differs from context")
    if manifest.get("context_revision") != context.get("revision"):
        errors.append("context manifest revision differs from context")
    if manifest.get("receipt_sha256") != receipt.get("receipt_sha256"):
        errors.append("context manifest receipt binding differs from receipt")
    if manifest.get("index_revision") != context.get("index_revision"):
        errors.append("context manifest index binding differs from context")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != _hash(body):
        errors.append("context manifest self-hash is invalid")
    if expected_manifest_sha256 is not None:
        try:
            _hash_ref(expected_manifest_sha256, "expected context manifest sha256")
        except BrainGroundingV2Error as error:
            errors.append(str(error))
        if manifest.get("manifest_sha256") != expected_manifest_sha256:
            errors.append("context manifest differs from trusted CAS authority")
    return errors


def _entry_view(
    entry: Mapping[str, Any], entries_by_field: Mapping[tuple[str, str], Mapping[str, Any]]
) -> dict[str, Any]:
    parent = (
        entry
        if entry["node_kind"] == "field"
        else entries_by_field.get((entry["catalog"], entry["field"]))
    )
    result = {
        "canonical_locator": entry["canonical_locator"],
        "catalog": entry["catalog"],
        "field": entry["field"],
        "literal": entry["literal"],
        "node_kind": entry["node_kind"],
        "domain": entry["domain"],
        "semantic_refs": entry["semantic_refs"],
        "constraint_refs": entry["constraint_refs"],
    }
    if isinstance(parent, Mapping):
        result["type"] = parent.get("type")
        result["modifiers"] = parent.get("modifiers")
    return result


def adjudicate_grounding_proposal_v2(
    index: Mapping[str, Any],
    context: Mapping[str, Any],
    request: str,
    proposal: Mapping[str, Any],
    *,
    context_receipt: Mapping[str, Any],
    context_manifest: Mapping[str, Any],
    expected_context_manifest_sha256: str,
    catalog: str | None = None,
) -> dict[str, Any]:
    """Validate a model proposal and return an executable-or-blocked clause map."""

    _contract("semantic index v2", validate_semantic_index_v2(index))
    _contract(
        "Brain semantic context v2 authority",
        validate_brain_context_v2_manifest(
            index,
            context,
            context_receipt,
            context_manifest,
            expected_manifest_sha256=expected_context_manifest_sha256,
        ),
    )
    request = _text(request, "request", allow_layout=True)
    request_sha256 = _hash(request)
    required_proposal = {
        "schema_version",
        "proposal_id",
        "index_revision",
        "context_revision",
        "request_sha256",
        "clauses",
    }
    if not isinstance(proposal, Mapping) or set(proposal) != required_proposal:
        raise BrainGroundingV2Error("proposal must be the closed v2 contract")
    if proposal.get("schema_version") != 1:
        raise BrainGroundingV2Error("proposal schema version is invalid")
    proposal_id = proposal.get("proposal_id")
    if not isinstance(proposal_id, str) or OPAQUE_RE.fullmatch(proposal_id) is None:
        raise BrainGroundingV2Error("proposal id is invalid")
    if (
        proposal.get("index_revision") != index["revision"]
        or proposal.get("context_revision") != context["revision"]
        or proposal.get("request_sha256") != request_sha256
    ):
        raise BrainGroundingV2Error("proposal is stale or bound to a different request")
    clauses = proposal.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        raise BrainGroundingV2Error("proposal clauses are missing")

    catalogs = sorted({item["catalog"] for item in index["entries"]})
    if catalog is None:
        if len(catalogs) != 1:
            raise BrainGroundingV2Error("multiple catalogs require explicit confirmation")
        allowed_catalog = catalogs[0]
    elif catalog not in catalogs:
        raise BrainGroundingV2Error("requested catalog is not in the membership snapshot")
    else:
        allowed_catalog = catalog

    entries_by_locator = {item["canonical_locator"]: item for item in index["entries"]}
    entries_by_field = {
        (item["catalog"], item["field"]): item
        for item in index["entries"]
        if item["node_kind"] == "field"
    }
    semantic_roster = set(index["semantic_ref_roster"])
    terminal_absent = set(index["terminal_absent_semantic_refs"])
    required_clause = {
        "clause_id",
        "surface",
        "resolution",
        "semantic_refs",
        "target_locators",
        "candidate_locators",
        "requested_value",
        "reason_code",
    }
    normalized: list[dict[str, Any]] = []
    clause_ids: list[str] = []
    occupied_spans: list[tuple[int, int]] = []
    for position, raw in enumerate(clauses):
        if not isinstance(raw, Mapping) or set(raw) != required_clause:
            raise BrainGroundingV2Error(f"clause[{position}] is not the closed contract")
        clause_id = raw.get("clause_id")
        if not isinstance(clause_id, str) or OPAQUE_RE.fullmatch(clause_id) is None:
            raise BrainGroundingV2Error(f"clause[{position}] id is invalid")
        clause_ids.append(clause_id)
        surface = _text(raw.get("surface"), f"clause[{position}].surface", maximum=1024)
        occupied_spans.append(_surface_span(request, surface, occupied_spans))
        resolution = raw.get("resolution")
        if not isinstance(resolution, str) or resolution not in {
            "resolved",
            "clarify",
            "unsupported",
        }:
            raise BrainGroundingV2Error(f"clause[{position}] resolution is invalid")
        refs = _hash_roster(raw.get("semantic_refs"), f"clause[{position}].semantic_refs")
        if not set(refs) <= semantic_roster:
            raise BrainGroundingV2Error(f"clause[{position}] has a dangling semantic ref")
        targets = _locator_roster(raw.get("target_locators"), f"clause[{position}].targets")
        candidates = _locator_roster(
            raw.get("candidate_locators"), f"clause[{position}].candidates"
        )
        if set(targets) & set(candidates):
            raise BrainGroundingV2Error(f"clause[{position}] target is also only a candidate")
        try:
            target_entries = [entries_by_locator[item] for item in targets]
            candidate_entries = [entries_by_locator[item] for item in candidates]
        except KeyError as error:
            raise BrainGroundingV2Error(
                f"clause[{position}] refers outside snapshot membership"
            ) from error
        if any(item["catalog"] != allowed_catalog for item in target_entries + candidate_entries):
            raise BrainGroundingV2Error(f"clause[{position}] crosses the selected catalog")
        requested_value = raw.get("requested_value")
        if requested_value is not None:
            requested_value = _text(
                requested_value, f"clause[{position}].requested_value", maximum=1024
            )
        reason_code = raw.get("reason_code")
        if not isinstance(reason_code, str):
            raise BrainGroundingV2Error(f"clause[{position}] reason code is invalid")
        lookup = None

        if resolution == "resolved":
            is_alias_group = reason_code == "REVIEWED_AKA_GROUP"
            if reason_code not in RESOLVED_REASONS or candidates:
                raise BrainGroundingV2Error(f"clause[{position}] resolved shape is invalid")
            if is_alias_group:
                if (
                    refs
                    or requested_value is not None
                    or not _reviewed_aka_group(surface, target_entries, index["entries"])
                ):
                    raise BrainGroundingV2Error(
                        f"clause[{position}] reviewed alias group is incomplete or invalid"
                    )
                normalized_targets = [
                    _entry_view(item, entries_by_field) for item in target_entries
                ]
                normalized_candidates = []
                normalized.append(
                    {
                        "clause_id": clause_id,
                        "surface": surface,
                        "resolution": resolution,
                        "reason_code": reason_code,
                        "semantic_refs": refs,
                        "selected": normalized_targets,
                        "candidates": normalized_candidates,
                        "requested_value": None,
                        "lookup": None,
                    }
                )
                continue
            if len(target_entries) != 1:
                raise BrainGroundingV2Error(f"clause[{position}] resolved shape is invalid")
            selected = target_entries[0]
            if selected["state"] != "reviewed" or selected["node_kind"] == "catalog":
                raise BrainGroundingV2Error(f"clause[{position}] target is not reviewed metadata")
            if refs and not set(refs) <= set(selected["semantic_refs"]):
                raise BrainGroundingV2Error(
                    f"clause[{position}] semantic refs do not support the target"
                )
            if reason_code == "SEMANTIC_SNAPSHOT_MEMBER" and not refs:
                raise BrainGroundingV2Error(
                    f"clause[{position}] semantic resolution requires a semantic ref"
                )
            if not _surface_supported(
                surface,
                selected,
                context,
                refs,
                extra_surfaces=(() if requested_value is None else (requested_value,)),
            ):
                raise BrainGroundingV2Error(
                    f"clause[{position}] surface is not supported by its selected target"
                )
            if selected["node_kind"] == "value":
                if requested_value not in {None, selected["literal"]}:
                    raise BrainGroundingV2Error(f"clause[{position}] value differs from membership")
                requested_value = None
            elif requested_value is not None:
                if selected["domain"]["kind"] != "open" or reason_code != "OPEN_LOOKUP_REQUIRED":
                    raise BrainGroundingV2Error(
                        f"clause[{position}] cannot resolve a non-member value"
                    )
                lookup = {
                    "mode": "exact_on_demand",
                    "owner": "retrieval_engine",
                    "catalog": selected["catalog"],
                    "field": selected["field"],
                    "requested_value": requested_value,
                    "values": None,
                }
            normalized_targets = [_entry_view(selected, entries_by_field)]
            normalized_candidates: list[dict[str, Any]] = []
        elif resolution == "unsupported":
            if (
                reason_code not in UNSUPPORTED_REASONS
                or target_entries
                or candidate_entries
                or requested_value is not None
                or not refs
                or not set(refs) <= terminal_absent
            ):
                raise BrainGroundingV2Error(f"clause[{position}] unsupported shape is invalid")
            if not _surface_supported(surface, {}, context, refs):
                raise BrainGroundingV2Error(
                    f"clause[{position}] unsupported surface is not supported by its semantic ref"
                )
            normalized_targets = []
            normalized_candidates = []
        else:
            if reason_code not in CLARIFY_REASONS or target_entries:
                raise BrainGroundingV2Error(f"clause[{position}] clarification shape is invalid")
            if reason_code == "UNMAPPED_REQUEST_SURFACE":
                if refs or candidates or requested_value is not None:
                    raise BrainGroundingV2Error(
                        f"clause[{position}] unmapped clarification must have no target"
                    )
            elif not (refs or candidates):
                raise BrainGroundingV2Error(f"clause[{position}] clarification has no evidence")
            if any(item["state"] != "reviewed" for item in candidate_entries):
                raise BrainGroundingV2Error(
                    f"clause[{position}] candidate is not reviewed metadata"
                )
            if reason_code == "AMBIGUOUS_SEMANTIC_ROLE" and len(refs) < 2:
                raise BrainGroundingV2Error(
                    f"clause[{position}] semantic ambiguity is not demonstrated"
                )
            if reason_code == "LEGACY_LITERAL_NOT_EQUIVALENT" and (
                not candidate_entries or not refs or not set(refs) & terminal_absent
            ):
                raise BrainGroundingV2Error(
                    f"clause[{position}] legacy mismatch is not demonstrated"
                )
            if reason_code == "MULTIPLE_CANDIDATES" and len(candidate_entries) < 2:
                raise BrainGroundingV2Error(
                    f"clause[{position}] candidate ambiguity is not demonstrated"
                )
            if reason_code == "UNCLASSIFIED_DOMAIN_LOOKUP" and (
                len(candidate_entries) != 1
                or candidate_entries[0]["node_kind"] != "field"
                or candidate_entries[0]["domain"]["kind"] != "none"
                or requested_value is None
            ):
                raise BrainGroundingV2Error(
                    f"clause[{position}] unclassified lookup is not demonstrated"
                )
            if reason_code != "UNMAPPED_REQUEST_SURFACE" and not any(
                _surface_supported(
                    surface,
                    item,
                    context,
                    refs,
                    extra_surfaces=(() if requested_value is None else (requested_value,)),
                    allow_partial=True,
                )
                for item in candidate_entries
            ):
                raise BrainGroundingV2Error(
                    f"clause[{position}] clarification surface is not supported by its evidence"
                )
            normalized_targets = []
            normalized_candidates = [
                _entry_view(item, entries_by_field) for item in candidate_entries
            ]

        normalized.append(
            {
                "clause_id": clause_id,
                "surface": surface,
                "resolution": resolution,
                "reason_code": reason_code,
                "semantic_refs": refs,
                "selected": normalized_targets,
                "candidates": normalized_candidates,
                "requested_value": requested_value,
                "lookup": lookup,
            }
        )
    if len(clause_ids) != len(set(clause_ids)):
        raise BrainGroundingV2Error("proposal clause identifiers are not distinct")
    missing = _missing_request_tokens(request, occupied_spans)
    if missing:
        raise BrainGroundingV2Error("proposal omits request clause(s)")

    statuses = [item["resolution"] for item in normalized]
    if all(status == "resolved" for status in statuses):
        status = "resolved"
        reason = "all clauses are reviewed snapshot membership"
    elif all(status == "unsupported" for status in statuses):
        status = "unsupported"
        reason = "all clauses are reviewed terminal absences"
    else:
        status = "clarify"
        reason = "one or more clauses require clarification or omission"
    grounding = {
        "schema_version": 2,
        "grounding_id": "video-semantics/brain-grounding-v2",
        "proposal_id": proposal_id,
        "index_revision": index["revision"],
        "context_revision": context["revision"],
        "context_manifest_sha256": expected_context_manifest_sha256,
        "request_sha256": request_sha256,
        "catalog": allowed_catalog,
        "status": status,
        "reason": reason,
        "clauses": normalized,
    }
    counts = {
        "clauses": len(normalized),
        "resolved": statuses.count("resolved"),
        "clarify": statuses.count("clarify"),
        "unsupported": statuses.count("unsupported"),
        "targets": sum(len(item["selected"]) for item in normalized),
        "candidates": sum(len(item["candidates"]) for item in normalized),
        "lookups": sum(item["lookup"] is not None for item in normalized),
        "gaps": 0,
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "video-semantics/brain-grounding-v2-receipt-v1",
        "grounding_sha256": _hash(grounding),
        "proposal_sha256": _hash(proposal),
        "index_revision": index["revision"],
        "context_revision": context["revision"],
        "context_manifest_sha256": expected_context_manifest_sha256,
        "request_sha256": request_sha256,
        "status": status,
        "counts": counts,
        "payload_redacted": True,
        "reasoning_present": False,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    _contract("generated grounding v2 receipt", validate_grounding_v2_receipt(receipt))
    return {"grounding": grounding, "receipt": receipt}


def validate_grounding_v2_receipt(receipt: Any) -> list[str]:
    """Validate the hash/count-only receipt for a clause grounding."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    required = {
        "schema_version",
        "receipt_id",
        "grounding_sha256",
        "proposal_sha256",
        "index_revision",
        "context_revision",
        "context_manifest_sha256",
        "request_sha256",
        "status",
        "counts",
        "payload_redacted",
        "reasoning_present",
        "receipt_sha256",
    }
    if set(receipt) != required:
        errors.append("receipt fields are not the closed grounding v2 contract")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("receipt_id") != "video-semantics/brain-grounding-v2-receipt-v1"
    ):
        errors.append("receipt identity is invalid")
    for key in (
        "grounding_sha256",
        "proposal_sha256",
        "index_revision",
        "context_revision",
        "context_manifest_sha256",
        "request_sha256",
        "receipt_sha256",
    ):
        value = receipt.get(key)
        if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
            errors.append(f"receipt {key} is invalid")
    if receipt.get("status") not in {"resolved", "clarify", "unsupported"}:
        errors.append("receipt status is invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "clauses",
        "resolved",
        "clarify",
        "unsupported",
        "targets",
        "candidates",
        "lookups",
        "gaps",
    }:
        errors.append("receipt counts are invalid")
    elif (
        any(type(value) is not int or value < 0 for value in counts.values())
        or counts["clauses"] != counts["resolved"] + counts["clarify"] + counts["unsupported"]
        or counts["gaps"] != 0
    ):
        errors.append("receipt counts are not closed")
    if receipt.get("payload_redacted") is not True or receipt.get("reasoning_present") is not False:
        errors.append("receipt redaction markers are invalid")
    expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash(expected):
        errors.append("receipt self-hash is invalid")
    return errors


__all__ = [
    "BrainGroundingV2Error",
    "adjudicate_grounding_proposal_v2",
    "brain_context_v2_revision",
    "build_brain_semantic_context_v2",
    "build_brain_context_v2_manifest",
    "validate_brain_context_v2_receipt",
    "validate_brain_context_v2_manifest",
    "validate_brain_semantic_context_v2",
    "validate_grounding_v2_receipt",
]
