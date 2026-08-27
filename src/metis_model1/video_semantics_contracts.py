"""Strict offline contracts for the video semantic-grounding wave.

This module owns only synthetic, file-backed validation.  It deliberately has
no network, model, tenant, credential, or reserved-source access. Source manifests carry
stable identity; acquisition receipts carry operational telemetry and are
never used to compute ``semantic_source_revision``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from metis_model1.evaluation import wilson_interval
from metis_model1.provenance import canonical_json_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = PROJECT_ROOT / "schemas"
FIXTURE_ROOT = PROJECT_ROOT / "fixtures/video-catalog-semantics-v1"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RELATIVE_PATH_RE = re.compile(r"^(?!/)(?!.*\\)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._@+/-]+$")

SCHEMA_FILES = (
    "video-semantics-source-manifest.schema.json",
    "video-semantics-acquisition-receipt.schema.json",
    "video-editorial-concept.schema.json",
    "video-semantic-work-item.schema.json",
    "video-semantic-crosswalk.schema.json",
    "video-editorial-constraint.schema.json",
    "video-catalog-census-profile.schema.json",
    "video-catalog-census-receipt.schema.json",
    "video-grounding-task.schema.json",
    "video-grounding-scorecard.schema.json",
)

FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "authorization",
        "bearer",
        "secret",
        "api_key",
        "apikey",
        "_source",
        "chain_of_thought",
        "model_output",
        "raw_output",
        "values_raw",
    }
)
FORBIDDEN_VALUE_RE = re.compile(
    r"(?is)(?:-----begin[^\n]*private key-----|\b(?:authorization|"
    r"bearer(?:\s+token)?|password|secret|"
    r"api[_-]?key|private[_-]?key)\s*[:=]|\b(?:_source|raw[_-]?(?:document|source)|"
    r"document[_-]?payload|source[_-]?payload)\b|^(?:/Users/|/home/|/private/var/|/tmp/|"
    r"[A-Za-z]:[\\/]))"
)


class VideoSemanticsContractError(ValueError):
    """Raised when a synthetic semantic contract fails closed."""


def _reject_constant(_value: str) -> None:
    raise VideoSemanticsContractError("JSON contains a non-finite number")


def load_json(path: Path) -> Any:
    """Load one UTF-8 JSON document while rejecting duplicate keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise VideoSemanticsContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=_reject_constant,
        )
    except VideoSemanticsContractError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VideoSemanticsContractError(f"cannot load JSON {path}") from error


def load_schema(name: str) -> dict[str, Any]:
    if name not in SCHEMA_FILES:
        raise VideoSemanticsContractError(f"schema is not allowlisted: {name}")
    value = load_json(SCHEMA_ROOT / name)
    if not isinstance(value, dict):
        raise VideoSemanticsContractError(f"schema is not an object: {name}")
    Draft202012Validator.check_schema(value)
    return value


def schema_errors(name: str, value: Any) -> list[str]:
    """Return deterministic Draft 2020-12 errors for one allowlisted schema."""

    try:
        schema = load_schema(name)
        return [
            error.message
            for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                value
            )
        ]
    except Exception as error:  # contract boundary must fail closed
        return [f"{type(error).__name__}: {error}"]


def _walk(value: Any) -> Sequence[tuple[str, Any]]:
    if isinstance(value, Mapping):
        return tuple((key, item) for key, item in value.items()) + tuple(
            pair for item in value.values() for pair in _walk(item)
        )
    if isinstance(value, list):
        return tuple(pair for item in value for pair in _walk(item))
    return ()


def _strings(value: Any) -> Sequence[str]:
    if isinstance(value, Mapping):
        return tuple(item for child in value.values() for item in _strings(child))
    if isinstance(value, list):
        return tuple(item for child in value for item in _strings(child))
    return (value,) if isinstance(value, str) else ()


