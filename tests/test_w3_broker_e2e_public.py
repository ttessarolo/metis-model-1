"""Exactly two payload-free public E2E cases for the Phase A broker stack."""

from __future__ import annotations

import copy
import hashlib
import stat
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from metis_model1.w3_broker_client import (  # noqa: E402
    BrokerClient,
    BrokerReceiptError,
    BrokerRequest,
    ConsumerAnchor,
    ReceiptConsumer,
    ReleaseEvidence,
    UnprotectedTestAnchorStore,
    VerificationKeyEpoch,
)
from runtime import w3_broker_protocol as protocol  # noqa: E402
from runtime import w3_protected_broker as core  # noqa: E402


def _digest(seed: str) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _row(path: str, digest: str) -> dict[str, object]:
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


def _authority() -> dict[str, object]:
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
        "loader": "loader/native.mjs",
        "runner": "runner/main.py",
        "node": "node/bin",
    }
    template = _digest("policy-template")
    parameters = {"NODE_EXECUTABLE": _digest("node"), "RUNTIME_ROOT": _digest("runtime")}
    authority = {
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
        "installed_code_roster": sorted(
            [
                _row(paths[role], installed[protocol.ROLE_DIGEST_FIELD[role]])
                for role in protocol.INSTALLED_CODE_ROLES
            ]
            + [
                _row("runtime/policy.json", _digest("installed-policy")),
                _row("runtime/release-manifest.json", _digest("installed-release-manifest")),
            ],
            key=lambda row: row["path"],
        ),
        "policy_identity": {
            "template_sha256": template,
            "parameters": parameters,
            "resolved_sha256": protocol.policy_hash(template, parameters),
        },
        "release_identity": {
            "release_id": "w3-public-synthetic-v1",
            "ancestry_root_sha256": "",
        },
    }
    authority["release_identity"]["ancestry_root_sha256"] = protocol.release_ancestry_hash(
        str(authority["release_identity"]["release_id"]), authority["installed_code_roster"]
    )
    return protocol.validate_authority(authority)


def _execution_result(
    request: Mapping[str, object], authority: Mapping[str, object]
) -> dict[str, object]:
    installed = authority["installed_code_identity"]
    roster = copy.deepcopy(authority["installed_code_roster"])
    return {
        "measured": {
            "authority_sha256": protocol.authority_hash(authority),
            "release_sha256": authority["release_identity"]["ancestry_root_sha256"],
            "policy_sha256": authority["policy_identity"]["resolved_sha256"],
        },
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
            "launcher_uid": authority["launcher_identity"]["uid"],
            "launcher_gid": authority["launcher_identity"]["gid"],
        },
        "policy": copy.deepcopy(authority["policy_identity"]),
        "roster": {"pre": roster, "post": copy.deepcopy(roster)},
        "output": {
            "stdout_sha256": _digest("normalized-stdout"),
            "stderr_sha256": _digest("empty-stderr"),
            "exit_code": 0,
            "publication": {"sha256": _digest("publication"), "size": 512, "atomic": True},
        },
        "cleanup": {
            "process_census": {"residual_children": 0, "census_sha256": _digest("process")},
            "fd_census": {"retained_fds": 0, "census_sha256": _digest("fds")},
            "temp_census": {"entries": [], "roster_sha256": _digest("temp")},
        },
    }


