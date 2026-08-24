"""Pure L70.3 planner and bundle validator for protected W3 execution.

This module describes install, upgrade and rollback operations.  It performs no
host mutation, key generation, daemon activation or payload execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
import plistlib
import re
import stat
from collections.abc import Mapping, Sequence
from typing import Any

CALLER_PRINCIPAL = "tommasotessarolo"
CALLER_GROUP = "staff"
CALLER_UID = 501
CALLER_GID = 20
BROKER_PRINCIPAL = "_metisbroker"
BROKER_UID = BROKER_GID = 499
RUNNER_PRINCIPAL = "_metisrunner"
RUNNER_UID = RUNNER_GID = 498
ANCHOR_PRINCIPAL = "_metisanchor"
ANCHOR_UID = ANCHOR_GID = 497
AUTHORITY_ID = "w3-protected-broker-authority-v1"

APP_SUPPORT_ROOT = "/Library/Application Support/MetisModel1"
RELEASE_ID = "w3-public-synthetic-v1"
RELEASE_ROOT = f"{APP_SUPPORT_ROOT}/releases/{RELEASE_ID}"
LOG_ROOT = "/Library/Logs/MetisModel1"
PRIVILEGED_HELPER_TOOL = "/Library/PrivilegedHelperTools/com.metis.model1.w3-launcher"
LAUNCH_DAEMONS_DIR = "/Library/LaunchDaemons"
BROKER_PLIST_LABEL = "com.metis.model1.w3-broker"
LAUNCHER_PLIST_LABEL = "com.metis.model1.w3-launcher"
ANCHOR_PLIST_LABEL = "com.metis.model1.w3-anchor"
LAUNCHD_PACKAGE_INSTANCE = "w3-public-synthetic-v1/install-v1"
LAUNCHD_PACKAGE_INSTANCE_KEY = "METIS_W3_PACKAGE_INSTANCE"
BROKER_PROGRAM = f"{APP_SUPPORT_ROOT}/broker/bin/w3-broker-socket-shim"
BROKER_CONFIG_PATH = f"{APP_SUPPORT_ROOT}/broker/config/w3-broker-config.json"
BROKER_LEDGER_PATH = f"{APP_SUPPORT_ROOT}/ledger/records.bin"
STAGING_PARENT = "/private/var/db/MetisModel1"
INSTALL_TRANSITION_JOURNAL_PATH = f"{STAGING_PARENT}/w3-phase-b-install-journal.bin"
PUBLIC_RECEIPT_JOURNAL_PATH = f"{APP_SUPPORT_ROOT}/receipts/public-signed-receipts.bin"
ANCHOR_LOG_PATH = f"{APP_SUPPORT_ROOT}/state/anchor/consumer-anchor.log"
SIGNING_KEY_PATH = f"{APP_SUPPORT_ROOT}/keys/w3-broker-signing.key"
PUBLIC_KEY_REGISTRY_PATH = f"{APP_SUPPORT_ROOT}/registry/public-keys.json"
PUBLIC_FIXTURE_REGISTRY_PATH = f"{APP_SUPPORT_ROOT}/registry/public-fixtures.json"
AUTHORITY_REGISTRY_PATH = f"{APP_SUPPORT_ROOT}/registry/protected-authority.json"
AUTHORITY_CANDIDATE_PATH = f"{APP_SUPPORT_ROOT}/registry/.protected-authority.candidate"
PUBLICATION_PARENT = f"{APP_SUPPORT_ROOT}/publication"
PUBLICATION_ACTIVE = f"{PUBLICATION_PARENT}/active"
RUNS_PARENT = f"{APP_SUPPORT_ROOT}/runs"
RUNS_ACTIVE = f"{RUNS_PARENT}/active"
BROKER_SOCKET_PATH = "/var/run/metis-model1/w3-broker.sock"
LAUNCHER_SOCKET_PATH = "/var/run/metis-model1/w3-launcher.sock"
ANCHOR_SOCKET_PATH = "/var/run/metis-model1/w3-anchor.sock"
INSTALL_BUNDLE_MANIFEST_PATH = f"{APP_SUPPORT_ROOT}/manifest/w3-phase-b-install-bundle.json"
STAGED_BUNDLE_ROOT = f"{STAGING_PARENT}/w3-phase-b-install-bundle"
STAGED_INSTALL_TREE = f"{STAGED_BUNDLE_ROOT}/install-root"
ROLLBACK_EVIDENCE_PREFIX = f"{STAGING_PARENT}/w3-phase-b-retained"
BOOTSTRAP_BINARY_PATH = f"{STAGING_PARENT}/w3-installer-bootstrap"
BOOTSTRAP_DESCRIPTOR_PATH = f"{STAGING_PARENT}/w3-phase-b-bootstrap.descriptor"
BOOTSTRAP_SOURCE_ROOT = "/private/var/tmp/MetisModel1-w3-phase-b-source"
BOOTSTRAP_BINARY_SOURCE_ROOT = "/private/var/tmp/MetisModel1-w3-phase-b-bootstrap"
BOOTSTRAP_BINARY_SOURCE_PATH = f"{BOOTSTRAP_BINARY_SOURCE_ROOT}/w3-installer-bootstrap"
BOOTSTRAP_DESCRIPTOR_MAGIC = "METIS-W3-PHASE-B-BOOTSTRAP-V1"
BOOTSTRAP_DESCRIPTOR_MAX_BYTES = 32 * 1024 * 1024
BOOTSTRAP_FILE_COUNT_MAX = 8_192
BOOTSTRAP_TOTAL_BYTES_MAX = 2_147_483_648
BOOTSTRAP_EXECUTOR_MODULE = "runtime.w3_broker_executor"
BOOTSTRAP_STERILE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
BOOTSTRAP_MANIFEST_RELATIVE_PATH = "metadata/w3-phase-b-install-bundle.json"
BOOTSTRAP_PLAN_RELATIVE_PATH = "metadata/install-plan.json"
BOOTSTRAP_COMPILER_PATH = (
    "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
)
BOOTSTRAP_COMPILER_VERSION = "Apple clang version 21.0.0 (clang-2100.1.1.101)"
BOOTSTRAP_COMPILER_SIZE = 141_373_024
BOOTSTRAP_COMPILER_SHA256 = (
    "sha256:7def90dd8829726686213a747fc5bff1583df933dae5edc55d755479e0bfe00a"
)
BOOTSTRAP_LINKER_PATH = (
    "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/ld"
)
BOOTSTRAP_LINKER_VERSION = "ld-1267"
BOOTSTRAP_LINKER_SIZE = 2_331_792
BOOTSTRAP_LINKER_SHA256 = "sha256:5897b275efd93b201b6df5832dd541262b3f20f290859ba78f2200a6a66ef38b"
BOOTSTRAP_SDK_PATH = (
    "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/"
    "Developer/SDKs/MacOSX26.5.sdk"
)
BOOTSTRAP_SDK_VERSION = "26.5"
BOOTSTRAP_SDK_SETTINGS_SIZE = 7_774
BOOTSTRAP_SDK_SETTINGS_SHA256 = (
    "sha256:f8d005f09381389167f9e0aeaa169bc9e7dff162ef22ca2fd8e98df7ff1acafe"
)
BOOTSTRAP_LIBSYSTEM_SIZE = 334_178
BOOTSTRAP_LIBSYSTEM_SHA256 = (
    "sha256:20cfce043f11a083e2eb6111efe3579919a8082fa4cc912a7bd839af2010ec57"
)
BOOTSTRAP_COMMONDIGEST_SIZE = 11_970
BOOTSTRAP_COMMONDIGEST_SHA256 = (
    "sha256:83a9705bbc8d44f27ee61801064ee99288496a038d623f152aa30db6819e9ca6"
)
BOOTSTRAP_ARCHITECTURE = "arm64"
BOOTSTRAP_DEPLOYMENT_TARGET = "26.0"
BOOTSTRAP_BUILD_ARGV: tuple[str, ...] = (
    BOOTSTRAP_COMPILER_PATH,
    "-std=c11",
    "-O2",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-arch",
    BOOTSTRAP_ARCHITECTURE,
    f"-mmacosx-version-min={BOOTSTRAP_DEPLOYMENT_TARGET}",
    "-isysroot",
    BOOTSTRAP_SDK_PATH,
    "-Wl,-no_uuid",
    "<SOURCE>",
    "-o",
    "<OUTPUT>",
)
BOOTSTRAP_BUILD_ENVIRONMENT: Mapping[str, str] = {
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": BOOTSTRAP_STERILE_PATH,
    "ZERO_AR_DATE": "1",
}
BOOTSTRAP_SOURCE_SIZE = 79_144
BOOTSTRAP_SOURCE_SHA256 = "sha256:66e686da506dfb67c6652c7cbd5952095d9867a0230d99542f96a2cebe0f7a31"
BOOTSTRAP_BINARY_SIZE = 54_232
BOOTSTRAP_BINARY_SHA256 = "sha256:ddd09fcffc5e8a38ab0f140fce640e66b9020b2654e398a2268a77fd787a8447"
ADMIN_INVOCATION_KIND = "w3-phase-b-admin-invocation"
ADMIN_INVOCATION_TEMPLATE_KIND = "w3-phase-b-admin-invocation-template"
ADMIN_INVOCATION_DIGEST_PLACEHOLDERS: Mapping[str, str] = {
    "descriptor": "<DESCRIPTOR_SHA256>",
    "plan": "<PLAN_SHA256>",
    "bundle": "<MANIFEST_SHA256>",
}
PYTHON_SOURCE_CENSUS_ROOT = f"{STAGED_BUNDLE_ROOT}/source-census/cpython-3.13.3"
NODE_SOURCE_CENSUS_ROOT = f"{STAGED_BUNDLE_ROOT}/source-census/node-capsule"
PYTHON_ROOT = f"{APP_SUPPORT_ROOT}/runtime/python"
PYTHON_SITE_PACKAGES = f"{PYTHON_ROOT}/lib/python3.13/site-packages"

NONCLAIMS: tuple[str, ...] = (
    "no-production-authority",
    "no-production-evidence",
    "public-synthetic-only",
    "no-semantic-accuracy-claim",
    "no-W5-credit",
)
PYTHON_VERSION = "3.13.3"
PYTHON_SOURCE_FILES = 1_808
PYTHON_SOURCE_BYTES = 44_064_036
PYTHON_SOURCE_ROSTER_SHA256 = (
    "sha256:b632ae57ee6c013e720fc699380923d807cafa6e82df6b1e96ab9163d7193333"
)
PYTHON_EXECUTABLE_SHA256 = "sha256:a4366d9cd2f4d63260a479cc58ff88abfde916bd46b0f0e12eb58baabe6f5a1a"
PYTHON_EXECUTABLE_SIZE = 49_968
PYTHON_DEPENDENCIES: tuple[Mapping[str, str], ...] = (
    {
        "name": "cryptography",
        "version": "47.0.0",
        "wheel_sha256": "sha256:160ad728f128972d362e714054f6ba0067cab7fb350c5202a9ae8ae4ce3ef1a0",
    },
    {
        "name": "cffi",
        "version": "2.0.0",
        "wheel_sha256": "sha256:45d5e886156860dc35862657e1494b9bae8dfa63bf56796f2fb56e1679fc0bca",
    },
    {
        "name": "pycparser",
        "version": "3.0",
        "wheel_sha256": "sha256:b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992",
    },
)
WHEEL_SOURCE_PATHS: Mapping[str, str] = {
    str(row["name"]): f"{STAGED_BUNDLE_ROOT}/wheels/{row['name']}-{row['version']}.whl"
    for row in PYTHON_DEPENDENCIES
}
NODE_VERSION = "v22.22.3"
NODE_SHA256 = "sha256:5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c"
NODE_SIZE = 112_915_776
NODE_CAPSULE_FILES = 1_827
NODE_CAPSULE_BYTES = 8_922_291
NODE_CAPSULE_ROSTER_SHA256 = (
    "sha256:d72a8a4bc3b3225c9750994f9f98bd8f653fef341bb23893425cde67810bafa2"
)
SEATBELT_POLICY_SHA256 = "sha256:8fb0a554738e379076a213eeb8de2be91beff4d09943875dc6d7f58fc072f124"
SEATBELT_POLICY_SIZE = 1_686
NATIVE_ARTIFACT_PINS: Mapping[str, tuple[int, str]] = {
    "launcher": (
        53_976,
        "sha256:bab278339cc1ad059cafa5cd1d2e75999495d45d768ee5c7b8770473698d09ca",
    ),
    "broker-socket-shim": (
        34_272,
        "sha256:97fa87cc18a0bb05cd4f52dbb60a0ee828c8ad7f14374d85f5275b1e4010a08a",
    ),
    "anchor-socket-shim": (
        34_272,
        "sha256:ff4f3af8b591d35a46b904768d787a48d3f16e8f2ca6e42de949fc5d92210aba",
    ),
}
ANCHOR_CONFIG_PATH = f"{APP_SUPPORT_ROOT}/anchor/config/w3-anchor-config.json"
ANCHOR_INSTANCE_ID = hashlib.sha256(b"metis-model1/w3-protected-anchor/v1").hexdigest()


def _expected_launchd_plist(label: str) -> dict[str, object]:
    common: dict[str, object] = {
        "Label": label,
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin",
            LAUNCHD_PACKAGE_INSTANCE_KEY: LAUNCHD_PACKAGE_INSTANCE,
        },
        "RunAtLoad": False,
        "ThrottleInterval": 10,
    }
    if label == LAUNCHER_PLIST_LABEL:
        common.update(
            {
                "ProgramArguments": [PRIVILEGED_HELPER_TOOL],
                "Sockets": {
                    "LauncherListener": {
                        "SockPathName": LAUNCHER_SOCKET_PATH,
                        "SockPathOwner": BROKER_UID,
                        "SockPathGroup": BROKER_GID,
                        "SockPathMode": 0o600,
                    },
                },
                "StandardOutPath": f"{LOG_ROOT}/w3-launcher.stdout.log",
                "StandardErrorPath": f"{LOG_ROOT}/w3-launcher.stderr.log",
            }
        )
    elif label == ANCHOR_PLIST_LABEL:
        common.update(
            {
                "ProgramArguments": [f"{APP_SUPPORT_ROOT}/anchor/bin/w3-anchor-socket-shim"],
                "UserName": ANCHOR_PRINCIPAL,
                "GroupName": ANCHOR_PRINCIPAL,
                "Sockets": {
                    "AnchorListener": {
                        "SockPathName": ANCHOR_SOCKET_PATH,
                        "SockPathOwner": CALLER_UID,
                        "SockPathGroup": CALLER_GID,
                        "SockPathMode": 0o600,
                    },
                },
                "StandardOutPath": f"{LOG_ROOT}/w3-anchor/w3-anchor.stdout.log",
                "StandardErrorPath": f"{LOG_ROOT}/w3-anchor/w3-anchor.stderr.log",
            }
        )
    elif label == BROKER_PLIST_LABEL:
        common.update(
            {
                "ProgramArguments": [BROKER_PROGRAM],
                "UserName": BROKER_PRINCIPAL,
                "GroupName": BROKER_PRINCIPAL,
                "Sockets": {
                    "BrokerListener": {
                        "SockPathName": BROKER_SOCKET_PATH,
                        "SockPathOwner": CALLER_UID,
                        "SockPathGroup": CALLER_GID,
                        "SockPathMode": 0o600,
                    },
                },
                "StandardOutPath": f"{LOG_ROOT}/broker/w3-broker.stdout.log",
                "StandardErrorPath": f"{LOG_ROOT}/broker/w3-broker.stderr.log",
            }
        )
    else:
        raise InstallerError("launchd plist label invalid")
    return common


def validate_launchd_plist_bytes(payload: bytes, *, label: str) -> dict[str, object]:
    """Parse and enforce the complete per-service launchd contract."""

    if not isinstance(payload, bytes) or not payload or len(payload) > 128 * 1024:
        raise InstallerError("launchd plist payload invalid")
    try:
        document = plistlib.loads(payload)
    except (plistlib.InvalidFileException, ValueError, TypeError) as error:
        raise InstallerError("launchd plist payload invalid") from error
    expected = _expected_launchd_plist(label)
    if type(document) is not dict or document != expected:
        raise InstallerError("launchd plist semantic contract invalid")
    return copy.deepcopy(expected)


def admin_invocation_template() -> dict[str, object]:
    """Return the non-circular, pre-main Stage-0 invocation contract."""

    bootstrap_source = {
        "path": BOOTSTRAP_BINARY_SOURCE_PATH,
        "size": BOOTSTRAP_BINARY_SIZE,
        "sha256": BOOTSTRAP_BINARY_SHA256,
        "mode": "0555",
    }
    bootstrap_target = {
        "path": BOOTSTRAP_BINARY_PATH,
        "size": BOOTSTRAP_BINARY_SIZE,
        "sha256": BOOTSTRAP_BINARY_SHA256,
        "mode": "0555",
    }
    return {
        "schema_version": 1,
        "kind": ADMIN_INVOCATION_TEMPLATE_KIND,
        "cwd": "/",
        "stage0_environment": {"PATH": BOOTSTRAP_STERILE_PATH},
        "bootstrap_source": bootstrap_source,
        "bootstrap_target": bootstrap_target,
        "trusted_install_argv": [
            "/usr/bin/sudo",
            "--",
            "/usr/bin/install",
            "-o",
            "root",
            "-g",
            "wheel",
            "-m",
            "0555",
            BOOTSTRAP_BINARY_SOURCE_PATH,
            BOOTSTRAP_BINARY_PATH,
        ],
        "target_remeasure_before_exec": {
            "path": BOOTSTRAP_BINARY_PATH,
            "regular_no_symlink": True,
            "size": BOOTSTRAP_BINARY_SIZE,
            "sha256": BOOTSTRAP_BINARY_SHA256,
            "mode": "0555",
            "must_match_source_bytes": True,
        },
        "argv": [
            "/usr/bin/sudo",
            "--",
            "/usr/bin/env",
            "-i",
            f"PATH={BOOTSTRAP_STERILE_PATH}",
            BOOTSTRAP_BINARY_PATH,
            "--apply",
            "--descriptor-digest",
            ADMIN_INVOCATION_DIGEST_PLACEHOLDERS["descriptor"],
            "--plan-digest",
            ADMIN_INVOCATION_DIGEST_PLACEHOLDERS["plan"],
            "--bundle-digest",
            ADMIN_INVOCATION_DIGEST_PLACEHOLDERS["bundle"],
        ],
        "pre_main_boundary": "trusted-admin-clean-environment-before-stage0-image-load",
        "in_main_scrub_role": "defense-in-depth-after-main-only",
    }


_FIXED_DIRECTORY_METADATA: Mapping[str, tuple[int, int, int]] = {
    APP_SUPPORT_ROOT: (0, 0, 0o755),
    f"{APP_SUPPORT_ROOT}/broker/config": (0, BROKER_GID, 0o750),
    f"{APP_SUPPORT_ROOT}/anchor/config": (0, ANCHOR_GID, 0o750),
    f"{APP_SUPPORT_ROOT}/ledger": (0, BROKER_GID, 0o710),
    f"{APP_SUPPORT_ROOT}/install": (0, 0, 0o700),
    f"{APP_SUPPORT_ROOT}/install/rollback-archive": (0, 0, 0o700),
    f"{APP_SUPPORT_ROOT}/manifest": (0, 0, 0o755),
    f"{APP_SUPPORT_ROOT}/receipts": (0, 0, 0o711),
    f"{APP_SUPPORT_ROOT}/keys": (0, BROKER_GID, 0o710),
    f"{APP_SUPPORT_ROOT}/registry": (0, 0, 0o755),
    PUBLICATION_PARENT: (0, BROKER_GID, 0o710),
    RUNS_PARENT: (0, 0, 0o711),
    f"{APP_SUPPORT_ROOT}/state/anchor": (0, ANCHOR_GID, 0o710),
    LOG_ROOT: (0, 0, 0o755),
    f"{LOG_ROOT}/broker": (0, BROKER_GID, 0o750),
    f"{LOG_ROOT}/w3-anchor": (0, ANCHOR_GID, 0o750),
    "/var/run/metis-model1": (0, 0, 0o755),
}

_FORBIDDEN_PYTHON_IMPORT_BASENAMES = frozenset({"sitecustomize.py", "usercustomize.py"})
_FORBIDDEN_PYTHON_IMPORT_SUFFIXES = (".pth", ".egg-link", ".pyc")

EXPECTED_ARTIFACT_PATHS: Mapping[str, str] = {
    "broker": f"{PYTHON_SITE_PACKAGES}/runtime/w3_broker_service.py",
    "worker": f"{PYTHON_SITE_PACKAGES}/runtime/w3_installed_worker.py",
    "installer": f"{PYTHON_SITE_PACKAGES}/runtime/w3_broker_installer.py",
    "installer-executor": f"{PYTHON_SITE_PACKAGES}/runtime/w3_broker_executor.py",
    "host-evidence": f"{PYTHON_SITE_PACKAGES}/runtime/w3_phase_b_evidence.py",
    "launcher": PRIVILEGED_HELPER_TOOL,
    "anchor": f"{PYTHON_SITE_PACKAGES}/runtime/w3_anchor_service.py",
    "broker-socket-shim": f"{APP_SUPPORT_ROOT}/broker/bin/w3-broker-socket-shim",
    "anchor-socket-shim": f"{APP_SUPPORT_ROOT}/anchor/bin/w3-anchor-socket-shim",
    "python": f"{PYTHON_ROOT}/bin/python3.13",
    "cryptography": f"{PYTHON_SITE_PACKAGES}/cryptography/__init__.py",
    "loader": f"{RELEASE_ROOT}/capsule/.metis-oracle/native_ts_loader.mjs",
    "runner": f"{RELEASE_ROOT}/capsule/.metis-oracle/runner.ts",
    "node": f"{RELEASE_ROOT}/runtime/node",
    "policy": f"{RELEASE_ROOT}/policy/w3-runner.sb",
    "fixture-registry": PUBLIC_FIXTURE_REGISTRY_PATH,
    "broker-config": BROKER_CONFIG_PATH,
    "broker-plist": f"{LAUNCH_DAEMONS_DIR}/{BROKER_PLIST_LABEL}.plist",
    "launcher-plist": f"{LAUNCH_DAEMONS_DIR}/{LAUNCHER_PLIST_LABEL}.plist",
    "anchor-plist": f"{LAUNCH_DAEMONS_DIR}/{ANCHOR_PLIST_LABEL}.plist",
}
AUTHORITY_LOGICAL_PATHS: Mapping[str, str] = {
    role: f"installed-role/{role}"
    for role in ("broker", "launcher", "worker", "loader", "runner", "node", "policy")
}


def authority_logical_path(install_path: str) -> str:
    for role, path in EXPECTED_ARTIFACT_PATHS.items():
        if path == install_path and role in AUTHORITY_LOGICAL_PATHS:
            return AUTHORITY_LOGICAL_PATHS[role]
    return "installed-tree/" + hashlib.sha256(install_path.encode("utf-8")).hexdigest()


def authority_roster_path_map(install_entries: Sequence[Mapping[str, object]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in install_entries:
        mode = int(row["mode"])
        if row["uid"] != 0 or row["gid"] != 0 or mode & 0o022:
            continue
        install_path = str(row["path"])
        logical = authority_logical_path(install_path)
        if logical in result or install_path in result.values():
            raise InstallerError("authority roster path map collision")
        result[logical] = install_path
    return dict(sorted(result.items()))


_ROOT_READONLY = (0, 0, stat.S_IFREG | 0o444)
_ROOT_EXECUTABLE = (0, 0, stat.S_IFREG | 0o555)
EXPECTED_ARTIFACT_METADATA: Mapping[str, tuple[int, int, int]] = {
    "broker": _ROOT_READONLY,
    "worker": _ROOT_READONLY,
    "installer": _ROOT_READONLY,
    "installer-executor": _ROOT_READONLY,
    "host-evidence": _ROOT_READONLY,
    "launcher": _ROOT_EXECUTABLE,
    "anchor": _ROOT_READONLY,
    "broker-socket-shim": _ROOT_EXECUTABLE,
    "anchor-socket-shim": _ROOT_EXECUTABLE,
    "python": _ROOT_EXECUTABLE,
    "cryptography": _ROOT_READONLY,
    "loader": _ROOT_READONLY,
    "runner": _ROOT_READONLY,
    "node": _ROOT_EXECUTABLE,
    "policy": _ROOT_READONLY,
    "fixture-registry": _ROOT_READONLY,
    "broker-config": (0, BROKER_GID, stat.S_IFREG | 0o440),
    "broker-plist": (0, 0, stat.S_IFREG | 0o644),
    "launcher-plist": (0, 0, stat.S_IFREG | 0o644),
    "anchor-plist": (0, 0, stat.S_IFREG | 0o644),
}

# `-I -B -m` still imports `site`; this fixed closure is therefore accepted
# only when the entire Python prefix is rostered and contains no executable
# startup hooks or editable path injectors.
REQUIRED_SITE_PACKAGE_PATHS: tuple[str, ...] = (
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_broker_service.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_anchor_service.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_broker_protocol.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_ed25519.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_protected_broker.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_installed_worker.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_broker_installer.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_broker_executor.py",
    f"{PYTHON_SITE_PACKAGES}/runtime/w3_phase_b_evidence.py",
    f"{PYTHON_SITE_PACKAGES}/metis_model1/__init__.py",
    f"{PYTHON_SITE_PACKAGES}/metis_model1/w3_broker_client.py",
    f"{PYTHON_SITE_PACKAGES}/metis_model1/provenance.py",
    f"{PYTHON_SITE_PACKAGES}/cryptography/__init__.py",
)
REQUIRED_PROJECT_PACKAGE_PATHS: tuple[str, ...] = tuple(
    path for path in REQUIRED_SITE_PACKAGE_PATHS if "/cryptography/" not in path
)

MACOS_BACKEND_OPERATION_ROSTER: Mapping[str, tuple[str, ...]] = {
    "validate-inputs": (
        "verify-canonical-plan",
        "verify-frozen-bundle",
        "verify-complete-source-install-rosters",
        "verify-caller-account-501-20",
        "verify-service-name-uid-gid-slots-free",
        "preflight-managed-target-conflicts-and-staged-closure",
    ),
    "create-identity-metisbroker": (
        "create-group-record-499",
        "set-group-primary-gid-499",
        "create-user-record-499",
        "set-user-unique-id-499",
        "set-user-primary-gid-499",
        "set-user-home-499",
        "set-user-shell-499",
        "verify-user-group-499",
    ),
    "create-identity-metisrunner": (
        "create-group-record-498",
        "set-group-primary-gid-498",
        "create-user-record-498",
        "set-user-unique-id-498",
        "set-user-primary-gid-498",
        "set-user-home-498",
        "set-user-shell-498",
        "verify-user-group-498",
    ),
    "create-identity-metisanchor": (
        "create-group-record-497",
        "set-group-primary-gid-497",
        "create-user-record-497",
        "set-user-unique-id-497",
        "set-user-primary-gid-497",
        "set-user-home-497",
        "set-user-shell-497",
        "verify-user-group-497",
    ),
    "install-broker-code": (
        "install-fixed-directory-roster",
        "install-root-owned-python-service-closure",
        "install-distinct-broker-anchor-shims",
        "verify-fixed-python-module-entrypoints",
    ),
    "install-runtime": (
        "install-cpython-3.13.3-symlink-free",
        "install-cryptography-47-cffi-pycparser",
        "install-node-v22.22.3",
        "verify-runtime-roster",
    ),
    "install-release": (
        "install-stable-release-slot",
        "install-public-capsule",
        "install-concrete-seatbelt-policy",
        "verify-release-content-roster",
    ),
    "install-launcher": ("install-privileged-launcher", "verify-launcher-fixed-macros-and-hash"),
    "precreate-durable-leaves": (
        "precreate-ledger",
        "verify-bootstrap-install-journal",
        "precreate-public-receipt-journal",
        "precreate-anchor-genesis",
        "precreate-publication-active",
        "precreate-runs-active",
        "verify-run-parent-active-inodes",
    ),
    "verify-installed-ancestry": (
        "verify-complete-installed-roster",
        "verify-owner-group-mode-link-inodes",
        "verify-no-extra-missing-or-symlink",
    ),
    "provision-signing-key": (
        "create-exclusive-ed25519-seed-cryptography47",
        "publish-public-key-registry-no-clobber",
        "prepare-authority-candidate-no-clobber",
        "prepare-anchor-config-no-clobber",
        "verify-prepared-authority-config-key-binding",
    ),
    "install-launchd-plists": (
        "install-launcher-plist",
        "install-anchor-plist",
        "install-broker-plist",
        "verify-three-plists-and-socket-owners",
    ),
    "bootstrap-launcher": ("launchctl-bootstrap-launcher", "verify-launcher-service"),
    "bootstrap-anchor": ("launchctl-bootstrap-anchor", "verify-anchor-job-authority-gated"),
    "bootstrap-broker": ("launchctl-bootstrap-broker", "verify-broker-job-authority-gated"),
    "register-authority": (
        "activate-prepared-authority-cas-last",
        "launchctl-kickstart-launcher-after-authority",
        "launchctl-kickstart-anchor-after-authority",
        "launchctl-kickstart-broker-after-authority",
        "verify-authority-config-and-services-live",
    ),
}

MACOS_BACKEND_COMMAND_CONTRACT: Mapping[str, object] = {
    "version": 1,
    "platform": "macOS",
    "shell": False,
    "environment": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    "executables": ["/usr/bin/dscl", "/usr/bin/dseditgroup", "/bin/launchctl"],
    "staged_source_mapping": f"{STAGED_INSTALL_TREE}<absolute-install-path>",
    "file_install": "dirfd-open-source-copy-temp-fsync-link-no-clobber-unlink-temp-remeasure",
    "authority": (
        "measure-full-content-and-code-closure-prepare-inactive-config-"
        "journal-intent-cas-activate-last"
    ),
    "rollback": "receipt-bound-recheck-all-host-mutations-children-first-retain-ambiguous",
    "journal": (
        "safe-o-excl-bootstrap-single-exclusive-inode-bound-flock-hash-chain-"
        "multi-transaction-operation-receipts"
    ),
}


def backend_roster_digest() -> str:
    material = {
        "operations": {
            key: list(value) for key, value in sorted(MACOS_BACKEND_OPERATION_ROSTER.items())
        },
        "command_contract": copy.deepcopy(dict(MACOS_BACKEND_COMMAND_CONTRACT)),
    }
    payload = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


FIXED_PRINCIPALS: Mapping[str, Mapping[str, object]] = {
    "caller": {
        "name": CALLER_PRINCIPAL,
        "uid": CALLER_UID,
        "gid": CALLER_GID,
        "group": CALLER_GROUP,
        "disposition": "must-exist-exactly",
    },
    "broker": {
        "name": BROKER_PRINCIPAL,
        "uid": BROKER_UID,
        "gid": BROKER_GID,
        "group": BROKER_PRINCIPAL,
        "disposition": "create-only-if-name-uid-gid-free",
    },
    "runner": {
        "name": RUNNER_PRINCIPAL,
        "uid": RUNNER_UID,
        "gid": RUNNER_GID,
        "group": RUNNER_PRINCIPAL,
        "disposition": "create-only-if-name-uid-gid-free",
    },
    "anchor": {
        "name": ANCHOR_PRINCIPAL,
        "uid": ANCHOR_UID,
        "gid": ANCHOR_GID,
        "group": ANCHOR_PRINCIPAL,
        "disposition": "create-only-if-name-uid-gid-free",
    },
    "launcher": {
        "name": "root",
        "uid": 0,
        "gid": 0,
        "group": "wheel",
        "disposition": "must-exist-exactly",
    },
}

INSTALL_STEP_IDS: tuple[str, ...] = (
    "validate-inputs",
    "create-identity-metisbroker",
    "create-identity-metisrunner",
    "create-identity-metisanchor",
    "install-broker-code",
    "install-runtime",
    "install-release",
    "install-launcher",
    "precreate-durable-leaves",
    "verify-installed-ancestry",
    "provision-signing-key",
    "install-launchd-plists",
    "bootstrap-launcher",
    "bootstrap-anchor",
    "bootstrap-broker",
    "register-authority",
)
ROLLBACK_STEP_IDS: tuple[str, ...] = (
    "withdraw-authority",
    "stop-broker",
    "stop-anchor",
    "stop-launcher",
    "archive-durable-evidence",
    "quarantine-signing-key",
    "remove-mutable-state",
    "remove-installed-code-children-first",
    "remove-created-identities-last",
)
RETAINED_ON_ROLLBACK: tuple[str, ...] = (
    "ledger",
    "old-public-keys",
    "signed-receipt-journal",
    "protected-anchor",
    "receipt-evidence",
    "install-transition-journal",
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOWED_KEYS = frozenset(
    {
        "authority_id",
        "bundle_sha256",
        "release_content_roster_sha256",
        "old_release_content_roster_sha256",
        "broker_principal",
        "runner_principal",
        "anchor_principal",
    }
)


class InstallerError(ValueError):
    """Typed refusal raised before a plan can become executable."""


def _contains_forbidden_material(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return (
            "/users/" in lowered
            or "private_key" in lowered
            or "private-key" in lowered
            or "-----begin" in lowered
        )
    if isinstance(value, Mapping):
        return any(
            _contains_forbidden_material(k) or _contains_forbidden_material(v)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_material(item) for item in value)
    return False


def _check_principal(name: Any, field: str, expected: str) -> str:
    if not isinstance(name, str) or not name:
        raise InstallerError(f"{field} must be a non-empty string")
    if name in {"root", "0"}:
        raise InstallerError(f"{field} must not resolve to root")
    if name != expected:
        raise InstallerError(f"{field} must be exactly {expected}")
    return name


def validate_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise InstallerError("config must be a mapping")
    unknown = set(config) - _ALLOWED_KEYS
    if unknown:
        raise InstallerError(f"unknown config keys: {sorted(unknown)}")
    if _contains_forbidden_material(config):
        raise InstallerError("config must contain no caller path, secret or private key material")
    normalized = copy.deepcopy(dict(config))
    authority_id = normalized.get("authority_id")
    if authority_id != AUTHORITY_ID:
        raise InstallerError(f"authority_id must be exactly {AUTHORITY_ID}")
    for name in (
        "bundle_sha256",
        "release_content_roster_sha256",
        "old_release_content_roster_sha256",
    ):
        value = normalized.get(name)
        if name == "old_release_content_roster_sha256" and value is None:
            continue
        pattern = _PREFIXED_DIGEST_RE if name == "bundle_sha256" else _DIGEST_RE
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise InstallerError(f"{name} has invalid lowercase sha256 syntax")
    normalized["broker_principal"] = _check_principal(
        normalized.get("broker_principal", BROKER_PRINCIPAL), "broker_principal", BROKER_PRINCIPAL
    )
    normalized["runner_principal"] = _check_principal(
        normalized.get("runner_principal", RUNNER_PRINCIPAL), "runner_principal", RUNNER_PRINCIPAL
    )
    normalized["anchor_principal"] = _check_principal(
        normalized.get("anchor_principal", ANCHOR_PRINCIPAL), "anchor_principal", ANCHOR_PRINCIPAL
    )
    if (
        len(
            {
                normalized["broker_principal"],
                normalized["runner_principal"],
                normalized["anchor_principal"],
            }
        )
        != 3
    ):
        raise InstallerError("service principals must be distinct")
    return normalized


def _step(
    step_id: str, depends_on: list[str], action: str, details: dict[str, Any]
) -> dict[str, Any]:
    return {"id": step_id, "depends_on": depends_on, "action": action, "details": details}


def _linear_steps(
    step_ids: Sequence[str], actions: Mapping[str, str], details: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    previous: list[str] = []
    for step_id in step_ids:
        steps.append(_step(step_id, previous, actions[step_id], details.get(step_id, {})))
        previous = [step_id]
    return steps


def _principals_block() -> dict[str, Any]:
    return {
        "ordered_roles": ["caller", "broker", "launcher", "runner", "anchor"],
        "fixed": copy.deepcopy(dict(FIXED_PRINCIPALS)),
        "fallback_ids_allowed": False,
        "all_distinct_except_fixed_root_and_caller_groups": True,
    }


def identity_conflict_preconditions() -> list[dict[str, object]]:
    checks: list[dict[str, object]] = [
        {
            "id": "caller-account-exact",
            "name": CALLER_PRINCIPAL,
            "uid": CALLER_UID,
            "gid": CALLER_GID,
            "group": CALLER_GROUP,
            "predicate": "name-uid-primary-gid-must-match",
            "on_failure": "STOP-before-effects",
        }
    ]
    for role in ("broker", "runner", "anchor"):
        principal = FIXED_PRINCIPALS[role]
        checks.append(
            {
                "id": f"{role}-slot-free",
                "name": principal["name"],
                "uid": principal["uid"],
                "gid": principal["gid"],
                "predicate": "name-and-uid-and-gid-must-all-be-free",
                "recheck": "immediately-before-and-after-create",
                "on_failure": "STOP-no-fallback-id",
            }
        )
    return checks


def _base_plan(plan_type: str, normalized: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "plan_type": plan_type,
        "schema_version": 2,
        "authority_id": normalized["authority_id"],
        "mode": "protected-public-synthetic",
        "nonclaims": list(NONCLAIMS),
        "principals": _principals_block(),
        "identity_conflict_preconditions": identity_conflict_preconditions(),
    }


def _tree_entry(
    path: str, owner: str, group: str, mode: str, writable_by: Sequence[str], checks: Sequence[str]
) -> dict[str, Any]:
    return {
        "path": path,
        "owner": owner,
        "group": group,
        "mode": mode,
        "writable_by": list(writable_by),
        "checks": list(checks),
    }


def _installed_tree() -> list[dict[str, Any]]:
    immutable = ["root-owned-ancestry", "symlink-free", "single-link", "mode-verification"]
    leaf = [
        "precreated-leaf",
        "root-owned-nonwritable-parent",
        "symlink-free",
        "single-link",
        "mode-verification",
    ]
    entries = [
        _tree_entry(APP_SUPPORT_ROOT, "root", "wheel", "0755", [], immutable),
        _tree_entry(f"{APP_SUPPORT_ROOT}/broker", "root", "wheel", "0755", [], immutable),
        _tree_entry(
            f"{APP_SUPPORT_ROOT}/broker/config", "root", BROKER_PRINCIPAL, "0750", [], immutable
        ),
        _tree_entry(
            BROKER_CONFIG_PATH, "root", BROKER_PRINCIPAL, "0440", [], [*immutable, "hash-remeasure"]
        ),
        _tree_entry(
            f"{APP_SUPPORT_ROOT}/anchor/config", "root", ANCHOR_PRINCIPAL, "0750", [], immutable
        ),
        _tree_entry(
            ANCHOR_CONFIG_PATH,
            "root",
            "wheel",
            "0444",
            [],
            [*immutable, "authority-candidate-cross-binding", "hash-remeasure"],
        ),
        _tree_entry(f"{APP_SUPPORT_ROOT}/runtime", "root", "wheel", "0755", [], immutable),
        _tree_entry(
            RELEASE_ROOT,
            "root",
            "wheel",
            "0755",
            [],
            [*immutable, "complete-roster-hash", "stable-slot-not-content-hash"],
        ),
        _tree_entry(f"{APP_SUPPORT_ROOT}/manifest", "root", "wheel", "0755", [], immutable),
        _tree_entry(
            INSTALL_BUNDLE_MANIFEST_PATH,
            "root",
            "wheel",
            "0444",
            [],
            [*immutable, "hash-remeasure"],
        ),
        _tree_entry(f"{APP_SUPPORT_ROOT}/ledger", "root", BROKER_PRINCIPAL, "0710", [], immutable),
        _tree_entry(
            BROKER_LEDGER_PATH, BROKER_PRINCIPAL, BROKER_PRINCIPAL, "0600", [BROKER_PRINCIPAL], leaf
        ),
        _tree_entry(f"{APP_SUPPORT_ROOT}/install", "root", "wheel", "0700", [], immutable),
        _tree_entry(
            INSTALL_TRANSITION_JOURNAL_PATH,
            "root",
            "wheel",
            "0600",
            ["root"],
            [*leaf, "append-only-code-path", "retained-on-rollback"],
        ),
        _tree_entry(f"{APP_SUPPORT_ROOT}/receipts", "root", "wheel", "0711", [], immutable),
        _tree_entry(
            PUBLIC_RECEIPT_JOURNAL_PATH,
            BROKER_PRINCIPAL,
            CALLER_GROUP,
            "0640",
            [BROKER_PRINCIPAL],
            [*leaf, "consumer-read-only", "append-only-code-path"],
        ),
        _tree_entry(f"{APP_SUPPORT_ROOT}/keys", "root", BROKER_PRINCIPAL, "0710", [], immutable),
        _tree_entry(
            SIGNING_KEY_PATH,
            "root",
            BROKER_PRINCIPAL,
            "0440",
            [],
            [*leaf, "broker-group-read-only", "never-environment"],
        ),
        _tree_entry(f"{APP_SUPPORT_ROOT}/registry", "root", "wheel", "0755", [], immutable),
        _tree_entry(
            PUBLIC_KEY_REGISTRY_PATH, "root", "wheel", "0444", [], [*immutable, "hash-remeasure"]
        ),
        _tree_entry(
            PUBLIC_FIXTURE_REGISTRY_PATH,
            "root",
            "wheel",
            "0444",
            [],
            [*immutable, "public-fixtures-only", "hash-remeasure"],
        ),
        _tree_entry(
            AUTHORITY_REGISTRY_PATH,
            "root",
            "wheel",
            "0444",
            [],
            [*immutable, "authority-last-activation"],
        ),
        _tree_entry(
            AUTHORITY_CANDIDATE_PATH,
            "root",
            "wheel",
            "0444",
            [],
            [*immutable, "inactive-transaction-owned", "removed-after-cas-activation"],
        ),
        _tree_entry(PUBLICATION_PARENT, "root", BROKER_PRINCIPAL, "0710", [], immutable),
        _tree_entry(
            PUBLICATION_ACTIVE,
            BROKER_PRINCIPAL,
            BROKER_PRINCIPAL,
            "0700",
            [BROKER_PRINCIPAL],
            [*leaf, "bounded-publication-only"],
        ),
        _tree_entry(
            RUNS_PARENT,
            "root",
            "wheel",
            "0711",
            [],
            [*immutable, "runner-can-traverse-not-write", "runner-cannot-rename-active"],
        ),
        _tree_entry(
            RUNS_ACTIVE,
            RUNNER_PRINCIPAL,
            RUNNER_PRINCIPAL,
            "0700",
            [RUNNER_PRINCIPAL],
            [*leaf, "launcher-holds-parent-and-leaf-dirfds", "post-run-named-inode-recheck"],
        ),
        _tree_entry(
            f"{APP_SUPPORT_ROOT}/state/anchor", "root", ANCHOR_PRINCIPAL, "0710", [], immutable
        ),
        _tree_entry(
            ANCHOR_LOG_PATH, ANCHOR_PRINCIPAL, ANCHOR_PRINCIPAL, "0600", [ANCHOR_PRINCIPAL], leaf
        ),
        _tree_entry(LOG_ROOT, "root", "wheel", "0755", [], immutable),
        _tree_entry(f"{LOG_ROOT}/broker", "root", BROKER_PRINCIPAL, "0750", [], immutable),
        _tree_entry(
            "/var/run/metis-model1",
            "root",
            "wheel",
            "0755",
            [],
            [*immutable, "socket-path-parent-only", "daemon-never-binds-or-unlinks"],
        ),
        _tree_entry(
            PRIVILEGED_HELPER_TOOL, "root", "wheel", "0755", [], [*immutable, "hash-remeasure"]
        ),
    ]
    for label in (BROKER_PLIST_LABEL, LAUNCHER_PLIST_LABEL, ANCHOR_PLIST_LABEL):
        entries.append(
            _tree_entry(
                f"{LAUNCH_DAEMONS_DIR}/{label}.plist", "root", "wheel", "0644", [], immutable
            )
        )
    return entries


_INSTALL_ACTIONS = {
    "validate-inputs": "validate frozen bundle, exact identities and conflict-free fixed slots",
    "create-identity-metisbroker": "create fixed broker user and group",
    "create-identity-metisrunner": "create fixed runner user and group",
    "create-identity-metisanchor": "create fixed anchor user and group",
    "install-broker-code": "install root-owned broker and worker code",
    "install-runtime": "install symlink-free Python and Node runtime closures",
    "install-release": "install pinned public-fixture release tree root-owned",
    "install-launcher": "install fixed privileged launcher root-owned",
    "precreate-durable-leaves": (
        "precreate ledger, public receipt journal, anchor and bounded active leaves"
    ),
    "verify-installed-ancestry": "remeasure complete installed bundle and inode identities",
    "provision-signing-key": "provision one broker-only protected-public-synthetic seed",
    "install-launchd-plists": "install three root-owned launchd property lists",
    "bootstrap-launcher": "bootstrap root launcher",
    "bootstrap-anchor": "bootstrap protected anchor",
    "bootstrap-broker": "bootstrap protected broker",
    "register-authority": "register authority only after every prior transition is durable",
}


def plan_install(config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_config(config)
    release_content = normalized["release_content_roster_sha256"]
    details: dict[str, dict[str, Any]] = {
        "validate-inputs": {
            "bundle_manifest": INSTALL_BUNDLE_MANIFEST_PATH,
            "bundle_sha256": normalized["bundle_sha256"],
            "backend_roster_sha256": backend_roster_digest(),
            "release_content_roster_sha256": release_content,
            "sockets": [BROKER_SOCKET_PATH, LAUNCHER_SOCKET_PATH, ANCHOR_SOCKET_PATH],
            "conflicts": identity_conflict_preconditions(),
            "journal_bootstrap": {
                "path": INSTALL_TRANSITION_JOURNAL_PATH,
                "mode": "0600",
                "owner": "root",
                "group": "wheel",
                "creation": "O_EXCL-before-transaction-session",
                "first_record_before_managed-effects": True,
            },
            "production": "rejected-before-effects",
        },
        "create-identity-metisbroker": {
            "principal": BROKER_PRINCIPAL,
            "uid": BROKER_UID,
            "gid": BROKER_GID,
            "fallback": False,
        },
        "create-identity-metisrunner": {
            "principal": RUNNER_PRINCIPAL,
            "uid": RUNNER_UID,
            "gid": RUNNER_GID,
            "fallback": False,
        },
        "create-identity-metisanchor": {
            "principal": ANCHOR_PRINCIPAL,
            "uid": ANCHOR_UID,
            "gid": ANCHOR_GID,
            "fallback": False,
        },
        "install-broker-code": {
            "program": BROKER_PROGRAM,
            "worker_role": "broker-side-python-adapter",
            "owner": "root",
            "group": "wheel",
        },
        "install-runtime": {
            "python": "CPython-3.13.3-symlink-free",
            "crypto": "cryptography-47.0.0",
            "node_evidence": "static-blocked-no-host-credit",
        },
        "install-release": {
            "path": RELEASE_ROOT,
            "release_id": RELEASE_ID,
            "expected_content_roster_sha256": f"sha256:{release_content}",
            "runtime_ancestry_is_postinstall_only": True,
            "public_fixtures_only": True,
            "path_contains_digest": False,
        },
        "install-launcher": {
            "tool": PRIVILEGED_HELPER_TOOL,
            "semantic_json": False,
            "signing": False,
        },
        "precreate-durable-leaves": {
            "ledger": BROKER_LEDGER_PATH,
            "install_transition_journal": {
                "path": INSTALL_TRANSITION_JOURNAL_PATH,
                "operation": "verify-prebootstrapped-inode-only",
            },
            "public_receipt_journal": PUBLIC_RECEIPT_JOURNAL_PATH,
            "anchor": ANCHOR_LOG_PATH,
            "publication_active": PUBLICATION_ACTIVE,
            "runs_parent": {"path": RUNS_PARENT, "owner": "root", "writable_by_runner": False},
            "runs_active": {
                "path": RUNS_ACTIVE,
                "owner": RUNNER_PRINCIPAL,
                "writable_by_runner": True,
            },
        },
        "verify-installed-ancestry": {
            "checks": [
                "root-owned-ancestry",
                "mode-verification",
                "symlink-free",
                "single-link",
                "complete-roster",
                "hash-remeasure",
                "runs-parent-active-inode-binding",
            ]
        },
        "provision-signing-key": {
            "path": SIGNING_KEY_PATH,
            "owner": "root",
            "group": BROKER_PRINCIPAL,
            "mode": "0440",
            "reachable_by": [BROKER_PRINCIPAL],
            "writable_by": [],
            "unreachable_by": ["caller", RUNNER_PRINCIPAL, ANCHOR_PRINCIPAL],
            "environment": False,
        },
        "install-launchd-plists": {
            "labels": [LAUNCHER_PLIST_LABEL, ANCHOR_PLIST_LABEL, BROKER_PLIST_LABEL],
            "owner": "root",
            "group": "wheel",
            "mode": "0644",
        },
        "bootstrap-launcher": {"label": LAUNCHER_PLIST_LABEL},
        "bootstrap-anchor": {"label": ANCHOR_PLIST_LABEL},
        "bootstrap-broker": {"label": BROKER_PLIST_LABEL},
        "register-authority": {"authority_id": normalized["authority_id"], "must_be_last": True},
    }
    plan = _base_plan("install", normalized)
    plan["steps"] = _linear_steps(INSTALL_STEP_IDS, _INSTALL_ACTIONS, details)
    plan["installed_tree"] = _installed_tree()
    plan["retained_on_failure"] = list(RETAINED_ON_ROLLBACK)
    return plan


def validate_install_plan(
    plan: Mapping[str, Any],
    *,
    bundle_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require the exact canonical install plan and optional frozen bundle binding."""

    if (
        not isinstance(plan, Mapping)
        or plan.get("plan_type") != "install"
        or plan.get("schema_version") != 2
    ):
        raise InstallerError("install plan identity invalid")
    steps = plan.get("steps")
    if (
        not isinstance(steps, list)
        or tuple(row.get("id") for row in steps if isinstance(row, Mapping)) != INSTALL_STEP_IDS
        or not steps
        or steps[-1].get("id") != "register-authority"
        or not isinstance(steps[0].get("details"), Mapping)
    ):
        raise InstallerError("install plan order invalid")
    first_details = steps[0]["details"]
    release_content = first_details.get("release_content_roster_sha256")
    bundle_sha256 = first_details.get("bundle_sha256")
    if (
        not isinstance(release_content, str)
        or _DIGEST_RE.fullmatch(release_content) is None
        or not isinstance(bundle_sha256, str)
        or _PREFIXED_DIGEST_RE.fullmatch(bundle_sha256) is None
    ):
        raise InstallerError("install plan digest binding invalid")
    expected = plan_install(
        {
            "authority_id": str(plan.get("authority_id")),
            "bundle_sha256": bundle_sha256,
            "release_content_roster_sha256": release_content,
        }
    )
    if dict(plan) != expected:
        raise InstallerError("install plan canonical form invalid")
    if bundle_manifest is not None:
        frozen = validate_bundle_manifest(bundle_manifest, require_frozen=True)
        if (
            bundle_sha256 != frozen["bundle_sha256"]
            or "sha256:" + release_content != frozen["release_content_roster_sha256"]
        ):
            raise InstallerError("install plan frozen bundle binding invalid")
    return copy.deepcopy(expected)


