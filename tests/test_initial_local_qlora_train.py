import json
import os
from pathlib import Path

import pytest

from metis_model1 import initial_local_qlora_train as train


def test_training_command_is_the_single_exact_configuration() -> None:
    step25 = train._command(25)
    assert step25.count("--lora-rank") == 1
    assert step25[step25.index("--lora-rank") + 1] == "8"
    assert step25[step25.index("--lora-alpha") + 1] == "16"
    assert step25[step25.index("--learning-rate") + 1] == "1e-5"
    assert step25[step25.index("--max-seq-length") + 1] == "1024"
    assert step25[step25.index("--dataset") + 1].endswith("/dataset/train.jsonl")
    assert "--resume" not in step25
    step50 = train._command(50)
    assert step50[step50.index("--resume") + 1].endswith("step-00000025")
    step100 = train._command(100)
    assert step100[step100.index("--resume") + 1].endswith("step-00000050")
    with pytest.raises(train.TrainingContractError):
        train._command(26)


def test_checkpoint_rosters_hold_the_four_checkpoint_cap() -> None:
    assert train.AFTER_CHECKPOINTS == {
        25: [25],
        50: [25, 50],
        100: [25, 50, 75, 100],
    }
    assert (
        max(len(value) for value in train.AFTER_CHECKPOINTS.values()) == train.LIMITS["checkpoints"]
    )


def test_artifact_census_rejects_symlinks(tmp_path, monkeypatch) -> None:
    root = tmp_path / "wave"
    root.mkdir()
    (root / "safe.json").write_text("{}")
    monkeypatch.setattr(train, "ARTIFACT_ROOT", root)
    monkeypatch.setattr(train, "CHECKPOINT_ROOT", root / "checkpoints")
    assert train.artifact_census()["bytes"] == 2
    (root / "link").symlink_to(Path("safe.json"))
    with pytest.raises(train.TrainingContractError, match="unsafe"):
        train.artifact_census()


def test_started_phase_marker_is_part_of_no_retry_contract() -> None:
    source = Path(train.__file__).read_text()
    assert "started_no_retry" in source
    assert "training phase output already exists; retries are forbidden" in source
    assert "cumulative four-hour cap" in source


def test_training_environment_is_a_closed_credential_free_allowlist() -> None:
    environment = train._training_environment()
    assert set(environment) == {
        "PATH",
        "LANG",
        "LC_ALL",
        "HOME",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "HF_HOME",
        "HF_DATASETS_CACHE",
        "TRANSFORMERS_CACHE",
        "HF_HUB_OFFLINE",
        "HF_DATASETS_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "TOKENIZERS_PARALLELISM",
        "PYTHONNOUSERSITE",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
    }
    assert set(environment).isdisjoint(
        {
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "SSH_AUTH_SOCK",
            "HF_TOKEN",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
        }
    )


def test_step50_continuation_failure_precedes_marker_and_popen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(train, "verify_freeze", lambda **_kwargs: {"freeze_sha256": "x"})
    monkeypatch.setattr(train, "_checkpoint_steps", lambda: [25])
    monkeypatch.setattr(train, "_verified_phase_receipt", lambda *_args: {})
    monkeypatch.setattr(
        train,
        "verify_continuation_gate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            train.TrainingContractError("step25 gain missing")
        ),
    )
    monkeypatch.setattr(train, "RUN_ROOT", tmp_path / "run")
    started = {"popen": False}

    def forbidden_popen(*_args, **_kwargs):
        started["popen"] = True
        raise AssertionError("optimizer must not start")

    monkeypatch.setattr(train.subprocess, "Popen", forbidden_popen)
    with pytest.raises(train.TrainingContractError, match="gain missing"):
        train.run_step(50)
    assert started["popen"] is False
    assert not (tmp_path / "run/phase-step50-started.json").exists()


def test_live_artifact_cap_terminates_the_process(monkeypatch) -> None:
    class Process:
        pid = 123

        def poll(self):
            return None

    stopped = []
    monkeypatch.setattr(
        train,
        "_artifact_usage",
        lambda: (_ for _ in ()).throw(train.TrainingContractError("8 GiB")),
    )
    monkeypatch.setattr(train, "_terminate_tree", lambda process: stopped.append(process.pid))
    with pytest.raises(train.TrainingContractError, match="8 GiB"):
        train._wait_with_live_caps(Process(), deadline=10**12)
    assert stopped == [123]


