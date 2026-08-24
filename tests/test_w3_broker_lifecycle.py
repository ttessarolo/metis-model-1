from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import os
import plistlib
import stat
import struct
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime import w3_broker_protocol as protocol  # noqa: E402
from runtime import w3_protected_broker as core  # noqa: E402

INSTALLER_PATH = PROJECT_ROOT / "runtime/w3_broker_installer.py"
BROKER_PLIST_PATH = PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-broker.plist.in"
LAUNCHER_PLIST_PATH = PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-launcher.plist.in"
ANCHOR_PLIST_PATH = PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-anchor.plist.in"

RELEASE_DIGEST = "ab" * 32
OLD_RELEASE_DIGEST = "cd" * 32
BUNDLE_DIGEST = "sha256:" + "ef" * 32


def _load_installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("w3_broker_installer_under_test", INSTALLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def installer() -> ModuleType:
    return _load_installer()


@pytest.fixture(scope="module")
def install_plan(installer: ModuleType) -> dict:
    return installer.plan_install(
        {
            "authority_id": installer.AUTHORITY_ID,
            "bundle_sha256": BUNDLE_DIGEST,
            "release_content_roster_sha256": RELEASE_DIGEST,
        }
    )


def _step_map(plan: dict) -> dict:
    return {step["id"]: step for step in plan["steps"]}


def test_distinct_non_root_identities_and_disjoint_writable_roots(
    installer: ModuleType, install_plan: dict
) -> None:
    principals = install_plan["principals"]
    assert principals["ordered_roles"] == ["caller", "broker", "launcher", "runner", "anchor"]
    assert principals["fixed"] == dict(installer.FIXED_PRINCIPALS)
    assert principals["fallback_ids_allowed"] is False
    assert [
        (row["name"], row["uid"], row["gid"])
        for row in install_plan["identity_conflict_preconditions"]
    ] == [
        ("tommasotessarolo", 501, 20),
        ("_metisbroker", 499, 499),
        ("_metisrunner", 498, 498),
        ("_metisanchor", 497, 497),
    ]
    assert all(
        row["on_failure"].startswith("STOP")
        for row in install_plan["identity_conflict_preconditions"]
    )
    for bad in (
        {"broker_principal": "root"},
        {"broker_principal": "0"},
        {"runner_principal": "root"},
        {"anchor_principal": "root"},
        {"broker_principal": "shared", "runner_principal": "shared"},
        {"broker_principal": "other-broker"},
        {"runner_principal": "other-runner"},
        {"anchor_principal": "other-anchor"},
        {"broker_principal": ""},
    ):
        with pytest.raises(installer.InstallerError):
            installer.plan_install(
                {
                    "authority_id": installer.AUTHORITY_ID,
                    "bundle_sha256": BUNDLE_DIGEST,
                    "release_content_roster_sha256": RELEASE_DIGEST,
                    **bad,
                }
            )
    broker_writable = set()
    runner_writable = set()
    anchor_writable = set()
    for entry in install_plan["installed_tree"]:
        if installer.BROKER_PRINCIPAL in entry["writable_by"]:
            broker_writable.add(entry["path"])
        if installer.RUNNER_PRINCIPAL in entry["writable_by"]:
            runner_writable.add(entry["path"])
        if installer.ANCHOR_PRINCIPAL in entry["writable_by"]:
            anchor_writable.add(entry["path"])
        assert (
            len(
                {
                    installer.BROKER_PRINCIPAL,
                    installer.RUNNER_PRINCIPAL,
                    installer.ANCHOR_PRINCIPAL,
                }.intersection(entry["writable_by"])
            )
            <= 1
        )
    assert broker_writable
    assert runner_writable
    assert anchor_writable
    assert broker_writable.isdisjoint(runner_writable | anchor_writable)
    assert runner_writable.isdisjoint(anchor_writable)
    assert all(path.startswith(installer.APP_SUPPORT_ROOT) for path in runner_writable)
    assert not any("broker" in Path(path).parts for path in runner_writable)


def test_install_dependency_order_and_authority_last(
    installer: ModuleType, install_plan: dict
) -> None:
    steps = install_plan["steps"]
    ids = [step["id"] for step in steps]
    assert ids == list(installer.INSTALL_STEP_IDS)
    assert steps[0]["depends_on"] == []
    for index in range(1, len(steps)):
        assert steps[index]["depends_on"] == [ids[index - 1]]
    assert ids[-1] == "register-authority"
    assert ids.index("create-identity-metisbroker") < ids.index("install-broker-code")
    assert ids.index("create-identity-metisrunner") < ids.index("install-broker-code")
    assert ids.index("create-identity-metisanchor") < ids.index("install-broker-code")
    assert ids.index("install-launcher") < ids.index("precreate-durable-leaves")
    assert ids.index("precreate-durable-leaves") < ids.index("verify-installed-ancestry")
    assert ids.index("verify-installed-ancestry") < ids.index("provision-signing-key")
    assert ids.index("provision-signing-key") < ids.index("install-launchd-plists")
    assert ids.index("install-launchd-plists") < ids.index("bootstrap-launcher")
    assert ids.index("bootstrap-launcher") < ids.index("bootstrap-anchor")
    assert ids.index("bootstrap-anchor") < ids.index("bootstrap-broker")
    assert ids.index("bootstrap-broker") < ids.index("register-authority")


def test_root_owned_ancestry_mode_symlink_single_link_verification(
    installer: ModuleType, install_plan: dict
) -> None:
    verify = _step_map(install_plan)["verify-installed-ancestry"]
    assert verify["details"]["checks"] == [
        "root-owned-ancestry",
        "mode-verification",
        "symlink-free",
        "single-link",
        "complete-roster",
        "hash-remeasure",
        "runs-parent-active-inode-binding",
    ]
    tree = install_plan["installed_tree"]
    by_path = {entry["path"]: entry for entry in tree}
    code_paths = (
        installer.APP_SUPPORT_ROOT,
        f"{installer.APP_SUPPORT_ROOT}/broker",
        f"{installer.APP_SUPPORT_ROOT}/runtime",
        installer.RELEASE_ROOT,
        installer.PRIVILEGED_HELPER_TOOL,
        f"{installer.LAUNCH_DAEMONS_DIR}/{installer.BROKER_PLIST_LABEL}.plist",
        f"{installer.LAUNCH_DAEMONS_DIR}/{installer.LAUNCHER_PLIST_LABEL}.plist",
        f"{installer.LAUNCH_DAEMONS_DIR}/{installer.ANCHOR_PLIST_LABEL}.plist",
    )
    for path in code_paths:
        entry = by_path[path]
        assert entry["owner"] == "root" and entry["group"] == "wheel"
        assert entry["writable_by"] == []
        assert "symlink-free" in entry["checks"]
    assert by_path[installer.RELEASE_ROOT]["checks"] == [
        "root-owned-ancestry",
        "symlink-free",
        "single-link",
        "mode-verification",
        "complete-roster-hash",
        "stable-slot-not-content-hash",
    ]
    ledger_parent = by_path[f"{installer.APP_SUPPORT_ROOT}/ledger"]
    assert ledger_parent["owner"] == "root"
    assert ledger_parent["writable_by"] == []
    ledger_leaf = by_path[installer.BROKER_LEDGER_PATH]
    assert ledger_leaf["owner"] == installer.BROKER_PRINCIPAL
    assert ledger_leaf["mode"] == "0600"
    assert ledger_leaf["writable_by"] == [installer.BROKER_PRINCIPAL]
    assert {"precreated-leaf", "root-owned-nonwritable-parent", "single-link"} <= set(
        ledger_leaf["checks"]
    )
    assert by_path[installer.RUNS_PARENT]["owner"] == "root"
    assert by_path[installer.RUNS_PARENT]["group"] == "wheel"
    assert by_path[installer.RUNS_PARENT]["mode"] == "0711"
    assert by_path[installer.RUNS_PARENT]["writable_by"] == []
    assert by_path[installer.RUNS_ACTIVE]["owner"] == installer.RUNNER_PRINCIPAL
    assert by_path[installer.RUNS_ACTIVE]["mode"] == "0700"
    assert "launcher-holds-parent-and-leaf-dirfds" in by_path[installer.RUNS_ACTIVE]["checks"]
    assert by_path[installer.PUBLIC_RECEIPT_JOURNAL_PATH]["owner"] == installer.BROKER_PRINCIPAL
    assert by_path[installer.PUBLIC_RECEIPT_JOURNAL_PATH]["group"] == installer.CALLER_GROUP
    assert by_path[installer.INSTALL_TRANSITION_JOURNAL_PATH]["mode"] == "0600"
    key_step = _step_map(install_plan)["provision-signing-key"]["details"]
    assert key_step["mode"] == "0440"
    assert key_step["owner"] == "root"
    assert key_step["group"] == installer.BROKER_PRINCIPAL
    assert key_step["writable_by"] == []
    assert key_step["reachable_by"] == [installer.BROKER_PRINCIPAL]
    assert "caller" in key_step["unreachable_by"]
    assert installer.RUNNER_PRINCIPAL in key_step["unreachable_by"]
    assert installer.ANCHOR_PRINCIPAL in key_step["unreachable_by"]


def test_plist_fixed_identities_paths_sockets_and_sterile_env(installer: ModuleType) -> None:
    broker = plistlib.loads(BROKER_PLIST_PATH.read_bytes())
    launcher = plistlib.loads(LAUNCHER_PLIST_PATH.read_bytes())
    anchor = plistlib.loads(ANCHOR_PLIST_PATH.read_bytes())
    assert broker["Label"] == installer.BROKER_PLIST_LABEL
    assert broker["UserName"] == installer.BROKER_PRINCIPAL
    assert broker["GroupName"] == installer.BROKER_PRINCIPAL
    assert "UserName" not in launcher and "GroupName" not in launcher
    assert launcher["Label"] == installer.LAUNCHER_PLIST_LABEL
    assert anchor["Label"] == installer.ANCHOR_PLIST_LABEL
    assert anchor["UserName"] == installer.ANCHOR_PRINCIPAL
    assert anchor["GroupName"] == installer.ANCHOR_PRINCIPAL
    assert broker["ProgramArguments"] == [installer.BROKER_PROGRAM]
    assert launcher["ProgramArguments"] == [installer.PRIVILEGED_HELPER_TOOL]
    for plist in (broker, launcher, anchor):
        assert plist["EnvironmentVariables"] == {
            "PATH": "/usr/bin:/bin",
            installer.LAUNCHD_PACKAGE_INSTANCE_KEY: installer.LAUNCHD_PACKAGE_INSTANCE,
        }
        assert "KeepAlive" not in plist
        assert plist["ThrottleInterval"] >= 1
        assert plist["RunAtLoad"] is False
    assert broker["Sockets"]["BrokerListener"] == {
        "SockPathName": installer.BROKER_SOCKET_PATH,
        "SockPathOwner": 501,
        "SockPathGroup": 20,
        "SockPathMode": 0o600,
    }
    assert launcher["Sockets"]["LauncherListener"] == {
        "SockPathName": installer.LAUNCHER_SOCKET_PATH,
        "SockPathOwner": 499,
        "SockPathGroup": 499,
        "SockPathMode": 0o600,
    }
    assert anchor["Sockets"]["AnchorListener"] == {
        "SockPathName": installer.ANCHOR_SOCKET_PATH,
        "SockPathOwner": 501,
        "SockPathGroup": 20,
        "SockPathMode": 0o600,
    }
    assert broker["StandardOutPath"].startswith("/Library/Logs/MetisModel1/broker/")
    assert anchor["StandardOutPath"].startswith("/Library/Logs/MetisModel1/")
    assert "/state/" not in anchor["StandardOutPath"]
    raw = (
        BROKER_PLIST_PATH.read_bytes()
        + LAUNCHER_PLIST_PATH.read_bytes()
        + ANCHOR_PLIST_PATH.read_bytes()
    )
    assert b"/Users/" not in raw
    assert raw.count(installer.LAUNCHD_PACKAGE_INSTANCE_KEY.encode("ascii")) == 3
    assert b"METIS_W3_SIGNING" not in raw and b"PRIVATE_KEY" not in raw


def test_rollback_order_retains_ledger_public_keys_and_evidence(installer: ModuleType) -> None:
    plan = installer.plan_rollback(
        {
            "authority_id": installer.AUTHORITY_ID,
            "bundle_sha256": BUNDLE_DIGEST,
            "release_content_roster_sha256": RELEASE_DIGEST,
        }
    )
    steps = plan["steps"]
    ids = [step["id"] for step in steps]
    assert ids == list(installer.ROLLBACK_STEP_IDS)
    assert ids[0] == "withdraw-authority"
    assert steps[0]["depends_on"] == []
    for index in range(1, len(steps)):
        assert steps[index]["depends_on"] == [ids[index - 1]]
    assert ids.index("stop-broker") < ids.index("stop-launcher")
    assert ids.index("stop-broker") < ids.index("stop-anchor") < ids.index("stop-launcher")
    assert ids.index("archive-durable-evidence") < ids.index("quarantine-signing-key")
    assert ids.index("quarantine-signing-key") < ids.index("remove-mutable-state")
    assert ids.index("remove-mutable-state") < ids.index("remove-installed-code-children-first")
    retained = list(installer.RETAINED_ON_ROLLBACK)
    assert plan["retained"] == retained
    assert "ledger" in retained and "old-public-keys" in retained
    assert "receipt-evidence" in retained and "signed-receipt-journal" in retained
    assert "protected-anchor" in retained and "install-transition-journal" in retained
    step_map = _step_map(plan)
    assert step_map["archive-durable-evidence"]["details"]["never_deleted"] is True
    for removal in ("remove-mutable-state", "remove-installed-code-children-first"):
        assert step_map[removal]["details"].get("excludes", retained) == retained
    targets = step_map["remove-mutable-state"]["details"]["targets"]
    assert not any("ledger" in target or "keys" in target for target in targets)


def test_upgrade_installs_and_verifies_before_activation(installer: ModuleType) -> None:
    config = {
        "authority_id": installer.AUTHORITY_ID,
        "bundle_sha256": BUNDLE_DIGEST,
        "release_content_roster_sha256": RELEASE_DIGEST,
    }
    with pytest.raises(installer.InstallerError):
        installer.plan_upgrade(config)
    with pytest.raises(installer.InstallerError):
        installer.plan_upgrade({**config, "old_release_content_roster_sha256": RELEASE_DIGEST})
    plan = installer.plan_upgrade(
        {**config, "old_release_content_roster_sha256": OLD_RELEASE_DIGEST}
    )
    ids = [step["id"] for step in plan["steps"]]
    assert ids.index("install-new-release") < ids.index("activate-new-release")
    assert ids.index("verify-new-release") < ids.index("activate-new-release")
    assert ids[-1] == "register-authority"
    verify = _step_map(plan)["verify-new-release"]
    assert "hash-remeasure" in verify["details"]["checks"]
    assert "single-link" in verify["details"]["checks"]
    assert plan["old_release_retention"] == "until-no-retained-receipt-depends-on-it"


# The remaining 37 cases are deliberately Phase-A-only.  Their executor is a
# pure in-memory fixture; it never starts a process or handles any payload.


def _digest(seed: str) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _authority(*, release_id: str = "w3-release-v1", release_seed: str = "release") -> dict:
    installed = {
        "broker_code_sha256": _digest("broker"),
        "launcher_sha256": _digest("launcher"),
        "worker_sha256": _digest("worker"),
        "loader_sha256": _digest("loader"),
        "runner_sha256": _digest("runner"),
        "node_sha256": _digest("node"),
    }
    paths = {
        "broker": "broker/main.py",
        "launcher": "launcher/w3",
        "worker": "worker/main.py",
        "loader": "loader/native",
        "runner": "runner/main.py",
        "node": "node/bin",
    }
    parameters, template, resolved = _policy()
    roster = sorted(
        [
            *(
                _row(paths[role], installed[protocol.ROLE_DIGEST_FIELD[role]])
                for role in protocol.INSTALLED_CODE_ROLES
            ),
            _row("release/imported-runtime.mjs", _digest(f"runtime:{release_seed}")),
        ],
        key=lambda row: row["path"],
    )
    return {
        "schema_version": protocol.SCHEMA_VERSION,
        "kind": protocol.KIND_AUTHORITY,
        "authority_id": protocol.AUTHORITY_ID,
        "mode": protocol.MODE_SYNTHETIC,
        "signing": {
            "algorithm": protocol.SYNTHETIC_ALGORITHM,
            "key_id": protocol.synthetic_key_id(),
        },
        "broker_identity": {"user": "_metisbroker", "uid": 501, "gid": 501},
        "runner_identity": {"user": "_metisrunner", "uid": 502, "gid": 502},
        "launcher_identity": {"user": "root", "uid": 0, "gid": 0},
        "installed_code_identity": installed,
        "installed_code_paths": paths,
        "installed_code_roster": roster,
        "policy_identity": {
            "template_sha256": template,
            "parameters": parameters,
            "resolved_sha256": resolved,
        },
        "release_identity": {
            "release_id": release_id,
            "ancestry_root_sha256": protocol.release_ancestry_hash(release_id, roster),
        },
    }


def _policy() -> tuple[dict[str, str], str, str]:
    template = _digest("policy-template")
    parameters = {"NODE_EXECUTABLE": _digest("node"), "RUNTIME_ROOT": _digest("runtime")}
    return parameters, template, protocol.policy_hash(template, parameters)


def _request(authority: dict, nonce: str, *, task: str = "phase-a-task") -> dict:
    _parameters, _template, policy_sha256 = _policy()
    return protocol.build_request(
        client_nonce=nonce,
        payload={"task": task, "inputs": {"source": _digest(f"source:{task}")}},
        claimed_authority_sha256=protocol.authority_hash(authority),
        claimed_release_sha256=authority["release_identity"]["ancestry_root_sha256"],
        claimed_policy_sha256=policy_sha256,
    )


def _row(path: str, digest: str) -> dict:
    return {
        "path": path,
        "size": 4096,
        "mode": stat.S_IFREG | 0o444,
        "sha256": digest,
        "uid": 0,
        "gid": 0,
        "dev": 1,
        "ino": int(hashlib.sha256(path.encode("utf-8")).hexdigest()[:8], 16),
        "nlink": 1,
    }


def _result(request: dict, authority: dict) -> dict:
    installed = authority["installed_code_identity"]
    roster = copy.deepcopy(authority["installed_code_roster"])
    return {
        "measured": {
            "authority_sha256": protocol.authority_hash(authority),
            "release_sha256": authority["release_identity"]["ancestry_root_sha256"],
            "policy_sha256": request["claimed_policy_sha256"],
        },
        "identities": {
            "broker": {"user": "_metisbroker", "code_sha256": installed["broker_code_sha256"]},
            "launcher": {"code_sha256": installed["launcher_sha256"]},
            "worker": {"code_sha256": installed["worker_sha256"]},
            "node": {"sha256": installed["node_sha256"], "version": "v22.22.3"},
            "loader": {"sha256": installed["loader_sha256"]},
        },
        "effective_ids": {
            "broker_uid": 501,
            "broker_gid": 501,
            "runner_uid": 502,
            "runner_gid": 502,
            "launcher_uid": 0,
            "launcher_gid": 0,
        },
        "policy": copy.deepcopy(authority["policy_identity"]),
        "roster": {"pre": roster, "post": copy.deepcopy(roster)},
        "output": {
            "stdout_sha256": _digest("stdout"),
            "stderr_sha256": _digest("stderr"),
            "exit_code": 0,
            "publication": {"sha256": _digest("publication"), "size": 1, "atomic": True},
        },
        "cleanup": {
            "process_census": {"residual_children": 0, "census_sha256": _digest("process")},
            "fd_census": {"retained_fds": 0, "census_sha256": _digest("fds")},
            "temp_census": {"entries": [], "roster_sha256": _digest("temp")},
        },
    }


def _broker(tmp_path: Path, authority: dict, executor, **kwargs):
    tmp_path.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("allow_unprotected_test_ledger", True)
    kwargs.setdefault("require_existing_ledger", False)
    return core.ProtectedExecutionBroker(
        authority=authority,
        ledger_path=tmp_path / "ledger.bin",
        executor=executor,
        nonce_factory=lambda: "b2" * 32,
        **kwargs,
    )


def _success_executor(calls: list[str] | None = None):
    def execute(request: dict, authority: dict, _attempt: dict) -> dict:
        if calls is not None:
            calls.append(request["client_nonce"])
        return _result(request, authority)

    return execute


def _records(broker: core.ProtectedExecutionBroker) -> list[dict]:
    return list(broker.inspect_ledger())


def _rewrite_records(path: Path, records: list[dict]) -> None:
    previous = core.LEDGER_GENESIS_DIGEST
    frames: list[bytes] = []
    for index, source in enumerate(records, start=1):
        record = core._build_record(
            record_sequence=index,
            previous_record_sha256=previous,
            record_kind=source["record_kind"],
            payload=source["payload"],
        )
        body = protocol.canonical_bytes(record)
        frames.append(struct.pack(">I", len(body)) + body)
        previous = record["record_sha256"]
    path.write_bytes(b"".join(frames))


def test_crash_before_consume_leaves_no_attempt(tmp_path: Path) -> None:
    authority = _authority()
    request = _request(authority, "01" * 32)
    broker = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.InjectedCrash, match="before_consume"):
        broker.handle(protocol.canonical_bytes(request), crash_at="before_consume")
    assert _records(broker) == []


