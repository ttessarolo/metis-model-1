from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import plistlib
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import MethodType

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime import w3_broker_executor as executor  # noqa: E402
from runtime import w3_broker_installer as installer  # noqa: E402
from runtime import w3_broker_protocol as protocol  # noqa: E402


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _roster(entries: list[dict[str, object]]) -> dict[str, object]:
    rows = sorted((dict(row) for row in entries), key=lambda row: str(row["path"]))
    return {
        "files": len(rows),
        "bytes": sum(int(row["size"]) for row in rows),
        "sha256": installer._roster_hash(rows),
        "entries": rows,
    }


def _build_provenance(binary_sha256: str) -> dict[str, object]:
    sdk = installer.BOOTSTRAP_SDK_PATH
    return {
        "compiler_path": installer.BOOTSTRAP_COMPILER_PATH,
        "compiler_size": installer.BOOTSTRAP_COMPILER_SIZE,
        "compiler_sha256": installer.BOOTSTRAP_COMPILER_SHA256,
        "compiler_version": installer.BOOTSTRAP_COMPILER_VERSION,
        "linker_path": installer.BOOTSTRAP_LINKER_PATH,
        "linker_size": installer.BOOTSTRAP_LINKER_SIZE,
        "linker_sha256": installer.BOOTSTRAP_LINKER_SHA256,
        "linker_version": installer.BOOTSTRAP_LINKER_VERSION,
        "sdk_path": sdk,
        "sdk_version": installer.BOOTSTRAP_SDK_VERSION,
        "sdk_settings_path": f"{sdk}/SDKSettings.json",
        "sdk_settings_size": installer.BOOTSTRAP_SDK_SETTINGS_SIZE,
        "sdk_settings_sha256": installer.BOOTSTRAP_SDK_SETTINGS_SHA256,
        "libsystem_link_path": f"{sdk}/usr/lib/libSystem.tbd",
        "libsystem_link_text": "libSystem.B.tbd",
        "libsystem_link_uid": 0,
        "libsystem_link_gid": 0,
        "libsystem_link_mode": 0o755,
        "libsystem_link_nlink": 1,
        "libsystem_resolved_path": f"{sdk}/usr/lib/libSystem.B.tbd",
        "libsystem_size": installer.BOOTSTRAP_LIBSYSTEM_SIZE,
        "libsystem_sha256": installer.BOOTSTRAP_LIBSYSTEM_SHA256,
        "commondigest_path": f"{sdk}/usr/include/CommonCrypto/CommonDigest.h",
        "commondigest_size": installer.BOOTSTRAP_COMMONDIGEST_SIZE,
        "commondigest_sha256": installer.BOOTSTRAP_COMMONDIGEST_SHA256,
        "architecture": installer.BOOTSTRAP_ARCHITECTURE,
        "deployment_target": installer.BOOTSTRAP_DEPLOYMENT_TARGET,
        "argv": list(installer.BOOTSTRAP_BUILD_ARGV),
        "environment": dict(installer.BOOTSTRAP_BUILD_ENVIRONMENT),
        "cwd": "/",
        "repeat_builds": 2,
        "build_hashes": [binary_sha256, binary_sha256],
        "build_status": "reproducible-two-builds",
        "reproducible_binary_sha256": binary_sha256,
        "mach_o_architectures": [installer.BOOTSTRAP_ARCHITECTURE],
        "linked_dylibs": ["/usr/lib/libSystem.B.dylib"],
        "lc_uuid_present": False,
        "forbidden_path_strings_present": False,
    }


def _bootstrap_block(*, frozen: bool = True) -> dict[str, object]:
    binary = installer.BOOTSTRAP_BINARY_SHA256 if frozen else None
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
        "bootstrap_binary_size": installer.BOOTSTRAP_BINARY_SIZE if frozen else None,
        "bootstrap_binary_sha256": binary,
        "build_provenance": _build_provenance(str(binary)) if frozen else None,
        "manifest_relative_path": installer.BOOTSTRAP_MANIFEST_RELATIVE_PATH,
        "plan_relative_path": installer.BOOTSTRAP_PLAN_RELATIVE_PATH,
        "python_path": installer.STAGED_INSTALL_TREE + installer.EXPECTED_ARTIFACT_PATHS["python"],
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


