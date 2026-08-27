from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import metis_model1.video_source_acquisition as acquisition
from metis_model1.video_semantics_contracts import (
    validate_acquisition_receipt,
    validate_source_manifest,
)
from metis_model1.video_source_acquisition import (
    MAX_FILE_BYTES,
    MAX_FILES,
    VideoSourceAcquisitionError,
    acquire_video_source_roster,
    private_bundle_document,
    public_failure,
    validate_private_bundle_document,
)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "reserved-root"
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir()
    return root


def _error(root: Path, code: str) -> None:
    with pytest.raises(VideoSourceAcquisitionError) as raised:
        acquire_video_source_roster(root, run_id="run-fixed-0001")
    assert raised.value.code == code
    assert str(raised.value) == code


def test_manifest_registry_are_deterministic_and_separate(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "zeta.txt").write_bytes(b"z")
    (root / "nested").mkdir()
    (root / "nested" / "alpha.md").write_bytes(b"alpha")
    (root / ".DS_Store").write_bytes(b"metadata")

    first = acquire_video_source_roster(root, run_id="run-fixed-0001")
    second = acquire_video_source_roster(root, run_id="run-fixed-0001")

    assert first.manifest == second.manifest
    assert first.locator_registry == second.locator_registry
    assert first.public_result == second.public_result
    assert [item["source_ref"] for item in first.manifest["sources"]] == [
        "source-ref-000001",
        "source-ref-000002",
    ]
    assert all(
        item["content_sha256"].startswith("sha256:")
        and len(item["content_sha256"]) == len("sha256:") + 64
        for item in first.manifest["sources"]
    )
    assert validate_source_manifest(first.manifest) == []
    assert first.receipt_roster["roster_id"] == "video-semantics/acquisition-receipts-v1"
    assert first.receipt_roster["manifest_sha256"] == first.locator_registry["manifest_sha256"]
    assert len(first.receipts) == 2
    assert all(
        validate_acquisition_receipt(receipt, first.manifest) == [] for receipt in first.receipts
    )
    assert [entry["locator"] for entry in first.locator_registry["entries"]] == [
        "nested/alpha.md",
        "zeta.txt",
    ]
    assert [entry["format"] for entry in first.locator_registry["entries"]] == ["md", "txt"]
    assert all(
        key not in source
        for source in first.manifest["sources"]
        for key in ("locator", "name", "format", "size_bytes", "relative_path")
    )

    (root / "zeta.txt").rename(root / "renamed.txt")
    renamed = acquire_video_source_roster(root, run_id="run-fixed-0001")
    assert renamed.manifest == first.manifest


def test_public_result_is_exactly_allowlisted_and_redacted(tmp_path: Path) -> None:
    root = _root(tmp_path)
    secret_name = "private-editorial-name.txt"
    (root / secret_name).write_text("sensitive editorial text", encoding="utf-8")
    bundle = acquire_video_source_roster(root, run_id="run-fixed-0001")
    assert set(bundle.public_result) == acquisition.PUBLIC_KEYS
    rendered = repr(bundle.public_result)
    assert secret_name not in rendered
    assert "sensitive editorial text" not in rendered
    assert str(root) not in rendered
    assert bundle.public_result == {
        "schema_version": 1,
        "operation": "acquire-video-source-roster",
        "status": "VALID",
        "private_roster_complete": True,
        "gaps": 0,
        "sensitivity": "internal_editorial",
        "raw_payloads_present": False,
        "error_codes": [],
    }

    failure = public_failure(VideoSourceAcquisitionError("ROOT_UNSAFE"))
    assert set(failure) == acquisition.PUBLIC_KEYS
    assert str(root) not in repr(failure)
    assert "ROOT_UNSAFE" in repr(failure)


def test_hidden_entries_are_excluded_and_empty_visible_root_fails(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / ".DS_Store").write_bytes(b"metadata")
    (root / ".localized").write_bytes(b"metadata")
    (root / "visible.txt").write_bytes(b"visible")
    bundle = acquire_video_source_roster(root, run_id="run-fixed-0001")
    assert len(bundle.receipts) == 1

    (root / ".hidden").write_bytes(b"hidden")
    _error(root, "HIDDEN_ENTRY")

    empty = _root(tmp_path / "empty")
    (empty / ".DS_Store").write_bytes(b"metadata")
    _error(empty, "EMPTY_ROOT")