def test_crash_after_consume_tombstones_without_reexecution(tmp_path: Path) -> None:
    authority = _authority()
    request = _request(authority, "02" * 32)
    calls: list[str] = []
    broker = _broker(tmp_path, authority, _success_executor(calls))
    with pytest.raises(core.InjectedCrash, match="after_consume"):
        broker.handle(protocol.canonical_bytes(request), crash_at="after_consume")
    restarted = _broker(tmp_path, authority, _success_executor(calls))
    with pytest.raises(core.BrokerCoreError, match="NONCE_CONSUMED_NO_RECEIPT"):
        restarted.handle(protocol.canonical_bytes(request))
    assert calls == []
    assert [row["record_kind"] for row in _records(restarted)] == ["attempt", "tombstone"]


def test_crash_during_execution_tombstones_without_receipt_gap(tmp_path: Path) -> None:
    authority = _authority()
    request = _request(authority, "03" * 32)
    broker = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.InjectedCrash, match="during_execution"):
        broker.handle(protocol.canonical_bytes(request), crash_at="during_execution")
    restarted = _broker(tmp_path, authority, _success_executor())
    fresh = _request(authority, "04" * 32)
    receipt = protocol.parse_canonical_json(restarted.handle(protocol.canonical_bytes(fresh)))
    assert receipt["attempt_sequence"] == 2
    assert receipt["receipt_sequence"] == 1