def _fixture_bundle(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    python_rows = [
        {"path": "bin/python3.13", "size": 7, "sha256": _digest("python"), "mode": 0o555},
        {"path": "lib/python3.13/stdlib.py", "size": 6, "sha256": _digest("stdlib"), "mode": 0o444},
    ]
    node_rows = [
        {
            "path": ".metis-oracle/native_ts_loader.mjs",
            "size": 6,
            "sha256": _digest("loader"),
            "mode": 0o444,
            "role": "loader",
        },
        {
            "path": ".metis-oracle/runner.ts",
            "size": 6,
            "sha256": _digest("runner"),
            "mode": 0o444,
            "role": "runner",
        },
    ]
    python_hash = installer._roster_hash(python_rows)
    node_hash = installer._roster_hash(node_rows)
    monkeypatch.setattr(installer, "PYTHON_SOURCE_FILES", len(python_rows))
    monkeypatch.setattr(installer, "PYTHON_SOURCE_BYTES", sum(row["size"] for row in python_rows))
    monkeypatch.setattr(installer, "PYTHON_SOURCE_ROSTER_SHA256", python_hash)
    monkeypatch.setattr(installer, "PYTHON_EXECUTABLE_SIZE", 7)
    monkeypatch.setattr(installer, "PYTHON_EXECUTABLE_SHA256", _digest("python"))
    monkeypatch.setattr(installer, "NODE_CAPSULE_FILES", len(node_rows))
    monkeypatch.setattr(installer, "NODE_CAPSULE_BYTES", sum(row["size"] for row in node_rows))
    monkeypatch.setattr(installer, "NODE_CAPSULE_ROSTER_SHA256", node_hash)
    monkeypatch.setattr(installer, "NODE_SIZE", 4)
    monkeypatch.setattr(installer, "NODE_SHA256", _digest("node"))
    monkeypatch.setattr(installer, "SEATBELT_POLICY_SIZE", 6)
    monkeypatch.setattr(installer, "SEATBELT_POLICY_SHA256", _digest("policy"))
    dependencies = tuple(
        {"name": name, "version": version, "wheel_sha256": _digest(f"wheel-{name}")}
        for name, version in (("cryptography", "47.0.0"), ("cffi", "2.0.0"), ("pycparser", "3.0"))
    )
    wheel_paths = {
        row["name"]: f"{installer.STAGED_BUNDLE_ROOT}/wheels/{row['name']}-{row['version']}.whl"
        for row in dependencies
    }
    monkeypatch.setattr(installer, "PYTHON_DEPENDENCIES", dependencies)
    monkeypatch.setattr(installer, "WHEEL_SOURCE_PATHS", wheel_paths)

    role_measurements = {
        role: (len(role) + 1, _digest(role)) for role in installer.EXPECTED_ARTIFACT_PATHS
    }
    role_measurements.update(
        {
            "python": (7, _digest("python")),
            "node": (4, _digest("node")),
            "policy": (6, _digest("policy")),
            "loader": (6, _digest("loader")),
            "runner": (6, _digest("runner")),
            "cryptography": (8, _digest("cryptography-member")),
        }
    )
    role_measurements["broker-socket-shim"] = (4, _digest("broker-shim"))
    role_measurements["anchor-socket-shim"] = (4, _digest("anchor-shim"))

    install_by_path: dict[str, dict[str, object]] = {}
    artifacts: list[dict[str, object]] = []
    for role in sorted(installer.EXPECTED_ARTIFACT_PATHS):
        path = installer.EXPECTED_ARTIFACT_PATHS[role]
        size, sha256 = role_measurements[role]
        uid, gid, mode = installer.EXPECTED_ARTIFACT_METADATA[role]
        install_by_path[path] = {
            "path": path,
            "size": size,
            "sha256": sha256,
            "uid": uid,
            "gid": gid,
            "mode": mode,
        }
        artifacts.append(
            {
                "role": role,
                "source_path": f"{installer.STAGED_BUNDLE_ROOT}/artifacts/{role}",
                "source_size": size,
                "source_sha256": sha256,
                "install_path": path,
                "size": size,
                "sha256": sha256,
            }
        )

    python_target = installer.EXPECTED_ARTIFACT_PATHS["python"]
    stdlib_target = f"{installer.PYTHON_ROOT}/lib/python3.13/stdlib.py"
    install_by_path[stdlib_target] = {
        "path": stdlib_target,
        "size": 6,
        "sha256": _digest("stdlib"),
        "uid": 0,
        "gid": 0,
        "mode": stat.S_IFREG | 0o444,
    }
    source_install_map = [
        {"source_path": "bin/python3.13", "install_path": python_target},
        {"source_path": "lib/python3.13/stdlib.py", "install_path": stdlib_target},
    ]
    wheel_targets = {
        "cryptography": installer.EXPECTED_ARTIFACT_PATHS["cryptography"],
        "cffi": f"{installer.PYTHON_SITE_PACKAGES}/cffi/__init__.py",
        "pycparser": f"{installer.PYTHON_SITE_PACKAGES}/pycparser/__init__.py",
    }
    wheel_install_map = []
    for name, target in wheel_targets.items():
        size = 8
        sha256 = _digest("cryptography-member" if name == "cryptography" else f"{name}-member")
        install_by_path[target] = {
            "path": target,
            "size": size,
            "sha256": sha256,
            "uid": 0,
            "gid": 0,
            "mode": stat.S_IFREG | 0o444,
        }
        wheel_install_map.append(
            {"distribution": name, "member_path": f"{name}/__init__.py", "install_path": target}
        )
    wheel_install_map.sort(
        key=lambda row: (row["distribution"], row["member_path"], row["install_path"])
    )

    project_paths = sorted(
        {
            installer.EXPECTED_ARTIFACT_PATHS[role]
            for role in (
                "broker",
                "worker",
                "installer",
                "installer-executor",
                "host-evidence",
                "anchor",
            )
        }
        | {f"{installer.PYTHON_SITE_PACKAGES}/runtime/w3_broker_protocol.py"}
    )
    for path in project_paths:
        if path not in install_by_path:
            install_by_path[path] = {
                "path": path,
                "size": 9,
                "sha256": _digest("non-role-protocol"),
                "uid": 0,
                "gid": 0,
                "mode": stat.S_IFREG | 0o444,
            }
    monkeypatch.setattr(installer, "REQUIRED_PROJECT_PACKAGE_PATHS", tuple(project_paths))
    monkeypatch.setattr(
        installer,
        "REQUIRED_SITE_PACKAGE_PATHS",
        tuple(project_paths) + (installer.EXPECTED_ARTIFACT_PATHS["cryptography"],),
    )

    install_entries = sorted(install_by_path.values(), key=lambda row: row["path"])
    source_entries = [
        {"path": row["source_path"], "size": row["source_size"], "sha256": row["source_sha256"]}
        for row in artifacts
    ]
    source_entries.extend(
        {
            "path": installer.STAGED_INSTALL_TREE + row["path"],
            "size": row["size"],
            "sha256": row["sha256"],
        }
        for row in install_entries
    )
    source_entries.extend(
        {
            "path": f"{installer.PYTHON_SOURCE_CENSUS_ROOT}/{row['path']}",
            "size": row["size"],
            "sha256": row["sha256"],
        }
        for row in python_rows
    )
    source_entries.extend(
        {
            "path": f"{installer.NODE_SOURCE_CENSUS_ROOT}/{row['path']}",
            "size": row["size"],
            "sha256": row["sha256"],
        }
        for row in node_rows
    )
    source_entries.extend(
        {"path": wheel_paths[row["name"]], "size": 10, "sha256": row["wheel_sha256"]}
        for row in dependencies
    )

    source_roster = _roster(source_entries)
    install_roster = _roster(install_entries)
    artifact_material = sorted(artifacts, key=lambda row: row["role"])
    artifact_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(artifact_material, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "kind": "w3-phase-b-install-bundle",
        "status": "frozen",
        "outcome": "PHASE_B_INSTALLABLE_UNEXECUTED",
        "nonclaims": list(installer.NONCLAIMS),
        "release_content_roster_sha256": installer.release_content_roster_digest(install_entries),
        "principals": copy.deepcopy(installer.FIXED_PRINCIPALS),
        "services": [
            installer.LAUNCHER_PLIST_LABEL,
            installer.ANCHOR_PLIST_LABEL,
            installer.BROKER_PLIST_LABEL,
        ],
        "installer_bootstrap": _bootstrap_block(),
        "artifacts": artifacts,
        "artifact_roster_sha256": artifact_hash,
        "python_runtime": {
            "implementation": "CPython",
            "version": installer.PYTHON_VERSION,
            "source_census": {
                "files": len(python_rows),
                "bytes": sum(row["size"] for row in python_rows),
                "sha256": python_hash,
                "entries": python_rows,
            },
            "source_install_map": source_install_map,
            "wheel_install_map": wheel_install_map,
            "project_install_paths": project_paths,
            "executable_paths": [python_target],
            "staged_roster": _roster(
                [
                    row
                    for row in install_entries
                    if row["path"].startswith(installer.PYTHON_ROOT + "/")
                ]
            ),
            "symlink_policy": "no-symlinks-normalize-aliases-before-freeze",
            "editable_paths_allowed": False,
        },
        "python_dependencies": [
            {
                "name": row["name"],
                "version": row["version"],
                "wheel_path": wheel_paths[row["name"]],
                "wheel_size": 10,
                "wheel_sha256": row["wheel_sha256"],
            }
            for row in dependencies
        ],
        "node_capsule": {
            "node_version": installer.NODE_VERSION,
            "node_sha256": installer.NODE_SHA256,
            "source_census": {
                "files": len(node_rows),
                "bytes": sum(row["size"] for row in node_rows),
                "sha256": node_hash,
                "entries": node_rows,
            },
            "evidence_status": "blocked-static-capsule-only",
            "host_credit": False,
        },
        "source_roster": source_roster,
        "install_roster": install_roster,
        "authority_roster_paths": sorted(
            installer.authority_roster_path_map(install_entries).values()
        ),
        "directories": installer.expected_directory_roster(install_entries),
        "backend_roster_sha256": installer.backend_roster_digest(),
        "bundle_sha256": None,
    }
    manifest["bundle_sha256"] = (
        "sha256:"
        + hashlib.sha256(installer.canonical_bundle_bytes(manifest, omit_digest=True)).hexdigest()
    )
    return manifest


def _plan_for(bundle: dict[str, object]) -> dict[str, object]:
    return installer.plan_install(
        {
            "authority_id": installer.AUTHORITY_ID,
            "bundle_sha256": bundle["bundle_sha256"],
            "release_content_roster_sha256": str(bundle["release_content_roster_sha256"])[7:],
        }
    )


class _MemoryJournal:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    @contextmanager
    def session(self):
        yield self

    def append(self, row: dict[str, object]) -> None:
        payload = dict(row)
        assert payload.pop("schema_version") == 1
        assert payload.pop("kind") == executor.INSTALL_JOURNAL_KIND
        self.rows.append({"payload": payload})

    def records(self, *, repair_torn_tail: bool = False) -> list[dict[str, object]]:
        del repair_torn_tail
        return list(self.rows)


def _stateful_exact_backend(
    manifest: dict[str, object],
    *,
    crash_at: tuple[str, str] | None = None,
) -> tuple[executor.MacOSInstallBackend, dict[str, object]]:
    """Use the exact production backend type while modelling only host effects."""

    backend = executor.MacOSInstallBackend(manifest)
    model: dict[str, object] = {
        "effects": [],
        "owned": set(),
        "rollbacks": [],
        "crash_at": crash_at,
        "crash_armed": crash_at is not None,
        "rollback_crash_armed": False,
        "final_checks": [],
        "dynamic_revision": 0,
    }

    def intent(self, step_id, operation):
        return {
            "kind": "fixture-operation-intent",
            "step_id": step_id,
            "operation_id": operation,
        }

    def receipt(step_id: str, operation: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "fixture-operation-receipt",
            "step_id": step_id,
            "operation_id": operation,
        }

    def apply_operation(self, step_id, operation):
        key = (step_id, operation)
        model["effects"].append(key)
        model["owned"].add(key)
        if model["crash_armed"] and key == model["crash_at"]:
            model["crash_armed"] = False
            raise SystemExit("injected-crash-after-effect-before-receipt")
        if step_id == "register-authority":
            self._applied_evidence = {
                "authority_sha256": _digest("installed-authority"),
                "release_ancestry_sha256": _digest("installed-ancestry"),
                "release_content_roster_sha256": manifest["release_content_roster_sha256"],
            }
        return executor.BackendEffect(1, receipt(step_id, operation))

    def step_receipt(self, step_id):
        return {"kind": "fixture-step-receipt", "step_id": step_id}

    def reconcile(self, step_id, operation, _intent):
        key = (step_id, operation)
        if key in model["owned"]:
            return executor.OperationReconciliation("owned-applied", receipt(step_id, operation))
        return executor.OperationReconciliation("not-applied")

    def rollback(self, rollback_id, details):
        model["rollbacks"].append((rollback_id, tuple(details["owned_sources"])))
        for key in tuple(model["owned"]):
            if key[0] in details["owned_sources"]:
                model["owned"].remove(key)
        if model["rollback_crash_armed"]:
            model["rollback_crash_armed"] = False
            raise SystemExit("injected-crash-after-rollback-effect-before-outcome")
        return 1

    def verify_final(self):
        model["final_checks"].append(int(model["dynamic_revision"]))
        return dict(self._applied_evidence)

    backend.operation_intent = MethodType(intent, backend)
    backend.apply_operation = MethodType(apply_operation, backend)
    backend.step_ownership_receipt = MethodType(step_receipt, backend)
    backend.reconcile_operation = MethodType(reconcile, backend)
    backend.rollback = MethodType(rollback, backend)
    backend.verify_final_postconditions = MethodType(verify_final, backend)
    return backend, model


def test_planner_fixes_identities_tree_order_and_key_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _fixture_bundle(monkeypatch)
    plan = _plan_for(bundle)
    assert tuple(step["id"] for step in plan["steps"]) == installer.INSTALL_STEP_IDS
    assert plan["steps"][-1]["id"] == "register-authority"
    assert plan["principals"]["fixed"]["caller"] == {
        "name": "tommasotessarolo",
        "uid": 501,
        "gid": 20,
        "group": "staff",
        "disposition": "must-exist-exactly",
    }
    assert [
        plan["principals"]["fixed"][role]["uid"] for role in ("broker", "runner", "anchor")
    ] == [499, 498, 497]
    tree = {row["path"]: row for row in plan["installed_tree"]}
    assert (
        tree[installer.RUNS_PARENT]["owner"] == "root"
        and tree[installer.RUNS_PARENT]["mode"] == "0711"
    )
    assert (
        tree[installer.RUNS_ACTIVE]["owner"] == installer.RUNNER_PRINCIPAL
        and tree[installer.RUNS_ACTIVE]["mode"] == "0700"
    )
    assert (
        tree[installer.SIGNING_KEY_PATH]["owner"] == "root"
        and tree[installer.SIGNING_KEY_PATH]["group"] == installer.BROKER_PRINCIPAL
        and tree[installer.SIGNING_KEY_PATH]["mode"] == "0440"
    )
    assert (
        tree[installer.PUBLIC_FIXTURE_REGISTRY_PATH]["group"] == "wheel"
        and tree[installer.PUBLIC_FIXTURE_REGISTRY_PATH]["mode"] == "0444"
    )


def test_bundle_validator_binds_full_rosters_bootstrap_and_safe_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _fixture_bundle(monkeypatch)
    assert (
        installer.validate_bundle_manifest(manifest)["bundle_sha256"] == manifest["bundle_sha256"]
    )
    bootstrap_source = ROOT / "runtime" / "w3_installer_bootstrap.c"
    assert bootstrap_source.stat().st_size == installer.BOOTSTRAP_SOURCE_SIZE
    assert (
        "sha256:" + hashlib.sha256(bootstrap_source.read_bytes()).hexdigest()
        == installer.BOOTSTRAP_SOURCE_SHA256
    )
    assert len(manifest["authority_roster_paths"]) > len(installer.AUTHORITY_LOGICAL_PATHS)
    non_role = f"{installer.PYTHON_SITE_PACKAGES}/runtime/w3_broker_protocol.py"
    assert non_role in manifest["authority_roster_paths"]

    weak = copy.deepcopy(manifest)
    row = next(item for item in weak["install_roster"]["entries"] if item["path"] == non_role)
    row["gid"] = installer.BROKER_GID
    weak["install_roster"] = _roster(weak["install_roster"]["entries"])
    weak["python_runtime"]["staged_roster"] = _roster(
        [
            item
            for item in weak["install_roster"]["entries"]
            if str(item["path"]).startswith(installer.PYTHON_ROOT + "/")
        ]
    )
    weak["release_content_roster_sha256"] = installer.release_content_roster_digest(
        weak["install_roster"]["entries"]
    )
    weak["authority_roster_paths"] = sorted(
        installer.authority_roster_path_map(weak["install_roster"]["entries"]).values()
    )
    weak["directories"] = installer.expected_directory_roster(weak["install_roster"]["entries"])
    weak["bundle_sha256"] = (
        "sha256:"
        + hashlib.sha256(installer.canonical_bundle_bytes(weak, omit_digest=True)).hexdigest()
    )
    with pytest.raises(installer.InstallerError, match="root-owned and immutable"):
        installer.validate_bundle_manifest(weak)

    missing_build = copy.deepcopy(manifest)
    missing_build["installer_bootstrap"]["bootstrap_binary_size"] = None
    missing_build["installer_bootstrap"]["bootstrap_binary_sha256"] = None
    missing_build["installer_bootstrap"]["build_provenance"] = None
    missing_build["bundle_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            installer.canonical_bundle_bytes(missing_build, omit_digest=True)
        ).hexdigest()
    )
    with pytest.raises(installer.InstallerError, match="lacks reproducible"):
        installer.validate_bundle_manifest(missing_build)

    self_consistent_fake = copy.deepcopy(manifest)
    fake_source = _digest("substituted-stage0-source")
    fake_binary = _digest("substituted-stage0-binary")
    bootstrap = self_consistent_fake["installer_bootstrap"]
    bootstrap["bootstrap_source_size"] = 999
    bootstrap["bootstrap_source_sha256"] = fake_source
    bootstrap["bootstrap_binary_size"] = 999
    bootstrap["bootstrap_binary_sha256"] = fake_binary
    bootstrap["build_provenance"]["build_hashes"] = [fake_binary, fake_binary]
    bootstrap["build_provenance"]["reproducible_binary_sha256"] = fake_binary
    self_consistent_fake["bundle_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            installer.canonical_bundle_bytes(self_consistent_fake, omit_digest=True)
        ).hexdigest()
    )
    with pytest.raises(installer.InstallerError, match="source measurement drifted"):
        installer.validate_bundle_manifest(self_consistent_fake)

    plist_payloads = {
        installer.EXPECTED_ARTIFACT_PATHS[role]: (
            ROOT / "packaging" / "launchd" / f"{label}.plist.in"
        ).read_bytes()
        for label, role in (
            (installer.LAUNCHER_PLIST_LABEL, "launcher-plist"),
            (installer.ANCHOR_PLIST_LABEL, "anchor-plist"),
            (installer.BROKER_PLIST_LABEL, "broker-plist"),
        )
    }
    for label, role in (
        (installer.LAUNCHER_PLIST_LABEL, "launcher-plist"),
        (installer.ANCHOR_PLIST_LABEL, "anchor-plist"),
        (installer.BROKER_PLIST_LABEL, "broker-plist"),
    ):
        document = installer.validate_launchd_plist_bytes(
            plist_payloads[installer.EXPECTED_ARTIFACT_PATHS[role]],
            label=label,
        )
        assert (
            document["EnvironmentVariables"][installer.LAUNCHD_PACKAGE_INSTANCE_KEY]
            == installer.LAUNCHD_PACKAGE_INSTANCE
        )
    mutated = plistlib.loads(plist_payloads[installer.EXPECTED_ARTIFACT_PATHS["broker-plist"]])
    mutated["ProgramArguments"] = ["/bin/sh"]
    plist_payloads[installer.EXPECTED_ARTIFACT_PATHS["broker-plist"]] = plistlib.dumps(mutated)
    backend = executor.MacOSInstallBackend(manifest)
    backend._verify_staged_row = MethodType(lambda self, row: Path(str(row["path"])), backend)
    monkeypatch.setattr(
        executor, "secure_read", lambda path, *_args, **_kwargs: plist_payloads[str(path)]
    )
    with pytest.raises(executor.BrokerExecutorError, match="STAGED_LAUNCHD_SEMANTICS_INVALID"):
        backend._verify_staged_launchd_plists()


