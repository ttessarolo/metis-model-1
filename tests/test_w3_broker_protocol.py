"""Focused protocol cases for the W3 protected execution broker (Phase A).

Exactly 12 named cases, payload-free and unprivileged:
1. canonical round trip;
2. duplicate raw key rejection;
3. normalized duplicate key rejection;
4. noncanonical byte/order/whitespace rejection;
5. invalid JSON number and strict integer/bool rejection;
6. unknown or path/argv/env/FD field rejection;
7. payload and nesting bounds;
8. frame truncation/trailing/oversize rejection;
9. domain-separated request hash stability;
10. authority claims-only cross-binding shape;
11. signed-material mutation coverage including previous receipt;
12. full-roster and synthetic-nonclaim schema enforcement.

Synthetic fixtures carry no production authority: executed_preimage_authority
stays false and no process, network, credential or payload is touched.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import io
import json
import stat
import struct
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).parents[1]
PROTOCOL_PATH = PROJECT_ROOT / "runtime/w3_broker_protocol.py"
REQUEST_SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-protected-broker-request.schema.json"
AUTHORITY_SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-protected-broker-authority.schema.json"
RECEIPT_SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-protected-broker-receipt.schema.json"
RFC8032_TEST_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)

_SPEC = importlib.util.spec_from_file_location("w3_broker_protocol_under_test", PROTOCOL_PATH)
assert _SPEC and _SPEC.loader
PROTOCOL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PROTOCOL)


def _digest(seed: str) -> str:
    return PROTOCOL.SHA256_PREFIX + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _flip_digest(digest: str) -> str:
    first = digest[len(PROTOCOL.SHA256_PREFIX)]
    replacement = "0" if first != "0" else "1"
    return PROTOCOL.SHA256_PREFIX + replacement + digest[len(PROTOCOL.SHA256_PREFIX) + 1 :]


def _sample_payload() -> dict:
    return {
        "task": "f1-smoke-candidate",
        "inputs": {
            "target_source": _digest("target-source"),
            "before_source": _digest("before-source"),
        },
    }


def _sample_request() -> dict:
    authority = _sample_authority()
    return PROTOCOL.build_request(
        client_nonce="a1" * 32,
        payload=_sample_payload(),
        claimed_authority_sha256=PROTOCOL.authority_hash(authority),
        claimed_release_sha256=authority["release_identity"]["ancestry_root_sha256"],
        claimed_policy_sha256=authority["policy_identity"]["resolved_sha256"],
    )


def _sample_authority(mode: str = PROTOCOL.MODE_SYNTHETIC) -> dict:
    algorithm = (
        PROTOCOL.SYNTHETIC_ALGORITHM
        if mode == PROTOCOL.MODE_SYNTHETIC
        else PROTOCOL.PRODUCTION_ALGORITHM
    )
    installed = {
        "broker_code_sha256": _digest("broker-code"),
        "launcher_sha256": _digest("launcher-code"),
        "worker_sha256": _digest("worker"),
        "loader_sha256": _digest("loader"),
        "runner_sha256": _digest("runner"),
        "node_sha256": _digest("node"),
    }
    paths = {
        "broker": "broker/broker.py",
        "launcher": "launcher/w3_privileged_launcher",
        "worker": "runtime/worker.py",
        "loader": "runtime/loader.mjs",
        "runner": "runtime/runner.ts",
        "node": "runtime/node",
    }
    roster = []
    for index, (role, path) in enumerate(sorted(paths.items(), key=lambda item: item[1])):
        row = _sample_row(path)
        row["sha256"] = installed[PROTOCOL.ROLE_DIGEST_FIELD[role]]
        row["ino"] = 1234567 + index
        roster.append(row)
    release_row = _sample_row("release/imported-runtime.json")
    release_row["sha256"] = _digest("release-imported-runtime")
    release_row["ino"] = 1234567 + len(roster)
    roster.append(release_row)
    roster.sort(key=lambda row: row["path"])
    parameters = {
        "NODE_EXECUTABLE": _digest("node-binary"),
        "RUNTIME_ROOT": _digest("runtime-root"),
    }
    policy = {
        "template_sha256": _digest("policy-template"),
        "parameters": parameters,
        "resolved_sha256": PROTOCOL.policy_hash(_digest("policy-template"), parameters),
    }
    release_id = "w3-metis-node-release-v1"
    authority = {
        "schema_version": 1,
        "kind": PROTOCOL.KIND_AUTHORITY,
        "authority_id": PROTOCOL.AUTHORITY_ID,
        "mode": mode,
        "signing": {"algorithm": algorithm, "key_id": _digest("signing-key")},
        "broker_identity": {"user": "_metisbroker", "uid": 501, "gid": 501},
        "runner_identity": {"user": "_metisrunner", "uid": 502, "gid": 502},
        "launcher_identity": {"user": "root", "uid": 0, "gid": 0},
        "installed_code_identity": installed,
        "installed_code_paths": paths,
        "installed_code_roster": roster,
        "policy_identity": policy,
        "release_identity": {
            "release_id": release_id,
            "ancestry_root_sha256": PROTOCOL.release_ancestry_hash(release_id, roster),
        },
    }
    if mode == PROTOCOL.MODE_PROTECTED_PUBLIC_SYNTHETIC:
        public_key = PROTOCOL.ed25519.derive_public_key(RFC8032_TEST_SEED)
        authority["signing"] = {
            "algorithm": PROTOCOL.PRODUCTION_ALGORITHM,
            "key_id": PROTOCOL.ed25519.mode_scoped_key_id(public_key, mode=mode),
            "public_key": PROTOCOL.ed25519.encode_public_key(public_key),
        }
    return authority


def _sample_row(path: str = "capsule/native_ts_loader.mjs") -> dict:
    return {
        "path": path,
        "size": 4096,
        "mode": stat.S_IFREG | 0o444,
        "sha256": _digest(f"row:{path}"),
        "uid": 0,
        "gid": 0,
        "dev": 16777220,
        "ino": 1234567,
        "nlink": 1,
    }


def _sample_receipt(request: dict | None = None) -> dict:
    source = request if request is not None else _sample_request()
    policy = _sample_authority()["policy_identity"]
    return {
        "schema_version": 1,
        "kind": PROTOCOL.KIND_RECEIPT,
        "mode": PROTOCOL.MODE_SYNTHETIC,
        "executed_preimage_authority": False,
        "nonclaims": list(PROTOCOL.SYNTHETIC_NONCLAIMS),
        "request": {
            "request_hash": source["request_hash"],
            "client_nonce": source["client_nonce"],
            "claimed_authority_sha256": source["claimed_authority_sha256"],
            "claimed_release_sha256": source["claimed_release_sha256"],
            "claimed_policy_sha256": source["claimed_policy_sha256"],
        },
        "measured": {
            "authority_sha256": source["claimed_authority_sha256"],
            "release_sha256": source["claimed_release_sha256"],
            "policy_sha256": source["claimed_policy_sha256"],
        },
        "broker_nonce": "b2" * 32,
        "attempt_sequence": 1,
        "receipt_sequence": 1,
        "previous_receipt_sha256": PROTOCOL.GENESIS_RECEIPT_DIGEST,
        "identities": {
            "broker": {"user": "_metisbroker", "code_sha256": _digest("broker-code")},
            "launcher": {"code_sha256": _digest("launcher-code")},
            "worker": {"code_sha256": _digest("worker")},
            "node": {"sha256": _digest("node"), "version": "v22.22.3"},
            "loader": {"sha256": _digest("loader")},
        },
        "effective_ids": {
            "broker_uid": 501,
            "broker_gid": 501,
            "runner_uid": 502,
            "runner_gid": 502,
            "launcher_uid": 0,
            "launcher_gid": 0,
        },
        "policy": policy,
        "roster": {
            "pre": [_sample_row(), _sample_row("runtime/node")],
            "post": [_sample_row(), _sample_row("runtime/node")],
        },
        "output": {
            "stdout_sha256": _digest("stdout"),
            "stderr_sha256": _digest("stderr"),
            "exit_code": 0,
            "publication": {"sha256": _digest("publication"), "size": 512, "atomic": True},
        },
        "cleanup": {
            "process_census": {"residual_children": 0, "census_sha256": _digest("proc-census")},
            "fd_census": {"retained_fds": 0, "census_sha256": _digest("fd-census")},
            "temp_census": {"entries": [], "roster_sha256": _digest("temp-census")},
        },
        "signature": {
            "algorithm": PROTOCOL.SYNTHETIC_ALGORITHM,
            "key_id": PROTOCOL.synthetic_key_id(),
            "value": "0" * 64,
        },
    }


def _signed_receipt() -> dict:
    return PROTOCOL.attach_synthetic_signature(_sample_receipt())


def _expect_error(error_type, reason: str):
    return pytest.raises(error_type, match=reason.replace("(", r"\(").replace(")", r"\)"))


def test_canonical_round_trip() -> None:
    request = _sample_request()
    raw = PROTOCOL.canonical_bytes(request)
    assert PROTOCOL.parse_canonical_json(raw) == request
    assert PROTOCOL.canonical_bytes(PROTOCOL.parse_canonical_json(raw)) == raw

    composed = {"greeting": "caf\u00e9", "lines": "one\ntwo"}
    decomposed = {"greeting": "cafe\u0301", "lines": "one\r\ntwo"}
    assert PROTOCOL.canonical_bytes(composed) == PROTOCOL.canonical_bytes(decomposed)
    rendered_text = PROTOCOL.canonical_bytes(composed).decode("utf-8")
    assert "caf\u00e9" in rendered_text
    assert "\r" not in rendered_text

    unsorted = {"b": 2, "a": [3, {"d": True, "c": None}]}
    rendered = PROTOCOL.canonical_bytes(unsorted)
    assert rendered == b'{"a":[3,{"c":null,"d":true}],"b":2}'
    assert PROTOCOL.parse_canonical_json(rendered) == json.loads(rendered)

    first = PROTOCOL.canonical_bytes(_sample_request())
    second = PROTOCOL.canonical_bytes(_sample_request())
    assert first == second


def test_duplicate_raw_key_rejection() -> None:
    with _expect_error(PROTOCOL.CanonicalizationError, "duplicate-key"):
        PROTOCOL.parse_canonical_json(b'{"a":1,"a":2}')
    nested = b'{"payload":{"task":"t","task":"u","inputs":{}}}'
    with _expect_error(PROTOCOL.CanonicalizationError, "duplicate-key"):
        PROTOCOL.parse_canonical_json(nested)
    assert "duplicate-key" in str(
        pytest.raises(
            PROTOCOL.CanonicalizationError, PROTOCOL.parse_canonical_json, b'{"k":0,"k":1}'
        ).value.reason
    )


def test_normalized_duplicate_key_rejection() -> None:
    collision = '{"caf\u00e9":1,"cafe\u0301":2}'.encode()
    with _expect_error(PROTOCOL.CanonicalizationError, "duplicate-normalized-key"):
        PROTOCOL.parse_canonical_json(collision)
    python_collision = {"caf\u00e9": 1, "cafe\u0301": 2}
    with pytest.raises(PROTOCOL.CanonicalizationError):
        PROTOCOL.canonical_bytes(python_collision)
    decomposed_only = '{"cafe\u0301":1}'.encode()
    with _expect_error(PROTOCOL.CanonicalizationError, "noncanonical-bytes"):
        PROTOCOL.parse_canonical_json(decomposed_only)


def test_noncanonical_bytes_order_whitespace_rejection() -> None:
    canonical = b'{"a":1,"b":[2,3]}'
    assert PROTOCOL.parse_canonical_json(canonical) == {"a": 1, "b": [2, 3]}
    for variant in (b'{"b":[2,3],"a":1}', b'{"a": 1, "b": [2, 3]}', b'{"a":1,"b":[2,3]}\n'):
        with pytest.raises(PROTOCOL.CanonicalizationError):
            PROTOCOL.parse_canonical_json(variant)
    escaped = json.dumps({"text": "caf\u00e9"}, ensure_ascii=True).encode("utf-8")
    with _expect_error(PROTOCOL.CanonicalizationError, "noncanonical-bytes"):
        PROTOCOL.parse_canonical_json(escaped)
    with _expect_error(PROTOCOL.CanonicalizationError, "noncanonical-bytes"):
        PROTOCOL.parse_canonical_json(b'{"a":1.50}')


def test_invalid_numbers_and_strict_integer_bool_rejection() -> None:
    for invalid in (b"1e999", b"NaN", b"Infinity", b"-Infinity", b"01", b"+1", b"1."):
        with pytest.raises(PROTOCOL.CanonicalizationError):
            PROTOCOL.parse_canonical_json(invalid)

    receipt = _signed_receipt()
    boolean_sequence = copy.deepcopy(receipt)
    boolean_sequence["receipt_sequence"] = True
    with _expect_error(PROTOCOL.ValidationError, "bad-integer"):
        PROTOCOL.validate_receipt(boolean_sequence)
    float_sequence = copy.deepcopy(receipt)
    float_sequence["receipt_sequence"] = 1.0
    with _expect_error(PROTOCOL.ValidationError, "bad-integer"):
        PROTOCOL.validate_receipt(float_sequence)
    string_exit = copy.deepcopy(receipt)
    string_exit["output"]["exit_code"] = "0"
    with _expect_error(PROTOCOL.ValidationError, "bad-integer"):
        PROTOCOL.validate_receipt(string_exit)
    assert PROTOCOL.parse_canonical_json(b"1") == 1
    assert PROTOCOL.parse_canonical_json(b"true") is True


def test_unknown_and_path_argv_env_fd_field_rejection() -> None:
    request = _sample_request()
    for field, value in (
        ("extra", 1),
        ("path", "/bin/sh"),
        ("argv", []),
        ("env", {}),
        ("fds", [3]),
    ):
        mutated = dict(request)
        mutated[field] = value
        expected = "forbidden-field" if field in PROTOCOL.FORBIDDEN_FIELD_NAMES else "unknown-field"
        with _expect_error(PROTOCOL.ValidationError, expected):
            PROTOCOL.validate_request(mutated)

    payload_attack = copy.deepcopy(request)
    payload_attack["payload"]["argv"] = ["node"]
    with _expect_error(PROTOCOL.ValidationError, "forbidden-field"):
        PROTOCOL.validate_request(payload_attack)
    input_name_attack = copy.deepcopy(request)
    input_name_attack["payload"]["inputs"]["path"] = _digest("sneaky")
    with _expect_error(PROTOCOL.ValidationError, "forbidden-field"):
        PROTOCOL.validate_request(input_name_attack)
    path_task = copy.deepcopy(request)
    path_task["payload"]["task"] = "tasks/f1"
    with _expect_error(PROTOCOL.ValidationError, "bad-task-identifier"):
        PROTOCOL.validate_request(path_task)

    missing = dict(request)
    del missing["client_nonce"]
    with _expect_error(PROTOCOL.ValidationError, "missing-field"):
        PROTOCOL.validate_request(missing)
    receipt_attack = dict(_signed_receipt())
    receipt_attack["locator"] = "/tmp/out"
    with _expect_error(PROTOCOL.ValidationError, "unknown-field"):
        PROTOCOL.validate_receipt(receipt_attack)
    row_attack = copy.deepcopy(_signed_receipt())
    row_attack["roster"]["pre"][0]["extra"] = 1
    with _expect_error(PROTOCOL.ValidationError, "unknown-field"):
        PROTOCOL.validate_receipt(row_attack)


def test_payload_and_nesting_bounds() -> None:
    oversize = b'{"big":"' + b"x" * (PROTOCOL.MAX_PAYLOAD_BYTES + 1) + b'"}'
    with _expect_error(PROTOCOL.CanonicalizationError, "payload-too-large"):
        PROTOCOL.parse_canonical_json(oversize)

    at_depth = {}
    current = at_depth
    for _ in range(PROTOCOL.MAX_NESTING_DEPTH - 1):
        current["next"] = {}
        current = current["next"]
    assert PROTOCOL.nesting_depth(at_depth) == PROTOCOL.MAX_NESTING_DEPTH
    assert PROTOCOL.parse_canonical_json(PROTOCOL.canonical_bytes(at_depth)) == at_depth
    over_depth = {"next": at_depth}
    assert PROTOCOL.nesting_depth(over_depth) == PROTOCOL.MAX_NESTING_DEPTH + 1
    with _expect_error(PROTOCOL.CanonicalizationError, "nesting-too-deep"):
        PROTOCOL.parse_canonical_json(PROTOCOL.canonical_bytes(over_depth))
    raw_brackets = "[" * (PROTOCOL.MAX_NESTING_DEPTH + 1) + "]" * (PROTOCOL.MAX_NESTING_DEPTH + 1)
    with _expect_error(PROTOCOL.CanonicalizationError, "nesting-too-deep"):
        PROTOCOL.parse_canonical_json(raw_brackets.encode("utf-8"))

    too_many_inputs = {
        "task": "bounded",
        "inputs": {f"input_{index:02d}": _digest(f"input-{index}") for index in range(33)},
    }
    with _expect_error(PROTOCOL.ValidationError, "too-many-inputs"):
        PROTOCOL.validate_payload(too_many_inputs)


def test_frame_truncation_trailing_oversize_rejection() -> None:
    payload = PROTOCOL.canonical_bytes(_sample_request())
    frame = PROTOCOL.encode_request_frame(
        payload,
        request_sha256=_digest("request"),
        authority_sha256=_digest("authority"),
        release_sha256=_digest("release"),
        broker_nonce="c3" * 32,
    )
    decoded = PROTOCOL.decode_request_frame(frame)
    assert decoded.payload == payload
    assert decoded.request_sha256 == _digest("request")
    assert decoded.broker_nonce == "c3" * 32
    streamed = PROTOCOL.read_request_frame(io.BytesIO(frame))
    assert streamed == decoded

    with _expect_error(PROTOCOL.FramingError, "frame-truncated-header"):
        PROTOCOL.decode_request_frame(frame[: PROTOCOL.REQUEST_HEADER_BYTES - 1])
    with _expect_error(PROTOCOL.FramingError, "frame-truncated-payload"):
        PROTOCOL.decode_request_frame(frame[:-1])
    with _expect_error(PROTOCOL.FramingError, "frame-trailing-bytes"):
        PROTOCOL.decode_request_frame(frame + b"\x00")
    with _expect_error(PROTOCOL.FramingError, "frame-bad-magic"):
        PROTOCOL.decode_request_frame(b"X" + frame[1:])
    bad_version = frame[:8] + struct.pack(">I", 2) + frame[12:]
    with _expect_error(PROTOCOL.FramingError, "frame-bad-version"):
        PROTOCOL.decode_request_frame(bad_version)
    zero_length = frame[:12] + struct.pack(">I", 0) + frame[16:]
    with _expect_error(PROTOCOL.FramingError, "frame-empty-payload"):
        PROTOCOL.decode_request_frame(zero_length)
    oversize_header = (
        PROTOCOL.FRAME_MAGIC
        + struct.pack(">II", PROTOCOL.PROTOCOL_VERSION, PROTOCOL.MAX_PAYLOAD_BYTES + 1)
        + b"\x00" * 128
        + b"payload"
    )
    with _expect_error(PROTOCOL.FramingError, "frame-oversize"):
        PROTOCOL.decode_request_frame(oversize_header)
    with _expect_error(PROTOCOL.FramingError, "frame-oversize"):
        PROTOCOL.encode_request_frame(
            b"x" * (PROTOCOL.MAX_PAYLOAD_BYTES + 1),
            request_sha256=_digest("request"),
            authority_sha256=_digest("authority"),
            release_sha256=_digest("release"),
            broker_nonce="c3" * 32,
        )
    with _expect_error(PROTOCOL.FramingError, "frame-truncated-stream"):
        PROTOCOL.read_request_frame(io.BytesIO(frame[:-3]))
    with _expect_error(PROTOCOL.FramingError, "frame-trailing-bytes"):
        PROTOCOL.read_request_frame(io.BytesIO(frame + b"\x01"))

    response = PROTOCOL.encode_response_frame(
        payload,
        status=PROTOCOL.STATUS_OK,
        request_sha256=_digest("request"),
        broker_nonce="c3" * 32,
        cleanup_sha256=_digest("cleanup"),
    )
    decoded_response = PROTOCOL.decode_response_frame(response)
    assert decoded_response.status == PROTOCOL.STATUS_OK
    assert decoded_response.cleanup_sha256 == _digest("cleanup")
    assert decoded_response.payload == payload


def test_domain_separated_request_hash_stability() -> None:
    request = _sample_request()
    assert PROTOCOL.compute_request_hash(request) == request["request_hash"]
    reordered = {key: request[key] for key in reversed(list(request))}
    assert PROTOCOL.compute_request_hash(reordered) == request["request_hash"]
    assert PROTOCOL.canonical_bytes(request) == PROTOCOL.canonical_bytes(reordered)

    mutated_nonce = dict(request)
    mutated_nonce["client_nonce"] = "d4" * 32
    assert PROTOCOL.compute_request_hash(mutated_nonce) != request["request_hash"]
    mutated_claim = dict(request)
    mutated_claim["claimed_release_sha256"] = _flip_digest(request["claimed_release_sha256"])
    assert PROTOCOL.compute_request_hash(mutated_claim) != request["request_hash"]

    body = {"shared": "body"}
    request_digest = PROTOCOL.request_hash(body)
    authority_digest = PROTOCOL.authority_hash(body)
    receipt_digest = PROTOCOL.receipt_hash(body)
    assert len({request_digest, authority_digest, receipt_digest}) == 3
    assert PROTOCOL.request_hash(body) == request_digest

    digest_bytes = PROTOCOL.digest_to_bytes(request["request_hash"])
    assert len(digest_bytes) == PROTOCOL.DIGEST_BYTES
    assert digest_bytes.hex() == request["request_hash"][len(PROTOCOL.SHA256_PREFIX) :]
    with _expect_error(PROTOCOL.FramingError, "frame-bad-digest"):
        PROTOCOL.digest_to_bytes("sha256:nothex")


def test_authority_claims_only_cross_binding_shape() -> None:
    authority = _sample_authority()
    measured = PROTOCOL.authority_hash(authority)
    request = PROTOCOL.build_request(
        client_nonce="e5" * 32,
        payload=_sample_payload(),
        claimed_authority_sha256=measured,
        claimed_release_sha256=authority["release_identity"]["ancestry_root_sha256"],
        claimed_policy_sha256=authority["policy_identity"]["resolved_sha256"],
    )
    assert PROTOCOL.cross_bind_authority(request, authority) == measured

    forged = copy.deepcopy(authority)
    forged["release_identity"]["release_id"] = "attacker-release-v1"
    forged["release_identity"]["ancestry_root_sha256"] = PROTOCOL.release_ancestry_hash(
        forged["release_identity"]["release_id"], forged["installed_code_roster"]
    )
    with _expect_error(PROTOCOL.ValidationError, "authority-claim-mismatch"):
        PROTOCOL.cross_bind_authority(request, forged)

    caller_supplied_pair = {"authority_bytes": "caller-owned", "digest": measured}
    with pytest.raises(PROTOCOL.ValidationError):
        PROTOCOL.cross_bind_authority(request, caller_supplied_pair)
    with pytest.raises(PROTOCOL.ValidationError):
        PROTOCOL.validate_authority({})

    uid_collision = copy.deepcopy(authority)
    uid_collision["runner_identity"]["uid"] = 501
    with _expect_error(PROTOCOL.ValidationError, "principal-uid-collision"):
        PROTOCOL.validate_authority(uid_collision)
    wrong_algorithm = copy.deepcopy(authority)
    wrong_algorithm["signing"]["algorithm"] = PROTOCOL.PRODUCTION_ALGORITHM
    with _expect_error(PROTOCOL.ValidationError, "algorithm-mode-mismatch"):
        PROTOCOL.validate_authority(wrong_algorithm)
    root_launcher = copy.deepcopy(authority)
    root_launcher["launcher_identity"]["uid"] = 1
    with _expect_error(PROTOCOL.ValidationError, "launcher-not-root"):
        PROTOCOL.validate_authority(root_launcher)
    unknown = copy.deepcopy(authority)
    unknown["note"] = "smuggled"
    with _expect_error(PROTOCOL.ValidationError, "unknown-field"):
        PROTOCOL.validate_authority(unknown)

    wrong_release = PROTOCOL.build_request(
        client_nonce="e6" * 32,
        payload=_sample_payload(),
        claimed_authority_sha256=measured,
        claimed_release_sha256=_digest("wrong-release"),
        claimed_policy_sha256=authority["policy_identity"]["resolved_sha256"],
    )
    with _expect_error(PROTOCOL.ValidationError, "release-claim-mismatch"):
        PROTOCOL.cross_bind_authority(wrong_release, authority)
    wrong_policy = PROTOCOL.build_request(
        client_nonce="e7" * 32,
        payload=_sample_payload(),
        claimed_authority_sha256=measured,
        claimed_release_sha256=authority["release_identity"]["ancestry_root_sha256"],
        claimed_policy_sha256=_digest("wrong-policy"),
    )
    with _expect_error(PROTOCOL.ValidationError, "policy-claim-mismatch"):
        PROTOCOL.cross_bind_authority(wrong_policy, authority)


def test_signed_material_mutation_coverage_including_previous_receipt() -> None:
    signed = _signed_receipt()
    assert PROTOCOL.verify_receipt_signature(signed) is True
    base = PROTOCOL.receipt_signing_bytes(signed)

    value_only = copy.deepcopy(signed)
    value_only["signature"]["value"] = "f" * 64
    assert PROTOCOL.receipt_signing_bytes(value_only) == base

    mutations = []

    def mutate(label, apply):
        mutations.append((label, apply))

    def set_path(receipt, path, value):
        cursor = receipt
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value

    mutate(
        "previous_receipt_sha256",
        lambda r: set_path(r, ("previous_receipt_sha256",), _digest("other-head")),
    )
    mutate("attempt_sequence", lambda r: set_path(r, ("attempt_sequence",), 2))
    mutate("receipt_sequence", lambda r: set_path(r, ("receipt_sequence",), 2))
    mutate("broker_nonce", lambda r: set_path(r, ("broker_nonce",), "f6" * 32))
    mutate(
        "request.client_nonce",
        lambda r: set_path(r, ("request", "client_nonce"), "9a" * 32),
    )
    mutate(
        "request.request_hash",
        lambda r: set_path(
            r, ("request", "request_hash"), _flip_digest(r["request"]["request_hash"])
        ),
    )
    for field in ("authority_sha256", "release_sha256", "policy_sha256"):
        mutate(
            f"measured.{field}",
            lambda r, field=field: set_path(
                r, ("measured", field), _flip_digest(r["measured"][field])
            ),
        )
    mutate(
        "identities.worker.code_sha256",
        lambda r: set_path(
            r,
            ("identities", "worker", "code_sha256"),
            _flip_digest(r["identities"]["worker"]["code_sha256"]),
        ),
    )
    mutate(
        "identities.node.version",
        lambda r: set_path(r, ("identities", "node", "version"), "v22.22.4"),
    )
    mutate("effective_ids.runner_uid", lambda r: set_path(r, ("effective_ids", "runner_uid"), 503))
    mutate(
        "policy.parameters",
        lambda r: (
            set_path(
                r,
                ("policy", "parameters", "RUNTIME_ROOT"),
                _flip_digest(r["policy"]["parameters"]["RUNTIME_ROOT"]),
            ),
            set_path(
                r,
                ("policy", "resolved_sha256"),
                PROTOCOL.policy_hash(r["policy"]["template_sha256"], r["policy"]["parameters"]),
            ),
        ),
    )
    mutate(
        "roster.pre[0].sha256",
        lambda r: set_path(
            r, ("roster", "pre", 0, "sha256"), _flip_digest(r["roster"]["pre"][0]["sha256"])
        ),
    )
    mutate("roster.post[1].size", lambda r: set_path(r, ("roster", "post", 1, "size"), 4097))
    mutate("output.exit_code", lambda r: set_path(r, ("output", "exit_code"), 1))
    mutate(
        "output.publication.sha256",
        lambda r: set_path(
            r,
            ("output", "publication", "sha256"),
            _flip_digest(r["output"]["publication"]["sha256"]),
        ),
    )
    mutate(
        "cleanup.process_census.census_sha256",
        lambda r: set_path(
            r,
            ("cleanup", "process_census", "census_sha256"),
            _flip_digest(r["cleanup"]["process_census"]["census_sha256"]),
        ),
    )
    mutate(
        "signature.key_id",
        lambda r: set_path(r, ("signature", "key_id"), _flip_digest(r["signature"]["key_id"])),
    )

    assert len(mutations) == 19
    for label, apply in mutations:
        mutated = copy.deepcopy(signed)
        apply(mutated)
        try:
            material = PROTOCOL.receipt_signing_bytes(mutated)
        except PROTOCOL.ValidationError:
            continue
        assert material != base, label
        assert not PROTOCOL.verify_synthetic_signature(
            material,
            signature_value=mutated["signature"]["value"],
            key_id=mutated["signature"]["key_id"],
        ), label

    assert PROTOCOL.verify_receipt_signature(signed) is True


def test_full_roster_and_synthetic_nonclaim_schema_enforcement() -> None:
    schemas = {}
    for label, path in (
        ("request", REQUEST_SCHEMA_PATH),
        ("authority", AUTHORITY_SCHEMA_PATH),
        ("receipt", RECEIPT_SCHEMA_PATH),
    ):
        parsed = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(parsed)
        schemas[label] = Draft202012Validator(parsed)

    schemas["request"].validate(_sample_request())
    schemas["authority"].validate(_sample_authority())
    signed = _signed_receipt()
    schemas["receipt"].validate(signed)

    summary_roster = copy.deepcopy(signed)
    summary_roster["roster"] = {"summary": True, "rows": 2}
    assert not schemas["receipt"].is_valid(summary_roster)
    truncated_row = copy.deepcopy(signed)
    del truncated_row["roster"]["pre"][0]["nlink"]
    assert not schemas["receipt"].is_valid(truncated_row)
    truncated_hash = copy.deepcopy(signed)
    truncated_hash["roster"]["post"][0]["sha256"] = "sha256:abc123"
    assert not schemas["receipt"].is_valid(truncated_hash)
    empty_roster = copy.deepcopy(signed)
    empty_roster["roster"]["pre"] = []
    assert not schemas["receipt"].is_valid(empty_roster)
    unsorted_row = copy.deepcopy(signed)
    unsorted_row["roster"]["pre"] = [_sample_row("z.mjs"), _sample_row("a.mjs")]
    with _expect_error(PROTOCOL.ValidationError, "roster-unsorted"):
        PROTOCOL.validate_receipt(unsorted_row)
    for dot_path in (".", "..", "capsule/.", "capsule/../loader.mjs"):
        dot_segment = copy.deepcopy(signed)
        dot_segment["roster"]["pre"][0]["path"] = dot_path
        assert not schemas["receipt"].is_valid(dot_segment)
        with _expect_error(PROTOCOL.ValidationError, "bad-roster-path"):
            PROTOCOL.validate_receipt(dot_segment)

    impossible_sequences = copy.deepcopy(signed)
    impossible_sequences["attempt_sequence"] = 1
    impossible_sequences["receipt_sequence"] = 2
    with _expect_error(PROTOCOL.ValidationError, "receipt-sequence-exceeds-attempt"):
        PROTOCOL.validate_receipt(impossible_sequences)

    synthetic_true = copy.deepcopy(signed)
    synthetic_true["executed_preimage_authority"] = True
    assert not schemas["receipt"].is_valid(synthetic_true)
    dropped_nonclaim = copy.deepcopy(signed)
    dropped_nonclaim["nonclaims"] = list(PROTOCOL.SYNTHETIC_NONCLAIMS[:-1])
    assert not schemas["receipt"].is_valid(dropped_nonclaim)
    unknown_field = copy.deepcopy(signed)
    unknown_field["locator"] = "/tmp/publication"
    assert not schemas["receipt"].is_valid(unknown_field)
    residual_children = copy.deepcopy(signed)
    residual_children["cleanup"]["process_census"]["residual_children"] = 1
    assert not schemas["receipt"].is_valid(residual_children)
    with _expect_error(PROTOCOL.ValidationError, "cleanup-residual-children"):
        PROTOCOL.validate_receipt(residual_children)

    production = copy.deepcopy(signed)
    production["mode"] = PROTOCOL.MODE_PRODUCTION
    production["executed_preimage_authority"] = True
    production["nonclaims"] = ["no-accuracy-claim"]
    production["signature"]["algorithm"] = PROTOCOL.PRODUCTION_ALGORITHM
    production["signature"]["value"] = base64.b64encode(bytes(64)).decode("ascii")
    assert schemas["receipt"].is_valid(production)
    assert PROTOCOL.validate_receipt(production)
    production_hex = copy.deepcopy(production)
    production_hex["signature"]["value"] = "0" * 64
    assert not schemas["receipt"].is_valid(production_hex)
    with _expect_error(PROTOCOL.ValidationError, "production-verification-unavailable"):
        PROTOCOL.verify_receipt_signature(production)

    protected_authority = _sample_authority(PROTOCOL.MODE_PROTECTED_PUBLIC_SYNTHETIC)
    assert schemas["authority"].is_valid(protected_authority)
    assert PROTOCOL.validate_authority(protected_authority)
    protected = copy.deepcopy(_sample_receipt())
    protected["mode"] = PROTOCOL.MODE_PROTECTED_PUBLIC_SYNTHETIC
    protected["executed_preimage_authority"] = True
    protected["nonclaims"] = list(PROTOCOL.PROTECTED_PUBLIC_SYNTHETIC_NONCLAIMS)
    protected["signature"] = {
        "algorithm": PROTOCOL.PRODUCTION_ALGORITHM,
        "key_id": protected_authority["signing"]["key_id"],
        "value": base64.b64encode(bytes(64)).decode("ascii"),
    }
    protected = PROTOCOL.attach_protected_public_synthetic_signature(
        protected,
        private_key=RFC8032_TEST_SEED,
        registered_key_id=protected_authority["signing"]["key_id"],
    )
    assert schemas["receipt"].is_valid(protected)
    assert PROTOCOL.verify_receipt_signature(
        protected,
        public_key=PROTOCOL.ed25519.decode_public_key(protected_authority["signing"]["public_key"]),
        registered_key_id=protected_authority["signing"]["key_id"],
    )
    with _expect_error(PROTOCOL.ValidationError, "protected-verification-key-required"):
        PROTOCOL.verify_receipt_signature(protected)
    with _expect_error(PROTOCOL.ValidationError, "mode-scoped-key-id-mismatch"):
        PROTOCOL.verify_receipt_signature(
            protected,
            public_key=PROTOCOL.ed25519.decode_public_key(
                protected_authority["signing"]["public_key"]
            ),
            registered_key_id=_digest("wrong-out-of-band-registration"),
        )

    protected_wrong_nonclaims = copy.deepcopy(protected)
    protected_wrong_nonclaims["nonclaims"] = ["no-production-authority"]
    assert not schemas["receipt"].is_valid(protected_wrong_nonclaims)
    with _expect_error(PROTOCOL.ValidationError, "nonclaims-mismatch"):
        PROTOCOL.validate_receipt(protected_wrong_nonclaims)

    protected_bad_registration = copy.deepcopy(protected_authority)
    protected_bad_registration["signing"]["key_id"] = _digest("wrong-protected-key")
    assert schemas["authority"].is_valid(protected_bad_registration)
    with _expect_error(PROTOCOL.ValidationError, "mode-scoped-key-id-mismatch"):
        PROTOCOL.validate_authority(protected_bad_registration)

    production_authority = _sample_authority(PROTOCOL.MODE_PRODUCTION)
    assert schemas["authority"].is_valid(production_authority)
    assert PROTOCOL.validate_authority(production_authority)
    production_with_protected_key = copy.deepcopy(production_authority)
    production_with_protected_key["signing"]["public_key"] = protected_authority["signing"][
        "public_key"
    ]
    assert not schemas["authority"].is_valid(production_with_protected_key)
    with _expect_error(PROTOCOL.ValidationError, "unknown-field"):
        PROTOCOL.validate_authority(production_with_protected_key)

    request_with_argv = dict(_sample_request())
    request_with_argv["argv"] = ["node", "runner.ts"]
    assert not schemas["request"].is_valid(request_with_argv)
    request_missing_nonce = dict(_sample_request())
    del request_missing_nonce["client_nonce"]
    assert not schemas["request"].is_valid(request_missing_nonce)
    request_path_input = copy.deepcopy(_sample_request())
    request_path_input["payload"]["inputs"]["path"] = _digest("x")
    assert not schemas["request"].is_valid(request_path_input)

    authority_missing_runner = copy.deepcopy(_sample_authority())
    del authority_missing_runner["runner_identity"]
    assert not schemas["authority"].is_valid(authority_missing_runner)
    authority_wrong_algorithm = copy.deepcopy(_sample_authority())
    authority_wrong_algorithm["signing"]["algorithm"] = PROTOCOL.PRODUCTION_ALGORITHM
    assert not schemas["authority"].is_valid(authority_wrong_algorithm)

    authority_bad_roster = copy.deepcopy(_sample_authority())
    authority_bad_roster["installed_code_roster"][0]["path"] = "attacker/broker.py"
    with _expect_error(PROTOCOL.ValidationError, "installed-roster-path-mismatch"):
        PROTOCOL.validate_authority(authority_bad_roster)

    arbitrary_release_scalar = copy.deepcopy(_sample_authority())
    arbitrary_release_scalar["release_identity"]["ancestry_root_sha256"] = _digest(
        "caller-selected-release-root"
    )
    assert schemas["authority"].is_valid(arbitrary_release_scalar)
    with _expect_error(PROTOCOL.ValidationError, "release-ancestry-mismatch"):
        PROTOCOL.validate_authority(arbitrary_release_scalar)
    assert len(_sample_authority()["installed_code_roster"]) > len(PROTOCOL.INSTALLED_CODE_ROLES)

    boolean_launcher = copy.deepcopy(signed)
    boolean_launcher["effective_ids"]["launcher_uid"] = False
    assert not schemas["receipt"].is_valid(boolean_launcher)
    with _expect_error(PROTOCOL.ValidationError, "bad-integer"):
        PROTOCOL.validate_receipt(boolean_launcher)
    boolean_cleanup = copy.deepcopy(signed)
    boolean_cleanup["cleanup"]["process_census"]["residual_children"] = False
    assert not schemas["receipt"].is_valid(boolean_cleanup)
    with _expect_error(PROTOCOL.ValidationError, "bad-integer"):
        PROTOCOL.validate_receipt(boolean_cleanup)
