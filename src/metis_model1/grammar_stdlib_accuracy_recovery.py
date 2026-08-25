"""Fail-closed post-output replay for the sealed D18 grammar/stdlib run.

This sidecar exists solely for the case where D18 has already written its two
canonical candidate rosters but could not publish ``report.json``.  It never
starts a worker or makes a model call.  Instead it seals the observed candidate
files, re-establishes every original D18 input through the exact system-Git
pin, and replays the pinned oracle scoring.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import grammar_stdlib_accuracy as d18

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECOVERY_FREEZE_PATH = PROJECT_ROOT / "manifests/grammar-stdlib-accuracy-d18-recovery-v1.json"
RECOVERY_SIDE_CAR_PATH = "src/metis_model1/grammar_stdlib_accuracy_recovery.py"
RECOVERY_ID = "grammar-stdlib-accuracy-d18-recovery/v1"
RECOVERY_STATUS = "frozen_after_candidates_before_report_replay"
ORIGINAL_FREEZE_PUBLICATION_COMMIT = "b36ff5b7768ab8337f82bd271d26a2f2c6afe14d"
ORIGINAL_FREEZE_SELF_SHA256 = (
    "sha256:730fb0ab6954652666ebd1b6d86bc82d392c55e214ff83be3f0c35d976b4df02"
)
ORIGINAL_FREEZE_FILE_SHA256 = (
    "sha256:ca9d5f6561a142656e7d4ae12bfb26c81aa413c6b88462549af10c6b4ba72fd3"
)
ORIGINAL_PREIMAGE_COMMIT = "4c0b32a03b5159e33f9b2c6955ffbc85e5c9e5f9"
ORIGINAL_PREIMAGE_TREE = "d472c02b1993fefb60504c023f5af183d9aa7595"
ORIGINAL_REMOTE = "origin"
ORIGINAL_REMOTE_REF = "refs/heads/codex/model1-local-99-foundation"
ORIGINAL_TRUTH_SHA256 = "sha256:0dff3f9279b00d50b3d7d544e0932bf7dcb02f3f26cd2608df2eae5b1048a542"
ORIGINAL_TASKS_SHA256 = "sha256:f2b30394c0729a0550f03f4d08e40a176c7de1cdbb9a05458cff329a44750c13"
ORIGINAL_REFERENCE_SHA256 = (
    "sha256:70fae1f40aca5c2417a825557c5a8e15e58a5dfbabd04d1fe81060ab56a643c0"
)
FIXED_RUN_ID = "d18-v1-20260825"
FIXED_RUN_RELATIVE = "artifacts/grammar-stdlib-accuracy/d18/d18-v1-20260825"
FIXED_CANDIDATE_RELATIVES = (
    FIXED_RUN_RELATIVE + "/base/candidates.jsonl",
    FIXED_RUN_RELATIVE + "/adapter/candidates.jsonl",
)
FIXED_CANDIDATE_HASHES = {
    FIXED_CANDIDATE_RELATIVES[
        0
    ]: "sha256:256b65c346978e3dd01db368d51157dccd20f8fc50c5144afec3ea1a1bd54c38",
    FIXED_CANDIDATE_RELATIVES[
        1
    ]: "sha256:2b254555a1cb991fb59fda39b29ac1b43ae7d1a0fd5feaf6c2b1e4dd22e951cd",
}
NO_MODEL_CALLS = {"model_replay": False, "additional_model_calls": 0}
SOURCE_FAILURE = {
    "kind": "post_generation_bound_verification_git_timeout",
    "phase": "after_candidate_scoring_before_report_publication",
    "exception": "subprocess.TimeoutExpired",
    "operation": "git show HEAD:fixtures/grammar-stdlib-accuracy-v1/d18-tasks.json",
    "timeout_seconds": 60,
    "report_observed": False,
}
RECOVERY_NONCLAIMS = [
    "not_clean_original_run_attestation",
    "candidate_origin_not_retroactively_attested",
    "no_model_replay",
    "no_training_authority",
    "no_delta_qlora_authority",
    "no_promotion_authority",
]
ORIGINAL_FREEZE_FIELDS = {
    "schema_version",
    "freeze_id",
    "status",
    "authority_tier",
    "preimage_commit",
    "preimage_tree",
    "remote",
    "remote_ref",
    "run_id",
    "run_dir",
    "bound_inputs",
    "truth_sha256",
    "tasks_file_sha256",
    "reference_context_sha256",
    "semantic_signature_contract",
    "runtime_identities",
    "generation",
    "thresholds",
    "model_outputs_observed",
    "training_authorized",
    "delta_qlora_authorized",
    "nonclaims",
    "freeze_sha256",
}


class GrammarStdlibRecoveryError(RuntimeError):
    """The D18 post-output replay contract could not be established."""


def canonical_hash(value: Any) -> str:
    return d18.canonical_hash(value)


def raw_hash(value: bytes) -> str:
    return d18.raw_hash(value)


def _load(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        return d18._load(path, label)
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibRecoveryError(str(error)) from error


def _self_hash(value: Mapping[str, Any], field: str) -> None:
    if value.get(field) != canonical_hash(
        {key: item for key, item in value.items() if key != field}
    ):
        raise GrammarStdlibRecoveryError(f"{field} does not match canonical body")


def _pinned_git(repository: Path | None, *args: str, text: bool = True) -> str | bytes:
    """Use only catalog-pin Git: it byte-pins ``/usr/bin/git`` before execution."""

    try:
        return catalog_pin._run_git(repository, *args, text=text)
    except catalog_pin.CatalogMaintenancePinError as error:
        raise GrammarStdlibRecoveryError(f"pinned Git verification failed: {error}") from error


def _pinned_commit_record(commit: str, relative: str) -> dict[str, Any]:
    """Read one exact blob record from ``commit`` through the pinned Git binary."""

    raw = _pinned_git(PROJECT_ROOT, "show", f"{commit}:{relative}", text=False)
    if not isinstance(raw, bytes):
        raise GrammarStdlibRecoveryError("pinned Git blob is not bytes")
    row = str(_pinned_git(PROJECT_ROOT, "ls-tree", commit, "--", relative)).split()
    if len(row) != 4 or row[1] != "blob" or row[3] != relative:
        raise GrammarStdlibRecoveryError(f"bound input is not one blob at {commit}: {relative}")
    return {"path": relative, "bytes": len(raw), "sha256": raw_hash(raw), "git_blob_oid": row[2]}


def _pinned_tracked_record(relative: str) -> dict[str, Any]:
    """Recreate D18's tracked-record predicate with the stronger Git wrapper."""

    record = _pinned_commit_record("HEAD", relative)
    try:
        current = d18.safe._read_regular(PROJECT_ROOT / relative, f"bound input {relative}")
    except d18.safe.DemoAccuracyError as error:
        raise GrammarStdlibRecoveryError(str(error)) from error
    if raw_hash(current) != record["sha256"] or len(current) != record["bytes"]:
        raise GrammarStdlibRecoveryError(f"bound input differs from HEAD: {relative}")
    return record


