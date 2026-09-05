from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import metis_model1.brain_complex_create_qualification as qualification
import metis_model1.cli as cli
from metis_model1.brain_hard_qualification import HeadlessBrainClient, HttpResult
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_server import parse_brain_config_bytes


def test_prompt_roster_is_exactly_ten_by_four_and_targets_are_opaque() -> None:
    spec = qualification.load_complex_create_qualification()

    assert len(spec.prompt["journeys"]) == 10
    assert sum(len(item["messages"]) for item in spec.prompt["journeys"]) == 40
    assert [item["case_id"] for item in spec.prompt["journeys"]] == [
        f"case_{index:02d}" for index in range(1, 11)
    ]
    assert [target.endpoint for target in spec.targets] == [
        f"brain_qualification_v3.case_{index:02d}" for index in range(1, 11)
    ]
    prompt_wire = json.dumps(spec.prompt["journeys"], sort_keys=True)
    for forbidden in ("blueprint", "reference_endpoint", "expected_spec", "source_endpoint"):
        assert forbidden not in prompt_wire


def test_ready_prompt_contracts_name_the_seed_and_series_tv_without_implicit_semantics() -> None:
    journeys = {
        item["case_id"]: item["messages"]
        for item in qualification.load_complex_create_qualification().prompt["journeys"]
    }

    assert "contenuto visto come seed" in journeys["case_01"][1]
    assert "film e serie TV recenti" in journeys["case_06"][1]


def test_loader_does_not_open_blueprints_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = qualification._read_json  # noqa: SLF001
    opened: list[str] = []

    def guarded(path: Path, *, label: str):
        opened.append(path.name)
        assert "blueprints" not in path.name
        return original(path, label=label)

    monkeypatch.setattr(qualification, "_read_json", guarded)
    qualification.load_complex_create_qualification()
    assert opened == [
        "metis-brain-complex-create-prompts.play-prod-v3.json",
        "metis-brain-complex-create-qualification.play-prod-v3.json",
    ]


def test_dedicated_pinned_config_enables_only_the_typed_create_client() -> None:
    spec = qualification.load_complex_create_qualification()
    config = parse_brain_config_bytes(spec.config_path.read_bytes())
    qualification._validate_complex_config(config, spec)  # noqa: SLF001
    assert config.typed_create is True
    assert len(config.client_policies) == 1
    assert config.client_policies[0].client_id == qualification.CLIENT_ID
    assert config.client_policies[0].capabilities == qualification.CLIENT_CAPABILITIES
    assert "apply" not in config.client_policies[0].capabilities


def test_disabled_typed_create_health_is_not_live_ready() -> None:
    expected = qualification.load_complex_create_qualification().runtime_identity["typed_create"]
    with pytest.raises(BrainError, match="pinned typed CREATE authority is not enabled"):
        qualification._validate_typed_create_health(  # noqa: SLF001
            {
                "typed_create": {
                    "enabled": False,
                    "implementation": None,
                    "policy_revision": None,
                    "inventory_revision": None,
                }
            },
            expected=expected,
        )


def test_typed_create_health_must_equal_the_pinned_runtime_identity() -> None:
    expected = qualification.load_complex_create_qualification().runtime_identity["typed_create"]
    drifted = deepcopy(expected)
    drifted["inventory_revision"] = "sha256:" + "f" * 64

    with pytest.raises(BrainError, match="pinned typed CREATE authority is not enabled"):
        qualification._validate_typed_create_health(  # noqa: SLF001
            {"typed_create": drifted},
            expected=expected,
        )