def test_bootstrap_descriptor_is_canonical_bounded_and_c_wire_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_relative = (
        installer.STAGED_INSTALL_TREE.removeprefix(installer.STAGED_BUNDLE_ROOT + "/")
        + installer.EXPECTED_ARTIFACT_PATHS["python"]
    )
    executor_relative = (
        installer.STAGED_INSTALL_TREE.removeprefix(installer.STAGED_BUNDLE_ROOT + "/")
        + installer.EXPECTED_ARTIFACT_PATHS["installer-executor"]
    )
    files = [
        {
            "path": installer.BOOTSTRAP_PLAN_RELATIVE_PATH,
            "size": 2,
            "sha256": _digest("plan"),
            "mode": "0444",
        },
        {
            "path": installer.BOOTSTRAP_MANIFEST_RELATIVE_PATH,
            "size": 3,
            "sha256": _digest("manifest"),
            "mode": "0444",
        },
        {"path": python_relative, "size": 4, "sha256": _digest("python"), "mode": "0555"},
        {"path": executor_relative, "size": 5, "sha256": _digest("executor"), "mode": "0444"},
        {"path": "z/" + "x" * 255, "size": 6, "sha256": _digest("bounded"), "mode": "0444"},
    ]
    payload = installer.bootstrap_descriptor_bytes(
        bootstrap_sha256=_digest("bootstrap"),
        manifest_sha256=_digest("manifest"),
        plan_sha256=_digest("plan"),
        files=files,
    )
    parsed = installer.validate_bootstrap_descriptor_bytes(payload)
    assert parsed["file_count"] == 5 and parsed["total_bytes"] == 20
    assert [row["path"] for row in parsed["files"]] == sorted(row["path"] for row in files)
    for bad_path in ("bad\x1fleaf", "x" * 256, "../escape"):
        bad = copy.deepcopy(files)
        bad[-1]["path"] = bad_path
        with pytest.raises(installer.InstallerError):
            installer.bootstrap_descriptor_bytes(
                bootstrap_sha256=_digest("bootstrap"),
                manifest_sha256=_digest("manifest"),
                plan_sha256=_digest("plan"),
                files=bad,
            )
    assert installer.STAGING_PARENT.startswith(
        "/private/var/db/"
    ) and installer.BOOTSTRAP_SOURCE_ROOT.startswith("/private/var/tmp/")

    library = tmp_path / "libw3-bootstrap-parser.dylib"
    subprocess.run(
        [
            "/usr/bin/clang",
            "-std=c11",
            "-O0",
            "-DW3_BOOTSTRAP_TESTING",
            "-Dmain=w3_embedded_main",
            "-dynamiclib",
            str(ROOT / "runtime" / "w3_installer_bootstrap.c"),
            "-o",
            str(library),
        ],
        check=True,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        capture_output=True,
    )
    parser = ctypes.CDLL(str(library)).w3_bootstrap_testing_validate_descriptor_bytes
    parser.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
    parser.restype = ctypes.c_int
    valid_buffer = ctypes.create_string_buffer(payload)
    assert parser(valid_buffer, len(payload)) == 0
    too_long = payload.replace(
        ("z/" + "x" * 255).encode().hex().encode(), ("z/" + "x" * 256).encode().hex().encode()
    )
    with pytest.raises(installer.InstallerError):
        installer.validate_bootstrap_descriptor_bytes(too_long)
    invalid_buffer = ctypes.create_string_buffer(too_long)
    assert parser(invalid_buffer, len(too_long)) == -1

    manifest = _fixture_bundle(monkeypatch)
    plan = _plan_for(manifest)
    manifest_payload = installer.canonical_bundle_bytes(manifest)
    plan_payload = installer.canonical_plan_bytes(plan)
    arbitrary_entrypoint_files = [
        {
            "path": installer.BOOTSTRAP_PLAN_RELATIVE_PATH,
            "size": len(plan_payload),
            "sha256": "sha256:" + hashlib.sha256(plan_payload).hexdigest(),
            "mode": "0444",
        },
        {
            "path": installer.BOOTSTRAP_MANIFEST_RELATIVE_PATH,
            "size": len(manifest_payload),
            "sha256": "sha256:" + hashlib.sha256(manifest_payload).hexdigest(),
            "mode": "0444",
        },
        {
            "path": python_relative,
            "size": 4,
            "sha256": _digest("python-runtime-entry"),
            "mode": "0555",
        },
        {
            "path": executor_relative,
            "size": 5,
            "sha256": _digest("executor-entry"),
            "mode": "0444",
        },
    ]
    arbitrary_entrypoint_descriptor = installer.bootstrap_descriptor_bytes(
        bootstrap_sha256=installer.BOOTSTRAP_BINARY_SHA256,
        manifest_sha256="sha256:" + hashlib.sha256(manifest_payload).hexdigest(),
        plan_sha256="sha256:" + hashlib.sha256(plan_payload).hexdigest(),
        files=arbitrary_entrypoint_files,
    )
    with pytest.raises(installer.InstallerError, match="descriptor file roster mismatch"):
        installer.admin_invocation_document(
            descriptor_payload=arbitrary_entrypoint_descriptor,
            plan_payload=plan_payload,
            manifest_payload=manifest_payload,
        )

    resolved_files = installer.expected_bootstrap_descriptor_files(
        manifest,
        manifest_payload=manifest_payload,
        plan_payload=plan_payload,
    )
    assert len(resolved_files) == manifest["source_roster"]["files"] + 2
    assert (
        next(row for row in resolved_files if row["path"] == python_relative)["sha256"]
        == next(
            row
            for row in manifest["install_roster"]["entries"]
            if row["path"] == installer.EXPECTED_ARTIFACT_PATHS["python"]
        )["sha256"]
    )
    resolved_descriptor = installer.bootstrap_descriptor_bytes(
        bootstrap_sha256=installer.BOOTSTRAP_BINARY_SHA256,
        manifest_sha256="sha256:" + hashlib.sha256(manifest_payload).hexdigest(),
        plan_sha256="sha256:" + hashlib.sha256(plan_payload).hexdigest(),
        files=resolved_files,
    )
    runbook = installer.admin_invocation_document(
        descriptor_payload=resolved_descriptor,
        plan_payload=plan_payload,
        manifest_payload=manifest_payload,
    )
    assert runbook["argv"][:6] == [
        "/usr/bin/sudo",
        "--",
        "/usr/bin/env",
        "-i",
        f"PATH={installer.BOOTSTRAP_STERILE_PATH}",
        installer.BOOTSTRAP_BINARY_PATH,
    ]
    assert runbook["inherited_environment"] == {}
    assert runbook["argv"][8] == runbook["inputs"]["descriptor"]["sha256"]
    assert runbook["argv"][10] == runbook["inputs"]["plan"]["sha256"]
    assert runbook["argv"][12] == runbook["inputs"]["bundle"]["sha256"]
    assert (
        installer.validate_admin_invocation_document(
            runbook,
            descriptor_payload=resolved_descriptor,
            plan_payload=plan_payload,
            manifest_payload=manifest_payload,
        )
        == runbook
    )
    drifted_runbook = copy.deepcopy(runbook)
    drifted_runbook["argv"][8] = _digest("foreign-descriptor")
    with pytest.raises(installer.InstallerError, match="document drifted"):
        installer.validate_admin_invocation_document(
            drifted_runbook,
            descriptor_payload=resolved_descriptor,
            plan_payload=plan_payload,
            manifest_payload=manifest_payload,
        )

    descriptor_mutations: list[list[dict[str, object]]] = []
    descriptor_mutations.append(copy.deepcopy(resolved_files[:-1]))
    with_extra = copy.deepcopy(resolved_files)
    with_extra.append(
        {
            "path": "unmanifested-extra",
            "size": 1,
            "sha256": _digest("extra"),
            "mode": "0444",
        }
    )
    descriptor_mutations.append(with_extra)
    wrong_python = copy.deepcopy(resolved_files)
    next(row for row in wrong_python if row["path"] == python_relative)["sha256"] = _digest(
        "foreign-python"
    )
    descriptor_mutations.append(wrong_python)
    wrong_executor_mode = copy.deepcopy(resolved_files)
    executor_row = next(row for row in wrong_executor_mode if row["path"] == executor_relative)
    executor_row["mode"] = "0555" if executor_row["mode"] == "0444" else "0444"
    descriptor_mutations.append(wrong_executor_mode)
    for mutated_files in descriptor_mutations:
        mutated_descriptor = installer.bootstrap_descriptor_bytes(
            bootstrap_sha256=installer.BOOTSTRAP_BINARY_SHA256,
            manifest_sha256="sha256:" + hashlib.sha256(manifest_payload).hexdigest(),
            plan_sha256="sha256:" + hashlib.sha256(plan_payload).hexdigest(),
            files=mutated_files,
        )
        with pytest.raises(installer.InstallerError, match="descriptor file roster mismatch"):
            installer.admin_invocation_document(
                descriptor_payload=mutated_descriptor,
                plan_payload=plan_payload,
                manifest_payload=manifest_payload,
            )

    foreign_plan = installer.plan_install(
        {
            "authority_id": installer.AUTHORITY_ID,
            "bundle_sha256": _digest("foreign-frozen-bundle"),
            "release_content_roster_sha256": str(manifest["release_content_roster_sha256"])[7:],
        }
    )
    foreign_plan_payload = installer.canonical_plan_bytes(foreign_plan)
    foreign_files = copy.deepcopy(resolved_files)
    foreign_plan_row = next(
        row for row in foreign_files if row["path"] == installer.BOOTSTRAP_PLAN_RELATIVE_PATH
    )
    foreign_plan_row["size"] = len(foreign_plan_payload)
    foreign_plan_row["sha256"] = "sha256:" + hashlib.sha256(foreign_plan_payload).hexdigest()
    foreign_descriptor = installer.bootstrap_descriptor_bytes(
        bootstrap_sha256=installer.BOOTSTRAP_BINARY_SHA256,
        manifest_sha256="sha256:" + hashlib.sha256(manifest_payload).hexdigest(),
        plan_sha256="sha256:" + hashlib.sha256(foreign_plan_payload).hexdigest(),
        files=foreign_files,
    )
    with pytest.raises(installer.InstallerError, match="frozen bundle binding invalid"):
        installer.admin_invocation_document(
            descriptor_payload=foreign_descriptor,
            plan_payload=foreign_plan_payload,
            manifest_payload=manifest_payload,
        )