def _published(remote: str, remote_ref: str) -> tuple[str, str]:
    if str(_pinned_git(PROJECT_ROOT, "status", "--porcelain", "--untracked-files=all")):
        raise GrammarStdlibRecoveryError("clean worktree is required")
    head = str(_pinned_git(PROJECT_ROOT, "rev-parse", "HEAD"))
    rows = str(_pinned_git(PROJECT_ROOT, "ls-remote", remote, remote_ref)).splitlines()
    if len(rows) != 1 or rows[0].split() != [head, remote_ref]:
        raise GrammarStdlibRecoveryError("current HEAD is not exactly published")
    return head, str(_pinned_git(PROJECT_ROOT, "rev-parse", "HEAD^{tree}"))


def _run_dir(value: Mapping[str, Any]) -> Path:
    if value.get("run_id") != FIXED_RUN_ID or value.get("run_dir") != FIXED_RUN_RELATIVE:
        raise GrammarStdlibRecoveryError("recovery is limited to the fixed D18 run")
    return PROJECT_ROOT / FIXED_RUN_RELATIVE


def _verify_original_freeze(
    original: Mapping[str, Any], *, head: str, expected_file: Mapping[str, Any] | None = None
) -> Path:
    """Verify the old seal without using its failed unpinned Git helper."""

    _self_hash(original, "freeze_sha256")
    if (
        set(original) != ORIGINAL_FREEZE_FIELDS
        or original.get("schema_version") != 1
        or original.get("freeze_id") != "grammar-stdlib-accuracy-d18-freeze/v1"
        or original.get("status") != "frozen_before_model_output"
        or original.get("authority_tier") != "automatic"
        or original.get("freeze_sha256") != ORIGINAL_FREEZE_SELF_SHA256
        or original.get("preimage_commit") != ORIGINAL_PREIMAGE_COMMIT
        or original.get("preimage_tree") != ORIGINAL_PREIMAGE_TREE
        or original.get("remote") != ORIGINAL_REMOTE
        or original.get("remote_ref") != ORIGINAL_REMOTE_REF
        or original.get("truth_sha256") != ORIGINAL_TRUTH_SHA256
        or original.get("tasks_file_sha256") != ORIGINAL_TASKS_SHA256
        or original.get("reference_context_sha256") != ORIGINAL_REFERENCE_SHA256
        or original.get("generation") != d18.GENERATION
        or original.get("thresholds") != d18.THRESHOLDS
        or original.get("semantic_signature_contract") != d18.SEMANTIC_SIGNATURE_CONTRACT
        or not isinstance(original.get("runtime_identities"), Mapping)
        or original.get("model_outputs_observed") is not False
        or original.get("training_authorized") is not False
        or original.get("delta_qlora_authorized") is not False
        or original.get("nonclaims") != d18.NONCLAIMS
    ):
        raise GrammarStdlibRecoveryError("original freeze is not a D18 pre-output seal")
    record = _pinned_tracked_record(str(d18.FREEZE_PATH.relative_to(PROJECT_ROOT)))
    published_raw = _pinned_git(
        PROJECT_ROOT,
        "show",
        f"{ORIGINAL_FREEZE_PUBLICATION_COMMIT}:{d18.FREEZE_PATH.relative_to(PROJECT_ROOT)}",
        text=False,
    )
    if (
        not isinstance(published_raw, bytes)
        or raw_hash(published_raw) != ORIGINAL_FREEZE_FILE_SHA256
        or record.get("sha256") != ORIGINAL_FREEZE_FILE_SHA256
    ):
        raise GrammarStdlibRecoveryError("original freeze publication drift")
    _pinned_git(
        PROJECT_ROOT,
        "merge-base",
        "--is-ancestor",
        ORIGINAL_FREEZE_PUBLICATION_COMMIT,
        head,
    )
    if expected_file is not None and record != expected_file:
        raise GrammarStdlibRecoveryError("original freeze file record drift")
    if str(
        _pinned_git(PROJECT_ROOT, "rev-parse", f"{original.get('preimage_commit')}^{{tree}}")
    ) != original.get("preimage_tree"):
        raise GrammarStdlibRecoveryError("original freeze preimage tree drift")
    ancestor = _pinned_git(
        PROJECT_ROOT,
        "merge-base",
        "--is-ancestor",
        str(original["preimage_commit"]),
        head,
    )
    # --is-ancestor intentionally has empty stdout; a non-zero return is already
    # fail-closed inside the pinned wrapper.
    if ancestor not in {"", b""}:
        raise GrammarStdlibRecoveryError("original freeze ancestor output drift")
    records = original.get("bound_inputs")
    if not isinstance(records, list) or [
        item.get("path") for item in records if isinstance(item, Mapping)
    ] != list(d18.BOUND_PATHS):
        raise GrammarStdlibRecoveryError("original bound input roster drift")
    for item in records:
        if not isinstance(item, Mapping) or _pinned_tracked_record(str(item.get("path"))) != item:
            raise GrammarStdlibRecoveryError("original bound input drift")
    return _run_dir(original)


