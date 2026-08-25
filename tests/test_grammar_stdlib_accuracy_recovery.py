from __future__ import annotations

import json
from pathlib import Path

import pytest

from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import grammar_stdlib_accuracy as d18
from metis_model1 import grammar_stdlib_accuracy_recovery as recovery


def _record(path: str, digest: str = "a") -> dict[str, object]:
    return {
        "path": path,
        "bytes": 1,
        "sha256": "sha256:" + digest * 64,
        "git_blob_oid": digest * 40,
    }


def _candidate_records() -> list[dict[str, object]]:
    return [
        {
            "path": relative,
            "bytes": 10,
            "sha256": "sha256:" + character * 64,
            "rows": 18,
            "mode": 0o600,
        }
        for relative, character in zip(recovery.FIXED_CANDIDATE_RELATIVES, ("a", "b"), strict=True)
    ]


def _original_freeze() -> dict[str, object]:
    value: dict[str, object] = {
        "status": "frozen_before_model_output",
        "authority_tier": "automatic",
        "generation": d18.GENERATION,
        "thresholds": d18.THRESHOLDS,
        "semantic_signature_contract": d18.SEMANTIC_SIGNATURE_CONTRACT,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "preimage_commit": "c" * 40,
        "preimage_tree": "d" * 40,
        "remote": "origin",
        "remote_ref": recovery.ORIGINAL_REMOTE_REF,
        "run_id": recovery.FIXED_RUN_ID,
        "run_dir": recovery.FIXED_RUN_RELATIVE,
        "bound_inputs": [_record(path) for path in d18.BOUND_PATHS],
    }
    value["freeze_sha256"] = recovery.canonical_hash(value)
    return value


def _recovery_freeze() -> dict[str, object]:
    original = _original_freeze()
    value: dict[str, object] = {
        "schema_version": 1,
        "recovery_id": recovery.RECOVERY_ID,
        "status": recovery.RECOVERY_STATUS,
        "preimage_commit": "e" * 40,
        "preimage_tree": "f" * 40,
        "remote": "origin",
        "remote_ref": recovery.ORIGINAL_REMOTE_REF,
        "original_freeze_file": _record(
            str(d18.FREEZE_PATH.relative_to(recovery.PROJECT_ROOT)), "1"
        ),
        "original_freeze_sha256": original["freeze_sha256"],
        "original_preimage_commit": original["preimage_commit"],
        "original_preimage_tree": original["preimage_tree"],
        "original_bound_inputs": original["bound_inputs"],
        "recovery_bound_inputs": [_record(recovery.RECOVERY_SIDE_CAR_PATH, "2")],
        "candidate_inputs": _candidate_records(),
        "source_failure": recovery.SOURCE_FAILURE,
        "model_outputs_observed": True,
        "candidate_origin_attested": False,
        **recovery.NO_MODEL_CALLS,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": recovery.RECOVERY_NONCLAIMS,
    }
    value["recovery_freeze_sha256"] = recovery.canonical_hash(value)
    return value


def test_recovery_source_has_no_worker_or_model_command() -> None:
    source = Path(recovery.__file__).read_text(encoding="utf-8")
    assert "_bounded_worker" not in source
    assert "_worker_command" not in source
    assert "SANDBOX_EXEC" not in source
    assert 'additional_model_calls": 0' in source


def test_recovery_freeze_is_self_hashed_and_explicitly_no_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _original_freeze()
    candidate_records = _candidate_records()
    sidecar = _record(recovery.RECOVERY_SIDE_CAR_PATH, "2")
    monkeypatch.setattr(recovery, "_published", lambda _remote, _ref: ("e" * 40, "f" * 40))
    monkeypatch.setattr(recovery, "_load", lambda _path, _label: (original, b"original"))
    monkeypatch.setattr(
        recovery,
        "_pinned_tracked_record",
        lambda path: sidecar if path == recovery.RECOVERY_SIDE_CAR_PATH else _record(path, "1"),
    )
    monkeypatch.setattr(
        recovery, "_verify_original_freeze", lambda *_args, **_kwargs: Path("/tmp/d18")
    )
    monkeypatch.setattr(d18, "_verify_frozen_inputs", lambda *_args, **_kwargs: ([], {}, b""))
    monkeypatch.setattr(recovery, "_verify_partial_roster", lambda _run: candidate_records)

    value = recovery.build_recovery_freeze("origin", d18.DEFAULT_METIS_ROOT, d18.DEFAULT_NODE)

    assert value["recovery_freeze_sha256"] == recovery.canonical_hash(
        {key: item for key, item in value.items() if key != "recovery_freeze_sha256"}
    )
    assert value["original_freeze_sha256"] == original["freeze_sha256"]
    assert value["candidate_inputs"] == candidate_records
    assert value["source_failure"] == recovery.SOURCE_FAILURE
    assert value["model_outputs_observed"] is True
    assert value["candidate_origin_attested"] is False
    assert value["model_replay"] is False
    assert value["additional_model_calls"] == 0
    assert value["training_authorized"] is False
    assert value["delta_qlora_authorized"] is False


