"""Isolated local authority for the repository's integration-test gate.

The source Metis checkout is an object provider only.  Tests execute against a
temporary clean repository at the historical oracle pin, so concurrent work in
the source checkout cannot weaken or spuriously fail the clean-HEAD contract.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from metis_model1 import brain_toolchain_pin, grammar_stdlib_oracle, oracles
from metis_model1 import catalog_maintenance_pin as catalog_pin

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestHarnessError(RuntimeError):
    """Raised when the isolated test authority cannot be trusted."""


def _git_text(root: Path, *args: str) -> str:
    value = catalog_pin._run_git(root, *args)
    if not isinstance(value, str):
        raise TestHarnessError("Git returned a non-text identity")
    return value


def _common_objects_directory(root: Path) -> Path:
    raw = _git_text(root, "rev-parse", "--git-common-dir")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    objects = (candidate.resolve(strict=True) / "objects").resolve(strict=True)
    if not objects.is_dir():
        raise TestHarnessError("Metis Git object authority is unavailable")
    return objects


def _write_alternate(path: Path, objects: Path) -> None:
    if "\n" in str(objects) or "\r" in str(objects):
        raise TestHarnessError("Metis Git object authority path is invalid")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        raw = (str(objects) + "\n").encode("utf-8")
        if os.write(descriptor, raw) != len(raw):
            raise TestHarnessError("cannot bind isolated Git objects")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular_file(path: Path, *, expected_mode: int, label: str) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        raw = os.read(descriptor, 4097)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except OSError as error:
        raise TestHarnessError(f"{label} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda value: (  # noqa: E731 - compact immutable stat identity
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != expected_mode
        or before.st_nlink != 1
        or before.st_size > 4096
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(path_after)
        or len(raw) != before.st_size
    ):
        raise TestHarnessError(f"{label} is not a stable private file")
    return raw


def _isolated_authority_identity(
    root: Path,
    *,
    revision: str,
    tree: str,
    modules_sha256: str,
    objects: Path,
) -> tuple[str, str, str, str, str]:
    expected_alternate = (str(objects) + "\n").encode("utf-8")
    observed_alternate = _read_regular_file(
        root / ".git/objects/info/alternates",
        expected_mode=0o600,
        label="isolated Git alternate",
    )
    if observed_alternate != expected_alternate:
        raise TestHarnessError("isolated Metis authority changed during tests")
    observed_revision = _git_text(root, "rev-parse", "HEAD")
    observed_tree = _git_text(root, "rev-parse", "HEAD^{tree}")
    observed_branch = _git_text(root, "rev-parse", "--abbrev-ref", "HEAD")
    observed_status = _git_text(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude)tooling/node_modules",
    )
    isolated_root = root.resolve(strict=True)
    modules = (root / "tooling/node_modules").resolve(strict=True)
    if not modules.is_relative_to(isolated_root):
        raise TestHarnessError("isolated tooling runtime escapes its authority")
    oracles._validate_tree_symlinks(modules, "isolated tooling runtime")
    observed_modules = catalog_pin._node_modules_sha256(modules)
    if (
        observed_revision != revision
        or observed_tree != tree
        or observed_branch != "HEAD"
        or observed_status
        or observed_modules != modules_sha256
    ):
        raise TestHarnessError("isolated Metis authority changed during tests")
    return (
        observed_revision,
        observed_tree,
        observed_branch,
        observed_modules,
        observed_alternate.decode("utf-8"),
    )


def _authority_identity(
    root: Path,
    *,
    revision: str,
    tree: str,
    modules_sha256: str,
) -> tuple[str, str, str]:
    observed_revision = _git_text(root, "rev-parse", revision)
    observed_tree = _git_text(root, "rev-parse", f"{revision}^{{tree}}")
    modules = (root / "tooling/node_modules").resolve(strict=True)
    observed_modules = catalog_pin._node_modules_sha256(modules)
    if observed_revision != revision or observed_tree != tree or observed_modules != modules_sha256:
        raise TestHarnessError("source Git/runtime authority differs from the test pin")
    return observed_revision, observed_tree, observed_modules


def _source_worktree_fingerprint(root: Path) -> str:
    """Hash names and metadata only; never read source-worktree file payloads."""

    authority = root.resolve(strict=True)
    digest = hashlib.sha256()
    pending = [authority]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name)
        except OSError as error:
            raise TestHarnessError("source worktree roster is unavailable") from error
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(authority)
            if relative.parts[:1] == (".git",) or relative.parts[:2] == (
                "tooling",
                "node_modules",
            ):
                continue
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise TestHarnessError(
                    "source worktree roster changed during inspection"
                ) from error
            digest.update(relative.as_posix().encode("utf-8") + b"\0")
            digest.update(
                ":".join(
                    str(value)
                    for value in (
                        metadata.st_dev,
                        metadata.st_ino,
                        metadata.st_mode,
                        metadata.st_nlink,
                        metadata.st_size,
                        metadata.st_mtime_ns,
                        metadata.st_ctime_ns,
                    )
                ).encode("ascii")
                + b"\0"
            )
            if entry.is_symlink():
                try:
                    digest.update(os.readlink(path).encode("utf-8") + b"\0")
                except OSError as error:
                    raise TestHarnessError(
                        "source worktree roster changed during inspection"
                    ) from error
            elif entry.is_dir(follow_symlinks=False):
                pending.append(path)
    return digest.hexdigest()


@contextmanager
def isolated_metis_test_authority(
    source_root: Path,
    *,
    revision: str = oracles.PINNED_METIS_REVISION,
    tree: str = oracles.PINNED_METIS_TREE,
    modules_sha256: str = oracles.PINNED_NODE_MODULES_SHA256,
) -> Iterator[Path]:
    """Materialize a clean detached authority without writing the source repo."""

    try:
        root = Path(source_root).resolve(strict=True)
        if not root.is_dir():
            raise TestHarnessError("Metis source authority is not a directory")
        before = _authority_identity(
            root,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
        )
        worktree_before = _source_worktree_fingerprint(root)
        archive = catalog_pin._run_git(
            root,
            "archive",
            "--format=tar",
            revision,
            text=False,
        )
        if not isinstance(archive, bytes):
            raise TestHarnessError("pinned Git archive is unavailable")
        objects = _common_objects_directory(root)
        source_modules = (root / "tooling/node_modules").resolve(strict=True)

        try:
            with tempfile.TemporaryDirectory(prefix="metis-model1-test-authority-") as temporary:
                isolated = Path(temporary) / "metis"
                isolated.mkdir(mode=0o700)
                catalog_pin._safe_extract_archive(archive, isolated)
                if catalog_pin._node_modules_sha256(source_modules) != modules_sha256:
                    raise TestHarnessError("tooling runtime changed before copy")
                copied_modules = isolated / "tooling/node_modules"
                if copied_modules.exists() or copied_modules.is_symlink():
                    raise TestHarnessError("pinned Git archive unexpectedly contains node_modules")
                shutil.copytree(source_modules, copied_modules, symlinks=True)
                if (
                    catalog_pin._node_modules_sha256(copied_modules) != modules_sha256
                    or catalog_pin._node_modules_sha256(source_modules) != modules_sha256
                ):
                    raise TestHarnessError("copied tooling runtime differs from the pin")

                _git_text(isolated, "init", "--quiet")
                _write_alternate(isolated / ".git/objects/info/alternates", objects)
                _git_text(isolated, "update-ref", "--no-deref", "HEAD", revision)
                _git_text(isolated, "read-tree", revision)
                isolated_before = _isolated_authority_identity(
                    isolated,
                    revision=revision,
                    tree=tree,
                    modules_sha256=modules_sha256,
                    objects=objects,
                )
                try:
                    yield isolated
                finally:
                    isolated_after = _isolated_authority_identity(
                        isolated,
                        revision=revision,
                        tree=tree,
                        modules_sha256=modules_sha256,
                        objects=objects,
                    )
                    if isolated_after != isolated_before:
                        raise TestHarnessError("isolated Metis authority changed during tests")
        finally:
            try:
                after = _authority_identity(
                    root,
                    revision=revision,
                    tree=tree,
                    modules_sha256=modules_sha256,
                )
            except TestHarnessError as error:
                raise TestHarnessError(
                    "source Git/runtime authority changed during tests"
                ) from error
            if after != before:
                raise TestHarnessError("source Git/runtime authority changed during tests")
            if _source_worktree_fingerprint(root) != worktree_before:
                raise TestHarnessError("source worktree changed during tests")
    except (catalog_pin.CatalogMaintenancePinError, OSError, shutil.Error) as error:
        raise TestHarnessError("cannot construct isolated Metis test authority") from error


def _pytest_environment(*, isolated: Path, node: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for key in tuple(environment):
        if (
            key.startswith("GIT_")
            or key.startswith("PYTEST_")
            or key.startswith("METIS_MODEL1_")
            or key
            in {
                "NODE_OPTIONS",
                "PYTHONHOME",
                "PYTHONPATH",
                "PYTHONSTARTUP",
                "PYTHONUSERBASE",
            }
        ):
            environment.pop(key, None)
    environment.update(
        {
            oracles.NODE_RUNTIME_ENV: str(node),
            "METIS_MODEL1_METIS_ROOT": str(isolated),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    return environment


def _node_stat_identity(node: Path) -> tuple[int, int, int, int, int, int, int]:
    metadata = node.lstat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def run_tests(*, metis_root: Path, node_path: Path, pytest_args: Sequence[str]) -> int:
    node, digest = oracles._validate_node_binary(node_path)
    node_identity = _node_stat_identity(node)
    source_root = Path(metis_root).resolve(strict=True)
    try:
        brain_receipt = brain_toolchain_pin.verify_metis_brain_toolchain_pin(
            source_root,
            node,
            execute_probes=True,
        )
        if (
            brain_receipt.get("evidence_in") != 29
            or brain_receipt.get("evidence_out") != 29
            or brain_receipt.get("evidence_distinct") != 29
            or brain_receipt.get("evidence_gaps") != 0
            or brain_receipt.get("probes_in") != 9
            or brain_receipt.get("probes_out") != 9
            or brain_receipt.get("probes_distinct") != 9
            or brain_receipt.get("probes_gaps") != 0
            or brain_receipt.get("probes_executed") is not True
        ):
            raise TestHarnessError("Metis Brain lossless authority is incomplete")
        with isolated_metis_test_authority(source_root) as isolated:
            oracles.validate_pinned_metis(isolated)
            grammar_stdlib_oracle.validate_grammar_stdlib_pin(metis_root=isolated)
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", *pytest_args],
                cwd=PROJECT_ROOT,
                env=_pytest_environment(isolated=isolated, node=node),
                check=False,
            )
            return completed.returncode
    finally:
        try:
            node_after, digest_after = oracles._validate_node_binary(node)
        except (OSError, oracles.OracleError) as error:
            raise TestHarnessError("Node authority changed during tests") from error
        if (
            node_after != node
            or digest_after != digest
            or _node_stat_identity(node_after) != node_identity
        ):
            raise TestHarnessError("Node authority changed during tests")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run tests against a clean pinned Metis authority")
    parser.add_argument("--metis-root", required=True, type=Path)
    parser.add_argument("--node", required=True, type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    pytest_args = list(arguments.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    try:
        return run_tests(
            metis_root=arguments.metis_root,
            node_path=arguments.node,
            pytest_args=pytest_args,
        )
    except (
        TestHarnessError,
        brain_toolchain_pin.BrainToolchainPinError,
        oracles.OracleError,
        grammar_stdlib_oracle.GrammarStdlibOracleError,
    ):
        print("test authority validation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