def test_cli_is_default_dry_and_injected_backends_never_attest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinned_python_size = installer.PYTHON_EXECUTABLE_SIZE
    pinned_python_sha256 = installer.PYTHON_EXECUTABLE_SHA256
    manifest = _fixture_bundle(monkeypatch)
    plan = _plan_for(manifest)
    assert executor.parse_executor_args([]).apply is False
    with pytest.raises(executor.BrokerExecutorError, match="CLI_APPLY_EXACT"):
        executor.parse_executor_args(["--apply", "--plan-digest", _digest("plan")])
    parsed = executor.parse_executor_args(
        ["--apply", "--plan-digest", _digest("plan"), "--bundle-digest", _digest("bundle")]
    )
    assert parsed.apply is True

    class SpoofBackend:
        operation_roster_sha256 = installer.backend_roster_digest()
        simulation = False

        def apply(self, step):
            return len(installer.MACOS_BACKEND_OPERATION_ROSTER[step["id"]])

        def rollback(self, _rollback_id, _details):
            return 1

    result = executor.execute_install_plan(
        plan,
        apply=True,
        supplied_plan_digest=installer.plan_digest(plan),
        euid=0,
        backend=SpoofBackend(),
        journal=_MemoryJournal(),
        bundle_manifest=manifest,
    )
    assert result["status"] == "simulated-apply" and "applied_evidence" not in result
    with pytest.raises(executor.BrokerExecutorError, match="BOOTSTRAP_RUNTIME_PROVENANCE_REQUIRED"):
        executor._verify_bootstrap_runtime_provenance()

    pinned_python = ROOT / ".venv" / "bin" / "python3"
    pinned_bytes = pinned_python.read_bytes()
    assert len(pinned_bytes) == pinned_python_size
    assert "sha256:" + hashlib.sha256(pinned_bytes).hexdigest() == pinned_python_sha256
    probe = subprocess.run(
        [
            "/usr/bin/env",
            "-i",
            f"PATH={installer.BOOTSTRAP_STERILE_PATH}",
            str(pinned_python),
            "-I",
            "-B",
            "-c",
            "import json,os;print(json.dumps(dict(os.environ),sort_keys=True))",
        ],
        check=True,
        cwd="/",
        capture_output=True,
    )
    post_exec_environment = json.loads(probe.stdout)
    assert set(post_exec_environment) == {"PATH", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}
    normalized = dict(post_exec_environment)
    executor._scrub_bootstrap_runtime_environment(normalized, effective_uid=os.geteuid())
    assert normalized == {"PATH": installer.BOOTSTRAP_STERILE_PATH}
    invalid_environments = []
    for key, value in (
        ("INJECTED", "1"),
        ("LC_CTYPE", "en_US.UTF-8"),
        ("__CF_USER_TEXT_ENCODING", f"0x{os.geteuid() + 1:X}:0x0:0x4"),
        ("__CF_USER_TEXT_ENCODING", f"0x{os.geteuid():X}:0x0:0x400000000"),
    ):
        candidate = dict(post_exec_environment)
        candidate[key] = value
        invalid_environments.append(candidate)
    invalid_environments.append({"PATH": installer.BOOTSTRAP_STERILE_PATH})
    for invalid in invalid_environments:
        with pytest.raises(executor.BrokerExecutorError, match="RUNTIME_ENVIRONMENT_INVALID"):
            executor._scrub_bootstrap_runtime_environment(
                invalid,
                effective_uid=os.geteuid(),
            )