@pytest.mark.parametrize(
    ("root_factory", "code"),
    [
        (lambda tmp: tmp / "relative", "ROOT_NOT_ABSOLUTE"),
        (lambda tmp: tmp / "missing", "ROOT_MISSING"),
        (lambda tmp: tmp / "file", "ROOT_NOT_DIRECTORY"),
    ],
)
def test_unsafe_roots_fail_closed(tmp_path: Path, root_factory, code: str) -> None:
    if code == "ROOT_NOT_DIRECTORY":
        (tmp_path / "file").write_bytes(b"file")
    root = root_factory(tmp_path)
    if code == "ROOT_NOT_ABSOLUTE":
        root = Path("relative")
    _error(root, code)


def test_symlink_root_and_entry_fail_closed(tmp_path: Path) -> None:
    real = _root(tmp_path)
    (real / "input.txt").write_bytes(b"input")
    link_root = tmp_path / "root-link"
    link_root.symlink_to(real, target_is_directory=True)
    _error(link_root, "ROOT_SYMLINK")

    (real / "linked.txt").symlink_to(real / "input.txt")
    _error(real, "SYMLINK_ENTRY")


def test_hardlink_is_rejected(tmp_path: Path) -> None:
    root = _root(tmp_path)
    original = root / "original.txt"
    original.write_bytes(b"original")
    os.link(original, root / "alias.txt")
    _error(root, "HARDLINK_ENTRY")


def test_device_and_other_nonregular_entries_are_rejected(tmp_path: Path) -> None:
    root = _root(tmp_path)
    fifo = root / "pipe"
    os.mkfifo(fifo)
    _error(root, "NONREGULAR_ENTRY")


def test_file_count_file_size_and_total_size_limits_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    (root / "one.txt").write_bytes(b"1234")
    (root / "two.txt").write_bytes(b"5")
    monkeypatch.setattr(acquisition, "MAX_FILES", 1)
    _error(root, "MAX_FILES_EXCEEDED")

    root = _root(tmp_path / "size")
    (root / "large.txt").write_bytes(b"1234")
    monkeypatch.setattr(acquisition, "MAX_FILES", MAX_FILES)
    monkeypatch.setattr(acquisition, "MAX_FILE_BYTES", 3)
    _error(root, "MAX_FILE_BYTES_EXCEEDED")

    root = _root(tmp_path / "total")
    (root / "one.txt").write_bytes(b"1234")
    (root / "two.txt").write_bytes(b"5")
    monkeypatch.setattr(acquisition, "MAX_FILE_BYTES", MAX_FILE_BYTES)
    monkeypatch.setattr(acquisition, "MAX_TOTAL_BYTES", 4)
    _error(root, "MAX_TOTAL_BYTES_EXCEEDED")


def test_inode_size_or_mtime_drift_during_hash_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    source = root / "drift.txt"
    source.write_bytes(b"stable")
    original_read = acquisition.os.read
    changed = False

    def read_and_drift(fd: int, size: int) -> bytes:
        nonlocal changed
        chunk = original_read(fd, size)
        if not changed and chunk:
            changed = True
            with source.open("r+b") as handle:
                handle.seek(0)
                handle.write(b"changed")
                handle.flush()
                os.fsync(handle.fileno())
        return chunk

    monkeypatch.setattr(acquisition.os, "read", read_and_drift)
    _error(root, "SOURCE_DRIFT")


