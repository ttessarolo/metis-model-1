from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from metis_model1 import initial_local_qlora_backup as backup

COMMIT = "a" * 40
TREE = "b" * 40
BRANCH = "codex/model1-local-99-foundation"
HISTORICAL_PRODUCER = backup.BACKUP_IMPLEMENTATION_PATH
HISTORICAL_BOUND = b"bound\n"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False, sort_keys=True) + "\n", encoding="utf-8")


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, prepare: bool = True) -> dict:
    root = tmp_path / "repo"
    run_root = root / "artifacts/initial-local-qlora-v1/run-v2"
    run_root.mkdir(parents=True)
    archive = run_root / "metis-model1-adapter.tar"
    archive.write_bytes(b"sealed-adapter-archive\n")
    archive_record = backup._file_record(archive)
    package_sha256 = "sha256:" + "c" * 64
    fresh_restore = {
        "status": "fresh_restore_verified",
        "archive": archive_record,
        "members": {
            "metis-model1-adapter/manifest.json": {
                "bytes": 2,
                "sha256": "sha256:" + "d" * 64,
            }
        },
        "package": {
            "status": "verified",
            "verdict": "LOCAL_ADAPTER_UPLIFT",
            "model_revision": "revision",
            "global_step": 50,
            "package_sha256": package_sha256,
            "files": 11,
        },
    }
    archive_receipt = run_root / "metis-model1-adapter-archive.json"
    archive_receipt_body = {
        "schema_version": 1,
        "status": "sealed",
        "package_sha256": package_sha256,
        "archive": {"path": str(archive), **archive_record},
        "fresh_restore": fresh_restore,
    }
    _write_json(
        archive_receipt,
        {
            **archive_receipt_body,
            "receipt_sha256": backup._canonical_hash(archive_receipt_body),
        },
    )
    aws_entry = root / "bin/aws"
    aws_entry.parent.mkdir(parents=True)
    aws_entry.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    aws_entry.chmod(0o755)
    bound_file = root / "bound.txt"
    bound_file.write_bytes(HISTORICAL_BOUND)
    producer_source = (f'BOUND_CODE_PATHS = ("bound.txt", "{HISTORICAL_PRODUCER}")\n').encode()
    producer_file = root / HISTORICAL_PRODUCER
    producer_file.parent.mkdir(parents=True, exist_ok=True)
    producer_file.write_bytes(producer_source)
    historical_blobs = {
        HISTORICAL_PRODUCER: producer_source,
        "bound.txt": HISTORICAL_BOUND,
    }

    monkeypatch.setattr(backup, "PROJECT_ROOT", root)
    monkeypatch.setattr(backup, "RUN_ROOT", run_root)
    monkeypatch.setattr(backup, "ARCHIVE_PATH", archive)
    monkeypatch.setattr(backup, "ARCHIVE_RECEIPT_PATH", archive_receipt)
    monkeypatch.setattr(
        backup,
        "PREIMAGE_PATH",
        root / "manifests/initial-local-qlora-backup-preimage-v1.json",
    )
    monkeypatch.setattr(
        backup,
        "ATTEMPT_PATH",
        run_root / "metis-model1-adapter-backup-started.json",
    )
    monkeypatch.setattr(
        backup,
        "RECEIPT_PATH",
        run_root / "metis-model1-adapter-backup-receipt.json",
    )
    monkeypatch.setattr(backup, "AWS_CLI_ENTRY", aws_entry)
    monkeypatch.setattr(backup, "BOUND_CODE_PATHS", ("bound.txt", HISTORICAL_PRODUCER))
    monkeypatch.setattr(
        backup.runtime,
        "verify_archive",
        lambda _path: copy.deepcopy(fresh_restore),
    )

    def git_text(*args: str) -> str:
        mapping = {
            ("symbolic-ref", "--quiet", "--short", "HEAD"): BRANCH,
            ("rev-parse", "HEAD"): COMMIT,
            ("rev-parse", "HEAD^{tree}"): TREE,
            ("rev-parse", f"{COMMIT}^{{commit}}"): COMMIT,
            ("rev-parse", f"{COMMIT}^{{tree}}"): TREE,
            ("rev-parse", f"refs/remotes/{backup.REMOTE}/{BRANCH}"): COMMIT,
            ("merge-base", "--is-ancestor", COMMIT, COMMIT): "",
            (
                "ls-tree",
                "--name-only",
                COMMIT,
                "--",
                "manifests/initial-local-qlora-backup-preimage-v1.json",
            ): "",
            (
                "ls-remote",
                "--exit-code",
                "--heads",
                backup.REMOTE,
                f"refs/heads/{BRANCH}",
            ): f"{COMMIT}\trefs/heads/{BRANCH}",
        }
        try:
            return mapping[args]
        except KeyError as exc:
            raise AssertionError(f"unexpected git call: {args}") from exc

    monkeypatch.setattr(backup, "_git_text", git_text)

    def git_blob(commit: str, relative: str) -> bytes:
        assert commit == COMMIT
        if relative in historical_blobs:
            return historical_blobs[relative]
        if relative == "manifests/initial-local-qlora-backup-preimage-v1.json":
            return backup.PREIMAGE_PATH.read_bytes()
        raise AssertionError(f"unexpected git blob: {relative}")

    monkeypatch.setattr(backup, "_git_blob", git_blob)
    document = backup.prepare(COMMIT, TREE) if prepare else None
    return {
        "root": root,
        "run_root": run_root,
        "archive": archive,
        "archive_bytes": archive.read_bytes(),
        "preimage": document,
        "fresh_restore": fresh_restore,
        "bound_file": bound_file,
        "producer_file": producer_file,
        "historical_blobs": historical_blobs,
    }