_UPGRADE_STEP_IDS = (
    "validate-inputs",
    "install-new-release",
    "verify-new-release",
    "activate-new-release",
    "register-authority",
)
_UPGRADE_ACTIONS = {
    "validate-inputs": "validate frozen upgrade bundle",
    "install-new-release": "install new release tree root-owned",
    "verify-new-release": "verify complete new release roster",
    "activate-new-release": "atomically activate new release",
    "register-authority": "register authority for new release last",
}


def plan_upgrade(config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_config(config)
    old = normalized.get("old_release_content_roster_sha256")
    if old is None:
        raise InstallerError("plan_upgrade requires old_release_content_roster_sha256")
    if old == normalized["release_content_roster_sha256"]:
        raise InstallerError("new and old release content roster digests must be distinct")
    details = {
        "validate-inputs": {
            "release_content_roster_sha256": normalized["release_content_roster_sha256"],
            "old_release_content_roster_sha256": old,
        },
        "install-new-release": {
            "path": RELEASE_ROOT,
            "release_id": RELEASE_ID,
            "expected_content_roster_sha256": (
                f"sha256:{normalized['release_content_roster_sha256']}"
            ),
            "runtime_ancestry_is_postinstall_only": True,
            "path_contains_digest": False,
        },
        "verify-new-release": {
            "checks": [
                "root-owned-ancestry",
                "mode-verification",
                "symlink-free",
                "single-link",
                "complete-roster",
                "hash-remeasure",
            ]
        },
        "activate-new-release": {"previous_release_content_roster_sha256": old, "atomic": True},
        "register-authority": {"authority_id": normalized["authority_id"], "must_be_last": True},
    }
    plan = _base_plan("upgrade", normalized)
    plan["steps"] = _linear_steps(_UPGRADE_STEP_IDS, _UPGRADE_ACTIONS, details)
    plan["old_release_retention"] = "until-no-retained-receipt-depends-on-it"
    return plan


_ROLLBACK_ACTIONS = {
    "withdraw-authority": "withdraw authority and refuse new work",
    "stop-broker": "stop broker daemon",
    "stop-anchor": "stop protected anchor daemon",
    "stop-launcher": "stop root launcher daemon",
    "archive-durable-evidence": "archive retained evidence without deletion",
    "quarantine-signing-key": "quarantine signing key without destroying evidence",
    "remove-mutable-state": "remove only explicit mutable children",
    "remove-installed-code-children-first": "remove explicit installed code children-first",
    "remove-created-identities-last": "remove only identities created by this journal",
}


def plan_rollback(config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_config(config)
    details = {
        "withdraw-authority": {"authority_id": normalized["authority_id"], "must_be_first": True},
        "stop-broker": {"label": BROKER_PLIST_LABEL},
        "stop-anchor": {"label": ANCHOR_PLIST_LABEL},
        "stop-launcher": {"label": LAUNCHER_PLIST_LABEL},
        "archive-durable-evidence": {"retained": list(RETAINED_ON_ROLLBACK), "never_deleted": True},
        "quarantine-signing-key": {"path": SIGNING_KEY_PATH, "destroy": False},
        "remove-mutable-state": {
            "targets": [PUBLICATION_ACTIVE, RUNS_ACTIVE],
            "excludes": list(RETAINED_ON_ROLLBACK),
            "explicit_paths_only": True,
        },
        "remove-installed-code-children-first": {
            "order": "children-first",
            "explicit_paths_only": True,
            "broad_globs": False,
        },
        "remove-created-identities-last": {
            "principals": [ANCHOR_PRINCIPAL, RUNNER_PRINCIPAL, BROKER_PRINCIPAL],
            "only_if_created_by_journal": True,
        },
    }
    plan = _base_plan("rollback", normalized)
    plan["steps"] = _linear_steps(ROLLBACK_STEP_IDS, _ROLLBACK_ACTIONS, details)
    plan["retained"] = list(RETAINED_ON_ROLLBACK)
    return plan


def canonical_bundle_bytes(document: Mapping[str, Any], *, omit_digest: bool = False) -> bytes:
    material = copy.deepcopy(dict(document))
    if omit_digest:
        material.pop("bundle_sha256", None)
    return json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def validate_bootstrap_descriptor_bytes(payload: bytes) -> dict[str, object]:
    """Parse the deliberately narrow, non-JSON Stage-0 consent descriptor."""

    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > BOOTSTRAP_DESCRIPTOR_MAX_BYTES
        or not payload.endswith(b"\n")
    ):
        raise InstallerError("bootstrap descriptor size or terminator invalid")
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise InstallerError("bootstrap descriptor must be ASCII") from error
    lines = text[:-1].split("\n")
    if len(lines) < 7 or lines[0] != BOOTSTRAP_DESCRIPTOR_MAGIC:
        raise InstallerError("bootstrap descriptor magic invalid")

    def header(index: int, name: str) -> str:
        parts = lines[index].split("\t")
        if len(parts) != 2 or parts[0] != name:
            raise InstallerError(f"bootstrap descriptor {name} header invalid")
        return parts[1]

    bootstrap_sha256 = header(1, "bootstrap_sha256")
    manifest_sha256 = header(2, "manifest_sha256")
    plan_sha256 = header(3, "plan_sha256")
    if any(
        _DIGEST_RE.fullmatch(value) is None
        for value in (bootstrap_sha256, manifest_sha256, plan_sha256)
    ):
        raise InstallerError("bootstrap descriptor digest invalid")
    file_count_text = header(4, "file_count")
    total_bytes_text = header(5, "total_bytes")
    if (
        not file_count_text.isdecimal()
        or not total_bytes_text.isdecimal()
        or (file_count_text.startswith("0") and file_count_text != "0")
        or (total_bytes_text.startswith("0") and total_bytes_text != "0")
    ):
        raise InstallerError("bootstrap descriptor count syntax invalid")
    file_count = int(file_count_text)
    total_bytes = int(total_bytes_text)
    if (
        file_count < 1
        or file_count > BOOTSTRAP_FILE_COUNT_MAX
        or total_bytes < 1
        or total_bytes > BOOTSTRAP_TOTAL_BYTES_MAX
        or len(lines) != 6 + file_count
    ):
        raise InstallerError("bootstrap descriptor denominator invalid")
    rows: list[dict[str, object]] = []
    decoded_paths: list[bytes] = []
    for line in lines[6:]:
        fields = line.split("\t")
        if len(fields) != 5 or fields[0] != "FILE":
            raise InstallerError("bootstrap descriptor file row invalid")
        path_hex, size_text, sha256, mode = fields[1:]
        if (
            not path_hex
            or len(path_hex) % 2
            or any(character not in "0123456789abcdef" for character in path_hex)
        ):
            raise InstallerError("bootstrap descriptor path hex invalid")
        try:
            path_bytes = bytes.fromhex(path_hex)
            relative_path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise InstallerError("bootstrap descriptor path encoding invalid") from error
        parts = relative_path.split("/")
        if (
            len(path_bytes) > 1024
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} or len(part.encode("utf-8")) > 255 for part in parts)
            or any(byte < 0x20 or byte == 0x7F for byte in path_bytes)
        ):
            raise InstallerError("bootstrap descriptor relative path invalid")
        if (
            not size_text.isdecimal()
            or (size_text.startswith("0") and size_text != "0")
            or _DIGEST_RE.fullmatch(sha256) is None
            or mode not in {"0444", "0555"}
        ):
            raise InstallerError("bootstrap descriptor file measurement invalid")
        size = int(size_text)
        if size < 0 or size > BOOTSTRAP_TOTAL_BYTES_MAX:
            raise InstallerError("bootstrap descriptor file size invalid")
        decoded_paths.append(path_bytes)
        rows.append(
            {"path": relative_path, "size": size, "sha256": "sha256:" + sha256, "mode": mode}
        )
    if (
        decoded_paths != sorted(decoded_paths)
        or len(decoded_paths) != len(set(decoded_paths))
        or sum(int(row["size"]) for row in rows) != total_bytes
    ):
        raise InstallerError("bootstrap descriptor file roster invalid")
    by_path = {str(row["path"]): row for row in rows}
    manifest = by_path.get("metadata/w3-phase-b-install-bundle.json")
    plan = by_path.get("metadata/install-plan.json")
    if (
        manifest is None
        or manifest["sha256"] != "sha256:" + manifest_sha256
        or plan is None
        or plan["sha256"] != "sha256:" + plan_sha256
    ):
        raise InstallerError("bootstrap descriptor metadata binding invalid")
    return {
        "bootstrap_sha256": "sha256:" + bootstrap_sha256,
        "manifest_sha256": "sha256:" + manifest_sha256,
        "plan_sha256": "sha256:" + plan_sha256,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "files": rows,
    }


