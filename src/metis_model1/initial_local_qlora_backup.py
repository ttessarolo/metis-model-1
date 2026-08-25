"""Single-use, preimage-bound S3 backup for ``INITIAL_LOCAL_QLORA_V1``.

``prepare`` and offline verification never invoke AWS.  ``transfer`` is the
only network-capable entry point.  It uses one fixed SSO profile, one
conditional ``PutObject`` attempt, and emits only redacted local evidence.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metis_model1 import initial_local_qlora_runtime as runtime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v2"
ARCHIVE_PATH = RUN_ROOT / "metis-model1-adapter.tar"
ARCHIVE_RECEIPT_PATH = RUN_ROOT / "metis-model1-adapter-archive.json"
PREIMAGE_PATH = PROJECT_ROOT / "manifests/initial-local-qlora-backup-preimage-v1.json"
ATTEMPT_PATH = RUN_ROOT / "metis-model1-adapter-backup-started.json"
RECEIPT_PATH = RUN_ROOT / "metis-model1-adapter-backup-receipt.json"
AWS_CLI_ENTRY = Path("/usr/local/bin/aws")

WAVE = "INITIAL_LOCAL_QLORA_V1"
ACCOUNT_ID = "670565864033"
ROLE_NAME = "MetisModel1BackupWriter"
PROFILE = "MetisModel1BackupWriter-670565864033"
REGION = "eu-west-1"
BUCKET = "metis-model-1"
REMOTE = "origin"
CONTENT_TYPE = "application/x-tar"
SERVER_SIDE_ENCRYPTION = "AES256"

BOUND_CODE_PATHS = (
    "docs/18-initial-local-qlora.md",
    "manifests/initial-local-qlora-plan-v1.json",
    "src/metis_model1/initial_local_qlora_backup.py",
    "src/metis_model1/initial_local_qlora_runtime.py",
    "tests/test_initial_local_qlora_backup.py",
)
AWS_OPERATIONS = (
    "sts-get-caller-identity",
    "s3-get-bucket-location",
    "s3-get-bucket-versioning",
    "s3-list-versions-before",
    "s3-put-once",
    "s3-head-version",
    "s3-head-current",
    "s3-list-versions-after",
    "s3-get-version",
)
AWS_ENVIRONMENT_KEYS = (
    "AWS_CLI_AUTO_PROMPT",
    "AWS_EC2_METADATA_DISABLED",
    "AWS_MAX_ATTEMPTS",
    "AWS_PAGER",
    "AWS_RETRY_MODE",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
)
NONCLAIMS = (
    "no_adapter_distribution",
    "no_promotion",
    "no_dataset_base_optimizer_or_raw_output_upload",
    "no_credential_material_in_evidence",
    "no_second_put_attempt",
)


class BackupContractError(ValueError):
    """Raised when the single-use backup contract cannot advance safely."""


def _fail(message: str) -> None:
    raise BackupContractError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _safe_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        _fail(f"required file is missing, linked, or unsafe: {path}")


def _file_record(path: Path) -> dict[str, Any]:
    _safe_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": "sha256:" + digest.hexdigest()}


def _json(path: Path) -> dict[str, Any]:
    _safe_file(path)
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"invalid JSON evidence: {path}: {exc}")
    if not isinstance(value, dict):
        _fail(f"JSON evidence must be an object: {path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite backup evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(value, allow_nan=False, sort_keys=True).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_name, path, follow_symlinks=False)
        except FileExistsError:
            _fail(f"refusing to overwrite backup evidence: {path}")
        os.unlink(temporary_name)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def _relative(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        _fail(f"backup path is outside the project: {path}")


def _git_text(*args: str) -> str:
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
        _fail(f"cannot verify backup Git identity: {exc}")


def _git_blob(commit: str, relative: str) -> bytes:
    try:
        return subprocess.check_output(
            ["/usr/bin/git", "-C", str(PROJECT_ROOT), "show", f"{commit}:{relative}"],
            stderr=subprocess.STDOUT,
            timeout=30,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(f"cannot reopen bound backup input {relative}: {exc}")


def _bound_code(commit: str) -> dict[str, str]:
    records: dict[str, str] = {}
    for relative in BOUND_CODE_PATHS:
        path = PROJECT_ROOT / relative
        _safe_file(path)
        live = path.read_bytes()
        if _git_blob(commit, relative) != live:
            _fail(f"backup implementation differs from Git preimage: {relative}")
        records[relative] = "sha256:" + hashlib.sha256(live).hexdigest()
    return records


def _aws_cli_identity() -> dict[str, Any]:
    try:
        resolved = AWS_CLI_ENTRY.resolve(strict=True)
    except OSError as exc:
        _fail(f"fixed AWS CLI entry is unavailable: {exc}")
    _safe_file(resolved)
    if not os.access(resolved, os.X_OK):
        _fail("fixed AWS CLI target is not executable")
    record = _file_record(resolved)
    return {
        "entry": str(AWS_CLI_ENTRY),
        "resolved": str(resolved),
        "bytes": record["bytes"],
        "sha256": record["sha256"],
    }


def _verified_archive_bundle() -> dict[str, Any]:
    archive = _file_record(ARCHIVE_PATH)
    receipt_record = _file_record(ARCHIVE_RECEIPT_PATH)
    receipt = _json(ARCHIVE_RECEIPT_PATH)
    body = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    live_restore = runtime.verify_archive(ARCHIVE_PATH)
    expected_archive_record = {"path": str(ARCHIVE_PATH), **archive}
    if (
        set(receipt)
        != {
            "schema_version",
            "status",
            "package_sha256",
            "archive",
            "fresh_restore",
            "receipt_sha256",
        }
        or receipt.get("schema_version") != 1
        or receipt.get("status") != "sealed"
        or not _is_hash(receipt.get("package_sha256"))
        or receipt.get("archive") != expected_archive_record
        or receipt.get("fresh_restore") != live_restore
        or receipt.get("receipt_sha256") != _canonical_hash(body)
    ):
        _fail("local archive receipt or fresh-restore evidence drift")
    return {
        "archive": {"path": _relative(ARCHIVE_PATH), **archive},
        "archive_receipt": {
            "path": _relative(ARCHIVE_RECEIPT_PATH),
            **receipt_record,
            "self_sha256": receipt["receipt_sha256"],
        },
        "package_sha256": receipt["package_sha256"],
        "fresh_restore": _redacted_restore_summary(live_restore),
        "fresh_restore_sha256": _canonical_hash(live_restore),
    }


def _aws_terms(archive: Mapping[str, Any], package_sha256: str) -> dict[str, Any]:
    archive_sha256 = archive["sha256"]
    if not _is_hash(archive_sha256) or not _is_hash(package_sha256):
        _fail("archive or package hash is malformed")
    digest = archive_sha256[7:]
    prefix = f"metis-model1/{digest}/"
    return {
        "account_id": ACCOUNT_ID,
        "role_name": ROLE_NAME,
        "profile": PROFILE,
        "region": REGION,
        "bucket": BUCKET,
        "expected_bucket_owner": ACCOUNT_ID,
        "prefix": prefix,
        "object_key": prefix + "metis-model1-adapter.tar",
        "object_count": 1,
        "server_side_encryption": SERVER_SIDE_ENCRYPTION,
        "bucket_versioning": "Enabled",
        "content_type": CONTENT_TYPE,
        "checksum_algorithm": "SHA256",
        "if_none_match": "*",
        "acl": "not_set",
        "put_attempts": 1,
        "metadata": {
            "archive-sha256": digest,
            "package-sha256": package_sha256[7:],
            "wave": WAVE,
        },
    }


def _command_policy() -> dict[str, Any]:
    return {
        "operations": list(AWS_OPERATIONS),
        "environment_keys": list(AWS_ENVIRONMENT_KEYS),
        "subprocess_argv_only": True,
        "shell": False,
        "put_attempts": 1,
        "internal_aws_max_attempts": 1,
        "conditional_no_clobber": True,
        "version_history_census": "before_and_after",
        "version_list_max_keys": 2,
        "version_list_pagination": False,
        "delete_markers_allowed": False,
        "raw_stdout_stderr_retained": False,
        "download_to_fresh_temporary_directory": True,
        "receipt_redacted": True,
    }


def _preimage_body(commit: str, tree: str, branch: str) -> dict[str, Any]:
    bundle = _verified_archive_bundle()
    return {
        "schema_version": 1,
        "preimage_id": "initial-local-qlora-s3-backup-preimage/v1",
        "status": "prepared_before_s3_transfer",
        "wave": WAVE,
        "preimage_commit": commit,
        "preimage_tree": tree,
        "branch": branch,
        "remote": REMOTE,
        "bound_code": _bound_code(commit),
        **bundle,
        "aws_cli": _aws_cli_identity(),
        "aws": _aws_terms(bundle["archive"], bundle["package_sha256"]),
        "command_policy": _command_policy(),
        "attempt_path": _relative(ATTEMPT_PATH),
        "receipt_path": _relative(RECEIPT_PATH),
        "nonclaims": list(NONCLAIMS),
    }


def _verify_git_binding(value: Mapping[str, Any], *, require_published_remote: bool) -> str:
    commit = value.get("preimage_commit")
    tree = value.get("preimage_tree")
    branch = value.get("branch")
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or not isinstance(tree, str)
        or len(tree) != 40
        or not isinstance(branch, str)
        or not branch
        or _git_text("rev-parse", f"{commit}^{{commit}}") != commit
        or _git_text("rev-parse", f"{commit}^{{tree}}") != tree
        or _git_text("symbolic-ref", "--quiet", "--short", "HEAD") != branch
    ):
        _fail("backup Git preimage identity drift")
    if _git_text("ls-tree", "--name-only", commit, "--", _relative(PREIMAGE_PATH)):
        _fail("backup preimage path was already present in the bound preimage commit")
    current_head = _git_text("rev-parse", "HEAD")
    _git_text("merge-base", "--is-ancestor", commit, current_head)
    if require_published_remote:
        remote_ref = f"refs/heads/{branch}"
        tracking_ref = f"refs/remotes/{REMOTE}/{branch}"
        if _git_text("rev-parse", tracking_ref) != current_head:
            _fail("backup publication differs from the origin tracking ref")
        raw = _git_text("ls-remote", "--exit-code", "--heads", REMOTE, remote_ref)
        rows = [row.split() for row in raw.splitlines() if row.strip()]
        if rows != [[current_head, remote_ref]]:
            _fail("backup publication is not the exact remote branch head")
        relative = _relative(PREIMAGE_PATH)
        if _git_blob(current_head, relative) != PREIMAGE_PATH.read_bytes():
            _fail("live backup preimage differs from published Git evidence")
    return current_head


def prepare(preimage_commit: str, preimage_tree: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Prepare the fixed tracked preimage without invoking AWS or any network API."""
    if PREIMAGE_PATH.exists() or PREIMAGE_PATH.is_symlink():
        _fail("backup preimage path must be absent")
    if (
        ATTEMPT_PATH.exists()
        or ATTEMPT_PATH.is_symlink()
        or RECEIPT_PATH.exists()
        or RECEIPT_PATH.is_symlink()
    ):
        _fail("backup transfer evidence already exists")
    branch = _git_text("symbolic-ref", "--quiet", "--short", "HEAD")
    if (
        _git_text("rev-parse", "HEAD") != preimage_commit
        or _git_text("rev-parse", "HEAD^{tree}") != preimage_tree
        or _git_text("rev-parse", f"{preimage_commit}^{{commit}}") != preimage_commit
        or _git_text("rev-parse", f"{preimage_commit}^{{tree}}") != preimage_tree
        or _git_text("ls-tree", "--name-only", preimage_commit, "--", _relative(PREIMAGE_PATH))
    ):
        _fail("caller-supplied backup Git HEAD/tree is not the live preimage")
    body = _preimage_body(preimage_commit, preimage_tree, branch)
    value = {**body, "preimage_sha256": _canonical_hash(body)}
    if not dry_run:
        _atomic_json(PREIMAGE_PATH, value)
    return value


