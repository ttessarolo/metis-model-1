from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from metis_model1 import catalog_maintenance_pin as catalog_pin
from metis_model1 import test_harness


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )
    return completed.stdout.strip()


def _source_authority(tmp_path: Path) -> tuple[Path, str, str, str]:
    source = tmp_path / "source-metis"
    modules = source / "tooling/node_modules/pkg"
    modules.mkdir(parents=True)
    (source / ".gitignore").write_text("tooling/node_modules/\n", encoding="utf-8")
    (source / "tooling/package.json").write_text("{}\n", encoding="utf-8")
    (source / "tooling/package-lock.json").write_text("{}\n", encoding="utf-8")
    (modules / "index.js").write_text("export default 1;\n", encoding="utf-8")
    _git(source, "init", "--quiet")
    _git(source, "config", "user.name", "Metis Model 1 test")
    _git(source, "config", "user.email", "metis-model1-test@invalid")
    _git(source, "add", ".gitignore", "tooling/package.json", "tooling/package-lock.json")
    _git(source, "commit", "--quiet", "-m", "fixture")
    revision = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    modules_sha256 = catalog_pin._node_modules_sha256(source / "tooling/node_modules")
    return source, revision, tree, modules_sha256


def test_isolated_authority_is_exact_clean_and_does_not_mutate_source(tmp_path: Path) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)
    source_head = _git(source, "rev-parse", "HEAD")
    source_status = _git(source, "status", "--porcelain=v1", "--untracked-files=all")

    with test_harness.isolated_metis_test_authority(
        source,
        revision=revision,
        tree=tree,
        modules_sha256=modules_sha256,
    ) as isolated:
        assert isolated != source
        assert _git(isolated, "rev-parse", "HEAD") == revision
        assert _git(isolated, "rev-parse", "HEAD^{tree}") == tree
        assert _git(isolated, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
        assert _git(isolated, "status", "--porcelain=v1", "--untracked-files=all") == ""
        assert (isolated / "tooling/node_modules/pkg/index.js").read_text(
            encoding="utf-8"
        ) == "export default 1;\n"
        alternate = isolated / ".git/objects/info/alternates"
        assert alternate.read_text(encoding="utf-8").strip() == str(
            (source / ".git/objects").resolve()
        )

    assert _git(source, "rev-parse", "HEAD") == source_head
    assert _git(source, "status", "--porcelain=v1", "--untracked-files=all") == source_status


@pytest.mark.parametrize("attack", ["tracked", "head", "modules", "alternate"])
def test_isolated_authority_detects_temporary_authority_mutation(
    tmp_path: Path,
    attack: str,
) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)
    retained: Path | None = None

    with (
        pytest.raises(test_harness.TestHarnessError),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
        ) as isolated,
    ):
        retained = isolated
        if attack == "tracked":
            (isolated / "tooling/package.json").write_text("mutated\n", encoding="utf-8")
        elif attack == "head":
            _git(isolated, "symbolic-ref", "HEAD", "refs/heads/forged")
        elif attack == "modules":
            (isolated / "tooling/node_modules/pkg/index.js").write_text(
                "export default 2;\n",
                encoding="utf-8",
            )
        else:
            (isolated / ".git/objects/info/alternates").write_text(
                "/forged/objects\n",
                encoding="utf-8",
            )

    assert retained is not None
    assert not retained.exists()


def test_isolated_authority_detects_source_runtime_change_during_use(tmp_path: Path) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)

    with (
        pytest.raises(test_harness.TestHarnessError, match="changed during tests"),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
        ),
    ):
        (source / "tooling/node_modules/pkg/index.js").write_text(
            "export default 2;\n",
            encoding="utf-8",
        )


def test_isolated_authority_cleans_up_after_body_exception(tmp_path: Path) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)
    retained: Path | None = None

    with (
        pytest.raises(RuntimeError, match="body failure"),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
        ) as isolated,
    ):
        retained = isolated
        raise RuntimeError("body failure")

    assert retained is not None
    assert not retained.exists()


def test_pytest_environment_removes_external_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "/forged/git")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--pdb")
    monkeypatch.setenv("PYTHONPATH", "/forged/python")
    monkeypatch.setenv("METIS_MODEL1_METIS_ROOT", "/forged/metis")
    isolated = tmp_path / "isolated"
    node = tmp_path / "runtime/bin/node"

    environment = test_harness._pytest_environment(isolated=isolated, node=node)

    assert "GIT_DIR" not in environment
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTHONPATH" not in environment
    assert environment["METIS_MODEL1_METIS_ROOT"] == str(isolated)
    assert environment["METIS_MODEL1_NODE"] == str(node)
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_source_worktree_fingerprint_detects_dirty_file_change(tmp_path: Path) -> None:
    source, _revision, _tree, _modules_sha256 = _source_authority(tmp_path)
    tracked = source / "tooling/package.json"
    tracked.write_text("dirty-before\n", encoding="utf-8")
    before = test_harness._source_worktree_fingerprint(source)

    tracked.write_text("dirty-after\n", encoding="utf-8")

    assert test_harness._source_worktree_fingerprint(source) != before


def test_main_redacts_authority_failure_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(**_kwargs: object) -> int:
        raise test_harness.TestHarnessError("private source path")

    monkeypatch.setattr(test_harness, "run_tests", fail)
    assert test_harness.main(["--metis-root", "/private/source", "--node", "/private/node"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "test authority validation failed\n"
