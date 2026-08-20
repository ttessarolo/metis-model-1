"""Deterministic, fail-closed provenance grouping for benchmark tasks.

This module deliberately treats a task's semantic ancestry as the unit of
independence.  Cosmetic IDs, paraphrases, or a different row order cannot
create a new leakage group.  A shared language epoch is metadata except for a
legacy migration root, where it is an explicit semantic edge.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from metis_model1.evaluation import wilson_interval
from metis_model1.provenance import NonJsonValueError, canonical_json_hash, normalize_json

FAMILIES = tuple(f"F-{number}" for number in range(1, 7))
SPLITS = ("train", "dev", "internal_test", "frozen")
TARGET_FAMILY_COUNTS = {
    "F-1": 100,
    "F-2": 110,
    "F-3": 110,
    "F-4": 110,
    "F-5": 90,
    "F-6": 80,
}
TARGET_ID = "accuracy-99/end-to-end-v1"
TARGET_POINT_MIN = 0.99
TARGET_CONFIDENCE = 0.95
TARGET_WILSON_LOWER_MIN = 0.99
TARGET_MINIMUM_GROUPS = 563
TARGET_TOTAL = 600
_SHA256_PREFIX = "sha256:"
_REGISTERED_FORBIDDEN_CRITICAL_FAILURES = {
    "accepted_invented_identifier",
    "benchmark_leakage",
    "identity_mismatch",
    "prohibited_data_exposure",
    "semantic_wrong_compile_clean_accepted",
    "unauthorized_metis_write",
    "unrelated_destructive_change",
}
_FROZEN_EVIDENCE_FIELDS = (
    "task_id",
    "family",
    "success",
    "critical_failures",
    "end_to_end_success",
    "all_applicable_oracles_pass",
    "semantic_or_human_oracle_pass",
    "patch_safety_pass",
    "tool_failure",
    "repair_cycles",
    "oracle_result_sha256",
    "semantic_result_sha256",
)
_HASH_FIELDS = {
    "normalized_ast_hash",
    "normalized_ir_hash",
    "dependency_closure_hash",
    "legacy_epoch_root",
}
_EDGE_FIELDS = {
    "semantic_spec_id",
    "source_seed_id",
    "normalized_ast_hash",
    "normalized_ir_hash",
    "dependency_closure_hash",
    "property_family",
    "mutation_parent",
    "template_id",
    "generator_id",
    "author_session_id",
    "model_session_id",
    "model_generation_session_id",
    "generation_session_id",
    "author_model_generation_session_id",
}


class IndependenceError(ValueError):
    """Raised when a provenance roster cannot support an independence audit."""


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith(_SHA256_PREFIX):
        raise IndependenceError(f"{field} must be a sha256 identity")
    digest = value[len(_SHA256_PREFIX) :]
    if len(digest) != 64:
        raise IndependenceError(f"{field} must be a sha256 identity")
    try:
        int(digest, 16)
    except ValueError as error:
        raise IndependenceError(f"{field} must be a sha256 identity") from error
    if digest != digest.lower():
        raise IndependenceError(f"{field} must use lowercase hexadecimal")
    return value


def _nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IndependenceError(f"{field} must be a non-empty string")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise IndependenceError(f"{field} must be a list")
    return value


def _provenance(task: Mapping[str, Any]) -> Mapping[str, Any]:
    value = task.get("provenance", task)
    if not isinstance(value, Mapping):
        raise IndependenceError("provenance must be an object")
    return value


def _field(provenance: Mapping[str, Any], task: Mapping[str, Any], name: str) -> Any:
    value = provenance.get(name)
    if value is None:
        value = task.get(name)
    return value


def _ids(value: Any, field: str, *, hashes: bool = False) -> list[str]:
    values = _list(value, field)
    result: list[str] = []
    for item in values:
        if hashes:
            result.append(_sha256(item, field))
        else:
            text = _nonempty_text(item, field)
            if text.startswith(_SHA256_PREFIX):
                text = _sha256(text, field)
            result.append(text)
    if len(result) != len(set(result)):
        raise IndependenceError(f"{field} must not contain duplicates")
    return result


def _attest_roots(
    provenance: Mapping[str, Any],
    task: Mapping[str, Any],
    roots: Sequence[str],
    task_id: str,
) -> None:
    evidence = _list(_field(provenance, task, "root_evidence"), "root_evidence")
    if len(evidence) != len(roots):
        raise IndependenceError(f"task {task_id} root evidence must cover every content root")
    for index, (root, material) in enumerate(zip(roots, evidence, strict=True)):
        if not isinstance(material, Mapping):
            raise IndependenceError("root_evidence entries must be objects")
        try:
            normalized = normalize_json(material)
        except NonJsonValueError as error:
            raise IndependenceError(f"root_evidence[{index}] is not canonical JSON") from error
        for field in ("kind", "origin", "authoring_session_id"):
            _nonempty_text(normalized.get(field), f"root_evidence.{field}")
        _sha256(normalized.get("content_sha256"), "root_evidence.content_sha256")
        expected = _SHA256_PREFIX + canonical_json_hash(normalized)
        if root != expected:
            raise IndependenceError(f"task {task_id} content root does not match its evidence")


@dataclass(frozen=True)
class _Task:
    task_id: str
    family: str
    split: str
    roots: tuple[str, ...]
    parents: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    benchmark_roots: tuple[str, ...]


class _UnionFind:
    def __init__(self, values: Sequence[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            next_value = self.parent[value]
            self.parent[value] = root
            value = next_value
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _task_records(records: Sequence[Mapping[str, Any]]) -> list[_Task]:
    if not records:
        raise IndependenceError("at least one task is required")
    ids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise IndependenceError("task records must be objects")
        task_id = _nonempty_text(record.get("task_id"), "task_id")
        if task_id in ids:
            raise IndependenceError(f"duplicate task_id: {task_id}")
        ids.append(task_id)
    known_task_ids = set(ids)
    result: list[_Task] = []
    all_roots: set[str] = set()

    for record in records:
        provenance = _provenance(record)
        task_id = _nonempty_text(record.get("task_id"), "task_id")
        family = _nonempty_text(record.get("family"), "family")
        if family not in FAMILIES:
            raise IndependenceError(f"unknown family: {family}")
        split = _nonempty_text(record.get("split"), "split")
        if split not in SPLITS:
            raise IndependenceError(f"unknown split: {split}")
        if (
            "leakage_group" in record
            or "group_id" in record
            or "leakage_group" in provenance
            or "group_id" in provenance
        ):
            raise IndependenceError("manually declared group IDs are forbidden")

        roots = _ids(_field(provenance, record, "roots"), "roots", hashes=True)
        if not roots:
            raise IndependenceError(f"task {task_id} must declare at least one content root")
        _attest_roots(provenance, record, roots, task_id)
        parents = _ids(_field(provenance, record, "parents"), "parents")
        benchmark_roots = _ids(
            _field(provenance, record, "benchmark_roots"), "benchmark_roots", hashes=True
        )
        all_roots.update(roots)
        all_roots.update(benchmark_roots)

        edge_values: list[tuple[str, str]] = []
        for field in sorted(_EDGE_FIELDS):
            value = _field(provenance, record, field)
            if value is None or value == "" or value == []:
                continue
            if field == "legacy_epoch_root" and family != "F-5":
                continue
            if field in _HASH_FIELDS:
                edge_values.append((field, _sha256(value, field)))
            elif field in {"template_id", "generator_id"}:
                version = _field(provenance, record, f"{field.rsplit('_', 1)[0]}_version")
                if version is None:
                    raise IndependenceError(f"{field} requires a version")
                edge_values.append(
                    (
                        field,
                        _nonempty_text(value, field)
                        + "@"
                        + _nonempty_text(version, f"{field}_version"),
                    )
                )
            elif field in {"mutation_parent", "property_family"}:
                edge_values.append((field, _nonempty_text(value, field)))
            else:
                edge_values.append((field, _nonempty_text(value, field)))

        legacy = _field(provenance, record, "legacy_epoch_root")
        if legacy is not None and legacy != "" and family == "F-5":
            edge_values.append(("legacy_epoch_root", _sha256(legacy, "legacy_epoch_root")))

        result.append(
            _Task(
                task_id,
                family,
                split,
                tuple(roots),
                tuple(parents),
                tuple(edge_values),
                tuple(benchmark_roots),
            )
        )

    for task in result:
        for parent in task.parents:
            if parent == task.task_id:
                raise IndependenceError(f"self-parent: {task.task_id}")
            if parent not in known_task_ids and parent not in all_roots:
                raise IndependenceError(f"unknown parent: {parent}")
    return result


def _components(tasks: Sequence[_Task]) -> list[dict[str, Any]]:
    ids = [task.task_id for task in tasks]
    by_id = {task.task_id: task for task in tasks}
    uf = _UnionFind(ids)
    keyed: dict[tuple[str, str], str] = {}

    for task in tasks:
        # Benchmark roots are semantic ancestry too.  In particular, a frozen
        # row derived from the same benchmark asset must share its component
        # even when its task-local content root is unique.
        for root in (*task.roots, *task.benchmark_roots):
            key = ("ancestry", root)
            if key in keyed:
                uf.union(task.task_id, keyed[key])
            keyed[key] = task.task_id
        for parent in task.parents:
            if parent in by_id:
                uf.union(task.task_id, parent)
            else:
                key = ("ancestry", parent)
                if key in keyed:
                    uf.union(task.task_id, keyed[key])
                keyed[key] = task.task_id
        for field, value in task.edges:
            # A language epoch is deliberately not an edge.  Migration roots
            # are already represented as the explicit legacy_epoch_root edge.
            if field == "language_epoch":
                continue
            key = (
                "generation_session"
                if field
                in {
                    "author_session_id",
                    "model_session_id",
                    "model_generation_session_id",
                    "generation_session_id",
                    "author_model_generation_session_id",
                }
                else field,
                value,
            )
            if key in keyed:
                uf.union(task.task_id, keyed[key])
            keyed[key] = task.task_id

    grouped: dict[str, list[_Task]] = defaultdict(list)
    for task in tasks:
        grouped[uf.find(task.task_id)].append(task)
    components: list[dict[str, Any]] = []
    for members in grouped.values():
        task_ids = sorted(task.task_id for task in members)
        roots = sorted(
            {
                root
                for task in members
                for root in (*task.roots, *task.benchmark_roots, *task.parents)
                if root.startswith(_SHA256_PREFIX)
            }
        )
        edges = [
            [field, value]
            for field, value in sorted({edge for task in members for edge in task.edges})
        ]
        group_id = "sha256:" + canonical_json_hash(
            {"schema_version": 1, "roots": roots, "edges": edges}
        )
        components.append(
            {
                "leakage_group": group_id,
                "task_ids": task_ids,
                "roots": roots,
                "edges": edges,
                "splits": sorted({task.split for task in members}),
                "families": sorted({task.family for task in members}),
                "task_families": {
                    task_id: family
                    for task_id, family in sorted((task.task_id, task.family) for task in members)
                },
            }
        )
    return sorted(components, key=lambda component: component["leakage_group"])


def _score(records: Sequence[Mapping[str, Any]]) -> tuple[int, int] | None:
    values = [record.get("success") for record in records]
    present = ["success" in record for record in records]
    if any(present) and not all(present):
        raise IndependenceError("frozen success evidence must cover the full denominator")
    if all(present) and not all(type(value) is bool for value in values):
        raise IndependenceError("frozen success evidence must use strict booleans")
    if records and all(present):
        return sum(values), len(values)
    return None


def _critical_evidence(records: Sequence[Mapping[str, Any]]) -> tuple[bool, int]:
    complete = True
    count = 0
    for record in records:
        if "critical_failures" not in record:
            complete = False
            continue
        failures = record["critical_failures"]
        if not isinstance(failures, list) or any(
            not isinstance(failure, str) or not failure.strip() for failure in failures
        ):
            raise IndependenceError("critical_failures must be a list of non-empty strings")
        if len(failures) != len(set(failures)):
            raise IndependenceError("critical_failures must not contain duplicates")
        if record.get("success") is True and failures:
            raise IndependenceError("a successful frozen task cannot have critical failures")
        count += len(failures)
    return complete, count


def _semantic_evidence(records: Sequence[Mapping[str, Any]]) -> tuple[bool, int]:
    complete = True
    contradictions = 0
    required_booleans = (
        "end_to_end_success",
        "all_applicable_oracles_pass",
        "semantic_or_human_oracle_pass",
        "patch_safety_pass",
        "tool_failure",
    )
    for record in records:
        evidence = record.get("oracle_evidence")
        if evidence is None:
            complete = False
            continue
        if not isinstance(evidence, Mapping):
            raise IndependenceError("oracle_evidence must be an object")
        for field in required_booleans:
            if type(evidence.get(field)) is not bool:
                raise IndependenceError(f"oracle_evidence.{field} must be a strict boolean")
        _sha256(evidence.get("oracle_result_sha256"), "oracle_result_sha256")
        _sha256(evidence.get("semantic_result_sha256"), "semantic_result_sha256")
        cycles = evidence.get("repair_cycles")
        if type(cycles) is not int or not 0 <= cycles <= 2:
            raise IndependenceError("oracle_evidence.repair_cycles must be an integer from 0 to 2")
        success = record.get("success")
        if type(success) is not bool or evidence["end_to_end_success"] is not success:
            raise IndependenceError("oracle evidence contradicts the task success value")
        success_predicates = (
            evidence["all_applicable_oracles_pass"],
            evidence["semantic_or_human_oracle_pass"],
            evidence["patch_safety_pass"],
            not evidence["tool_failure"],
        )
        if success and not all(success_predicates):
            contradictions += 1
    return complete, contradictions


def _frozen_evidence(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the canonical, immutable per-task frozen evidence roster.

    An unscored audit remains valid as product evidence, but it cannot expose a
    promotion roster.  In that case the roster is deliberately empty and its
    digest still commits to that fact.  A complete roster is sorted by task ID
    so input row order cannot change its identity.
    """

    required_record_fields = ("task_id", "family", "success", "critical_failures")
    if any(
        any(field not in record for field in required_record_fields)
        or record.get("oracle_evidence") is None
        for record in records
    ):
        return []

    evidence_rows: list[dict[str, Any]] = []
    for record in records:
        evidence = record["oracle_evidence"]
        if not isinstance(evidence, Mapping):
            raise IndependenceError("oracle_evidence must be an object")
        task_id = _nonempty_text(record["task_id"], "task_id")
        family = _nonempty_text(record["family"], "family")
        success = record["success"]
        critical_failures = record["critical_failures"]
        if family not in FAMILIES:
            raise IndependenceError(f"unknown family: {family}")
        if type(success) is not bool:
            raise IndependenceError("frozen success evidence must use strict booleans")
        if not isinstance(critical_failures, list):
            raise IndependenceError("critical_failures must be a list of non-empty strings")
        evidence_rows.append(
            {
                "task_id": task_id,
                "family": family,
                "success": success,
                "critical_failures": list(critical_failures),
                "end_to_end_success": evidence["end_to_end_success"],
                "all_applicable_oracles_pass": evidence["all_applicable_oracles_pass"],
                "semantic_or_human_oracle_pass": evidence["semantic_or_human_oracle_pass"],
                "patch_safety_pass": evidence["patch_safety_pass"],
                "tool_failure": evidence["tool_failure"],
                "repair_cycles": evidence["repair_cycles"],
                "oracle_result_sha256": evidence["oracle_result_sha256"],
                "semantic_result_sha256": evidence["semantic_result_sha256"],
            }
        )
    return sorted(evidence_rows, key=lambda row: row["task_id"])


