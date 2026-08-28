from __future__ import annotations

import copy
import json
import os
import socket
import struct
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from metis_model1 import video_frontier_boundary as boundary

SENTINEL = "PUBLIC-SYNTHETIC-adversarial0123456789"


@pytest.fixture(scope="module")
def live_receipt() -> dict[str, Any]:
    if sys.platform != "darwin" or not boundary.SANDBOX_EXEC.is_file():
        pytest.skip("the real Seatbelt proof is macOS-only")
    return boundary.run_synthetic_frontier_egress_boundary(sentinel=SENTINEL)


def _rehash(receipt: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = boundary._canonical_hash(body)
    return receipt


def test_real_peers_are_egress_denied_while_socketpair_work_survives(
    live_receipt: dict[str, Any],
) -> None:
    boundary.validate_frontier_egress_receipt(live_receipt)

    assert live_receipt["gate"] == "VIDEO_FRONTIER_EGRESS_SYNTHETIC_BOUNDARY_VALID"
    assert live_receipt["status"] == "VALID"
    assert live_receipt["evidence_scope"] == "public_synthetic_process_boundary"
    assert live_receipt["boundary"]["policy_mode"] == "deny-default"
    assert live_receipt["boundary"]["network_rule"] == "deny network*"
    assert live_receipt["boundary"]["transport"] == "anonymous_inherited_unix_socketpair"
    assert live_receipt["controls"] == {
        "positive_control_scope": "supervisor_outside_seatbelt",
        "dns_positive_control": "resolved",
        "tcp_positive_control": "connected",
        "dns_attempted": 2,
        "dns_denied": 2,
        "tcp_attempted": 2,
        "tcp_denied": 2,
        "total_attempted": 4,
        "total_denied": 4,
        "sandbox_network_successes": 0,
        "unexpected_attempts": 0,
        "listener_positive_control_connections": 1,
        "listener_sandbox_connections": 0,
    }

    processes = live_receipt["processes"]
    assert [process["role"] for process in processes] == ["runner", "model"]
    assert len({process["pid"] for process in processes}) == 2
    assert {process["work_channel"] for process in processes} == {"valid"}
    assert {process["payload_sha256"] for process in processes} == {
        live_receipt["sentinel"]["input_sha256"]
    }
    for process in processes:
        assert process["fd_roster_valid"] is True
        assert process["observed_fd_count"] == 5
        assert process["core_limit_zero"] is True
        assert process["file_limit_zero"] is True
        assert process["open_file_limit"] == boundary.MAX_OPEN_FILES
        assert process["peer_socket_valid"] is True
        assert process["control_socket_valid"] is True
        assert process["dns_canary"]["status"] == "denied"
        assert process["tcp_canary"] == {
            "status": "denied",
            "error_class": "PermissionError",
            "errno": 1,
        }


def test_receipt_binds_the_executed_source_runtime_policy_and_sandbox(
    live_receipt: dict[str, Any],
) -> None:
    source = boundary._measure_regular_file(boundary.SOURCE_PATH, "test source")
    python = boundary._measure_regular_file(Path(sys.executable), "test Python")
    sandbox = boundary._measure_regular_file(boundary.SANDBOX_EXEC, "test sandbox-exec")
    policy = boundary.build_sandbox_policy(source_path=source.path, python_executable=python.path)

    assert live_receipt["boundary"]["source_sha256"] == source.sha256
    assert live_receipt["boundary"]["python_executable_sha256"] == python.sha256
    assert live_receipt["boundary"]["sandbox_exec_sha256"] == sandbox.sha256
    assert live_receipt["boundary"]["policy_sha256"] == boundary._raw_hash(policy.encode("utf-8"))
    assert all(
        process["policy_sha256"] == live_receipt["boundary"]["policy_sha256"]
        for process in live_receipt["processes"]
    )


def test_seatbelt_policy_is_deny_default_without_write_or_network_allow() -> None:
    policy = boundary.build_sandbox_policy()

    assert policy.startswith("(version 1) (deny default) (deny network*)")
    assert "(deny process-fork)" in policy
    assert "(allow default)" not in policy
    assert "(allow network" not in policy
    assert "(allow file-write" not in policy
    assert policy.count("(allow process-exec") == 1
    assert str(boundary.SOURCE_PATH) in policy


def test_child_environment_is_literal_and_ignores_parent_poison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poison = {
        "HOME": "/private/sentinel-home",
        "HTTPS_PROXY": "https://sentinel.invalid",
        "NO_PROXY": "*",
        "DYLD_INSERT_LIBRARIES": "/private/sentinel.dylib",
        "PYTHONPATH": "/private/sentinel-pythonpath",
        "OPENAI_API_KEY": "sentinel-secret",
        "AWS_SESSION_TOKEN": "sentinel-token",
    }
    for key, value in poison.items():
        monkeypatch.setenv(key, value)

    environment = boundary.build_child_environment()

    assert environment == boundary.FIXED_CHILD_ENVIRONMENT
    assert not set(poison).intersection(environment)
    assert boundary._canonical_hash(environment) == boundary._canonical_hash(
        boundary.FIXED_CHILD_ENVIRONMENT
    )
    if sys.platform == "darwin" and boundary.SANDBOX_EXEC.is_file():
        poisoned_receipt = boundary.run_synthetic_frontier_egress_boundary(
            sentinel="PUBLIC-SYNTHETIC-poisonedparent1234"
        )
        assert poisoned_receipt["boundary"]["environment_sha256"] == boundary._canonical_hash(
            boundary.FIXED_CHILD_ENVIRONMENT
        )
        public_raw = boundary._canonical_bytes(poisoned_receipt)
        assert all(
            value.encode("utf-8") not in public_raw for value in poison.values() if len(value) >= 8
        )


def test_live_children_observed_only_the_fixed_environment(
    live_receipt: dict[str, Any],
) -> None:
    expected = boundary._canonical_hash(boundary.FIXED_CHILD_ENVIRONMENT)
    assert live_receipt["boundary"]["environment_keys"] == sorted(boundary.FIXED_CHILD_ENVIRONMENT)
    assert live_receipt["boundary"]["environment_sha256"] == expected
    assert {process["environment_sha256"] for process in live_receipt["processes"]} == {expected}


def test_public_receipt_and_child_channels_do_not_contain_the_sentinel(
    live_receipt: dict[str, Any],
) -> None:
    raw = boundary._canonical_bytes(live_receipt)

    assert SENTINEL.encode("utf-8") not in raw
    assert str(Path.home()).encode("utf-8") not in raw
    assert live_receipt["sentinel"] == {
        "kind": "public_synthetic_canary",
        "input_sha256": boundary._raw_hash(SENTINEL.encode("utf-8")),
        "receipt_occurrences": 0,
        "child_stdout_occurrences": 0,
        "child_stderr_occurrences": 0,
        "control_report_occurrences": 0,
    }


def test_receipt_explicitly_refuses_model_checkpoint_private_and_promotion_claims(
    live_receipt: dict[str, Any],
) -> None:
    assert live_receipt["nonclaims"] == list(boundary.NONCLAIMS)
    assert {
        "no_real_model_loaded",
        "no_adapter_loaded",
        "no_checkpoint_verified",
        "no_private_source_processed",
        "no_production_frontier_egress_gate",
        "no_accuracy_or_promotion_claim",
    }.issubset(live_receipt["nonclaims"])


def test_receipt_self_hash_tampering_is_rejected(live_receipt: dict[str, Any]) -> None:
    tampered = copy.deepcopy(live_receipt)
    tampered["receipt_sha256"] = "sha256:" + "0" * 64

    with pytest.raises(boundary.FrontierBoundaryError, match="self-hash"):
        boundary.validate_frontier_egress_receipt(tampered)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"status": "INVALID"}),
        lambda value: value["controls"].update({"total_denied": 3}),
        lambda value: value["boundary"].update({"policy_mode": "allow-default"}),
        lambda value: value["boundary"].update({"transport": "tcp"}),
        lambda value: value["processes"][0].update({"fd_roster_valid": False}),
        lambda value: value["processes"][1].update({"environment_sha256": "sha256:" + "0" * 64}),
        lambda value: value["processes"][1].update({"pid": value["processes"][0]["pid"]}),
        lambda value: value["sentinel"].update({"control_report_occurrences": 1}),
        lambda value: value.update({"nonclaims": value["nonclaims"][:-1]}),
        lambda value: value.update({"unapproved": "field"}),
    ],
    ids=[
        "status",
        "canary-count",
        "policy-mode",
        "transport",
        "fd-roster",
        "environment",
        "same-pid",
        "sentinel-leak",
        "missing-nonclaim",
        "extra-field",
    ],
)
def test_semantic_tampering_is_rejected_even_after_rehash(
    live_receipt: dict[str, Any], mutation: Any
) -> None:
    tampered = copy.deepcopy(live_receipt)
    mutation(tampered)
    _rehash(tampered)

    with pytest.raises(boundary.FrontierBoundaryError):
        boundary.validate_frontier_egress_receipt(tampered)