def _aws_responses(context: dict) -> dict[str, dict]:
    preimage = context["preimage"]
    archive = preimage["archive"]
    aws = preimage["aws"]
    checksum = base64.b64encode(bytes.fromhex(archive["sha256"][7:])).decode("ascii")
    version_id = "/opaque+version=0001"
    object_evidence = {
        "ContentLength": archive["bytes"],
        "ChecksumSHA256": checksum,
        "ServerSideEncryption": backup.SERVER_SIDE_ENCRYPTION,
        "Metadata": aws["metadata"],
        "VersionId": version_id,
        "ETag": '"etag"',
        "ContentType": backup.CONTENT_TYPE,
    }
    return {
        "sts-get-caller-identity": {
            "Account": backup.ACCOUNT_ID,
            "Arn": (
                f"arn:aws:sts::{backup.ACCOUNT_ID}:assumed-role/"
                f"AWSReservedSSO_{backup.ROLE_NAME}_0123456789abcdef/metis-session"
            ),
        },
        "s3-get-bucket-location": {"LocationConstraint": backup.REGION},
        "s3-get-bucket-versioning": {"Status": "Enabled", "MFADelete": None},
        "s3-list-versions-before": {
            "IsTruncated": False,
            "Versions": None,
            "DeleteMarkers": None,
        },
        "s3-put-once": {
            "ETag": '"etag"',
            "ChecksumSHA256": checksum,
            "ServerSideEncryption": backup.SERVER_SIDE_ENCRYPTION,
            "VersionId": version_id,
        },
        "s3-head-version": copy.deepcopy(object_evidence),
        "s3-head-current": copy.deepcopy(object_evidence),
        "s3-list-versions-after": {
            "IsTruncated": False,
            "Versions": [
                {
                    "Key": aws["object_key"],
                    "VersionId": version_id,
                    "IsLatest": True,
                    "Size": archive["bytes"],
                    "ETag": '"etag"',
                }
            ],
            "DeleteMarkers": None,
        },
        "s3-get-version": copy.deepcopy(object_evidence),
    }