def test_recovery_freeze_rejects_schema_and_hash_drift() -> None:
    value = _recovery_freeze()
    value["unexpected"] = True
    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="field roster"):
        recovery._verify_recovery_freeze(value, b"recovery", "e" * 40)

    value = _recovery_freeze()
    value["additional_model_calls"] = 1
    value["recovery_freeze_sha256"] = recovery.canonical_hash(
        {key: item for key, item in value.items() if key != "recovery_freeze_sha256"}
    )
    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="authority drift"):
        recovery._verify_recovery_freeze(value, b"recovery", "e" * 40)


@pytest.mark.parametrize(
    ("field", "altered"),
    (("remote", "fork"), ("remote_ref", "refs/heads/codex/altered")),
)
def test_recovery_freeze_rejects_alternate_publication_identity(field: str, altered: str) -> None:
    value = _recovery_freeze()
    value[field] = altered
    value["recovery_freeze_sha256"] = recovery.canonical_hash(
        {key: item for key, item in value.items() if key != "recovery_freeze_sha256"}
    )

    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="authority drift"):
        recovery._verify_recovery_freeze(value, b"recovery", "e" * 40)


def test_partial_roster_rejects_extra_symlink_and_candidate_contract_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    run_dir = root / recovery.FIXED_RUN_RELATIVE
    (run_dir / "base").mkdir(parents=True)
    (run_dir / "adapter").mkdir()
    for index, relative in enumerate(recovery.FIXED_CANDIDATE_RELATIVES):
        (root / relative).write_text(json.dumps({"row": index}) + "\n", encoding="utf-8")
        (root / relative).chmod(0o600)
    monkeypatch.setattr(recovery, "PROJECT_ROOT", root)
    monkeypatch.setattr(d18, "_assert_run_ancestors", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(d18, "_assert_direct_directory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(d18, "load_tasks", lambda: ({}, [], b""))
    monkeypatch.setattr(d18, "_read_candidates", lambda *_args: [])
    monkeypatch.setattr(
        recovery,
        "FIXED_CANDIDATE_HASHES",
        {
            relative: recovery.raw_hash((root / relative).read_bytes())
            for relative in recovery.FIXED_CANDIDATE_RELATIVES
        },
    )

    assert [item["rows"] for item in recovery._verify_partial_roster(run_dir)] == [18, 18]
    (run_dir / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="roster"):
        recovery._verify_partial_roster(run_dir)
    (run_dir / "extra.txt").unlink()
    (run_dir / "report.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="roster"):
        recovery._verify_partial_roster(run_dir)
    (run_dir / "report.json").unlink()
    (run_dir / "base" / "linked").symlink_to(run_dir / "adapter")
    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="symlink"):
        recovery._verify_partial_roster(run_dir)


def test_pinned_git_failure_is_wrapped_without_alternate_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejected(*_args, **_kwargs):
        raise catalog_pin.CatalogMaintenancePinError("cannot execute the pinned Git binary")

    monkeypatch.setattr(catalog_pin, "_run_git", rejected)
    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="pinned Git"):
        recovery._pinned_git(recovery.PROJECT_ROOT, "rev-parse", "HEAD")


def test_published_remote_lookup_stays_inside_the_pinned_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, tree = "a" * 40, "b" * 40
    remote_ref = "refs/heads/codex/test"
    calls: list[tuple[Path | None, tuple[str, ...]]] = []

    def pinned(repository: Path | None, *args: str, **_kwargs: object) -> str:
        calls.append((repository, args))
        if args[0] == "status":
            return ""
        if args[:2] == ("rev-parse", "HEAD"):
            return head
        if args[0] == "ls-remote":
            return f"{head}\t{remote_ref}\n"
        if args[:2] == ("rev-parse", "HEAD^{tree}"):
            return tree
        raise AssertionError(args)

    monkeypatch.setattr(recovery, "_pinned_git", pinned)

    assert recovery._published("origin", remote_ref) == (head, tree)
    assert all(repository == recovery.PROJECT_ROOT for repository, _args in calls)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("freeze_id", "grammar-stdlib-accuracy-d18-freeze/altered"),
        ("model_outputs_observed", True),
        ("nonclaims", ["altered"]),
        ("truth_sha256", "sha256:" + "9" * 64),
    ),
)
def test_original_freeze_rejects_self_hashed_semantic_drift(field: str, value: object) -> None:
    original = json.loads(d18.FREEZE_PATH.read_text(encoding="utf-8"))
    original[field] = value
    original["freeze_sha256"] = recovery.canonical_hash(
        {key: item for key, item in original.items() if key != "freeze_sha256"}
    )

    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="pre-output seal"):
        recovery._verify_original_freeze(original, head="f" * 40)


