"""Fresh T30-v2 successor for the terminal T30-v1 benchmark diagnosis.

The successor retains the audited T30 engine, model/runtime identities and
gates while installing a fully explicit grammar/stdlib serialization contract,
fresh task namespace and additional successful-task coverage denominators.
Configuration is scoped and V1 globals are restored on every exit path.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from metis_model1 import grammar_stdlib_t30 as core

PROJECT_ROOT = core.PROJECT_ROOT
V1_TASKS_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json"
V1_TRUTH_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-truth-v1.json"
V1_EVALUATION_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json"
V2_TASKS_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json"
V2_REFERENCE_PATH = PROJECT_ROOT / "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md"
V2_POLICY_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-policy-v2.json"
V2_TRUTH_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-truth-v2.json"
V2_FREEZE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-freeze-v2.json"
V2_EVIDENCE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json"
V2_ADJUDICATION_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-t30-adjudication-v2.json"
V2_RUN_ID = "t30-v2-20260825"
V2_RUN_RELATIVE = f"artifacts/grammar-stdlib-accuracy/t30/{V2_RUN_ID}"

STDLIB_MODULES = {"time", "codec", "text"}
INTERACTION_CLASSES = {
    "ambient-valid-needs-time",
    "ambient-invalid-std-namespace",
    "ambient-missing-needs",
    "pure-valid-no-needs",
    "pure-invalid-needs",
    "unknown-stdlib-module",
    "unknown-stdlib-member",
    "unknown-needs-capability",
    "timezone-setting-valid",
    "timezone-setting-invalid-key",
}
COVERAGE_FIELDS = (
    "top_levels",
    "stdlib_modules",
    "stdlib_members",
    "stdlib_settings",
    "interaction_classes",
)
V2_NONCLAIMS = [
    "not_accuracy99",
    "not_population_accuracy",
    "not_tenant_or_live_data_accuracy",
    "not_training_data",
    "no_training_authority",
    "no_delta_qlora_authority",
    "no_dataset_authority",
    "no_promotion_authority",
    "no_v1_rescore_or_promotion",
    "no_companion_vscode_or_windows_claim",
]

V2_POLICY_ROSTER = {
    "tasks": 30,
    "tasks_per_family": 5,
    "automatic_tasks": 20,
    "human_review_task_ids_expected": 15,
    "human_review_families": ["F-2", "F-5", "F-6"],
    "namespace": "gsl_t30v2",
    "task_id_prefix": "gsl_t30v2_",
    "top_levels_required": 10,
    "stdlib_modules_required": 3,
    "stdlib_members_required": 12,
    "stdlib_settings_required": 1,
    "interaction_classes_required": 10,
    "rare_or_critical_construct_min_occurrences": 2,
    "catalog_domain_family_reservations": ["F-1", "F-6"],
}
V2_POLICY_COVERAGE_GATE = {
    "credit_source": "final_successful_tasks_only",
    "declared_metadata_alone_is_ineligible": True,
    "failed_task_coverage_is_ineligible": True,
    "minimum_successful_occurrences_each": 1,
    "observed_union_must_equal_required_set": True,
    "top_levels": [
        "Tenant",
        "Catalog",
        "Property",
        "Endpoint",
        "Preset",
        "List",
        "Transformer",
        "NamedBlock",
        "SettingsDecl",
        "ValueSet",
    ],
    "stdlib_modules": ["time", "codec", "text"],
    "stdlib_members": [
        "time.now",
        "time.month",
        "time.day",
        "time.hour",
        "time.hhmm",
        "time.weekday",
        "time.fractional_second",
        "codec.decode",
        "codec.encode",
        "text.slugify",
        "text.truncate",
        "text.normalize",
    ],
    "stdlib_settings": ["time.timezone"],
    "interaction_classes": [
        "ambient-valid-needs-time",
        "ambient-invalid-std-namespace",
        "ambient-missing-needs",
        "pure-valid-no-needs",
        "pure-invalid-needs",
        "unknown-stdlib-module",
        "unknown-stdlib-member",
        "unknown-needs-capability",
        "timezone-setting-valid",
        "timezone-setting-invalid-key",
    ],
    "timezone_setting_invalid_key_input_semantics": (
        "parser_valid_warning_only_allowed_under_pin_then_repaired_to_warning_free_time.timezone"
    ),
}
V2_FINAL_COVERAGE_GATE_NAMES = {
    "top_levels": "coverage_all_10_top_levels",
    "stdlib_modules": "coverage_all_3_stdlib_modules",
    "stdlib_members": "coverage_all_12_stdlib_members",
    "stdlib_settings": "coverage_time_timezone",
    "interaction_classes": "coverage_all_10_interaction_classes",
}
V2_POLICY_EXTRA_CONTRACT = {
    "scope": "fresh_public_synthetic_grammar_stdlib_held_out_v2",
    "roster_id": "gsl_t30_public_synthetic_v2",
    "reference_context": {
        "path": "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
        "generic_only": True,
        "grammar_top_levels": 10,
        "stdlib_modules": 3,
        "stdlib_members": 12,
        "stdlib_settings": 1,
        "task_answers_present": False,
        "tenant_or_live_data_present": False,
    },
    "predecessor": {
        "benchmark_id": "grammar-stdlib-accuracy-t30-v1",
        "evaluation_path": "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
        "evaluation_self_sha256": (
            "sha256:e6e4d4d015c8086203c81a69800a3a14c136c01d3c66304d99df74b84349f0ac"
        ),
        "disposition": "terminal_diagnosis_no_promotion",
        "rescore_allowed": False,
        "model_replay_allowed": False,
        "task_or_output_reuse_allowed": False,
        "promotion_credit": False,
    },
    "serialization_contracts": {
        "surface_to_ast": {
            "tenant": "Tenant",
            "catalog": "Catalog",
            "property": "Property",
            "endpoint": "Endpoint",
            "preset": "Preset",
            "list": "List",
            "transformer": "Transformer",
            "block": "NamedBlock",
            "settings": "SettingsDecl",
            "values": "ValueSet",
        },
        "stdlib_registry_id_normalization": {
            "ambient": "time.member_to_time.member",
            "pure": "std.module.member_to_module.member",
        },
        "named_block_traversal": "recursive_source_preorder_exact_item_first_use_dedup",
        "array_order": "recursive_source_preorder_exact_item_first_use_dedup",
        "F-4": {
            "contract": "metis-source-review/v1",
            "root_keys": [
                "contract",
                "status",
                "top_levels",
                "stdlib_members",
                "stdlib_settings",
                "endpoint",
            ],
            "endpoint_keys": ["count", "mode", "requested", "selected", "variants"],
            "endpoint_modes": ["source", "endpoint"],
            "requested_semantics": "oracle_request_target_or_null_in_source_mode",
            "selected_semantics": "compiler_selected_target_or_null_in_source_mode",
            "variants_always_array": True,
        },
        "F-6": {
            "contract": "metis-structural-explanation/v2",
            "root_keys": [
                "contract",
                "top_levels",
                "declarations",
                "catalog_fields",
                "stdlib_members",
                "stdlib_settings",
                "relationships",
            ],
            "catalog_fields_always_array": True,
            "catalog_field_domains": ["implicit", "inline", "external-enum", "open"],
            "catalog_field_size_required_for": ["inline", "external-enum"],
            "catalog_field_literal_values_serialized": False,
            "relationship_cardinality": "each_label_at_most_once",
            "relationship_order": (
                "top_level_source_order_then_ratified_within_declaration_tie_order"
            ),
        },
    },
    "symbol_classification": {
        "known_surface_alias_in_json": {
            "examples": [
                "endpoint_instead_of_Endpoint",
                "std.codec.decode_instead_of_codec.decode",
            ],
            "failure_code": "contract_mismatch",
            "invented_symbol": False,
        },
        "known_symbol_wrong_nature": {
            "examples": ["std.time.now", "needs codec", "needs text"],
            "failure_code": "stdlib_nature_mismatch",
            "invented_symbol": False,
            "critical": True,
        },
        "missing_ambient_capability": {
            "example": "time.hour_without_needs_time",
            "failure_code": "ambient_capability_mismatch",
            "invented_symbol": False,
            "critical": True,
        },
        "unknown_pinned_identity": {
            "applies_to": [
                "grammar_ast_label",
                "stdlib_module",
                "stdlib_member",
                "stdlib_setting",
                "needs_capability",
            ],
            "failure_code": "invented_symbol",
            "invented_symbol": True,
            "critical": True,
        },
    },
}

_REPLACED_BOUND_PATHS = {
    "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v1/t30-reference-context.md",
    "manifests/grammar-stdlib-accuracy-t30-policy-v1.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v1.json",
}
SUCCESSOR_BOUND_PATHS = (
    "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
    "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
    "manifests/grammar-stdlib-accuracy-t30-policy-v2.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v2.json",
    "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
    "manifests/grammar-stdlib-accuracy-t30-truth-v1.json",
    "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
    "src/metis_model1/grammar_stdlib_t30_successor.py",
    "tests/test_grammar_stdlib_t30.py",
    "tests/test_grammar_stdlib_t30_successor.py",
    *(path for path in core.BOUND_PATHS if path not in _REPLACED_BOUND_PATHS),
)

V2_REFERENCE_REQUIRED_MARKERS = {
    "Canonical top-level vocabulary",
    "`Tenant`",
    "`Catalog`",
    "`Property`",
    "`Endpoint`",
    "`Preset`",
    "`List`",
    "`Transformer`",
    "`NamedBlock`",
    "`SettingsDecl`",
    "`ValueSet`",
    "time.now",
    "time.month",
    "time.day",
    "time.hour",
    "time.hhmm",
    "time.weekday",
    "time.fractional_second",
    "time.timezone",
    "std.codec.decode",
    "std.codec.encode",
    "std.text.slugify",
    "std.text.truncate",
    "std.text.normalize",
    "metis-source-review/v1",
    "metis-structural-explanation/v2",
    "ambient-invalid-std-namespace",
    "pure-invalid-needs",
    "unknown-stdlib-module",
    "unknown-stdlib-member",
    "unknown-needs-capability",
    "timezone-setting-invalid-key",
}

_OVERRIDES: dict[str, Any] = {
    "TASKS_PATH": V2_TASKS_PATH,
    "REFERENCE_PATH": V2_REFERENCE_PATH,
    "POLICY_PATH": V2_POLICY_PATH,
    "TRUTH_PATH": V2_TRUTH_PATH,
    "FREEZE_PATH": V2_FREEZE_PATH,
    "EVIDENCE_PATH": V2_EVIDENCE_PATH,
    "ADJUDICATION_PATH": V2_ADJUDICATION_PATH,
    "RUN_ID": V2_RUN_ID,
    "RUN_RELATIVE": V2_RUN_RELATIVE,
    "ATTEMPT_NONCE": "gsl-t30-v2-20260825-attempt-01",
    "BENCHMARK_ID": "grammar-stdlib-accuracy-t30-v2",
    "POLICY_ID": "grammar-stdlib-accuracy-t30-policy/v2",
    "TRUTH_ID": "grammar-stdlib-accuracy-t30-truth/v2",
    "FREEZE_ID": "grammar-stdlib-accuracy-t30-freeze/v2",
    "EVIDENCE_ID": "grammar-stdlib-accuracy-t30-evaluation/v2",
    "ADJUDICATION_ID": "grammar-stdlib-accuracy-t30-adjudication/v2",
    "HUMAN_REVIEW_ID": "grammar-stdlib-accuracy-t30-human-review/v2",
    "ROSTER_ID": "gsl_t30_public_synthetic_v2",
    "PROVENANCE_NAMESPACE": "gsl_t30v2",
    "TASK_ID_PREFIX": "gsl_t30v2_",
    "FRESHNESS_NAMESPACE": b"gsl_t30v2",
    "PRE_REVIEW_VERDICT": "GRAMMAR_STDLIB_T30_V2_REVIEW_REQUIRED",
    "PASS_VERDICT": "GRAMMAR_STDLIB_T30_V2_PASS_NO_RETRAIN",
    "DIAGNOSE_VERDICT": "GRAMMAR_STDLIB_T30_V2_DIAGNOSE",
    "F4_REVIEW_CONTRACT": "metis-source-review/v1",
    "F6_REVIEW_CONTRACT": "metis-structural-explanation/v2",
    "STDLIB_MODULES": STDLIB_MODULES,
    "INTERACTION_CLASSES": INTERACTION_CLASSES,
    "COVERAGE_FIELDS": COVERAGE_FIELDS,
    "MODEL_JSON_COVERAGE_FIELDS": (
        "top_levels",
        "stdlib_members",
        "stdlib_settings",
    ),
    "F4_ENDPOINT_SHAPE": "explicit_mode_variants",
    "F6_ALWAYS_CATALOG_FIELDS": True,
    "CATALOG_INLINE_DOMAIN_SUPPORTED": True,
    "REQUIRE_CATALOG_DOMAIN_SIZE": True,
    "STRUCTURAL_FIRST_USE_DEDUP": True,
    "REQUIRE_EXACT_REVIEW_CONTRACT": True,
    "KNOWN_SURFACE_ALIASES_ARE_CONTRACT_MISMATCH": True,
    "CLASSIFY_SOURCE_SYMBOL_FAILURES": True,
    "CONTRACT_MISMATCH_FAILURE_CODE": "contract_mismatch",
    "NONCLAIMS": V2_NONCLAIMS,
    "POLICY_ROSTER": V2_POLICY_ROSTER,
    "POLICY_COVERAGE_GATE": V2_POLICY_COVERAGE_GATE,
    "POLICY_EXTRA_CONTRACT": V2_POLICY_EXTRA_CONTRACT,
    "FINAL_COVERAGE_GATE_NAMES": V2_FINAL_COVERAGE_GATE_NAMES,
    "REFERENCE_HEADING": ("# Metis 0.43 grammar and standard-library reference — T30 v2\n"),
    "REFERENCE_REQUIRED_MARKERS": V2_REFERENCE_REQUIRED_MARKERS,
    "REFERENCE_FORBIDDEN_MARKERS": {"gsl_t30", "play-prod", "play-demo"},
    "REFERENCE_PROVENANCE_MARKER": (
        "tenant data, a training example, or an answer to any benchmark task"
    ),
    "PREDECESSOR_TERMINAL_EVALUATION": {
        "path": V1_EVALUATION_PATH,
        "relative_path": "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
        "evidence_id": "grammar-stdlib-accuracy-t30-evaluation/v1",
        "evaluation_sha256": (
            "sha256:e6e4d4d015c8086203c81a69800a3a14c136c01d3c66304d99df74b84349f0ac"
        ),
        "verdict": "GRAMMAR_STDLIB_T30_DIAGNOSE",
        "disposition": "terminal_diagnosis_no_promotion",
    },
    "ADDITIONAL_FRESHNESS_TASK_PATHS": (V1_TASKS_PATH,),
    "ADDITIONAL_FRESHNESS_TRUTH_PATHS": (V1_TRUTH_PATH,),
    "BOUND_PATHS": SUCCESSOR_BOUND_PATHS,
}


@contextlib.contextmanager
def successor_configuration() -> Iterator[None]:
    """Install the complete V2 contract and restore V1 on every exit path."""

    previous = {name: getattr(core, name) for name in _OVERRIDES}
    try:
        for name, value in _OVERRIDES.items():
            setattr(core, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(core, name, value)


def main(argv: list[str] | None = None) -> int:
    with successor_configuration():
        return core.main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
