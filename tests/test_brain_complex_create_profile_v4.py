from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_complex_create_qualification as qualification
import metis_model1.cli as cli
from metis_model1.brain_create_builder import render_create_endpoint
from metis_model1.brain_create_structural_authority_v2 import (
    initial_family_need,
    presemantic_structural_need,
)
from metis_model1.brain_create_surface import CreateAuthorityHistoryMessage
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256


def _v4_spec() -> qualification.ComplexCreateQualificationSpec:
    return qualification.load_complex_create_qualification(
        prompt_path=qualification.V4_PROMPT_PATH,
        plan_path=qualification.V4_PLAN_PATH,
    )


def _history(messages: list[str]) -> tuple[CreateAuthorityHistoryMessage, ...]:
    return tuple(
        CreateAuthorityHistoryMessage(
            ordinal=index,
            text=message,
            message_sha256=bytes_sha256(message.encode("utf-8")),
        )
        for index, message in enumerate(messages)
    )


def test_v4_is_an_exact_disjoint_ten_by_four_profile() -> None:
    v3 = qualification.load_complex_create_qualification()
    v4 = _v4_spec()

    assert v4.profile.profile_id == "play-prod-v4"
    assert v4.profile.denominator_map() == {
        "journeys": 10,
        "operator_messages": 40,
        "initial_ask_stages": 10,
        "assessed_stages": 30,
        "expected_ready": 9,
        "expected_blocked": 21,
    }
    assert [item["case_id"] for item in v4.prompt["journeys"]] == [
        f"case_{index:02d}" for index in range(11, 21)
    ]
    assert sum(len(item["messages"]) for item in v4.prompt["journeys"]) == 40
    assert [target.endpoint for target in v4.targets] == [
        f"brain_qualification_v4.case_{index:02d}" for index in range(11, 21)
    ]
    assert {target.scenario_id for target in v4.targets}.isdisjoint(
        target.scenario_id for target in v3.targets
    )
    prompt_wire = json.dumps(v4.prompt["journeys"], ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "brain_qualification",
        "source_path",
        "source_endpoint",
        "blueprint",
        "expected_spec",
    ):
        assert forbidden not in prompt_wire


def test_v4_prompt_and_plan_pair_cannot_be_mixed_or_self_registered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[Path] = []

    def forbidden_read(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
        del label
        opened.append(path)
        raise AssertionError("an unregistered pair must fail before reading input")

    monkeypatch.setattr(qualification, "_read_json", forbidden_read)
    with pytest.raises(BrainError, match="qualification paths differ"):
        qualification.load_complex_create_qualification(
            prompt_path=qualification.PROMPT_PATH,
            plan_path=qualification.V4_PLAN_PATH,
        )
    with pytest.raises(BrainError, match="qualification paths differ"):
        qualification.load_complex_create_qualification(
            prompt_path=tmp_path / "prompts.json",
            plan_path=tmp_path / "plan.json",
        )
    assert opened == []


def test_v4_loader_opens_only_prompt_and_plan_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = qualification._read_json  # noqa: SLF001
    opened: list[str] = []

    def guarded(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
        opened.append(path.name)
        assert "blueprints" not in path.name
        return original(path, label=label)

    monkeypatch.setattr(qualification, "_read_json", guarded)
    _v4_spec()
    assert opened == [
        "metis-brain-complex-create-prompts.play-prod-v4.json",
        "metis-brain-complex-create-qualification.play-prod-v4.json",
    ]


def test_v4_blueprint_has_exact_prompt_derived_denominator_and_self_hashes() -> None:
    spec = _v4_spec()
    payload = json.loads(
        (qualification.PROJECT_ROOT / "examples/metis-brain-create-blueprints-v4.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["schema_version"] == 4
    assert [item["scenario_id"] for item in payload["scenarios"]] == [
        target.scenario_id for target in spec.targets
    ]
    stages = [
        (scenario["scenario_id"], stage)
        for scenario in payload["scenarios"]
        for stage in scenario["stages"]
    ]
    assert len(stages) == len({f"{owner}:{stage['stage_id']}" for owner, stage in stages}) == 30
    assert sum(stage["status"] == "ready" for _owner, stage in stages) == 9
    assert sum(stage["status"] == "needs_clarification" for _owner, stage in stages) == 21
    for _owner, stage in stages:
        if stage["status"] == "ready":
            assert stage["missing"] == []
            assert canonical_sha256(stage["spec"]) == stage["spec_sha256"]
            assert render_create_endpoint(stage["spec"]).metis_text.startswith("metis ")
        else:
            assert stage["spec"] is None
            assert stage["spec_sha256"] is None
            assert stage["missing"]
            assert all(
                qualification._normalized_gap_key(item["slot"]) is not None  # noqa: SLF001
                for item in stage["missing"]
            )


def test_v4_blueprint_matches_the_code_owned_prompt_recognizer() -> None:
    spec = _v4_spec()
    stages = qualification._load_blueprint_stages(spec)  # noqa: SLF001
    initial_gaps = spec.profile.initial_gap_map()

    for target, journey in zip(spec.targets, spec.prompt["journeys"], strict=True):
        messages = journey["messages"]
        initial = initial_family_need(messages[0])
        assert initial is not None and initial[1] == initial_gaps[target.case_id]
        generation = 0
        for turn in (2, 3, 4):
            stage = stages[f"{target.scenario_id}:T{turn}"]
            need = presemantic_structural_need(
                _history(messages[:turn]),
                generation=generation,
            )
            if need is None:
                assert stage["status"] == "ready"
                generation += 1
            else:
                assert stage["status"] == "needs_clarification"
                assert need.target_key in {item["slot"] for item in stage["missing"]}


def test_v4_operator_document_contains_the_exact_forty_prompts() -> None:
    spec = _v4_spec()
    document = (
        qualification.PROJECT_ROOT / "docs/32-metis-brain-complex-create-demo-prompts.md"
    ).read_text(encoding="utf-8")
    found = {
        (case_id, int(turn)): body
        for case_id, turn, body in re.findall(
            r"<!-- prompt:(case_[0-9]{2}):([1-4]) -->\n```text\n([^\n]+)\n```",
            document,
        )
    }
    expected = {
        (journey["case_id"], turn): message
        for journey in spec.prompt["journeys"]
        for turn, message in enumerate(journey["messages"], start=1)
    }
    assert found == expected
    for forbidden in ("spec_sha256", "expected_gap", "source_path", "oracle"):
        assert forbidden not in document


def test_complex_create_cli_forwards_the_explicit_v4_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    def run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "status": "MEASURED",
            "denominator": qualification.V4_EXPECTED_DENOMINATOR,
            "assessment": {},
            "qualification_green": True,
            "receipt_sha256": "sha256:" + "a" * 64,
        }

    monkeypatch.setattr(cli, "run_complex_create_qualification", run)
    output = tmp_path / "receipt.json"
    result = cli.main(
        [
            "brain-complex-create-qualification",
            "--config",
            str(qualification._V4_PROFILE.config_path),  # noqa: SLF001
            "--corpus",
            str(qualification.V4_PROMPT_PATH),
            "--plan",
            str(qualification.V4_PLAN_PATH),
            "--output",
            str(output),
            "--authorize-local-model-execution",
        ]
    )

    assert result == 0
    assert captured["prompt_path"] == qualification.V4_PROMPT_PATH
    assert captured["plan_path"] == qualification.V4_PLAN_PATH
    assert captured["output_path"] == output
    assert captured["authorize_local_model_execution"] is True
    assert json.loads(capsys.readouterr().out)["qualification_green"] is True
