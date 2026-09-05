from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

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
    source_refs = _git(source, "for-each-ref", "--format=%(refname) %(objectname)")
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
        assert _git(isolated, "for-each-ref", "--format=%(refname) %(objectname)") == ""
        assert _git(isolated, "status", "--porcelain=v1", "--untracked-files=all") == ""
        assert (isolated / "tooling/node_modules/pkg/index.js").read_text(
            encoding="utf-8"
        ) == "export default 1;\n"
        alternate = isolated / ".git/objects/info/alternates"
        assert alternate.read_text(encoding="utf-8").strip() == str(
            (source / ".git/objects").resolve()
        )

    assert _git(source, "rev-parse", "HEAD") == source_head
    assert _git(source, "for-each-ref", "--format=%(refname) %(objectname)") == source_refs
    assert _git(source, "status", "--porcelain=v1", "--untracked-files=all") == source_status


def test_isolated_authority_materializes_the_verified_brain_remote_ref(tmp_path: Path) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)
    source_head = _git(source, "rev-parse", "HEAD")
    source_refs = _git(source, "for-each-ref", "--format=%(refname) %(objectname)")
    source_status = _git(source, "status", "--porcelain=v1", "--untracked-files=all")

    with test_harness.isolated_metis_test_authority(
        source,
        revision=revision,
        tree=tree,
        modules_sha256=modules_sha256,
        remote_ref_revision=revision,
    ) as isolated:
        assert _git(isolated, "rev-parse", "refs/remotes/origin/main") == revision
        _git(isolated, "merge-base", "--is-ancestor", revision, "refs/remotes/origin/main")

    assert _git(source, "rev-parse", "HEAD") == source_head
    assert _git(source, "for-each-ref", "--format=%(refname) %(objectname)") == source_refs
    assert _git(source, "status", "--porcelain=v1", "--untracked-files=all") == source_status


@pytest.mark.parametrize(
    "attack", ["tracked", "head", "modules", "alternate", "remote", "remote_missing"]
)
def test_isolated_authority_detects_temporary_authority_mutation(
    tmp_path: Path,
    attack: str,
) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)
    retained: Path | None = None
    remote_ref_revision = None
    if attack in {"remote", "remote_missing"}:
        (source / "remote-descendant.txt").write_text("remote descendant\n", encoding="utf-8")
        _git(source, "add", "remote-descendant.txt")
        _git(source, "commit", "--quiet", "-m", "remote descendant")
        remote_ref_revision = _git(source, "rev-parse", "HEAD")
    source_refs = _git(source, "for-each-ref", "--format=%(refname) %(objectname)")

    with (
        pytest.raises(test_harness.TestHarnessError),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
            remote_ref_revision=remote_ref_revision,
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
        elif attack == "alternate":
            (isolated / ".git/objects/info/alternates").write_text(
                "/forged/objects\n",
                encoding="utf-8",
            )
        else:
            if attack == "remote":
                _git(isolated, "update-ref", "refs/remotes/origin/main", revision)
            else:
                _git(isolated, "update-ref", "-d", "refs/remotes/origin/main")

    assert retained is not None
    assert not retained.exists()
    assert _git(source, "for-each-ref", "--format=%(refname) %(objectname)") == source_refs


@pytest.mark.parametrize("remote_ref_revision", ["not-an-oid", "0" * 40, 7])
def test_isolated_authority_rejects_invalid_or_missing_brain_remote_ref(
    tmp_path: Path, remote_ref_revision: object
) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)

    with (
        pytest.raises(test_harness.TestHarnessError),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
            remote_ref_revision=remote_ref_revision,
        ),
    ):
        pytest.fail("invalid Brain remote ref must fail before isolation")


def test_isolated_authority_rejects_brain_remote_ref_that_does_not_contain_the_pin(
    tmp_path: Path,
) -> None:
    source, old_revision, _old_tree, modules_sha256 = _source_authority(tmp_path)
    (source / "pin-descendant.txt").write_text("new pin\n", encoding="utf-8")
    _git(source, "add", "pin-descendant.txt")
    _git(source, "commit", "--quiet", "-m", "new pin")
    revision = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")

    with (
        pytest.raises(test_harness.TestHarnessError, match="does not contain its pin"),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
            remote_ref_revision=old_revision,
        ),
    ):
        pytest.fail("a Brain remote ref behind the pin must fail before isolation")