def test_crash_after_cleanup_tombstones_before_signing(tmp_path: Path) -> None:
    authority = _authority()
    request = _request(authority, "05" * 32)
    broker = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.InjectedCrash, match="after_cleanup"):
        broker.handle(protocol.canonical_bytes(request), crash_at="after_cleanup")
    assert "cleanup_proven" in broker.events
    assert "receipt_signed_volatile" not in broker.events
    restarted = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.BrokerCoreError, match="NONCE_CONSUMED_NO_RECEIPT"):
        restarted.handle(protocol.canonical_bytes(request))


def test_crash_after_sign_tombstones_without_resigning(tmp_path: Path) -> None:
    authority = _authority()
    request = _request(authority, "06" * 32)
    broker = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.InjectedCrash, match="after_sign"):
        broker.handle(protocol.canonical_bytes(request), crash_at="after_sign")
    assert "receipt_signed_volatile" in broker.events
    restarted = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.BrokerCoreError, match="NONCE_CONSUMED_NO_RECEIPT"):
        restarted.handle(protocol.canonical_bytes(request))


def test_durable_receipt_recovery_returns_exact_idempotent_bytes(tmp_path: Path) -> None:
    authority = _authority()
    request = _request(authority, "07" * 32)
    broker = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.InjectedCrash, match="after_receipt_append"):
        broker.handle(protocol.canonical_bytes(request), crash_at="after_receipt_append")
    restarted = _broker(tmp_path, authority, _success_executor())
    first = restarted.handle(protocol.canonical_bytes(request))
    second = restarted.handle(protocol.canonical_bytes(request))
    assert first == second
    assert len([row for row in _records(restarted) if row["record_kind"] == "receipt"]) == 1