def verify_preimage(*, require_published_remote: bool = False) -> dict[str, Any]:
    """Reopen the exact local contract; remote publication is optional and explicit."""
    value = _json(PREIMAGE_PATH)
    body = {key: item for key, item in value.items() if key != "preimage_sha256"}
    if value.get("preimage_sha256") != _canonical_hash(body):
        _fail("backup preimage self-hash mismatch")
    current_head = _verify_git_binding(value, require_published_remote=require_published_remote)
    expected = _preimage_body(
        str(value.get("preimage_commit")),
        str(value.get("preimage_tree")),
        str(value.get("branch")),
    )
    if body != expected:
        _fail("backup preimage identity, archive, or policy drift")
    return {"status": "verified", "publication_head": current_head, "preimage": value}


def _aws_environment() -> dict[str, str]:
    home = os.environ.get("HOME")
    if not home or not Path(home).is_absolute() or "\x00" in home:
        _fail("a fixed absolute HOME is required for the named AWS SSO profile")
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": home,
        "LANG": "C",
        "LC_ALL": "C",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_RETRY_MODE": "standard",
        "AWS_MAX_ATTEMPTS": "1",
        "AWS_PAGER": "",
        "AWS_CLI_AUTO_PROMPT": "off",
    }
    if tuple(sorted(environment)) != AWS_ENVIRONMENT_KEYS:
        _fail("closed AWS environment allowlist drift")
    return environment