def _mock_aws(
    context: dict,
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, dict] | None = None,
) -> list[dict]:
    response_map = responses or _aws_responses(context)
    calls: list[dict] = []

    def run(
        cli_path: str,
        operation_id: str,
        service: str,
        operation: str,
        arguments,
        query: str,
        *,
        destination: Path | None = None,
    ) -> dict:
        calls.append(
            {
                "cli_path": cli_path,
                "operation_id": operation_id,
                "service": service,
                "operation": operation,
                "arguments": list(arguments),
                "query": query,
                "destination": destination,
            }
        )
        if destination is not None:
            assert not destination.exists()
            destination.write_bytes(context["archive_bytes"])
        return copy.deepcopy(response_map[operation_id])

    monkeypatch.setattr(backup, "_run_aws", run)
    return calls


def test_prepare_and_dry_run_are_offline_and_bind_exact_identity(tmp_path, monkeypatch) -> None:
    assert "tests/test_initial_local_qlora_backup.py" in backup.BOUND_CODE_PATHS
    context = _configure(tmp_path, monkeypatch, prepare=False)
    monkeypatch.setattr(
        backup,
        "_run_aws",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )

    preview = backup.prepare(COMMIT, TREE, dry_run=True)

    assert not backup.PREIMAGE_PATH.exists()
    assert preview["preimage_commit"] == COMMIT
    assert preview["preimage_tree"] == TREE
    assert preview["aws"]["profile"] == "MetisModel1BackupWriter-670565864033"
    assert preview["aws"]["bucket"] == "metis-model-1"
    assert preview["aws"]["region"] == "eu-west-1"
    assert preview["aws"]["object_key"] == (
        f"metis-model1/{preview['archive']['sha256'][7:]}/metis-model1-adapter.tar"
    )
    assert preview["aws"]["put_attempts"] == 1
    assert preview["aws"]["acl"] == "not_set"
    assert preview["command_policy"]["version_history_census"] == "before_and_after"
    assert preview["command_policy"]["version_list_max_keys"] == 2
    assert preview["command_policy"]["version_list_pagination"] is False
    assert preview["command_policy"]["delete_markers_allowed"] is False
    assert context["archive"].is_file()

    written = backup.prepare(COMMIT, TREE)
    assert backup.PREIMAGE_PATH.is_file()
    assert json.loads(backup.PREIMAGE_PATH.read_text()) == written


def test_prepare_rejects_dangling_receipt_symlink_before_any_call(tmp_path, monkeypatch) -> None:
    _configure(tmp_path, monkeypatch, prepare=False)
    backup.RECEIPT_PATH.symlink_to(backup.RECEIPT_PATH.with_name("missing-receipt-target"))
    calls = []
    monkeypatch.setattr(backup, "_run_aws", lambda *_args, **_kwargs: calls.append("aws"))

    with pytest.raises(backup.BackupContractError, match="transfer evidence already exists"):
        backup.prepare(COMMIT, TREE)

    assert calls == []
    assert not backup.ATTEMPT_PATH.exists()


def test_transfer_rejects_dangling_receipt_symlink_before_any_call(tmp_path, monkeypatch) -> None:
    context = _configure(tmp_path, monkeypatch)
    backup.RECEIPT_PATH.symlink_to(backup.RECEIPT_PATH.with_name("missing-receipt-target"))
    calls = _mock_aws(context, monkeypatch)

    with pytest.raises(backup.BackupContractError, match="single-use"):
        backup.transfer()

    assert calls == []
    assert not backup.ATTEMPT_PATH.exists()


def test_verify_preimage_rejects_self_consistent_archive_drift(tmp_path, monkeypatch) -> None:
    _configure(tmp_path, monkeypatch)
    value = json.loads(backup.PREIMAGE_PATH.read_text())
    value["archive"]["sha256"] = "sha256:" + "f" * 64
    value["aws"]["prefix"] = f"metis-model1/{'f' * 64}/"
    value["aws"]["object_key"] = value["aws"]["prefix"] + "metis-model1-adapter.tar"
    body = {key: item for key, item in value.items() if key != "preimage_sha256"}
    value["preimage_sha256"] = backup._canonical_hash(body)
    _write_json(backup.PREIMAGE_PATH, value)

    with pytest.raises(backup.BackupContractError, match="policy drift"):
        backup.verify_preimage()


