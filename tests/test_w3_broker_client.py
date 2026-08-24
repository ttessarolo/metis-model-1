"""Exactly six Phase A client/consumer cases for the protected broker."""

from __future__ import annotations

import base64
import copy
import hashlib
import stat
import threading
from pathlib import Path

import pytest

import metis_model1.w3_broker_client as broker_client
from metis_model1.w3_broker_client import (
    BrokerClient,
    BrokerReceiptError,
    BrokerRequest,
    BrokerRequestError,
    BrokerStateError,
    BrokerTransportError,
    ConsumerAnchor,
    ConsumerAnchorStore,
    ReceiptConsumer,
    ReleaseEvidence,
    UnprotectedTestAnchorStore,
    VerificationKeyEpoch,
)

protocol = broker_client.protocol


def _digest(seed: str) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _policy(seed: str = "policy-v1") -> dict[str, object]:
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
    release_id: str = "release-v1",
    *,
    mode: str = protocol.MODE_SYNTHETIC,
    key_id: str | None = None,
    policy: dict[str, object] | None = None,
) -> dict[str, object]:
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
        "launcher": "launcher/w3_privileged_launcher",
        "worker": "runtime/worker.py",
        "loader": "runtime/loader.mjs",
        "runner": "runtime/runner.ts",
        "node": "runtime/node",
    }
    rows = sorted(
        [
            {
                "path": paths[role],
                "size": 4096,
                "mode": stat.S_IFREG | 0o444,
                "sha256": installed[protocol.ROLE_DIGEST_FIELD[role]],
                "uid": 0,
                "gid": 0,
                "dev": 16777220,
                "ino": int(hashlib.sha256(paths[role].encode()).hexdigest()[:8], 16),
                "nlink": 1,
            }
            for role in protocol.INSTALLED_CODE_ROLES
        ]
        + [
            {
                "path": path,
                "size": 2048,
                "mode": stat.S_IFREG | 0o444,
                "sha256": _digest(f"installed:{path}"),
                "uid": 0,
                "gid": 0,
                "dev": 16777220,
                "ino": int(hashlib.sha256(path.encode()).hexdigest()[:8], 16),
                "nlink": 1,
            }
            for path in ("runtime/policy.json", "runtime/release-manifest.json")
        ],
        key=lambda row: row["path"],
    )
    return protocol.validate_authority(
        {
            "schema_version": 1,
            "kind": protocol.KIND_AUTHORITY,
            "authority_id": protocol.AUTHORITY_ID,
            "mode": mode,
            "signing": {
                "algorithm": (
                    protocol.SYNTHETIC_ALGORITHM
                    if mode == protocol.MODE_SYNTHETIC
                    else protocol.PRODUCTION_ALGORITHM
                ),
                "key_id": key_id or protocol.synthetic_key_id(),
            },
            "broker_identity": {"user": "_metisbroker", "uid": 501, "gid": 501},
            "runner_identity": {"user": "_metisrunner", "uid": 502, "gid": 502},
            "launcher_identity": {"user": "root", "uid": 0, "gid": 0},
            "installed_code_identity": installed,
            "installed_code_paths": paths,
            "installed_code_roster": rows,
            "policy_identity": copy.deepcopy(policy or _policy()),
            "release_identity": {
                "release_id": release_id,
                "ancestry_root_sha256": protocol.release_ancestry_hash(release_id, rows),
            },
        }
    )


def _release(authority: dict[str, object], *, retired_after: int | None = None) -> ReleaseEvidence:
    identity = authority["release_identity"]
    return ReleaseEvidence(
        authority_sha256=protocol.authority_hash(authority),
        release_id=str(identity["release_id"]),
        release_sha256=str(identity["ancestry_root_sha256"]),
        retired_after_receipt_sequence=retired_after,
    )


def _request(
    authority: dict[str, object],
    policy: dict[str, object],
    sequence: int,
    *,
    release_sha256: str | None = None,
) -> BrokerRequest:
    release = authority["release_identity"]
    return BrokerRequest.build(
        client_nonce=hashlib.sha256(f"client:{sequence}".encode()).hexdigest(),
        task="f1-smoke-candidate",
        inputs={"target_source": _digest("candidate-source")},
        claimed_authority_sha256=protocol.authority_hash(authority),
        claimed_release_sha256=release_sha256 or str(release["ancestry_root_sha256"]),
        claimed_policy_sha256=str(policy["resolved_sha256"]),
    )