def test_transition_journal_hash_chain_torn_tail_and_single_session(tmp_path: Path) -> None:
    parent = tmp_path / "journal-parent"
    parent.mkdir(mode=0o700)
    leaf = parent / "install.bin"
    leaf.touch(mode=0o600)
    journal = executor.FileTransitionJournal(leaf.resolve(), require_root=False)
    with journal.session() as locked:
        executor._transition(
            locked,
            transaction_id=1,
            event="transaction-start",
            plan_sha256=_digest("plan"),
            bundle_sha256=_digest("bundle"),
            bundle_file_sha256=_digest("raw"),
            step_id=None,
        )
        executor._transition(
            locked,
            transaction_id=1,
            event="recovery-complete",
            plan_sha256=_digest("plan"),
            bundle_sha256=_digest("bundle"),
            bundle_file_sha256=_digest("raw"),
            step_id=None,
        )
        records = locked.records()
    assert [row["record_sequence"] for row in records] == [1, 2]
    assert records[1]["previous_record_sha256"] == records[0]["record_sha256"]
    with leaf.open("ab") as stream:
        stream.write(b"\x00\x00\x00\x10torn")
    with pytest.raises(executor.BrokerExecutorError, match="TORN"):
        journal.records()
    assert len(journal.records(repair_torn_tail=True)) == 2