def test_verify_preimage_rechecks_path_absent_from_bound_commit(tmp_path, monkeypatch) -> None:
    _configure(tmp_path, monkeypatch)
    original_git_text = backup._git_text

    def git_text(*args: str) -> str:
        if args[:2] == ("ls-tree", "--name-only"):
            return "manifests/initial-local-qlora-backup-preimage-v1.json"
        return original_git_text(*args)

    monkeypatch.setattr(backup, "_git_text", git_text)

    with pytest.raises(backup.BackupContractError, match="already present"):
        backup.verify_preimage()


def test_closed_aws_subprocess_environment_has_no_ambient_credentials(
    tmp_path, monkeypatch
) -> None:
    context = _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "ambient-token")
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid")
    seen = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(backup.subprocess, "run", run)
    backup._run_aws(
        context["preimage"]["aws_cli"]["resolved"],
        "sts-get-caller-identity",
        "sts",
        "get-caller-identity",
        [],
        "{}",
    )

    assert set(seen["env"]) == set(backup.AWS_ENVIRONMENT_KEYS)
    assert seen["env"]["AWS_MAX_ATTEMPTS"] == "1"
    assert seen["env"]["AWS_EC2_METADATA_DISABLED"] == "true"
    assert all("ambient" not in value for value in seen["env"].values())
    assert "--profile" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--profile") + 1] == backup.PROFILE
    assert seen.get("shell", False) is False
    assert seen["stdin"] is backup.subprocess.DEVNULL


@pytest.mark.parametrize(
    ("field", "entry"),
    [
        (
            "Versions",
            {
                "Key": "hidden-old-version",
                "VersionId": "old-version",
                "IsLatest": False,
                "Size": 1,
                "ETag": '"old"',
            },
        ),
        (
            "DeleteMarkers",
            {
                "Key": "hidden-delete-marker",
                "VersionId": "delete-marker",
                "IsLatest": True,
            },
        ),
    ],
)
def test_preexisting_version_or_delete_marker_stops_before_marker_and_put(
    tmp_path, monkeypatch, field, entry
) -> None:
    context = _configure(tmp_path, monkeypatch)
    responses = _aws_responses(context)
    responses["s3-list-versions-before"][field] = [
        {**entry, "Key": context["preimage"]["aws"]["object_key"]}
    ]
    calls = _mock_aws(context, monkeypatch, responses)

    with pytest.raises(backup.BackupContractError, match="versioned S3 prefix is not empty"):
        backup.transfer()

    assert [call["operation_id"] for call in calls] == list(backup.AWS_OPERATIONS[:4])
    assert not backup.ATTEMPT_PATH.exists()
    assert not backup.RECEIPT_PATH.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_version",
        "delete_marker",
        "truncated",
        "missing_versions",
        "null_version",
        "not_latest",
    ],
)
def test_post_put_version_census_rejects_history_or_malformed_evidence(
    tmp_path, monkeypatch, mutation
) -> None:
    context = _configure(tmp_path, monkeypatch)
    responses = _aws_responses(context)
    after = responses["s3-list-versions-after"]
    if mutation == "extra_version":
        after["Versions"].append(
            {
                "Key": context["preimage"]["aws"]["object_key"],
                "VersionId": "old-version",
                "IsLatest": False,
                "Size": 1,
                "ETag": '"old"',
            }
        )
    elif mutation == "delete_marker":
        after["DeleteMarkers"] = [
            {
                "Key": context["preimage"]["aws"]["object_key"],
                "VersionId": "delete-marker",
                "IsLatest": False,
            }
        ]
    elif mutation == "truncated":
        after["IsTruncated"] = True
    elif mutation == "missing_versions":
        del after["Versions"]
    elif mutation == "null_version":
        after["Versions"][0]["VersionId"] = "null"
    else:
        after["Versions"][0]["IsLatest"] = False
    calls = _mock_aws(context, monkeypatch, responses)

    with pytest.raises(backup.BackupContractError, match="sole object version"):
        backup.transfer()

    operations = [call["operation_id"] for call in calls]
    assert operations.count("s3-put-once") == 1
    assert operations[-1] == "s3-list-versions-after"
    assert "s3-get-version" not in operations
    assert backup.ATTEMPT_PATH.is_file()
    assert not backup.RECEIPT_PATH.exists()


