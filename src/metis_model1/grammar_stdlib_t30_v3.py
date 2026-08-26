"""Fresh T30-v3 wrapper for the terminal T30-v2 diagnosis.

V3 keeps the pinned grammar, standard-library and evaluator contracts.  Its
only new retrieval instruction is the generic braced multi-attribute rule;
the fresh roster must demonstrate it in at least two independently rooted
F-1 targets.  Configuration is scoped so the sealed V1 engine is restored on
every exit path.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from metis_model1 import grammar_stdlib_t30 as core
from metis_model1 import grammar_stdlib_t30_successor as v2

PROJECT_ROOT = core.PROJECT_ROOT

V1_TASKS_PATH = v2.V1_TASKS_PATH
V1_TRUTH_PATH = v2.V1_TRUTH_PATH
V1_EVALUATION_PATH = v2.V1_EVALUATION_PATH
V2_TASKS_PATH = v2.V2_TASKS_PATH
V2_REFERENCE_PATH = v2.V2_REFERENCE_PATH
V2_POLICY_PATH = v2.V2_POLICY_PATH
V2_TRUTH_PATH = v2.V2_TRUTH_PATH
V2_EVALUATION_PATH = v2.V2_EVIDENCE_PATH
V2_HUMAN_REVIEW_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-human-review-v2.json"
V2_ADJUDICATION_PATH = v2.V2_ADJUDICATION_PATH
V3_TASKS_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json"
V3_REFERENCE_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md"
V3_POLICY_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-policy-v3.json"
V3_TRUTH_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-truth-v3.json"
V3_FREEZE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-freeze-v3.json"
V3_EVIDENCE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-evaluation-v3.json"
V3_ADJUDICATION_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-adjudication-v3.json"
V3_RUN_ID = "t30-v3-20260826"
V3_RUN_RELATIVE = f"artifacts/grammar-stdlib-accuracy/t30/{V3_RUN_ID}"
V3_ATTEMPT_NONCE = "gsl-t30-v3-20260826-attempt-01"
V2_EVALUATION_SHA256 = "sha256:1ca9a340f39b52ed3f813a659dc36bc48b5c96ce1620240b8d8814381cfc4120"
V2_ADJUDICATION_SHA256 = "sha256:43c345ffd8106f7319fdc521280cf9c644299de3db44181e9844d8845f823015"
V2_ADJUDICATION_FILE_SHA256 = (
    "sha256:7bab68c501b35d7ea057f32bbe6be4717487dc412be5d29137a16387407d2034"
)
V3_MULTI_ATTRIBUTE_RULE = (
    "Compact attributes syntax is valid for exactly one assignment; two or more assignments "
    "require a braced attributes group."
)
V3_F1_BRACED_MULTI_ATTRIBUTE_MINIMUM = 2

STDLIB_MODULES = v2.STDLIB_MODULES
INTERACTION_CLASSES = v2.INTERACTION_CLASSES
COVERAGE_FIELDS = v2.COVERAGE_FIELDS
V3_NONCLAIMS = [
    *v2.V2_NONCLAIMS,
    "no_v2_rescore_or_promotion",
    "no_v2_task_message_content_or_target_reuse",
]
V3_POLICY_ROSTER = {
    **deepcopy(v2.V2_POLICY_ROSTER),
    "namespace": "gsl_t30v3",
    "task_id_prefix": "gsl_t30v3_",
    "f1_braced_multi_attribute_targets_minimum": V3_F1_BRACED_MULTI_ATTRIBUTE_MINIMUM,
}
V3_POLICY_COVERAGE_GATE = deepcopy(v2.V2_POLICY_COVERAGE_GATE)
V3_POLICY_COVERAGE_GATE["minimum_successful_occurrences_each"] = 2
V3_FINAL_COVERAGE_GATE_NAMES = deepcopy(v2.V2_FINAL_COVERAGE_GATE_NAMES)
V3_POLICY_EXTRA_CONTRACT = {
    **deepcopy(v2.V2_POLICY_EXTRA_CONTRACT),
    "scope": "fresh_public_synthetic_grammar_stdlib_held_out_v3",
    "roster_id": "gsl_t30_public_synthetic_v3",
    "reference_context": {
        **deepcopy(v2.V2_POLICY_EXTRA_CONTRACT["reference_context"]),
        "path": "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md",
        "generic_multi_attribute_rule": V3_MULTI_ATTRIBUTE_RULE,
    },
    "predecessor": {
        "benchmark_id": "grammar-stdlib-accuracy-t30-v2",
        "evaluation_path": "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json",
        "evaluation_self_sha256": V2_EVALUATION_SHA256,
        "adjudication_path": "manifests/grammar-stdlib-accuracy-t30-adjudication-v2.json",
        "adjudication_self_sha256": V2_ADJUDICATION_SHA256,
        "adjudication_raw_sha256": V2_ADJUDICATION_FILE_SHA256,
        "adjudication_evaluation_self_sha256": V2_EVALUATION_SHA256,
        "adjudication_verdict": "GRAMMAR_STDLIB_T30_V2_DIAGNOSE",
        "disposition": "terminal_diagnosis_no_promotion",
        "rescore_allowed": False,
        "model_replay_allowed": False,
        "task_or_output_reuse_allowed": False,
        "promotion_credit": False,
    },
    "v3_prompt_only_cure": {
        "rule": V3_MULTI_ATTRIBUTE_RULE,
        "f1_braced_multi_attribute_targets_minimum": V3_F1_BRACED_MULTI_ATTRIBUTE_MINIMUM,
        "weights_changed": False,
        "grammar_changed": False,
        "stdlib_changed": False,
        "oracle_changed": False,
    },
}

_REPLACED_BOUND_PATHS = {
    "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v1/t30-reference-context.md",
    "manifests/grammar-stdlib-accuracy-t30-policy-v1.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v1.json",
}
SUCCESSOR_BOUND_PATHS = (
    "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md",
    "manifests/grammar-stdlib-accuracy-t30-policy-v3.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v3.json",
    "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v1.json",
    "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
    "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
    "manifests/grammar-stdlib-accuracy-t30-policy-v2.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v2.json",
    "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json",
    "manifests/grammar-stdlib-accuracy-t30-human-review-v2.json",
    "manifests/grammar-stdlib-accuracy-t30-adjudication-v2.json",
    "src/metis_model1/contracts.py",
    "src/metis_model1/grammar_stdlib_t30_successor.py",
    "src/metis_model1/grammar_stdlib_t30_v3.py",
    "tests/test_contracts.py",
    "tests/test_grammar_stdlib_t30.py",
    "tests/test_grammar_stdlib_t30_successor.py",
    "tests/test_grammar_stdlib_t30_v3.py",
    *(path for path in core.BOUND_PATHS if path not in _REPLACED_BOUND_PATHS),
)

V3_REFERENCE_REQUIRED_MARKERS = {
    *v2.V2_REFERENCE_REQUIRED_MARKERS,
    V3_MULTI_ATTRIBUTE_RULE,
}


def _code_without_strings_or_comments(source: str) -> str:
    """Mask lexical decoys while retaining Metis structural delimiters.

    The pre-truth roster check must not credit an ``=`` inside a string or
    comment as an attributes assignment.  We deliberately fail closed on an
    unterminated quote or block comment rather than trying to recover a
    partial lexical structure.
    """

    result: list[str] = []
    cursor = 0
    while cursor < len(source):
        character = source[cursor]
        if character in {"'", '"'}:
            quote = character
            result.append(" ")
            cursor += 1
            while cursor < len(source):
                current = source[cursor]
                result.append("\n" if current == "\n" else " ")
                cursor += 1
                if current == "\\":
                    if cursor == len(source):
                        raise core.GrammarStdlibT30Error("unterminated escape in T30-v3 target")
                    escaped = source[cursor]
                    result.append("\n" if escaped == "\n" else " ")
                    cursor += 1
                    continue
                if current == quote:
                    break
            else:
                raise core.GrammarStdlibT30Error("unterminated string in T30-v3 target")
            continue
        if source.startswith("//", cursor):
            while cursor < len(source) and source[cursor] != "\n":
                result.append(" ")
                cursor += 1
            continue
        if source.startswith("/*", cursor):
            result.extend((" ", " "))
            cursor += 2
            while cursor < len(source) and not source.startswith("*/", cursor):
                result.append("\n" if source[cursor] == "\n" else " ")
                cursor += 1
            if cursor == len(source):
                raise core.GrammarStdlibT30Error("unterminated block comment in T30-v3 target")
            result.extend((" ", " "))
            cursor += 2
            continue
        result.append(character)
        cursor += 1
    return "".join(result)


def _braced_attribute_assignment_counts(source: str) -> list[int]:
    """Return real top-level assignment counts for every braced attributes group."""

    code = _code_without_strings_or_comments(source)
    counts: list[int] = []
    cursor = 0
    while cursor < len(code):
        if not (code[cursor].isalpha() or code[cursor] == "_"):
            cursor += 1
            continue
        end = cursor + 1
        while end < len(code) and (code[end].isalnum() or code[end] == "_"):
            end += 1
        if code[cursor:end] != "attributes":
            cursor = end
            continue
        group_start = end
        while group_start < len(code) and code[group_start].isspace():
            group_start += 1
        if group_start == len(code) or code[group_start] != "{":
            cursor = end
            continue
        depth = 1
        body = group_start + 1
        assignment_count = 0
        while body < len(code) and depth:
            character = code[body]
            if character == "{":
                depth += 1
                body += 1
                continue
            if character == "}":
                depth -= 1
                body += 1
                continue
            if depth == 1 and (character.isalpha() or character == "_"):
                identifier_end = body + 1
                while identifier_end < len(code) and (
                    code[identifier_end].isalnum() or code[identifier_end] == "_"
                ):
                    identifier_end += 1
                operator = identifier_end
                while operator < len(code) and code[operator].isspace():
                    operator += 1
                if (
                    operator < len(code)
                    and code[operator] == "="
                    and (operator == 0 or code[operator - 1] not in "<>=!")
                    and (operator + 1 == len(code) or code[operator + 1] != "=")
                ):
                    assignment_count += 1
                body = identifier_end
                continue
            body += 1
        if depth:
            raise core.GrammarStdlibT30Error("unterminated attributes group in T30-v3 target")
        counts.append(assignment_count)
        cursor = body
    return counts


def validate_v3_braced_multi_attribute_targets(tasks: list[Mapping[str, Any]]) -> None:
    """Require two fresh F-1 targets that exercise grouped assignments."""

    bracketed = 0
    for task in tasks:
        if task.get("family") != "F-1":
            continue
        target = task.get("expected_source")
        if not isinstance(target, str):
            continue
        if any(count >= 2 for count in _braced_attribute_assignment_counts(target)):
            bracketed += 1
    if bracketed < V3_F1_BRACED_MULTI_ATTRIBUTE_MINIMUM:
        raise core.GrammarStdlibT30Error(
            "T30-v3 requires at least two F-1 braced multi-attribute targets"
        )


_CORE_VALIDATE_TASKS = core.validate_tasks
_CORE_PREDECESSOR_TERMINAL_DIAGNOSIS = core._predecessor_terminal_diagnosis
_CORE_BUILD_TRUTH = core.build_truth


def _validate_v2_terminal_adjudication() -> None:
    """Bind v3 to the final v2 adjudication, not merely its evaluation report."""

    evaluation, evaluation_raw = core._load(V2_EVALUATION_PATH, "T30-v2 terminal evaluation")
    core._self_hash(evaluation, "evaluation_sha256")
    if (
        evaluation.get("evidence_id") != "grammar-stdlib-accuracy-t30-evaluation/v2"
        or evaluation.get("evaluation_sha256") != V2_EVALUATION_SHA256
        or evaluation.get("status") != "verified_local_cooperative"
        or not isinstance(evaluation.get("decision"), Mapping)
        or evaluation["decision"].get("verdict") != "GRAMMAR_STDLIB_T30_V2_DIAGNOSE"
        or evaluation.get("model_outputs_observed") is not True
        or evaluation.get("training_authorized") is not False
        or evaluation.get("delta_qlora_authorized") is not False
    ):
        raise core.GrammarStdlibT30Error("T30-v2 terminal evaluation contract drift")

    adjudication, adjudication_raw = core._load(
        V2_ADJUDICATION_PATH, "T30-v2 terminal adjudication"
    )
    core._self_hash(adjudication, "adjudication_sha256")
    decision = adjudication.get("decision")
    if (
        adjudication.get("adjudication_id") != "grammar-stdlib-accuracy-t30-adjudication/v2"
        or adjudication.get("adjudication_sha256") != V2_ADJUDICATION_SHA256
        or core.raw_hash(adjudication_raw) != V2_ADJUDICATION_FILE_SHA256
        or adjudication.get("schema_version") != 1
        or adjudication.get("status") != "final_local_adjudication"
        or adjudication.get("authority_tier") != "L0_frontier_human_review"
        or adjudication.get("evaluation_sha256") != evaluation["evaluation_sha256"]
        or adjudication.get("evaluation_file_sha256") != core.raw_hash(evaluation_raw)
        or adjudication.get("model_outputs_observed") is not True
        or adjudication.get("training_authorized") is not False
        or adjudication.get("delta_qlora_authorized") is not False
        or adjudication.get("nonclaims") != v2.V2_NONCLAIMS
        or not isinstance(decision, Mapping)
        or decision.get("verdict") != "GRAMMAR_STDLIB_T30_V2_DIAGNOSE"
        or decision.get("training_authorized") is not False
        or decision.get("delta_qlora_authorized") is not False
    ):
        raise core.GrammarStdlibT30Error("T30-v2 terminal adjudication contract drift")


def _predecessor_terminal_diagnosis_v3() -> dict[str, Any] | None:
    """Retain the core receipt shape after validating v2's final closure."""

    predecessor = _CORE_PREDECESSOR_TERMINAL_DIAGNOSIS()
    _validate_v2_terminal_adjudication()
    return predecessor