def test_ancestor_relocation_and_replacement_during_hash_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ancestor = tmp_path / "capability-parent"
    root = _root(ancestor)
    (root / "stable.txt").write_bytes(b"stable")
    moved = tmp_path / "capability-parent-original"
    replacement = tmp_path / "capability-parent-replacement"
    original_hash = acquisition._hash_regular_file
    relocated = False

    def hash_and_relocate(parent_fd: int, name: str, expected: os.stat_result) -> str:
        nonlocal relocated
        digest = original_hash(parent_fd, name, expected)
        if not relocated:
            relocated = True
            ancestor.rename(moved)
            replacement_root = ancestor / root.name
            replacement_root.mkdir(parents=True)
            (replacement_root / "stable.txt").write_bytes(b"replacement")
            ancestor.rename(replacement)
        return digest

    monkeypatch.setattr(acquisition, "_hash_regular_file", hash_and_relocate)
    _error(root, "SOURCE_DRIFT")


def test_ancestor_sibling_creation_during_hash_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ancestor = tmp_path / "capability-parent"
    root = _root(ancestor)
    (root / "stable.txt").write_bytes(b"stable")
    sibling = tmp_path / "harmless-sibling"
    original_hash = acquisition._hash_regular_file
    created = False

    def hash_and_create_sibling(parent_fd: int, name: str, expected: os.stat_result) -> str:
        nonlocal created
        digest = original_hash(parent_fd, name, expected)
        if not created:
            created = True
            sibling.write_bytes(b"unrelated")
        return digest

    monkeypatch.setattr(acquisition, "_hash_regular_file", hash_and_create_sibling)
    bundle = acquire_video_source_roster(root, run_id="run-fixed-0001")

    assert bundle.public_result["status"] == "VALID"
    assert sibling.read_bytes() == b"unrelated"


def test_ancestor_sibling_creation_between_stat_and_open_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ancestor = tmp_path / "capability-parent"
    root = _root(ancestor)
    (root / "stable.txt").write_bytes(b"stable")
    sibling = ancestor / "harmless-sibling.txt"
    original_open = acquisition.os.open
    opened_ancestor = False

    def open_with_ancestor_noise(
        path: str | bytes, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal opened_ancestor
        if path == ancestor.name and not opened_ancestor:
            opened_ancestor = True
            sibling.write_bytes(b"unrelated")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(acquisition.os, "open", open_with_ancestor_noise)
    bundle = acquire_video_source_roster(root, run_id="run-fixed-0001")

    assert bundle.public_result["status"] == "VALID"
    assert opened_ancestor is True
    assert sibling.read_bytes() == b"unrelated"


@pytest.mark.parametrize("unsafe_kind", ["root", "subdirectory", "file"])
def test_group_or_world_writable_source_entries_fail_closed(
    tmp_path: Path, unsafe_kind: str
) -> None:
    root = _root(tmp_path)
    (root / "stable.txt").write_bytes(b"stable")
    if unsafe_kind == "root":
        os.chmod(root, 0o777)
    elif unsafe_kind == "subdirectory":
        nested = root / "nested"
        nested.mkdir()
        (nested / "stable.txt").write_bytes(b"stable")
        os.chmod(nested, 0o777)
    else:
        os.chmod(root / "stable.txt", 0o666)

    _error(root, "ROOT_UNSAFE")


def test_private_source_modes_are_accepted(tmp_path: Path) -> None:
    root = _root(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    source = nested / "stable.txt"
    source.write_bytes(b"stable")
    os.chmod(root, 0o755)
    os.chmod(nested, 0o755)
    os.chmod(source, 0o644)

    bundle = acquire_video_source_roster(root, run_id="run-fixed-0001")

    assert bundle.public_result["status"] == "VALID"


def test_invalid_run_id_fails_without_reading_source(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "input.txt").write_bytes(b"input")
    with pytest.raises(VideoSourceAcquisitionError) as raised:
        acquire_video_source_roster(root, run_id="bad id")
    assert raised.value.code == "INVALID_RUN_ID"


def test_directory_depth_and_count_limits_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path / "depth")
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "input.txt").write_bytes(b"input")
    monkeypatch.setattr(acquisition, "MAX_DEPTH", 1)
    _error(root, "MAX_DEPTH_EXCEEDED")

    root = _root(tmp_path / "directories")
    (root / "nested").mkdir()
    (root / "nested" / "input.txt").write_bytes(b"input")
    monkeypatch.setattr(acquisition, "MAX_DEPTH", acquisition.MAX_DEPTH)
    monkeypatch.setattr(acquisition, "MAX_DIRECTORIES", 1)
    _error(root, "MAX_DIRECTORIES_EXCEEDED")