def bootstrap_descriptor_bytes(
    *,
    bootstrap_sha256: str,
    manifest_sha256: str,
    plan_sha256: str,
    files: Sequence[Mapping[str, object]],
) -> bytes:
    """Generate and self-validate one canonical Stage-0 descriptor."""

    digests = (bootstrap_sha256, manifest_sha256, plan_sha256)
    if any(
        not isinstance(value, str) or _PREFIXED_DIGEST_RE.fullmatch(value) is None
        for value in digests
    ):
        raise InstallerError("bootstrap descriptor digest invalid")
    normalized: list[dict[str, object]] = []
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "size", "sha256", "mode"}:
            raise InstallerError("bootstrap descriptor file input invalid")
        normalized.append(dict(item))
    normalized.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    file_lines = [
        "\t".join(
            (
                "FILE",
                str(row["path"]).encode("utf-8").hex(),
                str(row["size"]),
                str(row["sha256"])[7:]
                if isinstance(row.get("sha256"), str) and str(row["sha256"]).startswith("sha256:")
                else "",
                str(row["mode"]),
            )
        )
        for row in normalized
    ]
    lines = [
        BOOTSTRAP_DESCRIPTOR_MAGIC,
        f"bootstrap_sha256\t{bootstrap_sha256[7:]}",
        f"manifest_sha256\t{manifest_sha256[7:]}",
        f"plan_sha256\t{plan_sha256[7:]}",
        f"file_count\t{len(normalized)}",
        f"total_bytes\t{sum(int(row['size']) for row in normalized)}",
        *file_lines,
    ]
    payload = ("\n".join(lines) + "\n").encode("ascii")
    validate_bootstrap_descriptor_bytes(payload)
    return payload


