from __future__ import annotations

import json
import os
import stat
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import metis_model1.brain_hard_qualification as hard
import metis_model1.cli as cli
from metis_model1.brain_context import TenantRegistry
from metis_model1.brain_model_runtime import StaticModelRuntime
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult, semantic_revision
from metis_model1.brain_server import (
    BrainApplication,
    BrainRuntime,
    _ThreadingBrainHTTPServer,
    load_brain_config,
)
from metis_model1.brain_sessions import ClientPolicy, SessionManager

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "examples/metis-brain-hard-prompts.play-prod-v1.json"
PLAN = ROOT / "examples/metis-brain-hard-qualification.play-prod-v1.json"
CONFIG = ROOT / "examples/metis-brain-config.play-prod-hard-qualification.local.json"


def test_hard_qualification_plan_binds_exact_corpus_and_authority() -> None:
    spec = hard.load_hard_qualification(CORPUS, PLAN)

    assert spec.corpus_sha256 == hard.EXPECTED_CORPUS_SHA256
    assert len(spec.corpus["endpoints"]) == 10
    assert len(spec.corpus["zero_generation_scenarios"]) == 10
    assert sum(len(item["turns"]) for item in spec.corpus["zero_generation_scenarios"]) == 40
    assert spec.tenant_head == "5f56bdfe27e3fb00b735db630a4eb5cdf5ab12c3"
    assert spec.tenant_tree == "03abf1a30603ff6cb59d55c32c3395cef868a218"
    assert all(
        check["value"] is not True
        for oracle in spec.plan["create_oracles"]
        for turn in oracle["turns"]
        for check in turn["checks"]
        if check["fact"] == "paginate"
    )
    catalog_values = [
        value
        for oracle in spec.plan["create_oracles"]
        for turn in oracle["turns"]
        for check in turn["checks"]
        if check["fact"] == "catalog_refs"
        for value in check["value"]
    ]
    assert catalog_values
    assert all(value.startswith("play-prod-v2.") for value in catalog_values)
    assert (
        sum(
            len(turn["checks"])
            for oracle in spec.plan["create_oracles"]
            for turn in oracle["turns"]
        )
        == 139
    )
    assert {
        "edit_cases": len(spec.corpus["endpoints"]),
        "create_journeys": len(spec.corpus["zero_generation_scenarios"]),
        "logical_create_turns": sum(
            len(item["turns"]) for item in spec.corpus["zero_generation_scenarios"]
        ),
        "assessed_generated_draft_turns": sum(
            len(item["turns"]) for item in spec.plan["create_oracles"]
        ),
        "logical_operator_messages": len(spec.corpus["endpoints"])
        + sum(len(item["turns"]) for item in spec.corpus["zero_generation_scenarios"]),
    } == hard.EXPECTED_DENOMINATOR


def test_all_edit_oracles_bind_and_change_only_declared_lines() -> None:
    spec = hard.load_hard_qualification(CORPUS, PLAN)
    cases = {item["endpoint_identity"]["qualified"]: item for item in spec.corpus["endpoints"]}

    changed_lines: dict[str, list[int]] = {}
    for oracle in spec.plan["edit_oracles"]:
        case = cases[oracle["endpoint"]]
        source = (spec.tenant_root / case["source_path"]).read_text(encoding="utf-8")
        expected = hard._apply_replacements(source, oracle["replacements"])
        before = source.splitlines()
        after = expected.splitlines()
        changed_lines[oracle["endpoint"]] = [
            index
            for index, pair in enumerate(zip(before, after, strict=True), start=1)
            if pair[0] != pair[1]
        ]

    assert changed_lines == {
        item["endpoint"]: [replacement["line"] for replacement in item["replacements"]]
        for item in spec.plan["edit_oracles"]
    }
    assert changed_lines["play.multiple_block_dem_titoli_momento"] == [449]


def test_qualification_config_has_no_apply_or_direct_compile_capability() -> None:
    spec = hard.load_hard_qualification(CORPUS, PLAN)
    hard.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    config = load_brain_config(CONFIG)
    hard.validate_hard_config(config, spec)

    assert len(config.client_policies) == 1
    capabilities = config.client_policies[0].capabilities
    assert capabilities == hard.EXPECTED_CAPABILITIES
    assert all("apply" not in item for item in capabilities)
    assert "compile" not in capabilities