def _roster(authority: dict[str, object]) -> list[dict[str, object]]:
    return copy.deepcopy(authority["installed_code_roster"])


def _receipt(
    request: BrokerRequest,
    authority: dict[str, object],
    policy: dict[str, object],
    *,
    sequence: int,
    previous: str,
    attempt_sequence: int | None = None,
) -> dict[str, object]:
    installed = authority["installed_code_identity"]
    broker = authority["broker_identity"]
    runner = authority["runner_identity"]
    launcher = authority["launcher_identity"]
    mode = str(authority["mode"])
    rows = _roster(authority)
    body: dict[str, object] = {
        "schema_version": 1,
        "kind": protocol.KIND_RECEIPT,
        "mode": mode,
        "executed_preimage_authority": mode == protocol.MODE_PRODUCTION,
        "nonclaims": (
            ["phase-a-production-verification-unavailable"]
            if mode == protocol.MODE_PRODUCTION
            else list(protocol.SYNTHETIC_NONCLAIMS)
        ),
        "request": request.receipt_binding(),
        "measured": {
            "authority_sha256": request.claimed_authority_sha256,
            "release_sha256": request.claimed_release_sha256,
            "policy_sha256": request.claimed_policy_sha256,
        },
        "broker_nonce": hashlib.sha256(f"broker:{sequence}".encode()).hexdigest(),
        "attempt_sequence": attempt_sequence or sequence,
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
            "broker_uid": broker["uid"],
            "broker_gid": broker["gid"],
            "runner_uid": runner["uid"],
            "runner_gid": runner["gid"],
            "launcher_uid": launcher["uid"],
            "launcher_gid": launcher["gid"],
        },
        "policy": copy.deepcopy(policy),
        "roster": {"pre": rows, "post": copy.deepcopy(rows)},
        "output": {
            "stdout_sha256": _digest(f"stdout:{sequence}"),
            "stderr_sha256": _digest("stderr:empty"),
            "exit_code": 0,
            "publication": {
                "sha256": _digest(f"publication:{sequence}"),
                "size": 512,
                "atomic": True,
            },
        },
        "cleanup": {
            "process_census": {
                "residual_children": 0,
                "census_sha256": _digest(f"process-census:{sequence}"),
            },
            "fd_census": {
                "retained_fds": 0,
                "census_sha256": _digest(f"fd-census:{sequence}"),
            },
            "temp_census": {
                "entries": [],
                "roster_sha256": _digest(f"temp-census:{sequence}"),
            },
        },
        "signature": {
            "algorithm": authority["signing"]["algorithm"],
            "key_id": authority["signing"]["key_id"],
            "value": (
                base64.b64encode(b"\0" * 64).decode("ascii")
                if mode == protocol.MODE_PRODUCTION
                else "0" * 64
            ),
        },
    }
    if mode == protocol.MODE_SYNTHETIC:
        return protocol.attach_synthetic_signature(body)
    return protocol.validate_receipt(body)


def _resign(receipt: dict[str, object]) -> dict[str, object]:
    candidate = copy.deepcopy(receipt)
    candidate["signature"]["value"] = "0" * 64
    return protocol.attach_synthetic_signature(candidate)


def _initialized_store(path: Path) -> UnprotectedTestAnchorStore:
    store = UnprotectedTestAnchorStore(path)
    store.initialize_once(
        ConsumerAnchor(
            instance_id=hashlib.sha256(f"consumer-anchor:{path}".encode()).hexdigest(),
            revision=0,
        )
    )
    return store


def _consumer(
    anchor_store: ConsumerAnchorStore,
    authorities: list[dict[str, object]],
    policies: list[dict[str, object]],
    *,
    releases: list[ReleaseEvidence] | None = None,
    key: VerificationKeyEpoch | None = None,
) -> ReceiptConsumer:
    return ReceiptConsumer(
        anchor_store=anchor_store,
        authorities=authorities,
        key_epochs=[
            key
            or VerificationKeyEpoch(
                key_id=protocol.synthetic_key_id(),
                algorithm=protocol.SYNTHETIC_ALGORITHM,
            )
        ],
        releases=releases or [_release(authority) for authority in authorities],
        registered_policy_sha256s=[str(policy["resolved_sha256"]) for policy in policies],
    )