def _bind_target_contract(contract: Mapping[str, Any] | None) -> tuple[bool, str | None]:
    if contract is None:
        return False, None
    try:
        normalized = normalize_json(contract)
    except NonJsonValueError as error:
        raise IndependenceError("target contract is not canonical JSON") from error
    if not isinstance(normalized, Mapping):
        raise IndependenceError("target contract must be an object")
    exact = {
        "target_id": TARGET_ID,
        "status": "ratified",
        "registered_before_candidate_results": True,
        "variant": "D",
        "total": TARGET_TOTAL,
        "family_counts": TARGET_FAMILY_COUNTS,
        "point_min": TARGET_POINT_MIN,
        "confidence": TARGET_CONFIDENCE,
        "wilson_lower_min": TARGET_WILSON_LOWER_MIN,
        "maximum_failures": 1,
        "minimum_distinct_leakage_groups": TARGET_MINIMUM_GROUPS,
        "repair_budget": 2,
    }
    for field, expected in exact.items():
        if normalized.get(field) != expected:
            raise IndependenceError(f"target contract does not match registered {field}")
    population = normalized.get("population_attestation")
    if not isinstance(population, Mapping) or population.get("status") != "verified":
        raise IndependenceError("target contract lacks a verified population attestation")
    _sha256(population.get("evidence_sha256"), "population_attestation.evidence_sha256")
    _nonempty_text(population.get("reviewer_session_id"), "population reviewer session")
    forbidden = normalized.get("forbidden_critical_failures")
    if (
        not isinstance(forbidden, list)
        or len(forbidden) != len(_REGISTERED_FORBIDDEN_CRITICAL_FAILURES)
        or any(type(item) is not str or not item.strip() for item in forbidden)
        or len(set(forbidden)) != len(forbidden)
        or set(forbidden) != _REGISTERED_FORBIDDEN_CRITICAL_FAILURES
    ):
        raise IndependenceError(
            "target contract forbidden critical-failure roster is not registered"
        )
    if normalized.get("require_zero_unlisted_critical_failures") is not True:
        raise IndependenceError("target contract must require zero unlisted critical failures")
    return True, _SHA256_PREFIX + canonical_json_hash(normalized)