def _run_aws(
    cli_path: str,
    operation_id: str,
    service: str,
    operation: str,
    arguments: Sequence[str],
    query: str,
    *,
    destination: Path | None = None,
) -> dict[str, Any]:
    if operation_id not in AWS_OPERATIONS:
        _fail("AWS operation is outside the fixed command policy")
    argv = [
        cli_path,
        "--profile",
        PROFILE,
        "--region",
        REGION,
        "--no-cli-pager",
        "--no-cli-auto-prompt",
        "--output",
        "json",
        "--query",
        query,
        service,
        operation,
        *arguments,
    ]
    if destination is not None:
        if destination.exists() or destination.is_symlink():
            _fail("fresh S3 download destination must be absent")
        argv.append(str(destination))
    try:
        completed = subprocess.run(
            argv,
            cwd=PROJECT_ROOT,
            env=_aws_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=600 if destination is not None else 120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(f"AWS operation {operation_id} did not complete: {type(exc).__name__}")
    if (
        completed.returncode != 0
        or len(completed.stdout.encode("utf-8")) > 128 * 1024
        or len(completed.stderr.encode("utf-8")) > 32 * 1024
    ):
        _fail(f"AWS operation {operation_id} failed closed")
    try:
        value = json.loads(completed.stdout)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        _fail(f"AWS operation {operation_id} returned invalid JSON")
    if not isinstance(value, dict):
        _fail(f"AWS operation {operation_id} did not return an object")
    return value


def _expected_owner_arguments() -> list[str]:
    return ["--expected-bucket-owner", ACCOUNT_ID]


def _list_arguments(prefix: str) -> list[str]:
    return [
        "--bucket",
        BUCKET,
        "--prefix",
        prefix,
        "--max-keys",
        "2",
        "--no-paginate",
        *_expected_owner_arguments(),
    ]


VERSION_LIST_QUERY = (
    "{IsTruncated:IsTruncated,Versions:Versions[].{Key:Key,VersionId:VersionId,"
    "IsLatest:IsLatest,Size:Size,ETag:ETag},DeleteMarkers:DeleteMarkers[].{Key:Key,"
    "VersionId:VersionId,IsLatest:IsLatest}}"
)
OBJECT_QUERY = (
    "{ContentLength:ContentLength,ChecksumSHA256:ChecksumSHA256,"
    "ServerSideEncryption:ServerSideEncryption,Metadata:Metadata,VersionId:VersionId,"
    "ETag:ETag,ContentType:ContentType}"
)


def _empty_version_prefix(value: Mapping[str, Any]) -> bool:
    return (
        set(value) == {"IsTruncated", "Versions", "DeleteMarkers"}
        and value.get("IsTruncated") is False
        and value.get("Versions") in (None, [])
        and value.get("DeleteMarkers") in (None, [])
    )


def _single_version_prefix(
    value: Mapping[str, Any],
    *,
    key: str,
    version_id: str,
    archive_bytes: int,
    etag: str,
) -> bool:
    return (
        set(value) == {"IsTruncated", "Versions", "DeleteMarkers"}
        and value.get("IsTruncated") is False
        and value.get("Versions")
        == [
            {
                "Key": key,
                "VersionId": version_id,
                "IsLatest": True,
                "Size": archive_bytes,
                "ETag": etag,
            }
        ]
        and value.get("DeleteMarkers") in (None, [])
    )


def _object_evidence(
    value: Mapping[str, Any],
    *,
    aws: Mapping[str, Any],
    archive: Mapping[str, Any],
    version_id: str,
    checksum_sha256: str,
    etag: str,
) -> bool:
    return (
        set(value)
        == {
            "ContentLength",
            "ChecksumSHA256",
            "ServerSideEncryption",
            "Metadata",
            "VersionId",
            "ETag",
            "ContentType",
        }
        and value.get("ContentLength") == archive.get("bytes")
        and value.get("ChecksumSHA256") == checksum_sha256
        and value.get("ServerSideEncryption") == SERVER_SIDE_ENCRYPTION
        and value.get("Metadata") == aws.get("metadata")
        and value.get("VersionId") == version_id
        and value.get("ETag") == etag
        and value.get("ContentType") == CONTENT_TYPE
    )


def _attempt_marker(preimage: Mapping[str, Any], publication_head: str) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "status": "started_no_retry",
        "wave": WAVE,
        "preimage_file_sha256": _file_record(PREIMAGE_PATH)["sha256"],
        "preimage_self_sha256": preimage["preimage_sha256"],
        "publication_head": publication_head,
        "object_key": preimage["aws"]["object_key"],
        "operations": list(AWS_OPERATIONS),
        "put_attempts": 1,
    }
    return {**body, "marker_sha256": _canonical_hash(body)}