def test_missing_required_ledger_fails_closed(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor(), require_existing_ledger=True)
    with pytest.raises(core.BrokerCoreError, match="LEDGER_MISSING"):
        broker.handle(protocol.canonical_bytes(_request(authority, "08" * 32)))


def test_torn_final_ledger_tail_is_repaired_before_next_attempt(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor())
    broker.handle(protocol.canonical_bytes(_request(authority, "09" * 32)))
    ledger_path = tmp_path / "ledger.bin"
    with ledger_path.open("ab") as handle:
        handle.write(b"\x00\x00")
        handle.flush()
        os.fsync(handle.fileno())
    recovered = _broker(tmp_path, authority, _success_executor())
    receipt = protocol.parse_canonical_json(
        recovered.handle(protocol.canonical_bytes(_request(authority, "0a" * 32)))
    )
    assert receipt["receipt_sequence"] == 2

    ambiguous_dir = tmp_path / "ambiguous"
    ambiguous = _broker(ambiguous_dir, authority, _success_executor())
    ambiguous.handle(protocol.canonical_bytes(_request(authority, "0f" * 32)))
    with (ambiguous_dir / "ledger.bin").open("ab") as handle:
        handle.write(struct.pack(">I", 64) + b"short")
        handle.flush()
        os.fsync(handle.fileno())
    with pytest.raises(core.BrokerCoreError, match="TORN_TAIL_AMBIGUOUS"):
        _broker(ambiguous_dir, authority, _success_executor()).inspect_ledger(repair_torn_tail=True)


