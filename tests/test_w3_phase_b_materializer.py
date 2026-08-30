from __future__ import annotations

# ruff: noqa: E402, I001

import copy
import base64
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import w3_broker_installer as installer
from runtime import w3_broker_executor as executor
from runtime import w3_broker_protocol as protocol
from runtime import w3_installed_worker as installed_worker
from runtime import w3_phase_b_materializer as materializer


CPYTHON_ROOT = Path(
    "/Users/tommasotessarolo/.local/share/uv/python/cpython-3.13.3-macos-aarch64-none"
)
FROZEN_WHEEL_ROOT = Path("/private/var/tmp/MetisModel1-w3-phase-b-source/wheels")


def _registered_node() -> Path:
    configured = os.environ.get("METIS_MODEL1_NODE")
    if configured is None:
        raise RuntimeError("METIS_MODEL1_NODE must be supplied by the canonical test harness")
    node = Path(configured)
    if not node.is_absolute():
        raise RuntimeError("METIS_MODEL1_NODE must be an absolute path")
    return node.resolve(strict=True)


PINNED_NODE = _registered_node()


@pytest.fixture(scope="module")
def full_materialization(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("w3-phase-b-materialization") / "source"
    return materializer.build_materialization(root, node_path=PINNED_NODE)


def _transaction_roots(base: Path) -> dict[str, Path]:
    source_root = base / "source"
    wheel_root = source_root / "wheels"
    wheel_root.mkdir(parents=True, mode=0o700)
    for source in FROZEN_WHEEL_ROOT.iterdir():
        target = wheel_root / source.name
        target.write_bytes(source.read_bytes())
        target.chmod(0o444)
    manifest_root = base / "manifests"
    manifest_root.mkdir(mode=0o755)
    staging_parent = base / "staging"
    staging_parent.mkdir(mode=0o700)
    return {
        "base": base,
        "source_root": source_root,
        "bootstrap_source": base / "bootstrap" / "w3-installer-bootstrap",
        "manifest_root": manifest_root,
        "staging_parent": staging_parent,
    }


def _run_transaction(roots: dict[str, Path]) -> dict[str, object]:
    return materializer.materialize_transaction(
        staging_parent=roots["staging_parent"],
        source_root=roots["source_root"],
        bootstrap_source=roots["bootstrap_source"],
        manifest_root=roots["manifest_root"],
        node_path=PINNED_NODE,
    )


@pytest.fixture(scope="module")
def published_transaction(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    roots = _transaction_roots(tmp_path_factory.mktemp("w3-phase-b-transaction"))
    wheels = roots["source_root"] / "wheels"
    wheel_identities = {
        path.name: (path.lstat().st_dev, path.lstat().st_ino) for path in wheels.iterdir()
    }
    first = _run_transaction(roots)
    first_output_identities = {
        str(path.relative_to(roots["base"])): (path.lstat().st_dev, path.lstat().st_ino)
        for path in (
            roots["bootstrap_source"],
            *(
                roots["manifest_root"] / row["path"].rsplit("/", 1)[-1]
                for row in first["manifest_outputs"]
            ),
            *(
                roots["source_root"] / row["path"].rsplit("/", 1)[-1]
                for row in first["source_outputs"]
            ),
        )
    }
    second = _run_transaction(roots)
    second_output_identities = {
        str(path.relative_to(roots["base"])): (path.lstat().st_dev, path.lstat().st_ino)
        for path in (
            roots["bootstrap_source"],
            *(
                roots["manifest_root"] / row["path"].rsplit("/", 1)[-1]
                for row in second["manifest_outputs"]
            ),
            *(
                roots["source_root"] / row["path"].rsplit("/", 1)[-1]
                for row in second["source_outputs"]
            ),
        )
    }
    return {
        **roots,
        "first": first,
        "second": second,
        "wheel_identities": wheel_identities,
        "wheel_identities_after": {
            path.name: (path.lstat().st_dev, path.lstat().st_ino) for path in wheels.iterdir()
        },
        "first_output_identities": first_output_identities,
        "second_output_identities": second_output_identities,
    }


def _record_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return "sha256=" + digest.decode("ascii")


def _mini_wheel(
    members: list[tuple[str, bytes, int]],
    *,
    record_override: str | None = None,
) -> bytes:
    record_path = "cryptography-47.0.0.dist-info/RECORD"
    record = "".join(
        f"{name},{_record_digest(payload)},{len(payload)}\n" for name, payload, _mode in members
    )
    record += f"{record_path},,\n"
    if record_override is not None:
        record = record_override
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload, mode in members:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, payload)
        info = zipfile.ZipInfo(record_path)
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(info, record.encode("utf-8"))
    return output.getvalue()


def _unfrozen_bootstrap() -> dict[str, object]:
    return {
        "version": 1,
        "source_root": installer.BOOTSTRAP_SOURCE_ROOT,
        "target_root": installer.STAGED_BUNDLE_ROOT,
        "descriptor_path": installer.BOOTSTRAP_DESCRIPTOR_PATH,
        "descriptor_magic": installer.BOOTSTRAP_DESCRIPTOR_MAGIC,
        "descriptor_max_bytes": installer.BOOTSTRAP_DESCRIPTOR_MAX_BYTES,
        "file_count_max": installer.BOOTSTRAP_FILE_COUNT_MAX,
        "total_bytes_max": installer.BOOTSTRAP_TOTAL_BYTES_MAX,
        "bootstrap_install_path": installer.BOOTSTRAP_BINARY_PATH,
        "bootstrap_source_path": "runtime/w3_installer_bootstrap.c",
        "bootstrap_source_size": installer.BOOTSTRAP_SOURCE_SIZE,
        "bootstrap_source_sha256": installer.BOOTSTRAP_SOURCE_SHA256,
        "bootstrap_binary_size": None,
        "bootstrap_binary_sha256": None,
        "build_provenance": None,
        "manifest_relative_path": installer.BOOTSTRAP_MANIFEST_RELATIVE_PATH,
        "plan_relative_path": installer.BOOTSTRAP_PLAN_RELATIVE_PATH,
        "python_path": (
            installer.STAGED_INSTALL_TREE + installer.EXPECTED_ARTIFACT_PATHS["python"]
        ),
        "executor_module": installer.BOOTSTRAP_EXECUTOR_MODULE,
        "python_argv": ["-I", "-B", "-m", installer.BOOTSTRAP_EXECUTOR_MODULE],
        "cwd": "/",
        "sterile_environment": {"PATH": installer.BOOTSTRAP_STERILE_PATH},
        "admin_precondition": [
            "trusted-/usr/bin/install-copy-bootstrap-and-descriptor",
            "external-/usr/bin/shasum-remeasure-before-exec",
            "trusted-/usr/bin/env--ignore-environment-before-stage-0-exec",
            "no-repository-python-before-stage-0",
        ],
        "admin_invocation_template": installer.admin_invocation_template(),
    }


def test_cpython_census_excludes_bytecode_and_symlinks_without_losing_raw_modes() -> None:
    census = materializer.census_cpython(CPYTHON_ROOT)
    assert census["files"] == 1_808
    assert census["bytes"] == 44_064_036
    assert census["sha256"] == (
        "sha256:b632ae57ee6c013e720fc699380923d807cafa6e82df6b1e96ab9163d7193333"
    )
    assert {row["mode"] for row in census["entries"]} == {0o644, 0o755}
    assert sum(bool(int(row["mode"]) & 0o111) for row in census["entries"]) == 49
    assert all(
        not materializer.is_forbidden_cpython_path(str(row["path"])) for row in census["entries"]
    )


def test_cpython_install_projection_normalizes_modes_but_keeps_exact_bytes() -> None:
    census = materializer.census_cpython(CPYTHON_ROOT)
    rows, source_map = materializer.project_cpython_install(census["entries"])
    assert len(rows) == len(source_map) == 1_808
    assert {row["mode"] for row in rows} == {
        0o100444,
        0o100555,
    }
    by_path = {str(row["path"]): row for row in rows}
    python = by_path[installer.EXPECTED_ARTIFACT_PATHS["python"]]
    assert python["size"] == installer.PYTHON_EXECUTABLE_SIZE
    assert python["sha256"] == installer.PYTHON_EXECUTABLE_SHA256


def test_exact_three_frozen_wheels_are_regular_read_only_and_pinned() -> None:
    expected = {
        "cryptography-47.0.0.whl": (
            7_912_214,
            "160ad728f128972d362e714054f6ba0067cab7fb350c5202a9ae8ae4ce3ef1a0",
        ),
        "cffi-2.0.0.whl": (
            181_043,
            "45d5e886156860dc35862657e1494b9bae8dfa63bf56796f2fb56e1679fc0bca",
        ),
        "pycparser-3.0.whl": (
            48_172,
            "b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992",
        ),
    }
    assert {path.name for path in FROZEN_WHEEL_ROOT.iterdir()} == set(expected)
    for name, (size, sha256) in expected.items():
        path = FROZEN_WHEEL_ROOT / name
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and not path.is_symlink()
        assert stat.S_IMODE(info.st_mode) == 0o444
        payload = path.read_bytes()
        assert len(payload) == size == info.st_size
        assert hashlib.sha256(payload).hexdigest() == sha256


def test_exact_three_wheel_record_projections_are_complete_and_disjoint() -> None:
    counts = {"cryptography": 117, "cffi": 30, "pycparser": 13}
    targets: set[str] = set()
    for distribution, expected_count in counts.items():
        wheel = next(FROZEN_WHEEL_ROOT.glob(f"{distribution}-*.whl"))
        inspected = materializer.inspect_wheel(wheel, distribution=distribution)
        assert len(inspected["entries"]) == len(inspected["install_map"]) == expected_count
        assert len(inspected["payloads"]) == expected_count
        order = [
            (row["distribution"], row["member_path"], row["install_path"])
            for row in inspected["install_map"]
        ]
        assert order == sorted(order)
        current = {row["path"] for row in inspected["entries"]}
        assert targets.isdisjoint(current)
        targets.update(current)


@pytest.mark.parametrize("extra_kind", ("directory", "symlink", "fifo"))
def test_exact_wheel_root_rejects_every_extra_leaf(
    tmp_path: Path,
    extra_kind: str,
) -> None:
    wheel_root = tmp_path / "wheels"
    wheel_root.mkdir()
    for source in FROZEN_WHEEL_ROOT.iterdir():
        target = wheel_root / source.name
        target.write_bytes(source.read_bytes())
        target.chmod(0o444)
    extra = wheel_root / "ambient"
    if extra_kind == "directory":
        extra.mkdir()
    elif extra_kind == "symlink":
        extra.symlink_to(wheel_root / "cryptography-47.0.0.whl")
    else:
        os.mkfifo(extra)
    with pytest.raises(materializer.MaterializerError, match="missing or extra"):
        materializer.inspect_exact_wheels(wheel_root)


@pytest.mark.parametrize(
    "member_path",
    (
        "../escape.py",
        "/absolute.py",
        "pkg\\escape.py",
        "pkg/./dot.py",
        "pkg//empty.py",
        "pkg/__PYCACHE__/startup.PYC",
        "pkg/siteCUSTOMIZE.py",
        "pkg/inject.PTH",
        "pkg/inject.EGG-LINK",
        "pkg/cafe\u0301.py",
    ),
)
def test_wheel_inspection_rejects_escape_injection_and_noncanonical_paths(
    tmp_path: Path,
    member_path: str,
) -> None:
    wheel = tmp_path / "attack.whl"
    wheel.write_bytes(_mini_wheel([(member_path, b"payload", stat.S_IFREG | 0o644)]))
    with pytest.raises(materializer.MaterializerError):
        materializer.inspect_wheel(wheel, distribution="cryptography", enforce_pin=False)


@pytest.mark.parametrize("mode", (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600))
def test_wheel_inspection_rejects_symlink_and_special_members(
    tmp_path: Path,
    mode: int,
) -> None:
    wheel = tmp_path / "special.whl"
    wheel.write_bytes(_mini_wheel([("pkg/member.py", b"payload", mode)]))
    with pytest.raises(materializer.MaterializerError, match="symlink or non-regular"):
        materializer.inspect_wheel(wheel, distribution="cryptography", enforce_pin=False)


def test_wheel_inspection_rejects_casefold_collision_and_record_mismatch(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "collision.whl"
    wheel.write_bytes(
        _mini_wheel(
            [
                ("pkg/Member.py", b"one", stat.S_IFREG | 0o644),
                ("pkg/member.py", b"two", stat.S_IFREG | 0o644),
            ]
        )
    )
    with pytest.raises(materializer.MaterializerError, match="collision"):
        materializer.inspect_wheel(wheel, distribution="cryptography", enforce_pin=False)

    mismatch = tmp_path / "record-mismatch.whl"
    mismatch.write_bytes(
        _mini_wheel(
            [("pkg/member.py", b"payload", stat.S_IFREG | 0o644)],
            record_override=(
                "pkg/member.py,sha256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,7\n"
                "cryptography-47.0.0.dist-info/RECORD,,\n"
            ),
        )
    )
    with pytest.raises(materializer.MaterializerError, match="RECORD measurement mismatch"):
        materializer.inspect_wheel(mismatch, distribution="cryptography", enforce_pin=False)


def test_cpython_census_rejects_symlinked_ancestry_and_special_files(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    root = real_parent / "python"
    root.mkdir(parents=True)
    (root / "safe.py").write_bytes(b"safe")
    alias = tmp_path / "alias-parent"
    alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(materializer.MaterializerError, match="symlinked ancestry"):
        materializer.census_cpython(alias / "python", enforce_pin=False)

    os.mkfifo(root / "special")
    with pytest.raises(materializer.MaterializerError, match="non-regular"):
        materializer.census_cpython(root, enforce_pin=False)


def test_cpython_projection_rejects_casefold_target_collisions() -> None:
    digest = "sha256:" + hashlib.sha256(b"same").hexdigest()
    entries = [
        {"path": "pkg/Member.py", "size": 4, "sha256": digest, "mode": 0o644},
        {"path": "pkg/member.py", "size": 4, "sha256": digest, "mode": 0o644},
    ]
    with pytest.raises(materializer.MaterializerError, match="collision"):
        materializer.project_cpython_install(entries)


def test_capsule_git_archive_role_is_exactly_admitted_and_unknown_role_rejected() -> None:
    row = {
        "mode": 0o444,
        "path": "tooling/src/compiler/compile.ts",
        "role": "git-archive",
        "sha256": "sha256:" + hashlib.sha256(b"compile").hexdigest(),
        "size": 7,
    }
    roster = {
        "files": 1,
        "bytes": 7,
        "sha256": installer._roster_hash([row]),
        "entries": [row],
    }
    assert installer._validate_external_census(
        roster,
        label="capsule",
        fields={"mode", "path", "role", "sha256", "size"},
        expected_files=1,
        expected_bytes=7,
        expected_sha256=roster["sha256"],
    ) == [row]
    alien = copy.deepcopy(roster)
    alien["entries"][0]["role"] = "ambient"
    alien["sha256"] = installer._roster_hash(alien["entries"])
    with pytest.raises(installer.InstallerError, match="role invalid"):
        installer._validate_external_census(
            alien,
            label="capsule",
            fields={"mode", "path", "role", "sha256", "size"},
            expected_files=1,
            expected_bytes=7,
            expected_sha256=alien["sha256"],
        )


def test_frozen_capsule_keeps_all_four_roles_and_exact_32_git_objects() -> None:
    evidence = json.loads(
        (ROOT / "manifests" / "w3-native-loader-evidence.json").read_text(encoding="utf-8")
    )
    closure = evidence["capsule_closure"]
    rows = closure["rows"]
    assert Counter(row["role"] for row in rows) == {
        "tooling": 1_793,
        "git-archive": 32,
        "loader": 1,
        "runner": 1,
    }
    assert (
        installer._validate_external_census(
            {
                "files": closure["counts"]["files"],
                "bytes": closure["counts"]["bytes"],
                "sha256": closure["roster_sha256"],
                "entries": rows,
            },
            label="capsule",
            fields={"mode", "path", "role", "sha256", "size"},
            expected_files=installer.NODE_CAPSULE_FILES,
            expected_bytes=installer.NODE_CAPSULE_BYTES,
            expected_sha256=installer.NODE_CAPSULE_ROSTER_SHA256,
        )
        == rows
    )


def test_capsule_reconstruction_rehashes_all_1827_payloads() -> None:
    roster, payloads = materializer.census_node_capsule()
    assert len(payloads) == roster["files"] == 1_827
    assert sum(map(len, payloads.values())) == roster["bytes"] == 8_922_291
    assert roster["sha256"] == installer.NODE_CAPSULE_ROSTER_SHA256
    for row in roster["entries"]:
        payload = payloads[row["path"]]
        assert len(payload) == row["size"]
        assert "sha256:" + hashlib.sha256(payload).hexdigest() == row["sha256"]


def test_source_install_map_requires_immutable_normalized_modes() -> None:
    digest = "sha256:" + hashlib.sha256(b"source").hexdigest()
    source_rows = [
        {"path": "lib/source.py", "size": 6, "sha256": digest, "mode": 0o644},
        {"path": "bin/tool", "size": 6, "sha256": digest, "mode": 0o755},
    ]
    value = [
        {
            "source_path": "bin/tool",
            "install_path": f"{installer.PYTHON_ROOT}/bin/tool",
        },
        {
            "source_path": "lib/source.py",
            "install_path": f"{installer.PYTHON_ROOT}/lib/source.py",
        },
    ]
    install_by_path = {
        f"{installer.PYTHON_ROOT}/bin/tool": {
            "path": f"{installer.PYTHON_ROOT}/bin/tool",
            "size": 6,
            "sha256": digest,
            "uid": 0,
            "gid": 0,
            "mode": stat.S_IFREG | 0o555,
        },
        f"{installer.PYTHON_ROOT}/lib/source.py": {
            "path": f"{installer.PYTHON_ROOT}/lib/source.py",
            "size": 6,
            "sha256": digest,
            "uid": 0,
            "gid": 0,
            "mode": stat.S_IFREG | 0o444,
        },
    }
    assert installer._validate_source_install_map(
        value,
        source_rows=source_rows,
        install_by_path=install_by_path,
    ) == set(install_by_path)
    mutable = copy.deepcopy(install_by_path)
    mutable[f"{installer.PYTHON_ROOT}/lib/source.py"]["mode"] = stat.S_IFREG | 0o644
    with pytest.raises(installer.InstallerError, match="byte-identical"):
        installer._validate_source_install_map(
            value,
            source_rows=source_rows,
            install_by_path=mutable,
        )


def test_generated_fixture_registry_is_canonical_validated_and_five_role() -> None:
    first = materializer.build_fixture_registry()
    second = materializer.build_fixture_registry()
    assert first == second
    registry = protocol.parse_canonical_json(first)
    indexed = installed_worker.validate_fixture_registry(registry)
    assert list(indexed) == [
        "bridge-f1-author-001-author",
        "bridge-f2-edit-001-before",
        "bridge-f2-edit-001-after",
        "bridge-f3-repair-001-mutated",
        "bridge-f3-repair-001-fixed",
    ]
    assert b"/Users/" not in first
    assert all(
        row["runtime_expectations"]["execution_policy_sha256"]
        == "sha256:4f29bf5e092d83993f19ad3d257cafd968a69b708679cecf5edc03cdf018de51"
        for row in registry["entries"]
    )


def test_fixture_registry_rejects_duplicate_family_and_ignores_helper_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = json.loads(
        (ROOT / "manifests" / "w3-f1-f3-smoke-candidates.json").read_text(encoding="utf-8")
    )
    candidates["candidates"].append(copy.deepcopy(candidates["candidates"][0]))
    duplicate = tmp_path / "duplicate-candidates.json"
    duplicate.write_text(json.dumps(candidates), encoding="utf-8")
    with pytest.raises(
        materializer.MaterializerError, match="fixture manifests drifted|family roster"
    ):
        materializer.build_fixture_registry(duplicate)

    from runtime import w3_native_evidence as native_evidence

    baseline = materializer.build_fixture_registry()
    monkeypatch.setattr(
        native_evidence,
        "ROLE_FIELDS",
        (*native_evidence.ROLE_FIELDS, ("F-1", "ambient", "target_source")),
    )
    assert materializer.build_fixture_registry() == baseline


def test_generated_broker_config_is_canonical_and_bound_to_roster() -> None:
    entry = {
        "path": installer.EXPECTED_ARTIFACT_PATHS["python"],
        "size": installer.PYTHON_EXECUTABLE_SIZE,
        "sha256": installer.PYTHON_EXECUTABLE_SHA256,
        "uid": 0,
        "gid": 0,
        "mode": stat.S_IFREG | 0o555,
    }
    payload = materializer.build_broker_config([entry])
    document = protocol.parse_canonical_json(payload)
    assert executor._validate_config(document) == document
    assert document["installed_roster_path_map"] == installer.authority_roster_path_map([entry])


def test_launchd_artifacts_are_exact_tracked_validated_bytes() -> None:
    payloads = materializer.build_launchd_plists()
    for role, label in (
        ("broker-plist", installer.BROKER_PLIST_LABEL),
        ("launcher-plist", installer.LAUNCHER_PLIST_LABEL),
        ("anchor-plist", installer.ANCHOR_PLIST_LABEL),
    ):
        expected = ROOT / "packaging" / "launchd" / f"{label}.plist.in"
        assert payloads[role] == expected.read_bytes()
        installer.validate_launchd_plist_bytes(payloads[role], label=label)


def test_native_three_are_reproducible_distinct_and_release_pinned() -> None:
    payloads = materializer.build_native_binaries()
    assert set(payloads) == set(installer.NATIVE_ARTIFACT_PINS)
    for role, (size, sha256) in installer.NATIVE_ARTIFACT_PINS.items():
        assert len(payloads[role]) == size
        assert "sha256:" + hashlib.sha256(payloads[role]).hexdigest() == sha256
    assert payloads["broker-socket-shim"] != payloads["anchor-socket-shim"]


def test_native_validator_rejects_size_digest_and_role_swap_mutations() -> None:
    exact = {
        role: {
            "size": size,
            "sha256": sha256,
            "source_size": size,
            "source_sha256": sha256,
        }
        for role, (size, sha256) in installer.NATIVE_ARTIFACT_PINS.items()
    }
    installer._validate_native_artifact_pins(exact)

    wrong_size = copy.deepcopy(exact)
    wrong_size["launcher"]["size"] += 1
    with pytest.raises(installer.InstallerError, match="launcher"):
        installer._validate_native_artifact_pins(wrong_size)

    wrong_digest = copy.deepcopy(exact)
    digest = wrong_digest["broker-socket-shim"]["sha256"]
    wrong_digest["broker-socket-shim"]["sha256"] = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    with pytest.raises(installer.InstallerError, match="broker-socket-shim"):
        installer._validate_native_artifact_pins(wrong_digest)

    role_swap = copy.deepcopy(exact)
    role_swap["broker-socket-shim"], role_swap["anchor-socket-shim"] = (
        role_swap["anchor-socket-shim"],
        role_swap["broker-socket-shim"],
    )
    with pytest.raises(installer.InstallerError, match="broker-socket-shim"):
        installer._validate_native_artifact_pins(role_swap)


def test_native_build_rejects_source_swap_and_toolchain_pin_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_project = tmp_path / "fake-project"
    runtime = fake_project / "runtime"
    runtime.mkdir(parents=True)
    for name in ("w3_privileged_launcher.c", "w3_socket_activation_shim.c"):
        (runtime / name).write_text("int main(void) { return 0; }\n", encoding="utf-8")
    monkeypatch.setattr(materializer, "PROJECT_ROOT", fake_project)
    with pytest.raises(materializer.MaterializerError, match="source.*drift"):
        materializer.build_native_binaries()

    monkeypatch.setattr(materializer, "PROJECT_ROOT", ROOT)
    monkeypatch.setattr(installer, "BOOTSTRAP_COMPILER_SHA256", "sha256:" + "0" * 64)
    with pytest.raises(materializer.MaterializerError, match="compiler preimage drifted"):
        materializer.build_native_binaries()


def test_stage0_two_builds_are_exact_and_never_execute() -> None:
    payload = materializer.verify_stage0_builds()
    assert len(payload) == installer.BOOTSTRAP_BINARY_SIZE
    assert "sha256:" + hashlib.sha256(payload).hexdigest() == installer.BOOTSTRAP_BINARY_SHA256


def test_exclusive_writer_rejects_symlinked_parent_without_residue(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(materializer.MaterializerError, match="publication failed|symlink"):
        materializer._write_exclusive(alias / "leaf", b"payload", 0o444)
    assert not (outside / "leaf").exists()
    assert alias.is_symlink()


def test_tree_writer_holds_created_root_across_parent_swap_without_foreign_residue(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "source"
    displaced = parent / "displaced-source"

    def swap_root() -> None:
        root.rename(displaced)
        root.mkdir()

    with pytest.raises(materializer.MaterializerError, match="root identity changed"):
        materializer._write_tree_exclusive(
            root,
            {"nested/leaf": (b"canonical", 0o444)},
            after_root_open=swap_root,
        )
    assert root.is_dir() and list(root.iterdir()) == []
    assert displaced.is_dir() and list(displaced.iterdir()) == []
    assert not (root / "nested" / "leaf").exists()
    assert not (displaced / "nested" / "leaf").exists()


def test_tree_writer_rejects_intermediate_component_swap_without_touching_foreign_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "source"
    displaced = tmp_path / "owned-component"
    foreign_marker = root / "a" / "foreign-marker"
    real_fsync = materializer.os.fsync
    swapped = False

    def fsync_then_swap(descriptor: int) -> None:
        nonlocal swapped
        real_fsync(descriptor)
        if not swapped and (root / "a").is_dir():
            (root / "a").rename(displaced)
            (root / "a").mkdir()
            foreign_marker.write_bytes(b"foreign")
            foreign_marker.chmod(0o444)
            swapped = True

    monkeypatch.setattr(materializer.os, "fsync", fsync_then_swap)
    with pytest.raises(materializer.MaterializerError):
        materializer._write_tree_exclusive(
            root,
            {"a/leaf": (b"canonical", 0o444)},
        )
    assert swapped
    assert foreign_marker.read_bytes() == b"foreign"
    assert not (root / "a" / "leaf").exists()
    assert displaced.is_dir() and list(displaced.iterdir()) == []


def test_tree_writer_closes_component_descriptors_on_injected_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "source"
    real_open = materializer.os.open
    real_close = materializer.os.close
    real_fsync = materializer.os.fsync
    live_descriptors: set[int] = set()
    injected = False

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = real_open(*args, **kwargs)
        live_descriptors.add(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        live_descriptors.discard(descriptor)
        real_close(descriptor)

    def fail_after_component_open(descriptor: int) -> None:
        nonlocal injected
        real_fsync(descriptor)
        if not injected and (root / "a").is_dir():
            injected = True
            raise OSError("injected component publication failure")

    monkeypatch.setattr(materializer.os, "open", tracked_open)
    monkeypatch.setattr(materializer.os, "close", tracked_close)
    monkeypatch.setattr(materializer.os, "fsync", fail_after_component_open)
    with pytest.raises(materializer.MaterializerError, match="publication failed"):
        materializer._write_tree_exclusive(root, {"a/leaf": (b"canonical", 0o444)})
    leaked = set(live_descriptors)
    for descriptor in leaked:
        real_close(descriptor)
    live_descriptors.clear()
    assert injected
    assert leaked == set()


def test_stage0_template_binds_durable_source_target_copy_and_remeasure() -> None:
    template = installer.admin_invocation_template()
    source = template["bootstrap_source"]
    target = template["bootstrap_target"]
    assert source == {
        "path": installer.BOOTSTRAP_BINARY_SOURCE_PATH,
        "size": installer.BOOTSTRAP_BINARY_SIZE,
        "sha256": installer.BOOTSTRAP_BINARY_SHA256,
        "mode": "0555",
    }
    assert target == {
        "path": installer.BOOTSTRAP_BINARY_PATH,
        "size": installer.BOOTSTRAP_BINARY_SIZE,
        "sha256": installer.BOOTSTRAP_BINARY_SHA256,
        "mode": "0555",
    }
    assert not str(source["path"]).startswith(installer.BOOTSTRAP_SOURCE_ROOT + "/")
    assert template["trusted_install_argv"][2] == "/usr/bin/install"
    assert template["trusted_install_argv"][-2:] == [source["path"], target["path"]]
    assert template["target_remeasure_before_exec"] == {
        "path": installer.BOOTSTRAP_BINARY_PATH,
        "regular_no_symlink": True,
        "size": installer.BOOTSTRAP_BINARY_SIZE,
        "sha256": installer.BOOTSTRAP_BINARY_SHA256,
        "mode": "0555",
        "must_match_source_bytes": True,
    }
    assert (
        installer._validate_installer_bootstrap(_unfrozen_bootstrap())["admin_invocation_template"]
        == template
    )
    for field in ("bootstrap_source", "bootstrap_target", "trusted_install_argv"):
        mutated = _unfrozen_bootstrap()
        mutated["admin_invocation_template"][field] = copy.deepcopy(
            mutated["admin_invocation_template"][field]
        )
        if field == "trusted_install_argv":
            mutated["admin_invocation_template"][field][-1] = "/private/var/db/foreign"
        else:
            mutated["admin_invocation_template"][field]["path"] = "/private/var/tmp/foreign"
        with pytest.raises(installer.InstallerError, match="admin_invocation_template drifted"):
            installer._validate_installer_bootstrap(mutated)


def test_manifest_schema_carries_corrected_cpython_denominators_and_capsule_role() -> None:
    schema = json.loads(
        Path("schemas/w3-phase-b-install-bundle.schema.json").read_text(encoding="utf-8")
    )
    source = schema["$defs"]["pythonSourceCensus"]
    assert source["properties"]["files"] == {"const": 1_808}
    assert source["properties"]["bytes"] == {"const": 44_064_036}
    assert source["properties"]["sha256"] == {
        "const": "sha256:b632ae57ee6c013e720fc699380923d807cafa6e82df6b1e96ab9163d7193333"
    }
    assert schema["$defs"]["pythonRuntime"]["properties"]["source_install_map"]["minItems"] == 1_808
    assert "git-archive" in schema["$defs"]["nodeSourceRow"]["properties"]["role"]["enum"]
    template = schema["$defs"]["adminInvocationTemplate"]
    for field in (
        "bootstrap_source",
        "bootstrap_target",
        "trusted_install_argv",
        "target_remeasure_before_exec",
    ):
        assert field in template["required"]
    assert template["properties"]["bootstrap_source"]["const"]["path"] == (
        installer.BOOTSTRAP_BINARY_SOURCE_PATH
    )
    assert template["properties"]["bootstrap_target"]["const"]["path"] == (
        installer.BOOTSTRAP_BINARY_PATH
    )
    native_rules = {
        rule["if"]["properties"]["role"]["const"]: rule["then"]["properties"]
        for rule in schema["$defs"]["artifact"]["allOf"]
    }
    assert set(native_rules) == set(installer.NATIVE_ARTIFACT_PINS)
    for role, (size, sha256) in installer.NATIVE_ARTIFACT_PINS.items():
        assert native_rules[role]["size"] == {"const": size}
        assert native_rules[role]["sha256"] == {"const": sha256}


def test_full_materialization_closes_every_roster_and_canonical_document(
    full_materialization: dict[str, object],
) -> None:
    manifest = full_materialization["manifest"]
    assert isinstance(manifest, dict)
    assert manifest["bundle_sha256"] == (
        "sha256:9bacb3463c015e72d85d2283f07db13a63e17a9291c9bc8a4de2eadc6b029ec0"
    )
    assert len(full_materialization["manifest_payload"]) == 4_903_172
    assert len(full_materialization["plan_payload"]) == 16_838
    assert len(full_materialization["descriptor_payload"]) == 2_137_703
    assert len(full_materialization["admin_invocation_payload"]) == 2_217

    assert len(manifest["artifacts"]) == 20
    assert {row["role"] for row in manifest["artifacts"]} == set(installer.EXPECTED_ARTIFACT_PATHS)
    assert manifest["source_roster"] == {
        "files": 7_475,
        "bytes": 367_503_999,
        "sha256": ("sha256:db5360ff01971f9d1fa4400c32ac54dd405c377a65a754a9220c6b842c17be48"),
        "entries": manifest["source_roster"]["entries"],
    }
    assert manifest["install_roster"] == {
        "files": 3_817,
        "bytes": 191_988_683,
        "sha256": ("sha256:89293b5c5effbe86a89c16b289e1133fb8f18b5d82eb1d69b48cf05fd8e75e3b"),
        "entries": manifest["install_roster"]["entries"],
    }
    python_runtime = manifest["python_runtime"]
    raw_cpython_by_path = {row["path"]: row for row in python_runtime["source_census"]["entries"]}
    cpython_executables = {
        row["install_path"]
        for row in python_runtime["source_install_map"]
        if int(raw_cpython_by_path[row["source_path"]]["mode"]) & 0o111
    }
    assert len(cpython_executables) == 49
    assert set(python_runtime["executable_paths"]) - cpython_executables == {
        (f"{installer.PYTHON_SITE_PACKAGES}/_cffi_backend.cpython-313-darwin.so"),
        f"{installer.PYTHON_SITE_PACKAGES}/cryptography/hazmat/bindings/_rust.abi3.so",
    }
    assert Counter(row["role"] for row in manifest["node_capsule"]["source_census"]["entries"]) == {
        "tooling": 1_793,
        "git-archive": 32,
        "loader": 1,
        "runner": 1,
    }

    assert installer.validate_bundle_manifest(manifest, require_frozen=True) == manifest
    installer.validate_install_plan(full_materialization["plan"], bundle_manifest=manifest)
    parsed_descriptor = installer.validate_bootstrap_descriptor_bytes(
        full_materialization["descriptor_payload"]
    )
    assert parsed_descriptor["file_count"] == len(full_materialization["descriptor_files"])
    assert parsed_descriptor["file_count"] == 7_477
    installer.validate_admin_invocation_document(
        full_materialization["admin_invocation"],
        descriptor_payload=full_materialization["descriptor_payload"],
        plan_payload=full_materialization["plan_payload"],
        manifest_payload=full_materialization["manifest_payload"],
    )

    schema = json.loads(
        (ROOT / "schemas" / "w3-phase-b-install-bundle.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []


def test_full_materialization_descriptor_matches_the_complete_physical_tree(
    full_materialization: dict[str, object],
) -> None:
    source_root = Path(str(full_materialization["source_root"]))
    assert {path.name for path in source_root.iterdir()} == {
        "artifacts",
        "install-root",
        "metadata",
        "source-census",
        "wheels",
    }
    descriptor = installer.validate_bootstrap_descriptor_bytes(
        full_materialization["descriptor_payload"]
    )
    expected = {str(row["path"]): row for row in descriptor["files"]}
    measured: dict[str, tuple[int, str, str]] = {}
    for parent, directories, files in os.walk(source_root, topdown=True, followlinks=False):
        directories.sort(key=lambda value: value.encode("utf-8"))
        files.sort(key=lambda value: value.encode("utf-8"))
        for directory in directories:
            info = os.lstat(Path(parent) / directory)
            assert stat.S_ISDIR(info.st_mode)
        for filename in files:
            path = Path(parent) / filename
            info = os.lstat(path)
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            payload = path.read_bytes()
            relative = path.relative_to(source_root).as_posix()
            measured[relative] = (
                len(payload),
                "sha256:" + hashlib.sha256(payload).hexdigest(),
                f"{stat.S_IMODE(info.st_mode):04o}",
            )
    assert set(measured) == set(expected)
    assert len(measured) == 7_477
    assert sum(size for size, _sha256, _mode in measured.values()) == 372_424_009
    for relative, row in expected.items():
        assert measured[relative] == (row["size"], row["sha256"], row["mode"])


def test_transaction_clean_publish_and_second_call_exact_adoption(
    published_transaction: dict[str, object],
) -> None:
    first = published_transaction["first"]
    second = published_transaction["second"]
    assert first["status"] == second["status"] == "sealed"
    assert first["kind"] == second["kind"] == "w3-phase-b-materialization-receipt"
    assert (
        first["bundle_sha256"]
        == second["bundle_sha256"]
        == ("sha256:9bacb3463c015e72d85d2283f07db13a63e17a9291c9bc8a4de2eadc6b029ec0")
    )
    assert {row["state"] for row in first["source_outputs"]} == {"created"}
    assert {row["state"] for row in first["manifest_outputs"]} == {"created"}
    assert first["bootstrap_source"]["state"] == "created"
    assert {row["state"] for row in second["source_outputs"]} == {"adopted"}
    assert {row["state"] for row in second["manifest_outputs"]} == {"adopted"}
    assert second["bootstrap_source"]["state"] == "adopted"
    assert first["source_tree"]["files"] == second["source_tree"]["files"] == 7_477
    assert first["source_tree"]["bytes"] == second["source_tree"]["bytes"] == 372_424_009
    assert (
        published_transaction["wheel_identities_after"] == published_transaction["wheel_identities"]
    )
    assert (
        published_transaction["second_output_identities"]
        == published_transaction["first_output_identities"]
    )

    for receipt in (first, second):
        material = dict(receipt)
        digest = material.pop("receipt_sha256")
        payload = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        assert digest == "sha256:" + hashlib.sha256(payload).hexdigest()


def test_transaction_rejects_partial_foreign_source_child_without_publication(
    tmp_path: Path,
) -> None:
    roots = _transaction_roots(tmp_path / "partial")
    artifacts = roots["source_root"] / "artifacts"
    artifacts.mkdir()
    foreign = artifacts / "foreign"
    foreign.write_bytes(b"foreign")
    foreign.chmod(0o444)
    with pytest.raises(materializer.MaterializerError, match="adopted source child artifacts"):
        _run_transaction(roots)
    assert foreign.read_bytes() == b"foreign"
    assert {path.name for path in roots["source_root"].iterdir()} == {"artifacts", "wheels"}
    assert list(roots["manifest_root"].iterdir()) == []
    assert not roots["bootstrap_source"].parent.exists()


def test_transaction_removes_new_empty_bootstrap_root_on_manifest_preflight_failure(
    tmp_path: Path,
) -> None:
    roots = _transaction_roots(tmp_path / "bootstrap-residue")
    foreign = roots["manifest_root"] / "w3-phase-b-install-bundle.json"
    foreign.write_bytes(b"partial-foreign-output")
    foreign.chmod(0o644)
    with pytest.raises(materializer.MaterializerError, match="adopted manifest output"):
        _run_transaction(roots)
    assert foreign.read_bytes() == b"partial-foreign-output"
    assert not roots["bootstrap_source"].parent.exists()
    assert {path.name for path in roots["source_root"].iterdir()} == {"wheels"}


@pytest.mark.parametrize("fifo_target", ("manifest", "bootstrap"))
def test_transaction_rejects_fifo_before_expensive_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fifo_target: str,
) -> None:
    roots = _transaction_roots(tmp_path / f"fifo-preflight-{fifo_target}")
    if fifo_target == "manifest":
        fifo = roots["manifest_root"] / "w3-phase-b-install-bundle.json"
    else:
        roots["bootstrap_source"].parent.mkdir(mode=0o700)
        fifo = roots["bootstrap_source"]
    os.mkfifo(fifo)
    build_called = False

    def forbidden_build(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal build_called
        build_called = True
        raise AssertionError("expensive materialization ran before output preflight")

    monkeypatch.setattr(materializer, "build_materialization", forbidden_build)
    with pytest.raises(materializer.MaterializerError, match="single-link regular file"):
        _run_transaction(roots)
    assert not build_called
    assert stat.S_ISFIFO(fifo.lstat().st_mode)
    assert {path.name for path in roots["source_root"].iterdir()} == {"wheels"}
    assert [path for path in roots["manifest_root"].iterdir() if path != fifo] == []
    assert list(roots["staging_parent"].iterdir()) == []


@pytest.mark.parametrize("fifo_target", ("manifest", "bootstrap"))
def test_transaction_rejects_preexisting_fifo_without_blocking_or_publication(
    tmp_path: Path,
    fifo_target: str,
) -> None:
    roots = _transaction_roots(tmp_path / f"fifo-{fifo_target}")
    if fifo_target == "manifest":
        fifo = roots["manifest_root"] / "w3-phase-b-install-bundle.json"
    else:
        roots["bootstrap_source"].parent.mkdir(mode=0o700)
        fifo = roots["bootstrap_source"]
    os.mkfifo(fifo)
    script = """
import sys
from pathlib import Path
from runtime.w3_phase_b_materializer import MaterializerError, materialize_transaction
try:
    materialize_transaction(
        staging_parent=Path(sys.argv[1]),
        source_root=Path(sys.argv[2]),
        bootstrap_source=Path(sys.argv[3]),
        manifest_root=Path(sys.argv[4]),
        node_path=Path(sys.argv[5]),
    )
except MaterializerError:
    raise SystemExit(0)
raise SystemExit(2)
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(roots["staging_parent"]),
            str(roots["source_root"]),
            str(roots["bootstrap_source"]),
            str(roots["manifest_root"]),
            str(PINNED_NODE),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        timeout=45,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert stat.S_ISFIFO(fifo.lstat().st_mode)
    assert {path.name for path in roots["source_root"].iterdir()} == {"wheels"}
    assert [path for path in roots["manifest_root"].iterdir() if path != fifo] == []
    assert list(roots["staging_parent"].iterdir()) == []


def test_transaction_ledgers_renamed_child_before_fallible_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _transaction_roots(tmp_path / "rename-ledger")
    original = materializer._verify_child_at
    injected = False

    def fail_first_published_child(*args: object, **kwargs: object) -> os.stat_result:
        nonlocal injected
        label = kwargs.get("label")
        if label == "published source child artifacts":
            injected = True
            raise materializer.MaterializerError("injected child verification failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(materializer, "_verify_child_at", fail_first_published_child)
    with pytest.raises(materializer.MaterializerError, match="injected child verification"):
        _run_transaction(roots)
    assert injected
    assert {path.name for path in roots["source_root"].iterdir()} == {"wheels"}
    assert list(roots["manifest_root"].iterdir()) == []
    assert not roots["bootstrap_source"].parent.exists()


def test_transaction_rolls_back_renamed_child_when_post_rename_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _transaction_roots(tmp_path / "rename-sync")
    real_fsync = materializer.os.fsync
    injected = False

    def fail_first_sync_after_source_rename(descriptor: int) -> None:
        nonlocal injected
        real_fsync(descriptor)
        if not injected and (roots["source_root"] / "artifacts").is_dir():
            injected = True
            raise OSError("injected post-rename sync failure")

    monkeypatch.setattr(materializer.os, "fsync", fail_first_sync_after_source_rename)
    with pytest.raises(OSError, match="injected post-rename sync"):
        _run_transaction(roots)
    assert injected
    assert {path.name for path in roots["source_root"].iterdir()} == {"wheels"}
    assert list(roots["manifest_root"].iterdir()) == []
    assert not roots["bootstrap_source"].parent.exists()


def test_transaction_staging_parent_swap_leaves_foreign_replacement_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _transaction_roots(tmp_path / "staging-swap")
    staging_parent = roots["staging_parent"]
    displaced = roots["base"] / "held-staging"
    original = materializer._open_directory_no_follow
    swapped = False

    def open_then_swap(path: Path) -> int:
        nonlocal swapped
        descriptor = original(path)
        if Path(path) == staging_parent and not swapped:
            staging_parent.rename(displaced)
            staging_parent.mkdir(mode=0o700)
            swapped = True
        return descriptor

    monkeypatch.setattr(materializer, "_open_directory_no_follow", open_then_swap)
    receipt = _run_transaction(roots)
    assert swapped
    assert receipt["status"] == "sealed"
    assert staging_parent.is_dir() and list(staging_parent.iterdir()) == []
    assert displaced.is_dir() and list(displaced.iterdir()) == []
    assert {path.name for path in roots["source_root"].iterdir()} == {
        "artifacts",
        "install-root",
        "metadata",
        "source-census",
        "wheels",
    }
    assert len(list(roots["manifest_root"].iterdir())) == 4
    assert roots["bootstrap_source"].is_file()


@pytest.mark.parametrize("failure_timing", ("before", "after"))
def test_transaction_stages_manifest_leaf_before_atomic_no_replace_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_timing: str,
) -> None:
    roots = _transaction_roots(tmp_path / f"manifest-atomic-{failure_timing}")
    original = materializer._rename_exclusive
    injected = False

    def fail_manifest_rename(
        source_parent_fd: int,
        source_name: str,
        target_parent_fd: int,
        target_name: str,
    ) -> None:
        nonlocal injected
        if target_name == "w3-phase-b-install-bundle.json":
            injected = True
            if failure_timing == "before":
                raise OSError("injected failure before manifest rename")
            original(source_parent_fd, source_name, target_parent_fd, target_name)
            raise OSError("injected failure after manifest rename")
        original(source_parent_fd, source_name, target_parent_fd, target_name)

    monkeypatch.setattr(materializer, "_rename_exclusive", fail_manifest_rename)
    with pytest.raises(materializer.MaterializerError):
        _run_transaction(roots)
    assert injected
    assert {path.name for path in roots["source_root"].iterdir()} == {"wheels"}
    assert list(roots["manifest_root"].iterdir()) == []
    assert not roots["bootstrap_source"].parent.exists()
    assert list(roots["staging_parent"].iterdir()) == []


@pytest.mark.parametrize("cleanup_failure", ("unlink", "fsync"))
def test_transaction_reports_rollback_incomplete_for_owned_manifest_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_failure: str,
) -> None:
    roots = _transaction_roots(tmp_path / f"rollback-{cleanup_failure}")
    original_verify_tree = materializer._verify_tree_at
    real_unlink = materializer.os.unlink
    real_fsync = materializer.os.fsync
    rollback_started = False
    cleanup_injected = False

    def fail_after_final_source_verify(*args: object, **kwargs: object) -> object:
        nonlocal rollback_started
        result = original_verify_tree(*args, **kwargs)
        if kwargs.get("label") == "published fixed source tree":
            rollback_started = True
            raise materializer.MaterializerError("injected final verification failure")
        return result

    def fail_owned_manifest_unlink(*args: object, **kwargs: object) -> None:
        nonlocal cleanup_injected
        path = args[0] if args else kwargs.get("path")
        if (
            cleanup_failure == "unlink"
            and rollback_started
            and not cleanup_injected
            and path == "w3-phase-b-install-bundle.json"
        ):
            cleanup_injected = True
            raise OSError("injected owned manifest unlink failure")
        real_unlink(*args, **kwargs)

    def fail_owned_manifest_fsync(descriptor: int) -> None:
        nonlocal cleanup_injected
        if cleanup_failure == "fsync" and rollback_started and not cleanup_injected:
            cleanup_injected = True
            raise OSError("injected owned manifest fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(materializer, "_verify_tree_at", fail_after_final_source_verify)
    monkeypatch.setattr(materializer.os, "unlink", fail_owned_manifest_unlink)
    monkeypatch.setattr(materializer.os, "fsync", fail_owned_manifest_fsync)
    with pytest.raises(
        materializer.MaterializerError,
        match="rollback was incomplete: manifest outputs",
    ):
        _run_transaction(roots)
    assert cleanup_injected
    assert {path.name for path in roots["source_root"].iterdir()} == {"wheels"}
    assert not roots["bootstrap_source"].parent.exists()
    assert list(roots["staging_parent"].iterdir()) == []
    if cleanup_failure == "unlink":
        assert (roots["manifest_root"] / "w3-phase-b-install-bundle.json").is_file()


def test_transaction_rejects_adopted_output_inode_swap_and_preserves_replacement(
    published_transaction: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_root = published_transaction["manifest_root"]
    target = manifest_root / "w3-phase-b-admin-invocation.json"
    backup = published_transaction["base"] / "adopted-admin-original"
    canonical = target.read_bytes()
    original_identity = (target.lstat().st_dev, target.lstat().st_ino)
    replacement_identity: tuple[int, int] | None = None
    original = materializer._verify_tree_at
    swapped = False

    def swap_after_final_source_verify(*args: object, **kwargs: object) -> object:
        nonlocal replacement_identity, swapped
        result = original(*args, **kwargs)
        if kwargs.get("label") == "published fixed source tree" and not swapped:
            target.rename(backup)
            target.write_bytes(canonical)
            target.chmod(0o644)
            replacement_identity = (target.lstat().st_dev, target.lstat().st_ino)
            swapped = True
        return result

    monkeypatch.setattr(materializer, "_verify_tree_at", swap_after_final_source_verify)
    try:
        with pytest.raises(materializer.MaterializerError, match="identity changed"):
            _run_transaction(published_transaction)
        assert swapped and replacement_identity is not None
        assert replacement_identity != original_identity
        assert target.read_bytes() == canonical
        assert (target.lstat().st_dev, target.lstat().st_ino) == replacement_identity
    finally:
        if target.exists():
            target.unlink()
        if backup.exists():
            backup.rename(target)


def test_transaction_rejects_exact_source_child_inode_swap_and_preserves_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _transaction_roots(tmp_path / "source-child-swap")
    target = roots["source_root"] / "artifacts"
    backup = roots["base"] / "created-artifacts-original"
    original = materializer._verify_child_at
    replacement_identity: tuple[int, int] | None = None

    def swap_before_immediate_child_verify(*args: object, **kwargs: object) -> object:
        nonlocal replacement_identity
        if (
            kwargs.get("label") == "published source child artifacts"
            and replacement_identity is None
        ):
            target.rename(backup)
            shutil.copytree(backup, target, copy_function=shutil.copy2)
            replacement_identity = (target.lstat().st_dev, target.lstat().st_ino)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        materializer,
        "_verify_child_at",
        swap_before_immediate_child_verify,
    )
    with pytest.raises(
        materializer.MaterializerError,
        match="rollback was incomplete: source child artifacts",
    ):
        _run_transaction(roots)
    assert replacement_identity is not None
    assert (target.lstat().st_dev, target.lstat().st_ino) == replacement_identity
    assert target.is_dir() and len(list(target.iterdir())) == 20
    assert backup.is_dir() and len(list(backup.iterdir())) == 20
    assert {path.name for path in roots["source_root"].iterdir()} == {
        "artifacts",
        "wheels",
    }
    assert list(roots["manifest_root"].iterdir()) == []
    assert not roots["bootstrap_source"].parent.exists()


def test_transaction_never_deletes_foreign_workspace_subtree_during_final_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = _transaction_roots(tmp_path / "foreign-workspace")
    original = materializer._verify_tree_at
    foreign_marker: Path | None = None

    def inject_after_final_source_verify(*args: object, **kwargs: object) -> object:
        nonlocal foreign_marker
        result = original(*args, **kwargs)
        if kwargs.get("label") == "published fixed source tree" and foreign_marker is None:
            workspaces = list(roots["staging_parent"].glob(".w3-phase-b-materialize.*"))
            assert len(workspaces) == 1
            foreign_marker = workspaces[0] / "foreign-subtree" / "marker"
            foreign_marker.parent.mkdir()
            foreign_marker.write_bytes(b"foreign")
            foreign_marker.chmod(0o444)
        return result

    monkeypatch.setattr(materializer, "_verify_tree_at", inject_after_final_source_verify)
    with pytest.raises(materializer.MaterializerError, match="workspace|cleanup|ambiguous"):
        _run_transaction(roots)
    assert foreign_marker is not None
    assert foreign_marker.read_bytes() == b"foreign"
    assert foreign_marker.parent.parent.is_dir()