def test_authority_pair_rejects_a_brain_receipt_without_remote_ref(tmp_path: Path) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)

    with (
        pytest.raises(test_harness.TestHarnessError, match="authority identity is invalid"),
        test_harness._isolated_authority_pair(
            source_root=source,
            oracle_node_modules=None,
            brain_receipt={
                "identity": SimpleNamespace(node_modules_sha256=f"sha256:{modules_sha256}"),
                "revision": revision,
                "tree": tree,
            },
        ),
    ):
        pytest.fail("a Brain receipt without a remote ref must fail before isolation")


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


def test_isolated_authority_allows_clean_source_head_advance(tmp_path: Path) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)

    with test_harness.isolated_metis_test_authority(
        source,
        revision=revision,
        tree=tree,
        modules_sha256=modules_sha256,
    ) as isolated:
        (source / "tooling/package.json").write_text('{"new":true}\n', encoding="utf-8")
        _git(source, "add", "tooling/package.json")
        _git(source, "commit", "--quiet", "-m", "concurrent clean advance")
        assert _git(isolated, "rev-parse", "HEAD") == revision

    assert _git(source, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert _git(source, "rev-parse", "HEAD") != revision


def test_isolated_authority_rejects_dirty_source_change_during_use(tmp_path: Path) -> None:
    source, revision, tree, modules_sha256 = _source_authority(tmp_path)

    with (
        pytest.raises(test_harness.TestHarnessError, match="became dirty"),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=modules_sha256,
        ),
    ):
        (source / "tooling/package.json").write_text("dirty\n", encoding="utf-8")


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
    monkeypatch.setenv("METIS_MODEL1_BRAIN_METIS_ROOT", "/forged/brain-metis")
    isolated = tmp_path / "isolated"
    brain_isolated = tmp_path / "brain-isolated"
    node = tmp_path / "runtime/bin/node"

    environment = test_harness._pytest_environment(
        isolated=isolated,
        brain_isolated=brain_isolated,
        node=node,
    )

    assert "GIT_DIR" not in environment
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTHONPATH" not in environment
    assert environment["METIS_MODEL1_METIS_ROOT"] == str(isolated)
    assert environment["METIS_MODEL1_BRAIN_METIS_ROOT"] == str(brain_isolated)
    assert environment["METIS_MODEL1_NODE"] == str(node)
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_isolated_authority_can_use_a_separate_pinned_runtime(tmp_path: Path) -> None:
    source, revision, tree, _source_modules_sha256 = _source_authority(tmp_path)
    runtime_modules = tmp_path / "runtime/node_modules"
    runtime_package = runtime_modules / "pkg/index.js"
    runtime_package.parent.mkdir(parents=True)
    runtime_package.write_text("export default 'historical';\n", encoding="utf-8")
    runtime_sha256 = catalog_pin._node_modules_sha256(runtime_modules)

    with test_harness.isolated_metis_test_authority(
        source,
        revision=revision,
        tree=tree,
        modules_sha256=runtime_sha256,
        runtime_modules=runtime_modules,
    ) as isolated:
        assert (isolated / "tooling/node_modules/pkg/index.js").read_text(
            encoding="utf-8"
        ) == "export default 'historical';\n"
        assert _git(isolated, "rev-parse", "HEAD") == revision


def test_isolated_authority_rejects_the_wrong_external_runtime(tmp_path: Path) -> None:
    source, revision, tree, _source_modules_sha256 = _source_authority(tmp_path)
    runtime_modules = tmp_path / "runtime/node_modules"
    runtime_package = runtime_modules / "pkg/index.js"
    runtime_package.parent.mkdir(parents=True)
    runtime_package.write_text("export default 'wrong';\n", encoding="utf-8")

    with (
        pytest.raises(test_harness.TestHarnessError, match="differs from the test pin"),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256="0" * 64,
            runtime_modules=runtime_modules,
        ),
    ):
        pytest.fail("wrong external runtime must fail before isolation")