def _direct_file(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
        raw = d18.safe._read_regular(path, label, 32 * 1024 * 1024)
        after = path.lstat()
    except (OSError, d18.safe.DemoAccuracyError) as error:
        raise GrammarStdlibRecoveryError(f"{label} is unavailable") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink, metadata.st_size)
        != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_size)
    ):
        raise GrammarStdlibRecoveryError(f"{label} is not a stable direct regular file")
    return raw


def _verify_candidate_records(run_dir: Path) -> list[dict[str, Any]]:
    """Reopen and validate the two immutable candidate payloads."""

    records: list[dict[str, Any]] = []
    _manifest, tasks, _raw = d18.load_tasks()
    for relative in FIXED_CANDIDATE_RELATIVES:
        path = PROJECT_ROOT / relative
        raw = _direct_file(path, "partial D18 candidate")
        mode = stat.S_IMODE(path.lstat().st_mode)
        if mode != 0o600:
            raise GrammarStdlibRecoveryError("partial D18 candidate mode drift")
        try:
            d18._read_candidates(path, tasks)
        except d18.GrammarStdlibAccuracyError as error:
            raise GrammarStdlibRecoveryError(str(error)) from error
        digest = raw_hash(raw)
        if digest != FIXED_CANDIDATE_HASHES[relative]:
            raise GrammarStdlibRecoveryError(
                "partial D18 candidate hash differs from observed output"
            )
        records.append(
            {"path": relative, "bytes": len(raw), "sha256": digest, "rows": 18, "mode": mode}
        )
    return records