@pytest.mark.parametrize(
    "sentinel",
    [
        "private-value",
        "PUBLIC-SYNTHETIC-short",
        "PUBLIC-SYNTHETIC-abcdefghijklmnop/escape",
        "PUBLIC-SYNTHETIC-abcdefghijklmnop\nsecond-line",
    ],
)
def test_non_public_or_unsafe_sentinels_fail_before_process_execution(sentinel: str) -> None:
    with pytest.raises(boundary.FrontierBoundaryError, match="public-synthetic"):
        boundary.run_synthetic_frontier_egress_boundary(sentinel=sentinel)


def test_child_request_rejects_unapproved_secret_field() -> None:
    request = {
        "schema_version": boundary.SCHEMA_VERSION,
        "role": "runner",
        "channel_sha256": "sha256:" + "1" * 64,
        "expected_environment_sha256": "sha256:" + "2" * 64,
        "expected_policy_sha256": "sha256:" + "3" * 64,
        "expected_source_sha256": "sha256:" + "4" * 64,
        "expected_python_executable_sha256": "sha256:" + "5" * 64,
        "tcp_port": 1234,
        "synthetic_payload": SENTINEL,
        "api_key": "must-not-cross",
    }

    with pytest.raises(boundary.FrontierBoundaryError, match="allowlist"):
        boundary._validate_child_request(request, "runner")


