"""Fail-closed offline evaluation of oracle-grounded A/B/C/D observations."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import comb
from typing import Any

from metis_model1.evaluation import wilson_interval

VARIANTS = ("A", "B", "C", "D")
FAMILIES = tuple(f"F-{number}" for number in range(1, 7))
ORACLE_REGISTRY = {
    "F-1": ("parse", "link", "validate", "compile", "semantic"),
    "F-2": ("patch_minimality", "parse", "link", "validate", "compile", "semantic"),
    "F-3": ("diagnostic", "parse", "link", "validate", "compile", "semantic"),
    "F-4": ("compile", "ir", "wire", "golden", "semantic"),
    "F-5": ("migration_pair", "parse", "link", "validate", "compile", "semantic"),
    "F-6": ("ast", "ir", "semantic", "human"),
}
ALL_ORACLES = frozenset(oracle for names in ORACLE_REGISTRY.values() for oracle in names)
REQUIRED_ORACLES_BY_FAMILY = ORACLE_REGISTRY
ORACLE_NAMES = ALL_ORACLES
OUTCOMES = ("pass", "fail", "not_applicable")
FAILURE_CATEGORIES = frozenset(
    {
        "misunderstanding",
        "syntax",
        "linking",
        "validation",
        "compile",
        "semantic",
        "nonminimal_or_regressive",
        "context_or_retrieval",
        "loop_or_tool",
        "benchmark_oracle",
        "invented_identifier",
        "unknown",
    }
)
IDENTITY_KEYS = (
    "seed",
    "base_model_hash",
    "adapter_hash",
    "dataset_manifest_hash",
    "compiler_hash",
    "benchmark_hash",
    "runtime_hash",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^git:[0-9a-f]{40}$")
CONFIG_KEYS = (
    "prompt_hash",
    "sampling_hash",
    "reasoning_mode",
    "context_budget",
    "repair_budget",
    "context_enabled",
    "compiler_loop",
    "adapter_enabled",
)
OBSERVATION_KEYS = frozenset(
    {
        "task_id",
        "family",
        "variant",
        "leakage_group",
        "config",
        "identity",
        "evidence",
        "first_shot_success",
        "post_repair_success",
        "first_shot_end_to_end",
        "post_repair_end_to_end",
        "repair_cycles",
        "first_shot_outcomes",
        "post_repair_outcomes",
        "outcomes",  # accepted only as an alias for post_repair_outcomes
        "tool_failure",
        "critical_failures",
        "failure_category",
        "invented_identifier",
    }
)
EVIDENCE_KEYS = ("output_sha256", "first_shot_oracles", "post_repair_oracles")


class EvaluationError(ValueError):
    """Raised when evidence cannot support a trustworthy report."""


def _strict_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise EvaluationError(f"{name} must be a strict bool")
    return value


def _strict_int(value: object, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise EvaluationError(f"{name} must be an integer in the allowed range")
    return value


def _string(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise EvaluationError(f"{name} must be a non-empty string")
    return value


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _reject_unknown(raw: Mapping[str, Any], allowed: Iterable[str], label: str) -> None:
    unknown = set(raw) - set(allowed)
    if unknown:
        raise EvaluationError(f"unknown {label} key(s): {', '.join(sorted(unknown))}")


def _outcome_map(raw: object, required: tuple[str, ...], label: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise EvaluationError(f"{label} must be an object")
    _reject_unknown(raw, required, label)
    if set(raw) != set(required):
        missing = sorted(set(required) - set(raw))
        raise EvaluationError(f"{label} missing oracle(s): {', '.join(missing)}")
    result = {}
    for oracle in required:
        value = raw[oracle]
        if value not in OUTCOMES:
            raise EvaluationError(f"{label}.{oracle} has an invalid outcome")
        if value == "not_applicable":
            raise EvaluationError(f"required oracle {oracle} cannot be not_applicable")
        result[oracle] = value
    return result


def _evidence_map(raw: object, required: tuple[str, ...], label: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise EvaluationError(f"{label} must be an object")
    _reject_unknown(raw, required, label)
    if set(raw) != set(required):
        raise EvaluationError(f"{label} must contain exactly the required oracles")
    result = {}
    for oracle in required:
        value = _string(raw[oracle], f"{label}.{oracle}")
        if not value.startswith("sha256:") or not SHA256_RE.fullmatch(value[7:]):
            raise EvaluationError(f"{label}.{oracle} must be sha256:<64 hex>")
        result[oracle] = value
    return result


def _sign_test(left_wins: int, right_wins: int) -> float:
    discordant = left_wins + right_wins
    if discordant == 0:
        return 1.0
    tail = sum(comb(discordant, k) for k in range(min(left_wins, right_wins) + 1)) / 2**discordant
    return min(1.0, 2.0 * tail)


@dataclass(frozen=True)
class Observation:
    """Validated immutable row; callers must supply mappings, never this object."""

    task_id: str
    family: str
    variant: str
    leakage_group: str
    config: dict[str, Any]
    identity: dict[str, Any]
    evidence: dict[str, Any]
    first_shot_success: bool
    post_repair_success: bool
    repair_cycles: int
    first_shot_outcomes: dict[str, str]
    post_repair_outcomes: dict[str, str]
    tool_failure: bool
    critical_failures: tuple[str, ...]
    failure_category: str | None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Observation:
        if not isinstance(raw, Mapping):
            raise EvaluationError("each observation must be an object")
        _reject_unknown(raw, OBSERVATION_KEYS, "observation")
        config = raw.get("config")
        identity = raw.get("identity")
        evidence = raw.get("evidence")
        if not isinstance(config, Mapping) or not isinstance(identity, Mapping):
            raise EvaluationError("config and identity are required objects")
        if not isinstance(evidence, Mapping):
            raise EvaluationError("evidence is required and must be an object")
        _reject_unknown(evidence, EVIDENCE_KEYS, "evidence")
        if set(evidence) != set(EVIDENCE_KEYS):
            raise EvaluationError("evidence must contain output and both stage oracle maps")
        output_hash = _string(evidence["output_sha256"], "evidence.output_sha256")
        if not output_hash.startswith("sha256:") or not SHA256_RE.fullmatch(output_hash[7:]):
            raise EvaluationError("evidence.output_sha256 must be sha256:<64 hex>")
        _reject_unknown(config, CONFIG_KEYS, "config")
        _reject_unknown(identity, IDENTITY_KEYS, "identity")
        if set(identity) != set(IDENTITY_KEYS):
            raise EvaluationError("identity must contain the complete immutable identity")
        for key in IDENTITY_KEYS:
            if key == "seed":
                _strict_int(identity[key], "identity.seed")
            else:
                value = _string(identity[key], f"identity.{key}")
                if key == "compiler_hash":
                    if not SHA256_RE.fullmatch(value) and not GIT_RE.fullmatch(value):
                        raise EvaluationError("identity.compiler_hash must be sha256 or git:sha1")
                elif key == "adapter_hash":
                    if value != "none" and not SHA256_RE.fullmatch(value):
                        raise EvaluationError("identity.adapter_hash must be none or sha256")
                elif not SHA256_RE.fullmatch(value):
                    raise EvaluationError(f"identity.{key} must be a SHA-256 hash")
        if set(config) != set(CONFIG_KEYS):
            raise EvaluationError("config must contain the complete comparable configuration")
        for key in ("prompt_hash", "sampling_hash", "reasoning_mode"):
            value = _string(config[key], f"config.{key}")
            if key in ("prompt_hash", "sampling_hash") and not SHA256_RE.fullmatch(value):
                raise EvaluationError(f"config.{key} must be a SHA-256 hash")
        for key in ("context_budget", "repair_budget"):
            _strict_int(config[key], f"config.{key}", maximum=2 if key == "repair_budget" else None)
        for key in ("context_enabled", "compiler_loop", "adapter_enabled"):
            _strict_bool(config[key], f"config.{key}")
        task_id = _string(raw.get("task_id"), "task_id")
        family = _string(raw.get("family"), "family")
        variant = _string(raw.get("variant"), "variant")
        leakage_group = _string(raw.get("leakage_group"), "leakage_group")
        if family not in FAMILIES or variant not in VARIANTS:
            raise EvaluationError("family or variant is outside the frozen registry")
        expected_context = variant in ("B", "D")
        expected_adapter = variant in ("C", "D")
        if (
            config["context_enabled"] != expected_context
            or config["compiler_loop"] != expected_context
        ):
            raise EvaluationError(
                f"variant {variant} has invalid context/compiler-loop configuration"
            )
        if config["adapter_enabled"] != expected_adapter:
            raise EvaluationError(f"variant {variant} has invalid adapter configuration")
        first = _strict_bool(raw.get("first_shot_success"), "first_shot_success")
        post = _strict_bool(raw.get("post_repair_success"), "post_repair_success")
        cycles = _strict_int(raw.get("repair_cycles"), "repair_cycles", maximum=2)
        if cycles > config["repair_budget"]:
            raise EvaluationError("repair_cycles cannot exceed repair_budget")
        if first and cycles != 0:
            raise EvaluationError("first-shot success requires zero repair_cycles")
        if first and not post:
            raise EvaluationError("post_repair_success cannot be false after first-shot success")
        if post and not first and cycles < 1:
            raise EvaluationError(
                "post-repair success after first-shot failure needs a repair cycle"
            )
        required = ORACLE_REGISTRY[family]
        if "first_shot_outcomes" not in raw:
            raise EvaluationError("first_shot_outcomes is required for stage-grounded scoring")
        if (
            "post_repair_outcomes" in raw
            and "outcomes" in raw
            and raw["post_repair_outcomes"] != raw["outcomes"]
        ):
            raise EvaluationError("conflicting post_repair_outcomes and outcomes fields")
        post_raw = raw.get("post_repair_outcomes", raw.get("outcomes"))
        first_outcomes = _outcome_map(raw["first_shot_outcomes"], required, "first_shot_outcomes")
        post_outcomes = _outcome_map(post_raw, required, "post_repair_outcomes")
        first_evidence = _evidence_map(
            evidence["first_shot_oracles"], required, "evidence.first_shot_oracles"
        )
        post_evidence = _evidence_map(
            evidence["post_repair_oracles"], required, "evidence.post_repair_oracles"
        )
        failures = raw.get("critical_failures", [])
        if not isinstance(failures, list) or any(
            type(item) is not str or not item.strip() for item in failures
        ):
            raise EvaluationError("critical_failures must be a list of non-empty strings")
        if len(failures) != len(set(failures)):
            raise EvaluationError("critical_failures must not contain duplicates")
        invented = _strict_bool(raw.get("invented_identifier", False), "invented_identifier")
        invented_failure = any(
            "invented" in item.lower() and "identifier" in item.lower() for item in failures
        )
        if invented and not invented_failure:
            raise EvaluationError("invented_identifier must be propagated as a critical failure")
        category = raw.get("failure_category")
        if category is not None:
            category = _string(category, "failure_category")
            if category not in FAILURE_CATEGORIES:
                raise EvaluationError("failure_category is not in the frozen taxonomy")
        if (
            category is not None
            and post
            and not failures
            and all(value == "pass" for value in post_outcomes.values())
            and not raw.get("tool_failure", False)
        ):
            raise EvaluationError("a successful row cannot carry a failure_category")
        tool_failure = _strict_bool(raw.get("tool_failure", False), "tool_failure")
        expected_category = _derive_category(post_outcomes, tool_failure, failures, post)
        if category is not None and category != expected_category:
            raise EvaluationError(
                f"failure_category {category!r} is incoherent; expected {expected_category!r}"
            )
        result = cls(
            task_id,
            family,
            variant,
            leakage_group,
            dict(config),
            dict(identity),
            {
                "output_sha256": output_hash,
                "first_shot_oracles": first_evidence,
                "post_repair_oracles": post_evidence,
            },
            first,
            post,
            cycles,
            first_outcomes,
            post_outcomes,
            tool_failure,
            tuple(failures),
            category,
        )
        for key, expected in (
            ("first_shot_end_to_end", result.first_shot_end_to_end),
            ("post_repair_end_to_end", result.post_repair_end_to_end),
        ):
            if key in raw and _strict_bool(raw[key], key) != expected:
                raise EvaluationError(f"{key} is inconsistent with oracle-grounded outcomes")
        if not result.post_repair_end_to_end and category is None:
            raise EvaluationError(
                "every computed post-repair failure requires an enumerated failure_category"
            )
        return result

    def oracle_success(self, stage: str) -> bool:
        outcomes = self.first_shot_outcomes if stage == "first_shot" else self.post_repair_outcomes
        return (
            all(value == "pass" for value in outcomes.values())
            and not self.tool_failure
            and not self.critical_failures
        )

    @property
    def first_shot_end_to_end(self) -> bool:
        return self.first_shot_success and self.oracle_success("first_shot")

    @property
    def post_repair_end_to_end(self) -> bool:
        return self.post_repair_success and self.oracle_success("post_repair")


def _derive_category(
    outcomes: Mapping[str, str], tool: bool, failures: Iterable[str], post: bool
) -> str | None:
    lowered = " ".join(failures).lower()
    if "benchmark" in lowered or "oracle" in lowered:
        return "benchmark_oracle"
    if "invented" in lowered and "identifier" in lowered:
        return "invented_identifier"
    if tuple(failures):
        return "unknown"
    if tool:
        return "loop_or_tool"
    if outcomes.get("patch_minimality") == "fail":
        return "nonminimal_or_regressive"
    if outcomes.get("diagnostic") == "fail":
        return "context_or_retrieval"
    if outcomes.get("human") == "fail":
        return "semantic"
    if outcomes.get("parse") == "fail":
        return "syntax"
    if outcomes.get("link") == "fail":
        return "linking"
    if outcomes.get("validate") == "fail":
        return "validation"
    if outcomes.get("compile") == "fail":
        return "compile"
    if outcomes.get("semantic") == "fail":
        return "semantic"
    return "unknown" if not post else None


def _metric(rows: list[Observation], attr: str) -> dict[str, Any]:
    successes = sum(bool(getattr(row, attr)) for row in rows)
    interval = wilson_interval(successes, len(rows))
    return {
        "successes": successes,
        "total": len(rows),
        "denominator": len(rows),
        "rate": successes / len(rows),
        "wilson95": {"lower": interval.lower, "upper": interval.upper},
    }


def _variant_report(rows: list[Observation]) -> dict[str, Any]:
    taxonomy = Counter(
        row.failure_category
        or _derive_category(
            row.post_repair_outcomes,
            row.tool_failure,
            row.critical_failures,
            row.post_repair_success,
        )
        for row in rows
    )
    taxonomy.pop(None, None)
    critical = Counter(failure for row in rows for failure in row.critical_failures)
    family = {}
    for name in FAMILIES:
        selected = [row for row in rows if row.family == name]
        if selected:
            family[name] = {
                "first_shot": _metric(selected, "first_shot_end_to_end"),
                "post_repair": _metric(selected, "post_repair_end_to_end"),
            }
    return {
        "denominator": len(rows),
        "first_shot": _metric(rows, "first_shot_end_to_end"),
        "post_repair": _metric(rows, "post_repair_end_to_end"),
        "family_breakdown": family,
        "failure_taxonomy": dict(sorted(taxonomy.items())),
        "critical_failures": dict(sorted(critical.items())),
    }


def _paired(left: list[Observation], right: list[Observation], attr: str) -> dict[str, Any]:
    lrows = {row.task_id: row for row in left}
    rrows = {row.task_id: row for row in right}
    if set(lrows) != set(rrows):
        raise EvaluationError("paired delta roster mismatch")
    left_success = sum(bool(getattr(lrows[key], attr)) for key in lrows)
    right_success = sum(bool(getattr(rrows[key], attr)) for key in rrows)
    total = len(lrows)
    left_wins = sum(
        bool(getattr(lrows[key], attr)) and not bool(getattr(rrows[key], attr)) for key in lrows
    )
    right_wins = sum(
        bool(getattr(rrows[key], attr)) and not bool(getattr(lrows[key], attr)) for key in lrows
    )
    return {
        "left_successes": left_success,
        "right_successes": right_success,
        "denominator": total,
        "left_rate": left_success / total,
        "right_rate": right_success / total,
        "delta_successes": left_success - right_success,
        "delta_rate": (left_success - right_success) / total,
        "discordant_left_wins": left_wins,
        "discordant_right_wins": right_wins,
        "discordant_total": left_wins + right_wins,
        "sign_test_p_value": _sign_test(left_wins, right_wins),
    }


def evaluate_observations(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate mappings and return an auditable, unfiltered A/B/C/D report."""
    materialized = list(observations)
    if not materialized:
        raise EvaluationError("at least one observation is required")
    if any(not isinstance(item, Mapping) or isinstance(item, Observation) for item in materialized):
        raise EvaluationError("observations must be plain mappings, not prevalidated objects")
    rows = [Observation.from_mapping(item) for item in materialized]
    by_task: dict[str, list[Observation]] = {}
    for row in rows:
        by_task.setdefault(row.task_id, []).append(row)
    if any(len(task_rows) != 4 for task_rows in by_task.values()):
        raise EvaluationError("each task must have exactly four observations")
    for task_id, task_rows in by_task.items():
        if {row.variant for row in task_rows} != set(VARIANTS):
            raise EvaluationError(f"variant missing or duplicated for task {task_id}")
        first = task_rows[0]
        for row in task_rows[1:]:
            if (row.family, row.leakage_group) != (first.family, first.leakage_group):
                raise EvaluationError(f"task {task_id} has family/leakage roster mismatch")
            for key in (
                "prompt_hash",
                "sampling_hash",
                "reasoning_mode",
                "context_budget",
                "repair_budget",
            ):
                if row.config[key] != first.config[key]:
                    raise EvaluationError(f"task {task_id} has comparable-config mismatch")
    for key in (
        "sampling_hash",
        "reasoning_mode",
        "context_budget",
        "repair_budget",
    ):
        if len({json.dumps(row.config[key], sort_keys=True) for row in rows}) != 1:
            raise EvaluationError(f"mixed comparable configuration for {key}")
    adapter_partition: dict[str, str] = {}
    for key in IDENTITY_KEYS:
        if key == "adapter_hash":
            for enabled in (False, True):
                values = {
                    row.identity[key] for row in rows if row.config["adapter_enabled"] is enabled
                }
                if len(values) != 1:
                    raise EvaluationError("adapter identity partition is missing or mixed")
                adapter_partition["on" if enabled else "off"] = next(iter(values))
            if adapter_partition["off"] == adapter_partition["on"]:
                raise EvaluationError("adapter-off and adapter-on identities must differ")
        elif len({json.dumps(row.identity[key], sort_keys=True) for row in rows}) != 1:
            raise EvaluationError(f"mixed seed/identity for {key}")
    grouped = {
        variant: sorted(
            (row for row in rows if row.variant == variant), key=lambda row: row.task_id
        )
        for variant in VARIANTS
    }
    config_identity = {
        "sampling_hash": first.config["sampling_hash"],
        "reasoning_mode": first.config["reasoning_mode"],
        "context_budget": first.config["context_budget"],
        "repair_budget": first.config["repair_budget"],
        "prompt_roster_hash": _canonical_hash(
            sorted(
                (task_id, task_rows[0].config["prompt_hash"])
                for task_id, task_rows in by_task.items()
            )
        ),
        "variants": {
            variant: {
                key: grouped[variant][0].config[key]
                for key in ("context_enabled", "compiler_loop", "adapter_enabled")
            }
            for variant in VARIANTS
        },
    }
    variants = {variant: _variant_report(grouped[variant]) for variant in VARIANTS}
    paired = {
        "B-A": {
            "first_shot": _paired(grouped["B"], grouped["A"], "first_shot_end_to_end"),
            "post_repair": _paired(grouped["B"], grouped["A"], "post_repair_end_to_end"),
        },
        "C-A": {
            "first_shot": _paired(grouped["C"], grouped["A"], "first_shot_end_to_end"),
            "post_repair": _paired(grouped["C"], grouped["A"], "post_repair_end_to_end"),
        },
        "D-B": {
            "first_shot": _paired(grouped["D"], grouped["B"], "first_shot_end_to_end"),
            "post_repair": _paired(grouped["D"], grouped["B"], "post_repair_end_to_end"),
        },
        "D-C": {
            "first_shot": _paired(grouped["D"], grouped["C"], "first_shot_end_to_end"),
            "post_repair": _paired(grouped["D"], grouped["C"], "post_repair_end_to_end"),
        },
    }
    return {
        "schema_version": 1,
        "status": "complete",
        "all_observations_post_repair_pass": all(row.post_repair_end_to_end for row in rows),
        "prompt_roster_hash": config_identity["prompt_roster_hash"],
        "denominator": {
            "tasks": len(by_task),
            "observations": len(rows),
            "expected_observations": 4 * len(by_task),
            "distinct_task_ids": len(by_task),
            "in": len(rows),
            "out": len(rows),
            "distinct_task": len(by_task),
            "gaps": 0,
            "filtered": 0,
            "conditional": False,
            "policy": "all_tasks_unfiltered",
        },
        "config_identity": config_identity,
        "variants": variants,
        "family_breakdown": {
            variant: variants[variant]["family_breakdown"] for variant in VARIANTS
        },
        "paired_deltas": paired,
        "failure_taxonomy": {
            variant: variants[variant]["failure_taxonomy"] for variant in VARIANTS
        },
        "critical_failures": dict(
            sorted(Counter(failure for row in rows for failure in row.critical_failures).items())
        ),
        "identity_hashes": {
            "shared_identity_hash": _canonical_hash(
                {key: rows[0].identity[key] for key in IDENTITY_KEYS if key != "adapter_hash"}
            ),
            **{key: rows[0].identity[key] for key in IDENTITY_KEYS if key != "adapter_hash"},
            "adapter_hash": adapter_partition,
        },
        "observations": [
            {
                "task_id": row.task_id,
                "family": row.family,
                "variant": row.variant,
                "leakage_group": row.leakage_group,
                "config": row.config,
                "identity": row.identity,
                "evidence": row.evidence,
                "first_shot_success": row.first_shot_success,
                "post_repair_success": row.post_repair_success,
                "first_shot_end_to_end": row.first_shot_end_to_end,
                "post_repair_end_to_end": row.post_repair_end_to_end,
                "repair_cycles": row.repair_cycles,
                "first_shot_outcomes": row.first_shot_outcomes,
                "post_repair_outcomes": row.post_repair_outcomes,
                "tool_failure": row.tool_failure,
                "critical_failures": list(row.critical_failures),
                "failure_category": row.failure_category,
            }
            for row in sorted(rows, key=lambda item: (item.task_id, item.variant))
        ],
    }


evaluate_abcd = evaluate_observations
build_evaluation_report = evaluate_observations
score_abcd = evaluate_observations
evaluate_report = evaluate_observations
build_report = evaluate_observations
TaskObservation = Observation