def _verify_partial_roster(run_dir: Path) -> list[dict[str, Any]]:
    try:
        d18._assert_run_ancestors(run_dir, allow_missing=False)
        d18._assert_direct_directory(run_dir, "D18 run directory")
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibRecoveryError(str(error)) from error
    expected = {PROJECT_ROOT / path for path in FIXED_CANDIDATE_RELATIVES}
    directories = {run_dir / "base", run_dir / "adapter"}
    files: set[Path] = set()
    found_directories: set[Path] = set()
    for path in run_dir.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise GrammarStdlibRecoveryError("partial D18 run contains a symlink")
        if stat.S_ISDIR(metadata.st_mode):
            found_directories.add(path)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            files.add(path)
        else:
            raise GrammarStdlibRecoveryError("partial D18 run contains a special or linked file")
    if files != expected or found_directories != directories:
        raise GrammarStdlibRecoveryError("partial D18 run roster differs")
    return _verify_candidate_records(run_dir)


def _recovery_fields() -> set[str]:
    return {
        "schema_version",
        "recovery_id",
        "status",
        "preimage_commit",
        "preimage_tree",
        "remote",
        "remote_ref",
        "original_freeze_file",
        "original_freeze_sha256",
        "original_preimage_commit",
        "original_preimage_tree",
        "original_bound_inputs",
        "recovery_bound_inputs",
        "candidate_inputs",
        "source_failure",
        "model_outputs_observed",
        "candidate_origin_attested",
        "model_replay",
        "additional_model_calls",
        "training_authorized",
        "delta_qlora_authorized",
        "nonclaims",
        "recovery_freeze_sha256",
    }


def build_recovery_freeze(remote: str, metis_root: Path, node_path: Path) -> dict[str, Any]:
    """Seal an already-observed partial D18 run; this is never a model freeze."""

    original, _raw = _load(d18.FREEZE_PATH, "original D18 freeze")
    head, tree = _published(
        str(original.get("remote", remote)), str(original.get("remote_ref", ""))
    )
    if remote != original.get("remote"):
        raise GrammarStdlibRecoveryError("recovery remote differs from original freeze")
    original_file = _pinned_tracked_record(str(d18.FREEZE_PATH.relative_to(PROJECT_ROOT)))
    run_dir = _verify_original_freeze(original, head=head, expected_file=original_file)
    try:
        d18._verify_frozen_inputs(original, metis_root, node_path)
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibRecoveryError(str(error)) from error
    candidates = _verify_partial_roster(run_dir)
    sidecar = _pinned_tracked_record(RECOVERY_SIDE_CAR_PATH)
    body: dict[str, Any] = {
        "schema_version": 1,
        "recovery_id": RECOVERY_ID,
        "status": RECOVERY_STATUS,
        "preimage_commit": head,
        "preimage_tree": tree,
        "remote": remote,
        "remote_ref": original["remote_ref"],
        "original_freeze_file": original_file,
        "original_freeze_sha256": original["freeze_sha256"],
        "original_preimage_commit": original["preimage_commit"],
        "original_preimage_tree": original["preimage_tree"],
        "original_bound_inputs": original["bound_inputs"],
        "recovery_bound_inputs": [sidecar],
        "candidate_inputs": candidates,
        "source_failure": SOURCE_FAILURE,
        "model_outputs_observed": True,
        "candidate_origin_attested": False,
        **NO_MODEL_CALLS,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": RECOVERY_NONCLAIMS,
    }
    body["recovery_freeze_sha256"] = canonical_hash(body)
    return body