def test_answer_v2_emits_the_exact_dialogue_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def request(
        _self: HeadlessBrainClient,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> HttpResult:
        captured.update(method=method, path=path, token=token, body=body, timeout=timeout)
        return HttpResult(202, {"turn_id": "turn-answer-v2"})

    monkeypatch.setattr(HeadlessBrainClient, "request", request)
    client = HeadlessBrainClient("127.0.0.1", 9797, bootstrap_token="bootstrap")
    turn_id = client.answer_v2(
        {"id": "session-one", "token": "session-token"},
        parent_turn_id="parent-turn",
        clarification_id="clarification-one",
        message="Il catalogo è video e voglio 24 risultati.",
        answers=(),
    )

    assert turn_id == "turn-answer-v2"
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/sessions/session-one/turns/parent-turn/answer"
    assert captured["token"] == "session-token"
    assert captured["body"].keys() == {
        "schema_version",
        "request_id",
        "clarification_id",
        "message",
        "answers",
    }
    assert captured["body"]["schema_version"] == 2
    assert captured["body"]["clarification_id"] == "clarification-one"
    assert captured["body"]["answers"] == []


def test_headless_client_can_request_the_dedicated_typed_create_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def request(
        _self: HeadlessBrainClient,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> HttpResult:
        captured.update(method=method, path=path, token=token, body=body, timeout=timeout)
        return HttpResult(201, {"session": {"id": "session-one"}})

    monkeypatch.setattr(HeadlessBrainClient, "request", request)
    capabilities = frozenset(
        {"chat.read", "chat.turn", "compile", "context.read", "session.close", "session.read"}
    )
    client = HeadlessBrainClient(
        "127.0.0.1",
        9797,
        bootstrap_token="bootstrap",
        client_id="brain-complex-create-qualification",
        capabilities=capabilities,
    )

    assert client.open_session(tenant_alias="play-prod") == {"id": "session-one"}
    assert captured["body"] == {
        "client_id": "brain-complex-create-qualification",
        "tenant_alias": "play-prod",
        "capabilities": sorted(capabilities),
    }


class _FakeTurns:
    def seal_typed_create_qualification_receipt(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "contract_id": "metis-brain-typed-create-qualification-receipt/v1",
            "turn_id": kwargs["turn_id"],
            "spec_sha256": "sha256:" + "1" * 64,
            "receipt_sha256": "sha256:" + "2" * 64,
        }

    def seal_typed_create_clarification_receipt(self, **kwargs: Any) -> dict[str, Any]:
        return _clarification_receipt(kwargs["turn_id"], "endpoint.catalogs")


class _FakeClient:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.terminals = {
            "turn-1": {
                "turn_id": "turn-1",
                "status": "completed",
                "outcome": "needs_clarification",
                "clarification": {"clarification_id": "clarification-1"},
            },
            "turn-2": {
                "turn_id": "turn-2",
                "status": "completed",
                "outcome": "proposed",
                "proposal": {"proposal_ref": "proposal-2", "source": "draft-2"},
            },
            "turn-3": {
                "turn_id": "turn-3",
                "status": "completed",
                "outcome": "needs_clarification",
                "clarification": {"clarification_id": "clarification-3"},
            },
            "turn-4": {
                "turn_id": "turn-4",
                "status": "completed",
                "outcome": "proposed",
                "proposal": {"proposal_ref": "proposal-4", "source": "draft-4"},
            },
        }

    def open_session(self, *, tenant_alias: str) -> dict[str, str]:
        assert tenant_alias == "play-prod"
        return {"id": "session", "token": "token"}

    def context(self, _session: dict[str, str]) -> dict[str, str]:
        return {
            "revision": "sha256:" + "a" * 64,
            "semantic_source_revision": "sha256:" + "b" * 64,
            "toolchain_binding": "sha256:" + "c" * 64,
        }

    def submit(self, _session: dict[str, str], body: dict[str, Any]) -> str:
        turn_id = f"turn-{len(self.submissions) + 1}"
        self.submissions.append(("turn", deepcopy(body)))
        return turn_id

    def answer_v2(self, _session: dict[str, str], **body: Any) -> str:
        turn_id = f"turn-{len(self.submissions) + 1}"
        self.submissions.append(("answer_v2", deepcopy(body)))
        return turn_id

    def wait_terminal(self, _session: dict[str, str], turn_id: str):
        return deepcopy(self.terminals[turn_id]), 0

    def events(self, _session: dict[str, str], turn_id: str) -> list[dict[str, Any]]:
        terminal = self.terminals[turn_id]
        names = ["terminal"]
        if terminal["outcome"] == "proposed":
            names = ["inference.started", "compile.started", "terminal"]
        return [{"event": name, "data": {}} for name in names]

    def close_session(self, _session: dict[str, str]) -> None:
        self.closed = True


def test_journey_uses_answer_v2_after_ask_and_proposal_basis_after_ready() -> None:
    spec = qualification.load_complex_create_qualification()
    client = _FakeClient()
    journey = spec.prompt["journeys"][0]

    result = qualification._run_journey(  # noqa: SLF001
        service=SimpleNamespace(app=SimpleNamespace(turns=_FakeTurns())),
        client=client,
        spec=spec,
        journey=journey,
        target=spec.targets[0],
    )

    assert client.closed is True
    assert [kind for kind, _ in client.submissions] == [
        "turn",
        "answer_v2",
        "turn",
        "answer_v2",
    ]
    assert client.submissions[1][1]["message"] == journey["messages"][1]
    assert client.submissions[1][1]["answers"] == ()
    assert client.submissions[2][1]["basis"] == {
        "kind": "proposal",
        "proposal_ref": "proposal-2",
    }
    wire = json.dumps(client.submissions, sort_keys=True)
    assert spec.targets[0].scenario_id not in wire
    assert "blueprint" not in wire
    assert len(result["turns"]) == 4
    assert all("proposal_source" not in record["terminal"] for record in result["turns"])
    assert "draft-2" not in json.dumps(result, sort_keys=True)
    assert "draft-4" not in json.dumps(result, sort_keys=True)


def _blueprint_stage_map() -> dict[str, dict[str, Any]]:
    root = qualification.PROJECT_ROOT
    result: dict[str, dict[str, Any]] = {}
    for name in ("similar", "search"):
        value = json.loads(
            (root / f"examples/metis-brain-create-blueprints-v3-{name}.json").read_text()
        )
        for stage in value["stages"]:
            result[stage["stage_id"]] = stage
    value = json.loads(
        (root / "examples/metis-brain-create-blueprints-v3-multiblock.json").read_text()
    )
    for scenario in value["scenarios"]:
        for stage in scenario["stages"]:
            result[f"{scenario['scenario_id']}:{stage['stage_id']}"] = stage
    return result


def _clarification_receipt(turn_id: str, target_key: str) -> dict[str, Any]:
    slots = [
        {
            "decision_key": f"gap.{target_key}",
            "target_key": target_key,
            "kind": "result_count",
            "answer_kind": "integer",
            "value_contract": "total",
            "minimum": 1,
            "maximum": 100,
            "choice_count": 0,
        }
    ]
    body = {
        "contract_id": "metis-brain-typed-create-clarification-receipt/v1",
        "turn_id": turn_id,
        "round": 1,
        "slot_contracts": slots,
        "slot_contracts_sha256": canonical_sha256(slots),
        "binding_sha256": "sha256:" + "9" * 64,
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


def _qualification_receipt(
    turn_id: str,
    spec_sha256: str,
    generation: int,
) -> dict[str, Any]:
    body = {
        "contract_id": "metis-brain-typed-create-qualification-receipt/v1",
        "turn_id": turn_id,
        "generation": generation,
        "source_sha256": "sha256:" + "3" * 64,
        "manifest_sha256": "sha256:" + "4" * 64,
        "spec_sha256": spec_sha256,
        "ir_sha256": "sha256:" + "5" * 64,
        "parent_ir_sha256": None if generation == 0 else "sha256:" + "a" * 64,
        "delta_sha256": "sha256:" + "6" * 64,
        "delta_operation_count": 1,
        "history_revision": "sha256:" + "7" * 64,
        "compiler_receipt_sha256": "sha256:" + "8" * 64,
        "generation_strategy": "model_create_plan_v2",
    }
    return {**body, "receipt_sha256": canonical_sha256(body)}


def _passing_observations() -> list[dict[str, Any]]:
    spec = qualification.load_complex_create_qualification()
    stages = _blueprint_stage_map()
    journeys: list[dict[str, Any]] = []
    for target in spec.targets:
        generation = -1
        records: list[dict[str, Any]] = [
            {
                "turn": 1,
                "turn_id": f"{target.case_id}-turn-1",
                "request_sha256": "sha256:" + "1" * 64,
                "dialogue_binding_sha256": "sha256:" + "9" * 64,
                "terminal": {"outcome": "needs_clarification"},
                "event_counts": {"inference": 0, "compile": 0, "repair": 0, "terminal": 1},
                "qualification_proof": None,
                "clarification_proof": _clarification_receipt(
                    f"{target.case_id}-turn-1",
                    qualification.EXPECTED_INITIAL_GAP_TARGET[target.case_id],
                ),
                "clarification_sha256": "sha256:" + "0" * 64,
            }
        ]
        for turn in range(2, 5):
            stage = stages[f"{target.scenario_id}:T{turn}"]
            if stage["status"] == "ready":
                generation += 1
                expected = deepcopy(stage["spec"])
                expected["endpoint"]["name"] = target.endpoint
                turn_id = f"{target.case_id}-turn-{turn}"
                records.append(
                    {
                        "turn": turn,
                        "turn_id": turn_id,
                        "request_sha256": "sha256:" + str(turn) * 64,
                        "dialogue_binding_sha256": "sha256:" + "9" * 64,
                        "terminal": {
                            "outcome": "proposed",
                            "generation_strategy": "model_create_plan_v2",
                            "compile_status": "ok",
                            "compile_attempts": 1,
                            "proposal_source_sha256": "sha256:" + "3" * 64,
                            "compiler_receipt_sha256": "sha256:" + "8" * 64,
                        },
                        "event_counts": {
                            "inference": 1,
                            "compile": 1,
                            "repair": 0,
                            "terminal": 1,
                        },
                        "qualification_proof": _qualification_receipt(
                            turn_id,
                            canonical_sha256(expected),
                            generation,
                        ),
                        "clarification_proof": None,
                        "clarification_sha256": None,
                    }
                )
            else:
                records.append(
                    {
                        "turn": turn,
                        "turn_id": f"{target.case_id}-turn-{turn}",
                        "request_sha256": "sha256:" + str(turn) * 64,
                        "dialogue_binding_sha256": "sha256:" + "9" * 64,
                        "terminal": {"outcome": "needs_clarification"},
                        "event_counts": {
                            "inference": 0,
                            "compile": 0,
                            "repair": 0,
                            "terminal": 1,
                        },
                        "qualification_proof": None,
                        "clarification_proof": _clarification_receipt(
                            f"{target.case_id}-turn-{turn}",
                            qualification._normalized_gap_key(  # noqa: SLF001
                                stage["missing"][0]["slot"]
                            ),
                        ),
                        "clarification_sha256": "sha256:" + "0" * 64,
                    }
                )
        journeys.append({"case_id": target.case_id, "turns": records})
    return journeys


def test_post_close_assessment_separates_ready_from_authority_blocked() -> None:
    spec = qualification.load_complex_create_qualification()
    result = qualification.assess_complex_create_after_close(spec, _passing_observations())

    assert result["initial_ask"]["passed"] == 10
    assert result["ready"] == {
        **result["ready"],
        "total": 6,
        "passed": 6,
    }
    assert result["authority_blocked"]["total"] == 24
    assert result["authority_blocked"]["safely_blocked"] == 24
    assert all(item["expected_missing_slots"] for item in result["authority_blocked"]["stages"])


def test_post_close_assessment_detects_one_wrong_private_spec_hash() -> None:
    spec = qualification.load_complex_create_qualification()
    observations = _passing_observations()
    ready = next(
        record
        for journey in observations
        for record in journey["turns"]
        if isinstance(record.get("qualification_proof"), dict)
    )
    ready["qualification_proof"]["spec_sha256"] = "sha256:" + "f" * 64

    result = qualification.assess_complex_create_after_close(spec, observations)
    assert result["ready"]["passed"] == 5


def test_post_close_assessment_rejects_self_hashed_forged_draft_receipt() -> None:
    spec = qualification.load_complex_create_qualification()
    observations = _passing_observations()
    ready = next(
        record
        for journey in observations
        for record in journey["turns"]
        if isinstance(record.get("qualification_proof"), dict)
    )
    proof = ready["qualification_proof"]
    proof["contract_id"] = "forged-contract/v1"
    proof["turn_id"] = "forged-turn"
    proof["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in proof.items() if key != "receipt_sha256"}
    )

    result = qualification.assess_complex_create_after_close(spec, observations)
    assert result["ready"]["passed"] == 5


def test_post_close_assessment_rejects_an_arbitrary_blocking_question() -> None:
    spec = qualification.load_complex_create_qualification()
    observations = _passing_observations()
    blocked = next(
        record
        for journey in observations
        for record in journey["turns"][1:]
        if record["terminal"]["outcome"] == "needs_clarification"
    )
    blocked["clarification_proof"] = _clarification_receipt(
        blocked["turn_id"], "endpoint.unrelated"
    )

    result = qualification.assess_complex_create_after_close(spec, observations)
    assert result["authority_blocked"]["safely_blocked"] == 23


def test_post_close_assessment_rejects_a_self_hashed_wrong_dialogue_binding() -> None:
    spec = qualification.load_complex_create_qualification()
    observations = _passing_observations()
    blocked = next(
        record
        for journey in observations
        for record in journey["turns"][1:]
        if record["terminal"]["outcome"] == "needs_clarification"
    )
    proof = blocked["clarification_proof"]
    proof["binding_sha256"] = "sha256:" + "e" * 64
    proof["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in proof.items() if key != "receipt_sha256"}
    )

    result = qualification.assess_complex_create_after_close(spec, observations)
    assert result["authority_blocked"]["safely_blocked"] == 23


@pytest.mark.parametrize("mutation", ["round", "slot_contract"])
def test_post_close_assessment_enforces_the_producer_clarification_bounds(
    mutation: str,
) -> None:
    spec = qualification.load_complex_create_qualification()
    observations = _passing_observations()
    blocked = next(
        record
        for journey in observations
        for record in journey["turns"][1:]
        if record["terminal"]["outcome"] == "needs_clarification"
    )
    proof = blocked["clarification_proof"]
    if mutation == "round":
        proof["round"] = 4
    else:
        proof["slot_contracts"][0]["answer_kind"] = "option_ref"
        proof["slot_contracts_sha256"] = canonical_sha256(proof["slot_contracts"])
    proof["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in proof.items() if key != "receipt_sha256"}
    )

    result = qualification.assess_complex_create_after_close(spec, observations)
    assert result["authority_blocked"]["safely_blocked"] == 23


@pytest.mark.parametrize("mutation", ["duplicate_ordinal", "duplicate_turn_id", "bad_request_hash"])
def test_post_close_assessment_rejects_malformed_journey_records(mutation: str) -> None:
    spec = qualification.load_complex_create_qualification()
    observations = _passing_observations()
    records = observations[0]["turns"]
    if mutation == "duplicate_ordinal":
        records[1]["turn"] = 1
    elif mutation == "duplicate_turn_id":
        records[1]["turn_id"] = records[0]["turn_id"]
    else:
        records[1]["request_sha256"] = "not-a-hash"

    with pytest.raises(BrainError, match="journey (roster|record) differs"):
        qualification.assess_complex_create_after_close(spec, observations)


@pytest.mark.parametrize(("green", "expected_exit"), ((True, 0), (False, 2)))
def test_complex_create_cli_reports_the_measured_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    green: bool,
    expected_exit: int,
) -> None:
    output = tmp_path / "receipt.json"
    receipt = {
        "status": "MEASURED",
        "denominator": deepcopy(qualification.EXPECTED_DENOMINATOR),
        "assessment": {
            "initial_ask": {"total": 10, "passed": 10},
            "ready": {"total": 6, "passed": 6 if green else 5},
            "authority_blocked": {"total": 24, "safely_blocked": 24},
        },
        "qualification_green": green,
        "receipt_sha256": "sha256:" + "a" * 64,
    }
    monkeypatch.setattr(cli, "run_complex_create_qualification", lambda **_kwargs: receipt)

    result = cli.main(
        [
            "brain-complex-create-qualification",
            "--config",
            str(qualification.PROJECT_ROOT / "config.json"),
            "--output",
            str(output),
            "--authorize-local-model-execution",
        ]
    )

    assert result == expected_exit
    payload = json.loads(capsys.readouterr().out)
    assert payload["qualification_green"] is green
    assert payload["assessment"]["ready"]["passed"] == (6 if green else 5)
    assert payload["receipt_path"] == str(output)


def test_complex_create_cli_fails_closed_without_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def blocked(**_kwargs: Any) -> dict[str, Any]:
        raise BrainError("COMPLEX_CREATE_NOT_AUTHORIZED", 403, "authorization required")

    monkeypatch.setattr(cli, "run_complex_create_qualification", blocked)
    result = cli.main(
        [
            "brain-complex-create-qualification",
            "--config",
            str(qualification.PROJECT_ROOT / "config.json"),
            "--output",
            str(tmp_path / "receipt.json"),
        ]
    )

    assert result == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "COMPLEX_CREATE_NOT_AUTHORIZED"


def test_failed_live_run_writes_one_redacted_partial_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = qualification.load_complex_create_qualification()
    output = tmp_path / "receipt.json"
    written: dict[str, Any] = {}
    services: list[Any] = []
    model_guard = {"head": "model-head"}
    tenant_guard = {
        "commit": spec.tenant_head,
        "tree": spec.tenant_tree,
        "status_sha256": "sha256:" + "1" * 64,
        "roster_sha256": "sha256:" + "2" * 64,
        "target_sha256": "sha256:" + "3" * 64,
    }

    class FailingService:
        closed = False

        def __init__(self, _config: Any) -> None:
            services.append(self)

        def start_background(self) -> None:
            raise BrainError("MODEL_UNAVAILABLE", 503, "model unavailable")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(qualification.hard, "_prepare_output", lambda _path: output)
    monkeypatch.setattr(
        qualification.hard,
        "_write_receipt",
        lambda path, receipt: written.update(path=path, receipt=deepcopy(receipt)),
    )
    monkeypatch.setattr(qualification, "MetisBrainService", FailingService)
    monkeypatch.setattr(qualification, "capture_model1_guard", lambda: deepcopy(model_guard))
    monkeypatch.setattr(
        qualification, "capture_tenant_guard", lambda **_kwargs: deepcopy(tenant_guard)
    )

    receipt = qualification.run_complex_create_qualification(
        config_path=spec.config_path,
        output_path=output,
        authorize_local_model_execution=True,
    )

    assert receipt["status"] == "INCOMPLETE"
    assert receipt["measurement_status"] == "PARTIAL"
    assert receipt["qualification_green"] is False
    assert receipt["assessment"] is None
    assert receipt["completed"] == {"journeys": 0, "operator_messages": 0}
    assert receipt["boundary"]["blueprints_loaded"] is False
    assert receipt["boundary"]["blueprint_load_phase"] is None
    assert receipt["identity"]["health_before_sha256"] is None
    assert receipt["identity"]["health_after_sha256"] is None
    assert receipt["terminal_gate"] == {
        "status": "FAILED",
        "phase": "startup",
        "code": "MODEL_UNAVAILABLE",
    }
    assert written["receipt"] == receipt
    assert written["path"] != output
    assert written["path"].name.startswith("receipt.incomplete-")
    assert len(services) == 1 and services[0].closed is True


def test_blueprint_oracle_is_never_opened_when_service_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = qualification.load_complex_create_qualification()
    output = tmp_path / "receipt.json"
    model_guard = {"head": "model-head"}
    tenant_guard = {
        "commit": spec.tenant_head,
        "tree": spec.tenant_tree,
        "status_sha256": "sha256:" + "1" * 64,
        "roster_sha256": "sha256:" + "2" * 64,
        "target_sha256": "sha256:" + "3" * 64,
    }

    class CloseFailingService:
        address = ("127.0.0.1", 9797)
        app = SimpleNamespace(compiler=SimpleNamespace(pin_identity={"revision": "pin"}))

        def __init__(self, _config: Any) -> None:
            pass

        def start_background(self) -> None:
            pass

        def close(self) -> None:
            raise RuntimeError("synthetic close failure")

    class FakeHeadlessClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def health(self) -> dict[str, Any]:
            return {"status": "ready"}

    def forbidden_blueprint_read(_spec: Any) -> dict[str, Any]:
        raise AssertionError("blueprint oracle was opened before a proven close")

    monkeypatch.setattr(qualification.hard, "_prepare_output", lambda _path: output)
    monkeypatch.setattr(qualification.hard, "_write_receipt", lambda *_args: None)
    monkeypatch.setattr(qualification.hard, "_bootstrap_token", lambda _service: "token")
    monkeypatch.setattr(qualification, "MetisBrainService", CloseFailingService)
    monkeypatch.setattr(qualification.hard, "HeadlessBrainClient", FakeHeadlessClient)
    monkeypatch.setattr(
        qualification,
        "_validate_typed_create_health",
        lambda _health, **_kwargs: {},
    )
    monkeypatch.setattr(qualification.hard, "_validate_qualified_health", lambda *_a, **_k: {})
    monkeypatch.setattr(
        qualification,
        "_run_journey",
        lambda **kwargs: {
            "case_id": kwargs["target"].case_id,
            "turns": [{"turn": index} for index in range(1, 5)],
        },
    )
    monkeypatch.setattr(qualification, "_load_blueprint_stages", forbidden_blueprint_read)
    monkeypatch.setattr(qualification, "capture_model1_guard", lambda: deepcopy(model_guard))
    monkeypatch.setattr(
        qualification, "capture_tenant_guard", lambda **_kwargs: deepcopy(tenant_guard)
    )

    receipt = qualification.run_complex_create_qualification(
        config_path=spec.config_path,
        output_path=output,
        authorize_local_model_execution=True,
    )

    assert receipt["measurement_status"] == "COMPLETE"
    assert receipt["assessment"] is None
    assert receipt["boundary"]["blueprints_loaded"] is False
    assert receipt["terminal_gate"] == {
        "status": "FAILED",
        "phase": "close",
        "code": "RuntimeError",
    }
