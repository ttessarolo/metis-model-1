from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

import metis_model1.video_private_artifacts as boundary
import metis_model1.video_private_io as private_io
from metis_model1.video_private_io import (
    MAX_PRIVATE_FILE_BYTES,
    VideoPrivateIOError,
    prepare_private_store,
    read_private_bytes,
    read_private_json,
    write_private_bytes_atomic,
    write_private_json_atomic,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("/artifacts/\n", encoding="utf-8")
    _git(root, "init", "-q")
    monkeypatch.setattr(private_io, "PROJECT_ROOT", root)
    monkeypatch.setattr(boundary, "PROJECT_ROOT", root)
    prepare_private_store()
    return root


def _private(root: Path) -> Path:
    return root / "artifacts" / "video-catalog-semantics-v1"


def test_prepare_and_atomic_bytes_round_trip(isolated_store: Path) -> None:
    prepare_private_store()
    write_private_bytes_atomic("receipts/input.bin", b"private\x00payload")
    assert read_private_bytes("receipts/input.bin", 64) == b"private\x00payload"
    target = _private(isolated_store) / "receipts" / "input.bin"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.stat().st_nlink == 1
    assert not any(target.parent.glob(".tmp-video-semantics-*"))


def test_json_is_canonical_finite_and_duplicate_free(isolated_store: Path) -> None:
    value = {"z": ["è", 2], "a": {"nested": True}}
    write_private_json_atomic("receipts/one.json", value)
    write_private_json_atomic("receipts/two.json", value)
    first = (_private(isolated_store) / "receipts" / "one.json").read_bytes()
    second = (_private(isolated_store) / "receipts" / "two.json").read_bytes()
    assert first == second == b'{"a":{"nested":true},"z":["\xc3\xa8",2]}'
    assert read_private_json("receipts/one.json", MAX_PRIVATE_FILE_BYTES) == value


@pytest.mark.parametrize(
    "relative_path",
    ["", ".", "..", "a/../b", "/tmp/out", "a//b", "a/./b", "a\\b", "a/"],
)
def test_path_traversal_and_non_relative_paths_fail_closed(
    isolated_store: Path, relative_path: str
) -> None:
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic(relative_path, b"nope")
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes(relative_path, 16)


def test_symlink_directory_is_rejected_without_touching_target(
    isolated_store: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (_private(isolated_store) / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("linked/payload", b"no")
    assert list(outside.iterdir()) == []


def test_symlink_file_and_preexisting_target_are_never_overwritten(
    isolated_store: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    target = _private(isolated_store) / "linked.bin"
    target.symlink_to(outside)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("linked.bin", b"new")
    assert outside.read_bytes() == b"outside"

    write_private_bytes_atomic("fixed.bin", b"original")
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("fixed.bin", b"replacement")
    assert read_private_bytes("fixed.bin", 64) == b"original"


def test_hard_link_is_rejected_on_read(isolated_store: Path, tmp_path: Path) -> None:
    target = _private(isolated_store) / "linked.bin"
    target.write_bytes(b"linked")
    target.chmod(0o600)
    outside = tmp_path / "hardlink.bin"
    os.link(target, outside)
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("linked.bin", 64)


def test_read_rejects_directory_entry_replacement_during_read(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_private_bytes_atomic("replace.bin", b"original")
    target = _private(isolated_store) / "replace.bin"
    replacement = _private(isolated_store) / "replacement.bin"
    replacement.write_bytes(b"replacement")
    replacement.chmod(0o600)
    original_read = private_io.os.read
    replaced = False

    def replace_after_first_read(fd: int, size: int) -> bytes:
        nonlocal replaced
        result = original_read(fd, size)
        if not replaced and stat.S_ISREG(os.fstat(fd).st_mode):
            os.replace(replacement, target)
            replaced = True
        return result

    monkeypatch.setattr(private_io.os, "read", replace_after_first_read)
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("replace.bin", 64)
    assert target.read_bytes() == b"replacement"


def test_read_rejects_same_size_mutation_during_read(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_private_bytes_atomic("mutate.bin", b"original")
    target = _private(isolated_store) / "mutate.bin"
    original_read = private_io.os.read
    mutated = False

    def mutate_after_first_read(fd: int, size: int) -> bytes:
        nonlocal mutated
        result = original_read(fd, size)
        if not mutated and stat.S_ISREG(os.fstat(fd).st_mode):
            target.write_bytes(b"changed!")
            target.chmod(0o600)
            mutated = True
        return result

    monkeypatch.setattr(private_io.os, "read", mutate_after_first_read)
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("mutate.bin", 64)


def test_wrong_mode_and_oversize_are_rejected(isolated_store: Path) -> None:
    write_private_bytes_atomic("mode.bin", b"data")
    target = _private(isolated_store) / "mode.bin"
    target.chmod(0o644)
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("mode.bin", 64)

    write_private_bytes_atomic("large.bin", b"0123456789")
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("large.bin", 9)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("too-large.bin", b"x" * (MAX_PRIVATE_FILE_BYTES + 1))


def test_wrong_owner_is_rejected_when_uid_probe_is_mocked(
    isolated_store: Path, monkeypatch
) -> None:
    write_private_bytes_atomic("owner.bin", b"data")
    monkeypatch.setattr(private_io, "_current_uid", lambda: os.getuid() + 1)
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("owner.bin", 64)


def test_nonignored_and_tracked_targets_fail_before_write(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_ignored = private_io._git_ignored
    monkeypatch.setattr(private_io, "_git_ignored", lambda *args: False)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("public.bin", b"no")
    assert not (_private(isolated_store) / "public.bin").exists()

    monkeypatch.setattr(private_io, "_git_ignored", original_ignored)
    target = _private(isolated_store) / "tracked.bin"
    target.write_bytes(b"tracked")
    target.chmod(0o600)
    _git(isolated_store, "add", "-f", str(target.relative_to(isolated_store)))
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("tracked.bin", b"no")
    assert target.read_bytes() == b"tracked"


def test_status_drift_fails_and_removes_temporary_file(isolated_store: Path, monkeypatch) -> None:
    original = private_io._git_status
    calls = 0

    def drifting_status(root: Path, git) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "unrelated-drift").write_text("drift", encoding="utf-8")
        return original(root, git)

    monkeypatch.setattr(private_io, "_git_status", drifting_status)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("receipts/drift.bin", b"data")
    assert not (_private(isolated_store) / "receipts" / "drift.bin").exists()
    assert not any(_private(isolated_store).rglob(".tmp-video-semantics-*"))


def test_link_publish_failure_cleans_temporary_file(isolated_store: Path, monkeypatch) -> None:
    def fail_link(*args, **kwargs):
        raise OSError("synthetic link failure")

    monkeypatch.setattr(private_io.os, "link", fail_link)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("receipts/failure.bin", b"data")
    assert not any(_private(isolated_store).rglob(".tmp-video-semantics-*"))


def test_directory_relocation_after_publish_is_detected_and_cleaned(
    isolated_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    moved_parent = tmp_path / "relocated"
    moved_parent.mkdir()
    original_publish = private_io._publish_no_replace

    def publish_then_relocate(parent, temp_name, target_name, expected):
        result = original_publish(parent, temp_name, target_name, expected)
        source_directory = _private(isolated_store) / "receipts"
        os.rename(source_directory, moved_parent / "receipts")
        return result

    monkeypatch.setattr(private_io, "_publish_no_replace", publish_then_relocate)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("receipts/relocated.bin", b"private-data")
    assert not (_private(isolated_store) / "receipts" / "relocated.bin").exists()
    assert not (moved_parent / "receipts" / "relocated.bin").exists()
    assert not any((moved_parent / "receipts").glob(".tmp-video-semantics-*"))


def test_temp_name_swap_cannot_leave_readable_poison(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_link = private_io.os.link
    swapped = False

    def swap_then_link(src, dst, *, src_dir_fd, dst_dir_fd, follow_symlinks):
        nonlocal swapped
        if not swapped and str(src).startswith(".tmp-video-semantics-"):
            swapped = True
            os.unlink(src, dir_fd=src_dir_fd)
            poison = os.open(
                src,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=src_dir_fd,
            )
            try:
                os.write(poison, b"poison")
                os.fsync(poison)
            finally:
                os.close(poison)
        return original_link(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(private_io.os, "link", swap_then_link)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("poison.bin", b"private-data")
    assert swapped is True
    assert not (_private(isolated_store) / "poison.bin").exists()
    assert not any(_private(isolated_store).glob(".tmp-video-semantics-*"))
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("poison.bin", 64)


def test_target_swap_after_publish_is_detected_and_cleaned(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_publish = private_io._publish_no_replace

    def publish_then_swap(parent, temp_name, target_name, expected):
        result = original_publish(parent, temp_name, target_name, expected)
        os.unlink(target_name, dir_fd=parent)
        poison = os.open(
            target_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent,
        )
        try:
            os.write(poison, b"poison")
            os.fsync(poison)
        finally:
            os.close(poison)
        return result

    monkeypatch.setattr(private_io, "_publish_no_replace", publish_then_swap)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("post-publish-poison.bin", b"private-data")
    assert not (_private(isolated_store) / "post-publish-poison.bin").exists()
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("post-publish-poison.bin", 64)


def test_same_inode_mutation_after_publish_is_detected_and_cleaned(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_publish = private_io._publish_no_replace

    def publish_then_mutate(parent, temp_name, target_name, expected):
        result = original_publish(parent, temp_name, target_name, expected)
        target = os.open(target_name, os.O_WRONLY, dir_fd=parent)
        try:
            os.write(target, b"BBBB")
            os.fsync(target)
        finally:
            os.close(target)
        return result

    monkeypatch.setattr(private_io, "_publish_no_replace", publish_then_mutate)
    with pytest.raises(VideoPrivateIOError):
        write_private_bytes_atomic("post-publish-mutation.bin", b"AAAA")
    assert not (_private(isolated_store) / "post-publish-mutation.bin").exists()
    with pytest.raises(VideoPrivateIOError):
        read_private_bytes("post-publish-mutation.bin", 64)


def test_malformed_json_and_nonfinite_json_fail_closed(isolated_store: Path) -> None:
    write_private_bytes_atomic("bad.json", b'{"a": 1, "a": 2}')
    with pytest.raises(VideoPrivateIOError):
        read_private_json("bad.json", 64)
    write_private_bytes_atomic("nan.json", b'{"a": NaN}')
    with pytest.raises(VideoPrivateIOError):
        read_private_json("nan.json", 64)


def test_json_recursion_is_redacted_as_a_private_io_error(isolated_store: Path) -> None:
    nested: list[object] = []
    for _ in range(10_000):
        nested = [nested]
    with pytest.raises(VideoPrivateIOError):
        write_private_json_atomic("deep.json", nested)

    write_private_bytes_atomic("deep-read.json", b"[" * 10_000 + b"]" * 10_000)
    with pytest.raises(VideoPrivateIOError):
        read_private_json("deep-read.json", MAX_PRIVATE_FILE_BYTES)


def test_public_errors_do_not_contain_path_or_content(isolated_store: Path) -> None:
    with pytest.raises(VideoPrivateIOError) as error:
        write_private_bytes_atomic("../../secret", b"SENSITIVE-CONTENT")
    rendered = str(error.value)
    assert "secret" not in rendered
    assert "SENSITIVE-CONTENT" not in rendered
    assert "/Users/" not in rendered


def test_write_preserves_git_status(isolated_store: Path) -> None:
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=isolated_store,
        check=True,
        capture_output=True,
    ).stdout
    write_private_json_atomic("receipts/status.json", {"ok": True})
    after = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=isolated_store,
        check=True,
        capture_output=True,
    ).stdout
    assert before == after