def _initialized_consumer(
    path: Path,
    authorities: list[dict[str, object]],
    policies: list[dict[str, object]],
    *,
    releases: list[ReleaseEvidence] | None = None,
    key: VerificationKeyEpoch | None = None,
) -> ReceiptConsumer:
    return _consumer(
        _initialized_store(path),
        authorities,
        policies,
        releases=releases,
        key=key,
    )


class _StaticTransport:
    def __init__(self, receipt: dict[str, object]):
        self.receipt = receipt
        self.seen: list[bytes] = []

    def exchange(self, canonical_request: bytes) -> bytes:
        assert isinstance(protocol.parse_canonical_json(canonical_request), dict)
        self.seen.append(canonical_request)
        return protocol.canonical_bytes(self.receipt)


def test_canonical_request_transport_submission_and_typed_errors(tmp_path: Path) -> None:
    authority = _authority()
    policy = _policy()
    request = _request(authority, policy, 1)
    receipt = _receipt(
        request,
        authority,
        policy,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    transport = _StaticTransport(receipt)
    anchor_path = tmp_path / "anchor.json"
    store = _initialized_store(anchor_path)
    consumer = _consumer(store, [authority], [policy])
    accepted = BrokerClient(transport, consumer).submit(request)
    assert accepted == receipt
    assert transport.seen == [request.canonical_bytes()]
    assert protocol.parse_canonical_json(transport.seen[0]) == request.to_document()
    persisted = store.load_required()
    assert persisted.revision == 1
    assert persisted.head_for(protocol.AUTHORITY_ID) is not None
    with pytest.raises(BrokerStateError) as captured:
        store.initialize_once(
            ConsumerAnchor(instance_id=hashlib.sha256(b"second-instance").hexdigest(), revision=0)
        )
    assert captured.value.reason == "anchor-already-initialized"

    for field in ("schema_version", "revision"):
        boolean_integer = persisted.to_document()
        boolean_integer[field] = True
        with pytest.raises(BrokerStateError) as captured:
            ConsumerAnchor.from_bytes(protocol.canonical_bytes(boolean_integer))
        assert captured.value.reason == "anchor-invalid"

    for forbidden in ("path", "argv", "env", "fd"):
        with pytest.raises(BrokerRequestError) as captured:
            BrokerRequest.build(
                client_nonce="a1" * 32,
                task="candidate",
                inputs={forbidden: _digest("forbidden")},
                claimed_authority_sha256=request.claimed_authority_sha256,
                claimed_release_sha256=request.claimed_release_sha256,
                claimed_policy_sha256=request.claimed_policy_sha256,
            )
        assert captured.value.reason == "request-invalid"

    class BrokenTransport:
        def exchange(self, canonical_request: bytes) -> bytes:
            raise OSError("offline")

    with pytest.raises(BrokerTransportError) as captured:
        BrokerClient(BrokenTransport(), consumer).submit(request)
    assert captured.value.reason == "transport-failure"

    production_key_id = _digest("production-key")
    production_authority = _authority(
        "release-production",
        mode=protocol.MODE_PRODUCTION,
        key_id=production_key_id,
    )
    production_request = _request(production_authority, policy, 9)
    production_receipt = _receipt(
        production_request,
        production_authority,
        policy,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    production_consumer = _initialized_consumer(
        tmp_path / "production-state.json",
        [production_authority],
        [policy],
        key=VerificationKeyEpoch(
            key_id=production_key_id,
            algorithm=protocol.PRODUCTION_ALGORITHM,
            public_key=b"P" * 32,
        ),
    )
    with pytest.raises(BrokerReceiptError) as captured:
        production_consumer.accept(production_receipt, expected_request=production_request)
    assert captured.value.reason == "production-verification-unavailable"


def test_consumer_rejects_sequence_regression_and_invalid_signature(tmp_path: Path) -> None:
    authority = _authority()
    policy = _policy()
    store = _initialized_store(tmp_path / "anchor.json")
    genesis = store.load_required()
    consumer = _consumer(store, [authority], [policy])
    first_request = _request(authority, policy, 1)
    first = _receipt(
        first_request,
        authority,
        policy,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    consumer.accept(first, expected_request=first_request)
    second_request = _request(authority, policy, 2)
    second = _receipt(
        second_request,
        authority,
        policy,
        sequence=2,
        previous=protocol.receipt_hash(first),
    )
    consumer.accept(second, expected_request=second_request)

    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(first, expected_request=first_request)
    assert captured.value.reason == "receipt-sequence-regression"

    third_request = _request(authority, policy, 3)
    third = _receipt(
        third_request,
        authority,
        policy,
        sequence=3,
        previous=protocol.receipt_hash(second),
    )
    third["signature"]["value"] = "f" * 64
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(third, expected_request=third_request)
    assert captured.value.reason == "signature-invalid"
    assert consumer.state.head_for(protocol.AUTHORITY_ID).receipt_sequence == 2

    replayed_first_anchor = genesis.advanced(
        authority_id=protocol.AUTHORITY_ID,
        receipt_sequence=1,
        previous_receipt_sha256=protocol.GENESIS_RECEIPT_DIGEST,
        receipt_sha256=protocol.receipt_hash(first),
    )
    with pytest.raises(BrokerStateError) as captured:
        store.compare_and_swap(genesis.digest(), replayed_first_anchor)
    assert captured.value.reason == "anchor-cas-mismatch"


def test_consumer_rejects_gap_divergent_head_and_attempt_order(tmp_path: Path) -> None:
    authority = _authority()
    policy = _policy()
    consumer = _initialized_consumer(tmp_path / "anchor.json", [authority], [policy])
    gap_request = _request(authority, policy, 2)
    gap = _receipt(
        gap_request,
        authority,
        policy,
        sequence=2,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(gap, expected_request=gap_request)
    assert captured.value.reason == "receipt-sequence-gap"

    first_request = _request(authority, policy, 1)
    first = _receipt(
        first_request,
        authority,
        policy,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    consumer.accept(first, expected_request=first_request)
    second_request = _request(authority, policy, 2)
    fork = _receipt(
        second_request,
        authority,
        policy,
        sequence=2,
        previous=_digest("divergent-valid-head"),
    )
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(fork, expected_request=second_request)
    assert captured.value.reason == "receipt-chain-fork"

    bad_attempt = _receipt(
        second_request,
        authority,
        policy,
        sequence=2,
        previous=protocol.receipt_hash(first),
    )
    bad_attempt["attempt_sequence"] = 1
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(bad_attempt, expected_request=second_request)
    assert captured.value.reason == "receipt-invalid"
    assert "receipt-sequence-exceeds-attempt" in captured.value.detail

    race_delegate = _initialized_store(tmp_path / "race-anchor.json")
    barrier = threading.Barrier(2)

    class BarrierStore:
        def initialize_once(self, anchor: ConsumerAnchor) -> None:
            race_delegate.initialize_once(anchor)

        def load_required(self) -> ConsumerAnchor:
            return race_delegate.load_required()

        def compare_and_swap(self, expected_anchor_sha256: str, new_anchor: ConsumerAnchor) -> None:
            barrier.wait(timeout=5)
            race_delegate.compare_and_swap(expected_anchor_sha256, new_anchor)

    shared_store = BarrierStore()
    racing_consumers = [
        _consumer(shared_store, [authority], [policy]),
        _consumer(shared_store, [authority], [policy]),
    ]
    racing_requests = [_request(authority, policy, 101), _request(authority, policy, 102)]
    racing_receipts = [
        _receipt(
            request,
            authority,
            policy,
            sequence=1,
            previous=protocol.GENESIS_RECEIPT_DIGEST,
        )
        for request in racing_requests
    ]
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def race(index: int) -> None:
        try:
            racing_consumers[index].accept(
                racing_receipts[index], expected_request=racing_requests[index]
            )
            outcome = "accepted"
        except BrokerStateError as error:
            outcome = error.reason
        except BaseException as error:  # pragma: no cover - asserted diagnostic path
            outcome = type(error).__name__
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=race, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["accepted", "anchor-cas-mismatch"]
    assert race_delegate.load_required().revision == 1


def test_persisted_old_time_replay_claim_mismatch_and_cleanup_refusal(tmp_path: Path) -> None:
    authority = _authority()
    policy = _policy()
    state_path = tmp_path / "state.json"
    first_request = _request(authority, policy, 1)
    first = _receipt(
        first_request,
        authority,
        policy,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )
    store = _initialized_store(state_path)
    _consumer(store, [authority], [policy]).accept(first, expected_request=first_request)

    restarted = _consumer(UnprotectedTestAnchorStore(state_path), [authority], [policy])
    with pytest.raises(BrokerReceiptError) as captured:
        restarted.accept(first, expected_request=first_request)
    assert captured.value.reason == "receipt-sequence-regression"

    second_request = _request(authority, policy, 2)
    mismatch = _receipt(
        second_request,
        authority,
        policy,
        sequence=2,
        previous=protocol.receipt_hash(first),
    )
    mismatch_cases = (
        ("authority_sha256", "claimed-measured-authority-mismatch"),
        ("release_sha256", "claimed-measured-release-mismatch"),
        ("policy_sha256", "claimed-measured-policy-mismatch"),
    )
    for field, reason in mismatch_cases:
        candidate = copy.deepcopy(mismatch)
        candidate["measured"][field] = _digest(f"different-{field}")
        candidate = _resign(candidate)
        with pytest.raises(BrokerReceiptError) as captured:
            restarted.accept(candidate, expected_request=second_request)
        assert captured.value.reason == reason

    cleanup_cases = []
    dirty_process = copy.deepcopy(mismatch)
    dirty_process["cleanup"]["process_census"]["residual_children"] = 1
    cleanup_cases.append((dirty_process, "cleanup-residual-children"))
    dirty_fd = copy.deepcopy(mismatch)
    dirty_fd["cleanup"]["fd_census"]["retained_fds"] = 1
    cleanup_cases.append((dirty_fd, "cleanup-retained-fds"))
    incomplete = copy.deepcopy(mismatch)
    del incomplete["cleanup"]["temp_census"]
    cleanup_cases.append((incomplete, "missing-field"))
    for candidate, detail in cleanup_cases:
        with pytest.raises(BrokerReceiptError) as captured:
            restarted.accept(candidate, expected_request=second_request)
        assert captured.value.reason == "receipt-invalid"
        assert detail in captured.value.detail

    state_path.unlink()
    deleted_store = UnprotectedTestAnchorStore(state_path)
    with pytest.raises(BrokerStateError) as captured:
        _consumer(deleted_store, [authority], [policy])
    assert captured.value.reason == "anchor-missing"
    with pytest.raises(BrokerStateError) as captured:
        deleted_store.initialize_once(
            ConsumerAnchor(instance_id=hashlib.sha256(b"forbidden-reset").hexdigest(), revision=0)
        )
    assert captured.value.reason == "anchor-already-initialized"


def test_key_high_water_and_preimage_authority_mutations_fail_closed(tmp_path: Path) -> None:
    authority = _authority()
    policy = _policy()
    request = _request(authority, policy, 1)
    receipt = _receipt(
        request,
        authority,
        policy,
        sequence=1,
        previous=protocol.GENESIS_RECEIPT_DIGEST,
    )

    unknown = copy.deepcopy(receipt)
    unknown["signature"]["key_id"] = _digest("unknown-key-epoch")
    consumer = _initialized_consumer(tmp_path / "unknown.json", [authority], [policy])
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(unknown, expected_request=request)
    assert captured.value.reason == "unknown-key-epoch"

    revoked = _initialized_consumer(
        tmp_path / "revoked.json",
        [authority],
        [policy],
        key=VerificationKeyEpoch(
            key_id=protocol.synthetic_key_id(),
            algorithm=protocol.SYNTHETIC_ALGORITHM,
            revocation_high_water=1,
        ),
    )
    revoked.accept(receipt, expected_request=request)
    second_request = _request(authority, policy, 2)
    second = _receipt(
        second_request,
        authority,
        policy,
        sequence=2,
        previous=protocol.receipt_hash(receipt),
    )
    with pytest.raises(BrokerReceiptError) as captured:
        revoked.accept(second, expected_request=second_request)
    assert captured.value.reason == "revoked-key-future-receipt"

    nlink = copy.deepcopy(receipt)
    nlink["roster"]["pre"][0]["nlink"] = 2
    nlink["roster"]["post"][0]["nlink"] = 2
    with pytest.raises(BrokerReceiptError) as captured:
        _initialized_consumer(tmp_path / "nlink.json", [authority], [policy]).accept(
            nlink, expected_request=request
        )
    assert captured.value.reason == "receipt-invalid"
    assert "roster-not-single-link" in captured.value.detail

    boolean_mode = copy.deepcopy(receipt)
    boolean_mode["roster"]["pre"][0]["mode"] = True
    boolean_mode["roster"]["post"][0]["mode"] = True
    with pytest.raises(BrokerReceiptError) as captured:
        _initialized_consumer(tmp_path / "bool-mode.json", [authority], [policy]).accept(
            boolean_mode, expected_request=request
        )
    assert captured.value.reason == "receipt-invalid"
    assert "bad-integer" in captured.value.detail

    mutations = []
    drift = copy.deepcopy(receipt)
    drift["roster"]["post"][0]["ino"] += 1
    mutations.append((_resign(drift), "pre-post-roster-mismatch"))
    incomplete = copy.deepcopy(receipt)
    incomplete["roster"]["pre"] = incomplete["roster"]["pre"][:-1]
    incomplete["roster"]["post"] = incomplete["roster"]["post"][:-1]
    mutations.append((_resign(incomplete), "authority-installed-roster-mismatch"))
    role_digest = copy.deepcopy(receipt)
    for side in ("pre", "post"):
        first = role_digest["roster"][side][0]["sha256"]
        role_digest["roster"][side][0]["sha256"] = role_digest["roster"][side][1]["sha256"]
        role_digest["roster"][side][1]["sha256"] = first
    mutations.append((_resign(role_digest), "authority-installed-roster-mismatch"))
    launcher = copy.deepcopy(receipt)
    launcher["identities"]["launcher"]["code_sha256"] = _digest("substituted-launcher")
    mutations.append((_resign(launcher), "authority-identity-mismatch"))
    for index, (candidate, reason) in enumerate(mutations):
        isolated = _initialized_consumer(tmp_path / f"mutation-{index}.json", [authority], [policy])
        with pytest.raises(BrokerReceiptError) as captured:
            isolated.accept(candidate, expected_request=request)
        assert captured.value.reason == reason


def test_retired_release_evidence_and_ten_receipt_restart_progression(tmp_path: Path) -> None:
    old_authority = _authority("release-v1")
    new_authority = _authority("release-v2")
    policy = _policy()
    state_path = tmp_path / "state.json"
    releases = [_release(old_authority, retired_after=5), _release(new_authority)]
    _initialized_store(state_path)
    consumers = [
        _consumer(
            UnprotectedTestAnchorStore(state_path),
            [old_authority, new_authority],
            [policy],
            releases=releases,
        )
        for _ in range(2)
    ]
    previous = protocol.GENESIS_RECEIPT_DIGEST
    last_receipt: dict[str, object] | None = None
    for sequence in range(1, 11):
        authority = old_authority if sequence <= 5 else new_authority
        request = _request(authority, policy, sequence)
        receipt = _receipt(
            request,
            authority,
            policy,
            sequence=sequence,
            attempt_sequence=sequence + 2,
            previous=previous,
        )
        consumers[(sequence - 1) % 2].accept(receipt, expected_request=request)
        previous = protocol.receipt_hash(receipt)
        last_receipt = receipt

    assert last_receipt is not None
    persisted = UnprotectedTestAnchorStore(state_path).load_required()
    head = persisted.head_for(protocol.AUTHORITY_ID)
    assert head is not None
    assert persisted.revision == 10
    assert head.receipt_sequence == 10
    assert head.receipt_sha256 == protocol.receipt_hash(last_receipt)

    old_request = _request(old_authority, policy, 11)
    retired_future = _receipt(
        old_request,
        old_authority,
        policy,
        sequence=11,
        attempt_sequence=13,
        previous=head.receipt_sha256,
    )
    consumer = _consumer(
        UnprotectedTestAnchorStore(state_path),
        [old_authority, new_authority],
        [policy],
        releases=releases,
    )
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(retired_future, expected_request=old_request)
    assert captured.value.reason == "retired-release-future-receipt"

    old_release_digest = str(old_authority["release_identity"]["ancestry_root_sha256"])
    cross_release_request = _request(
        new_authority,
        policy,
        11,
        release_sha256=old_release_digest,
    )
    cross_release = _receipt(
        cross_release_request,
        new_authority,
        policy,
        sequence=11,
        attempt_sequence=13,
        previous=head.receipt_sha256,
    )
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(cross_release, expected_request=cross_release_request)
    assert captured.value.reason == "unknown-release"

    unknown_policy = _policy("unregistered-policy")
    policy_request = _request(new_authority, unknown_policy, 11)
    policy_receipt = _receipt(
        policy_request,
        new_authority,
        unknown_policy,
        sequence=11,
        attempt_sequence=13,
        previous=head.receipt_sha256,
    )
    with pytest.raises(BrokerReceiptError) as captured:
        consumer.accept(policy_receipt, expected_request=policy_request)
    assert captured.value.reason == "authority-policy-claim-mismatch"