def _assert_sanitized(value: Any) -> list[str]:
    errors: list[str] = []
    for key, item in _walk(value):
        if key.lower() in FORBIDDEN_KEYS:
            errors.append(f"forbidden sensitive/raw key: {key}")
        if isinstance(item, str) and FORBIDDEN_VALUE_RE.search(item):
            errors.append(f"forbidden sensitive/raw value under key: {key}")
    if any(FORBIDDEN_VALUE_RE.search(item) for item in _strings(value)):
        errors.append("forbidden sensitive/raw value in nested data")
    return errors


def _assert_opaque(value: Any, label: str) -> list[str]:
    if not isinstance(value, str) or OPAQUE_RE.fullmatch(value) is None:
        return [f"{label} is not an opaque identifier"]
    return []


def _assert_hash(value: Any, label: str) -> list[str]:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        return [f"{label} is not a sha256 hash"]
    return []


def canonical_source_material(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return only stable source identity fields used by the semantic revision."""

    return {
        "schema_version": manifest["schema_version"],
        "manifest_id": manifest["manifest_id"],
        "sources": manifest["sources"],
    }


def semantic_source_revision(manifest: Mapping[str, Any]) -> str:
    return "sha256:" + canonical_json_hash(canonical_source_material(manifest))


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return "sha256:" + canonical_json_hash(manifest)


def literal_sha256(value: str | bytes) -> str:
    """Hash literal bytes independently from structural JSON canonicalization."""

    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def synthetic_fixture_content_sha256(root: Path = FIXTURE_ROOT) -> str:
    """Hash the owned synthetic fixture without creating a manifest cycle."""

    digest = hashlib.sha256()
    # The payload is deliberately separate from derived contract documents:
    # crosswalk/task revisions point back to the manifest and must not create a
    # content-hash cycle.
    payload = root / "payload.json"
    for path in (payload,):
        if not path.is_file():
            raise VideoSemanticsContractError("synthetic fixture payload is missing")
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def validate_source_manifest(manifest: Any) -> list[str]:
    errors = schema_errors("video-semantics-source-manifest.schema.json", manifest)
    if errors:
        return errors
    assert isinstance(manifest, Mapping)
    errors.extend(_assert_sanitized(manifest))
    sources = manifest["sources"]
    source_ids = [item["source_id"] for item in sources]
    source_refs = [item["source_ref"] for item in sources]
    if len(source_ids) != len(set(source_ids)):
        errors.append("source_id values are not distinct")
    if len(source_refs) != len(set(source_refs)):
        errors.append("source_ref values are not distinct")
    expected = semantic_source_revision(manifest)
    if manifest["semantic_source_revision"] != expected:
        errors.append("semantic_source_revision does not match stable source material")
    return errors


def validate_repository_source_manifest(
    manifest: Any, *, fixture_root: Path = FIXTURE_ROOT
) -> list[str]:
    """Apply the stricter policy for the tracked repository manifest."""

    errors = validate_source_manifest(manifest)
    if errors:
        return errors
    assert isinstance(manifest, Mapping)
    if len(manifest["sources"]) != 1:
        errors.append("tracked repository manifest must contain exactly one synthetic source")
    for source in manifest["sources"]:
        if (
            source["kind"] != "synthetic_fixture"
            or source["identity_storage"] != "public-synthetic"
            or source["sensitivity"] != "public_synthetic"
        ):
            errors.append("tracked repository manifest may contain public synthetic sources only")
    expected_fixture_hash = synthetic_fixture_content_sha256(fixture_root)
    if manifest["sources"][0]["content_sha256"] != expected_fixture_hash:
        errors.append("tracked synthetic source content_sha256 differs from fixture bytes")
    return errors


def validate_acquisition_receipt(receipt: Any, manifest: Mapping[str, Any]) -> list[str]:
    errors = schema_errors("video-semantics-acquisition-receipt.schema.json", receipt)
    if errors:
        return errors
    assert isinstance(receipt, Mapping)
    errors.extend(_assert_sanitized(receipt))
    if receipt["manifest_sha256"] != manifest_digest(manifest):
        errors.append("acquisition receipt is bound to a different manifest")
    source_ids = {item["source_id"] for item in manifest["sources"]}
    if receipt["source_id"] not in source_ids:
        errors.append("acquisition receipt source_id is not in the manifest")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != manifest_digest(body):
        errors.append("acquisition receipt self-hash is invalid")
    return errors


def canonical_concept_material(concept: Mapping[str, Any]) -> dict[str, Any]:
    """Stable semantic identity, excluding relations and review telemetry."""

    return {
        "schema_version": concept["schema_version"],
        "editorial_source_ref": concept["editorial_source_ref"],
        "source_locator": concept["source_locator"],
        "editorial_variant": concept["editorial_variant"],
        "scope": sorted(concept["scope"]),
        "source_label": concept["source_label"],
        "definition": concept["definition"],
        "include_when": concept["include_when"],
        "exclude_when": concept["exclude_when"],
        "cardinality": concept["cardinality"],
    }


def semantic_concept_id(concept: Mapping[str, Any]) -> str:
    """Return the host-owned deterministic ID for one concept candidate."""

    return "sha256:" + canonical_json_hash(canonical_concept_material(concept))


def validate_concepts(concepts: Sequence[Any]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, concept in enumerate(concepts):
        concept_errors = schema_errors("video-editorial-concept.schema.json", concept)
        errors.extend(f"concept[{index}]: {error}" for error in concept_errors)
        if isinstance(concept, Mapping):
            errors.extend(f"concept[{index}]: {error}" for error in _assert_sanitized(concept))
            concept_id = concept.get("concept_id")
            if isinstance(concept_id, str) and concept_id in ids:
                errors.append(f"concept[{index}]: duplicate concept_id")
            if isinstance(concept_id, str):
                ids.add(concept_id)
                by_id[concept_id] = concept
            if not concept_errors and concept_id != semantic_concept_id(concept):
                errors.append(f"concept[{index}]: concept_id is not deterministic")
            cardinality = concept.get("cardinality")
            if (
                isinstance(cardinality, Mapping)
                and set(cardinality) == {"kind", "min", "max"}
                and isinstance(cardinality.get("kind"), str)
                and type(cardinality.get("min")) is int
                and (type(cardinality.get("max")) is int or cardinality.get("max") is None)
            ):
                kind = cardinality["kind"]
                minimum = cardinality["min"]
                maximum = cardinality["max"]
                if maximum is not None and minimum > maximum:
                    errors.append(f"concept[{index}]: cardinality min exceeds max")
                if kind == "one" and (minimum not in {0, 1} or maximum != 1):
                    errors.append(f"concept[{index}]: one cardinality must be 0..1 or 1..1")
                elif kind == "max" and (minimum != 0 or maximum is None or maximum < 1):
                    errors.append(f"concept[{index}]: max cardinality must be 0..N with N >= 1")
                elif kind == "range" and maximum is None:
                    errors.append(f"concept[{index}]: range cardinality requires max")
                elif kind == "unbounded" and maximum is not None:
                    errors.append(f"concept[{index}]: unbounded cardinality requires null max")
    for index, concept in enumerate(concepts):
        if not isinstance(concept, Mapping):
            continue
        for relation in ("parents", "children", "dependencies", "exclusive_with"):
            for ref in concept.get(relation, []):
                if not isinstance(ref, str) or ref not in ids:
                    errors.append(f"concept[{index}]: dangling {relation} ref")
                if ref == concept.get("concept_id"):
                    errors.append(f"concept[{index}]: self-referential {relation} ref")
        concept_id = concept.get("concept_id")
        if not isinstance(concept_id, str):
            continue
        for parent_id in concept.get("parents", []):
            parent = by_id.get(parent_id)
            if parent is not None and concept_id not in parent.get("children", []):
                errors.append(f"concept[{index}]: parent/child relation is not reciprocal")
        for child_id in concept.get("children", []):
            child = by_id.get(child_id)
            if child is not None and concept_id not in child.get("parents", []):
                errors.append(f"concept[{index}]: child/parent relation is not reciprocal")
        for other_id in concept.get("exclusive_with", []):
            other = by_id.get(other_id)
            if other is not None and concept_id not in other.get("exclusive_with", []):
                errors.append(f"concept[{index}]: exclusive_with relation is not symmetric")

    indegree = {concept_id: 0 for concept_id in by_id}
    children_by_parent = {concept_id: set() for concept_id in by_id}
    for concept_id, concept in by_id.items():
        for parent_id in concept.get("parents", []):
            if parent_id in by_id and concept_id not in children_by_parent[parent_id]:
                children_by_parent[parent_id].add(concept_id)
                indegree[concept_id] += 1
    ready = sorted(concept_id for concept_id, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        current = ready.pop(0)
        visited += 1
        for child_id in sorted(children_by_parent[current]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(child_id)
                ready.sort()
    if visited != len(by_id):
        errors.append("concept hierarchy contains a cycle")
    return errors


def validate_work_item(item: Any, *, concept_ids: set[str] | None = None) -> list[str]:
    errors = schema_errors("video-semantic-work-item.schema.json", item)
    if errors:
        return errors
    assert isinstance(item, Mapping)
    errors.extend(_assert_sanitized(item))
    path = item["canonical_locator"]["path"]
    if RELATIVE_PATH_RE.fullmatch(path) is None:
        errors.append("work item path is not a safe relative path")
    if concept_ids is not None:
        for ref in item["editorial_rules"]["dependencies"]:
            if ref not in concept_ids:
                errors.append("work item has a dangling concept dependency")
    candidate = item["candidate"]
    means = candidate["means"]
    has_means = isinstance(means, str) and bool(means.strip())
    if candidate["aka"] and not has_means:
        errors.append("work item aka requires a non-empty means")
    if not has_means and candidate["review_state"] != "unannotated":
        errors.append("work item without means must be unannotated")
    if has_means and candidate["review_state"] == "unannotated":
        errors.append("work item with means cannot be unannotated")
    return errors


def validate_crosswalk(
    crosswalk: Any,
    *,
    concept_ids: set[str] | None = None,
    semantic_source_revision_ref: str | None = None,
) -> list[str]:
    errors = schema_errors("video-semantic-crosswalk.schema.json", crosswalk)
    if errors:
        return errors
    assert isinstance(crosswalk, Mapping)
    errors.extend(_assert_sanitized(crosswalk))
    if (
        semantic_source_revision_ref is not None
        and crosswalk["semantic_source_revision"] != semantic_source_revision_ref
    ):
        errors.append("crosswalk semantic_source_revision differs from manifest")
    seen: set[tuple[Any, ...]] = set()
    for index, row in enumerate(crosswalk["rows"]):
        key = (row["concept_id"], row["canonical_locator"], row["literal"])
        if key in seen:
            errors.append(f"crosswalk row[{index}] is a duplicate locator")
        seen.add(key)
        if concept_ids is not None and row["concept_id"] not in concept_ids:
            errors.append(f"crosswalk row[{index}] has a dangling concept ref")
    return errors


def validate_constraints(ledger: Any) -> list[str]:
    errors = schema_errors("video-editorial-constraint.schema.json", ledger)
    if errors:
        return errors
    assert isinstance(ledger, Mapping)
    errors.extend(_assert_sanitized(ledger))
    for index, item in enumerate(ledger["constraints"]):
        if item["grammar_expressed"] and item["future_grammar_decision"] is not None:
            errors.append(f"constraint[{index}] expresses grammar but requests future grammar work")
        if not item["editorial_oracle"] and item["brain_behavior"] == "apply":
            errors.append(f"constraint[{index}] cannot apply without an editorial oracle")
    return errors


def validate_profile(profile: Any) -> list[str]:
    errors = schema_errors("video-catalog-census-profile.schema.json", profile)
    if errors:
        return errors
    assert isinstance(profile, Mapping)
    errors.extend(_assert_sanitized(profile))
    expected_revision = "sha256:" + canonical_json_hash(
        {key: value for key, value in profile.items() if key != "profile_revision"}
    )
    if profile["profile_revision"] != expected_revision:
        errors.append("profile_revision does not match stable profile material")
    seen: set[str] = set()
    for item in profile["fields"]:
        field = item["field_path"]
        if field in seen:
            errors.append(f"duplicate profile field: {field}")
        seen.add(field)
        if item["page_size"] > 10000:
            errors.append(f"profile field {field} page size exceeds bound")
        if item["capability"] == "enumerate-finite-values" and item["max_literal_bytes"] == 0:
            errors.append(f"finite field {field} has no literal budget")
    return errors


def validate_census_receipt(receipt: Any) -> list[str]:
    errors = schema_errors("video-catalog-census-receipt.schema.json", receipt)
    if errors:
        return errors
    assert isinstance(receipt, Mapping)
    errors.extend(_assert_sanitized(receipt))
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != manifest_digest(body):
        errors.append("census receipt self-hash is invalid")
    if receipt["evidence_scope"] == "offline_contract":
        if receipt["snapshot_ref"] is not None or any(
            key in receipt
            for key in (
                "mapping_sha256_before",
                "mapping_sha256_after",
                "document_count_before",
                "document_count_after",
            )
        ):
            errors.append("offline receipt contains live census evidence")
        if receipt["query_count"] != len(receipt["query_hashes"]):
            errors.append("offline receipt query_count does not equal query_hashes count")
        return errors
    if receipt["query_count"] != len(receipt["query_hashes"]):
        errors.append("query_count does not equal query_hashes count")
    if receipt["status"] == "VALID":
        if receipt["mapping_sha256_before"] != receipt["mapping_sha256_after"]:
            errors.append("VALID census mapping changed")
        if receipt["document_count_before"] != receipt["document_count_after"]:
            errors.append("VALID census document count changed")
        if any(receipt["state_counts"][key] for key in ("partial", "denied", "inconsistent")):
            errors.append("VALID census contains non-complete field states")
    return errors


def validate_task(task: Any, *, semantic_source_revision_ref: str | None = None) -> list[str]:
    errors = schema_errors("video-grounding-task.schema.json", task)
    if errors:
        return errors
    assert isinstance(task, Mapping)
    errors.extend(_assert_sanitized(task))
    if task["task_id"].split("-")[1] != task["family"].split("-")[1]:
        errors.append("task family does not match task_id")
    if task["semantic_refs"] != task["expected"]["semantic_refs"]:
        errors.append("task semantic refs are not repeated consistently")
    if (
        semantic_source_revision_ref is not None
        and task["provenance"]["source_revision"] != semantic_source_revision_ref
    ):
        errors.append("task source_revision differs from manifest")
    return errors


def validate_scorecard(scorecard: Any, *, task_roster_revision: str | None = None) -> list[str]:
    errors = schema_errors("video-grounding-scorecard.schema.json", scorecard)
    if errors:
        return errors
    assert isinstance(scorecard, Mapping)
    errors.extend(_assert_sanitized(scorecard))
    if set(scorecard["variants"]) != {"B0", "B1", "D0", "D1"}:
        errors.append("scorecard variants are incomplete")
    scores = [("overall", scorecard["overall"])] + [
        ("family", item["score"]) for item in scorecard["families"]
    ]
    for label, score in scores:
        if score["passed"] > score["total"]:
            errors.append(f"{label} score exceeds denominator")
        expected_interval = wilson_interval(score["passed"], score["total"])
        if any(
            abs(actual - expected) > 1e-12
            for actual, expected in zip(score["wilson95"], expected_interval, strict=True)
        ):
            errors.append(f"{label} Wilson interval is not recomputed from counts")
    critical = scorecard["critical"]
    if scorecard["evidence_scope"] == "synthetic_contract":
        if scorecard["roster_complete"] or scorecard["task_roster_revision"] is not None:
            errors.append("synthetic scorecard claims a complete evaluated roster")
        if critical["passed"] != 0 or critical["failed"] != 0:
            errors.append("synthetic scorecard cannot claim critical passes")
    else:
        if not scorecard["roster_complete"]:
            errors.append("evaluated scorecard has an incomplete roster")
        if scorecard["benchmark_revision"] != scorecard["task_roster_revision"]:
            errors.append("evaluated scorecard is not bound to the task roster")
        if (
            task_roster_revision is not None
            and scorecard["benchmark_revision"] != task_roster_revision
        ):
            errors.append("evaluated scorecard task roster revision differs from expected")
        expected_pairs = {
            (variant, family)
            for variant in ("B0", "B1", "D0", "D1")
            for family in ("V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7")
        }
        observed_pairs = {(item["variant"], item["family"]) for item in scorecard["families"]}
        if observed_pairs != expected_pairs:
            errors.append("evaluated scorecard does not contain the complete 4x7 roster")
        if critical["passed"] + critical["failed"] != critical["total"]:
            errors.append("critical score arithmetic is inconsistent")
    body = {key: value for key, value in scorecard.items() if key != "receipt_sha256"}
    if scorecard["receipt_sha256"] != manifest_digest(body):
        errors.append("scorecard self-hash is invalid")
    return errors


def validate_synthetic_fixture(
    root: Path = FIXTURE_ROOT,
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the bounded synthetic fixture and return exact roster counts."""

    manifest = load_json(
        manifest_path or PROJECT_ROOT / "manifests/video-semantics-sources-v1.json"
    )
    concept = load_json(root / "concept.json")
    work_item = load_json(root / "work-item.json")
    crosswalk = load_json(root / "crosswalk.json")
    constraint = load_json(root / "constraint.json")
    profile = load_json(root / "profile.json")
    census_receipt = load_json(root / "census-receipt.json")
    task = load_json(root / "task.json")
    scorecard = load_json(root / "scorecard.json")
    acquisition = {
        "schema_version": 1,
        "receipt_id": "synthetic-receipt-001",
        "manifest_sha256": manifest_digest(manifest),
        "source_id": "VIDEO_SYNTHETIC_FIXTURE_V1",
        "status": "VALID",
        "acquired_at": "2026-08-27T10:00:00Z",
        "duration_ms": 12,
        "run_id": "synthetic-run-001",
        "runtime": {"python": "3.13", "tool_version": "synthetic-1"},
        "counts": {"items_in": 1, "items_out": 1, "items_distinct": 1, "items_gaps": 0},
    }
    acquisition["receipt_sha256"] = manifest_digest(acquisition)
    errors = validate_repository_source_manifest(manifest, fixture_root=root)
    errors.extend(validate_acquisition_receipt(acquisition, manifest))
    errors.extend(validate_concepts([concept]))
    errors.extend(validate_work_item(work_item, concept_ids={concept["concept_id"]}))
    errors.extend(
        validate_crosswalk(
            crosswalk,
            concept_ids={concept["concept_id"]},
            semantic_source_revision_ref=manifest["semantic_source_revision"],
        )
    )
    errors.extend(validate_constraints(constraint))
    errors.extend(validate_profile(profile))
    errors.extend(validate_census_receipt(census_receipt))
    errors.extend(
        validate_task(task, semantic_source_revision_ref=manifest["semantic_source_revision"])
    )
    errors.extend(validate_scorecard(scorecard))
    if errors:
        raise VideoSemanticsContractError("; ".join(errors))
    return {"in": 10, "out": 10, "distinct": 10, "gaps": 0}
