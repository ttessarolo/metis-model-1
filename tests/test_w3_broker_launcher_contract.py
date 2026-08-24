from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "runtime/w3_privileged_launcher.c"


def _source() -> str:
    return SOURCE_PATH.read_text(encoding="utf-8")


def test_launcher_contract_phase_a_is_inert_by_default() -> None:
    source = _source()
    assert "#ifndef W3_PRIVILEGED_LAUNCHER_PHASE_B" in source
    assert "return EX_CONFIG;" in source
    assert "transport not installed" in source


def test_launcher_contract_uses_fixed_bounded_binary_frame() -> None:
    source = _source()
    assert '#define W3_LAUNCHER_MAGIC "M1W3LCH"' in source
    assert "#define W3_LAUNCHER_PROTOCOL_VERSION 1U" in source
    assert "#define W3_LAUNCHER_MAX_PAYLOAD_BYTES (4U * 1024U * 1024U)" in source
    assert "struct w3_launcher_request_header" in source


def test_launcher_contract_has_no_json_semantic_or_signing_surface() -> None:
    source = _source().lower()
    forbidden = (
        "json.h",
        "json_parse",
        "candidate_id",
        "semantic_spec",
        "private_key",
        "sign_receipt",
        "ed25519",
        "hmac",
    )
    assert all(token not in source for token in forbidden)


def test_launcher_contract_authenticates_exact_broker_peer() -> None:
    source = _source()
    assert "getpeereid(descriptor, &peer_uid, &peer_gid)" in source
    assert "peer_uid != W3_BROKER_UID || peer_gid != W3_BROKER_GID" in source
    assert "errno = EACCES;" in source


def test_launcher_contract_does_not_accept_paths_argv_env_or_ancillary_fds() -> None:
    source = _source()
    header = source.split("struct w3_launcher_request_header", 1)[1].split("};", 1)[0]
    assert not re.search(r"path|argv|env|descriptor|fd", header, re.IGNORECASE)
    assert "recvmsg(" not in source
    assert "SCM_RIGHTS" not in source


def test_launcher_contract_selects_only_fixed_installed_paths() -> None:
    source = _source()
    assert '#define W3_RELEASE_ROOT "/Library/Application Support/MetisModel1/' in source
    assert "#define W3_NODE_PATH W3_RELEASE_ROOT" in source
    assert "#define W3_LOADER_PATH W3_RELEASE_ROOT" in source
    assert "#define W3_RUNNER_PATH W3_RELEASE_ROOT" in source
    assert "installed_paths[index][0] != '/'" in source


def test_launcher_contract_drops_groups_gid_uid_in_irreversible_order() -> None:
    source = _source()
    function = source.split("static int w3_drop_irreversibly_to_runner", 1)[1]
    setgroups_at = function.index("setgroups(0, NULL)")
    setgid_at = function.index("setgid(W3_RUNNER_GID)")
    setuid_at = function.index("setuid(W3_RUNNER_UID)")
    regain_at = function.index("setuid(0)")
    assert setgroups_at < setgid_at < setuid_at < regain_at
    assert "errno != EPERM" in function


def test_launcher_contract_closes_every_non_stdio_child_fd() -> None:
    source = _source()
    function = source.split("static int w3_close_child_fds", 1)[1]
    assert "STDERR_FILENO + 1" in function
    assert "close(descriptor)" in function
    assert "errno != EBADF" in function


def test_launcher_contract_phase_b_placeholder_is_fail_closed() -> None:
    source = _source()
    function = source.split("static int w3_launch_registered_node", 1)[1]
    function = function.split("#ifdef W3_PRIVILEGED_LAUNCHER_PHASE_B", 1)[0]
    assert "errno = ENOTSUP;" in function
    assert "return -1;" in function
    assert "exec" not in function.lower()


def test_launcher_contract_is_clang_syntax_clean_without_a_binary() -> None:
    common = [
        "/usr/bin/clang",
        "-std=c17",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-fsyntax-only",
        str(SOURCE_PATH),
    ]
    phase_a = subprocess.run(common, check=False, capture_output=True, text=True)
    assert phase_a.returncode == 0, phase_a.stderr

    phase_b_contract = [
        *common[:-1],
        "-DW3_PRIVILEGED_LAUNCHER_PHASE_B=1",
        "-DW3_BROKER_UID=499",
        "-DW3_BROKER_GID=499",
        "-DW3_RUNNER_UID=498",
        "-DW3_RUNNER_GID=498",
        common[-1],
    ]
    phase_b = subprocess.run(
        phase_b_contract,
        check=False,
        capture_output=True,
        text=True,
    )
    assert phase_b.returncode == 0, phase_b.stderr
