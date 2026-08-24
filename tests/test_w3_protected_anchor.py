"""Exactly eight L70 protected-anchor cases; no host-evidence credit."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import plistlib
import socket
import stat
import struct
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from metis_model1.w3_broker_client import (  # noqa: E402
    ANCHOR_SERVICE_OPERATION,
    ANCHOR_SERVICE_REQUEST_KIND,
    ANCHOR_SERVICE_SCHEMA_VERSION,
    BrokerClientError,
    BrokerReceiptError,
    BrokerRequest,
    BrokerStateError,
    ConsumerAnchor,
    ProtectedAnchorClient,
    ReceiptConsumer,
    ReleaseEvidence,
    UnprotectedTestAnchorStore,
    VerificationKeyEpoch,
    protocol,
)
from runtime import w3_anchor_service as anchor_service  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-protected-anchor-service.schema.json"
PLIST_PATH = PROJECT_ROOT / "packaging/launchd/com.metis.model1.w3-anchor.plist.in"
SERVICE_PATH = PROJECT_ROOT / "runtime/w3_anchor_service.py"

# Published RFC 8032 test-vector seed; no key is generated or persisted.
RFC8032_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
RFC8032_OTHER_SEED = bytes.fromhex(
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
)


def _digest(seed: str) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _policy(seed: str = "protected-policy") -> dict[str, object]:
    template = _digest(f"{seed}:template")
    parameters = {
        "NODE_EXECUTABLE": _digest(f"{seed}:node"),
        "RUNTIME_ROOT": _digest(f"{seed}:runtime"),
    }
    return {
        "template_sha256": template,
        "parameters": parameters,
        "resolved_sha256": protocol.policy_hash(template, parameters),
    }


def _authority(
    *,
    seed: bytes = RFC8032_SEED,
    mode: str = protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    release_id: str = "protected-public-synthetic-v1",
) -> dict[str, object]:
    public_key = protocol.ed25519.derive_public_key(seed)
    key_id = protocol.ed25519.mode_scoped_key_id(public_key, mode=mode)
    installed = {
        "broker_code_sha256": _digest("installed:broker"),
        "launcher_sha256": _digest("installed:launcher"),
        "worker_sha256": _digest("installed:worker"),
        "loader_sha256": _digest("installed:loader"),
        "runner_sha256": _digest("installed:runner"),
        "node_sha256": _digest("installed:node"),
    }
    paths = {
        "broker": "broker/broker.py",
        "launcher": "launcher/w3-launcher",
        "worker": "runtime/worker.py",
        "loader": "runtime/loader.mjs",
        "runner": "runtime/runner.ts",
        "node": "runtime/node",
    }
    roster = sorted(
        [
            {
                "path": paths[role],
                "size": 4096,
                "mode": stat.S_IFREG | 0o444,
                "sha256": installed[protocol.ROLE_DIGEST_FIELD[role]],
                "uid": 0,
                "gid": 0,
                "dev": 1,
                "ino": int(hashlib.sha256(paths[role].encode()).hexdigest()[:8], 16),
                "nlink": 1,
            }
            for role in protocol.INSTALLED_CODE_ROLES
        ],
        key=lambda row: row["path"],
    )
    signing: dict[str, object] = {
        "algorithm": protocol.PRODUCTION_ALGORITHM,
        "key_id": key_id,
    }
    if mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
        signing["public_key"] = protocol.ed25519.encode_public_key(public_key)
    authority: dict[str, object] = {
        "schema_version": protocol.SCHEMA_VERSION,
        "kind": protocol.KIND_AUTHORITY,
        "authority_id": protocol.AUTHORITY_ID,
        "mode": mode,
        "signing": signing,
        "broker_identity": {"user": "_metisbroker", "uid": 501, "gid": 501},
        "runner_identity": {"user": "_metisrunner", "uid": 502, "gid": 502},
        "launcher_identity": {"user": "root", "uid": 0, "gid": 0},
        "installed_code_identity": installed,
        "installed_code_paths": paths,
        "installed_code_roster": roster,
        "policy_identity": _policy(),
        "release_identity": {"release_id": release_id, "ancestry_root_sha256": ""},
    }
    authority["release_identity"]["ancestry_root_sha256"] = protocol.release_ancestry_hash(
        release_id, roster
    )
    return protocol.validate_authority(authority)


def _release(authority: dict[str, object]) -> ReleaseEvidence:
    identity = authority["release_identity"]
    return ReleaseEvidence(
        authority_sha256=protocol.authority_hash(authority),
        release_id=str(identity["release_id"]),
        release_sha256=str(identity["ancestry_root_sha256"]),
    )


def _key_epoch(authority: dict[str, object], *, seed: bytes = RFC8032_SEED) -> VerificationKeyEpoch:
    return VerificationKeyEpoch(
        key_id=str(authority["signing"]["key_id"]),
        algorithm=protocol.PRODUCTION_ALGORITHM,
        public_key=protocol.ed25519.derive_public_key(seed),
        mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )


def _request(authority: dict[str, object], nonce_seed: str) -> BrokerRequest:
    return BrokerRequest.build(
        client_nonce=hashlib.sha256(nonce_seed.encode()).hexdigest(),
        task="protected-public-synthetic-anchor",
        inputs={"source": _digest(f"source:{nonce_seed}")},
        claimed_authority_sha256=protocol.authority_hash(authority),
        claimed_release_sha256=str(authority["release_identity"]["ancestry_root_sha256"]),
        claimed_policy_sha256=str(authority["policy_identity"]["resolved_sha256"]),
    )


def _receipt(
    request: BrokerRequest,
    authority: dict[str, object],
    *,
    sequence: int,
    previous: str,
    seed: bytes = RFC8032_SEED,
) -> dict[str, object]:
    installed = authority["installed_code_identity"]
    policy = authority["policy_identity"]
    mode = str(authority["mode"])
    roster = copy.deepcopy(authority["installed_code_roster"])
    body: dict[str, object] = {
        "schema_version": protocol.SCHEMA_VERSION,
        "kind": protocol.KIND_RECEIPT,
        "mode": mode,
        "executed_preimage_authority": True,
        "nonclaims": (
            list(protocol.PROTECTED_PUBLIC_SYNTHETIC_NONCLAIMS)
            if mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
            else ["future-production-authority-not-registered"]
        ),
        "request": request.receipt_binding(),
        "measured": {
            "authority_sha256": request.claimed_authority_sha256,
            "release_sha256": request.claimed_release_sha256,
            "policy_sha256": request.claimed_policy_sha256,
        },
        "broker_nonce": hashlib.sha256(f"broker:{request.client_nonce}".encode()).hexdigest(),
        "attempt_sequence": sequence,
        "receipt_sequence": sequence,
        "previous_receipt_sha256": previous,
        "identities": {
            "broker": {
                "user": "_metisbroker",
                "code_sha256": installed["broker_code_sha256"],
            },
            "launcher": {"code_sha256": installed["launcher_sha256"]},
            "worker": {"code_sha256": installed["worker_sha256"]},
            "node": {"sha256": installed["node_sha256"], "version": "v22.22.3"},
            "loader": {"sha256": installed["loader_sha256"]},
        },
        "effective_ids": {
            "broker_uid": authority["broker_identity"]["uid"],
            "broker_gid": authority["broker_identity"]["gid"],
            "runner_uid": authority["runner_identity"]["uid"],
            "runner_gid": authority["runner_identity"]["gid"],
            "launcher_uid": 0,
            "launcher_gid": 0,
        },
        "policy": copy.deepcopy(policy),
        "roster": {"pre": roster, "post": copy.deepcopy(roster)},
        "output": {
            "stdout_sha256": _digest(f"stdout:{request.client_nonce}"),
            "stderr_sha256": _digest("stderr:empty"),
            "exit_code": 0,
            "publication": {
                "sha256": _digest(f"publication:{request.client_nonce}"),
                "size": 512,
                "atomic": True,
            },
        },
        "cleanup": {
            "process_census": {"residual_children": 0, "census_sha256": _digest("process")},
            "fd_census": {"retained_fds": 0, "census_sha256": _digest("fds")},
            "temp_census": {"entries": [], "roster_sha256": _digest("temp")},
        },
        "signature": {
            "algorithm": protocol.PRODUCTION_ALGORITHM,
            "key_id": authority["signing"]["key_id"],
            "value": protocol.ed25519.encode_signature(bytes(64)),
        },
    }
    if mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
        return protocol.attach_protected_public_synthetic_signature(
            body,
            private_key=seed,
            registered_key_id=str(authority["signing"]["key_id"]),
        )
    return protocol.validate_receipt(body)


def _genesis(label: str) -> ConsumerAnchor:
    return ConsumerAnchor(instance_id=hashlib.sha256(label.encode()).hexdigest(), revision=0)


def _precreate(log_path: Path, genesis: ConsumerAnchor, *, mode: int = 0o600) -> None:
    log_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    log_path.parent.chmod(0o700)
    log_path.write_bytes(anchor_service.encode_genesis_log(genesis))
    log_path.chmod(mode)


def _service(
    log_path: Path,
    genesis: ConsumerAnchor,
    authority: dict[str, object],
) -> anchor_service.ProtectedAnchorService:
    return anchor_service.ProtectedAnchorService(
        log_path=log_path,
        genesis_anchor_sha256=genesis.digest(),
        anchor_uid=os.geteuid(),
        anchor_gid=os.getegid(),
        caller_uid=anchor_service.INSTALLED_CALLER_UID,
        caller_gid=anchor_service.INSTALLED_CALLER_GID,
        authorities=[authority],
        key_epochs=[_key_epoch(authority)],
        releases=[_release(authority)],
        registered_policy_sha256s=[str(authority["policy_identity"]["resolved_sha256"])],
        allow_unprotected_test_storage=True,
    )


class _ServiceTransport:
    def __init__(self, service: anchor_service.ProtectedAnchorService):
        self.service = service
        self.requests: list[bytes] = []

    def exchange(self, canonical_request: bytes) -> bytes:
        self.requests.append(canonical_request)
        return self.service.handle(canonical_request)


class _LoseFirstResponseTransport(_ServiceTransport):
    def __init__(self, service: anchor_service.ProtectedAnchorService):
        super().__init__(service)
        self._lost = False

    def exchange(self, canonical_request: bytes) -> bytes:
        self.requests.append(canonical_request)
        response = self.service.handle(canonical_request)
        if not self._lost:
            self._lost = True
            raise OSError("simulated response loss after durable ADVANCE")
        return response


def _consumer(
    authority: dict[str, object],
    genesis: ConsumerAnchor,
    transport: _ServiceTransport,
    *,
    journal: bytes | list[dict[str, object]] | None = None,
) -> ReceiptConsumer:
    protected = ProtectedAnchorClient(transport=transport, initial_anchor=genesis)
    return ReceiptConsumer(
        anchor_store=None,
        protected_anchor=protected,
        authorities=[authority],
        key_epochs=[_key_epoch(authority)],
        releases=[_release(authority)],
        registered_policy_sha256s=[str(authority["policy_identity"]["resolved_sha256"])],
        protected_receipt_journal=journal,
    )


def _records(log_path: Path) -> list[dict[str, object]]:
    data = log_path.read_bytes()
    offset = 0
    records: list[dict[str, object]] = []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        value = protocol.parse_canonical_json(data[offset + 4 : offset + 4 + length])
        assert isinstance(value, dict)
        records.append(value)
        offset += 4 + length
    assert offset == len(data)
    return records


def _advance_document(expected: str, receipt: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": ANCHOR_SERVICE_SCHEMA_VERSION,
        "kind": ANCHOR_SERVICE_REQUEST_KIND,
        "operation": ANCHOR_SERVICE_OPERATION,
        "expected_anchor_sha256": expected,
        "canonical_receipt": receipt,
    }


def _journal_bytes(*receipts: dict[str, object]) -> bytes:
    frames: list[bytes] = []
    for receipt in receipts:
        body = protocol.canonical_bytes(receipt)
        frames.append(struct.pack(">I", len(body)) + body)
    return b"".join(frames)


def _direct(
    service: anchor_service.ProtectedAnchorService,
    expected: str,
    receipt: dict[str, object],
) -> dict[str, object]:
    response = protocol.parse_canonical_json(
        service.handle(protocol.canonical_bytes(_advance_document(expected, receipt)))
    )
    assert isinstance(response, dict)
    return response


def test_protected_anchor_happy_path_client_and_service_advance(tmp_path: Path) -> None:
    authority = _authority()
    genesis = _genesis("happy")
    log_path = tmp_path / "happy" / "consumer-anchor.log"
    _precreate(log_path, genesis)
    service = _service(log_path, genesis, authority)
    transport = _ServiceTransport(service)
    consumer = _consumer(authority, genesis, transport)
    request = _request(authority, "happy-1")
    receipt = _receipt(
        request,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )

    assert consumer.accept(receipt, expected_request=request) == receipt
    assert consumer.anchor.revision == 1
    head = consumer.anchor.head_for(protocol.AUTHORITY_ID)
    assert head is not None and head.receipt_sha256 == protocol.receipt_hash(receipt)
    wire = protocol.parse_canonical_json(transport.requests[0])
    assert isinstance(wire, dict)
    assert set(wire) == {
        "schema_version",
        "kind",
        "operation",
        "expected_anchor_sha256",
        "canonical_receipt",
    }
    assert len(_records(log_path)) == 2
    schema = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    for artifact in [wire, *_records(log_path)]:
        assert list(schema.iter_errors(artifact)) == []


def test_exact_current_head_replay_is_byte_idempotent(tmp_path: Path) -> None:
    authority = _authority()
    genesis = _genesis("idempotent")
    log_path = tmp_path / "idempotent" / "consumer-anchor.log"
    _precreate(log_path, genesis)
    service = _service(log_path, genesis, authority)
    transport = _LoseFirstResponseTransport(service)
    consumer = _consumer(authority, genesis, transport)
    request = _request(authority, "same-receipt")
    receipt = _receipt(
        request,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    consumer.accept(receipt, expected_request=request)
    first_bytes = log_path.read_bytes()
    first_anchor = consumer.anchor.canonical_bytes()
    assert len(transport.requests) == 2
    assert transport.requests[0] == transport.requests[1]
    assert len(_records(log_path)) == 2

    assert consumer.accept(receipt, expected_request=request) == receipt
    assert log_path.read_bytes() == first_bytes
    assert consumer.anchor.canonical_bytes() == first_anchor
    response = protocol.parse_canonical_json(service.handle(transport.requests[-1]))
    assert isinstance(response, dict) and response["status"] == "idempotent"

    restart_transport = _ServiceTransport(service)
    restarted = _consumer(
        authority,
        genesis,
        restart_transport,
        journal=_journal_bytes(receipt),
    )
    assert restarted.anchor.canonical_bytes() == first_anchor
    assert len(restart_transport.requests) == 1
    proof = protocol.parse_canonical_json(service.handle(restart_transport.requests[0]))
    assert isinstance(proof, dict) and proof["status"] == "idempotent"
    assert log_path.read_bytes() == first_bytes

    iterable_restart = _consumer(
        authority,
        genesis,
        _ServiceTransport(service),
        journal=[receipt],
    )
    assert iterable_restart.anchor.canonical_bytes() == first_anchor


def test_stale_expected_digest_and_competing_cas_loser_are_denied(tmp_path: Path) -> None:
    authority = _authority()
    genesis = _genesis("cas")
    log_path = tmp_path / "cas" / "consumer-anchor.log"
    _precreate(log_path, genesis)
    service = _service(log_path, genesis, authority)
    first = _consumer(authority, genesis, _ServiceTransport(service))
    stale = _consumer(authority, genesis, _ServiceTransport(service))
    request_a = _request(authority, "cas-a")
    request_b = _request(authority, "cas-b")
    receipt_a = _receipt(
        request_a,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    receipt_b = _receipt(
        request_b,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    first.accept(receipt_a, expected_request=request_a)
    accepted_bytes = log_path.read_bytes()

    with pytest.raises(BrokerStateError, match="anchor-cas-mismatch"):
        stale.accept(receipt_b, expected_request=request_b)
    assert log_path.read_bytes() == accepted_bytes
    assert len(_records(log_path)) == 2


def test_authority_key_signature_and_mode_mutations_reject_before_append(
    tmp_path: Path,
) -> None:
    authority = _authority()
    genesis = _genesis("crypto-matrix")
    log_path = tmp_path / "crypto-matrix" / "consumer-anchor.log"
    _precreate(log_path, genesis)
    service = _service(log_path, genesis, authority)
    request = _request(authority, "crypto")
    receipt = _receipt(
        request,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    baseline = log_path.read_bytes()
    cases: list[dict[str, object]] = []

    bad_signature = copy.deepcopy(receipt)
    raw = bytearray(protocol.ed25519.decode_signature(bad_signature["signature"]["value"]))
    raw[0] ^= 1
    bad_signature["signature"]["value"] = protocol.ed25519.encode_signature(raw)
    cases.append(bad_signature)

    bad_key_id = copy.deepcopy(receipt)
    bad_key_id["signature"]["key_id"] = _digest("unknown-protected-key")
    cases.append(bad_key_id)

    unknown_authority = copy.deepcopy(receipt)
    unknown_authority["request"]["claimed_authority_sha256"] = _digest("unknown-authority")
    unknown_authority["measured"]["authority_sha256"] = _digest("unknown-authority")
    cases.append(unknown_authority)

    wrong_mode = copy.deepcopy(receipt)
    wrong_mode["mode"] = protocol.MODE_SYNTHETIC
    wrong_mode["executed_preimage_authority"] = False
    wrong_mode["nonclaims"] = list(protocol.SYNTHETIC_NONCLAIMS)
    wrong_mode["signature"] = {
        "algorithm": protocol.SYNTHETIC_ALGORITHM,
        "key_id": protocol.synthetic_key_id(),
        "value": "0" * 64,
    }
    cases.append(protocol.attach_synthetic_signature(wrong_mode))

    other_authority = _authority(seed=RFC8032_OTHER_SEED, release_id="other-release")
    other_request = _request(other_authority, "other-authority")
    cases.append(
        _receipt(
            other_request,
            other_authority,
            sequence=1,
            previous=protocol.GENESIS_RECEIPT_DIGEST,
            seed=RFC8032_OTHER_SEED,
        )
    )

    for candidate in cases:
        response = _direct(service, genesis.digest(), candidate)
        assert response["status"] == "error"
        assert log_path.read_bytes() == baseline
    assert len(cases) == 5
    assert len(_records(log_path)) == 1


def test_sequence_regression_gap_and_chain_fork_matrix_are_denied(tmp_path: Path) -> None:
    authority = _authority()
    genesis = _genesis("sequence-matrix")
    log_path = tmp_path / "sequence-matrix" / "consumer-anchor.log"
    _precreate(log_path, genesis)
    service = _service(log_path, genesis, authority)
    first_request = _request(authority, "sequence-first")
    first_receipt = _receipt(
        first_request,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    first_response = _direct(service, genesis.digest(), first_receipt)
    assert first_response["status"] == "advanced"
    current = ConsumerAnchor.from_bytes(protocol.canonical_bytes(first_response["anchor"]))
    accepted = log_path.read_bytes()
    cases = (
        (
            "receipt-sequence-regression",
            _receipt(
                _request(authority, "regression"),
                authority,
                sequence=1,
                previous=protocol.GENESIS_RECEIPT_DIGEST,
            ),
        ),
        (
            "receipt-sequence-gap",
            _receipt(
                _request(authority, "gap"),
                authority,
                sequence=3,
                previous=protocol.receipt_hash(first_receipt),
            ),
        ),
        (
            "receipt-chain-fork",
            _receipt(
                _request(authority, "fork"),
                authority,
                sequence=2,
                previous=_digest("divergent-head"),
            ),
        ),
    )
    for reason, candidate in cases:
        response = _direct(service, current.digest(), candidate)
        assert response["status"] == "error"
        assert response["error"]["code"] == reason
        assert log_path.read_bytes() == accepted
    assert len(cases) == 3


def test_precreated_storage_and_leaf_replacement_fail_closed(tmp_path: Path) -> None:
    authority = _authority()
    genesis = _genesis("storage")

    missing = tmp_path / "missing" / "consumer-anchor.log"
    missing.parent.mkdir(mode=0o700)
    with pytest.raises(anchor_service.AnchorServiceError, match="anchor-genesis-missing"):
        _service(missing, genesis, authority)

    bad_mode = tmp_path / "bad-mode" / "consumer-anchor.log"
    _precreate(bad_mode, genesis, mode=0o644)
    with pytest.raises(anchor_service.AnchorServiceError, match="anchor-log-replaced"):
        _service(bad_mode, genesis, authority)

    hardlinked = tmp_path / "hardlink" / "consumer-anchor.log"
    _precreate(hardlinked, genesis)
    os.link(hardlinked, hardlinked.parent / "second-link")
    with pytest.raises(anchor_service.AnchorServiceError, match="anchor-log-replaced"):
        _service(hardlinked, genesis, authority)

    torn = tmp_path / "torn" / "consumer-anchor.log"
    _precreate(torn, genesis)
    with torn.open("ab") as stream:
        stream.write(b"\0")
    with pytest.raises(anchor_service.AnchorServiceError, match="anchor-log-torn"):
        _service(torn, genesis, authority)

    replaced = tmp_path / "replaced" / "consumer-anchor.log"
    _precreate(replaced, genesis)
    service = _service(replaced, genesis, authority)
    original_identity = replaced.stat().st_ino
    replaced.replace(replaced.parent / "retired-anchor.log")
    replaced.write_bytes(anchor_service.encode_genesis_log(genesis))
    replaced.chmod(0o600)
    assert replaced.stat().st_ino != original_identity
    request = _request(authority, "after-replacement")
    receipt = _receipt(
        request,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    response = _direct(service, genesis.digest(), receipt)
    assert response["status"] == "error"
    assert response["error"]["code"] == "anchor-log-replaced"
    assert len(_records(replaced)) == 1

    journal_log = tmp_path / "journal" / "consumer-anchor.log"
    journal_genesis = _genesis("journal")
    _precreate(journal_log, journal_genesis)
    journal_service = _service(journal_log, journal_genesis, authority)
    request_one = _request(authority, "journal-one")
    receipt_one = _receipt(
        request_one,
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    advanced_one = _direct(journal_service, journal_genesis.digest(), receipt_one)
    anchor_one = ConsumerAnchor.from_bytes(protocol.canonical_bytes(advanced_one["anchor"]))
    request_two = _request(authority, "journal-two")
    receipt_two = _receipt(
        request_two,
        authority,
        sequence=2,
        previous=protocol.receipt_hash(receipt_one),
    )
    advanced_two = _direct(journal_service, anchor_one.digest(), receipt_two)
    anchor_two = ConsumerAnchor.from_bytes(protocol.canonical_bytes(advanced_two["anchor"]))
    complete_journal = _journal_bytes(receipt_one, receipt_two)
    stable_log = journal_log.read_bytes()

    restored = _consumer(
        authority,
        journal_genesis,
        _ServiceTransport(journal_service),
        journal=complete_journal,
    )
    assert restored.anchor.digest() == anchor_two.digest()
    assert journal_log.read_bytes() == stable_log

    mutated = copy.deepcopy(receipt_one)
    mutated_signature = bytearray(protocol.ed25519.decode_signature(mutated["signature"]["value"]))
    mutated_signature[-1] ^= 1
    mutated["signature"]["value"] = protocol.ed25519.encode_signature(mutated_signature)
    fork = _receipt(
        _request(authority, "journal-fork"),
        authority,
        sequence=2,
        previous=_digest("journal-divergent-head"),
    )
    journal_failures: tuple[tuple[str, bytes], ...] = (
        ("truncated", complete_journal[:-1]),
        ("rollback", _journal_bytes(receipt_one)),
        ("empty-rollback", b""),
        ("gap", _journal_bytes(receipt_two)),
        ("fork", _journal_bytes(receipt_one, fork)),
        ("mutation", _journal_bytes(mutated, receipt_two)),
    )
    for _label, candidate in journal_failures:
        with pytest.raises(BrokerClientError):
            _consumer(
                authority,
                journal_genesis,
                _ServiceTransport(journal_service),
                journal=candidate,
            )
        assert journal_log.read_bytes() == stable_log
    assert len(journal_failures) == 6


def test_fd3_daemon_plist_schema_and_exact_advance_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority = _authority()
    genesis = _genesis("api")
    log_path = tmp_path / "api" / "consumer-anchor.log"
    _precreate(log_path, genesis)
    service = _service(log_path, genesis, authority)
    receipt = _receipt(
        _request(authority, "api"),
        authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    request = _advance_document(genesis.digest(), receipt)
    schema_document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema_document)
    assert list(validator.iter_errors(request)) == []
    for invalid in (
        {**request, "operation": "INITIALIZE"},
        {**request, "next_anchor": genesis.to_document()},
    ):
        assert list(validator.iter_errors(invalid))
        response = protocol.parse_canonical_json(service.handle(protocol.canonical_bytes(invalid)))
        assert isinstance(response, dict) and response["status"] == "error"
    assert len(_records(log_path)) == 1

    source = SERVICE_PATH.read_text(encoding="utf-8")
    assert "ANCHOR_LISTENER_FD = 3" in source
    assert 'ANCHOR_SOCKET_PATH = "/var/run/metis-model1/w3-anchor.sock"' in source
    assert "def serve_inherited_fd3" in source
    assert "listener.family != socket.AF_UNIX" in source
    assert "socket.SO_TYPE) != socket.SOCK_STREAM" in source
    assert "bound_path != ANCHOR_SOCKET_PATH" in source
    assert "socket.LOCAL_PEERCRED" in source
    assert "stat.S_IMODE(info.st_mode) != 0o444" in source
    assert "follow_symlinks=False" in source
    assert ".bind(" not in source
    assert ".unlink(" not in source

    class Peer:
        def __init__(self, uid: int, gid: int):
            self.uid = uid
            self.gid = gid

        def getsockopt(self, level: int, option: int, length: int) -> bytes:
            assert (level, option, length) == (
                anchor_service.SOL_LOCAL,
                socket.LOCAL_PEERCRED,
                anchor_service.XUCRED_BYTES,
            )
            return struct.pack(
                anchor_service.XUCRED_FORMAT,
                anchor_service.XUCRED_VERSION,
                self.uid,
                1,
                self.gid,
                *([0] * 15),
            )

    anchor_service._verify_caller_peer(
        Peer(501, 20),
        expected_uid=501,
        expected_gid=20,
    )
    for peer in (Peer(502, 20), Peer(501, 21)):
        with pytest.raises(anchor_service.AnchorServiceError, match="anchor-peer-not-authorized"):
            anchor_service._verify_caller_peer(
                peer,
                expected_uid=501,
                expected_gid=20,
            )

    plist = plistlib.loads(PLIST_PATH.read_bytes())
    assert plist["UserName"] == plist["GroupName"] == "_metisanchor"
    assert plist["ProgramArguments"] == [
        "/Library/Application Support/MetisModel1/anchor/bin/w3-anchor-socket-shim"
    ]
    assert plist["EnvironmentVariables"] == {
        "PATH": "/usr/bin:/bin",
        "METIS_W3_PACKAGE_INSTANCE": "w3-public-synthetic-v1/install-v1",
    }
    assert set(plist["Sockets"]) == {"AnchorListener"}
    assert plist["Sockets"]["AnchorListener"] == {
        "SockPathName": "/var/run/metis-model1/w3-anchor.sock",
        "SockPathOwner": 501,
        "SockPathGroup": 20,
        "SockPathMode": 0o600,
    }
    log_parent = Path("/Library/Logs/MetisModel1/w3-anchor")
    assert Path(plist["StandardOutPath"]).parent == log_parent
    assert Path(plist["StandardErrorPath"]).parent == log_parent

    epoch = _key_epoch(authority)
    release = _release(authority)
    installed_config = {
        "schema_version": ANCHOR_SERVICE_SCHEMA_VERSION,
        "kind": "w3-protected-anchor-installed-config",
        "active_authority_path": str(anchor_service.INSTALLED_ACTIVE_AUTHORITY_PATH),
        "active_authority_sha256": protocol.authority_hash(authority),
        "genesis_anchor_sha256": genesis.digest(),
        "anchor_uid": 502,
        "anchor_gid": 502,
        "caller_uid": 501,
        "caller_gid": 20,
        "authorities": [authority],
        "key_epochs": [
            {
                "mode": epoch.mode,
                "algorithm": epoch.algorithm,
                "key_id": epoch.key_id,
                "public_key": protocol.ed25519.encode_public_key(epoch.public_key),
                "revocation_high_water": epoch.revocation_high_water,
            }
        ],
        "releases": [
            {
                "authority_sha256": release.authority_sha256,
                "release_id": release.release_id,
                "release_sha256": release.release_sha256,
                "retired_after_receipt_sequence": release.retired_after_receipt_sequence,
            }
        ],
        "registered_policy_sha256s": [str(authority["policy_identity"]["resolved_sha256"])],
    }
    assert list(validator.iter_errors(installed_config)) == []
    for invalid_config in (
        {**installed_config, "caller_uid": 502},
        {**installed_config, "caller_gid": 21},
        {**installed_config, "active_authority_path": "/tmp/caller-selected.json"},
        {**installed_config, "authorities": [authority, authority]},
        {key: value for key, value in installed_config.items() if key != "caller_uid"},
    ):
        assert list(validator.iter_errors(invalid_config))

    runtime_config = {
        **installed_config,
        "anchor_uid": os.geteuid(),
        "anchor_gid": os.getegid(),
    }
    installed_log = tmp_path / "installed" / "consumer-anchor.log"
    _precreate(installed_log, genesis)
    monkeypatch.setattr(anchor_service, "INSTALLED_LOG_PATH", installed_log)
    monkeypatch.setattr(
        anchor_service,
        "_read_root_owned_config",
        lambda path: copy.deepcopy(runtime_config),
    )

    def unavailable(_path: Path) -> dict[str, object]:
        raise anchor_service.AnchorServiceError("anchor-active-authority-unavailable")

    monkeypatch.setattr(anchor_service, "_read_active_authority", unavailable)
    with pytest.raises(
        anchor_service.AnchorServiceError,
        match="anchor-active-authority-unavailable",
    ):
        anchor_service._installed_service()

    swapped = _authority(seed=RFC8032_OTHER_SEED, release_id="swapped-release")
    monkeypatch.setattr(anchor_service, "_read_active_authority", lambda _path: swapped)
    with pytest.raises(
        anchor_service.AnchorServiceError,
        match="anchor-active-authority-mismatch",
    ):
        anchor_service._installed_service()

    forged = copy.deepcopy(authority)
    forged["release_identity"]["ancestry_root_sha256"] = _digest("forged-release")
    monkeypatch.setattr(anchor_service, "_read_active_authority", lambda _path: forged)
    with pytest.raises(
        anchor_service.AnchorServiceError,
        match="anchor-active-authority-invalid",
    ):
        anchor_service._installed_service()

    mismatched_config = copy.deepcopy(runtime_config)
    mismatched_config["authorities"] = [swapped]
    monkeypatch.setattr(
        anchor_service,
        "_read_root_owned_config",
        lambda path: copy.deepcopy(mismatched_config),
    )
    monkeypatch.setattr(anchor_service, "_read_active_authority", lambda _path: authority)
    with pytest.raises(
        anchor_service.AnchorServiceError,
        match="anchor-active-authority-mismatch",
    ):
        anchor_service._installed_service()

    monkeypatch.setattr(
        anchor_service,
        "_read_root_owned_config",
        lambda path: copy.deepcopy(runtime_config),
    )
    registry_failures = []
    for field, replacement in (
        ("key_epochs", []),
        ("releases", []),
        ("registered_policy_sha256s", [_digest("unbound-policy")]),
    ):
        unbound = copy.deepcopy(runtime_config)
        unbound[field] = replacement
        monkeypatch.setattr(
            anchor_service,
            "_read_root_owned_config",
            lambda path, document=unbound: copy.deepcopy(document),
        )
        with pytest.raises(anchor_service.AnchorServiceError, match="anchor-config-invalid"):
            anchor_service._installed_service()
        registry_failures.append(field)
    assert registry_failures == ["key_epochs", "releases", "registered_policy_sha256s"]

    monkeypatch.setattr(
        anchor_service,
        "_read_root_owned_config",
        lambda path: copy.deepcopy(runtime_config),
    )
    built_arguments: dict[str, object] = {}
    built_service = object()

    def build_service(**arguments: object) -> object:
        built_arguments.update(arguments)
        return built_service

    monkeypatch.setattr(anchor_service, "ProtectedAnchorService", build_service)
    assert anchor_service._installed_service() is built_service
    assert built_arguments["authorities"] == [authority]
    assert built_arguments["log_path"] == installed_log


def test_production_and_cross_mode_keys_are_unconditionally_rejected(tmp_path: Path) -> None:
    protected_authority = _authority()
    genesis = _genesis("production-denial")
    log_path = tmp_path / "protected" / "consumer-anchor.log"
    _precreate(log_path, genesis)
    service = _service(log_path, genesis, protected_authority)
    baseline = log_path.read_bytes()

    production_authority = _authority(mode=protocol.MODE_PRODUCTION, release_id="production-v1")
    production_request = _request(production_authority, "production")
    production_receipt = _receipt(
        production_request,
        production_authority,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    state_path = tmp_path / "production-state" / "anchor.json"
    state_path.parent.mkdir(mode=0o700)
    store = UnprotectedTestAnchorStore(state_path)
    store.initialize_once(genesis)
    production_key = VerificationKeyEpoch(
        key_id=str(production_authority["signing"]["key_id"]),
        algorithm=protocol.PRODUCTION_ALGORITHM,
        public_key=protocol.ed25519.derive_public_key(RFC8032_SEED),
        mode=protocol.MODE_PRODUCTION,
    )
    consumer = ReceiptConsumer(
        anchor_store=store,
        authorities=[production_authority],
        key_epochs=[production_key],
        releases=[_release(production_authority)],
        registered_policy_sha256s=[str(production_authority["policy_identity"]["resolved_sha256"])],
    )
    with pytest.raises(BrokerReceiptError, match="production-verification-unavailable"):
        consumer.accept(production_receipt, expected_request=production_request)
    response = _direct(service, genesis.digest(), production_receipt)
    assert response["status"] == "error"
    assert response["error"]["code"] == "production-verification-unavailable"
    assert log_path.read_bytes() == baseline

    production_key_id = protocol.ed25519.mode_scoped_key_id(
        protocol.ed25519.derive_public_key(RFC8032_SEED),
        mode=protocol.MODE_PRODUCTION,
    )
    with pytest.raises(BrokerClientError, match="mode-scoped key id"):
        VerificationKeyEpoch(
            key_id=production_key_id,
            algorithm=protocol.PRODUCTION_ALGORITHM,
            public_key=protocol.ed25519.derive_public_key(RFC8032_SEED),
            mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
        )
