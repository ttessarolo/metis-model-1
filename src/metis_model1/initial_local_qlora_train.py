"""Preimage-bound, single-configuration trainer for INITIAL_LOCAL_QLORA_V1."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metis_model1.initial_local_qlora_runtime import (
    CONFIG,
    DARWIN_METAL_CACHE_ROOTS,
    DARWIN_USER_CACHE_ROOTS,
    LIMITS,
    _canonical_hash,
    _check_checkpoint,
    _check_receipt,
    _check_runtime,
    _dataset_fingerprint,
    _prefixed_sha256,
    _verified_dev_bundle,
    verify_checkpoint,
    verify_continuation_gate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts/initial-local-qlora-v1"
DATASET_ROOT = ARTIFACT_ROOT / "dataset"
LEGACY_RUN_ROOT = ARTIFACT_ROOT / "run-v1"
RUN_ROOT = ARTIFACT_ROOT / "run-v2"
CHECKPOINT_ROOT = RUN_ROOT / "checkpoints"
MODEL_PATH = PROJECT_ROOT / "artifacts/w4/2026-08-20-qualification/checkpoint"
CHECKPOINT_REPORT = (
    PROJECT_ROOT / "artifacts/w5-xs/2026-08-24-delivery/preflight/checkpoint-verification.json"
)
QUALIFICATION_PYTHON = PROJECT_ROOT / "qualification/.venv/bin/python"
TRAINER = PROJECT_ROOT / "qualification/train_full_state.py"
TELEMETRY = PROJECT_ROOT / "qualification/run_with_telemetry.py"
PRIOR_FREEZE_PATH = PROJECT_ROOT / "manifests/initial-local-qlora-training-freeze-v1.json"
FREEZE_PATH = PROJECT_ROOT / "manifests/initial-local-qlora-training-freeze-v2.json"
REUSE_MANIFEST_PATH = PROJECT_ROOT / "manifests/initial-local-qlora-baseline-reuse-v1.json"
REUSE_RECEIPT_PATH = RUN_ROOT / "baseline-reuse.json"
PRIOR_FREEZE_PUBLICATION = "0777a0a64704f815a13cfd63875d37afbfc231d2"
PRIOR_FREEZE_FILE_SHA256 = "sha256:5847fc2889696406989e79cb8413e41bb1cdff1e08f8fa30e3cd9e7d381fdc28"
PRIOR_FREEZE_SELF_SHA256 = "sha256:443ca34bb67c394089c0506dfaa9ec816514568f6a4d9b1b8ad3ca945b3dd824"
REUSE_MANIFEST_SELF_SHA256 = (
    "sha256:b51cac04ce851cf38e9013b8f81936cb06c02322a091025f9f07a0e14f5edc6e"
)
ALLOWED_STEPS = (25, 50, 100)
EXPECTED_CHECKPOINTS = {25: [], 50: [25], 100: [25, 50]}
AFTER_CHECKPOINTS = {25: [25], 50: [25, 50], 100: [25, 50, 75, 100]}
BOUND_INPUTS = (
    "docs/18-initial-local-qlora.md",
    "manifests/initial-local-qlora-baseline-reuse-v1.json",
    "manifests/initial-local-qlora-plan-v1.json",
    "manifests/initial-local-qlora-exclusions-v1.json",
    "qualification/checkpoint-pin.json",
    "qualification/runtime-pin.json",
    "qualification/train_full_state.py",
    "qualification/run_with_telemetry.py",
    "qualification/verify_checkpoint.py",
    "qualification/uv.lock",
    "manifests/catalog-maintenance-pin-v1.json",
    "runtime/metis_oracle/runner.ts",
    "schemas/catalog-maintenance-pin.schema.json",
    "schemas/initial-local-qlora-baseline-reuse.schema.json",
    "schemas/initial-local-qlora-plan.schema.json",
    "schemas/oracle-result.schema.json",
    "src/metis_model1/catalog_maintenance_pin.py",
    "src/metis_model1/catalog_maintenance_probe.py",
    "src/metis_model1/catalog_retrieval.py",
    "src/metis_model1/catalog_retrieval_refresh.py",
    "src/metis_model1/contracts.py",
    "src/metis_model1/dataset.py",
    "src/metis_model1/initial_local_qlora_b12.py",
    "src/metis_model1/initial_local_qlora_dataset.py",
    "src/metis_model1/initial_local_qlora_runtime.py",
    "src/metis_model1/initial_local_qlora_train.py",
    "src/metis_model1/oracles.py",
    "src/metis_model1/provenance.py",
)
REMOTE = "origin"
ARTIFACT_LIMIT_BYTES = LIMITS["new_artifacts_gb"] * 1024**3


class TrainingContractError(ValueError):
    """Raised when the sole authorized training run cannot advance safely."""


def _fail(message: str) -> None:
    raise TrainingContractError(message)


def _file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        _fail(f"bound file is missing or unsafe: {path}")
    return _prefixed_sha256(path)


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(f"required JSON is missing or unsafe: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"invalid JSON {path}: {exc}")
    if not isinstance(value, dict):
        _fail(f"JSON object required: {path}")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite training evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                (json.dumps(value, allow_nan=False, sort_keys=True) + "\n").encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["/usr/bin/git", "-C", str(PROJECT_ROOT), *args],
            stderr=subprocess.STDOUT,
            timeout=30,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "GIT_TERMINAL_PROMPT": "0",
            },
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(f"cannot inspect repository identity: {exc}")


def _bound_inputs(commit: str = "HEAD") -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in BOUND_INPUTS:
        path = PROJECT_ROOT / relative
        try:
            head_bytes = subprocess.check_output(
                [
                    "/usr/bin/git",
                    "-C",
                    str(PROJECT_ROOT),
                    "show",
                    f"{commit}:{relative}",
                ],
                timeout=30,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except subprocess.SubprocessError as exc:
            _fail(f"bound input is not published in {commit}: {relative}: {exc}")
        live = path.read_bytes()
        if live != head_bytes:
            _fail(f"bound input differs from published preimage: {relative}")
        result[relative] = "sha256:" + hashlib.sha256(live).hexdigest()
    return result


def _published_git_identity() -> dict[str, str]:
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch or branch.startswith("-"):
        _fail("training requires a named Git branch")
    head = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    remote_ref = f"refs/heads/{branch}"
    tracking_ref = f"refs/remotes/{REMOTE}/{branch}"
    if _git("rev-parse", tracking_ref) != head:
        _fail("local HEAD differs from the origin tracking ref")
    raw = _git("ls-remote", "--exit-code", "--heads", REMOTE, remote_ref)
    lines = [line.split() for line in raw.splitlines() if line.strip()]
    if lines != [[head, remote_ref]]:
        _fail("published remote branch does not equal local HEAD exactly")
    return {
        "branch": branch,
        "head": head,
        "tree": tree,
        "remote": REMOTE,
        "remote_ref": remote_ref,
        "remote_head": head,
    }


def _verify_freeze_publication(value: dict[str, Any], *, require_remote: bool) -> dict[str, str]:
    preimage = value.get("preimage_commit")
    preimage_tree = value.get("preimage_tree")
    branch = value.get("branch")
    remote_ref = value.get("remote_ref")
    if (
        not isinstance(preimage, str)
        or _git("rev-parse", f"{preimage}^{{commit}}") != preimage
        or _git("rev-parse", f"{preimage}^{{tree}}") != preimage_tree
        or _git("merge-base", "--is-ancestor", preimage, "HEAD")
    ):
        _fail("training freeze Git preimage identity or ancestry drift")
    current_branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    current = {
        "branch": current_branch,
        "head": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "remote": REMOTE,
        "remote_ref": f"refs/heads/{current_branch}",
    }
    if branch != current_branch or remote_ref != current["remote_ref"]:
        _fail("training freeze branch identity drift")
    if require_remote:
        published = _published_git_identity()
        current.update(published)
        relative = FREEZE_PATH.relative_to(PROJECT_ROOT).as_posix()
        try:
            frozen_in_head = subprocess.check_output(
                [
                    "/usr/bin/git",
                    "-C",
                    str(PROJECT_ROOT),
                    "show",
                    f"HEAD:{relative}",
                ],
                timeout=30,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except subprocess.SubprocessError as exc:
            _fail(f"training freeze is not committed in published HEAD: {exc}")
        if frozen_in_head != FREEZE_PATH.read_bytes():
            _fail("live training freeze differs from published HEAD")
    return current


def _checkpoint_steps() -> list[int]:
    if not CHECKPOINT_ROOT.exists():
        return []
    if CHECKPOINT_ROOT.is_symlink() or not CHECKPOINT_ROOT.is_dir():
        _fail("checkpoint root is unsafe")
    steps: list[int] = []
    for item in CHECKPOINT_ROOT.iterdir():
        if item.is_symlink() or not item.is_dir() or not item.name.startswith("step-"):
            _fail("checkpoint root contains an unexpected entry")
        try:
            steps.append(int(item.name.removeprefix("step-")))
        except ValueError:
            _fail("checkpoint directory has an invalid step name")
    return sorted(steps)


def artifact_census() -> dict[str, Any]:
    total = 0
    files = 0
    if ARTIFACT_ROOT.exists():
        if ARTIFACT_ROOT.is_symlink() or not ARTIFACT_ROOT.is_dir():
            _fail("wave artifact root is unsafe")
        for path in ARTIFACT_ROOT.rglob("*"):
            metadata = path.lstat()
            if path.is_symlink() or not (
                stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
            ):
                _fail(f"wave artifacts contain an unsafe entry: {path}")
            if stat.S_ISREG(metadata.st_mode):
                if metadata.st_nlink != 1:
                    _fail(f"wave artifacts contain a hard-linked file: {path}")
                total += metadata.st_size
                files += 1
    steps = _checkpoint_steps()
    result = {"bytes": total, "files": files, "checkpoint_steps": steps}
    if total > LIMITS["new_artifacts_gb"] * 1024**3:
        _fail("wave artifact budget exceeds 8 GiB")
    if len(steps) > LIMITS["checkpoints"]:
        _fail("wave checkpoint count exceeds four")
    return result


def _artifact_usage() -> dict[str, int]:
    total = 0
    files = 0
    if not ARTIFACT_ROOT.exists():
        return {"bytes": 0, "files": 0}
    if ARTIFACT_ROOT.is_symlink() or not ARTIFACT_ROOT.is_dir():
        _fail("wave artifact root is unsafe")
    for path in ARTIFACT_ROOT.rglob("*"):
        metadata = path.lstat()
        if path.is_symlink() or not (
            stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
        ):
            _fail(f"wave artifacts contain an unsafe live entry: {path}")
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                _fail(f"wave artifacts contain a hard-linked file: {path}")
            total += metadata.st_size
            files += 1
    if total > ARTIFACT_LIMIT_BYTES:
        _fail("wave artifact budget exceeds 8 GiB during execution")
    return {"bytes": total, "files": files}


def _command(target: int) -> list[str]:
    if target not in ALLOWED_STEPS:
        _fail("target step must be 25, 50, or 100")
    telemetry_root = RUN_ROOT / f"telemetry-step{target}"
    training_log = RUN_ROOT / f"training-step{target}.jsonl"
    command = [
        str(QUALIFICATION_PYTHON),
        str(TELEMETRY),
        "--output-dir",
        str(telemetry_root),
        "--sample-seconds",
        "1",
        "--max-rss-gib",
        "110",
        "--max-metal-gib",
        "110",
        "--max-monotonic-growth-gib",
        "8",
        "--min-metal-samples",
        "1",
        "--",
        str(QUALIFICATION_PYTHON),
        str(TRAINER),
        "--model-path",
        str(MODEL_PATH),
        "--checkpoint-report",
        str(CHECKPOINT_REPORT),
        "--dataset",
        str(DATASET_ROOT / "train.jsonl"),
        "--split",
        "train",
        "--iters",
        str(target),
        "--checkpoint-root",
        str(CHECKPOINT_ROOT),
        "--telemetry-path",
        str(training_log),
        "--checkpoint-every",
        "25",
        "--steps-per-report",
        "1",
        "--batch-size",
        "1",
        "--gradient-accumulation-steps",
        "1",
        "--max-seq-length",
        "1024",
        "--learning-rate",
        "1e-5",
        "--lora-rank",
        "8",
        "--lora-alpha",
        "16",
        "--lora-dropout",
        "0",
        "--seed",
        "17",
        "--train-on-completions",
    ]
    if target > 25:
        command.extend(
            ("--resume", str(CHECKPOINT_ROOT / f"step-{EXPECTED_CHECKPOINTS[target][-1]:08d}"))
        )
    return command


def _training_environment() -> dict[str, str]:
    cache_root = RUN_ROOT / "offline-cache"
    temp_root = RUN_ROOT / "tmp"
    home_root = RUN_ROOT / "home"
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": str(home_root),
        "TMPDIR": str(temp_root),
        "XDG_CACHE_HOME": str(cache_root / "xdg"),
        "HF_HOME": str(cache_root / "huggingface"),
        "HF_DATASETS_CACHE": str(cache_root / "datasets"),
        "TRANSFORMERS_CACHE": str(cache_root / "transformers"),
        "HF_HUB_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }


def _sandbox_path(path: Path) -> str:
    value = str(path.resolve(strict=False))
    if '"' in value or "\n" in value:
        _fail("sandbox path contains an unsafe character")
    return value


def _training_sandbox_policy(target: int) -> str:
    if target not in ALLOWED_STEPS:
        _fail("sandbox target must be 25, 50, or 100")
    telemetry_root = RUN_ROOT / f"telemetry-step{target}"
    training_log = RUN_ROOT / f"training-step{target}.jsonl"
    writable_subpaths = (
        RUN_ROOT / "offline-cache",
        RUN_ROOT / "tmp",
        RUN_ROOT / "home",
        telemetry_root,
        CHECKPOINT_ROOT,
    )
    allowed = " ".join(f'(subpath "{_sandbox_path(path)}")' for path in writable_subpaths)
    metal_cache_allowed = " ".join(f'(subpath "{path}")' for path in DARWIN_METAL_CACHE_ROOTS)
    metal_cache_extensions = " ".join(
        f'(allow file-issue-extension (subpath "{path}"))' for path in DARWIN_USER_CACHE_ROOTS
    )
    denied_prior = " ".join(
        f'(subpath "{_sandbox_path(CHECKPOINT_ROOT / f"step-{step:08d}")}")'
        for step in EXPECTED_CHECKPOINTS[target]
    )
    user_root = PROJECT_ROOT.parents[1]
    denied_reads = " ".join(
        f'(subpath "{_sandbox_path(path)}")'
        for path in (
            PROJECT_ROOT / ".env",
            user_root / ".aws",
            user_root / ".ssh",
            user_root / "Library/Keychains",
        )
    )
    policy = (
        "(version 1) (deny default) (deny network*) "
        "(allow process*) (allow file-read*) "
        f"(deny file-read* {denied_reads}) "
        f"(allow file-write* {allowed} {metal_cache_allowed} "
        f'(literal "{_sandbox_path(training_log)}") '
        '(literal "/dev/null")) '
        f"{metal_cache_extensions} "
        "(allow sysctl-read) (allow mach-lookup) (allow iokit*) (allow ipc-posix-shm*)"
    )
    if denied_prior:
        policy += f" (deny file-write* {denied_prior})"
    return policy


def _reuse_manifest() -> dict[str, Any]:
    value = _json(REUSE_MANIFEST_PATH)
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    source = value.get("source")
    destination = value.get("destination")
    execution = value.get("execution")
    if (
        set(value)
        != {
            "schema_version",
            "manifest_id",
            "status",
            "reason",
            "source",
            "destination",
            "execution",
            "nonclaims",
            "manifest_sha256",
        }
        or value.get("schema_version") != 1
        or value.get("manifest_id") != "initial-local-qlora-baseline-reuse/v1"
        or value.get("status") != "authorized_post_output_recovery"
        or value.get("manifest_sha256") != REUSE_MANIFEST_SELF_SHA256
        or value.get("manifest_sha256") != _canonical_hash(body)
        or not isinstance(source, dict)
        or source.get("run_root") != "artifacts/initial-local-qlora-v1/run-v1"
        or source.get("freeze_path") != "manifests/initial-local-qlora-training-freeze-v1.json"
        or source.get("freeze_publication_commit") != PRIOR_FREEZE_PUBLICATION
        or source.get("freeze_file_sha256") != PRIOR_FREEZE_FILE_SHA256
        or source.get("freeze_self_sha256") != PRIOR_FREEZE_SELF_SHA256
        or not isinstance(destination, dict)
        or destination.get("run_root") != "artifacts/initial-local-qlora-v1/run-v2"
        or destination.get("freeze_path") != "manifests/initial-local-qlora-training-freeze-v2.json"
        or destination.get("copy_roster")
        != [
            "base-dev/candidates.jsonl",
            "base-dev/generation.json",
            "base-dev/semantic.json",
        ]
        or not isinstance(execution, dict)
        or execution.get("baseline_model_invocations_total") != 1
        or execution.get("additional_model_invocations") != 0
        or execution.get("dev_consumptions_total") != 1
        or execution.get("optimizer_invocations") != 0
        or execution.get("oracle_replay_for_verification_only") is not True
        or execution.get("model_replay_allowed") is not False
        or execution.get("fresh_namespace_required") is not True
        or execution.get("atomic_copy_required") is not True
        or execution.get("source_remains_read_only") is not True
    ):
        _fail("baseline reuse manifest identity or authority drift")
    return value


def _prior_freeze(manifest: dict[str, Any]) -> dict[str, Any]:
    value = _json(PRIOR_FREEZE_PATH)
    body = {key: item for key, item in value.items() if key != "freeze_sha256"}
    relative = PRIOR_FREEZE_PATH.relative_to(PROJECT_ROOT).as_posix()
    try:
        published = subprocess.check_output(
            [
                "/usr/bin/git",
                "-C",
                str(PROJECT_ROOT),
                "show",
                f"{PRIOR_FREEZE_PUBLICATION}:{relative}",
            ],
            timeout=30,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except subprocess.SubprocessError as exc:
        _fail(f"cannot reopen the prior published freeze: {exc}")
    source = manifest["source"]
    if (
        published != PRIOR_FREEZE_PATH.read_bytes()
        or _file_hash(PRIOR_FREEZE_PATH) != PRIOR_FREEZE_FILE_SHA256
        or value.get("freeze_sha256") != PRIOR_FREEZE_SELF_SHA256
        or value.get("freeze_sha256") != _canonical_hash(body)
        or value.get("status") != "frozen_before_model_output"
        or value.get("model_outputs_observed") is not False
        or value.get("training_started") is not False
        or value.get("preimage_commit") != source.get("freeze_preimage_commit")
        or value.get("preimage_tree") != source.get("freeze_preimage_tree")
        or _git("merge-base", "--is-ancestor", PRIOR_FREEZE_PUBLICATION, "HEAD")
    ):
        _fail("prior training freeze publication or identity drift")
    return value


def _legacy_base_state(manifest: dict[str, Any]) -> dict[str, Any]:
    if LEGACY_RUN_ROOT.is_symlink() or not LEGACY_RUN_ROOT.is_dir():
        _fail("legacy run-v1 source is missing or unsafe")
    expected_directories = {
        "base-dev",
        "evaluation-cache",
        "evaluation-cache/home",
        "evaluation-cache/tmp",
    }
    expected_files = {
        "base-dev/candidates.jsonl",
        "base-dev/generation.json",
        "base-dev/semantic.json",
    }
    observed_directories: set[str] = set()
    observed_files: set[str] = set()
    for path in LEGACY_RUN_ROOT.rglob("*"):
        metadata = path.lstat()
        relative = path.relative_to(LEGACY_RUN_ROOT).as_posix()
        if path.is_symlink():
            _fail("legacy run-v1 contains a symlink")
        if stat.S_ISDIR(metadata.st_mode):
            observed_directories.add(relative)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            observed_files.add(relative)
        else:
            _fail("legacy run-v1 contains a linked or nonregular entry")
    if observed_directories != expected_directories or observed_files != expected_files:
        _fail("legacy run-v1 roster is not the exact pre-training baseline")
    expected = manifest["source"]["base_dev"]["files"]
    files: dict[str, dict[str, Any]] = {}
    for name in ("candidates.jsonl", "generation.json", "semantic.json"):
        path = LEGACY_RUN_ROOT / "base-dev" / name
        reference = expected.get(name)
        if (
            not isinstance(reference, dict)
            or path.stat().st_size != reference.get("bytes")
            or _file_hash(path) != reference.get("sha256")
        ):
            _fail(f"legacy baseline file drift: {name}")
        files[name] = {
            "bytes": path.stat().st_size,
            "sha256": _file_hash(path),
        }
        if name in {"generation.json", "semantic.json"}:
            value = _json(path)
            body = {key: item for key, item in value.items() if key != "report_sha256"}
            if value.get("report_sha256") != reference.get("self_sha256") or value.get(
                "report_sha256"
            ) != _canonical_hash(body):
                _fail(f"legacy baseline self-hash drift: {name}")
            files[name]["self_sha256"] = value["report_sha256"]
    return {
        "run_root": "artifacts/initial-local-qlora-v1/run-v1",
        "directories": sorted(observed_directories),
        "files": files,
        "model_invocations_total": 1,
        "dev_consumptions_total": 1,
        "training_started": False,
        "checkpoint_steps": [],
    }


def _static_legacy_bundle(manifest: dict[str, Any]) -> dict[str, Any]:
    semantic = _json(LEGACY_RUN_ROOT / "base-dev/semantic.json")
    expected = manifest["source"]["base_dev"]["files"]
    files = {
        kind: {
            "path": f"base-dev/{name}",
            "bytes": expected[name]["bytes"],
            "sha256": expected[name]["sha256"],
        }
        for kind, name in (
            ("candidates", "candidates.jsonl"),
            ("generation", "generation.json"),
            ("semantic", "semantic.json"),
        )
    }
    body = {
        "label": "base",
        "score": manifest["source"]["base_dev"]["score"],
        "identity": semantic["generation_identity"],
        "files": files,
    }
    return {**body, "bundle_sha256": _canonical_hash(body)}


def _baseline_origin(*, replay_oracle: bool) -> dict[str, Any]:
    manifest = _reuse_manifest()
    prior = _prior_freeze(manifest)
    legacy = _legacy_base_state(manifest)
    bundle = _static_legacy_bundle(manifest)
    if replay_oracle:
        replayed = _verified_dev_bundle(
            "base",
            dataset_receipt=DATASET_ROOT / "receipt.json",
            adapter=None,
            output_root=LEGACY_RUN_ROOT,
        )
        if replayed != bundle:
            _fail("legacy baseline differs from pinned-oracle replay")
    return {
        "binding": "post_hoc_exact_bytes_not_embedded_in_original_generation",
        "reuse_manifest_file_sha256": _file_hash(REUSE_MANIFEST_PATH),
        "reuse_manifest_self_sha256": manifest["manifest_sha256"],
        "prior_freeze_publication_commit": PRIOR_FREEZE_PUBLICATION,
        "prior_freeze_file_sha256": _file_hash(PRIOR_FREEZE_PATH),
        "prior_freeze_self_sha256": prior["freeze_sha256"],
        "prior_freeze_preimage_commit": prior["preimage_commit"],
        "prior_freeze_preimage_tree": prior["preimage_tree"],
        "legacy_state": legacy,
        "base_dev": bundle,
    }


def _destination_base_files() -> dict[str, dict[str, Any]]:
    base = RUN_ROOT / "base-dev"
    if base.is_symlink() or not base.is_dir():
        _fail("run-v2 imported baseline is missing or unsafe")
    if {path.name for path in base.iterdir()} != {
        "candidates.jsonl",
        "generation.json",
        "semantic.json",
    }:
        _fail("run-v2 imported baseline roster is not exact")
    result: dict[str, dict[str, Any]] = {}
    for name in ("candidates.jsonl", "generation.json", "semantic.json"):
        path = base / name
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            _fail("run-v2 imported baseline contains an unsafe file")
        result[name] = {"bytes": path.stat().st_size, "sha256": _file_hash(path)}
    return result


def _verified_reuse_receipt(freeze: dict[str, Any]) -> dict[str, Any]:
    value = _json(REUSE_RECEIPT_PATH)
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    source_files = freeze["baseline_origin"]["legacy_state"]["files"]
    expected_files = {
        name: {"bytes": item["bytes"], "sha256": item["sha256"]}
        for name, item in source_files.items()
    }
    destination_files = _destination_base_files()
    if (
        set(value)
        != {
            "schema_version",
            "status",
            "wave",
            "mode",
            "freeze_file_sha256",
            "freeze_self_sha256",
            "reuse_manifest_file_sha256",
            "reuse_manifest_self_sha256",
            "source_run_root",
            "destination_run_root",
            "source_files",
            "destination_files",
            "source_to_destination_exact",
            "baseline_model_invocations_total",
            "additional_model_invocations",
            "dev_consumptions_total",
            "optimizer_invocations",
            "receipt_sha256",
        }
        or value.get("receipt_sha256") != _canonical_hash(body)
        or value.get("schema_version") != 1
        or value.get("status") != "imported_verified"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("mode") != "post_hoc_exact_byte_reuse_no_model_replay"
        or value.get("freeze_file_sha256") != _file_hash(FREEZE_PATH)
        or value.get("freeze_self_sha256") != freeze.get("freeze_sha256")
        or value.get("reuse_manifest_file_sha256") != _file_hash(REUSE_MANIFEST_PATH)
        or value.get("reuse_manifest_self_sha256") != REUSE_MANIFEST_SELF_SHA256
        or value.get("source_run_root") != "artifacts/initial-local-qlora-v1/run-v1"
        or value.get("destination_run_root") != "artifacts/initial-local-qlora-v1/run-v2"
        or value.get("source_files") != expected_files
        or value.get("destination_files") != destination_files
        or destination_files != expected_files
        or value.get("source_to_destination_exact") is not True
        or value.get("baseline_model_invocations_total") != 1
        or value.get("additional_model_invocations") != 0
        or value.get("dev_consumptions_total") != 1
        or value.get("optimizer_invocations") != 0
    ):
        _fail("baseline reuse receipt or imported bytes drift")
    return value


def freeze_training() -> dict[str, Any]:
    if FREEZE_PATH.exists() or FREEZE_PATH.is_symlink():
        _fail("training freeze output already exists")
    if RUN_ROOT.exists() or RUN_ROOT.is_symlink():
        _fail("run-v2 must be absent when the recovery preimage is frozen")
    runtime = _check_runtime()
    checkpoint = _check_checkpoint(MODEL_PATH)
    dataset = _check_receipt(DATASET_ROOT / "receipt.json")
    origin = _baseline_origin(replay_oracle=True)
    census = artifact_census()
    publication = _published_git_identity()
    preimage = publication["head"]
    body = {
        "schema_version": 2,
        "status": "refrozen_after_base_before_training",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "preimage_commit": preimage,
        "preimage_tree": publication["tree"],
        "branch": publication["branch"],
        "remote": publication["remote"],
        "remote_ref": publication["remote_ref"],
        "remote_head_at_freeze": publication["remote_head"],
        "preimage_published": True,
        "bound_inputs": _bound_inputs(preimage),
        "checkpoint": checkpoint,
        "checkpoint_report_sha256": _file_hash(CHECKPOINT_REPORT),
        "runtime": runtime,
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "train_fingerprint_sha256": _dataset_fingerprint(DATASET_ROOT / "train.jsonl"),
        "config": CONFIG,
        "limits": LIMITS,
        "artifact_census": census,
        "run_root": "artifacts/initial-local-qlora-v1/run-v2",
        "checkpoint_root": "artifacts/initial-local-qlora-v1/run-v2/checkpoints",
        "baseline_import_receipt": "artifacts/initial-local-qlora-v1/run-v2/baseline-reuse.json",
        "baseline_origin": origin,
        "commands": {str(step): _command(step) for step in ALLOWED_STEPS},
        "training_environment": _training_environment(),
        "sandbox_policy_sha256": {
            str(step): _canonical_hash(_training_sandbox_policy(step)) for step in ALLOWED_STEPS
        },
        "prior_model_output_present": True,
        "run_v2_output_absent_at_freeze": True,
        "model_outputs_observed": True,
        "training_started": False,
        "baseline_model_invocations_total": 1,
        "additional_model_invocations": 0,
        "dev_consumptions_total": 1,
        "model_replay_allowed": False,
        "network": "denied_during_model_and_optimizer_execution",
        "configurations": 1,
    }
    freeze = {**body, "freeze_sha256": _canonical_hash(body)}
    if (
        RUN_ROOT.exists()
        or RUN_ROOT.is_symlink()
        or artifact_census() != census
        or _baseline_origin(replay_oracle=False) != origin
    ):
        _fail("training recovery inputs changed while freeze-v2 was being built")
    _atomic_write(FREEZE_PATH, freeze)
    return freeze


def verify_freeze(*, require_remote: bool = True, require_import: bool = True) -> dict[str, Any]:
    value = _json(FREEZE_PATH)
    body = {key: item for key, item in value.items() if key != "freeze_sha256"}
    if (
        value.get("freeze_sha256") != _canonical_hash(body)
        or value.get("schema_version") != 2
        or value.get("status") != "refrozen_after_base_before_training"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("config") != CONFIG
        or value.get("limits") != LIMITS
        or value.get("prior_model_output_present") is not True
        or value.get("run_v2_output_absent_at_freeze") is not True
        or value.get("model_outputs_observed") is not True
        or value.get("training_started") is not False
        or value.get("baseline_model_invocations_total") != 1
        or value.get("additional_model_invocations") != 0
        or value.get("dev_consumptions_total") != 1
        or value.get("model_replay_allowed") is not False
        or value.get("configurations") != 1
        or value.get("remote") != REMOTE
        or value.get("remote_head_at_freeze") != value.get("preimage_commit")
        or value.get("preimage_published") is not True
        or value.get("bound_inputs") != _bound_inputs(str(value.get("preimage_commit")))
        or value.get("checkpoint_report_sha256") != _file_hash(CHECKPOINT_REPORT)
        or value.get("train_fingerprint_sha256")
        != _dataset_fingerprint(DATASET_ROOT / "train.jsonl")
        or value.get("commands") != {str(step): _command(step) for step in ALLOWED_STEPS}
        or value.get("training_environment") != _training_environment()
        or value.get("sandbox_policy_sha256")
        != {str(step): _canonical_hash(_training_sandbox_policy(step)) for step in ALLOWED_STEPS}
        or value.get("run_root") != "artifacts/initial-local-qlora-v1/run-v2"
        or value.get("checkpoint_root") != "artifacts/initial-local-qlora-v1/run-v2/checkpoints"
        or value.get("baseline_import_receipt")
        != "artifacts/initial-local-qlora-v1/run-v2/baseline-reuse.json"
        or value.get("baseline_origin") != _baseline_origin(replay_oracle=False)
    ):
        _fail("training freeze identity or contract drift")
    runtime = _check_runtime()
    dataset = _check_receipt(DATASET_ROOT / "receipt.json")
    if (
        value.get("runtime") != runtime
        or value.get("dataset_receipt_sha256") != dataset["receipt_sha256"]
    ):
        _fail("training freeze runtime or dataset drift")
    _verify_freeze_publication(value, require_remote=require_remote)
    if require_import:
        _verified_reuse_receipt(value)
    return value


def import_baseline() -> dict[str, Any]:
    freeze = verify_freeze(require_remote=True, require_import=False)
    if RUN_ROOT.exists() or RUN_ROOT.is_symlink():
        _fail("run-v2 already exists; baseline import is single-use")
    manifest = _reuse_manifest()
    source_before = _legacy_base_state(manifest)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".run-v2-import-", dir=ARTIFACT_ROOT))
    try:
        destination = staging / "base-dev"
        destination.mkdir()
        for name in ("candidates.jsonl", "generation.json", "semantic.json"):
            source = LEGACY_RUN_ROOT / "base-dev" / name
            target = destination / name
            with source.open("rb") as input_stream, target.open("xb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
        source_files = {
            name: {"bytes": item["bytes"], "sha256": item["sha256"]}
            for name, item in source_before["files"].items()
        }
        destination_files: dict[str, dict[str, Any]] = {}
        for name in ("candidates.jsonl", "generation.json", "semantic.json"):
            path = destination / name
            if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                _fail("baseline import staging contains an unsafe file")
            destination_files[name] = {"bytes": path.stat().st_size, "sha256": _file_hash(path)}
        if destination_files != source_files:
            _fail("baseline import staging differs from the immutable source")
        body = {
            "schema_version": 1,
            "status": "imported_verified",
            "wave": "INITIAL_LOCAL_QLORA_V1",
            "mode": "post_hoc_exact_byte_reuse_no_model_replay",
            "freeze_file_sha256": _file_hash(FREEZE_PATH),
            "freeze_self_sha256": freeze["freeze_sha256"],
            "reuse_manifest_file_sha256": _file_hash(REUSE_MANIFEST_PATH),
            "reuse_manifest_self_sha256": manifest["manifest_sha256"],
            "source_run_root": "artifacts/initial-local-qlora-v1/run-v1",
            "destination_run_root": "artifacts/initial-local-qlora-v1/run-v2",
            "source_files": source_files,
            "destination_files": destination_files,
            "source_to_destination_exact": True,
            "baseline_model_invocations_total": 1,
            "additional_model_invocations": 0,
            "dev_consumptions_total": 1,
            "optimizer_invocations": 0,
        }
        receipt = {**body, "receipt_sha256": _canonical_hash(body)}
        _atomic_write(staging / "baseline-reuse.json", receipt)
        for directory in (destination, staging):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if _legacy_base_state(manifest) != source_before:
            _fail("legacy baseline changed during import")
        os.replace(staging, RUN_ROOT)
        parent = os.open(ARTIFACT_ROOT, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(staging)
        raise
    verified = _verified_reuse_receipt(freeze)
    if _legacy_base_state(manifest) != source_before:
        _fail("legacy baseline changed after import")
    return verified


def _elapsed_training_seconds(freeze: dict[str, Any]) -> float:
    total = 0.0
    for step in ALLOWED_STEPS:
        receipt = RUN_ROOT / f"phase-step{step}-receipt.json"
        if receipt.exists():
            value = _verified_phase_receipt(step, freeze)
            total += float(value["duration_seconds"])
    if total > LIMITS["hours"] * 3600:
        _fail("cumulative optimizer wall-clock cap exhausted")
    return total


def _terminate_tree(process: subprocess.Popen[Any]) -> None:
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            observed = psutil.Process(process.pid)
            descendants = observed.children(recursive=True)
            for child in reversed(descendants):
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.terminate()
            _, alive = psutil.wait_procs(descendants, timeout=20)
            for child in alive:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    child.kill()
        except psutil.Error:
            pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=20)
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=20)


def _sandbox_canary(target: int, environment: dict[str, str]) -> dict[str, Any]:
    allowed = RUN_ROOT / "tmp" / f"sandbox-canary-step{target}.txt"
    forbidden = PROJECT_ROOT / ".initial-local-qlora-denied-canary"
    if allowed.exists() or forbidden.exists():
        _fail("sandbox canary path is not clean")
    code = (
        "from pathlib import Path; import sys; import mlx.core as mx; "
        "allowed=Path(sys.argv[1]); forbidden=Path(sys.argv[2]); "
        "allowed.write_text('ok'); "
        "blocked=False; "
        "\ntry:\n forbidden.write_text('forbidden')\n"
        "except PermissionError:\n blocked=True\n"
        "kernel=mx.fast.metal_kernel(name='metis_model1_training_jit_canary', "
        "input_names=['x'], output_names=['y'], "
        "source='uint i=thread_position_in_grid.x; y[i]=x[i]+T(2);'); "
        "x=mx.ones((1,)); y=kernel(inputs=[x], template=[('T',x.dtype)], "
        "grid=(1,1,1), threadgroup=(1,1,1), output_shapes=[x.shape], "
        "output_dtypes=[x.dtype])[0]; mx.eval(y); value=float(y[0]); "
        "sys.exit(0 if blocked and value == 3.0 else 7)"
    )
    completed = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            _training_sandbox_policy(target),
            str(QUALIFICATION_PYTHON),
            "-c",
            code,
            str(allowed),
            str(forbidden),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    forbidden_created = forbidden.exists()
    with contextlib.suppress(FileNotFoundError):
        forbidden.unlink()
    if (
        completed.returncode != 0
        or completed.stdout
        or len(completed.stderr.encode("utf-8")) > 16 * 1024
        or forbidden_created
        or allowed.read_text(encoding="utf-8") != "ok"
    ):
        _fail("training sandbox write/Metal canary failed")
    allowed_hash = _file_hash(allowed)
    allowed.unlink()
    return {
        "status": "pass",
        "target_step": target,
        "allowed_probe_sha256": allowed_hash,
        "forbidden_project_write": "denied",
        "metal_probe": "pass",
    }


def _wait_with_live_caps(process: subprocess.Popen[Any], *, deadline: float) -> dict[str, Any]:
    peak = 0
    samples = 0
    while True:
        try:
            usage = _artifact_usage()
        except (OSError, TrainingContractError):
            _terminate_tree(process)
            raise
        peak = max(peak, usage["bytes"])
        samples += 1
        returncode = process.poll()
        if returncode is not None:
            return {
                "returncode": returncode,
                "peak_artifact_bytes": peak,
                "artifact_samples": samples,
            }
        if time.monotonic() >= deadline:
            _terminate_tree(process)
            _fail("training phase exceeded the cumulative four-hour cap")
        time.sleep(0.5)


def _verified_phase_receipt(step: int, freeze: dict[str, Any]) -> dict[str, Any]:
    marker_path = RUN_ROOT / f"phase-step{step}-started.json"
    receipt_path = RUN_ROOT / f"phase-step{step}-receipt.json"
    marker = _json(marker_path)
    receipt = _json(receipt_path)
    marker_body = {key: item for key, item in marker.items() if key != "marker_sha256"}
    receipt_body = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    telemetry_root = RUN_ROOT / f"telemetry-step{step}"
    summary_path = telemetry_root / "summary.json"
    process_log = telemetry_root / "process.log"
    telemetry_log = telemetry_root / "rss.jsonl"
    summary = _json(summary_path)
    inner_command = _command(step)
    inner_command = inner_command[inner_command.index("--") + 1 :]
    summary_duration = summary.get("duration_seconds")
    duration = receipt.get("duration_seconds")
    supervisor_duration = receipt.get("supervisor_duration_seconds")
    peak = summary.get("peak_metal_gb")
    max_rss = summary.get("max_rss_bytes")
    prior_total = 0.0
    for prior in EXPECTED_CHECKPOINTS[step]:
        prior_receipt = _verified_phase_receipt(prior, freeze)
        prior_total += float(prior_receipt["duration_seconds"])
    authority = verify_continuation_gate(
        step,
        dataset_receipt=DATASET_ROOT / "receipt.json",
        checkpoint_root=CHECKPOINT_ROOT,
    )
    checkpoint = verify_checkpoint(
        CHECKPOINT_ROOT / f"step-{step:08d}",
        expected_dataset=DATASET_ROOT / "train.jsonl",
    )
    retained_checkpoints = [
        verify_checkpoint(
            CHECKPOINT_ROOT / f"step-{retained_step:08d}",
            expected_dataset=DATASET_ROOT / "train.jsonl",
            allowed_steps=(25, 50, 75, 100),
        )
        for retained_step in AFTER_CHECKPOINTS[step]
    ]
    if (
        marker.get("marker_sha256") != _canonical_hash(marker_body)
        or marker.get("schema_version") != 1
        or marker.get("status") != "started_no_retry"
        or marker.get("target_step") != step
        or marker.get("freeze_sha256") != freeze["freeze_sha256"]
        or marker.get("command_sha256") != _canonical_hash(_command(step))
        or marker.get("continuation_authority_sha256") != authority["authority_sha256"]
        or marker.get("environment_sha256") != _canonical_hash(_training_environment())
        or marker.get("environment_keys") != sorted(_training_environment())
        or marker.get("sandbox_policy_sha256") != _canonical_hash(_training_sandbox_policy(step))
        or not isinstance(marker.get("sandbox_canary"), dict)
        or marker["sandbox_canary"].get("status") != "pass"
        or marker["sandbox_canary"].get("target_step") != step
        or marker["sandbox_canary"].get("forbidden_project_write") != "denied"
        or marker["sandbox_canary"].get("metal_probe") != "pass"
        or not isinstance(marker.get("artifact_census_before"), dict)
        or marker["artifact_census_before"].get("checkpoint_steps") != EXPECTED_CHECKPOINTS[step]
        or receipt.get("receipt_sha256") != _canonical_hash(receipt_body)
        or receipt.get("schema_version") != 1
        or receipt.get("status") != "complete"
        or receipt.get("target_step") != step
        or receipt.get("freeze_sha256") != freeze["freeze_sha256"]
        or receipt.get("marker_sha256") != marker["marker_sha256"]
        or receipt.get("command_sha256") != _canonical_hash(_command(step))
        or receipt.get("continuation_authority_sha256") != authority["authority_sha256"]
        or receipt.get("environment_sha256") != _canonical_hash(_training_environment())
        or receipt.get("sandbox_policy_sha256") != _canonical_hash(_training_sandbox_policy(step))
        or receipt.get("checkpoint") != checkpoint
        or receipt.get("retained_checkpoints") != retained_checkpoints
        or receipt.get("telemetry_summary_sha256") != _file_hash(summary_path)
        or receipt.get("driver_log_sha256") != _file_hash(RUN_ROOT / f"phase-step{step}-driver.log")
        or summary.get("schema_version") != 1
        or summary.get("status") != "pass"
        or summary.get("command") != inner_command
        or summary.get("exit_code") != 0
        or summary.get("stop_reason") is not None
        or summary.get("residual_process_count") != 0
        or type(summary_duration) not in (int, float)
        or not math.isfinite(summary_duration)
        or not 0 <= summary_duration <= LIMITS["hours"] * 3600
        or type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 <= duration <= LIMITS["hours"] * 3600
        or supervisor_duration != duration
        or receipt.get("cumulative_duration_seconds") != prior_total + duration
        or prior_total + duration > LIMITS["hours"] * 3600
        or summary_duration > duration
        or type(peak) not in (int, float)
        or not math.isfinite(peak)
        or not 0 <= peak <= LIMITS["metal_gb"]
        or type(max_rss) is not int
        or not 0 <= max_rss <= LIMITS["metal_gb"] * 1024**3
        or type(summary.get("samples")) is not int
        or summary["samples"] < 1
        or type(summary.get("metal_samples")) is not int
        or summary["metal_samples"] < 1
        or summary.get("process_log_sha256") != _file_hash(process_log)[7:]
        or summary.get("telemetry_sha256") != _file_hash(telemetry_log)[7:]
        or receipt.get("peak_artifact_bytes", ARTIFACT_LIMIT_BYTES + 1) > ARTIFACT_LIMIT_BYTES
        or type(receipt.get("artifact_samples")) is not int
        or receipt["artifact_samples"] < 1
        or receipt.get("artifact_limit_bytes") != ARTIFACT_LIMIT_BYTES
        or receipt.get("network") != "sandbox_denied_and_offline_environment"
        or not isinstance(receipt.get("artifact_census_after"), dict)
        or receipt["artifact_census_after"].get("checkpoint_steps") != AFTER_CHECKPOINTS[step]
        or type(receipt["artifact_census_after"].get("bytes")) is not int
        or receipt["artifact_census_after"]["bytes"] + receipt_path.stat().st_size
        > ARTIFACT_LIMIT_BYTES
    ):
        _fail(f"training phase {step} receipt or evidence drift")
    return receipt


def run_step(target: int) -> dict[str, Any]:
    freeze = verify_freeze(require_remote=True)
    if target not in ALLOWED_STEPS:
        _fail("target step must be 25, 50, or 100")
    if _checkpoint_steps() != EXPECTED_CHECKPOINTS[target]:
        _fail("checkpoint roster does not authorize this phase")
    for prior in EXPECTED_CHECKPOINTS[target]:
        _verified_phase_receipt(prior, freeze)
    continuation = verify_continuation_gate(
        target,
        dataset_receipt=DATASET_ROOT / "receipt.json",
        checkpoint_root=CHECKPOINT_ROOT,
    )
    marker = RUN_ROOT / f"phase-step{target}-started.json"
    receipt_path = RUN_ROOT / f"phase-step{target}-receipt.json"
    telemetry_root = RUN_ROOT / f"telemetry-step{target}"
    training_log = RUN_ROOT / f"training-step{target}.jsonl"
    driver_log = RUN_ROOT / f"phase-step{target}-driver.log"
    if any(
        path.exists() or path.is_symlink()
        for path in (marker, receipt_path, telemetry_root, training_log, driver_log)
    ):
        _fail("training phase output already exists; retries are forbidden")
    before = artifact_census()
    elapsed_before = _elapsed_training_seconds(freeze)
    remaining = LIMITS["hours"] * 3600 - elapsed_before
    if remaining <= 0:
        _fail("cumulative optimizer wall-clock cap exhausted")
    command = _command(target)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    cache_root = RUN_ROOT / "offline-cache"
    temp_root = RUN_ROOT / "tmp"
    home_root = RUN_ROOT / "home"
    cache_root.mkdir(exist_ok=True)
    temp_root.mkdir(exist_ok=True)
    home_root.mkdir(exist_ok=True)
    environment = _training_environment()
    sandbox_canary = _sandbox_canary(target, environment)
    policy = _training_sandbox_policy(target)
    marker_body = {
        "schema_version": 1,
        "status": "started_no_retry",
        "target_step": target,
        "freeze_sha256": freeze["freeze_sha256"],
        "command_sha256": _canonical_hash(command),
        "continuation_authority_sha256": continuation["authority_sha256"],
        "environment_sha256": _canonical_hash(environment),
        "environment_keys": sorted(environment),
        "sandbox_policy_sha256": _canonical_hash(policy),
        "sandbox_canary": sandbox_canary,
        "started_epoch": time.time(),
        "artifact_census_before": before,
    }
    marker_value = {**marker_body, "marker_sha256": _canonical_hash(marker_body)}
    _atomic_write(marker, marker_value)
    telemetry_root.mkdir()
    CHECKPOINT_ROOT.mkdir(exist_ok=True)
    execution_census = _artifact_usage()
    full_command = ["/usr/bin/sandbox-exec", "-p", policy, *command]
    started = time.monotonic()
    deadline = started + remaining
    remaining_file_bytes = ARTIFACT_LIMIT_BYTES - execution_census["bytes"]
    if remaining_file_bytes <= 0:
        _fail("training phase has no artifact budget remaining")

    def set_file_limit() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (remaining_file_bytes, remaining_file_bytes))

    with driver_log.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            full_command,
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
            preexec_fn=set_file_limit,
        )
        live_caps = _wait_with_live_caps(process, deadline=deadline)
        returncode = live_caps["returncode"]
    supervisor_duration = time.monotonic() - started
    if returncode != 0:
        _fail(f"training phase failed with exit {returncode}")
    summary = _json(telemetry_root / "summary.json")
    peak = summary.get("peak_metal_gb")
    if (
        summary.get("status") != "pass"
        or summary.get("exit_code") != 0
        or summary.get("residual_process_count") != 0
        or type(peak) not in (int, float)
        or not 0 <= peak <= LIMITS["metal_gb"]
        or type(summary.get("duration_seconds")) not in (int, float)
        or not math.isfinite(summary["duration_seconds"])
        or not math.isfinite(supervisor_duration)
        or supervisor_duration < summary["duration_seconds"]
        or supervisor_duration + elapsed_before > LIMITS["hours"] * 3600
    ):
        _fail("training telemetry violates a runtime cap")
    duration = supervisor_duration
    checkpoint = CHECKPOINT_ROOT / f"step-{target:08d}"
    verified = verify_checkpoint(checkpoint, expected_dataset=DATASET_ROOT / "train.jsonl")
    after = artifact_census()
    if after["checkpoint_steps"] != AFTER_CHECKPOINTS[target]:
        _fail("training phase produced an unexpected checkpoint roster")
    retained_checkpoints = [
        verify_checkpoint(
            CHECKPOINT_ROOT / f"step-{retained_step:08d}",
            expected_dataset=DATASET_ROOT / "train.jsonl",
            allowed_steps=(25, 50, 75, 100),
        )
        for retained_step in AFTER_CHECKPOINTS[target]
    ]
    if (
        verify_continuation_gate(
            target,
            dataset_receipt=DATASET_ROOT / "receipt.json",
            checkpoint_root=CHECKPOINT_ROOT,
        )
        != continuation
    ):
        _fail("continuation authority drifted during optimizer execution")
    verify_freeze(require_remote=False)
    body = {
        "schema_version": 1,
        "status": "complete",
        "target_step": target,
        "freeze_sha256": freeze["freeze_sha256"],
        "marker_sha256": marker_value["marker_sha256"],
        "command_sha256": _canonical_hash(command),
        "continuation_authority_sha256": continuation["authority_sha256"],
        "environment_sha256": _canonical_hash(environment),
        "sandbox_policy_sha256": _canonical_hash(policy),
        "duration_seconds": duration,
        "supervisor_duration_seconds": supervisor_duration,
        "cumulative_duration_seconds": elapsed_before + duration,
        "telemetry_summary_sha256": _file_hash(telemetry_root / "summary.json"),
        "driver_log_sha256": _file_hash(driver_log),
        "checkpoint": verified,
        "retained_checkpoints": retained_checkpoints,
        "artifact_census_after": after,
        "peak_artifact_bytes": live_caps["peak_artifact_bytes"],
        "artifact_samples": live_caps["artifact_samples"],
        "artifact_limit_bytes": ARTIFACT_LIMIT_BYTES,
        "network": "sandbox_denied_and_offline_environment",
    }
    receipt = {**body, "receipt_sha256": _canonical_hash(body)}
    raw_receipt = (json.dumps(receipt, allow_nan=False, sort_keys=True) + "\n").encode("utf-8")
    if _artifact_usage()["bytes"] + len(raw_receipt) > ARTIFACT_LIMIT_BYTES:
        _fail("training phase receipt would exceed the 8 GiB artifact cap")
    _atomic_write(receipt_path, receipt)
    if _artifact_usage()["bytes"] > ARTIFACT_LIMIT_BYTES:
        _fail("training phase receipt exceeded the 8 GiB artifact cap")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    sub.add_parser("verify-freeze")
    sub.add_parser("import-baseline")
    command = sub.add_parser("command")
    command.add_argument("--target", type=int, required=True)
    run = sub.add_parser("run")
    run.add_argument("--target", type=int, required=True)
    sub.add_parser("census")
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            result = freeze_training()
        elif args.command == "verify-freeze":
            result = verify_freeze()
        elif args.command == "import-baseline":
            result = import_baseline()
        elif args.command == "command":
            result = {"command": _command(args.target)}
        elif args.command == "run":
            result = run_step(args.target)
        else:
            result = artifact_census()
    except TrainingContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