def test_artifact_usage_rejects_hardlinks(tmp_path, monkeypatch) -> None:
    root = tmp_path / "wave"
    root.mkdir()
    original = root / "original"
    original.write_text("x")
    os.link(original, root / "linked")
    monkeypatch.setattr(train, "ARTIFACT_ROOT", root)
    with pytest.raises(train.TrainingContractError, match="hard-linked"):
        train._artifact_usage()


def test_sandbox_canary_allows_only_the_wave_output(tmp_path, monkeypatch) -> None:
    run_root = tmp_path.resolve() / "run"
    monkeypatch.setattr(train, "RUN_ROOT", run_root)
    monkeypatch.setattr(train, "CHECKPOINT_ROOT", run_root / "checkpoints")
    for path in (run_root / "tmp", run_root / "offline-cache", run_root / "home"):
        path.mkdir(parents=True, exist_ok=True)
    result = train._sandbox_canary(25, train._training_environment())
    assert result["status"] == "pass"
    assert result["forbidden_project_write"] == "denied"


def test_run_v2_and_freeze_v2_are_separate_from_legacy_baseline() -> None:
    assert train.RUN_ROOT.name == "run-v2"
    assert train.RUN_ROOT != train.LEGACY_RUN_ROOT
    assert train.PRIOR_FREEZE_PATH.name.endswith("freeze-v1.json")
    assert train.FREEZE_PATH.name.endswith("freeze-v2.json")
    assert train.PRIOR_FREEZE_PATH != train.FREEZE_PATH

    policy = train._training_sandbox_policy(25)
    assert str(train.LEGACY_RUN_ROOT.resolve()) not in policy


def test_baseline_reuse_manifest_self_hash_is_valid() -> None:
    manifest = train._reuse_manifest()
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    assert manifest["manifest_sha256"] == train.REUSE_MANIFEST_SELF_SHA256
    assert manifest["manifest_sha256"] == train._canonical_hash(body)


def _legacy_baseline_fixture(tmp_path):
    root = tmp_path / "run-v1"
    base = root / "base-dev"
    for directory in (
        base,
        root / "evaluation-cache/home",
        root / "evaluation-cache/tmp",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    candidates = base / "candidates.jsonl"
    candidates.write_text("{}\n")
    generation_body = {"schema_version": 1, "status": "complete"}
    generation = {**generation_body, "report_sha256": train._canonical_hash(generation_body)}
    (base / "generation.json").write_text(json.dumps(generation))
    semantic_body = {"schema_version": 1, "status": "verified"}
    semantic = {**semantic_body, "report_sha256": train._canonical_hash(semantic_body)}
    (base / "semantic.json").write_text(json.dumps(semantic))
    files = {}
    for name in ("candidates.jsonl", "generation.json", "semantic.json"):
        path = base / name
        record = {"bytes": path.stat().st_size, "sha256": train._file_hash(path)}
        if name in {"generation.json", "semantic.json"}:
            record["self_sha256"] = json.loads(path.read_text())["report_sha256"]
        files[name] = record
    return root, {"source": {"base_dev": {"files": files}}}


def test_legacy_base_state_accepts_only_exact_regular_baseline(tmp_path, monkeypatch) -> None:
    root, manifest = _legacy_baseline_fixture(tmp_path)
    monkeypatch.setattr(train, "LEGACY_RUN_ROOT", root)

    state = train._legacy_base_state(manifest)

    assert state["checkpoint_steps"] == []
    assert state["training_started"] is False


@pytest.mark.parametrize("mutation", ["extra", "symlink", "hardlink"])
def test_legacy_base_state_rejects_extra_symlink_or_hardlink(
    tmp_path, monkeypatch, mutation
) -> None:
    root, manifest = _legacy_baseline_fixture(tmp_path)
    monkeypatch.setattr(train, "LEGACY_RUN_ROOT", root)
    source = root / "base-dev/candidates.jsonl"
    target = root / f"{mutation}-entry"
    if mutation == "extra":
        target.write_text("unexpected\n")
    elif mutation == "symlink":
        target.symlink_to(source)
    else:
        target.hardlink_to(source)

    with pytest.raises(train.TrainingContractError, match="legacy run-v1"):
        train._legacy_base_state(manifest)