def test_interior_ledger_corruption_refuses_recovery(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor())
    broker.handle(protocol.canonical_bytes(_request(authority, "0b" * 32)))
    ledger_path = tmp_path / "ledger.bin"
    data = bytearray(ledger_path.read_bytes())
    first_size = struct.unpack(">I", data[:4])[0]
    data[4 + first_size // 2] ^= 1
    ledger_path.write_bytes(data)
    with pytest.raises(core.BrokerCoreError, match="LEDGER_CORRUPT"):
        _broker(tmp_path, authority, _success_executor()).inspect_ledger()

    forged_dir = tmp_path / "forged-terminal"
    forged_broker = _broker(forged_dir, authority, _success_executor())
    forged_broker.handle(protocol.canonical_bytes(_request(authority, "0c" * 32)))
    forged_broker.handle(protocol.canonical_bytes(_request(authority, "0d" * 32)))
    records = _records(forged_broker)
    forged = copy.deepcopy(records)
    first_attempt = forged[0]["payload"]
    first_terminal = forged[1]["payload"]
    second_terminal = forged[3]["payload"]
    second_terminal["attempt_id"] = first_attempt["attempt_id"]
    second_terminal["request_hash"] = first_attempt["request_hash"]
    second_terminal["receipt_sha256"] = first_terminal["receipt_sha256"]
    second_terminal["receipt"] = first_terminal["receipt"]
    _rewrite_records(forged_dir / "ledger.bin", forged)
    restarted = _broker(forged_dir, authority, _success_executor())
    with pytest.raises(core.BrokerCoreError, match="LEDGER_CORRUPT"):
        restarted.inspect_ledger()
    with pytest.raises(core.BrokerCoreError, match="LEDGER_CORRUPT"):
        restarted.handle(protocol.canonical_bytes(_request(authority, "0e" * 32)))

    inner_dir = tmp_path / "forged-inner-terminal"
    inner_broker = _broker(inner_dir, authority, _success_executor())
    inner_broker.handle(protocol.canonical_bytes(_request(authority, "0f" * 32)))
    inner_broker.handle(protocol.canonical_bytes(_request(authority, "10" * 32)))
    inner_records = _records(inner_broker)
    inner_forged = copy.deepcopy(inner_records)
    first_attempt = inner_forged[0]["payload"]
    second_terminal = inner_forged[3]["payload"]
    forged_receipt = copy.deepcopy(second_terminal["receipt"])
    forged_receipt["request"]["client_nonce"] = first_attempt["client_nonce"]
    forged_receipt["request"]["request_hash"] = first_attempt["request_hash"]
    second_terminal["receipt"] = protocol.attach_synthetic_signature(forged_receipt)
    second_terminal["receipt_sha256"] = protocol.receipt_hash(second_terminal["receipt"])
    _rewrite_records(inner_dir / "ledger.bin", inner_forged)
    inner_restarted = _broker(inner_dir, authority, _success_executor())
    with pytest.raises(core.BrokerCoreError, match="LEDGER_CORRUPT"):
        inner_restarted.inspect_ledger()
    with pytest.raises(core.BrokerCoreError, match="LEDGER_CORRUPT"):
        inner_restarted.handle(protocol.canonical_bytes(_request(authority, "11" * 32)))


def test_same_nonce_never_reexecutes_and_returns_same_receipt(tmp_path: Path) -> None:
    authority = _authority()
    calls: list[str] = []
    broker = _broker(tmp_path, authority, _success_executor(calls))
    request = protocol.canonical_bytes(_request(authority, "0c" * 32))
    assert broker.handle(request) == broker.handle(request)
    assert calls == ["0c" * 32]


def test_identical_payload_with_fresh_nonce_reexecutes(tmp_path: Path) -> None:
    authority = _authority()
    calls: list[str] = []
    broker = _broker(tmp_path, authority, _success_executor(calls))
    first = protocol.parse_canonical_json(
        broker.handle(protocol.canonical_bytes(_request(authority, "0d" * 32)))
    )
    second = protocol.parse_canonical_json(
        broker.handle(protocol.canonical_bytes(_request(authority, "0e" * 32)))
    )
    assert calls == ["0d" * 32, "0e" * 32]
    assert (first["attempt_sequence"], second["attempt_sequence"]) == (1, 2)
    assert (first["receipt_sequence"], second["receipt_sequence"]) == (1, 2)


def test_concurrent_requests_receive_unique_attempt_and_receipt_sequences(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor(), max_inflight=8)
    requests = [_request(authority, f"{index:02x}" * 32) for index in range(1, 5)]
    barrier = threading.Barrier(len(requests) + 1)
    responses: list[dict] = []
    errors: list[BaseException] = []

    def invoke(request: dict) -> None:
        barrier.wait()
        try:
            responses.append(
                protocol.parse_canonical_json(broker.handle(protocol.canonical_bytes(request)))
            )
        except BaseException as error:  # asserted below; preserves thread failure evidence
            errors.append(error)

    threads = [threading.Thread(target=invoke, args=(request,)) for request in requests]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(row["attempt_sequence"] for row in responses) == [1, 2, 3, 4]
    assert sorted(row["receipt_sequence"] for row in responses) == [1, 2, 3, 4]


def test_receipt_chain_has_no_shared_predecessor_or_fork(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor())
    receipts = [
        protocol.parse_canonical_json(
            broker.handle(protocol.canonical_bytes(_request(authority, f"{index:02x}" * 32)))
        )
        for index in range(16, 19)
    ]
    previous = protocol.GENESIS_RECEIPT_DIGEST
    for receipt in sorted(receipts, key=lambda row: row["receipt_sequence"]):
        assert receipt["previous_receipt_sha256"] == previous
        previous = protocol.receipt_hash(receipt)


def test_consumption_is_fsynced_before_synthetic_executor(tmp_path: Path) -> None:
    authority = _authority()
    observed: list[tuple[str, ...]] = []
    broker: core.ProtectedExecutionBroker

    def execute(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        observed.append(broker.events)
        return _result(request, loaded_authority)

    broker = _broker(tmp_path, authority, execute)
    broker.handle(protocol.canonical_bytes(_request(authority, "13" * 32)))
    assert observed == [("consume_fsync", "execute_started")]


def test_receipt_is_fsynced_before_delivery(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor())
    broker.handle(protocol.canonical_bytes(_request(authority, "14" * 32)))
    assert broker.events.index("receipt_fsync") < broker.events.index("delivered")


def test_authority_and_synthetic_key_continuity_is_structural(tmp_path: Path) -> None:
    first_authority = _authority()
    first = _broker(tmp_path, first_authority, _success_executor())
    first.handle(protocol.canonical_bytes(_request(first_authority, "15" * 32)))
    rotated = _authority(release_id="w3-release-v2", release_seed="release-v2")
    second = _broker(tmp_path, rotated, _success_executor())
    receipt = protocol.parse_canonical_json(
        second.handle(protocol.canonical_bytes(_request(rotated, "16" * 32)))
    )
    assert receipt["receipt_sequence"] == 2
    assert receipt["signature"]["key_id"] == protocol.synthetic_key_id()
    assert all(
        protocol.verify_receipt_signature(row["payload"]["receipt"])
        for row in _records(second)
        if row["record_kind"] == "receipt"
    )


def test_release_rotation_preserves_receipt_chain_continuity(tmp_path: Path) -> None:
    old = _authority(release_id="release-old", release_seed="release-old")
    broker = _broker(tmp_path, old, _success_executor())
    old_receipt = protocol.parse_canonical_json(
        broker.handle(protocol.canonical_bytes(_request(old, "17" * 32)))
    )
    new = _authority(release_id="release-new", release_seed="release-new")
    rotated = _broker(tmp_path, new, _success_executor())
    new_receipt = protocol.parse_canonical_json(
        rotated.handle(protocol.canonical_bytes(_request(new, "18" * 32)))
    )
    assert new_receipt["previous_receipt_sha256"] == protocol.receipt_hash(old_receipt)


def test_request_hash_existence_probe_is_explicitly_denied(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.BrokerCoreError, match="REQUEST_HASH_PROBE_DENIED"):
        broker.lookup_request_hash(_digest("guess"))


def test_bounded_queue_rejects_before_consuming_a_nonce(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor(), max_inflight=1)
    assert broker._slots.acquire(blocking=False) is True  # deliberate bounded-queue seam
    try:
        with pytest.raises(core.BrokerCoreError, match="QUEUE_FULL"):
            broker.handle(protocol.canonical_bytes(_request(authority, "19" * 32)))
    finally:
        broker._slots.release()
    assert not (tmp_path / "ledger.bin").exists()


def test_authority_release_and_policy_claims_are_cross_bound(tmp_path: Path) -> None:
    authority = _authority()
    bad_authority = protocol.build_request(
        client_nonce="1a" * 32,
        payload={"task": "phase-a-task", "inputs": {"source": _digest("source")}},
        claimed_authority_sha256=_digest("forged-authority"),
        claimed_release_sha256=authority["release_identity"]["ancestry_root_sha256"],
        claimed_policy_sha256=_policy()[2],
    )
    with pytest.raises(core.BrokerCoreError, match="INVALID_REQUEST"):
        _broker(tmp_path / "authority", authority, _success_executor()).handle(
            protocol.canonical_bytes(bad_authority)
        )
    bad_release = protocol.build_request(
        client_nonce="1b" * 32,
        payload={"task": "phase-a-task", "inputs": {"source": _digest("source")}},
        claimed_authority_sha256=protocol.authority_hash(authority),
        claimed_release_sha256=_digest("forged-release"),
        claimed_policy_sha256=_policy()[2],
    )
    with pytest.raises(core.BrokerCoreError, match="INVALID_REQUEST"):
        _broker(tmp_path / "release", authority, _success_executor()).handle(
            protocol.canonical_bytes(bad_release)
        )
    bad_policy_claim = protocol.build_request(
        client_nonce="1c" * 32,
        payload={"task": "phase-a-task", "inputs": {"source": _digest("source")}},
        claimed_authority_sha256=protocol.authority_hash(authority),
        claimed_release_sha256=authority["release_identity"]["ancestry_root_sha256"],
        claimed_policy_sha256=_digest("forged-policy-claim"),
    )
    with pytest.raises(core.BrokerCoreError, match="INVALID_REQUEST"):
        _broker(tmp_path / "policy-claim", authority, _success_executor()).handle(
            protocol.canonical_bytes(bad_policy_claim)
        )

    def bad_policy(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["policy"]["resolved_sha256"] = _digest("forged-policy")
        return result

    with pytest.raises(core.BrokerCoreError, match="POLICY_CLAIM_MISMATCH"):
        _broker(tmp_path / "policy", authority, bad_policy).handle(
            protocol.canonical_bytes(_request(authority, "1d" * 32))
        )


def test_all_executed_code_identities_including_launcher_are_bound(tmp_path: Path) -> None:
    authority = _authority()
    for index, (section, field) in enumerate(
        (
            ("broker", "code_sha256"),
            ("launcher", "code_sha256"),
            ("worker", "code_sha256"),
            ("node", "sha256"),
            ("loader", "sha256"),
        )
    ):

        def mutated(
            request: dict, loaded_authority: dict, _attempt: dict, section=section, field=field
        ) -> dict:
            result = _result(request, loaded_authority)
            result["identities"][section][field] = _digest(f"forged-{section}")
            return result

        with pytest.raises(core.BrokerCoreError, match="EXECUTED_IDENTITY_MISMATCH"):
            _broker(tmp_path / str(index), authority, mutated).handle(
                protocol.canonical_bytes(_request(authority, f"{0x20 + index:02x}" * 32))
            )


def test_complete_root_owned_single_link_roster_is_required(tmp_path: Path) -> None:
    authority = _authority()

    def cases(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["roster"]["pre"][0]["uid"] = 501
        result["roster"]["post"] = copy.deepcopy(result["roster"]["pre"])
        return result

    with pytest.raises(core.BrokerCoreError, match="PREIMAGE_ROSTER_INCOMPLETE"):
        _broker(tmp_path / "owner", authority, cases).handle(
            protocol.canonical_bytes(_request(authority, "25" * 32))
        )

    def hardlink(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["roster"]["pre"][0]["nlink"] = 2
        result["roster"]["post"] = copy.deepcopy(result["roster"]["pre"])
        return result

    with pytest.raises(core.BrokerCoreError, match="PREIMAGE_ROSTER_INCOMPLETE"):
        _broker(tmp_path / "link", authority, hardlink).handle(
            protocol.canonical_bytes(_request(authority, "26" * 32))
        )

    arbitrary = copy.deepcopy(authority)
    arbitrary["installed_code_paths"]["broker"] = "arbitrary/caller-selected"
    with pytest.raises(protocol.ValidationError, match="installed-roster-path-mismatch"):
        protocol.validate_authority(arbitrary)
    swapped = copy.deepcopy(authority)
    swapped["installed_code_paths"]["broker"] = authority["installed_code_paths"]["launcher"]
    swapped["installed_code_paths"]["launcher"] = authority["installed_code_paths"]["broker"]
    with pytest.raises(protocol.ValidationError, match="installed-roster-digest-mismatch"):
        protocol.validate_authority(swapped)

    def swapped_result(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["roster"]["pre"][0]["path"] = "arbitrary/leaf"
        result["roster"]["post"] = copy.deepcopy(result["roster"]["pre"])
        return result

    with pytest.raises(core.BrokerCoreError, match="PREIMAGE_ROSTER_INCOMPLETE"):
        _broker(tmp_path / "arbitrary-result", authority, swapped_result).handle(
            protocol.canonical_bytes(_request(authority, "26" * 32))
        )


def test_pre_and_post_rosters_must_match_exactly(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["roster"]["post"][0]["sha256"] = _digest("changed-after")
        return result

    with pytest.raises(core.BrokerCoreError, match="PREIMAGE_ROSTER_CHANGED"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "27" * 32))
        )


def test_caller_writable_roster_mode_is_rejected(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["roster"]["pre"][0]["mode"] = stat.S_IFREG | 0o666
        result["roster"]["post"] = copy.deepcopy(result["roster"]["pre"])
        return result

    with pytest.raises(core.BrokerCoreError, match="PREIMAGE_ROSTER_INCOMPLETE"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "28" * 32))
        )


def test_missing_required_roster_leaf_is_rejected(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["roster"]["pre"] = result["roster"]["pre"][:-1]
        result["roster"]["post"] = copy.deepcopy(result["roster"]["pre"])
        return result

    with pytest.raises(core.BrokerCoreError, match="PREIMAGE_ROSTER_INCOMPLETE"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "29" * 32))
        )


def test_effective_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["effective_ids"]["runner_uid"] = 501
        return result

    with pytest.raises(core.BrokerCoreError, match="EFFECTIVE_ID_MISMATCH"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "2a" * 32))
        )


def test_ledger_symlink_mode_and_link_count_are_rejected(tmp_path: Path) -> None:
    authority = _authority()
    target = tmp_path / "target"
    target.write_bytes(b"")
    symlink = tmp_path / "ledger.bin"
    symlink.symlink_to(target)
    with pytest.raises(core.BrokerCoreError):
        _broker(tmp_path, authority, _success_executor()).handle(
            protocol.canonical_bytes(_request(authority, "2b" * 32))
        )

    mode_dir = tmp_path / "mode"
    mode_dir.mkdir()
    mode_ledger = mode_dir / "ledger.bin"
    mode_ledger.write_bytes(b"")
    mode_ledger.chmod(0o644)
    with pytest.raises(core.BrokerCoreError, match="LEDGER_FILE_UNSAFE"):
        _broker(mode_dir, authority, _success_executor()).handle(
            protocol.canonical_bytes(_request(authority, "2c" * 32))
        )

    link_dir = tmp_path / "nlink"
    link_dir.mkdir()
    link_ledger = link_dir / "ledger.bin"
    link_ledger.write_bytes(b"")
    link_ledger.chmod(0o600)
    os.link(link_ledger, link_dir / "ledger-alias.bin")
    with pytest.raises(core.BrokerCoreError, match="LEDGER_FILE_UNSAFE"):
        _broker(link_dir, authority, _success_executor()).handle(
            protocol.canonical_bytes(_request(authority, "2d" * 32))
        )

    replacement_dir = tmp_path / "replacement"
    replacement_dir.mkdir()
    replacement_path = replacement_dir / "ledger.bin"

    def replace_ledger(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        staged = replacement_dir / "staged-ledger.bin"
        staged.write_bytes(b"")
        staged.chmod(0o600)
        os.replace(staged, replacement_path)
        return _result(request, loaded_authority)

    executor_calls: list[str] = []

    def counted_replacement(request: dict, loaded_authority: dict, attempt: dict) -> dict:
        executor_calls.append(request["client_nonce"])
        return replace_ledger(request, loaded_authority, attempt)

    replaced = _broker(replacement_dir, authority, counted_replacement)
    replacement_request = protocol.canonical_bytes(_request(authority, "2e" * 32))
    with pytest.raises(core.BrokerCoreError):
        replaced.handle(replacement_request)
    with pytest.raises(core.BrokerCoreError, match="LEDGER_POISONED"):
        replaced.handle(replacement_request)
    assert executor_calls == ["2e" * 32]
    assert "delivered" not in replaced.events
    assert replacement_path.read_bytes() == b""

    user_owned_parent = tmp_path / "user-owned-parent"
    user_owned_parent.mkdir()
    with pytest.raises(core.BrokerCoreError, match="LEDGER_PARENT_UNSAFE"):
        core.ProtectedExecutionBroker(
            authority=authority,
            ledger_path=user_owned_parent / "ledger.bin",
            executor=_success_executor(),
            nonce_factory=lambda: "b2" * 32,
        ).handle(protocol.canonical_bytes(_request(authority, "2f" * 32)))

    unsafe_parent = tmp_path / "unsafe-parent"
    unsafe_parent.mkdir()
    unsafe_parent.chmod(0o777)
    with pytest.raises(core.BrokerCoreError, match="LEDGER_PARENT_UNSAFE"):
        _broker(unsafe_parent, authority, _success_executor()).handle(
            protocol.canonical_bytes(_request(authority, "2e" * 32))
        )

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(core.BrokerCoreError, match="LEDGER_PARENT_UNSAFE"):
        _broker(linked_parent, authority, _success_executor()).handle(
            protocol.canonical_bytes(_request(authority, "2f" * 32))
        )


def test_broker_core_never_imports_or_invokes_process_apis() -> None:
    tree = ast.parse(inspect.getsource(core))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "subprocess" not in imports
    assert not {"Popen", "run", "call", "system", "spawn", "execve"} & calls


def test_executor_exception_is_durably_tombstoned(tmp_path: Path) -> None:
    authority = _authority()

    def explode(_request: dict, _authority: dict, _attempt: dict) -> dict:
        raise RuntimeError("synthetic failure")

    broker = _broker(tmp_path, authority, explode)
    with pytest.raises(core.BrokerCoreError, match="EXECUTOR_FAILED"):
        broker.handle(protocol.canonical_bytes(_request(authority, "3a" * 32)))
    assert [row["record_kind"] for row in _records(broker)] == ["attempt", "tombstone"]


def test_residual_child_census_refuses_receipt(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["cleanup"]["process_census"]["residual_children"] = 1
        return result

    with pytest.raises(core.BrokerCoreError, match="EXECUTION_RESULT_INVALID"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "2f" * 32))
        )


def test_retained_fd_census_refuses_receipt(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["cleanup"]["fd_census"]["retained_fds"] = 1
        return result

    with pytest.raises(core.BrokerCoreError, match="EXECUTION_RESULT_INVALID"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "30" * 32))
        )