def test_recovery_rejects_tampered_candidate_hash_before_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _recovery_freeze()
    original = _original_freeze()
    raw = b"recovery"
    recovery_path = str(recovery.RECOVERY_FREEZE_PATH.relative_to(recovery.PROJECT_ROOT))

    def tracked(path: str) -> dict[str, object]:
        if path == recovery_path:
            return {"sha256": recovery.raw_hash(raw)}
        return _record(recovery.RECOVERY_SIDE_CAR_PATH, "2")

    monkeypatch.setattr(recovery, "_pinned_tracked_record", tracked)
    monkeypatch.setattr(
        recovery,
        "_pinned_commit_record",
        lambda _commit, path: (
            value["original_freeze_file"]
            if path == str(d18.FREEZE_PATH.relative_to(recovery.PROJECT_ROOT))
            else value["recovery_bound_inputs"][0]
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_pinned_git",
        lambda _repo, *args, **_kwargs: "f" * 40 if args[0] == "rev-parse" else "",
    )
    monkeypatch.setattr(recovery, "_load", lambda *_args: (original, b"original"))
    monkeypatch.setattr(
        recovery, "_verify_original_freeze", lambda *_args, **_kwargs: Path("/tmp/d18")
    )
    monkeypatch.setattr(
        recovery,
        "_verify_partial_roster",
        lambda _run: [{**_candidate_records()[0], "sha256": "sha256:" + "9" * 64}],
    )

    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="candidate binding drift"):
        recovery._verify_recovery_freeze(value, raw, "e" * 40)


def test_recovery_rejects_sidecar_absent_from_recorded_preimage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _recovery_freeze()
    raw = b"recovery"
    recovery_path = str(recovery.RECOVERY_FREEZE_PATH.relative_to(recovery.PROJECT_ROOT))

    monkeypatch.setattr(
        recovery,
        "_pinned_tracked_record",
        lambda path: (
            {"sha256": recovery.raw_hash(raw)}
            if path == recovery_path
            else value["recovery_bound_inputs"][0]
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_pinned_git",
        lambda _repo, *args, **_kwargs: "f" * 40 if args[0] == "rev-parse" else "",
    )

    def at_preimage(_commit: str, path: str) -> dict[str, object]:
        if path == str(d18.FREEZE_PATH.relative_to(recovery.PROJECT_ROOT)):
            return value["original_freeze_file"]
        raise recovery.GrammarStdlibRecoveryError("sidecar absent at recovery preimage")

    monkeypatch.setattr(recovery, "_pinned_commit_record", at_preimage)

    with pytest.raises(recovery.GrammarStdlibRecoveryError, match="absent at recovery preimage"):
        recovery._verify_recovery_freeze(value, raw, "e" * 40)


def test_recover_builds_lineaged_report_without_model_execution(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recovery_freeze = _recovery_freeze()
    original = _original_freeze()
    candidates = _candidate_records()
    tasks = [{"task_id": f"task-{item}"} for item in range(18)]
    truth = {"tasks": [{"task_id": task["task_id"]} for task in tasks]}
    written: dict[str, object] = {}

    monkeypatch.setattr(recovery, "_load", lambda *_args: (recovery_freeze, b"recovery"))
    monkeypatch.setattr(recovery, "_published", lambda *_args: ("e" * 40, "f" * 40))
    monkeypatch.setattr(
        recovery, "_verify_recovery_freeze", lambda *_args: (original, Path("/tmp/d18"))
    )
    monkeypatch.setattr(d18, "_verify_frozen_inputs", lambda *_args: (tasks, truth, b""))
    monkeypatch.setattr(recovery, "_pinned_git", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        d18,
        "_read_candidates",
        lambda _path, _tasks: [
            {"request_id": task["task_id"], "text": "candidate", "peak_metal_gb": 1.0}
            for task in _tasks
        ],
    )
    monkeypatch.setattr(
        d18,
        "score_candidate",
        lambda task, *_args: {"task_id": task["task_id"], "semantic_correct": True},
    )
    monkeypatch.setattr(recovery, "_verify_partial_roster", lambda _run: candidates)
    monkeypatch.setattr(
        d18, "gate_arithmetic", lambda *_args: {"verdict": "GRAMMAR_STDLIB_D18_PASS"}
    )
    monkeypatch.setattr(
        d18,
        "_write_run_file",
        lambda _run, _directory, _name, raw: written.setdefault("raw", raw),
    )
    monkeypatch.setattr(d18, "_verify_run_roster", lambda _run: set())
    monkeypatch.setattr(recovery, "_verify_candidate_records", lambda _run: candidates)
    monkeypatch.setattr(
        recovery,
        "_direct_file",
        lambda _path, _label: bytes(written["raw"]),
    )

    result = recovery.recover(recovery.parser().parse_args(["recover", "--remote", "origin"]))

    assert result == 0
    report = json.loads(bytes(written["raw"]).decode("utf-8"))
    assert report["status"] == "complete_recovered_candidate_replay"
    assert report["recovery"] == {
        "recovery_freeze_sha256": recovery_freeze["recovery_freeze_sha256"],
        "original_freeze_file_sha256": recovery_freeze["original_freeze_file"]["sha256"],
        "source_failure": recovery.SOURCE_FAILURE,
        "model_replay": False,
        "additional_model_calls": 0,
        "candidate_origin_attested": False,
    }
    assert report["training_authorized"] is False
    assert report["delta_qlora_authorized"] is False
    assert json.loads(capsys.readouterr().out)["event"] == "grammar_stdlib_d18_recover"