def test_clarification_resolver_uses_only_exact_message_or_source_evidence() -> None:
    catalog = {
        "kind": "catalog",
        "options": [
            {"catalog": "play-prod-v2.video", "label": "Video", "option_ref": "video-ref"},
            {"catalog": "play-prod-v2.users", "label": "Users", "option_ref": "users-ref"},
        ],
    }
    assert hard.clarification_answer(
        catalog,
        evidence="Usa il catalogo video",
    ) == {"option_ref": "video-ref"}
    assert hard.clarification_answer(
        catalog,
        evidence="Confermo l'endpoint",
        source_catalogs={"video"},
    ) == {"option_ref": "video-ref"}
    assert hard.clarification_answer(catalog, evidence="Scegli tu") is None

    assert hard.clarification_answer(
        {"kind": "result_count", "answer_schema": {"type": "integer"}},
        evidence="Voglio 24 risultati totali",
    ) == {"integer": 24}
    assert (
        hard.clarification_answer(
            {"kind": "result_count", "answer_schema": {"type": "integer"}},
            evidence="Fra 20 e 30 risultati",
        )
        is None
    )

    response_shape = {
        "kind": "response_shape",
        "options": [
            {"label": "24 risultati complessivi", "option_ref": "count-ref"},
            {"label": "24 risultati per pagina", "option_ref": "page-ref"},
        ],
    }
    assert hard.clarification_answer(
        response_shape,
        evidence="Sono 24 risultati totali",
    ) == {"option_ref": "count-ref"}
    assert hard.clarification_answer(
        response_shape,
        evidence="Sono 24 risultati per pagina",
    ) == {"option_ref": "page-ref"}


def test_draft_gate_separates_compile_grounding_and_target_contracts() -> None:
    target = {
        "mode": "create",
        "relative_path": "properties/qualification/test.metis",
        "endpoint": "qualification.test",
        "base_sha256": None,
        "reference": None,
    }
    terminal = {
        "status": "completed",
        "outcome": "proposed",
        "proposal": {
            "operation": "create",
            "relative_path": target["relative_path"],
            "endpoint": target["endpoint"],
            "base_sha256": None,
        },
        "validation": {"status": "ok", "attempts": 1},
        "grounding": {
            "status": "resolved",
            "candidates": [],
            "unresolved": [],
            "selections": [],
            "resolutions": [],
        },
        "claims": {"semantic_grounded": True, "tenant_modified": False},
    }

    assert hard._draft_gate(terminal, target) == (True, [])
    invalid = json.loads(json.dumps(terminal))
    invalid["validation"]["attempts"] = 2
    invalid["grounding"]["unresolved"] = ["fallback"]
    valid, failures = hard._draft_gate(invalid, target)
    assert valid is False
    assert failures == ["not_first_attempt", "grounding_not_exact"]


def test_aggregate_keeps_safe_failure_distinct_from_accuracy_pass() -> None:
    edits = [
        {"verdict": "PASS_DRAFT"},
        {"verdict": "SAFE_FAIL_CLOSED"},
        {"verdict": "FAIL_SEMANTIC_ORACLE"},
        {"verdict": "FAIL"},
    ]
    journey = {
        "verdict": "NOT_CONVERGED",
        "turns": [
            {"verdict": "PASS_CLARIFICATION"},
            {"verdict": "PASS_STRUCTURAL_ORACLE"},
            {"verdict": "SAFE_FAIL_CLOSED"},
            {"verdict": "BLOCKED_BY_PREDECESSOR"},
        ],
    }

    result = hard._aggregate(edits, [journey])

    assert result["edits"] == {
        "total": 4,
        "pass_draft": 1,
        "safe_fail_closed": 1,
        "semantic_oracle_fail": 1,
        "unsafe_fail": 1,
    }
    assert result["create_journeys"] == {
        "total": 1,
        "converged_structural_oracle": 0,
        "not_converged": 1,
    }
    assert result["logical_create_turns"] == {
        "total": 4,
        "pass_clarification": 1,
        "pass_structural_oracle": 1,
        "semantic_oracle_fail": 0,
        "action_mismatch": 0,
        "safe_fail_closed": 1,
        "blocked_by_predecessor": 1,
        "unsafe_fail": 0,
    }