def test_exact_macos_operation_roster_and_launchd_absence_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _fixture_bundle(monkeypatch)
    plan = _plan_for(manifest)
    backend, model = _stateful_exact_backend(manifest)
    journal = _MemoryJournal()
    result = executor._execute_install_plan_locked(
        plan,
        steps=plan["steps"],
        digest=installer.plan_digest(plan),
        frozen_bundle=manifest,
        backend=backend,
        journal=journal,
        attestation_allowed=True,
    )
    expected = [
        (step["id"], unit)
        for step in plan["steps"]
        for operation in installer.MACOS_BACKEND_OPERATION_ROSTER[step["id"]]
        for unit in backend.operation_units(step["id"], operation)
    ]
    assert result["status"] == "applied"
    assert model["effects"] == expected and result["backend_calls"] == len(expected)

    print_payload = f"""system/{installer.LAUNCHER_PLIST_LABEL} = {{
path = {installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"]}
program = {installer.PRIVILEGED_HELPER_TOOL}
state = running
pid = 4242
arguments = {{
{installer.PRIVILEGED_HELPER_TOOL}
}}
environment = {{
PATH => /usr/bin:/bin
{installer.LAUNCHD_PACKAGE_INSTANCE_KEY} => {installer.LAUNCHD_PACKAGE_INSTANCE}
}}
}}
""".encode()
    assert executor.MacOSInstallBackend._parse_launchd_print_identity(
        print_payload,
        installer.LAUNCHER_PLIST_LABEL,
    ) == {
        "label": installer.LAUNCHER_PLIST_LABEL,
        "path": installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
        "program": installer.PRIVILEGED_HELPER_TOOL,
        "program_arguments": [installer.PRIVILEGED_HELPER_TOOL],
        "package_instance": installer.LAUNCHD_PACKAGE_INSTANCE,
        "state": "running",
        "pid": 4242,
    }
    with pytest.raises(executor.BrokerExecutorError, match="LAUNCHD_PRINT_INVALID"):
        executor.MacOSInstallBackend._parse_launchd_print_identity(
            b"foreign-prefix " + print_payload,
            installer.LAUNCHER_PLIST_LABEL,
        )
    registered_not_running = print_payload.replace(
        b"state = running\npid = 4242\n",
        b"state = waiting\n",
    )
    registration = executor.MacOSInstallBackend.__new__(executor.MacOSInstallBackend)
    registration_identity = {
        "kind": "launchd-registration",
        "label": installer.LAUNCHER_PLIST_LABEL,
        "program_arguments": [installer.PRIVILEGED_HELPER_TOOL],
        "package_instance": installer.LAUNCHD_PACKAGE_INSTANCE,
        "plist_semantics_sha256": _digest("launcher-plist-semantics"),
        "plist": {"kind": "file", "path": installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"]},
    }
    registration._launchd_plist_identity = MethodType(
        lambda self, label, plist: copy.deepcopy(registration_identity),
        registration,
    )
    registration._run = MethodType(
        lambda self, argv: registered_not_running,
        registration,
    )
    assert (
        registration._launchd_job_receipt(
            installer.LAUNCHER_PLIST_LABEL,
            installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"],
        )
        == registration_identity
    )
    with pytest.raises(executor.BrokerExecutorError, match="SERVICE_NOT_LIVE"):
        registration._verify_service_live(installer.LAUNCHER_PLIST_LABEL)

    kickstart_operation = "launchctl-kickstart-launcher-after-authority"

    def demand_probe(mode: str):
        probe = executor.MacOSInstallBackend.__new__(executor.MacOSInstallBackend)
        probe._pending_operation_intents = {}
        probe._LAUNCHD_POLL_ATTEMPTS = 2
        probe._LAUNCHD_POLL_INTERVAL_SECONDS = 0
        state = {"live": False}
        calls: list[tuple[str, ...]] = []
        probe._active_authority_sha256 = lambda: _digest("active-authority")
        probe._launchd_registered = MethodType(lambda self, label: True, probe)
        probe._launchd_plist_identity = MethodType(
            lambda self, label, plist: copy.deepcopy(registration_identity),
            probe,
        )

        def run(self, argv):
            vector = tuple(argv)
            calls.append(vector)
            if vector[1] == "print":
                if mode == "foreign":
                    return print_payload.replace(
                        installer.PRIVILEGED_HELPER_TOOL.encode(),
                        b"/bin/foreign-service",
                    )
                return print_payload if state["live"] else registered_not_running
            if vector[1] == "kickstart":
                if mode == "failure":
                    raise executor.BrokerExecutorError("MACOS_BACKEND_COMMAND_FAILED")
                if mode != "waiting":
                    state["live"] = True
                return b""
            raise AssertionError(vector)

        probe._run = MethodType(run, probe)
        return probe, state, calls

    foreign_demand, _state, foreign_calls = demand_probe("foreign")
    with pytest.raises(executor.BrokerExecutorError, match="JOB_IDENTITY_MISMATCH"):
        foreign_demand.operation_intent("register-authority", kickstart_operation)
    assert not any(call[1] == "kickstart" for call in foreign_calls)

    failed_demand, _state, failed_calls = demand_probe("failure")
    failed_demand.operation_intent("register-authority", kickstart_operation)
    with pytest.raises(executor.BrokerExecutorError, match="COMMAND_FAILED"):
        failed_demand.apply_operation("register-authority", kickstart_operation)
    assert [call[1] for call in failed_calls].count("kickstart") == 1

    waiting_demand, waiting_state, waiting_calls = demand_probe("waiting")
    waiting_intent = waiting_demand.operation_intent("register-authority", kickstart_operation)
    with pytest.raises(executor.BrokerExecutorError, match="SERVICE_START_TIMEOUT"):
        waiting_demand.apply_operation("register-authority", kickstart_operation)
    assert [call[1] for call in waiting_calls].count("kickstart") == 1
    assert (
        waiting_demand.reconcile_operation(
            "register-authority",
            kickstart_operation,
            waiting_intent,
        ).status
        == "not-applied"
    )
    waiting_state["live"] = True
    assert (
        waiting_demand.reconcile_operation(
            "register-authority",
            kickstart_operation,
            waiting_intent,
        ).status
        == "owned-applied"
    )

    race = executor.MacOSInstallBackend.__new__(executor.MacOSInstallBackend)
    race._pending_operation_intents = {}
    registered = {"value": False}
    bootout_calls: list[tuple[str, ...]] = []
    race._launchd_registered = MethodType(lambda self, label: registered["value"], race)
    race._launchd_plist_identity = MethodType(
        lambda self, label, plist: {
            "kind": "launchd-registration",
            "label": label,
            "program_arguments": [installer.PRIVILEGED_HELPER_TOOL],
            "package_instance": installer.LAUNCHD_PACKAGE_INSTANCE,
            "plist": {"kind": "file", "path": plist, "dev": 1, "ino": 2},
        },
        race,
    )
    race._run = MethodType(lambda self, argv: bootout_calls.append(tuple(argv)) or b"", race)
    race._verify_launchd_slots_free()
    intent = race.operation_intent("bootstrap-launcher", "launchctl-bootstrap-launcher")
    assert intent["targets"][0]["label"] == installer.LAUNCHER_PLIST_LABEL
    assert intent["targets"][0]["action"] == "bootstrap"
    registered["value"] = True
    with pytest.raises(executor.BrokerExecutorError, match="LAUNCHD_LABEL_PREEXISTS"):
        race._perform("launchctl-bootstrap-launcher", "bootstrap-launcher")
    with pytest.raises(executor.BrokerExecutorError, match="LAUNCHD_OWNERSHIP_AMBIGUOUS"):
        race.reconcile_operation("bootstrap-launcher", "launchctl-bootstrap-launcher", intent)
    assert not any(len(argv) > 1 and argv[1] == "bootout" for argv in bootout_calls)

    # Full journal replay: our bootstrap succeeds, SIGKILL lands before the
    # operation receipt, recovery structurally adopts only that exact job,
    # rolls it back, and a fresh transaction can install successfully.
    own_backend, own_model = _stateful_exact_backend(manifest)
    fixture_intent = own_backend.operation_intent
    fixture_apply = own_backend.apply_operation
    fixture_reconcile = own_backend.reconcile_operation
    fixture_rollback = own_backend.rollback
    launcher_plist = installer.EXPECTED_ARTIFACT_PATHS["launcher-plist"]
    launcher_bytes = (
        ROOT / "packaging" / "launchd" / f"{installer.LAUNCHER_PLIST_LABEL}.plist.in"
    ).read_bytes()
    launcher_receipt = {
        "kind": "file",
        "path": launcher_plist,
        "mode": stat.S_IFREG | 0o644,
        "uid": 0,
        "gid": 0,
        "dev": 17,
        "ino": 23,
        "nlink": 1,
        "size": len(launcher_bytes),
        "sha256": "sha256:" + hashlib.sha256(launcher_bytes).hexdigest(),
    }
    monkeypatch.setattr(
        executor,
        "secure_read",
        lambda path, *_args, **_kwargs: (
            launcher_bytes
            if str(path) == launcher_plist
            else (_ for _ in ()).throw(AssertionError(f"unexpected secure_read:{path}"))
        ),
    )
    own_backend._measure_receipt_path = MethodType(
        lambda self, path: (
            copy.deepcopy(launcher_receipt)
            if path == launcher_plist
            else (_ for _ in ()).throw(AssertionError(f"unexpected measure:{path}"))
        ),
        own_backend,
    )
    own_registered = {"value": False, "crash_after_bootstrap": True}
    own_calls: list[tuple[str, ...]] = []
    own_backend._launchd_registered = MethodType(
        lambda self, label: (
            own_registered["value"] if label == installer.LAUNCHER_PLIST_LABEL else False
        ),
        own_backend,
    )

    def own_launchctl(self, argv):
        vector = tuple(argv)
        own_calls.append(vector)
        if vector[1] == "bootstrap":
            own_registered["value"] = True
            if own_registered["crash_after_bootstrap"]:
                own_registered["crash_after_bootstrap"] = False
                raise SystemExit("launchd-success-before-operation-receipt")
            return b""
        if vector[1] == "bootout":
            own_registered["value"] = False
            return b""
        if vector[1] == "print":
            return print_payload
        raise AssertionError(vector)

    own_backend._run = MethodType(own_launchctl, own_backend)

    def own_intent(self, step_id, operation):
        if (step_id, operation) == ("bootstrap-launcher", "launchctl-bootstrap-launcher"):
            return executor.MacOSInstallBackend.operation_intent(self, step_id, operation)
        return fixture_intent(step_id, operation)

    def own_apply(self, step_id, operation):
        if (step_id, operation) == ("bootstrap-launcher", "launchctl-bootstrap-launcher"):
            return executor.MacOSInstallBackend.apply_operation(self, step_id, operation)
        return fixture_apply(step_id, operation)

    def own_reconcile(self, step_id, operation, operation_intent):
        if (step_id, operation) == ("bootstrap-launcher", "launchctl-bootstrap-launcher"):
            return executor.MacOSInstallBackend.reconcile_operation(
                self,
                step_id,
                operation,
                operation_intent,
            )
        return fixture_reconcile(step_id, operation, operation_intent)

    def own_rollback(self, rollback_id, details):
        if rollback_id == "stop-launcher":
            return executor.MacOSInstallBackend.rollback(self, rollback_id, details)
        return fixture_rollback(rollback_id, details)

    own_backend.operation_intent = MethodType(own_intent, own_backend)
    own_backend.apply_operation = MethodType(own_apply, own_backend)
    own_backend.reconcile_operation = MethodType(own_reconcile, own_backend)
    own_backend.rollback = MethodType(own_rollback, own_backend)
    own_journal = _MemoryJournal()
    with pytest.raises(SystemExit, match="launchd-success-before-operation-receipt"):
        executor._execute_install_plan_locked(
            plan,
            steps=plan["steps"],
            digest=installer.plan_digest(plan),
            frozen_bundle=manifest,
            backend=own_backend,
            journal=own_journal,
            attestation_allowed=True,
        )
    assert own_journal.rows[-1]["payload"]["event"] == "operation-start"
    assert own_journal.rows[-1]["payload"]["operation_id"] == "launchctl-bootstrap-launcher"
    recovered = executor._recover_install_plan_locked(
        plan,
        manifest,
        backend=own_backend,
        journal=own_journal,
    )
    assert recovered["status"] == "rolled-back" and own_registered["value"] is False
    assert any(call[1] == "print" for call in own_calls)
    assert any(call[1] == "bootout" for call in own_calls)
    retry = executor._execute_install_plan_locked(
        plan,
        steps=plan["steps"],
        digest=installer.plan_digest(plan),
        frozen_bundle=manifest,
        backend=own_backend,
        journal=own_journal,
        attestation_allowed=True,
    )
    assert retry["status"] == "applied" and own_registered["value"] is True

    # The authority-last demand start has the same durable crash boundary:
    # exact live identity is adopted after kickstart success, rolled back, and
    # the retained journal permits a fresh transaction to retry.
    demand_backend, _demand_model = _stateful_exact_backend(manifest)
    demand_fixture_intent = demand_backend.operation_intent
    demand_fixture_apply = demand_backend.apply_operation
    demand_fixture_reconcile = demand_backend.reconcile_operation
    demand_fixture_rollback = demand_backend.rollback
    demand_backend._pending_operation_intents = {}
    demand_backend._active_authority_sha256 = lambda: _digest("active-authority")
    demand_backend._launchd_registered = MethodType(lambda self, label: True, demand_backend)
    demand_backend._launchd_plist_identity = MethodType(
        lambda self, label, plist: copy.deepcopy(registration_identity),
        demand_backend,
    )
    demand_state = {"live": False, "crash_after_kickstart": True}
    demand_calls: list[tuple[str, ...]] = []

    def demand_launchctl(self, argv):
        vector = tuple(argv)
        demand_calls.append(vector)
        if vector[1] == "print":
            return print_payload if demand_state["live"] else registered_not_running
        if vector[1] == "kickstart":
            demand_state["live"] = True
            if demand_state["crash_after_kickstart"]:
                demand_state["crash_after_kickstart"] = False
                raise SystemExit("kickstart-success-before-operation-receipt")
            return b""
        raise AssertionError(vector)

    demand_backend._run = MethodType(demand_launchctl, demand_backend)

    def demand_intent(self, step_id, operation):
        if (step_id, operation) == ("register-authority", kickstart_operation):
            return executor.MacOSInstallBackend.operation_intent(self, step_id, operation)
        return demand_fixture_intent(step_id, operation)

    def demand_apply(self, step_id, operation):
        if (step_id, operation) == ("register-authority", kickstart_operation):
            return executor.MacOSInstallBackend.apply_operation(self, step_id, operation)
        return demand_fixture_apply(step_id, operation)

    def demand_reconcile(self, step_id, operation, operation_intent):
        if (step_id, operation) == ("register-authority", kickstart_operation):
            return executor.MacOSInstallBackend.reconcile_operation(
                self,
                step_id,
                operation,
                operation_intent,
            )
        return demand_fixture_reconcile(step_id, operation, operation_intent)

    def demand_rollback(self, rollback_id, details):
        if rollback_id == "stop-launcher":
            demand_state["live"] = False
        return demand_fixture_rollback(rollback_id, details)

    demand_backend.operation_intent = MethodType(demand_intent, demand_backend)
    demand_backend.apply_operation = MethodType(demand_apply, demand_backend)
    demand_backend.reconcile_operation = MethodType(demand_reconcile, demand_backend)
    demand_backend.rollback = MethodType(demand_rollback, demand_backend)
    demand_journal = _MemoryJournal()
    with pytest.raises(SystemExit, match="kickstart-success-before-operation-receipt"):
        executor._execute_install_plan_locked(
            plan,
            steps=plan["steps"],
            digest=installer.plan_digest(plan),
            frozen_bundle=manifest,
            backend=demand_backend,
            journal=demand_journal,
            attestation_allowed=True,
        )
    assert demand_journal.rows[-1]["payload"]["operation_id"] == kickstart_operation
    demand_recovered = executor._recover_install_plan_locked(
        plan,
        manifest,
        backend=demand_backend,
        journal=demand_journal,
    )
    assert demand_recovered["status"] == "rolled-back" and demand_state["live"] is False
    stop_launcher = next(row for row in _demand_model["rollbacks"] if row[0] == "stop-launcher")
    assert stop_launcher[1] == ("bootstrap-launcher",)
    demand_retry = executor._execute_install_plan_locked(
        plan,
        steps=plan["steps"],
        digest=installer.plan_digest(plan),
        frozen_bundle=manifest,
        backend=demand_backend,
        journal=demand_journal,
        attestation_allowed=True,
    )
    assert demand_retry["status"] == "applied" and demand_state["live"] is True
    assert [call[1] for call in demand_calls].count("kickstart") == 2


def test_crash_recovery_uses_operation_receipts_and_typed_authority_cas(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _fixture_bundle(monkeypatch)
    plan = _plan_for(manifest)
    probe = executor.MacOSInstallBackend(manifest)
    crash_unit = probe.operation_units(
        "install-broker-code", "install-root-owned-python-service-closure"
    )[0]
    backend, model = _stateful_exact_backend(manifest, crash_at=("install-broker-code", crash_unit))
    journal = _MemoryJournal()
    with pytest.raises(SystemExit, match="injected-crash"):
        executor._execute_install_plan_locked(
            plan,
            steps=plan["steps"],
            digest=installer.plan_digest(plan),
            frozen_bundle=manifest,
            backend=backend,
            journal=journal,
            attestation_allowed=True,
        )
    assert journal.rows[-1]["payload"]["event"] == "operation-start"
    assert (
        executor._recover_install_plan_locked(plan, manifest, backend=backend, journal=journal)[
            "status"
        ]
        == "rolled-back"
    )
    assert any(row[0] == "remove-installed-code-children-first" for row in model["rollbacks"])
    partial = next(
        row["payload"]["ownership_receipt"]
        for row in journal.rows
        if row["payload"]["event"] == "operation-complete"
        and row["payload"]["operation_id"] == crash_unit
    )
    assert partial["operation_id"] == crash_unit

    registry = tmp_path / "registry"
    registry.mkdir()
    candidate = registry / ".candidate"
    active = registry / "active.json"
    candidate.write_bytes(b"{}")
    candidate.chmod(0o444)
    info = candidate.stat()
    monkeypatch.setattr(installer, "AUTHORITY_CANDIDATE_PATH", str(candidate))
    monkeypatch.setattr(installer, "AUTHORITY_REGISTRY_PATH", str(active))
    monkeypatch.setattr(executor, "_canonical_document", lambda payload, label: {})
    monkeypatch.setattr(executor.protocol, "validate_authority", lambda value: value)
    monkeypatch.setattr(executor.protocol, "authority_hash", lambda value: _digest("authority"))
    monkeypatch.setattr(executor, "secure_read", lambda *args, **kwargs: b"{}")
    real_fstat = os.fstat

    class RootStat:
        def __init__(self, original):
            self._original = original
            self.st_uid = 0
            self.st_gid = 0
            self.st_mode = original.st_mode

        def __getattr__(self, name):
            return getattr(self._original, name)

    monkeypatch.setattr(executor.os, "fstat", lambda fd: RootStat(real_fstat(fd)))
    cas = executor.MacOSInstallBackend.__new__(executor.MacOSInstallBackend)
    cas_intent = {
        "kind": "authority-cas-intent",
        "active_path": str(active),
        "authority_sha256": _digest("authority"),
        "candidate": {"dev": info.st_dev, "ino": info.st_ino},
    }
    assert cas.activation_receipt_from_intent(cas_intent).status == "not-applied"
    os.link(candidate, active)
    assert (
        cas.activation_receipt_from_intent(cas_intent).status == "cleaned" and not active.exists()
    )
    os.link(candidate, active)
    candidate.unlink()
    cas._operation_receipt = MethodType(lambda self, step, operation: {"owned": True}, cas)
    outcome = cas.activation_receipt_from_intent(cas_intent)
    assert outcome.status == "owned-applied" and outcome.ownership_receipt == {"owned": True}


def test_rollback_crash_is_idempotent_and_fresh_retry_retains_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _fixture_bundle(monkeypatch)
    plan = _plan_for(manifest)
    probe = executor.MacOSInstallBackend(manifest)
    crash_unit = probe.operation_units(
        "install-broker-code", "install-root-owned-python-service-closure"
    )[0]
    backend, model = _stateful_exact_backend(manifest, crash_at=("install-broker-code", crash_unit))
    journal = _MemoryJournal()
    with pytest.raises(SystemExit):
        executor._execute_install_plan_locked(
            plan,
            steps=plan["steps"],
            digest=installer.plan_digest(plan),
            frozen_bundle=manifest,
            backend=backend,
            journal=journal,
            attestation_allowed=True,
        )
    model["rollback_crash_armed"] = True
    with pytest.raises(SystemExit, match="rollback-effect"):
        executor._recover_install_plan_locked(plan, manifest, backend=backend, journal=journal)
    assert (
        executor._recover_install_plan_locked(plan, manifest, backend=backend, journal=journal)[
            "status"
        ]
        == "rolled-back"
    )
    retry = executor._execute_install_plan_locked(
        plan,
        steps=plan["steps"],
        digest=installer.plan_digest(plan),
        frozen_bundle=manifest,
        backend=backend,
        journal=journal,
        attestation_allowed=True,
    )
    assert retry["status"] == "applied"
    segments = executor._journal_segments(journal.records())
    assert [segment[0]["transaction_id"] for segment in segments] == [1, 2]
    assert (
        segments[0][-1]["event"] == "recovery-complete"
        and segments[1][-1]["event"] == "plan-complete"
    )
    assert sum(row[0] == "remove-installed-code-children-first" for row in model["rollbacks"]) == 2


def test_second_apply_remeasures_dynamic_publications_and_rejects_orphans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _fixture_bundle(monkeypatch)
    plan = _plan_for(manifest)
    plist_specs = {
        installer.LAUNCHER_PLIST_LABEL: (
            "launcher-plist",
            installer.PRIVILEGED_HELPER_TOOL,
        ),
        installer.ANCHOR_PLIST_LABEL: (
            "anchor-plist",
            f"{installer.APP_SUPPORT_ROOT}/anchor/bin/w3-anchor-socket-shim",
        ),
        installer.BROKER_PLIST_LABEL: ("broker-plist", installer.BROKER_PROGRAM),
    }
    plist_payloads = {
        installer.EXPECTED_ARTIFACT_PATHS[role]: (
            ROOT / "packaging" / "launchd" / f"{label}.plist.in"
        ).read_bytes()
        for label, (role, _program) in plist_specs.items()
    }
    monkeypatch.setattr(
        executor,
        "secure_read",
        lambda path, *_args, **_kwargs: plist_payloads[str(path)],
    )

    def bind_live_final(
        exact_backend: executor.MacOSInstallBackend,
        state_model: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        jobs = {label: {} for label in plist_specs}
        fixture_apply = exact_backend.apply_operation

        def measured(self, path):
            payload = plist_payloads[path]
            return {
                "kind": "file",
                "path": path,
                "mode": stat.S_IFREG | 0o644,
                "uid": 0,
                "gid": 0,
                "dev": 31,
                "ino": 37 + len(path),
                "nlink": 1,
                "size": len(payload),
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }

        def launchctl_print(self, argv):
            assert tuple(argv[:2]) == ("/bin/launchctl", "print")
            label = str(argv[2]).removeprefix("system/")
            role, expected_program = plist_specs[label]
            mutation = jobs[label]
            program = str(mutation.get("program", expected_program))
            arguments = mutation.get("program_arguments", [expected_program])
            package_instance = str(
                mutation.get("package_instance", installer.LAUNCHD_PACKAGE_INSTANCE)
            )
            state = str(mutation.get("state", "running"))
            pid = int(mutation.get("pid", 5000 + len(label)))
            path = installer.EXPECTED_ARTIFACT_PATHS[role]
            argument_rows = "\n".join(str(value) for value in arguments)
            return f"""system/{label} = {{
path = {path}
program = {program}
state = {state}
pid = {pid}
arguments = {{
{argument_rows}
}}
environment = {{
PATH => /usr/bin:/bin
{installer.LAUNCHD_PACKAGE_INSTANCE_KEY} => {package_instance}
}}
}}
""".encode()

        def verify_final(self):
            for label in plist_specs:
                executor.MacOSInstallBackend._verify_service_live(self, label)
            state_model["final_checks"].append(int(state_model["dynamic_revision"]))
            return dict(self._applied_evidence)

        def apply_with_final(self, step_id, operation):
            if operation == "verify-authority-config-and-services-live":
                self.verify_final_postconditions()
            return fixture_apply(step_id, operation)

        exact_backend._measure_receipt_path = MethodType(measured, exact_backend)
        exact_backend._run = MethodType(launchctl_print, exact_backend)
        exact_backend.verify_final_postconditions = MethodType(verify_final, exact_backend)
        exact_backend.apply_operation = MethodType(apply_with_final, exact_backend)
        return jobs

    foreign_backend, foreign_model = _stateful_exact_backend(manifest)
    foreign_jobs = bind_live_final(foreign_backend, foreign_model)
    foreign_jobs[installer.BROKER_PLIST_LABEL]["program"] = "/bin/foreign-service"
    with pytest.raises(executor.BrokerExecutorError, match="INSTALL_TRANSACTION_FAILED"):
        executor._execute_install_plan_locked(
            plan,
            steps=plan["steps"],
            digest=installer.plan_digest(plan),
            frozen_bundle=manifest,
            backend=foreign_backend,
            journal=_MemoryJournal(),
            attestation_allowed=True,
        )

    backend, model = _stateful_exact_backend(manifest)
    jobs = bind_live_final(backend, model)
    journal = _MemoryJournal()
    first = executor._execute_install_plan_locked(
        plan,
        steps=plan["steps"],
        digest=installer.plan_digest(plan),
        frozen_bundle=manifest,
        backend=backend,
        journal=journal,
        attestation_allowed=True,
    )
    assert first["status"] == "applied"
    model["dynamic_revision"] = 1
    second = executor._execute_install_plan_locked(
        plan,
        steps=plan["steps"],
        digest=installer.plan_digest(plan),
        frozen_bundle=manifest,
        backend=backend,
        journal=journal,
        attestation_allowed=True,
    )
    assert second["status"] == "already-complete"
    assert model["final_checks"] == [0, 1]
    jobs[installer.BROKER_PLIST_LABEL]["program_arguments"] = ["/bin/foreign-service"]
    with pytest.raises(executor.BrokerExecutorError, match="SERVICE_NOT_LIVE"):
        executor._execute_install_plan_locked(
            plan,
            steps=plan["steps"],
            digest=installer.plan_digest(plan),
            frozen_bundle=manifest,
            backend=backend,
            journal=journal,
            attestation_allowed=True,
        )
    jobs[installer.BROKER_PLIST_LABEL].clear()
    model["dynamic_revision"] = 2
    third = executor._execute_install_plan_locked(
        plan,
        steps=plan["steps"],
        digest=installer.plan_digest(plan),
        frozen_bundle=manifest,
        backend=backend,
        journal=journal,
        attestation_allowed=True,
    )
    assert third["status"] == "already-complete" and model["final_checks"] == [0, 1, 2]

    exact = executor.MacOSInstallBackend.__new__(executor.MacOSInstallBackend)
    exact._install_rows = {f"{installer.APP_SUPPORT_ROOT}/code.py": {}}
    exact._directories = {
        installer.APP_SUPPORT_ROOT: (0, 0, 0o755),
        installer.PUBLICATION_ACTIVE: (installer.BROKER_UID, installer.BROKER_GID, 0o700),
        installer.RUNS_ACTIVE: (installer.RUNNER_UID, installer.RUNNER_GID, 0o700),
    }
    dynamic = f"{installer.PUBLICATION_ACTIVE}/1-{'a' * 64}.json"
    files = {
        installer.INSTALL_BUNDLE_MANIFEST_PATH,
        installer.BROKER_LEDGER_PATH,
        installer.PUBLIC_RECEIPT_JOURNAL_PATH,
        installer.ANCHOR_LOG_PATH,
        installer.SIGNING_KEY_PATH,
        installer.PUBLIC_KEY_REGISTRY_PATH,
        installer.ANCHOR_CONFIG_PATH,
        installer.AUTHORITY_REGISTRY_PATH,
        dynamic,
        f"{installer.APP_SUPPORT_ROOT}/code.py",
    }
    directories = set(exact._directories)
    monkeypatch.setattr(exact, "_walk_paths", lambda root: (set(files), set(directories)))
    exact._verify_managed_tree_exact(complete=True, dynamic_publications={dynamic})
    files.add(f"{installer.PUBLICATION_ACTIVE}/.orphan.tmp")
    with pytest.raises(executor.BrokerExecutorError, match="MANAGED_TREE_EXTRA"):
        exact._verify_managed_tree_exact(complete=True, dynamic_publications={dynamic})


def test_seed_registry_authority_swaps_quarantine_and_nonattestation_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seed_a = bytes(range(32))
    seed_b = bytes(reversed(range(32)))

    def signing(seed: bytes) -> tuple[dict[str, object], bytes]:
        public = protocol.ed25519.derive_public_key(seed)
        key_id = protocol.ed25519.mode_scoped_key_id(
            public, mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
        )
        return (
            {
                "algorithm": protocol.PRODUCTION_ALGORITHM,
                "key_id": key_id,
                "public_key": protocol.ed25519.encode_public_key(public),
            },
            public,
        )

    signing_a, public_a = signing(seed_a)
    signing_b, public_b = signing(seed_b)

    def registry_payload(signing_row: dict[str, object]) -> bytes:
        return protocol.canonical_bytes(
            {
                "schema_version": 1,
                "kind": executor.PUBLIC_KEY_REGISTRY_KIND,
                "keys": [{"mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC, **signing_row}],
            }
        )

    installed = {
        installer.SIGNING_KEY_PATH: seed_a,
        installer.PUBLIC_KEY_REGISTRY_PATH: registry_payload(signing_a),
    }
    monkeypatch.setattr(
        executor, "secure_read", lambda path, policy, **kwargs: installed[str(path)]
    )
    executor.MacOSInstallBackend._verify_final_key_binding({"signing": signing_a})
    installed[installer.SIGNING_KEY_PATH] = seed_b
    with pytest.raises(executor.BrokerExecutorError, match="FINAL_KEY_REGISTRY_MISMATCH"):
        executor.MacOSInstallBackend._verify_final_key_binding({"signing": signing_a})
    installed[installer.SIGNING_KEY_PATH] = seed_a
    installed[installer.PUBLIC_KEY_REGISTRY_PATH] = registry_payload(signing_b)
    with pytest.raises(executor.BrokerExecutorError, match="FINAL_KEY_REGISTRY_MISMATCH"):
        executor.MacOSInstallBackend._verify_final_key_binding({"signing": signing_a})
    installed[installer.PUBLIC_KEY_REGISTRY_PATH] = registry_payload(signing_a)
    with pytest.raises(executor.BrokerExecutorError, match="FINAL_KEY_REGISTRY_MISMATCH"):
        executor.MacOSInstallBackend._verify_final_key_binding({"signing": signing_b})
    assert public_a != public_b

    exact = executor.MacOSInstallBackend.__new__(executor.MacOSInstallBackend)
    for name, payload in (
        ("seed", seed_a),
        ("registry", b"same-registry"),
        ("authority", b"same-authority"),
    ):
        source = tmp_path / name
        source.write_bytes(payload)
        source.chmod(0o440 if name == "seed" else 0o444)
        before = source.stat()
        row = {
            "kind": "file",
            "path": str(source),
            "uid": before.st_uid,
            "gid": before.st_gid,
            "mode": before.st_mode,
            "dev": before.st_dev,
            "ino": before.st_ino,
            "nlink": 1,
            "size": len(payload),
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }
        parent_fd, fd, opened = exact._open_receipt_owned_file(row, str(source))
        source.unlink()
        source.write_bytes(payload)
        source.chmod(stat.S_IMODE(before.st_mode))
        try:
            with pytest.raises(executor.BrokerExecutorError, match="ROLLBACK_POSTIMAGE_MISMATCH"):
                exact._recheck_held_owned_file(
                    row,
                    str(source),
                    parent_fd,
                    fd,
                    opened,
                    uid=before.st_uid,
                    gid=before.st_gid,
                    mode=stat.S_IMODE(before.st_mode),
                )
        finally:
            os.close(fd)
            os.close(parent_fd)
        assert source.exists()

    schema = json.loads((ROOT / "schemas" / "w3-phase-b-install-bundle.schema.json").read_text())
    assert schema["properties"]["status"]["enum"] == ["awaiting-bootstrap-build", "frozen"]
    assert schema["properties"]["outcome"]["const"] == "PHASE_B_INSTALLABLE_UNEXECUTED"
    brief = (
        ROOT / "orchestra" / "briefs" / "2026-08-23-model1-l70-phase-b-installable-unexecuted.md"
    ).read_text()
    contract = (ROOT / "docs" / "13-protected-execution-broker.md").read_text()
    assert "root-owned `_metisbroker`-group signing seed" in brief
    assert "root:_metisbroker` with mode `0440" in contract
    assert "production `complete` result is denied" in brief
    source_text = Path(__file__).read_text()
    assert sum(line.startswith("def test_") for line in source_text.splitlines()) == 10