def expected_bootstrap_descriptor_files(
    manifest: Mapping[str, Any],
    *,
    manifest_payload: bytes,
    plan_payload: bytes,
) -> list[dict[str, object]]:
    """Project the complete frozen source roster into the closed Stage-0 wire."""

    frozen = validate_bundle_manifest(manifest, require_frozen=True)
    if canonical_bundle_bytes(frozen) != manifest_payload:
        raise InstallerError("bootstrap descriptor manifest bytes are not canonical")
    try:
        plan = json.loads(plan_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallerError("bootstrap descriptor plan bytes are not canonical") from error
    if not isinstance(plan, Mapping) or canonical_plan_bytes(plan) != plan_payload:
        raise InstallerError("bootstrap descriptor plan bytes are not canonical")
    validate_install_plan(plan, bundle_manifest=frozen)
    install_by_path = {str(row["path"]): row for row in frozen["install_roster"]["entries"]}
    artifact_install_by_source = {
        str(row["source_path"]): str(row["install_path"]) for row in frozen["artifacts"]
    }
    rows: list[dict[str, object]] = []
    for source in frozen["source_roster"]["entries"]:
        absolute_path = str(source["path"])
        prefix = STAGED_BUNDLE_ROOT + "/"
        if not absolute_path.startswith(prefix):
            raise InstallerError("bootstrap descriptor source path outside staged root")
        relative_path = absolute_path[len(prefix) :]
        installed_path: str | None = None
        install_prefix = STAGED_INSTALL_TREE + "/"
        if absolute_path.startswith(install_prefix):
            installed_path = "/" + absolute_path[len(install_prefix) :]
        elif absolute_path in artifact_install_by_source:
            installed_path = artifact_install_by_source[absolute_path]
        mode = "0444"
        if installed_path is not None:
            installed = install_by_path.get(installed_path)
            if installed is None:
                raise InstallerError("bootstrap descriptor staged source lacks installed row")
            mode = "0555" if stat.S_IMODE(int(installed["mode"])) & 0o111 else "0444"
        rows.append(
            {
                "path": relative_path,
                "size": int(source["size"]),
                "sha256": str(source["sha256"]),
                "mode": mode,
            }
        )
    rows.extend(
        (
            {
                "path": BOOTSTRAP_MANIFEST_RELATIVE_PATH,
                "size": len(manifest_payload),
                "sha256": "sha256:" + hashlib.sha256(manifest_payload).hexdigest(),
                "mode": "0444",
            },
            {
                "path": BOOTSTRAP_PLAN_RELATIVE_PATH,
                "size": len(plan_payload),
                "sha256": "sha256:" + hashlib.sha256(plan_payload).hexdigest(),
                "mode": "0444",
            },
        )
    )
    rows.sort(key=lambda row: str(row["path"]).encode("utf-8"))
    paths = [str(row["path"]) for row in rows]
    if len(paths) != len(set(paths)):
        raise InstallerError("bootstrap descriptor projected path collision")
    return rows


def admin_invocation_document(
    *,
    descriptor_payload: bytes,
    plan_payload: bytes,
    manifest_payload: bytes,
) -> dict[str, object]:
    """Resolve the non-circular invocation template against three frozen files."""

    descriptor = validate_bootstrap_descriptor_bytes(descriptor_payload)
    descriptor_sha256 = "sha256:" + hashlib.sha256(descriptor_payload).hexdigest()
    plan_sha256 = "sha256:" + hashlib.sha256(plan_payload).hexdigest()
    manifest_sha256 = "sha256:" + hashlib.sha256(manifest_payload).hexdigest()
    if (
        descriptor["bootstrap_sha256"] != BOOTSTRAP_BINARY_SHA256
        or descriptor["plan_sha256"] != plan_sha256
        or descriptor["manifest_sha256"] != manifest_sha256
    ):
        raise InstallerError("admin invocation descriptor binding invalid")
    try:
        plan = json.loads(plan_payload.decode("utf-8"))
        manifest = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallerError("admin invocation canonical inputs invalid") from error
    if (
        not isinstance(plan, Mapping)
        or canonical_plan_bytes(plan) != plan_payload
        or not isinstance(manifest, Mapping)
        or canonical_bundle_bytes(manifest) != manifest_payload
    ):
        raise InstallerError("admin invocation canonical inputs invalid")
    validate_bundle_manifest(manifest, require_frozen=True)
    validate_install_plan(plan, bundle_manifest=manifest)
    expected_files = expected_bootstrap_descriptor_files(
        manifest,
        manifest_payload=manifest_payload,
        plan_payload=plan_payload,
    )
    if descriptor["files"] != expected_files:
        raise InstallerError("admin invocation descriptor file roster mismatch")
    template = admin_invocation_template()
    substitutions = {
        ADMIN_INVOCATION_DIGEST_PLACEHOLDERS["descriptor"]: descriptor_sha256,
        ADMIN_INVOCATION_DIGEST_PLACEHOLDERS["plan"]: plan_sha256,
        ADMIN_INVOCATION_DIGEST_PLACEHOLDERS["bundle"]: manifest_sha256,
    }
    argv = [substitutions.get(str(value), value) for value in template["argv"]]
    return {
        "schema_version": 1,
        "kind": ADMIN_INVOCATION_KIND,
        "status": "frozen",
        "cwd": template["cwd"],
        "inherited_environment": {},
        "stage0_environment": template["stage0_environment"],
        "argv": argv,
        "inputs": {
            "bootstrap_source": copy.deepcopy(template["bootstrap_source"]),
            "bootstrap_target": copy.deepcopy(template["bootstrap_target"]),
            "descriptor": {
                "path": BOOTSTRAP_DESCRIPTOR_PATH,
                "size": len(descriptor_payload),
                "sha256": descriptor_sha256,
            },
            "plan": {
                "path": f"{BOOTSTRAP_SOURCE_ROOT}/{BOOTSTRAP_PLAN_RELATIVE_PATH}",
                "size": len(plan_payload),
                "sha256": plan_sha256,
            },
            "bundle": {
                "path": f"{BOOTSTRAP_SOURCE_ROOT}/{BOOTSTRAP_MANIFEST_RELATIVE_PATH}",
                "size": len(manifest_payload),
                "sha256": manifest_sha256,
            },
        },
        "trusted_install_argv": list(template["trusted_install_argv"]),
        "target_remeasure_before_exec": copy.deepcopy(template["target_remeasure_before_exec"]),
        "pre_main_boundary": template["pre_main_boundary"],
        "in_main_scrub_role": template["in_main_scrub_role"],
    }


def validate_admin_invocation_document(
    document: Mapping[str, object],
    *,
    descriptor_payload: bytes,
    plan_payload: bytes,
    manifest_payload: bytes,
) -> dict[str, object]:
    expected = admin_invocation_document(
        descriptor_payload=descriptor_payload,
        plan_payload=plan_payload,
        manifest_payload=manifest_payload,
    )
    if not isinstance(document, Mapping) or dict(document) != expected:
        raise InstallerError("admin invocation document drifted")
    return copy.deepcopy(expected)


def _validate_installer_bootstrap(value: object) -> dict[str, object]:
    """Validate the fixed, externally trusted Stage-0 boundary declaration."""

    fields = {
        "version",
        "source_root",
        "target_root",
        "descriptor_path",
        "descriptor_magic",
        "descriptor_max_bytes",
        "file_count_max",
        "total_bytes_max",
        "bootstrap_install_path",
        "bootstrap_source_path",
        "bootstrap_source_size",
        "bootstrap_source_sha256",
        "bootstrap_binary_size",
        "bootstrap_binary_sha256",
        "build_provenance",
        "manifest_relative_path",
        "plan_relative_path",
        "python_path",
        "executor_module",
        "python_argv",
        "cwd",
        "sterile_environment",
        "admin_precondition",
        "admin_invocation_template",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise InstallerError("installer bootstrap declaration invalid")
    bootstrap = dict(value)
    expected_python = STAGED_INSTALL_TREE + EXPECTED_ARTIFACT_PATHS["python"]
    fixed = {
        "version": 1,
        "source_root": BOOTSTRAP_SOURCE_ROOT,
        "target_root": STAGED_BUNDLE_ROOT,
        "descriptor_path": BOOTSTRAP_DESCRIPTOR_PATH,
        "descriptor_magic": BOOTSTRAP_DESCRIPTOR_MAGIC,
        "descriptor_max_bytes": BOOTSTRAP_DESCRIPTOR_MAX_BYTES,
        "file_count_max": BOOTSTRAP_FILE_COUNT_MAX,
        "total_bytes_max": BOOTSTRAP_TOTAL_BYTES_MAX,
        "bootstrap_install_path": BOOTSTRAP_BINARY_PATH,
        "bootstrap_source_path": "runtime/w3_installer_bootstrap.c",
        "manifest_relative_path": BOOTSTRAP_MANIFEST_RELATIVE_PATH,
        "plan_relative_path": BOOTSTRAP_PLAN_RELATIVE_PATH,
        "python_path": expected_python,
        "executor_module": BOOTSTRAP_EXECUTOR_MODULE,
        "python_argv": ["-I", "-B", "-m", BOOTSTRAP_EXECUTOR_MODULE],
        "cwd": "/",
        "sterile_environment": {"PATH": BOOTSTRAP_STERILE_PATH},
        "admin_precondition": [
            "trusted-/usr/bin/install-copy-bootstrap-and-descriptor",
            "external-/usr/bin/shasum-remeasure-before-exec",
            "trusted-/usr/bin/env--ignore-environment-before-stage-0-exec",
            "no-repository-python-before-stage-0",
        ],
        "admin_invocation_template": admin_invocation_template(),
    }
    for name, expected in fixed.items():
        if bootstrap[name] != expected:
            raise InstallerError(f"installer bootstrap {name} drifted")
    if (
        bootstrap["bootstrap_source_size"] != BOOTSTRAP_SOURCE_SIZE
        or bootstrap["bootstrap_source_sha256"] != BOOTSTRAP_SOURCE_SHA256
    ):
        raise InstallerError("installer bootstrap source measurement drifted")
    binary_missing = (
        bootstrap["bootstrap_binary_size"] is None and bootstrap["bootstrap_binary_sha256"] is None
    )
    binary_complete = (
        bootstrap["bootstrap_binary_size"] == BOOTSTRAP_BINARY_SIZE
        and bootstrap["bootstrap_binary_sha256"] == BOOTSTRAP_BINARY_SHA256
    )
    provenance = bootstrap["build_provenance"]
    if not binary_missing and not binary_complete:
        raise InstallerError("installer bootstrap binary measurement invalid")
    if provenance is not None:
        provenance_fields = {
            "compiler_path",
            "compiler_size",
            "compiler_sha256",
            "compiler_version",
            "linker_path",
            "linker_size",
            "linker_sha256",
            "linker_version",
            "sdk_path",
            "sdk_version",
            "sdk_settings_path",
            "sdk_settings_size",
            "sdk_settings_sha256",
            "libsystem_link_path",
            "libsystem_link_text",
            "libsystem_link_uid",
            "libsystem_link_gid",
            "libsystem_link_mode",
            "libsystem_link_nlink",
            "libsystem_resolved_path",
            "libsystem_size",
            "libsystem_sha256",
            "commondigest_path",
            "commondigest_size",
            "commondigest_sha256",
            "architecture",
            "deployment_target",
            "argv",
            "environment",
            "cwd",
            "repeat_builds",
            "build_hashes",
            "build_status",
            "reproducible_binary_sha256",
            "mach_o_architectures",
            "linked_dylibs",
            "lc_uuid_present",
            "forbidden_path_strings_present",
        }
        if not isinstance(provenance, Mapping) or set(provenance) != provenance_fields:
            raise InstallerError("installer bootstrap build provenance invalid")
        if (
            provenance["compiler_path"] != BOOTSTRAP_COMPILER_PATH
            or provenance["compiler_version"] != BOOTSTRAP_COMPILER_VERSION
            or provenance["compiler_size"] != BOOTSTRAP_COMPILER_SIZE
            or provenance["compiler_sha256"] != BOOTSTRAP_COMPILER_SHA256
            or provenance["linker_path"] != BOOTSTRAP_LINKER_PATH
            or provenance["linker_version"] != BOOTSTRAP_LINKER_VERSION
            or provenance["linker_size"] != BOOTSTRAP_LINKER_SIZE
            or provenance["linker_sha256"] != BOOTSTRAP_LINKER_SHA256
            or provenance["sdk_path"] != BOOTSTRAP_SDK_PATH
            or provenance["sdk_version"] != BOOTSTRAP_SDK_VERSION
            or provenance["sdk_settings_path"] != f"{BOOTSTRAP_SDK_PATH}/SDKSettings.json"
            or provenance["sdk_settings_size"] != BOOTSTRAP_SDK_SETTINGS_SIZE
            or provenance["sdk_settings_sha256"] != BOOTSTRAP_SDK_SETTINGS_SHA256
            or provenance["libsystem_link_path"] != f"{BOOTSTRAP_SDK_PATH}/usr/lib/libSystem.tbd"
            or provenance["libsystem_link_text"] != "libSystem.B.tbd"
            or provenance["libsystem_link_uid"] != 0
            or provenance["libsystem_link_gid"] != 0
            or provenance["libsystem_link_mode"] != 0o755
            or provenance["libsystem_link_nlink"] != 1
            or provenance["libsystem_resolved_path"]
            != f"{BOOTSTRAP_SDK_PATH}/usr/lib/libSystem.B.tbd"
            or provenance["libsystem_size"] != BOOTSTRAP_LIBSYSTEM_SIZE
            or provenance["libsystem_sha256"] != BOOTSTRAP_LIBSYSTEM_SHA256
            or provenance["commondigest_path"]
            != f"{BOOTSTRAP_SDK_PATH}/usr/include/CommonCrypto/CommonDigest.h"
            or provenance["commondigest_size"] != BOOTSTRAP_COMMONDIGEST_SIZE
            or provenance["commondigest_sha256"] != BOOTSTRAP_COMMONDIGEST_SHA256
            or provenance["architecture"] != BOOTSTRAP_ARCHITECTURE
            or provenance["deployment_target"] != BOOTSTRAP_DEPLOYMENT_TARGET
            or "/Users/" in str(provenance)
            or provenance["cwd"] != "/"
            or provenance["repeat_builds"] != 2
            or provenance["build_status"] != "reproducible-two-builds"
            or provenance["reproducible_binary_sha256"] != bootstrap["bootstrap_binary_sha256"]
            or provenance["argv"] != list(BOOTSTRAP_BUILD_ARGV)
            or provenance["environment"] != dict(BOOTSTRAP_BUILD_ENVIRONMENT)
            or provenance["build_hashes"]
            != [bootstrap["bootstrap_binary_sha256"], bootstrap["bootstrap_binary_sha256"]]
            or provenance["mach_o_architectures"] != [BOOTSTRAP_ARCHITECTURE]
            or provenance["linked_dylibs"] != ["/usr/lib/libSystem.B.dylib"]
            or provenance["lc_uuid_present"] is not False
            or provenance["forbidden_path_strings_present"] is not False
        ):
            raise InstallerError("installer bootstrap build recipe drifted")
        for name in (
            "compiler_size",
            "linker_size",
            "sdk_settings_size",
            "libsystem_size",
            "commondigest_size",
        ):
            if type(provenance[name]) is not int or int(provenance[name]) <= 0:
                raise InstallerError("installer bootstrap toolchain size invalid")
        for name in (
            "compiler_sha256",
            "linker_sha256",
            "sdk_settings_sha256",
            "libsystem_sha256",
            "commondigest_sha256",
            "reproducible_binary_sha256",
        ):
            if (
                not isinstance(provenance[name], str)
                or _PREFIXED_DIGEST_RE.fullmatch(str(provenance[name])) is None
            ):
                raise InstallerError("installer bootstrap toolchain digest invalid")
    if binary_complete != (provenance is not None):
        raise InstallerError("installer bootstrap binary and build provenance are incomplete")
    return bootstrap


def _safe_manifest_path(value: object, *, prefix: str | None = None) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or "\x00" in value
        or "/Users/" in value
    ):
        raise InstallerError("bundle roster path invalid")
    if any(part in {"", ".", ".."} for part in value.split("/")[1:]):
        raise InstallerError("bundle roster path invalid")
    if prefix is not None and value != prefix and not value.startswith(prefix.rstrip("/") + "/"):
        raise InstallerError("bundle roster path outside fixed prefix")
    return value


def _roster_hash(entries: Sequence[Mapping[str, object]]) -> str:
    payload = json.dumps(
        list(entries), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _content_role(install_path: str) -> str:
    role_by_path = {path: role for role, path in EXPECTED_ARTIFACT_PATHS.items()}
    if install_path in role_by_path:
        return role_by_path[install_path]
    if install_path.startswith(PYTHON_ROOT + "/"):
        return "python-runtime-closure"
    if install_path.startswith(RELEASE_ROOT + "/"):
        return "release-capsule-closure"
    return "managed-static-closure"


def release_content_roster_projection(
    install_entries: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Return every immutable preinstall row; only runtime dev/ino are absent."""

    rows = [
        {
            "role": _content_role(str(entry["path"])),
            "install_path": str(entry["path"]),
            "size": int(entry["size"]),
            "sha256": str(entry["sha256"]),
            "uid": int(entry["uid"]),
            "gid": int(entry["gid"]),
            "mode": int(entry["mode"]),
            "nlink": 1,
        }
        for entry in install_entries
    ]
    rows.sort(key=lambda row: (str(row["install_path"]), str(row["role"])))
    return rows


def release_content_roster_digest(install_entries: Sequence[Mapping[str, object]]) -> str:
    """Hash the complete deterministic content projection, never a role sample."""

    rows = release_content_roster_projection(install_entries)
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def expected_directory_roster(
    install_entries: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    paths = set(_FIXED_DIRECTORY_METADATA)
    for entry in install_entries:
        path = str(entry["path"])
        if not path.startswith(APP_SUPPORT_ROOT + "/"):
            continue
        parent = path.rsplit("/", 1)[0]
        while parent.startswith(APP_SUPPORT_ROOT):
            paths.add(parent)
            if parent == APP_SUPPORT_ROOT:
                break
            parent = parent.rsplit("/", 1)[0]
    rows = []
    for path in sorted(paths):
        uid, gid, mode = _FIXED_DIRECTORY_METADATA.get(path, (0, 0, 0o755))
        rows.append({"path": path, "uid": uid, "gid": gid, "mode": mode})
    return rows


def _validate_roster(
    roster: object,
    *,
    label: str,
    installed: bool,
    expected_files: int | None = None,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> list[dict[str, object]]:
    if (
        not isinstance(roster, Mapping)
        or set(roster) != {"files", "bytes", "sha256", "entries"}
        or not isinstance(roster["entries"], list)
    ):
        raise InstallerError(f"{label} invalid")
    fields = (
        {"path", "size", "mode", "uid", "gid", "sha256"}
        if installed
        else {"path", "size", "sha256"}
    )
    entries: list[dict[str, object]] = []
    for item in roster["entries"]:
        if not isinstance(item, Mapping) or set(item) != fields:
            raise InstallerError(f"{label} entry invalid")
        row = dict(item)
        row["path"] = _safe_manifest_path(row["path"])
        if (
            type(row["size"]) is not int
            or int(row["size"]) < 0
            or not isinstance(row["sha256"], str)
            or _PREFIXED_DIGEST_RE.fullmatch(str(row["sha256"])) is None
        ):
            raise InstallerError(f"{label} entry measurement invalid")
        if installed and (
            type(row["mode"]) is not int
            or not stat.S_ISREG(int(row["mode"]))
            or type(row["uid"]) is not int
            or type(row["gid"]) is not int
            or int(row["uid"]) < 0
            or int(row["gid"]) < 0
        ):
            raise InstallerError(f"{label} metadata invalid")
        entries.append(row)
    paths = [str(row["path"]) for row in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)) or not entries:
        raise InstallerError(f"{label} paths invalid")
    measured_files = len(entries)
    measured_bytes = sum(int(row["size"]) for row in entries)
    if roster["files"] != measured_files or roster["bytes"] != measured_bytes:
        raise InstallerError(f"{label} count invalid")
    if expected_files is not None and measured_files != expected_files:
        raise InstallerError(f"{label} file denominator invalid")
    if expected_bytes is not None and measured_bytes != expected_bytes:
        raise InstallerError(f"{label} byte denominator invalid")
    if expected_sha256 is not None and roster["sha256"] != expected_sha256:
        raise InstallerError(f"{label} pinned digest invalid")
    if roster["sha256"] != _roster_hash(entries):
        raise InstallerError(f"{label} digest invalid")
    return entries


def _validate_external_census(
    roster: object,
    *,
    label: str,
    fields: set[str],
    expected_files: int,
    expected_bytes: int,
    expected_sha256: str,
) -> list[dict[str, object]]:
    if (
        not isinstance(roster, Mapping)
        or set(roster) != {"files", "bytes", "sha256", "entries"}
        or not isinstance(roster["entries"], list)
    ):
        raise InstallerError(f"{label} invalid")
    entries: list[dict[str, object]] = []
    for item in roster["entries"]:
        if not isinstance(item, Mapping) or set(item) != fields:
            raise InstallerError(f"{label} entry invalid")
        row = dict(item)
        path = row.get("path")
        if (
            not isinstance(path, str)
            or path.startswith("/")
            or "\x00" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise InstallerError(f"{label} path invalid")
        if (
            type(row.get("size")) is not int
            or int(row["size"]) < 0
            or not isinstance(row.get("sha256"), str)
            or _PREFIXED_DIGEST_RE.fullmatch(str(row["sha256"])) is None
        ):
            raise InstallerError(f"{label} measurement invalid")
        if "mode" in fields and (
            type(row.get("mode")) is not int or int(row["mode"]) < 0 or int(row["mode"]) > 0o7777
        ):
            raise InstallerError(f"{label} mode invalid")
        if "role" in fields and row.get("role") not in {
            "git-archive",
            "loader",
            "runner",
            "tooling",
        }:
            raise InstallerError(f"{label} role invalid")
        entries.append(row)
    paths = [str(row["path"]) for row in entries]
    if (
        paths != sorted(paths)
        or len(paths) != len(set(paths))
        or len(entries) != expected_files
        or sum(int(row["size"]) for row in entries) != expected_bytes
    ):
        raise InstallerError(f"{label} denominator invalid")
    if (
        roster["files"] != expected_files
        or roster["bytes"] != expected_bytes
        or roster["sha256"] != expected_sha256
        or _roster_hash(entries) != expected_sha256
    ):
        raise InstallerError(f"{label} canonical preimage digest invalid")
    return entries


def _is_forbidden_python_import_path(path: str) -> bool:
    basename = path.rsplit("/", 1)[-1]
    lowered = basename.lower()
    return (
        lowered in _FORBIDDEN_PYTHON_IMPORT_BASENAMES
        or lowered.endswith(_FORBIDDEN_PYTHON_IMPORT_SUFFIXES)
        or "/__pycache__/" in path.lower()
    )


def _validate_source_install_map(
    value: object,
    *,
    source_rows: Sequence[Mapping[str, object]],
    install_by_path: Mapping[str, Mapping[str, object]],
) -> set[str]:
    if not isinstance(value, list) or len(value) != len(source_rows):
        raise InstallerError("Python source/install map denominator invalid")
    source_by_path = {str(row["path"]): row for row in source_rows}
    seen_sources: list[str] = []
    seen_targets: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"source_path", "install_path"}:
            raise InstallerError("Python source/install map row invalid")
        source_path = item["source_path"]
        install_path = item["install_path"]
        if not isinstance(source_path, str) or not isinstance(install_path, str):
            raise InstallerError("Python source/install map identity invalid")
        source = source_by_path.get(source_path)
        installed = install_by_path.get(install_path)
        if (
            source is None
            or installed is None
            or not install_path.startswith(PYTHON_ROOT + "/")
            or install_path in seen_targets
            or source["size"] != installed["size"]
            or source["sha256"] != installed["sha256"]
            or installed["uid"] != 0
            or installed["gid"] != 0
            or not stat.S_ISREG(int(installed["mode"]))
            or int(installed["mode"])
            != stat.S_IFREG | (0o555 if int(source["mode"]) & 0o111 else 0o444)
            or int(installed["mode"]) & 0o022
        ):
            raise InstallerError(
                "Python source census is not byte-identical to its staged install target"
            )
        seen_sources.append(source_path)
        seen_targets.add(install_path)
    if seen_sources != sorted(source_by_path) or set(seen_sources) != set(source_by_path):
        raise InstallerError("Python source/install map is not canonical and complete")
    return seen_targets


def _validate_python_install_partition(
    python_runtime: Mapping[str, object],
    *,
    cpython_targets: set[str],
    installed_python_rows: Sequence[Mapping[str, object]],
) -> None:
    installed_paths = {str(row["path"]) for row in installed_python_rows}
    project = python_runtime["project_install_paths"]
    if (
        not isinstance(project, list)
        or any(not isinstance(path, str) for path in project)
        or project != sorted(project)
        or len(project) != len(set(project))
        or not set(REQUIRED_PROJECT_PACKAGE_PATHS).issubset(set(project))
    ):
        raise InstallerError("Python project package roster invalid")
    wheel_map = python_runtime["wheel_install_map"]
    if not isinstance(wheel_map, list) or not wheel_map:
        raise InstallerError("Python wheel/install map invalid")
    wheel_targets: set[str] = set()
    wheel_members: set[tuple[str, str]] = set()
    order: list[tuple[str, str, str]] = []
    dependency_names = {str(row["name"]) for row in PYTHON_DEPENDENCIES}
    for item in wheel_map:
        if not isinstance(item, Mapping) or set(item) != {
            "distribution",
            "member_path",
            "install_path",
        }:
            raise InstallerError("Python wheel/install map row invalid")
        distribution = item["distribution"]
        member_path = item["member_path"]
        install_path = item["install_path"]
        if (
            distribution not in dependency_names
            or not isinstance(member_path, str)
            or member_path.startswith("/")
            or any(part in {"", ".", ".."} for part in member_path.split("/"))
            or not isinstance(install_path, str)
            or not install_path.startswith(PYTHON_SITE_PACKAGES + "/")
            or install_path in wheel_targets
            or (str(distribution), member_path) in wheel_members
        ):
            raise InstallerError("Python wheel/install map identity invalid")
        wheel_targets.add(install_path)
        wheel_members.add((str(distribution), member_path))
        order.append((str(distribution), member_path, install_path))
    if order != sorted(order):
        raise InstallerError("Python wheel/install map is not canonical")
    project_targets = set(project)
    if (
        cpython_targets & wheel_targets
        or cpython_targets & project_targets
        or wheel_targets & project_targets
    ):
        raise InstallerError("Python installed provenance partitions overlap")
    if cpython_targets | wheel_targets | project_targets != installed_paths:
        raise InstallerError(
            "Python installed prefix is not exactly partitioned by pinned provenance"
        )
    executable_paths = python_runtime["executable_paths"]
    if (
        not isinstance(executable_paths, list)
        or any(not isinstance(path, str) for path in executable_paths)
        or executable_paths != sorted(executable_paths)
        or len(executable_paths) != len(set(executable_paths))
        or EXPECTED_ARTIFACT_PATHS["python"] not in executable_paths
        or not set(executable_paths) <= installed_paths
    ):
        raise InstallerError("Python executable path roster invalid")
    actual_executables: set[str] = set()
    for row in installed_python_rows:
        mode = int(row["mode"])
        if row["uid"] != 0 or row["gid"] != 0 or not stat.S_ISREG(mode) or mode & 0o022:
            raise InstallerError(
                "Python installed closure metadata is not root-owned and immutable"
            )
        if mode & 0o111:
            actual_executables.add(str(row["path"]))
    if actual_executables != set(executable_paths):
        raise InstallerError("Python executable mode roster mismatch")


def validate_concrete_policy_bytes(payload: bytes) -> None:
    """Validate the exact rendered Seatbelt preimage, not the template identity."""

    if not isinstance(payload, bytes) or len(payload) != SEATBELT_POLICY_SIZE:
        raise InstallerError("concrete Seatbelt policy size invalid")
    if "sha256:" + hashlib.sha256(payload).hexdigest() != SEATBELT_POLICY_SHA256:
        raise InstallerError("concrete Seatbelt policy digest invalid")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InstallerError("concrete Seatbelt policy is not UTF-8") from error
    required = (
        "(deny default)",
        "(deny network*)",
        "(deny process-fork)",
        f'(literal "{RELEASE_ROOT}/runtime/node")',
        f'(subpath "{RELEASE_ROOT}/capsule")',
        f'(subpath "{RUNS_ACTIVE}")',
    )
    if "(param" in text or "/Users/" in text or any(token not in text for token in required):
        raise InstallerError("concrete Seatbelt policy semantic contract invalid")


def _validate_native_artifact_pins(
    artifacts_by_role: Mapping[str, Mapping[str, object]],
) -> None:
    """Bind the three reproducible release binaries to their exact output pins."""

    for role, (expected_size, expected_sha256) in NATIVE_ARTIFACT_PINS.items():
        artifact = artifacts_by_role.get(role)
        if (
            artifact is None
            or artifact.get("size") != expected_size
            or artifact.get("sha256") != expected_sha256
            or artifact.get("source_size") != expected_size
            or artifact.get("source_sha256") != expected_sha256
        ):
            raise InstallerError(f"pinned native artifact drifted: {role}")


def validate_bundle_manifest(
    document: Mapping[str, Any], *, require_frozen: bool = True
) -> dict[str, Any]:
    """Reject manifest inflation, local paths, secrets and role drift."""
    if not isinstance(document, Mapping):
        raise InstallerError("bundle manifest must be a mapping")
    manifest = copy.deepcopy(dict(document))
    expected_fields = {
        "schema_version",
        "kind",
        "status",
        "outcome",
        "nonclaims",
        "release_content_roster_sha256",
        "principals",
        "services",
        "installer_bootstrap",
        "artifacts",
        "artifact_roster_sha256",
        "python_runtime",
        "python_dependencies",
        "node_capsule",
        "source_roster",
        "install_roster",
        "authority_roster_paths",
        "directories",
        "backend_roster_sha256",
        "bundle_sha256",
    }
    if set(manifest) != expected_fields:
        raise InstallerError("bundle manifest top-level fields drifted")
    if _contains_forbidden_material(manifest):
        raise InstallerError("bundle manifest contains caller path or secret material")
    if manifest["schema_version"] != 1 or manifest["kind"] != "w3-phase-b-install-bundle":
        raise InstallerError("bundle manifest identity drifted")
    status = manifest["status"]
    if status not in {"awaiting-bootstrap-build", "frozen"} or (
        require_frozen and status != "frozen"
    ):
        raise InstallerError("bundle manifest is not frozen")
    if manifest["outcome"] != "PHASE_B_INSTALLABLE_UNEXECUTED":
        raise InstallerError("bundle outcome exceeds L70 authority")
    if manifest["nonclaims"] != list(NONCLAIMS):
        raise InstallerError("bundle nonclaims drifted")
    if (
        not isinstance(manifest["release_content_roster_sha256"], str)
        or _PREFIXED_DIGEST_RE.fullmatch(manifest["release_content_roster_sha256"]) is None
    ):
        raise InstallerError("bundle release content roster digest invalid")
    if manifest["principals"] != _principals_block()["fixed"]:
        raise InstallerError("bundle principal roster drifted")
    if manifest["services"] != [LAUNCHER_PLIST_LABEL, ANCHOR_PLIST_LABEL, BROKER_PLIST_LABEL]:
        raise InstallerError("bundle service roster drifted")
    bootstrap = _validate_installer_bootstrap(manifest["installer_bootstrap"])
    if status == "frozen" and (
        bootstrap["bootstrap_binary_sha256"] is None or bootstrap["build_provenance"] is None
    ):
        raise InstallerError("frozen bundle lacks reproducible Stage-0 binary provenance")
    artifacts = manifest["artifacts"]
    required_roles = set(EXPECTED_ARTIFACT_PATHS)
    if not isinstance(artifacts, list) or not artifacts:
        raise InstallerError("bundle artifact roster empty")
    roles: list[str] = []
    for row in artifacts:
        if not isinstance(row, Mapping) or set(row) != {
            "role",
            "source_path",
            "source_size",
            "source_sha256",
            "install_path",
            "size",
            "sha256",
        }:
            raise InstallerError("bundle artifact row invalid")
        role, path = row["role"], row["install_path"]
        expected_path = EXPECTED_ARTIFACT_PATHS.get(str(role))
        expected_source = f"{STAGED_BUNDLE_ROOT}/artifacts/{role}"
        if (
            not isinstance(role, str)
            or path != expected_path
            or row["source_path"] != expected_source
        ):
            raise InstallerError("bundle artifact identity invalid")
        if (
            type(row["size"]) is not int
            or row["size"] <= 0
            or not isinstance(row["sha256"], str)
            or _PREFIXED_DIGEST_RE.fullmatch(row["sha256"]) is None
            or row["source_size"] != row["size"]
            or row["source_sha256"] != row["sha256"]
        ):
            raise InstallerError("bundle artifact measurement invalid")
        roles.append(role)
    if set(roles) != required_roles or len(roles) != len(required_roles):
        raise InstallerError("bundle artifact roles missing, duplicated or extra")
    artifact_material = sorted(
        [
            {
                "role": row["role"],
                "source_path": row["source_path"],
                "source_size": row["source_size"],
                "source_sha256": row["source_sha256"],
                "install_path": row["install_path"],
                "size": row["size"],
                "sha256": row["sha256"],
            }
            for row in artifacts
        ],
        key=lambda row: str(row["role"]),
    )
    expected_artifact_roster = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                artifact_material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    if manifest["artifact_roster_sha256"] != expected_artifact_roster:
        raise InstallerError("bundle artifact roster digest mismatch")
    roster_entries = {
        "source_roster": _validate_roster(
            manifest["source_roster"], label="source_roster", installed=False
        ),
        "install_roster": _validate_roster(
            manifest["install_roster"], label="install_roster", installed=True
        ),
    }
    source_by_path = {str(row["path"]): row for row in roster_entries["source_roster"]}
    install_by_path = {str(row["path"]): row for row in roster_entries["install_roster"]}
    if manifest["release_content_roster_sha256"] != release_content_roster_digest(
        roster_entries["install_roster"]
    ):
        raise InstallerError("bundle full release content projection digest mismatch")
    allowed_install_paths = set(EXPECTED_ARTIFACT_PATHS.values())
    for install_path in install_by_path:
        if (
            install_path not in allowed_install_paths
            and not install_path.startswith(PYTHON_ROOT + "/")
            and not install_path.startswith(RELEASE_ROOT + "/")
        ):
            raise InstallerError("install roster path outside exact managed roles or closures")
    for install_path, install_row in install_by_path.items():
        staged_row = source_by_path.get(STAGED_INSTALL_TREE + install_path)
        if (
            staged_row is None
            or staged_row["size"] != install_row["size"]
            or staged_row["sha256"] != install_row["sha256"]
        ):
            raise InstallerError("installed roster row lacks exact staged preimage")
    for artifact in artifacts:
        source_row = source_by_path.get(str(artifact["source_path"]))
        install_row = install_by_path.get(str(artifact["install_path"]))
        expected_metadata = EXPECTED_ARTIFACT_METADATA[str(artifact["role"])]
        if (
            source_row is None
            or install_row is None
            or source_row["size"] != artifact["source_size"]
            or source_row["sha256"] != artifact["source_sha256"]
            or install_row["size"] != artifact["size"]
            or install_row["sha256"] != artifact["sha256"]
            or (install_row["uid"], install_row["gid"], install_row["mode"]) != expected_metadata
        ):
            raise InstallerError("artifact not cross-bound to complete rosters")
    artifacts_by_role = {str(row["role"]): row for row in artifacts}
    if (
        artifacts_by_role["python"]["size"] != PYTHON_EXECUTABLE_SIZE
        or artifacts_by_role["python"]["sha256"] != PYTHON_EXECUTABLE_SHA256
    ):
        raise InstallerError("pinned Python executable drifted")
    if (
        artifacts_by_role["node"]["size"] != NODE_SIZE
        or artifacts_by_role["node"]["sha256"] != NODE_SHA256
    ):
        raise InstallerError("pinned Node executable drifted")
    if (
        artifacts_by_role["policy"]["size"] != SEATBELT_POLICY_SIZE
        or artifacts_by_role["policy"]["sha256"] != SEATBELT_POLICY_SHA256
    ):
        raise InstallerError("concrete Seatbelt artifact drifted")
    if (
        artifacts_by_role["broker-socket-shim"]["sha256"]
        == artifacts_by_role["anchor-socket-shim"]["sha256"]
    ):
        raise InstallerError("broker and anchor shim binaries must be distinct")
    python_hint = manifest.get("python_runtime")
    python_source_hint = (
        python_hint.get("source_census") if isinstance(python_hint, Mapping) else None
    )
    node_hint = manifest.get("node_capsule")
    node_source_hint = node_hint.get("source_census") if isinstance(node_hint, Mapping) else None
    if (
        isinstance(python_source_hint, Mapping)
        and python_source_hint.get("files") == 1_808
        and python_source_hint.get("bytes") == 44_064_036
        and python_source_hint.get("sha256")
        == "sha256:b632ae57ee6c013e720fc699380923d807cafa6e82df6b1e96ab9163d7193333"
        and isinstance(node_source_hint, Mapping)
        and node_source_hint.get("files") == 1_827
        and node_source_hint.get("bytes") == 8_922_291
        and node_source_hint.get("sha256") == NODE_CAPSULE_ROSTER_SHA256
    ):
        _validate_native_artifact_pins(artifacts_by_role)
    python_runtime = manifest["python_runtime"]
    if not isinstance(python_runtime, Mapping) or set(python_runtime) != {
        "implementation",
        "version",
        "source_census",
        "source_install_map",
        "wheel_install_map",
        "project_install_paths",
        "executable_paths",
        "staged_roster",
        "symlink_policy",
        "editable_paths_allowed",
    }:
        raise InstallerError("Python runtime declaration invalid")
    if (
        python_runtime["implementation"] != "CPython"
        or python_runtime["version"] != PYTHON_VERSION
        or python_runtime["symlink_policy"] != "no-symlinks-normalize-aliases-before-freeze"
        or python_runtime["editable_paths_allowed"] is not False
    ):
        raise InstallerError("Python runtime identity drifted")
    python_source = _validate_external_census(
        python_runtime["source_census"],
        label="Python source census",
        fields={"path", "size", "sha256", "mode"},
        expected_files=PYTHON_SOURCE_FILES,
        expected_bytes=PYTHON_SOURCE_BYTES,
        expected_sha256=PYTHON_SOURCE_ROSTER_SHA256,
    )
    python_staged = _validate_roster(
        python_runtime["staged_roster"], label="Python staged roster", installed=True
    )
    if any(
        source_by_path.get(f"{PYTHON_SOURCE_CENSUS_ROOT}/{row['path']}")
        != {
            "path": f"{PYTHON_SOURCE_CENSUS_ROOT}/{row['path']}",
            "size": row["size"],
            "sha256": row["sha256"],
        }
        for row in python_source
    ):
        raise InstallerError("Python source census is not bound to source roster")
    installed_python_rows = [
        row
        for row in roster_entries["install_roster"]
        if str(row["path"]).startswith(PYTHON_ROOT + "/")
    ]
    if python_staged != installed_python_rows:
        raise InstallerError("Python staged roster is not the complete installed Python prefix")
    cpython_targets = _validate_source_install_map(
        python_runtime["source_install_map"],
        source_rows=python_source,
        install_by_path=install_by_path,
    )
    _validate_python_install_partition(
        python_runtime,
        cpython_targets=cpython_targets,
        installed_python_rows=installed_python_rows,
    )
    python_paths = {str(row["path"]) for row in python_staged}
    if not set(REQUIRED_SITE_PACKAGE_PATHS).issubset(python_paths) or any(
        _is_forbidden_python_import_path(path) for path in python_paths
    ):
        raise InstallerError("Python import closure incomplete or contains startup injection")

    dependencies = manifest["python_dependencies"]
    if not isinstance(dependencies, list) or len(dependencies) != len(PYTHON_DEPENDENCIES):
        raise InstallerError("Python dependency wheel roster invalid")
    pinned_dependencies = {str(row["name"]): dict(row) for row in PYTHON_DEPENDENCIES}
    for dependency in dependencies:
        if not isinstance(dependency, Mapping) or set(dependency) != {
            "name",
            "version",
            "wheel_path",
            "wheel_size",
            "wheel_sha256",
        }:
            raise InstallerError("Python dependency wheel row invalid")
        pinned = pinned_dependencies.get(str(dependency["name"]))
        source_row = source_by_path.get(str(dependency["wheel_path"]))
        if (
            pinned is None
            or dependency["version"] != pinned["version"]
            or dependency["wheel_sha256"] != pinned["wheel_sha256"]
            or dependency["wheel_path"] != WHEEL_SOURCE_PATHS[str(dependency["name"])]
            or type(dependency["wheel_size"]) is not int
            or int(dependency["wheel_size"]) <= 0
            or source_row
            != {
                "path": dependency["wheel_path"],
                "size": dependency["wheel_size"],
                "sha256": dependency["wheel_sha256"],
            }
        ):
            raise InstallerError("Python dependency wheel provenance drifted")
    if [str(row["name"]) for row in dependencies] != [
        str(row["name"]) for row in PYTHON_DEPENDENCIES
    ]:
        raise InstallerError("Python dependency wheel order drifted")
    node_capsule = manifest["node_capsule"]
    if not isinstance(node_capsule, Mapping) or set(node_capsule) != {
        "node_version",
        "node_sha256",
        "source_census",
        "evidence_status",
        "host_credit",
    }:
        raise InstallerError("Node capsule declaration invalid")
    if (
        node_capsule["node_version"] != NODE_VERSION
        or node_capsule["node_sha256"] != NODE_SHA256
        or node_capsule["evidence_status"] != "blocked-static-capsule-only"
        or node_capsule["host_credit"] is not False
    ):
        raise InstallerError("Node capsule identity or nonclaim drifted")
    node_source = _validate_external_census(
        node_capsule["source_census"],
        label="Node capsule source census",
        fields={"mode", "path", "role", "sha256", "size"},
        expected_files=NODE_CAPSULE_FILES,
        expected_bytes=NODE_CAPSULE_BYTES,
        expected_sha256=NODE_CAPSULE_ROSTER_SHA256,
    )
    if any(
        source_by_path.get(f"{NODE_SOURCE_CENSUS_ROOT}/{row['path']}")
        != {
            "path": f"{NODE_SOURCE_CENSUS_ROOT}/{row['path']}",
            "size": row["size"],
            "sha256": row["sha256"],
        }
        for row in node_source
    ):
        raise InstallerError("Node capsule census is not bound to source roster")
    for row in node_source:
        installed = install_by_path.get(f"{RELEASE_ROOT}/capsule/{row['path']}")
        if (
            installed is None
            or installed["size"] != row["size"]
            or installed["sha256"] != row["sha256"]
            or installed["uid"] != 0
            or installed["gid"] != 0
            or installed["mode"] != stat.S_IFREG | int(row["mode"])
        ):
            raise InstallerError(
                "Node capsule census is not byte-identical to the installed capsule closure"
            )
    expected_release_paths = {
        installer_path
        for installer_path in (
            EXPECTED_ARTIFACT_PATHS["node"],
            EXPECTED_ARTIFACT_PATHS["policy"],
            *(f"{RELEASE_ROOT}/capsule/{row['path']}" for row in node_source),
        )
    }
    actual_release_paths = {path for path in install_by_path if path.startswith(RELEASE_ROOT + "/")}
    if actual_release_paths != expected_release_paths:
        raise InstallerError("installed release closure has missing or extra paths")
    expected_source_paths = {
        *(str(row["source_path"]) for row in artifacts),
        *(STAGED_INSTALL_TREE + path for path in install_by_path),
        *(f"{PYTHON_SOURCE_CENSUS_ROOT}/{row['path']}" for row in python_source),
        *(f"{NODE_SOURCE_CENSUS_ROOT}/{row['path']}" for row in node_source),
        *WHEEL_SOURCE_PATHS.values(),
    }
    if set(source_by_path) != expected_source_paths or any(
        not path.startswith(STAGED_BUNDLE_ROOT + "/") for path in source_by_path
    ):
        raise InstallerError("source roster has missing, extra or non-staged paths")
    if manifest["directories"] != expected_directory_roster(roster_entries["install_roster"]):
        raise InstallerError("directory roster is incomplete or metadata drifted")
    expected_authority_paths = sorted(
        authority_roster_path_map(roster_entries["install_roster"]).values()
    )
    if manifest["authority_roster_paths"] != expected_authority_paths:
        raise InstallerError("authority executable/import closure path roster drifted")
    if manifest["backend_roster_sha256"] != backend_roster_digest():
        raise InstallerError("backend roster digest invalid")
    expected = (
        "sha256:" + hashlib.sha256(canonical_bundle_bytes(manifest, omit_digest=True)).hexdigest()
    )
    if manifest["bundle_sha256"] != expected:
        raise InstallerError("bundle manifest digest mismatch")
    return manifest


def canonical_plan_bytes(plan: Mapping[str, Any]) -> bytes:
    return json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def plan_digest(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


__all__ = [
    "ADMIN_INVOCATION_KIND",
    "ADMIN_INVOCATION_TEMPLATE_KIND",
    "ANCHOR_GID",
    "ANCHOR_LOG_PATH",
    "ANCHOR_PLIST_LABEL",
    "ANCHOR_PRINCIPAL",
    "ANCHOR_UID",
    "APP_SUPPORT_ROOT",
    "ANCHOR_CONFIG_PATH",
    "ANCHOR_INSTANCE_ID",
    "AUTHORITY_CANDIDATE_PATH",
    "AUTHORITY_ID",
    "AUTHORITY_LOGICAL_PATHS",
    "AUTHORITY_REGISTRY_PATH",
    "BROKER_CONFIG_PATH",
    "BROKER_GID",
    "BROKER_LEDGER_PATH",
    "BROKER_PLIST_LABEL",
    "BROKER_PRINCIPAL",
    "BROKER_UID",
    "CALLER_GID",
    "CALLER_GROUP",
    "CALLER_UID",
    "FIXED_PRINCIPALS",
    "EXPECTED_ARTIFACT_METADATA",
    "EXPECTED_ARTIFACT_PATHS",
    "INSTALL_STEP_IDS",
    "INSTALL_TRANSITION_JOURNAL_PATH",
    "InstallerError",
    "MACOS_BACKEND_COMMAND_CONTRACT",
    "MACOS_BACKEND_OPERATION_ROSTER",
    "NATIVE_ARTIFACT_PINS",
    "NONCLAIMS",
    "PUBLIC_FIXTURE_REGISTRY_PATH",
    "PUBLIC_RECEIPT_JOURNAL_PATH",
    "PUBLICATION_ACTIVE",
    "RELEASE_ID",
    "RELEASE_ROOT",
    "RETAINED_ON_ROLLBACK",
    "ROLLBACK_STEP_IDS",
    "RUNNER_GID",
    "RUNNER_PRINCIPAL",
    "BOOTSTRAP_ARCHITECTURE",
    "BOOTSTRAP_BINARY_SOURCE_PATH",
    "BOOTSTRAP_BINARY_SOURCE_ROOT",
    "BOOTSTRAP_BINARY_PATH",
    "BOOTSTRAP_BINARY_SHA256",
    "BOOTSTRAP_BINARY_SIZE",
    "BOOTSTRAP_BUILD_ARGV",
    "BOOTSTRAP_BUILD_ENVIRONMENT",
    "BOOTSTRAP_COMMONDIGEST_SHA256",
    "BOOTSTRAP_COMMONDIGEST_SIZE",
    "BOOTSTRAP_COMPILER_PATH",
    "BOOTSTRAP_COMPILER_SHA256",
    "BOOTSTRAP_COMPILER_SIZE",
    "BOOTSTRAP_COMPILER_VERSION",
    "BOOTSTRAP_DEPLOYMENT_TARGET",
    "BOOTSTRAP_DESCRIPTOR_MAGIC",
    "BOOTSTRAP_DESCRIPTOR_MAX_BYTES",
    "BOOTSTRAP_DESCRIPTOR_PATH",
    "BOOTSTRAP_EXECUTOR_MODULE",
    "BOOTSTRAP_FILE_COUNT_MAX",
    "BOOTSTRAP_LIBSYSTEM_SHA256",
    "BOOTSTRAP_LIBSYSTEM_SIZE",
    "BOOTSTRAP_LINKER_PATH",
    "BOOTSTRAP_LINKER_SHA256",
    "BOOTSTRAP_LINKER_SIZE",
    "BOOTSTRAP_LINKER_VERSION",
    "BOOTSTRAP_MANIFEST_RELATIVE_PATH",
    "BOOTSTRAP_PLAN_RELATIVE_PATH",
    "BOOTSTRAP_SDK_PATH",
    "BOOTSTRAP_SDK_SETTINGS_SHA256",
    "BOOTSTRAP_SDK_SETTINGS_SIZE",
    "BOOTSTRAP_SDK_VERSION",
    "BOOTSTRAP_SOURCE_ROOT",
    "BOOTSTRAP_SOURCE_SHA256",
    "BOOTSTRAP_SOURCE_SIZE",
    "BOOTSTRAP_STERILE_PATH",
    "BOOTSTRAP_TOTAL_BYTES_MAX",
    "PYTHON_ROOT",
    "PYTHON_SITE_PACKAGES",
    "REQUIRED_SITE_PACKAGE_PATHS",
    "RUNNER_UID",
    "RUNS_ACTIVE",
    "RUNS_PARENT",
    "SEATBELT_POLICY_SHA256",
    "SIGNING_KEY_PATH",
    "STAGED_BUNDLE_ROOT",
    "STAGED_INSTALL_TREE",
    "admin_invocation_document",
    "admin_invocation_template",
    "bootstrap_descriptor_bytes",
    "canonical_bundle_bytes",
    "canonical_plan_bytes",
    "expected_bootstrap_descriptor_files",
    "authority_logical_path",
    "authority_roster_path_map",
    "backend_roster_digest",
    "expected_directory_roster",
    "identity_conflict_preconditions",
    "plan_digest",
    "plan_install",
    "plan_rollback",
    "plan_upgrade",
    "release_content_roster_digest",
    "release_content_roster_projection",
    "validate_admin_invocation_document",
    "validate_bootstrap_descriptor_bytes",
    "validate_bundle_manifest",
    "validate_concrete_policy_bytes",
    "validate_config",
    "validate_install_plan",
    "validate_launchd_plist_bytes",
]