class _SyntheticExecutor:
    def __init__(self) -> None:
        self.client_nonces: list[str] = []

    def __call__(
        self,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        _attempt: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.client_nonces.append(str(request["client_nonce"]))
        return _execution_result(request, authority)


class _InMemoryTransport:
    def __init__(
        self,
        broker: core.ProtectedExecutionBroker,
        transform: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._broker = broker
        self._transform = transform

    def exchange(self, canonical_request: bytes) -> bytes:
        response = self._broker.handle(canonical_request)
        return response if self._transform is None else self._transform(response)


def _broker(
    directory: Path, authority: dict[str, object]
) -> tuple[core.ProtectedExecutionBroker, _SyntheticExecutor]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    executor = _SyntheticExecutor()
    broker_nonces = iter(("b2" * 32, "c3" * 32, "d4" * 32))
    broker = core.ProtectedExecutionBroker(
        authority=authority,
        ledger_path=directory / "ledger.bin",
        executor=executor,
        nonce_factory=lambda: next(broker_nonces),
        require_existing_ledger=False,
        allow_unprotected_test_ledger=True,
    )
    return broker, executor


def _consumer(directory: Path, authority: dict[str, object]) -> ReceiptConsumer:
    authority_sha256 = protocol.authority_hash(authority)
    release = authority["release_identity"]
    anchor_store = UnprotectedTestAnchorStore(directory / "consumer-anchor.json")
    anchor_store.initialize_once(
        ConsumerAnchor(
            instance_id=hashlib.sha256(f"consumer-anchor:{directory}".encode()).hexdigest(),
            revision=0,
        )
    )
    return ReceiptConsumer(
        anchor_store=anchor_store,
        authorities=[authority],
        key_epochs=[
            VerificationKeyEpoch(
                key_id=protocol.synthetic_key_id(),
                algorithm=protocol.SYNTHETIC_ALGORITHM,
            )
        ],
        releases=[
            ReleaseEvidence(
                authority_sha256=authority_sha256,
                release_id=str(release["release_id"]),
                release_sha256=str(release["ancestry_root_sha256"]),
            )
        ],
        registered_policy_sha256s=[str(authority["policy_identity"]["resolved_sha256"])],
    )


def _request(authority: dict[str, object], nonce: str) -> BrokerRequest:
    return BrokerRequest.build(
        client_nonce=nonce,
        task="public-synthetic-e2e",
        inputs={"source": _digest("public-source")},
        claimed_authority_sha256=protocol.authority_hash(authority),
        claimed_release_sha256=str(authority["release_identity"]["ancestry_root_sha256"]),
        claimed_policy_sha256=str(authority["policy_identity"]["resolved_sha256"]),
    )


def _projection(receipt: Mapping[str, object]) -> dict[str, object]:
    return {
        key: receipt[key]
        for key in (
            "mode",
            "executed_preimage_authority",
            "nonclaims",
            "measured",
            "identities",
            "effective_ids",
            "policy",
            "roster",
            "output",
            "cleanup",
        )
    }


def _tamper(
    mutate: Callable[[dict[str, object]], None], *, resign: bool
) -> Callable[[bytes], bytes]:
    def transform(response: bytes) -> bytes:
        receipt = protocol.parse_canonical_json(response)
        assert isinstance(receipt, dict)
        mutate(receipt)
        if resign:
            receipt["signature"]["value"] = "0" * 64
            receipt = protocol.attach_synthetic_signature(receipt)
        return protocol.canonical_bytes(receipt)

    return transform


def test_public_synthetic_happy_path_two_fresh_nonces_and_projection(tmp_path: Path) -> None:
    authority = _authority()
    broker, executor = _broker(tmp_path / "happy", authority)
    consumer = _consumer(tmp_path / "happy", authority)
    client = BrokerClient(_InMemoryTransport(broker), consumer)

    first_request = _request(authority, "01" * 32)
    first = client.submit(first_request)
    first_head = consumer.state.head_for(protocol.AUTHORITY_ID)
    assert first_head is not None and first_head.receipt_sequence == 1

    second_request = _request(authority, "02" * 32)
    second = client.submit(second_request)
    second_head = consumer.state.head_for(protocol.AUTHORITY_ID)
    assert second_head is not None and second_head.receipt_sequence == 2
    assert second_head.receipt_sha256 == protocol.receipt_hash(second)

    assert executor.client_nonces == ["01" * 32, "02" * 32]
    assert first["attempt_sequence"] == first["receipt_sequence"] == 1
    assert second["attempt_sequence"] == second["receipt_sequence"] == 2
    assert second["previous_receipt_sha256"] == protocol.receipt_hash(first)
    assert protocol.canonical_bytes(_projection(first)) == protocol.canonical_bytes(
        _projection(second)
    )
    assert first["output"] == second["output"]
    assert first["executed_preimage_authority"] is False
    assert second["executed_preimage_authority"] is False
    assert tuple(first["nonclaims"]) == protocol.SYNTHETIC_NONCLAIMS
    assert tuple(second["nonclaims"]) == protocol.SYNTHETIC_NONCLAIMS


def test_public_synthetic_tamper_matrix_fails_closed(tmp_path: Path) -> None:
    authority = _authority()

    def signed_field(receipt: dict[str, object]) -> None:
        receipt["output"]["exit_code"] = 1

    def claimed_authority(receipt: dict[str, object]) -> None:
        receipt["request"]["claimed_authority_sha256"] = _digest("forged-authority")

    def claimed_release(receipt: dict[str, object]) -> None:
        receipt["request"]["claimed_release_sha256"] = _digest("forged-release")

    def claimed_policy(receipt: dict[str, object]) -> None:
        receipt["request"]["claimed_policy_sha256"] = _digest("forged-policy")

    def roster_path(receipt: dict[str, object]) -> None:
        receipt["roster"]["pre"][0]["path"] = "broker/substituted.py"
        receipt["roster"]["post"][0]["path"] = "broker/substituted.py"

    def cleanup(receipt: dict[str, object]) -> None:
        receipt["cleanup"]["process_census"]["residual_children"] = 1

    matrix = (
        ("signed-field", signed_field, False, "signature-invalid", ""),
        (
            "claimed-authority",
            claimed_authority,
            True,
            "claimed-measured-authority-mismatch",
            "",
        ),
        (
            "claimed-release",
            claimed_release,
            True,
            "request-binding-mismatch",
            "",
        ),
        (
            "claimed-policy",
            claimed_policy,
            True,
            "request-binding-mismatch",
            "",
        ),
        ("roster-path", roster_path, True, "authority-installed-roster-mismatch", ""),
        ("cleanup", cleanup, False, "receipt-invalid", "cleanup-residual-children"),
    )
    for index, (label, mutate, resign, reason, detail) in enumerate(matrix, start=1):
        directory = tmp_path / label
        broker, _executor = _broker(directory, authority)
        consumer = _consumer(directory, authority)
        request = _request(authority, f"{index:02x}" * 32)
        client = BrokerClient(_InMemoryTransport(broker, _tamper(mutate, resign=resign)), consumer)
        with pytest.raises(BrokerReceiptError) as captured:
            client.submit(request)
        assert captured.value.reason == reason
        if detail:
            assert detail in captured.value.detail
        assert consumer.state.head_for(protocol.AUTHORITY_ID) is None

    chain_directory = tmp_path / "chain-head"
    chain_broker, _executor = _broker(chain_directory, authority)
    chain_consumer = _consumer(chain_directory, authority)
    first_request = _request(authority, "a1" * 32)
    first = BrokerClient(_InMemoryTransport(chain_broker), chain_consumer).submit(first_request)

    def previous_head(receipt: dict[str, object]) -> None:
        receipt["previous_receipt_sha256"] = _digest("divergent-head")

    second_request = _request(authority, "a2" * 32)
    forked_client = BrokerClient(
        _InMemoryTransport(chain_broker, _tamper(previous_head, resign=True)), chain_consumer
    )
    with pytest.raises(BrokerReceiptError) as captured:
        forked_client.submit(second_request)
    assert captured.value.reason == "receipt-chain-fork"
    head = chain_consumer.state.head_for(protocol.AUTHORITY_ID)
    assert head is not None
    assert head.receipt_sequence == 1
    assert head.receipt_sha256 == protocol.receipt_hash(first)