def audit_independence(
    records: Iterable[Mapping[str, Any]],
    *,
    target_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic independence audit or raise on invalid input."""

    try:
        rows = list(records)
        normalize_json(rows)
    except (NonJsonValueError, TypeError, ValueError) as error:
        raise IndependenceError(f"records are not finite canonical JSON: {error}") from error
    target_bound, target_contract_sha256 = _bind_target_contract(target_contract)

    tasks = _task_records(rows)
    components = _components(tasks)
    by_id = {task.task_id: task for task in tasks}
    benchmark_violations = sorted(
        task.task_id for task in tasks if task.split != "frozen" and task.benchmark_roots
    )
    if benchmark_violations:
        raise IndependenceError("benchmark roots in W3: " + ",".join(benchmark_violations))

    cross_split = [
        component["leakage_group"] for component in components if len(component["splits"]) > 1
    ]
    if cross_split:
        raise IndependenceError("transitive split crossing: " + ",".join(sorted(cross_split)))

    frozen_rows = [row for row in rows if row.get("split") == "frozen"]
    score = _score(frozen_rows)
    groups = len(components)
    frozen_groups = len(
        {component["leakage_group"] for component in components if "frozen" in component["splits"]}
    )
    frozen_family_counts = {
        family: sum(task.family == family and task.split == "frozen" for task in tasks)
        for family in FAMILIES
    }
    family_counts_match = frozen_family_counts == TARGET_FAMILY_COUNTS
    critical_complete, critical_count = _critical_evidence(frozen_rows)
    semantic_complete, semantic_contradictions = _semantic_evidence(frozen_rows)
    frozen_evidence = _frozen_evidence(frozen_rows)
    frozen_evidence_sha256 = _SHA256_PREFIX + canonical_json_hash(frozen_evidence)
    score_pass = False
    wilson_lower = None
    if score is not None:
        successes, total = score
        wilson_lower = wilson_interval(successes, total, TARGET_CONFIDENCE).lower
        score_pass = (
            successes / total >= TARGET_POINT_MIN and wilson_lower >= TARGET_WILSON_LOWER_MIN
        )
    operational_score_pass = (
        score_pass
        and semantic_complete
        and semantic_contradictions == 0
        and critical_complete
        and critical_count == 0
    )
    target_contract_pass = (
        operational_score_pass
        and target_bound
        and len(frozen_rows) == TARGET_TOTAL
        and frozen_groups >= TARGET_MINIMUM_GROUPS
        and family_counts_match
    )
    if target_contract_pass:
        verdict = "TARGET_99_CONFIRMED"
    elif operational_score_pass:
        verdict = "OBSERVED_99_ONLY"
    else:
        verdict = "PRODUCT_EVIDENCE"

    counts_by_split: dict[str, dict[str, int]] = {}
    counts_by_family: dict[str, dict[str, int]] = {}
    for split in SPLITS:
        members = [task for task in tasks if task.split == split]
        counts_by_split[split] = {
            "tasks": len(members),
            "distinct_groups": len(
                {
                    component["leakage_group"]
                    for component in components
                    if split in component["splits"]
                }
            ),
        }
    for family in FAMILIES:
        members = [task for task in tasks if task.family == family]
        counts_by_family[family] = {
            "tasks": len(members),
            "distinct_groups": len(
                {
                    component["leakage_group"]
                    for component in components
                    if family in component["families"]
                }
            ),
        }

    return {
        "schema_version": 1,
        "counts": {
            "in": len(rows),
            "out": len(tasks),
            "distinct": len(by_id),
            "gaps": 0,
            "distinct_leakage_groups": groups,
            "frozen_distinct_leakage_groups": frozen_groups,
        },
        "components": components,
        "counts_by_split": counts_by_split,
        "counts_by_family": counts_by_family,
        "cross_split_violations": [],
        "benchmark_root_violations": [],
        "frozen_evidence": frozen_evidence,
        "frozen_evidence_sha256": frozen_evidence_sha256,
        "observed": {
            "successes": score[0] if score else None,
            "total": score[1] if score else None,
            "wilson_lower": wilson_lower,
            "point_min": TARGET_POINT_MIN,
            "confidence": TARGET_CONFIDENCE,
            "wilson_lower_min": TARGET_WILSON_LOWER_MIN,
            "minimum_distinct_leakage_groups": TARGET_MINIMUM_GROUPS,
            "required_frozen_tasks": TARGET_TOTAL,
            "required_family_counts": dict(sorted(TARGET_FAMILY_COUNTS.items())),
            "frozen_family_counts": dict(sorted(frozen_family_counts.items())),
            "family_counts_match": family_counts_match,
            "critical_evidence_complete": critical_complete,
            "critical_failure_count": critical_count,
            "semantic_evidence_complete": semantic_complete,
            "semantic_evidence_contradictions": semantic_contradictions,
            "target_contract_bound": target_bound,
            "target_contract_sha256": target_contract_sha256,
        },
        "verdict": verdict,
    }


build_independence_audit = audit_independence