def freeze(args: argparse.Namespace) -> int:
    if RECOVERY_FREEZE_PATH.exists() or RECOVERY_FREEZE_PATH.is_symlink():
        raise GrammarStdlibRecoveryError("recovery freeze output already exists")
    body = build_recovery_freeze(args.remote, Path(args.metis_root), Path(args.node_path))
    d18.safe._atomic_json(RECOVERY_FREEZE_PATH, body)
    print(
        json.dumps(
            {
                "event": "grammar_stdlib_d18_recovery_freeze",
                "recovery_freeze_sha256": body["recovery_freeze_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


def _verify_recovery_freeze(
    value: Mapping[str, Any], raw: bytes, head: str
) -> tuple[dict[str, Any], Path]:
    if set(value) != _recovery_fields():
        raise GrammarStdlibRecoveryError("recovery freeze field roster drift")
    _self_hash(value, "recovery_freeze_sha256")
    if (
        value.get("schema_version") != 1
        or value.get("recovery_id") != RECOVERY_ID
        or value.get("status") != RECOVERY_STATUS
        or value.get("remote") != ORIGINAL_REMOTE
        or value.get("remote_ref") != ORIGINAL_REMOTE_REF
        or value.get("source_failure") != SOURCE_FAILURE
        or value.get("model_outputs_observed") is not True
        or value.get("candidate_origin_attested") is not False
        or value.get("model_replay") is not False
        or value.get("additional_model_calls") != 0
        or value.get("training_authorized") is not False
        or value.get("delta_qlora_authorized") is not False
        or value.get("nonclaims") != RECOVERY_NONCLAIMS
    ):
        raise GrammarStdlibRecoveryError("recovery freeze authority drift")
    if _pinned_tracked_record(str(RECOVERY_FREEZE_PATH.relative_to(PROJECT_ROOT)))[
        "sha256"
    ] != raw_hash(raw):
        raise GrammarStdlibRecoveryError("recovery freeze is not committed")
    if str(
        _pinned_git(PROJECT_ROOT, "rev-parse", f"{value.get('preimage_commit')}^{{tree}}")
    ) != value.get("preimage_tree"):
        raise GrammarStdlibRecoveryError("recovery preimage tree drift")
    _pinned_git(PROJECT_ROOT, "merge-base", "--is-ancestor", str(value["preimage_commit"]), head)
    preimage = str(value["preimage_commit"])
    original_relative = str(d18.FREEZE_PATH.relative_to(PROJECT_ROOT))
    if value.get("original_freeze_file") != _pinned_commit_record(preimage, original_relative):
        raise GrammarStdlibRecoveryError("original freeze is not bound at recovery preimage")
    preimage_sidecar = _pinned_commit_record(preimage, RECOVERY_SIDE_CAR_PATH)
    if value.get("recovery_bound_inputs") != [preimage_sidecar]:
        raise GrammarStdlibRecoveryError("recovery sidecar is not bound at recovery preimage")
    if _pinned_tracked_record(RECOVERY_SIDE_CAR_PATH) != preimage_sidecar:
        raise GrammarStdlibRecoveryError("recovery sidecar changed after recovery preimage")
    original, _original_raw = _load(d18.FREEZE_PATH, "original D18 freeze")
    if (
        original.get("freeze_sha256") != value.get("original_freeze_sha256")
        or original.get("preimage_commit") != value.get("original_preimage_commit")
        or original.get("preimage_tree") != value.get("original_preimage_tree")
        or original.get("bound_inputs") != value.get("original_bound_inputs")
    ):
        raise GrammarStdlibRecoveryError("recovery original-freeze lineage drift")
    run_dir = _verify_original_freeze(
        original, head=head, expected_file=value.get("original_freeze_file")
    )
    if _verify_partial_roster(run_dir) != value.get("candidate_inputs"):
        raise GrammarStdlibRecoveryError("recovery candidate binding drift")
    return original, run_dir


def recover(args: argparse.Namespace) -> int:
    value, raw = _load(RECOVERY_FREEZE_PATH, "D18 recovery freeze")
    head, tree = _published(str(value.get("remote")), str(value.get("remote_ref")))
    original, run_dir = _verify_recovery_freeze(value, raw, head)
    try:
        tasks, truth, _task_raw = d18._verify_frozen_inputs(
            original, Path(args.metis_root), Path(args.node_path)
        )
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibRecoveryError(str(error)) from error
    porcelain_before = str(
        _pinned_git(PROJECT_ROOT, "status", "--porcelain", "--untracked-files=all")
    )
    if porcelain_before:
        raise GrammarStdlibRecoveryError("worktree must remain clean before recovery")
    truth_by_id = {item["task_id"]: item for item in truth["tasks"]}
    candidates = {
        label: d18._read_candidates(run_dir / label / "candidates.jsonl", tasks)
        for label in ("base", "adapter")
    }
    observations = {
        label: [
            d18.score_candidate(
                task, row, truth_by_id[task["task_id"]], Path(args.metis_root), Path(args.node_path)
            )
            for task, row in zip(tasks, rows, strict=True)
        ]
        for label, rows in candidates.items()
    }
    if _verify_partial_roster(run_dir) != value["candidate_inputs"]:
        raise GrammarStdlibRecoveryError("recovery candidates changed during scoring")
    if (
        str(_pinned_git(PROJECT_ROOT, "status", "--porcelain", "--untracked-files=all"))
        != porcelain_before
    ):
        raise GrammarStdlibRecoveryError("tracked worktree changed during recovery")
    if _published(str(value["remote"]), str(value["remote_ref"])) != (head, tree):
        raise GrammarStdlibRecoveryError("published recovery identity changed during scoring")
    repeated_original, repeated_run_dir = _verify_recovery_freeze(value, raw, head)
    if repeated_original != original or repeated_run_dir != run_dir:
        raise GrammarStdlibRecoveryError("recovery lineage changed during scoring")
    decision = d18.gate_arithmetic(observations["base"], observations["adapter"])
    report = {
        "schema_version": 1,
        "status": "complete_recovered_candidate_replay",
        "authority_tier": "diagnostic_only",
        "head": head,
        "tree": tree,
        "freeze_sha256": original["freeze_sha256"],
        "outputs": {
            label: {key: item[key] for key in ("path", "bytes", "sha256")}
            for label, item in zip(("base", "adapter"), value["candidate_inputs"], strict=True)
        },
        "observations": observations,
        "decision": decision,
        "recovery": {
            "recovery_freeze_sha256": value["recovery_freeze_sha256"],
            "original_freeze_file_sha256": value["original_freeze_file"]["sha256"],
            "source_failure": value["source_failure"],
            **NO_MODEL_CALLS,
            "candidate_origin_attested": False,
        },
        "model_outputs_observed": True,
        "training_authorized": False,
        "delta_qlora_authorized": False,
        "nonclaims": [*d18.NONCLAIMS, "candidate_origin_not_retroactively_attested"],
    }
    report["report_sha256"] = canonical_hash(report)
    report_raw = d18.safe.canonical_bytes(report) + b"\n"
    try:
        d18._write_run_file(run_dir, run_dir, "report.json", report_raw)
        d18._verify_run_roster(run_dir)
    except d18.GrammarStdlibAccuracyError as error:
        raise GrammarStdlibRecoveryError(str(error)) from error
    if _verify_candidate_records(run_dir) != value["candidate_inputs"]:
        raise GrammarStdlibRecoveryError("recovery candidates changed at report publication")
    if _direct_file(run_dir / "report.json", "recovered D18 report") != report_raw:
        raise GrammarStdlibRecoveryError("recovered D18 report publication drift")
    if _published(str(value["remote"]), str(value["remote_ref"])) != (head, tree):
        raise GrammarStdlibRecoveryError(
            "published recovery identity changed at report publication"
        )
    print(
        json.dumps(
            {"event": "grammar_stdlib_d18_recover", "verdict": decision["verdict"]}, sort_keys=True
        )
    )
    return 0 if decision["verdict"].endswith("PASS") else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("mode", choices=("freeze", "recover"))
    result.add_argument("--metis-root", type=Path, default=d18.DEFAULT_METIS_ROOT)
    result.add_argument("--node-path", type=Path, default=d18.DEFAULT_NODE)
    result.add_argument("--remote", default="origin")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return {"freeze": freeze, "recover": recover}[args.mode](args)
    except (
        GrammarStdlibRecoveryError,
        d18.GrammarStdlibAccuracyError,
        catalog_pin.CatalogMaintenancePinError,
        d18.qlora.RuntimeContractError,
        d18.oracle.GrammarStdlibOracleError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