@pytest.mark.parametrize(
    "arn",
    [
        (
            f"arn:aws:sts::{backup.ACCOUNT_ID}:assumed-role/"
            f"{backup.ROLE_NAME}_0123456789abcdef/metis-session"
        ),
        (
            f"arn:aws:sts::{backup.ACCOUNT_ID}:assumed-role/"
            f"AWSReservedSSO_{backup.ROLE_NAME}_short/metis-session"
        ),
        (
            "arn:aws:sts::999999999999:assumed-role/"
            f"AWSReservedSSO_{backup.ROLE_NAME}_0123456789abcdef/metis-session"
        ),
    ],
)
def test_wrong_sso_role_prefix_suffix_or_account_stops_before_s3(
    tmp_path, monkeypatch, arn
) -> None:
    context = _configure(tmp_path, monkeypatch)
    responses = _aws_responses(context)
    responses["sts-get-caller-identity"]["Arn"] = arn
    calls = _mock_aws(context, monkeypatch, responses)

    with pytest.raises(backup.BackupContractError, match="caller identity"):
        backup.transfer()

    assert [call["operation_id"] for call in calls] == ["sts-get-caller-identity"]
    assert not backup.ATTEMPT_PATH.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("VersionId", None),
        ("ChecksumSHA256", None),
        ("ServerSideEncryption", None),
    ],
)
def test_put_requires_version_checksum_and_sse_and_never_retries(
    tmp_path, monkeypatch, field, value
) -> None:
    context = _configure(tmp_path, monkeypatch)
    responses = _aws_responses(context)
    responses["s3-put-once"][field] = value
    calls = _mock_aws(context, monkeypatch, responses)

    with pytest.raises(backup.BackupContractError, match="PutObject response"):
        backup.transfer()

    operations = [call["operation_id"] for call in calls]
    assert operations.count("s3-put-once") == 1
    assert operations[-1] == "s3-put-once"
    assert backup.ATTEMPT_PATH.is_file()
    assert not backup.RECEIPT_PATH.exists()


def test_head_mismatch_stops_after_one_put_without_download(tmp_path, monkeypatch) -> None:
    context = _configure(tmp_path, monkeypatch)
    responses = _aws_responses(context)
    responses["s3-head-version"]["ServerSideEncryption"] = None
    calls = _mock_aws(context, monkeypatch, responses)

    with pytest.raises(backup.BackupContractError, match="HeadObject"):
        backup.transfer()

    operations = [call["operation_id"] for call in calls]
    assert operations.count("s3-put-once") == 1
    assert "s3-get-version" not in operations
    assert not backup.RECEIPT_PATH.exists()


@pytest.mark.parametrize("operation_id", ["s3-head-version", "s3-head-current", "s3-get-version"])
def test_etag_mismatch_stops_without_receipt(tmp_path, monkeypatch, operation_id) -> None:
    context = _configure(tmp_path, monkeypatch)
    responses = _aws_responses(context)
    responses[operation_id]["ETag"] = '"different-etag"'
    calls = _mock_aws(context, monkeypatch, responses)

    with pytest.raises(backup.BackupContractError, match="HeadObject|download metadata"):
        backup.transfer()

    operations = [call["operation_id"] for call in calls]
    assert operations.count("s3-put-once") == 1
    assert not backup.RECEIPT_PATH.exists()