def _verify_marker(preimage: Mapping[str, Any], current_head: str) -> dict[str, Any]:
    marker = _json(ATTEMPT_PATH)
    body = {key: item for key, item in marker.items() if key != "marker_sha256"}
    if (
        set(marker)
        != {
            "schema_version",
            "status",
            "wave",
            "preimage_file_sha256",
            "preimage_self_sha256",
            "publication_head",
            "object_key",
            "operations",
            "put_attempts",
            "marker_sha256",
        }
        or marker.get("marker_sha256") != _canonical_hash(body)
        or marker.get("schema_version") != 1
        or marker.get("status") != "started_no_retry"
        or marker.get("wave") != WAVE
        or marker.get("preimage_file_sha256") != _file_record(PREIMAGE_PATH)["sha256"]
        or marker.get("preimage_self_sha256") != preimage.get("preimage_sha256")
        or marker.get("object_key") != preimage["aws"]["object_key"]
        or marker.get("operations") != list(AWS_OPERATIONS)
        or marker.get("put_attempts") != 1
    ):
        _fail("backup no-retry marker drift")
    publication_head = marker.get("publication_head")
    if (
        not isinstance(publication_head, str)
        or not re.fullmatch(r"[0-9a-f]{40}", publication_head)
        or _git_text("rev-parse", f"{publication_head}^{{commit}}") != publication_head
    ):
        _fail("backup marker publication commit drift")
    _git_text("merge-base", "--is-ancestor", publication_head, current_head)
    if _git_blob(publication_head, _relative(PREIMAGE_PATH)) != PREIMAGE_PATH.read_bytes():
        _fail("backup marker does not reopen the exact published preimage")
    return marker