@pytest.mark.parametrize(
    "argv",
    [
        ("module.py", "--isolated-child", "unknown", "3", "4"),
        ("module.py", "--isolated-child", "runner", "3", "3"),
        ("module.py", "--isolated-child", "model", "2", "4"),
        ("module.py", "--isolated-child", "model", "3", "64"),
        ("module.py", "--isolated-child", "model", "3", "4", "extra"),
    ],
)
def test_child_entrypoint_rejects_role_fd_and_argument_smuggling(argv: tuple[str, ...]) -> None:
    with pytest.raises(boundary.FrontierBoundaryError):
        boundary._parse_child_argv(argv)


def test_channel_rejects_noncanonical_json() -> None:
    parent, child = socket.socketpair()
    try:
        raw = b'{"z":1,"a":2}'
        parent.sendall(struct.pack(">I", len(raw)) + raw)
        with pytest.raises(boundary.FrontierBoundaryError, match="canonical"):
            boundary._recv_json(child, timeout=1.0)
    finally:
        parent.close()
        child.close()


def test_file_identity_comparison_detects_a_postflight_digest_change() -> None:
    measured = boundary._measure_regular_file(boundary.SOURCE_PATH, "test source")
    tampered = replace(measured, sha256="sha256:" + "0" * 64)

    assert boundary._same_file_identity(measured, measured)
    assert not boundary._same_file_identity(measured, tampered)


def test_receipt_is_canonical_json_and_contains_only_digest_not_payload(
    live_receipt: dict[str, Any],
) -> None:
    raw = boundary._canonical_bytes(live_receipt)
    decoded = json.loads(raw)

    assert decoded == live_receipt
    assert raw == boundary._canonical_bytes(decoded)
    assert SENTINEL not in raw.decode("utf-8")
    body = {key: value for key, value in decoded.items() if key != "receipt_sha256"}
    assert decoded["receipt_sha256"] == boundary._canonical_hash(body)


def test_source_module_has_no_model_framework_or_private_data_dependency() -> None:
    source = boundary.SOURCE_PATH.read_text(encoding="utf-8")

    assert "import mlx" not in source
    assert "import transformers" not in source
    assert "video_private" not in source
    assert "video_census_bridge" not in source
    assert 'open(".env"' not in source
    assert "keychain" in source.lower()  # only the explicit non-access docstring
    assert os.path.basename(__file__) not in source