def test_temp_residual_census_refuses_receipt(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["cleanup"]["temp_census"]["entries"] = ["leftover"]
        return result

    with pytest.raises(core.BrokerCoreError, match="EXECUTION_RESULT_INVALID"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "31" * 32))
        )


def test_non_atomic_publication_refuses_receipt(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["output"]["publication"]["atomic"] = False
        return result

    with pytest.raises(core.BrokerCoreError, match="EXECUTION_RESULT_INVALID"):
        _broker(tmp_path, authority, mutated).handle(
            protocol.canonical_bytes(_request(authority, "32" * 32))
        )


def test_invalid_stdout_stderr_and_exit_shapes_refuse_receipt(tmp_path: Path) -> None:
    authority = _authority()
    for index, (path, value) in enumerate(
        (("stdout_sha256", "not-a-digest"), ("stderr_sha256", "not-a-digest"), ("exit_code", "0"))
    ):

        def mutated(
            request: dict, loaded_authority: dict, _attempt: dict, path=path, value=value
        ) -> dict:
            result = _result(request, loaded_authority)
            result["output"][path] = value
            return result

        with pytest.raises(core.BrokerCoreError, match="EXECUTION_RESULT_INVALID"):
            _broker(tmp_path / str(index), authority, mutated).handle(
                protocol.canonical_bytes(_request(authority, f"{0x33 + index:02x}" * 32))
            )


def test_cleanup_failure_never_reaches_the_signing_event(tmp_path: Path) -> None:
    authority = _authority()

    def mutated(request: dict, loaded_authority: dict, _attempt: dict) -> dict:
        result = _result(request, loaded_authority)
        result["cleanup"]["fd_census"]["retained_fds"] = 1
        return result

    broker = _broker(tmp_path, authority, mutated)
    with pytest.raises(core.BrokerCoreError, match="EXECUTION_RESULT_INVALID"):
        broker.handle(protocol.canonical_bytes(_request(authority, "36" * 32)))
    assert "receipt_signed_volatile" not in broker.events


def test_crash_before_receipt_fsync_never_reaches_delivery(tmp_path: Path) -> None:
    authority = _authority()
    broker = _broker(tmp_path, authority, _success_executor())
    with pytest.raises(core.InjectedCrash, match="after_sign"):
        broker.handle(
            protocol.canonical_bytes(_request(authority, "37" * 32)), crash_at="after_sign"
        )
    assert "receipt_fsync" not in broker.events
    assert "delivered" not in broker.events


def test_failed_attempt_has_no_receipt_and_restart_never_reexecutes(tmp_path: Path) -> None:
    authority = _authority()
    calls: list[str] = []

    def explode(_request: dict, _authority: dict, _attempt: dict) -> dict:
        calls.append("called")
        raise ValueError("synthetic failure")

    request = protocol.canonical_bytes(_request(authority, "38" * 32))
    broker = _broker(tmp_path, authority, explode)
    with pytest.raises(core.BrokerCoreError, match="EXECUTOR_FAILED"):
        broker.handle(request)
    restarted = _broker(tmp_path, authority, _success_executor(calls))
    with pytest.raises(core.BrokerCoreError, match="NONCE_CONSUMED_NO_RECEIPT"):
        restarted.handle(request)
    assert calls == ["called"]
    assert not any(row["record_kind"] == "receipt" for row in _records(restarted))