def _redacted_restore_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    package = value.get("package")
    members = value.get("members")
    if (
        value.get("status") != "fresh_restore_verified"
        or not isinstance(package, Mapping)
        or package.get("status") != "verified"
        or not isinstance(members, Mapping)
    ):
        _fail("downloaded archive did not pass the fresh-restore contract")
    return {
        "status": "fresh_restore_verified",
        "member_count": len(members),
        "package_status": "verified",
        "package_sha256": package.get("package_sha256"),
        "package_files": package.get("files"),
        "verdict": package.get("verdict"),
        "global_step": package.get("global_step"),
    }


def _assert_redacted(value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, allow_nan=False, sort_keys=True).lower()
    forbidden = (
        ".env",
        "/.aws",
        "aws_access_key",
        "aws_secret",
        "aws_session_token",
        "credential",
        "stdout",
        "stderr",
        "authorization",
        "secret_key",
    )
    if any(token in raw for token in forbidden):
        _fail("backup receipt contains forbidden credential or raw-process material")


def _valid_caller_arn(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return (
        re.fullmatch(
            rf"arn:aws:sts::{ACCOUNT_ID}:assumed-role/"
            rf"AWSReservedSSO_{re.escape(ROLE_NAME)}_[0-9A-Fa-f]{{16}}/"
            r"[A-Za-z0-9+=,.@_-]{2,64}",
            value,
        )
        is not None
    )


def transfer() -> dict[str, Any]:
    """Perform the sole conditional S3 transfer and verify a versioned restore."""
    if (
        ATTEMPT_PATH.exists()
        or ATTEMPT_PATH.is_symlink()
        or RECEIPT_PATH.exists()
        or RECEIPT_PATH.is_symlink()
    ):
        _fail("backup transfer is single-use and already has local evidence")
    verified = verify_preimage(require_published_remote=True)
    preimage = verified["preimage"]
    publication_head = verified["publication_head"]
    aws = preimage["aws"]
    archive = preimage["archive"]
    cli_path = preimage["aws_cli"]["resolved"]
    prefix = aws["prefix"]
    key = aws["object_key"]

    identity = _run_aws(
        cli_path,
        "sts-get-caller-identity",
        "sts",
        "get-caller-identity",
        [],
        "{Account:Account,Arn:Arn}",
    )
    if (
        set(identity) != {"Account", "Arn"}
        or identity.get("Account") != ACCOUNT_ID
        or not _valid_caller_arn(identity.get("Arn"))
    ):
        _fail("AWS caller identity does not match the bound account and role")
    location = _run_aws(
        cli_path,
        "s3-get-bucket-location",
        "s3api",
        "get-bucket-location",
        ["--bucket", BUCKET, *_expected_owner_arguments()],
        "{LocationConstraint:LocationConstraint}",
    )
    if location != {"LocationConstraint": REGION}:
        _fail("S3 bucket region differs from the backup preimage")
    versioning = _run_aws(
        cli_path,
        "s3-get-bucket-versioning",
        "s3api",
        "get-bucket-versioning",
        ["--bucket", BUCKET, *_expected_owner_arguments()],
        "{Status:Status,MFADelete:MFADelete}",
    )
    if set(versioning) != {"Status", "MFADelete"} or versioning.get("Status") != "Enabled":
        _fail("S3 bucket versioning is not enabled")
    before = _run_aws(
        cli_path,
        "s3-list-versions-before",
        "s3api",
        "list-object-versions",
        _list_arguments(prefix),
        VERSION_LIST_QUERY,
    )
    if not _empty_version_prefix(before):
        _fail("exact archive-derived versioned S3 prefix is not empty")

    marker = _attempt_marker(preimage, publication_head)
    _atomic_json(ATTEMPT_PATH, marker)
    digest = archive["sha256"][7:]
    checksum_sha256 = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
    metadata = aws["metadata"]
    metadata_argument = ",".join(f"{name}={metadata[name]}" for name in sorted(metadata))
    put = _run_aws(
        cli_path,
        "s3-put-once",
        "s3api",
        "put-object",
        [
            "--bucket",
            BUCKET,
            "--key",
            key,
            "--body",
            str(ARCHIVE_PATH),
            "--content-type",
            CONTENT_TYPE,
            "--server-side-encryption",
            SERVER_SIDE_ENCRYPTION,
            "--checksum-algorithm",
            "SHA256",
            "--checksum-sha256",
            checksum_sha256,
            "--metadata",
            metadata_argument,
            "--if-none-match",
            "*",
            *_expected_owner_arguments(),
        ],
        "{ETag:ETag,ChecksumSHA256:ChecksumSHA256,"
        "ServerSideEncryption:ServerSideEncryption,VersionId:VersionId}",
    )
    version_id = put.get("VersionId")
    put_etag = put.get("ETag")
    if (
        set(put) != {"ETag", "ChecksumSHA256", "ServerSideEncryption", "VersionId"}
        or not isinstance(version_id, str)
        or not version_id
        or version_id == "null"
        or put.get("ChecksumSHA256") != checksum_sha256
        or put.get("ServerSideEncryption") != SERVER_SIDE_ENCRYPTION
        or not isinstance(put_etag, str)
        or not put_etag
    ):
        _fail("conditional PutObject response lacks exact version/checksum/SSE evidence")

    head_arguments = [
        "--bucket",
        BUCKET,
        "--key",
        key,
        "--checksum-mode",
        "ENABLED",
        *_expected_owner_arguments(),
    ]
    head_version = _run_aws(
        cli_path,
        "s3-head-version",
        "s3api",
        "head-object",
        [*head_arguments, "--version-id", version_id],
        OBJECT_QUERY,
    )
    head_current = _run_aws(
        cli_path,
        "s3-head-current",
        "s3api",
        "head-object",
        head_arguments,
        OBJECT_QUERY,
    )
    if not _object_evidence(
        head_version,
        aws=aws,
        archive=archive,
        version_id=version_id,
        checksum_sha256=checksum_sha256,
        etag=put_etag,
    ) or not _object_evidence(
        head_current,
        aws=aws,
        archive=archive,
        version_id=version_id,
        checksum_sha256=checksum_sha256,
        etag=put_etag,
    ):
        _fail("S3 HeadObject identity, version, metadata, checksum, or SSE drift")
    after = _run_aws(
        cli_path,
        "s3-list-versions-after",
        "s3api",
        "list-object-versions",
        _list_arguments(prefix),
        VERSION_LIST_QUERY,
    )
    if not _single_version_prefix(
        after,
        key=key,
        version_id=version_id,
        archive_bytes=archive["bytes"],
        etag=put_etag,
    ):
        _fail("archive-derived S3 prefix does not contain exactly the sole object version")

    with tempfile.TemporaryDirectory(prefix=".backup-restore-", dir=RUN_ROOT) as temporary:
        downloaded = Path(temporary) / "metis-model1-adapter.tar"
        get = _run_aws(
            cli_path,
            "s3-get-version",
            "s3api",
            "get-object",
            [
                "--bucket",
                BUCKET,
                "--key",
                key,
                "--version-id",
                version_id,
                "--checksum-mode",
                "ENABLED",
                *_expected_owner_arguments(),
            ],
            OBJECT_QUERY,
            destination=downloaded,
        )
        if not _object_evidence(
            get,
            aws=aws,
            archive=archive,
            version_id=version_id,
            checksum_sha256=checksum_sha256,
            etag=put_etag,
        ):
            _fail("versioned S3 download metadata drift")
        downloaded_record = _file_record(downloaded)
        if downloaded_record != {"bytes": archive["bytes"], "sha256": archive["sha256"]}:
            _fail("versioned S3 download bytes differ from the sealed archive")
        restored = runtime.verify_archive(downloaded)
        restore_summary = _redacted_restore_summary(restored)

    receipt_body = {
        "schema_version": 1,
        "status": "uploaded_versioned_restore_verified",
        "wave": WAVE,
        "preimage_file_sha256": _file_record(PREIMAGE_PATH)["sha256"],
        "preimage_self_sha256": preimage["preimage_sha256"],
        "publication_head": publication_head,
        "attempt_file_sha256": _file_record(ATTEMPT_PATH)["sha256"],
        "attempt_self_sha256": marker["marker_sha256"],
        "archive": {"bytes": archive["bytes"], "sha256": archive["sha256"]},
        "package_sha256": preimage["package_sha256"],
        "aws": {
            "account_id": ACCOUNT_ID,
            "profile": PROFILE,
            "region": REGION,
            "bucket": BUCKET,
            "object_key": key,
            "version_id": version_id,
            "server_side_encryption": SERVER_SIDE_ENCRYPTION,
            "checksum_sha256": checksum_sha256,
            "metadata": metadata,
            "content_type": CONTENT_TYPE,
        },
        "version_census": {
            "before": {"is_truncated": False, "versions": 0, "delete_markers": 0},
            "after": {
                "is_truncated": False,
                "versions": 1,
                "delete_markers": 0,
                "key": key,
                "version_id": version_id,
                "is_latest": True,
            },
        },
        "put": {"etag": put_etag, "checksum_sha256": checksum_sha256},
        "head": {
            "version_etag": head_version["ETag"],
            "current_etag": head_current["ETag"],
            "content_length": head_version["ContentLength"],
            "current_version_matches": head_current["VersionId"] == version_id,
        },
        "download": {**downloaded_record, "version_id": version_id, "etag": get["ETag"]},
        "fresh_restore": restore_summary,
        "operations": list(AWS_OPERATIONS),
        "put_attempts": 1,
        "raw_process_output_retained": False,
    }
    _assert_redacted(receipt_body)
    receipt = {**receipt_body, "receipt_sha256": _canonical_hash(receipt_body)}
    _atomic_json(RECEIPT_PATH, receipt)
    return receipt


def verify_receipt(*, require_published_remote: bool = False) -> dict[str, Any]:
    verified = verify_preimage(require_published_remote=require_published_remote)
    preimage = verified["preimage"]
    marker = _verify_marker(preimage, verified["publication_head"])
    receipt = _json(RECEIPT_PATH)
    body = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    aws = receipt.get("aws")
    archive = receipt.get("archive")
    fresh_restore = receipt.get("fresh_restore")
    put = receipt.get("put")
    head = receipt.get("head")
    download = receipt.get("download")
    if (
        set(receipt)
        != {
            "schema_version",
            "status",
            "wave",
            "preimage_file_sha256",
            "preimage_self_sha256",
            "publication_head",
            "attempt_file_sha256",
            "attempt_self_sha256",
            "archive",
            "package_sha256",
            "aws",
            "version_census",
            "put",
            "head",
            "download",
            "fresh_restore",
            "operations",
            "put_attempts",
            "raw_process_output_retained",
            "receipt_sha256",
        }
        or receipt.get("receipt_sha256") != _canonical_hash(body)
        or receipt.get("schema_version") != 1
        or receipt.get("status") != "uploaded_versioned_restore_verified"
        or receipt.get("wave") != WAVE
        or receipt.get("preimage_file_sha256") != _file_record(PREIMAGE_PATH)["sha256"]
        or receipt.get("preimage_self_sha256") != preimage["preimage_sha256"]
        or receipt.get("publication_head") != marker["publication_head"]
        or receipt.get("attempt_file_sha256") != _file_record(ATTEMPT_PATH)["sha256"]
        or receipt.get("attempt_self_sha256") != marker["marker_sha256"]
        or archive
        != {"bytes": preimage["archive"]["bytes"], "sha256": preimage["archive"]["sha256"]}
        or receipt.get("package_sha256") != preimage["package_sha256"]
        or not isinstance(aws, Mapping)
        or set(aws)
        != {
            "account_id",
            "profile",
            "region",
            "bucket",
            "object_key",
            "version_id",
            "server_side_encryption",
            "checksum_sha256",
            "metadata",
            "content_type",
        }
        or aws.get("account_id") != ACCOUNT_ID
        or aws.get("profile") != PROFILE
        or aws.get("region") != REGION
        or aws.get("bucket") != BUCKET
        or aws.get("object_key") != preimage["aws"]["object_key"]
        or not isinstance(aws.get("version_id"), str)
        or not aws["version_id"]
        or aws.get("version_id") == "null"
        or aws.get("server_side_encryption") != SERVER_SIDE_ENCRYPTION
        or aws.get("metadata") != preimage["aws"]["metadata"]
        or aws.get("content_type") != CONTENT_TYPE
        or receipt.get("version_census")
        != {
            "before": {"is_truncated": False, "versions": 0, "delete_markers": 0},
            "after": {
                "is_truncated": False,
                "versions": 1,
                "delete_markers": 0,
                "key": preimage["aws"]["object_key"],
                "version_id": aws.get("version_id"),
                "is_latest": True,
            },
        }
        or not isinstance(put, Mapping)
        or set(put) != {"etag", "checksum_sha256"}
        or not isinstance(put.get("etag"), str)
        or not put["etag"]
        or not isinstance(head, Mapping)
        or set(head)
        != {"version_etag", "current_etag", "content_length", "current_version_matches"}
        or head.get("version_etag") != put.get("etag")
        or head.get("current_etag") != put.get("etag")
        or head.get("content_length") != preimage["archive"]["bytes"]
        or head.get("current_version_matches") is not True
        or not isinstance(download, Mapping)
        or set(download) != {"bytes", "sha256", "version_id", "etag"}
        or download.get("bytes") != preimage["archive"]["bytes"]
        or download.get("sha256") != preimage["archive"]["sha256"]
        or download.get("version_id") != aws.get("version_id")
        or download.get("etag") != put.get("etag")
        or receipt.get("operations") != list(AWS_OPERATIONS)
        or receipt.get("put_attempts") != 1
        or receipt.get("raw_process_output_retained") is not False
        or not isinstance(fresh_restore, Mapping)
        or fresh_restore != preimage.get("fresh_restore")
        or set(fresh_restore)
        != {
            "status",
            "member_count",
            "package_status",
            "package_sha256",
            "package_files",
            "verdict",
            "global_step",
        }
        or fresh_restore.get("status") != "fresh_restore_verified"
        or fresh_restore.get("package_status") != "verified"
        or type(fresh_restore.get("member_count")) is not int
        or fresh_restore["member_count"] < 1
        or type(fresh_restore.get("package_files")) is not int
        or fresh_restore["package_files"] < 1
        or fresh_restore.get("package_sha256") != preimage["package_sha256"]
    ):
        _fail("redacted S3 backup receipt drift")
    expected_checksum = base64.b64encode(bytes.fromhex(preimage["archive"]["sha256"][7:])).decode(
        "ascii"
    )
    if aws.get("checksum_sha256") != expected_checksum:
        _fail("redacted S3 receipt checksum drift")
    if put.get("checksum_sha256") != expected_checksum:
        _fail("redacted S3 receipt PutObject checksum drift")
    _assert_redacted(receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--preimage-commit", required=True)
    prepare_parser.add_argument("--preimage-tree", required=True)
    prepare_parser.add_argument("--dry-run", action="store_true")
    verify_parser = subparsers.add_parser("verify-preimage")
    verify_parser.add_argument("--require-published-remote", action="store_true")
    subparsers.add_parser("transfer")
    receipt_parser = subparsers.add_parser("verify-receipt")
    receipt_parser.add_argument("--require-published-remote", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.preimage_commit, args.preimage_tree, dry_run=args.dry_run)
        elif args.command == "verify-preimage":
            result = verify_preimage(require_published_remote=args.require_published_remote)
        elif args.command == "transfer":
            result = transfer()
        else:
            result = verify_receipt(require_published_remote=args.require_published_remote)
    except BackupContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