def _build_truth_v3(metis_root: Path, node_path: Path) -> dict[str, Any]:
    """Reject a broken v2 terminal chain before the core opens an Oracle session."""

    _validate_v2_terminal_adjudication()
    return _CORE_BUILD_TRUTH(metis_root, node_path)


def _validate_tasks_v3(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    tasks = _CORE_VALIDATE_TASKS(manifest)
    validate_v3_braced_multi_attribute_targets(tasks)
    return tasks


_OVERRIDES: dict[str, Any] = {
    "TASKS_PATH": V3_TASKS_PATH,
    "REFERENCE_PATH": V3_REFERENCE_PATH,
    "POLICY_PATH": V3_POLICY_PATH,
    "TRUTH_PATH": V3_TRUTH_PATH,
    "FREEZE_PATH": V3_FREEZE_PATH,
    "EVIDENCE_PATH": V3_EVIDENCE_PATH,
    "ADJUDICATION_PATH": V3_ADJUDICATION_PATH,
    "RUN_ID": V3_RUN_ID,
    "RUN_RELATIVE": V3_RUN_RELATIVE,
    "ATTEMPT_NONCE": V3_ATTEMPT_NONCE,
    "BENCHMARK_ID": "grammar-stdlib-accuracy-t30-v3",
    "POLICY_ID": "grammar-stdlib-accuracy-t30-policy/v3",
    "TRUTH_ID": "grammar-stdlib-accuracy-t30-truth/v3",
    "FREEZE_ID": "grammar-stdlib-accuracy-t30-freeze/v3",
    "EVIDENCE_ID": "grammar-stdlib-accuracy-t30-evaluation/v3",
    "ADJUDICATION_ID": "grammar-stdlib-accuracy-t30-adjudication/v3",
    "HUMAN_REVIEW_ID": "grammar-stdlib-accuracy-t30-human-review/v3",
    "ROSTER_ID": "gsl_t30_public_synthetic_v3",
    "PROVENANCE_NAMESPACE": "gsl_t30v3",
    "TASK_ID_PREFIX": "gsl_t30v3_",
    "FRESHNESS_NAMESPACE": b"gsl_t30v3",
    "_predecessor_terminal_diagnosis": _predecessor_terminal_diagnosis_v3,
    "build_truth": _build_truth_v3,
    "PRE_REVIEW_VERDICT": "GRAMMAR_STDLIB_T30_V3_REVIEW_REQUIRED",
    "PASS_VERDICT": "GRAMMAR_STDLIB_T30_V3_PASS_NO_RETRAIN",
    "DIAGNOSE_VERDICT": "GRAMMAR_STDLIB_T30_V3_DIAGNOSE",
    "F4_REVIEW_CONTRACT": v2.V2_POLICY_EXTRA_CONTRACT["serialization_contracts"]["F-4"]["contract"],
    "F6_REVIEW_CONTRACT": v2.V2_POLICY_EXTRA_CONTRACT["serialization_contracts"]["F-6"]["contract"],
    "STDLIB_MODULES": STDLIB_MODULES,
    "INTERACTION_CLASSES": INTERACTION_CLASSES,
    "COVERAGE_FIELDS": COVERAGE_FIELDS,
    "MODEL_JSON_COVERAGE_FIELDS": ("top_levels", "stdlib_members", "stdlib_settings"),
    "F4_ENDPOINT_SHAPE": "explicit_mode_variants",
    "F6_ALWAYS_CATALOG_FIELDS": True,
    "CATALOG_INLINE_DOMAIN_SUPPORTED": True,
    "REQUIRE_CATALOG_DOMAIN_SIZE": True,
    "STRUCTURAL_FIRST_USE_DEDUP": True,
    "REQUIRE_EXACT_REVIEW_CONTRACT": True,
    "KNOWN_SURFACE_ALIASES_ARE_CONTRACT_MISMATCH": True,
    "CLASSIFY_SOURCE_SYMBOL_FAILURES": True,
    "CONTRACT_MISMATCH_FAILURE_CODE": "contract_mismatch",
    "NONCLAIMS": V3_NONCLAIMS,
    "POLICY_ROSTER": V3_POLICY_ROSTER,
    "POLICY_COVERAGE_GATE": V3_POLICY_COVERAGE_GATE,
    "POLICY_EXTRA_CONTRACT": V3_POLICY_EXTRA_CONTRACT,
    "FINAL_COVERAGE_GATE_NAMES": V3_FINAL_COVERAGE_GATE_NAMES,
    "REFERENCE_HEADING": "# Metis 0.43 grammar and standard-library reference — T30 v3\n",
    "REFERENCE_REQUIRED_MARKERS": V3_REFERENCE_REQUIRED_MARKERS,
    "REFERENCE_FORBIDDEN_MARKERS": {"gsl_t30", "play-prod", "play-demo"},
    "REFERENCE_PROVENANCE_MARKER": (
        "tenant data, a training example, or an answer to any benchmark task"
    ),
    "PREDECESSOR_TERMINAL_EVALUATION": {
        "path": V2_EVALUATION_PATH,
        "relative_path": "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json",
        "evidence_id": "grammar-stdlib-accuracy-t30-evaluation/v2",
        "evaluation_sha256": V2_EVALUATION_SHA256,
        "verdict": "GRAMMAR_STDLIB_T30_V2_DIAGNOSE",
        "disposition": "terminal_diagnosis_no_promotion",
    },
    "ADDITIONAL_FRESHNESS_TASK_PATHS": (V1_TASKS_PATH, V2_TASKS_PATH),
    "ADDITIONAL_FRESHNESS_TRUTH_PATHS": (V1_TRUTH_PATH, V2_TRUTH_PATH),
    "BOUND_PATHS": SUCCESSOR_BOUND_PATHS,
}


@contextlib.contextmanager
def successor_configuration() -> Iterator[None]:
    """Install V3 only within this scope and restore all core state on exit."""

    previous = {name: getattr(core, name) for name in _OVERRIDES}
    previous_validate_tasks = core.validate_tasks
    try:
        for name, value in _OVERRIDES.items():
            setattr(core, name, value)
        core.validate_tasks = _validate_tasks_v3
        yield
    finally:
        core.validate_tasks = previous_validate_tasks
        for name, value in previous.items():
            setattr(core, name, value)


def main(argv: list[str] | None = None) -> int:
    with successor_configuration():
        return core.main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