def test_isolated_authority_detects_external_runtime_change_during_use(
    tmp_path: Path,
) -> None:
    source, revision, tree, _source_modules_sha256 = _source_authority(tmp_path)
    runtime_modules = tmp_path / "runtime/node_modules"
    runtime_package = runtime_modules / "pkg/index.js"
    runtime_package.parent.mkdir(parents=True)
    runtime_package.write_text("export default 'historical';\n", encoding="utf-8")
    runtime_sha256 = catalog_pin._node_modules_sha256(runtime_modules)

    with (
        pytest.raises(test_harness.TestHarnessError, match="changed during tests"),
        test_harness.isolated_metis_test_authority(
            source,
            revision=revision,
            tree=tree,
            modules_sha256=runtime_sha256,
            runtime_modules=runtime_modules,
        ),
    ):
        runtime_package.write_text("export default 'mutated';\n", encoding="utf-8")


def test_run_tests_separates_current_brain_from_historical_oracle_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brain_root = tmp_path / "brain-metis"
    oracle_node_modules = tmp_path / "oracle-node-modules"
    isolated_root = tmp_path / "isolated-metis"
    brain_isolated_root = tmp_path / "brain-isolated-metis"
    node = tmp_path / "bin/node"
    for path in (brain_root, oracle_node_modules, isolated_root, node.parent):
        path.mkdir(parents=True)
    node.write_bytes(b"node")
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        test_harness.oracles,
        "_validate_node_binary",
        lambda path: (Path(path), "digest"),
    )
    monkeypatch.setattr(
        test_harness.brain_toolchain_pin,
        "verify_metis_brain_toolchain_pin",
        lambda root, _node, execute_probes: {
            **{
                f"evidence_{key}": value
                for key, value in {
                    "in": 29,
                    "out": 29,
                    "distinct": 29,
                    "gaps": 0,
                }.items()
            },
            **{
                f"probes_{key}": value
                for key, value in {
                    "in": 9,
                    "out": 9,
                    "distinct": 9,
                    "gaps": 0,
                }.items()
            },
            "probes_executed": execute_probes,
            "revision": "a" * 40,
            "tree": "b" * 40,
            "remote_ref_revision": "c" * 40,
            "identity": SimpleNamespace(node_modules_sha256="sha256:" + "d" * 64),
            "brain_root": seen.setdefault("brain", Path(root)),
        },
    )

    @contextmanager
    def isolated(
        root: Path,
        *,
        revision: str = test_harness.oracles.PINNED_METIS_REVISION,
        tree: str = test_harness.oracles.PINNED_METIS_TREE,
        modules_sha256: str = test_harness.oracles.PINNED_NODE_MODULES_SHA256,
        runtime_modules: Path | None = None,
        remote_ref_revision: str | None = None,
    ):
        if runtime_modules is not None:
            seen["oracle_source"] = Path(root)
            seen["oracle_runtime"] = Path(runtime_modules)
            yield isolated_root
            return
        seen["brain_source"] = Path(root)
        seen["brain_revision"] = Path(revision)
        seen["brain_tree"] = Path(tree)
        seen["brain_modules"] = Path(modules_sha256)
        assert remote_ref_revision is not None
        seen["brain_remote_ref"] = Path(remote_ref_revision)
        yield brain_isolated_root

    monkeypatch.setattr(test_harness, "isolated_metis_test_authority", isolated)
    monkeypatch.setattr(test_harness.oracles, "validate_pinned_metis", lambda root: None)
    monkeypatch.setattr(
        test_harness.grammar_stdlib_oracle,
        "validate_grammar_stdlib_pin",
        lambda *, metis_root: None,
    )
    monkeypatch.setattr(
        test_harness.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    assert (
        test_harness.run_tests(
            metis_root=brain_root,
            oracle_node_modules=oracle_node_modules,
            node_path=node,
            pytest_args=("-q",),
        )
        == 0
    )
    assert seen == {
        "brain": brain_root,
        "oracle_source": brain_root,
        "oracle_runtime": oracle_node_modules,
        "brain_source": brain_root,
        "brain_revision": Path("a" * 40),
        "brain_tree": Path("b" * 40),
        "brain_modules": Path("d" * 64),
        "brain_remote_ref": Path("c" * 40),
    }


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
