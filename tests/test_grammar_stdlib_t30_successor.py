"""Synthetic contracts for the fresh grammar/stdlib T30-v2 wrapper."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from metis_model1 import grammar_stdlib_t30 as core
from metis_model1 import grammar_stdlib_t30_successor as successor


def _v2_observations() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    _manifest, tasks, _raw = core.load_tasks()
    rows: list[dict[str, object]] = []
    for task in tasks:
        automatic = task["family"] in {"F-1", "F-2", "F-3", "F-4"}
        rows.append(
            {
                "task_id": task["task_id"],
                "family": task["family"],
                "task_mode": task["task_mode"],
                "authority_tier": task["authority_tier"],
                "independent_root": task["provenance_roots"]["independent"],
                "mechanical_match": True,
                "semantic_correct": True if automatic else None,
                "final_human_review_required": task["family"] in core.FINAL_HUMAN_REVIEW,
                "final_human_review_kind": core.FINAL_HUMAN_REVIEW.get(task["family"]),
                "critical_failure": False,
                "failure_code": None,
                "candidate_sha256": core.canonical_hash(task["task_id"]),
                "observed": None,
                "observed_coverage": deepcopy(task["coverage"]),
                "peak_metal_gb": 1.0,
            }
        )
    return deepcopy(rows), rows


def test_successor_configuration_is_complete_and_restores_v1() -> None:
    before = {name: getattr(core, name) for name in successor._OVERRIDES}

    with successor.successor_configuration():
        assert core.BENCHMARK_ID == "grammar-stdlib-accuracy-t30-v2"
        assert core.ROSTER_ID == "gsl_t30_public_synthetic_v2"
        assert core.TASK_ID_PREFIX == "gsl_t30v2_"
        assert core.RUN_ID == "t30-v2-20260825"
        assert core.ATTEMPT_NONCE == "gsl-t30-v2-20260825-attempt-01"
        assert core.PRE_REVIEW_VERDICT == "GRAMMAR_STDLIB_T30_V2_REVIEW_REQUIRED"
        assert core.PASS_VERDICT == "GRAMMAR_STDLIB_T30_V2_PASS_NO_RETRAIN"
        assert core.DIAGNOSE_VERDICT == "GRAMMAR_STDLIB_T30_V2_DIAGNOSE"
        assert core.COVERAGE_FIELDS == successor.COVERAGE_FIELDS
        assert {"time", "codec", "text"} == core.STDLIB_MODULES
        assert len(core.INTERACTION_CLASSES) == 10
        assert core.CONTRACT_MISMATCH_FAILURE_CODE == "contract_mismatch"

    assert {name: getattr(core, name) for name in successor._OVERRIDES} == before


def test_successor_roster_policy_reference_and_terminal_predecessor_are_bound() -> None:
    with successor.successor_configuration():
        policy, _policy_raw = core._policy()
        _manifest, tasks, _tasks_raw = core.load_tasks()
        reference, _reference_raw = core._reference_context()
        predecessor = core._predecessor_terminal_diagnosis()

    assert policy["policy_id"] == "grammar-stdlib-accuracy-t30-policy/v2"
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 30
    assert all(task["task_id"].startswith("gsl_t30v2_") for task in tasks)
    assert reference.startswith("# Metis 0.43 grammar and standard-library reference — T30 v2\n")
    assert predecessor is not None
    assert predecessor["verdict"] == "GRAMMAR_STDLIB_T30_DIAGNOSE"
    assert predecessor["disposition"] == "terminal_diagnosis_no_promotion"
    assert predecessor["evaluation_sha256"].startswith("sha256:")


def test_successor_binds_engine_wrapper_tests_and_v1_terminal_evidence() -> None:
    required = {
        "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v2/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-truth-v2.json",
        "fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json",
        "manifests/grammar-stdlib-accuracy-t30-truth-v1.json",
        "manifests/grammar-stdlib-accuracy-t30-evaluation-v1.json",
        "src/metis_model1/grammar_stdlib_t30.py",
        "src/metis_model1/grammar_stdlib_t30_successor.py",
        "tests/test_grammar_stdlib_t30.py",
        "tests/test_grammar_stdlib_t30_successor.py",
    }

    assert required.issubset(successor.SUCCESSOR_BOUND_PATHS)
    assert len(successor.SUCCESSOR_BOUND_PATHS) == len(set(successor.SUCCESSOR_BOUND_PATHS))
    assert "manifests/grammar-stdlib-accuracy-t30-policy-v1.json" not in (
        successor.SUCCESSOR_BOUND_PATHS
    )


def test_terminal_predecessor_mutation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    value = json.loads(successor.V1_EVALUATION_PATH.read_text(encoding="utf-8"))
    forged = deepcopy(value)
    forged["decision"]["verdict"] = "GRAMMAR_STDLIB_T30_PASS_NO_RETRAIN"
    forged["evaluation_sha256"] = core.canonical_hash(
        {key: item for key, item in forged.items() if key != "evaluation_sha256"}
    )
    raw = (json.dumps(forged, allow_nan=False, sort_keys=True) + "\n").encode()

    with successor.successor_configuration():
        monkeypatch.setattr(core, "_load", lambda *_args: (forged, raw))
        with pytest.raises(core.GrammarStdlibT30Error, match="terminal diagnosis"):
            core._predecessor_terminal_diagnosis()


def test_known_surface_alias_is_noncritical_but_unknown_identity_is_critical() -> None:
    with successor.successor_configuration():
        _manifest, tasks, _raw = core.load_tasks()
        task = next(row for row in tasks if row["task_id"] == "gsl_t30v2_f4_03")
        known_alias = deepcopy(task["expected_json"])
        known_alias["top_levels"] = ["transformer"]
        known_alias["stdlib_members"] = [
            "std.codec.encode",
            "std.text.truncate",
            "std.text.normalize",
        ]
        assert core._review_json_contract_failure(task, known_alias) == "contract_mismatch"
        observation = core.score_candidate(
            task,
            {
                "text": json.dumps(known_alias),
                "peak_metal_gb": 1.0,
            },
            {"target": {"expected_json_sha256": core.canonical_hash(task["expected_json"])}},
            successor.PROJECT_ROOT,
            successor.PROJECT_ROOT,
        )
        assert observation["failure_code"] == "contract_mismatch"
        assert observation["critical_failure"] is False

        unknown = deepcopy(task["expected_json"])
        unknown["top_levels"] = ["ImaginaryDeclaration"]
        assert core._review_json_contract_failure(task, unknown) == "invented_symbol"


def test_ambient_std_prefix_is_critical_nature_mismatch_not_invented() -> None:
    with successor.successor_configuration():
        _manifest, tasks, _raw = core.load_tasks()
        task = next(row for row in tasks if row["task_id"] == "gsl_t30v2_f4_01")
        wrong_nature = deepcopy(task["expected_json"])
        wrong_nature["stdlib_members"][0] = "std.time.month"
        assert core._review_json_contract_failure(task, wrong_nature) == "stdlib_nature_mismatch"
        observation = core.score_candidate(
            task,
            {"text": json.dumps(wrong_nature), "peak_metal_gb": 1.0},
            {"target": {"expected_json_sha256": core.canonical_hash(task["expected_json"])}},
            successor.PROJECT_ROOT,
            successor.PROJECT_ROOT,
        )
        assert observation["failure_code"] == "stdlib_nature_mismatch"
        assert observation["critical_failure"] is True

        unknown = deepcopy(task["expected_json"])
        unknown["stdlib_members"][0] = "time.moonphase"
        assert core._review_json_contract_failure(task, unknown) == "invented_symbol"


def test_v2_source_symbol_failures_are_specific_with_generic_oracle_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_oracle(**_kwargs):
        raise core.oracle.GrammarStdlibOracleError("synthetic unavailable oracle")

    monkeypatch.setattr(core.oracle, "grammar_stdlib_oracle_session", unavailable_oracle)
    classified = (
        (
            "metis 0.43\ntransformer heldout { set value = std.time.now() }",
            "stdlib_nature_mismatch",
        ),
        (
            'metis 0.43\nendpoint heldout as "ref" { needs codec }',
            "stdlib_nature_mismatch",
        ),
        (
            "metis 0.43\nproperty heldout { needs text }",
            "stdlib_nature_mismatch",
        ),
        (
            'metis 0.43\nendpoint heldout as "ref" { attributes active = time.now exists }',
            "ambient_capability_mismatch",
        ),
        (
            "metis 0.43\ntransformer heldout { set value = std.math.abs(1) }",
            "invented_symbol",
        ),
        (
            'metis 0.43\ntransformer heldout { set value = std.codec.rot13("x") }',
            "invented_symbol",
        ),
        (
            "metis 0.43\nproperty heldout { needs weather }",
            "invented_symbol",
        ),
        (
            'metis 0.43\nsettings heldout.time { zone "UTC" }',
            "invented_symbol",
        ),
    )

    assert core.CLASSIFY_SOURCE_SYMBOL_FAILURES is False
    with successor.successor_configuration():
        _manifest, tasks, _raw = core.load_tasks()
        task = next(row for row in tasks if row["task_id"] == "gsl_t30v2_f2_02")
        assert core.CLASSIFY_SOURCE_SYMBOL_FAILURES is True
        for source, expected_failure in classified:
            assert core._source_symbol_failure(source) == expected_failure
            observation = core.score_candidate(
                task,
                {"text": source, "peak_metal_gb": 1.0},
                {"target": {"expected": None}},
                successor.PROJECT_ROOT,
                successor.PROJECT_ROOT,
            )
            assert observation["failure_code"] == expected_failure
            assert observation["critical_failure"] is True

        assert (
            core._source_symbol_failure('metis 0.43\nsettings heldout.time { timezone "UTC" }')
            is None
        )
        for task_id in ("gsl_t30v2_f2_04", "gsl_t30v2_f3_05"):
            warning_task = next(row for row in tasks if row["task_id"] == task_id)
            unrepaired = core.score_candidate(
                warning_task,
                {"text": warning_task["before_source"], "peak_metal_gb": 1.0},
                {"target": {"expected": None}},
                successor.PROJECT_ROOT,
                successor.PROJECT_ROOT,
            )
            assert unrepaired["failure_code"] == "invented_symbol"
            assert unrepaired["critical_failure"] is True
            assert core._source_symbol_failure(warning_task["expected_repaired_source"]) is None

        generic = core.score_candidate(
            task,
            {"text": "metis 0.43\nendpoint heldout {", "peak_metal_gb": 1.0},
            {"target": {"expected": None}},
            successor.PROJECT_ROOT,
            successor.PROJECT_ROOT,
        )
        assert generic["failure_code"] == "grammar_stdlib_oracle_rejected_candidate"
        assert generic["critical_failure"] is True
    assert core.CLASSIFY_SOURCE_SYMBOL_FAILURES is False


def test_v2_json_duplicates_and_endpoint_type_are_contract_mismatches() -> None:
    with successor.successor_configuration():
        _manifest, tasks, _raw = core.load_tasks()
        task = next(row for row in tasks if row["task_id"] == "gsl_t30v2_f4_04")

        duplicate_coverage = deepcopy(task["expected_json"])
        duplicate_coverage["top_levels"].append(duplicate_coverage["top_levels"][0])
        assert core._review_json_contract_failure(task, duplicate_coverage) == "contract_mismatch"

        duplicate_variant = deepcopy(task["expected_json"])
        duplicate_variant["endpoint"]["variants"].append(
            duplicate_variant["endpoint"]["variants"][0]
        )
        assert core._review_json_contract_failure(task, duplicate_variant) == "contract_mismatch"

        wrong_count_type = deepcopy(task["expected_json"])
        wrong_count_type["endpoint"]["count"] = "1"
        assert core._review_json_contract_failure(task, wrong_count_type) == "contract_mismatch"

        wrong_array_order = deepcopy(task["expected_json"])
        wrong_array_order["top_levels"].reverse()
        assert core._review_json_contract_failure(task, wrong_array_order) == "contract_mismatch"


def test_known_source_name_in_wrong_f4_slot_is_contract_mismatch_not_invented() -> None:
    with successor.successor_configuration():
        _manifest, tasks, _raw = core.load_tasks()
        task = next(row for row in tasks if row["task_id"] == "gsl_t30v2_f4_01")
        known_source_name = deepcopy(task["expected_json"])
        known_source_name["endpoint"]["selected"] = "t30v2_review_sunrise_ref"
        assert core._review_json_contract_failure(task, known_source_name) == "contract_mismatch"

        truly_unknown = deepcopy(task["expected_json"])
        truly_unknown["endpoint"]["selected"] = "gsl_t30v2_never_seen"
        assert core._review_json_contract_failure(task, truly_unknown) == "invented_symbol"


def test_setting_only_inventory_derives_time_module() -> None:
    inventory = {
        "$type": "Model",
        "elements": [
            {
                "$type": "SettingsDecl",
                "name": "gsl_t30v2_setting_only.time",
                "items": [
                    {
                        "$type": "SettingsPair",
                        "key": "timezone",
                        "value": "UTC",
                    }
                ],
            }
        ],
    }

    with successor.successor_configuration():
        coverage = core._coverage_from_inventory(inventory)

    assert coverage["stdlib_modules"] == ["time"]
    assert coverage["stdlib_members"] == []
    assert coverage["stdlib_settings"] == ["time.timezone"]


def test_v2_f4_contract_has_explicit_mode_and_variants_without_coverage_extras() -> None:
    task = {
        "oracle": {"mode": "endpoint", "target": "heldout"},
        "coverage": {
            "top_levels": ["Endpoint"],
            "stdlib_modules": [],
            "stdlib_members": [],
            "stdlib_settings": [],
            "interaction_classes": [],
        },
    }
    envelope = {
        "result": {
            "status": "ok",
            "endpoint": {"count": 1, "name": "heldout"},
            "ast": {
                "inventory": {
                    "$type": "Model",
                    "elements": [
                        {
                            "$type": "Endpoint",
                            "name": "heldout",
                            "members": [
                                {"$type": "VariantDecl", "name": "compact"},
                                {"$type": "VariantDecl", "name": "compact"},
                                {"$type": "VariantDecl", "name": "expanded"},
                            ],
                        }
                    ],
                }
            },
        }
    }
    with pytest.raises(core.GrammarStdlibT30Error, match="ambiguous variants"):
        core._f4_review_target(task, envelope)

    with successor.successor_configuration():
        result = core._f4_review_target(task, envelope)

    assert list(result) == [
        "contract",
        "status",
        "top_levels",
        "stdlib_members",
        "stdlib_settings",
        "endpoint",
    ]
    assert result["endpoint"] == {
        "count": 1,
        "mode": "endpoint",
        "requested": "heldout",
        "selected": "heldout",
        "variants": ["compact", "expanded"],
    }
    assert "stdlib_modules" not in result and "interaction_classes" not in result


def test_v2_f4_source_mode_forces_null_selection_from_non_null_envelope() -> None:
    task = {
        "oracle": {"mode": "source"},
        "coverage": {
            "top_levels": ["Endpoint"],
            "stdlib_modules": [],
            "stdlib_members": [],
            "stdlib_settings": [],
            "interaction_classes": [],
        },
    }
    envelope = {
        "result": {
            "status": "ok",
            "endpoint": {"count": 1, "name": "must_not_be_selected"},
            "ast": {
                "inventory": {
                    "$type": "Model",
                    "elements": [{"$type": "Endpoint", "name": "must_not_be_selected"}],
                }
            },
        }
    }

    with successor.successor_configuration():
        result = core._f4_review_target(task, envelope)

    assert result["endpoint"] == {
        "count": 1,
        "mode": "source",
        "requested": None,
        "selected": None,
        "variants": [],
    }


def test_v2_structural_records_use_exact_first_use_dedup_only_in_successor() -> None:
    catalog = {
        "$type": "Catalog",
        "name": "heldout.catalog",
        "fields": [{"$type": "Field", "name": "availability"}],
    }
    inventory = {"$type": "Model", "elements": [catalog, deepcopy(catalog)]}

    assert core._declarations_from_inventory(inventory) == [
        {"kind": "Catalog", "name": "heldout.catalog"},
        {"kind": "Catalog", "name": "heldout.catalog"},
    ]
    assert core._catalog_fields(inventory) == [
        {"name": "availability", "domain": "implicit"},
        {"name": "availability", "domain": "implicit"},
    ]

    with successor.successor_configuration():
        declarations = core._declarations_from_inventory(inventory)
        fields = core._catalog_fields(inventory)

    assert declarations == [{"kind": "Catalog", "name": "heldout.catalog"}]
    assert fields == [{"name": "availability", "domain": "implicit"}]


def test_v2_f6_inline_domain_reports_only_kind_and_size() -> None:
    inventory = {
        "$type": "Model",
        "elements": [
            {
                "$type": "Catalog",
                "name": "heldout.catalog",
                "fields": [
                    {
                        "$type": "Field",
                        "name": "availability",
                        "values": {
                            "$type": "InlineValues",
                            "items": ["private-a", "private-b"],
                        },
                    }
                ],
            }
        ],
    }
    task = {
        "expected_json": {"catalog_fields": []},
        "coverage": {
            "top_levels": ["Catalog"],
            "stdlib_modules": [],
            "stdlib_members": [],
            "stdlib_settings": [],
            "interaction_classes": [],
        },
    }
    envelope = {"result": {"ast": {"inventory": inventory}}}

    with successor.successor_configuration():
        result = core._f6_review_target(task, envelope)

    assert result["catalog_fields"] == [{"name": "availability", "domain": "inline", "size": 2}]
    assert "private-a" not in json.dumps(result)


def test_v2_f6_external_enum_requires_a_pinned_integer_size() -> None:
    inventory = {
        "$type": "Model",
        "elements": [
            {
                "$type": "Catalog",
                "name": "heldout.catalog",
                "fields": [
                    {
                        "$type": "Field",
                        "name": "availability",
                        "values": {"$type": "EnumMarker"},
                    }
                ],
            }
        ],
    }

    with (
        successor.successor_configuration(),
        pytest.raises(core.GrammarStdlibT30Error, match="enum size"),
    ):
        core._catalog_fields(inventory)


def test_warning_only_timezone_truth_requires_marker_then_warning_free_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostics: list[object] = [
        {"severity": "warning", "message": "Setting sconosciuta `tz` nel gruppo `time`"}
    ]

    def oracle_task(*_args, **_kwargs):
        return {
            "result": {
                "status": "ok",
                "diagnostics": {"all": diagnostics},
                "ast": {"inventory": {"$type": "Model", "elements": []}},
                "endpoint": {"count": 0, "name": None},
            }
        }

    monkeypatch.setattr(core.d18, "_oracle_task", oracle_task)
    monkeypatch.setattr(core.d18, "_oracle_signature", lambda *_args: {"status": "ok"})
    task = {"task_id": "gsl_t30v2_warning"}

    with successor.successor_configuration():
        signature, _envelope = core._validate_source_envelope(
            task,
            'metis 0.43\nsettings heldout.time { tz "UTC" }',
            successor.PROJECT_ROOT,
            successor.PROJECT_ROOT,
            object(),  # type: ignore[arg-type]
            expected_ok=True,
            expected_diagnostic_markers=("Setting sconosciuta `tz`",),
        )
        assert signature == {"status": "ok"}
        with pytest.raises(core.GrammarStdlibT30Error, match="retains diagnostics"):
            core._validate_source_envelope(
                task,
                'metis 0.43\nsettings heldout.time { timezone "UTC" }',
                successor.PROJECT_ROOT,
                successor.PROJECT_ROOT,
                object(),  # type: ignore[arg-type]
                expected_ok=True,
                require_no_diagnostics=True,
            )
        diagnostics.clear()
        repaired, _envelope = core._validate_source_envelope(
            task,
            'metis 0.43\nsettings heldout.time { timezone "UTC" }',
            successor.PROJECT_ROOT,
            successor.PROJECT_ROOT,
            object(),  # type: ignore[arg-type]
            expected_ok=True,
            require_no_diagnostics=True,
        )
        assert repaired == {"status": "ok"}


def test_v2_final_gate_credits_modules_and_interactions_from_successes_only() -> None:
    with successor.successor_configuration():
        base, adapter = _v2_observations()
        gate = core.gate_arithmetic(base, adapter)
        reviews = {
            "reviews": [
                {"task_id": row["task_id"], "decision": "ACCEPT"}
                for row in adapter
                if row["family"] in core.FINAL_HUMAN_REVIEW
            ]
        }
        freeze = {"runtime_identities": {"adapter_off_restore": {"exact_candidate_restore": True}}}
        decision = core._final_adjudication(
            {"decision": gate, "observations": {"adapter": adapter}}, reviews, freeze
        )
        assert decision["verdict"] == "GRAMMAR_STDLIB_T30_V2_PASS_NO_RETRAIN"
        assert decision["gates"]["coverage_all_3_stdlib_modules"] is True
        assert decision["gates"]["coverage_all_10_interaction_classes"] is True

        for row in adapter:
            row["observed_coverage"]["interaction_classes"] = [
                item
                for item in row["observed_coverage"]["interaction_classes"]
                if item != "unknown-needs-capability"
            ]
        missing = core._final_adjudication(
            {"decision": gate, "observations": {"adapter": adapter}}, reviews, freeze
        )
        assert missing["gates"]["coverage_all_10_interaction_classes"] is False
        assert missing["verdict"] == "GRAMMAR_STDLIB_T30_V2_DIAGNOSE"


def test_declared_interaction_without_source_scenario_fails_closed() -> None:
    task = {
        "coverage": {"interaction_classes": ["unknown-stdlib-module"]},
        "expected_source": "metis 0.43\ntransformer heldout {}",
    }
    with (
        successor.successor_configuration(),
        pytest.raises(core.GrammarStdlibT30Error, match="no source scenario"),
    ):
        core._validate_interaction_coverage(task)