def test_local_model_execution_requires_explicit_one_run_flag(tmp_path: Path) -> None:
    output = tmp_path / "must-not-exist.json"
    with pytest.raises(BrainError, match="explicit one-run flag") as caught:
        hard.run_hard_qualification(
            config_path=CONFIG,
            corpus_path=CORPUS,
            plan_path=PLAN,
            output_path=output,
            authorize_local_model_execution=False,
        )
    assert caught.value.code == "HARD_QUALIFICATION_NOT_AUTHORIZED"
    assert not output.exists()


def test_receipt_writer_is_create_only_and_self_hash_is_stable(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    body = {"schema_version": 1, "status": "MEASURED"}
    receipt = {**body, "receipt_sha256": canonical_sha256(body)}

    hard._write_receipt(output, receipt)

    assert json.loads(output.read_text(encoding="utf-8")) == receipt
    with pytest.raises(FileExistsError):
        hard._write_receipt(output, receipt)
    assert not list(tmp_path.glob("*.pending"))


def _mock_live_qualification_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[hard.HardQualificationSpec, Path]:
    spec = hard.load_hard_qualification(CORPUS, PLAN)
    output_root = (tmp_path / "receipts").resolve()
    monkeypatch.setattr(hard, "OUTPUT_ROOT", output_root)
    monkeypatch.setattr(hard, "validate_hard_config", lambda _config, _spec: None)
    model_guard = {"commit": "model-commit", "tree": "model-tree", "status": []}
    tenant_guard = {
        "commit": spec.tenant_head,
        "tree": spec.tenant_tree,
        "status": [],
        "target": "sha256:" + "a" * 64,
    }
    monkeypatch.setattr(hard, "capture_model1_guard", lambda: dict(model_guard))
    monkeypatch.setattr(
        hard,
        "capture_tenant_guard",
        lambda **_kwargs: dict(tenant_guard),
    )

    class FakeService:
        address = ("127.0.0.1", 43123)
        app = SimpleNamespace(
            compiler=SimpleNamespace(pin_identity=spec.runtime_identity["toolchain"])
        )

        def __init__(self, _config: Any) -> None:
            self.closed = False

        def start_background(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    class FakeClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def health(self) -> dict[str, Any]:
            return {"status": "ready"}

    monkeypatch.setattr(hard, "MetisBrainService", FakeService)
    monkeypatch.setattr(hard, "HeadlessBrainClient", FakeClient)
    monkeypatch.setattr(hard, "_bootstrap_token", lambda _service: "bootstrap")
    return spec, output_root / "receipt.json"


def test_completed_measurement_survives_failed_post_suite_health_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec, output = _mock_live_qualification_runtime(monkeypatch, tmp_path)
    validations = 0

    def validate_health(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal validations
        validations += 1
        if validations == 2:
            raise BrainError("HARD_QUALIFICATION_RUNTIME", 503, "not qualified")
        return dict(spec.runtime_identity)

    monkeypatch.setattr(hard, "_validate_qualified_health", validate_health)
    monkeypatch.setattr(
        hard,
        "_run_edit",
        lambda **kwargs: {
            "endpoint": kwargs["case"]["endpoint_identity"]["qualified"],
            "verdict": "SAFE_FAIL_CLOSED",
        },
    )
    monkeypatch.setattr(
        hard,
        "_run_journey",
        lambda **kwargs: {
            "source_endpoint": kwargs["journey"]["endpoint_qualified"],
            "verdict": "NOT_CONVERGED",
            "turns": [{"verdict": "SAFE_FAIL_CLOSED"} for _ in range(4)],
        },
    )

    receipt = hard.run_hard_qualification(
        config_path=CONFIG,
        corpus_path=CORPUS,
        plan_path=PLAN,
        output_path=output,
        authorize_local_model_execution=True,
    )

    assert receipt["status"] == "MEASURED"
    assert receipt["measurement_status"] == "COMPLETE"
    assert receipt["completed"] == {
        "edits": 10,
        "create_journeys": 10,
        "logical_create_turns": 40,
    }
    assert receipt["terminal_gate"] == {
        "status": "FAILED",
        "phase": "health_after",
        "code": "HARD_QUALIFICATION_RUNTIME",
    }
    assert receipt["qualification_green"] is False
    assert receipt["boundary"]["tenant_modified"] is False
    stored = json.loads(output.read_text(encoding="utf-8"))
    digest = stored.pop("receipt_sha256")
    assert digest == canonical_sha256(stored)


def test_partial_measurement_preserves_completed_results_in_incomplete_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec, output = _mock_live_qualification_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(
        hard,
        "_validate_qualified_health",
        lambda *_args, **_kwargs: dict(spec.runtime_identity),
    )
    calls = 0

    def edit(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise BrainError("HARD_QUALIFICATION_HTTP", 502, "failed")
        return {
            "endpoint": kwargs["case"]["endpoint_identity"]["qualified"],
            "verdict": "SAFE_FAIL_CLOSED",
        }

    monkeypatch.setattr(hard, "_run_edit", edit)

    returned = hard.run_hard_qualification(
        config_path=CONFIG,
        corpus_path=CORPUS,
        plan_path=PLAN,
        output_path=output,
        authorize_local_model_execution=True,
    )
    assert not output.exists()
    incomplete_path = Path(returned["receipt_path"])
    assert incomplete_path.parent == output.parent
    assert incomplete_path.match("receipt.incomplete-*.json")
    receipt = json.loads(incomplete_path.read_text(encoding="utf-8"))
    assert receipt == returned
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["measurement_status"] == "PARTIAL"
    assert receipt["completed"] == {
        "edits": 3,
        "create_journeys": 0,
        "logical_create_turns": 0,
    }
    assert len(receipt["edits"]) == 3
    assert receipt["terminal_gate"] == {
        "status": "FAILED",
        "phase": "edit",
        "code": "HARD_QUALIFICATION_HTTP",
    }
    digest = receipt.pop("receipt_sha256")
    assert digest == canonical_sha256(receipt)


def test_terminal_gate_precedence_is_deterministic_and_drift_first() -> None:
    tenant = {"commit": "tenant"}
    model = {"commit": "model"}
    guard = BrainError("GUARD", 409, "guard")
    suite = BrainError("SUITE", 503, "suite")
    close = BrainError("CLOSE", 503, "close")

    error, phase = hard._terminal_failure(
        tenant_before=tenant,
        tenant_after={"commit": "changed"},
        model1_before=model,
        model1_after={"commit": "changed"},
        guard_error=guard,
        guard_error_phase="tenant_guard",
        suite_error=suite,
        suite_error_phase="health_after",
        close_error=close,
    )
    assert isinstance(error, BrainError) and error.code == "HARD_QUALIFICATION_DRIFT"
    assert phase == "tenant_guard"

    error, phase = hard._terminal_failure(
        tenant_before=tenant,
        tenant_after=tenant,
        model1_before=model,
        model1_after={"commit": "changed"},
        guard_error=guard,
        guard_error_phase="model_guard",
        suite_error=suite,
        suite_error_phase="health_after",
        close_error=close,
    )
    assert isinstance(error, BrainError) and error.code == "HARD_QUALIFICATION_DRIFT"
    assert phase == "model_guard"

    for expected, expected_phase, values in (
        (guard, "model_guard", (guard, "model_guard", suite, close)),
        (suite, "health_after", (None, None, suite, close)),
        (close, "close", (None, None, None, close)),
        (None, "complete", (None, None, None, None)),
    ):
        guard_error, guard_phase, suite_error, close_error = values
        error, phase = hard._terminal_failure(
            tenant_before=tenant,
            tenant_after=tenant,
            model1_before=model,
            model1_after=model,
            guard_error=guard_error,
            guard_error_phase=guard_phase,
            suite_error=suite_error,
            suite_error_phase="health_after",
            close_error=close_error,
        )
        assert error is expected
        assert phase == expected_phase


def test_plan_and_config_identity_pins_are_sealed() -> None:
    """The live lane must never run against a self-selected plan or config."""

    assert hard._HASH_RE.fullmatch(hard.EXPECTED_PLAN_SHA256)
    assert hard._HASH_RE.fullmatch(hard.EXPECTED_CONFIG_SHA256)
    assert hard.EXPECTED_PLAN_SHA256 != "sha256:TO_BE_SEALED"
    assert hard.EXPECTED_CONFIG_SHA256 != "sha256:TO_BE_SEALED"
    assert hard._sha256(PLAN.read_bytes()) == hard.EXPECTED_PLAN_SHA256
    assert hard._sha256(CONFIG.read_bytes()) == hard.EXPECTED_CONFIG_SHA256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "draft"),
        ("unresolved", ["catalog"]),
        ("candidates", [{"catalog": "video"}]),
        ("selections", [{"catalog": "video", "field": "mood", "literal": "dark"}]),
        (
            "resolutions",
            [{"catalog": "video", "field": "mood", "literal": "dark", "review_state": "draft"}],
        ),
    ],
)
def test_draft_gate_rejects_unreviewed_or_nonresolved_grounding(field: str, value: Any) -> None:
    target = {
        "mode": "create",
        "relative_path": "properties/qualification/test.metis",
        "endpoint": "qualification.test",
        "base_sha256": None,
    }
    terminal: dict[str, Any] = {
        "status": "completed",
        "outcome": "proposed",
        "proposal": {
            "operation": "create",
            "relative_path": target["relative_path"],
            "endpoint": target["endpoint"],
            "base_sha256": None,
        },
        "validation": {"status": "ok", "attempts": 1},
        "grounding": {
            "status": "resolved",
            "candidates": [],
            "unresolved": [],
            "selections": [],
            "resolutions": [],
        },
        "claims": {"semantic_grounded": True, "tenant_modified": False},
    }
    terminal["grounding"][field] = value
    if field == "resolutions":
        terminal["grounding"]["selections"] = [
            {"catalog": "video", "field": "mood", "literal": "dark"}
        ]
    valid, failures = hard._draft_gate(terminal, target)
    assert valid is False
    assert "grounding_not_exact" in failures or "grounding_roster_not_reviewed" in failures


def test_structural_facts_and_checks_are_format_independent() -> None:
    ir = {
        "node": "Endpoint",
        "name": "qualification.test",
        "paginate": "snapshot",
        "context": {"user": {}},
        "attributes": {"genre": {}},
        "blocks": [
            {
                "node": "Fetch",
                "name": "main",
                "source": {"kind": "catalog", "ref": "video"},
                "count": {"take": 24},
                "output": [{"kind": "items", "n": 24}],
                "fallback": {
                    "rule": {"trigger": {"kind": "empty"}, "mode": "use"},
                    "target": "backup",
                },
                "uses": [{"ref": "parametric", "arg": {"limit": 24}}],
                "viewAll": {},
                "ordering": [
                    {
                        "by": {
                            "kind": "similarity",
                            "target": {"ctx": "user.video_historical_fingerprint"},
                        },
                        "direction": "desc",
                    }
                ],
            }
        ],
        "variants": [{"name": "fallback", "guard": "offline", "blocks": []}],
    }
    facts = hard.structural_facts(ir)
    assert facts["endpoint_name"] == "qualification.test"
    assert facts["catalog_refs"] == ["video"]
    assert facts["paginate"] == "snapshot"
    assert facts["endpoint_take_counts"] == [24]
    assert facts["view_all_count"] == 1
    assert facts["parameterized_block_count"] == 1
    assert facts["fallback_keys"] == ["empty:use:backup"]
    assert facts["output_flow_count"] == 1
    assert facts["ordering_signatures"] == ["similarity:desc:ctx:user.video_historical_fingerprint"]
    checks_green, outcomes = hard.evaluate_structural_checks(
        facts,
        [
            {"id": "catalog", "fact": "catalog_refs", "op": "contains_all", "value": ["video"]},
            {"id": "take", "fact": "endpoint_take_counts", "op": "contains_all", "value": [24]},
            {"id": "not-users", "fact": "catalog_refs", "op": "excludes_all", "value": ["users"]},
        ],
    )
    assert checks_green is True
    assert all(item["pass"] is True for item in outcomes)


def test_structural_facts_include_all_root_fallback_targets_and_thresholds() -> None:
    facts = hard.structural_facts(
        {
            "node": "Endpoint",
            "name": "qualification.test",
            "blocks": [],
            "variants": [],
            "fallback": {
                "endpoint": "play.backup",
                "when": {"below": 2},
                "mode": "append",
            },
            "fallbacks": [
                {
                    "endpoint": "play.backup",
                    "when": {"below": 2},
                    "mode": "append",
                },
                {"block": "emergency", "when": "error", "mode": "substitute"},
            ],
        }
    )

    assert facts["fallback_keys"] == [
        "below-2:append:endpoint.play.backup",
        "error:substitute:block.emergency",
    ]


def test_clarification_gate_requires_typed_bound_and_next_answerable_question() -> None:
    terminal = {
        "turn_id": "turn-1",
        "clarification": {
            "clarification_id": "clarification-1",
            "kind": "result_count",
            "question": "Quanti risultati vuoi?",
            "options": [],
            "answer_schema": {"type": "integer", "minimum": 1, "maximum": 1000},
            "round": 1,
            "max_rounds": 3,
        },
    }

    assert hard._clarification_gate(
        terminal,
        expected_turn_id="turn-1",
        next_evidence="Catalogo video, 24 risultati totali.",
    ) == (True, [])
    valid, failures = hard._clarification_gate(
        terminal,
        expected_turn_id="other-turn",
        next_evidence="Non lo so.",
    )
    assert valid is False
    assert failures == ["clarification_turn_binding"]
    valid, failures = hard._clarification_gate(
        terminal,
        expected_turn_id="turn-1",
        next_evidence="Non lo so.",
    )
    assert valid is False
    assert failures == ["clarification_not_answerable_by_next_message"]


def test_structural_checks_reject_unknown_fact_and_shape() -> None:
    with pytest.raises(BrainError, match="structural check is invalid"):
        hard.evaluate_structural_checks(
            {"catalog_refs": ["video"]},
            [{"id": "unknown", "fact": "missing", "op": "equals", "value": 1}],
        )
    with pytest.raises(BrainError, match="structural check is invalid"):
        hard.evaluate_structural_checks(
            {"catalog_refs": ["video"]},
            [{"id": "bad", "fact": "catalog_refs", "op": "regex", "value": "video"}],
        )


def test_bootstrap_token_rejects_symlink_and_wrong_mode(tmp_path: Path) -> None:
    runtime = BrainRuntime(tmp_path / "runtime")
    service = SimpleNamespace(runtime=runtime)
    try:
        token = tmp_path / "token-target"
        token.write_text("not-the-bootstrap-token\n", encoding="ascii")
        runtime.bootstrap_file.unlink()
        runtime.bootstrap_file.symlink_to(token)
        with pytest.raises(BrainError):
            hard._bootstrap_token(service)

        runtime.bootstrap_file.unlink()
        runtime.bootstrap_file.write_text("valid-token\n", encoding="ascii")
        os.chmod(runtime.bootstrap_file, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        with pytest.raises(BrainError):
            hard._bootstrap_token(service)
    finally:
        runtime.close()


def test_runtime_and_output_reject_symlink_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_runtime = tmp_path / "real-runtime"
    real_runtime.mkdir()
    runtime_link = tmp_path / "runtime-link"
    runtime_link.symlink_to(real_runtime, target_is_directory=True)
    with pytest.raises(BrainError):
        BrainRuntime(runtime_link)

    output_root = tmp_path / "output"
    output_root.mkdir()
    monkeypatch.setattr(hard, "OUTPUT_ROOT", output_root)
    (output_root / "nested").mkdir()
    with pytest.raises(BrainError):
        hard._prepare_output(output_root / "nested" / "receipt.json")

    root_link = tmp_path / "output-link"
    root_link.symlink_to(output_root, target_is_directory=True)
    monkeypatch.setattr(hard, "OUTPUT_ROOT", root_link)
    with pytest.raises(BrainError):
        hard._prepare_output(root_link / "receipt.json")


def test_receipt_writer_removes_partial_pending_file_on_short_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "receipt.json"
    original_write = os.write

    def short_write(fd: int, data: bytes) -> int:
        return max(0, len(data) - 1)

    monkeypatch.setattr(hard.os, "write", short_write)
    with pytest.raises(OSError, match="short receipt write"):
        hard._write_receipt(output, {"schema_version": 1})
    assert not output.exists()
    assert not list(tmp_path.glob("*.pending"))
    monkeypatch.setattr(hard.os, "write", original_write)


def test_case_guard_runs_after_close_failure_and_drift_takes_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    source_path = "source.metis"
    source = "endpoint qualification.test { take 24 from @video }\n"
    (tenant / source_path).write_text(source, encoding="utf-8")
    source_sha = hard._sha256(source.encode("utf-8"))
    spec = SimpleNamespace(
        tenant_root=tenant,
        tenant_alias="play-prod",
        tenant_id="play-prod-v2",
    )
    case = {
        "endpoint_identity": {"qualified": "qualification.test"},
        "source_path": source_path,
        "source_sha256": source_sha,
        "operator_edit_prompt_it": "Cambia il numero a 12",
    }
    oracle = {"replacements": [{"line": 1, "before": "take 24", "after": "take 12"}]}
    edited = source.replace("take 24", "take 12")
    terminal = {
        "status": "completed",
        "outcome": "proposed",
        "proposal": {
            "operation": "replace",
            "relative_path": source_path,
            "endpoint": "qualification.test",
            "base_sha256": source_sha,
            "source": edited,
            "source_sha256": hard._sha256(edited.encode("utf-8")),
            "proposal_ref": "proposal-1",
        },
        "validation": {"status": "ok", "attempts": 1},
        "grounding": {
            "status": "resolved",
            "candidates": [],
            "unresolved": [],
            "selections": [],
            "resolutions": [],
        },
        "claims": {"semantic_grounded": True, "tenant_modified": False},
    }

    class CloseFailClient:
        def open_session(self, *, tenant_alias: str) -> dict[str, Any]:
            assert tenant_alias == "play-prod"
            return {"id": "session-1", "token": "session-token"}

        def context(self, session: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "files": [{"path": source_path, "sha256": source_sha}],
                "revision": "r1",
                "semantic_source_revision": "s1",
            }

        def submit(self, session: Mapping[str, Any], body: Mapping[str, Any]) -> str:
            return "turn-1"

        def wait_terminal(
            self, session: Mapping[str, Any], turn_id: str
        ) -> tuple[dict[str, Any], int]:
            return terminal, 1

        def events(self, session: Mapping[str, Any], turn_id: str) -> list[dict[str, Any]]:
            return []

        def close_session(self, session: Mapping[str, Any]) -> None:
            raise BrainError("HARD_QUALIFICATION_HTTP", 502, "session close failed")

    calls: list[dict[str, Any]] = []

    def guard(**_kwargs: Any) -> dict[str, Any]:
        calls.append({})
        return {"commit": "head", "tree": "tree", "target": source_sha}

    monkeypatch.setattr(hard, "capture_tenant_guard", guard)
    with pytest.raises(BrainError) as caught:
        hard._run_edit(client=CloseFailClient(), spec=spec, case=case, oracle=oracle)
    assert caught.value.code == "HARD_QUALIFICATION_HTTP"
    assert len(calls) == 2


class _Compiler:
    toolchain_binding = "sha256:" + "a" * 64

    def compile(self, *, lease: Any, source: str, filename: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "compiler": {"status": "ok", "endpoint_sha256": canonical_sha256(source)},
            "diagnostics": [],
            "toolchain_binding": self.toolchain_binding,
            "receipt_sha256": canonical_sha256({"source": source, "filename": filename}),
            "session_id": lease.session_id,
        }


class _Retriever:
    def retrieve(self, *, lease: Any, request: Any) -> RetrievalResult:
        return RetrievalResult(
            context={"tenant": lease.tenant_alias, "semantic_schema": 2},
            grounding={
                "status": "resolved",
                "catalogs": ["video"],
                "selections": [],
                "candidates": [],
                "unresolved": [],
            },
            semantic_source_revision=semantic_revision(lease.snapshot),
            catalog_candidates=({"catalog": "video", "label": "Video"},),
        )


@contextmanager
def _http_service(tmp_path: Path):
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    (tenant / "metis.toml").write_text(
        '[tenant]\nid = "tenant-one"\n\n[stdlib]\nlanguage = "0.43"\n',
        encoding="utf-8",
    )
    (tenant / "main.metis").write_text("metis 0.43\n", encoding="utf-8")
    runtime = BrainRuntime((tmp_path / "runtime").resolve())
    compiler = _Compiler()
    manager = SessionManager(
        registry=TenantRegistry([("play-prod", "tenant-one", tenant.resolve())]),
        policies=[
            ClientPolicy(
                hard.EXPECTED_CLIENT_ID,
                frozenset({"play-prod"}),
                hard.EXPECTED_CAPABILITIES,
            )
        ],
        runtime_root=runtime.run_dir / "sessions",
        toolchain_binding=compiler.toolchain_binding,
    )
    model = StaticModelRuntime("metis 0.43\nendpoint qualification.test { take 24 from @video }\n")
    app = BrainApplication(
        runtime=runtime,
        manager=manager,
        compiler=compiler,
        retriever=_Retriever(),
        model=model,
    )
    server = _ThreadingBrainHTTPServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runtime, tenant
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        app.close()
        manager.shutdown()
        runtime.close()


def test_headless_client_crosses_real_http_turn_and_answer_routes(tmp_path: Path) -> None:
    with _http_service(tmp_path) as (server, runtime, tenant):
        client = hard.HeadlessBrainClient(
            "127.0.0.1",
            server.server_address[1],
            bootstrap_token=runtime.bootstrap_file.read_text(encoding="ascii").strip(),
        )
        session = client.open_session(tenant_alias="play-prod")
        context = client.context(session)
        target = {
            "mode": "create",
            "relative_path": "qualification.metis",
            "endpoint": "qualification.test",
            "base_sha256": None,
            "reference": None,
        }
        body = hard._turn_body(
            context=context,
            instruction="Crea alcuni risultati dal catalogo video",
            intent="create",
            target=target,
            basis=None,
        )
        turn_id = client.submit(session, body)
        pending, _elapsed = client.wait_terminal(session, turn_id)
        assert pending["outcome"] == "needs_clarification"
        assert pending["clarification"]["kind"] == "result_count"
        resumed_id = client.answer(
            session,
            parent_turn_id=pending["turn_id"],
            clarification_id=pending["clarification"]["clarification_id"],
            answer={"integer": 24},
        )
        proposed, _elapsed = client.wait_terminal(session, resumed_id)
        assert proposed["outcome"] == "proposed"
        assert proposed["claims"]["tenant_modified"] is False
        assert any(item["event"] == "terminal" for item in client.events(session, resumed_id))
        client.close_session(session)
        assert not (tenant / "qualification.metis").exists()


@pytest.mark.parametrize(("green", "expected_exit"), [(True, 0), (False, 2)])
def test_hard_qualification_cli_exit_reflects_promotion_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    green: bool,
    expected_exit: int,
) -> None:
    receipt = {
        "status": "MEASURED",
        "denominator": {
            "edit_cases": 10,
            "create_journeys": 10,
            "logical_create_turns": 40,
            "assessed_generated_draft_turns": 30,
            "logical_operator_messages": 50,
        },
        "aggregate": {
            "edits": {"total": 10, "pass_draft": 10 if green else 9},
            "create_journeys": {
                "total": 10,
                "converged_structural_oracle": 10,
            },
        },
        "qualification_green": green,
        "receipt_sha256": "sha256:" + "a" * 64,
    }
    monkeypatch.setattr(cli, "run_hard_qualification", lambda **_kwargs: receipt)

    result = cli.main(
        [
            "brain-hard-qualification",
            "--config",
            str(CONFIG),
            "--corpus",
            str(CORPUS),
            "--plan",
            str(PLAN),
            "--output",
            str(tmp_path / "receipt.json"),
            "--authorize-local-model-execution",
        ]
    )

    assert result == expected_exit


def test_hard_qualification_cli_reports_partial_receipt_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt_path = tmp_path / "receipt.incomplete-1234.json"
    receipt = {
        "status": "INCOMPLETE",
        "measurement_status": "PARTIAL",
        "denominator": dict(hard.EXPECTED_DENOMINATOR),
        "completed": {"edits": 3, "create_journeys": 0, "logical_create_turns": 0},
        "terminal_gate": {
            "status": "FAILED",
            "phase": "edit",
            "code": "HARD_QUALIFICATION_HTTP",
        },
        "qualification_green": False,
        "receipt_sha256": "sha256:" + "a" * 64,
        "receipt_path": str(receipt_path),
    }
    monkeypatch.setattr(cli, "run_hard_qualification", lambda **_kwargs: receipt)

    result = cli.main(
        [
            "brain-hard-qualification",
            "--config",
            str(CONFIG),
            "--corpus",
            str(CORPUS),
            "--plan",
            str(PLAN),
            "--output",
            str(tmp_path / "receipt.json"),
            "--authorize-local-model-execution",
        ]
    )

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "INCOMPLETE"
    assert payload["measurement_status"] == "PARTIAL"
    assert payload["receipt_path"] == str(receipt_path)
    assert payload["terminal_gate"]["code"] == "HARD_QUALIFICATION_HTTP"