def test_wrong_owner_is_rejected_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    (root / "input.txt").write_bytes(b"input")
    monkeypatch.setattr(acquisition, "_current_uid", lambda: os.getuid() + 1)
    _error(root, "ROOT_WRONG_OWNER")


def test_private_bundle_envelope_round_trip_and_tamper_rejection(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "source.txt").write_text("synthetic source", encoding="utf-8")
    bundle = acquire_video_source_roster(root, run_id="run-fixed-0001")
    document = private_bundle_document(bundle)
    assert set(document) == {
        "schema_version",
        "artifact_kind",
        "manifest",
        "receipt_roster",
        "locator_registry",
        "bundle_sha256",
    }
    assert validate_private_bundle_document(document) is True

    tampered_hash = dict(document, bundle_sha256="sha256:" + "0" * 64)
    with pytest.raises(VideoSourceAcquisitionError) as raised:
        validate_private_bundle_document(tampered_hash)
    assert raised.value.code == "BUNDLE_INVALID"

    tampered_registry = dict(document)
    registry = dict(document["locator_registry"])
    entries = [dict(entry) for entry in registry["entries"]]
    entries[0]["name"] = "different.txt"
    registry["entries"] = entries
    tampered_registry["locator_registry"] = registry
    body = {key: tampered_registry[key] for key in tampered_registry if key != "bundle_sha256"}
    tampered_registry["bundle_sha256"] = acquisition.manifest_digest(body)
    with pytest.raises(VideoSourceAcquisitionError) as raised:
        validate_private_bundle_document(tampered_registry)
    assert raised.value.code == "BUNDLE_INVALID"

    tampered_format = json.loads(json.dumps(document))
    tampered_format["locator_registry"]["entries"][0]["format"] = "pdf"
    body = {key: tampered_format[key] for key in tampered_format if key != "bundle_sha256"}
    tampered_format["bundle_sha256"] = acquisition.manifest_digest(body)
    with pytest.raises(VideoSourceAcquisitionError) as raised:
        validate_private_bundle_document(tampered_format)
    assert raised.value.code == "BUNDLE_INVALID"

    for location in ("bundle", "receipt_roster", "locator_registry"):
        tampered_type = json.loads(json.dumps(document))
        target = tampered_type if location == "bundle" else tampered_type[location]
        target["schema_version"] = True
        body = {key: tampered_type[key] for key in tampered_type if key != "bundle_sha256"}
        tampered_type["bundle_sha256"] = acquisition.manifest_digest(body)
        with pytest.raises(VideoSourceAcquisitionError) as raised:
            validate_private_bundle_document(tampered_type)
        assert raised.value.code == "BUNDLE_INVALID"

    assert private_bundle_document(bundle) == document


@pytest.mark.parametrize(
    "name",
    [
        "archive.bin",
        "credentials",
        "credentials.pdf",
        "credentials_backup.txt",
        "aws_credentials.txt",
        "id_rsa_backup.txt",
        "secret-notes.md",
        "secret.txt",
        "identity.pem",
    ],
)
def test_unsupported_or_sensitive_source_names_fail_before_hashing(
    tmp_path: Path, name: str
) -> None:
    root = _root(tmp_path)
    (root / name).write_bytes(b"synthetic")
    expected = "SENSITIVE_NAME_FORBIDDEN" if name != "archive.bin" else "FORMAT_UNSUPPORTED"
    _error(root, expected)


def test_private_bundle_validator_reenforces_roster_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    (root / "one.txt").write_bytes(b"one")
    (root / "two.txt").write_bytes(b"two")
    document = private_bundle_document(acquire_video_source_roster(root, run_id="run-fixed-0001"))
    monkeypatch.setattr(acquisition, "MAX_FILES", 1)
    with pytest.raises(VideoSourceAcquisitionError) as raised:
        validate_private_bundle_document(document)
    assert raised.value.code == "BUNDLE_INVALID"