def test_success_is_redacted_conditional_and_strictly_single_use(tmp_path, monkeypatch) -> None:
    context = _configure(tmp_path, monkeypatch)
    calls = _mock_aws(context, monkeypatch)

    receipt = backup.transfer()

    operations = [call["operation_id"] for call in calls]
    assert operations == list(backup.AWS_OPERATIONS)
    assert operations.count("s3-put-once") == 1
    put = next(call for call in calls if call["operation_id"] == "s3-put-once")
    assert put["arguments"].count("--if-none-match") == 1
    assert put["arguments"][put["arguments"].index("--if-none-match") + 1] == "*"
    assert "--acl" not in put["arguments"]
    assert "--server-side-encryption" in put["arguments"]
    assert put["arguments"].count("--expected-bucket-owner") == 1
    for operation_id in ("s3-list-versions-before", "s3-list-versions-after"):
        version_list = next(call for call in calls if call["operation_id"] == operation_id)
        assert version_list["operation"] == "list-object-versions"
        assert version_list["arguments"].count("--no-paginate") == 1
        assert version_list["arguments"].count("--max-keys") == 1
        assert version_list["arguments"][version_list["arguments"].index("--max-keys") + 1] == "2"
        assert version_list["arguments"].count("--prefix") == 1
        assert (
            version_list["arguments"][version_list["arguments"].index("--prefix") + 1]
            == context["preimage"]["aws"]["prefix"]
        )
        assert "--key-marker" not in version_list["arguments"]
        assert "--version-id-marker" not in version_list["arguments"]
    assert receipt == backup.verify_receipt(require_published_remote=True)
    assert receipt["aws"]["version_id"].startswith("/")
    assert receipt["put"]["etag"] == receipt["head"]["version_etag"]
    assert receipt["put"]["etag"] == receipt["head"]["current_etag"]
    assert receipt["put"]["etag"] == receipt["download"]["etag"]
    assert receipt["version_census"] == {
        "before": {"is_truncated": False, "versions": 0, "delete_markers": 0},
        "after": {
            "is_truncated": False,
            "versions": 1,
            "delete_markers": 0,
            "key": context["preimage"]["aws"]["object_key"],
            "version_id": receipt["aws"]["version_id"],
            "is_latest": True,
        },
    }
    raw = backup.RECEIPT_PATH.read_text().lower()
    for forbidden in (
        ".env",
        "/.aws",
        "aws_access_key",
        "aws_secret",
        "aws_session_token",
        "credential",
        "stdout",
        "stderr",
        str(context["root"]).lower(),
    ):
        assert forbidden not in raw

    observed = len(calls)
    monkeypatch.setattr(
        backup,
        "_run_aws",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("second call")),
    )
    with pytest.raises(backup.BackupContractError, match="single-use"):
        backup.transfer()
    assert len(calls) == observed


def test_receipt_rejects_self_consistent_etag_drift(tmp_path, monkeypatch) -> None:
    context = _configure(tmp_path, monkeypatch)
    _mock_aws(context, monkeypatch)
    backup.transfer()
    receipt = json.loads(backup.RECEIPT_PATH.read_text())
    receipt["download"]["etag"] = '"laundered-etag"'
    body = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = backup._canonical_hash(body)
    _write_json(backup.RECEIPT_PATH, receipt)

    with pytest.raises(backup.BackupContractError, match="receipt drift"):
        backup.verify_receipt()


def test_receipt_rejects_forged_resigned_restore_summary(tmp_path, monkeypatch) -> None:
    context = _configure(tmp_path, monkeypatch)
    _mock_aws(context, monkeypatch)
    backup.transfer()
    receipt = json.loads(backup.RECEIPT_PATH.read_text())
    receipt["fresh_restore"]["verdict"] = "FORGED_VERDICT"
    receipt["fresh_restore"]["global_step"] = 999
    receipt["fresh_restore"]["package_files"] = 999
    receipt["fresh_restore"]["member_count"] = 999
    body = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = backup._canonical_hash(body)
    _write_json(backup.RECEIPT_PATH, receipt)

    with pytest.raises(backup.BackupContractError, match="receipt drift"):
        backup.verify_receipt()


def test_receipt_remains_valid_after_published_head_advances(tmp_path, monkeypatch) -> None:
    context = _configure(tmp_path, monkeypatch)
    _mock_aws(context, monkeypatch)
    receipt = backup.transfer()
    advanced = "e" * 40

    def git_text(*args: str) -> str:
        mapping = {
            ("symbolic-ref", "--quiet", "--short", "HEAD"): BRANCH,
            ("rev-parse", "HEAD"): advanced,
            ("rev-parse", f"{COMMIT}^{{commit}}"): COMMIT,
            ("rev-parse", f"{COMMIT}^{{tree}}"): TREE,
            ("rev-parse", f"refs/remotes/{backup.REMOTE}/{BRANCH}"): advanced,
            ("merge-base", "--is-ancestor", COMMIT, advanced): "",
            (
                "ls-tree",
                "--name-only",
                COMMIT,
                "--",
                "manifests/initial-local-qlora-backup-preimage-v1.json",
            ): "",
            (
                "ls-remote",
                "--exit-code",
                "--heads",
                backup.REMOTE,
                f"refs/heads/{BRANCH}",
            ): f"{advanced}\trefs/heads/{BRANCH}",
        }
        try:
            return mapping[args]
        except KeyError as exc:
            raise AssertionError(f"unexpected git call after publication: {args}") from exc

    def git_blob(commit: str, relative: str) -> bytes:
        if commit == COMMIT and relative in context["historical_blobs"]:
            return context["historical_blobs"][relative]
        if commit in {COMMIT, advanced} and relative == (
            "manifests/initial-local-qlora-backup-preimage-v1.json"
        ):
            return backup.PREIMAGE_PATH.read_bytes()
        raise AssertionError(f"unexpected Git blob after publication: {commit}:{relative}")

    monkeypatch.setattr(backup, "_git_text", git_text)
    monkeypatch.setattr(backup, "_git_blob", git_blob)

    assert backup.verify_receipt(require_published_remote=True) == receipt


def test_historical_receipt_reopens_immutable_producer_and_bound_blobs(
    tmp_path, monkeypatch
) -> None:
    context = _configure(tmp_path, monkeypatch)
    _mock_aws(context, monkeypatch)
    receipt = backup.transfer()

    # The current checkout has legitimately evolved after publication.  The
    # historical verifier must use the producer and bound bytes at the
    # preimage commit, rather than accepting this live implementation drift.
    context["bound_file"].write_bytes(b"live implementation drift\n")
    with pytest.raises(backup.BackupContractError, match="implementation differs"):
        backup.verify_receipt()

    monkeypatch.setattr(
        backup,
        "_run_aws",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("AWS forbidden")),
    )
    monkeypatch.setattr(
        backup,
        "_aws_cli_identity",
        lambda: (_ for _ in ()).throw(AssertionError("AWS identity forbidden")),
    )
    assert backup.verify_historical_receipt() == receipt


@pytest.mark.parametrize(
    "producer",
    [
        b"BOUND_CODE_PATHS = [\n",
        b"BOUND_CODE_PATHS = tuple(['bound.txt'])\n",
        b'BOUND_CODE_PATHS = ("bound.txt", "bound.txt")\n',
        b'BOUND_CODE_PATHS = ("../bound.txt",)\n',
        (f'BOUND_CODE_PATHS = ("bound.txt", "{HISTORICAL_PRODUCER}", "other.txt")\n').encode(),
    ],
)
def test_historical_receipt_rejects_producer_roster_drift(
    tmp_path, monkeypatch, producer: bytes
) -> None:
    context = _configure(tmp_path, monkeypatch)
    _mock_aws(context, monkeypatch)
    backup.transfer()
    context["historical_blobs"][HISTORICAL_PRODUCER] = producer

    with pytest.raises(backup.BackupContractError):
        backup.verify_historical_receipt()


def test_historical_receipt_rejects_historical_bound_blob_hash_mismatch(
    tmp_path, monkeypatch
) -> None:
    context = _configure(tmp_path, monkeypatch)
    _mock_aws(context, monkeypatch)
    backup.transfer()
    context["historical_blobs"]["bound.txt"] = b"tampered historical bytes\n"

    with pytest.raises(backup.BackupContractError):
        backup.verify_historical_receipt()


def test_atomic_evidence_write_never_clobbers_existing_receipt(tmp_path) -> None:
    target = tmp_path / "receipt.json"
    target.write_text("original\n", encoding="utf-8")

    with pytest.raises(backup.BackupContractError, match="refusing to overwrite"):
        backup._atomic_json(target, {"replacement": True})

    assert target.read_text(encoding="utf-8") == "original\n"
