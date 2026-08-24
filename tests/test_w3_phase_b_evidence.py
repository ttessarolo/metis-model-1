"""Exactly eight local evidence-contract cases; never host evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import struct
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime import w3_broker_protocol as protocol  # noqa: E402
from runtime import w3_phase_b_evidence as evidence  # noqa: E402

MANIFEST_PATH = PROJECT_ROOT / "manifests/w3-phase-b-host-evidence.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas/w3-phase-b-host-evidence.schema.json"
RFC8032_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
ROLES = ("broker", "launcher", "worker", "loader", "runner", "node", "policy")


def _raw_digest(payload: bytes) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def _seed_digest(label: str) -> str:
    return _raw_digest(label.encode())


def _fixture_bundle(document: Mapping[str, object]) -> Mapping[str, object]:
    if set(document) != {
        "schema_version",
        "kind",
        "artifacts",
        "install_roster",
        "authority_roster_paths",
        "bundle_sha256",
    }:
        raise ValueError("fixture bundle fields")
    material = dict(document)
    claimed = material.pop("bundle_sha256")
    expected = _raw_digest(protocol.canonical_bytes(material))
    if claimed != expected:
        raise ValueError("fixture bundle digest")
    return document


class _CompleteFixture:
    def __init__(self, root: Path):
        self.evidence_root = root / "evidence"
        self.installed_root = root / "installed"
        self.evidence_root.mkdir(parents=True, mode=0o700)
        self.installed_root.mkdir(parents=True, mode=0o700)
        self.evidence_root.chmod(0o700)
        self.installed_root.chmod(0o700)
        self.rows: dict[str, dict[str, object]] = {}
        self.seed = RFC8032_SEED
        self.logical_paths = {role: f"installed-role/{role}" for role in ROLES}
        self.installed_paths: dict[str, Path] = {}
        self.document = self._build()

    def _path(self, root: str, relative: str) -> Path:
        base = self.evidence_root if root == "evidence" else self.installed_root
        return base / relative

    def _write(
        self,
        artifact_id: str,
        kind: str,
        root: str,
        relative: str,
        payload: bytes,
    ) -> str:
        path = self._path(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        path.write_bytes(payload)
        path.chmod(0o444)
        self.rows[artifact_id] = {
            "artifact_id": artifact_id,
            "kind": kind,
            "root": root,
            "path": relative,
            "size": len(payload),
            "sha256": _raw_digest(payload),
        }
        return str(self.rows[artifact_id]["sha256"])

    def _write_json(
        self,
        artifact_id: str,
        kind: str,
        root: str,
        relative: str,
        document: Mapping[str, object],
    ) -> str:
        return self._write(
            artifact_id,
            kind,
            root,
            relative,
            protocol.canonical_bytes(document),
        )

    def rewrite(
        self,
        artifact_id: str,
        value: Mapping[str, object] | bytes,
        *,
        canonical: bool = True,
        update_row: bool = True,
    ) -> None:
        row = self.rows[artifact_id]
        path = self._path(str(row["root"]), str(row["path"]))
        payload = (
            value
            if isinstance(value, bytes)
            else (
                protocol.canonical_bytes(value)
                if canonical
                else json.dumps(value, indent=2).encode()
            )
        )
        path.chmod(0o644)
        path.write_bytes(payload)
        path.chmod(0o444)
        if update_row:
            row["size"] = len(payload)
            row["sha256"] = _raw_digest(payload)
            self.document["artifact_roster"] = sorted(
                self.rows.values(), key=lambda item: str(item["artifact_id"])
            )

    def load_json(self, artifact_id: str) -> dict[str, object]:
        row = self.rows[artifact_id]
        value = protocol.parse_canonical_json(
            self._path(str(row["root"]), str(row["path"])).read_bytes()
        )
        assert isinstance(value, dict)
        return value

    def validate(self) -> dict[str, object]:
        return evidence.validate_unprotected_fixture_evidence(
            self.document,
            evidence_root=self.evidence_root,
            installed_root=self.installed_root,
            installed_paths=self.installed_paths,
            logical_paths=self.logical_paths,
            bundle_validator=_fixture_bundle,
        )

    def _installed_preimages(self) -> tuple[dict[str, object], dict[str, object]]:
        roster: list[dict[str, object]] = []
        bundle_rows: list[dict[str, object]] = []
        for index, role in enumerate(ROLES):
            path = self.installed_root / "tree" / f"{role}.bin"
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = f"installed-{index}-{role}".encode()
            path.write_bytes(payload)
            mode = 0o555 if role in {"launcher", "node"} else 0o444
            path.chmod(mode)
            info = path.stat()
            self.installed_paths[role] = path
            digest = _raw_digest(payload)
            roster.append(
                {
                    "path": self.logical_paths[role],
                    "size": len(payload),
                    "mode": stat.S_IFREG | mode,
                    "sha256": digest,
                    "uid": 0,
                    "gid": 0,
                    "dev": info.st_dev,
                    "ino": info.st_ino,
                    "nlink": 1,
                }
            )
            bundle_rows.append(
                {
                    "role": role,
                    "path": str(path),
                    "size": len(payload),
                    "mode": stat.S_IFREG | mode,
                    "uid": 0,
                    "gid": 0,
                    "sha256": digest,
                }
            )
        config_path = self.installed_root / "tree" / "execution-config.json"
        config_payload = protocol.canonical_bytes(
            {
                "schema_version": 1,
                "kind": "w3-phase-b-fixture-execution-config",
                "network_allowed": False,
            }
        )
        config_path.write_bytes(config_payload)
        config_path.chmod(0o444)
        config_info = config_path.stat()
        self.installed_paths["fixture-config"] = config_path
        config_digest = _raw_digest(config_payload)
        config_logical = "installed-tree/" + hashlib.sha256(str(config_path).encode()).hexdigest()
        roster.append(
            {
                "path": config_logical,
                "size": len(config_payload),
                "mode": stat.S_IFREG | 0o444,
                "sha256": config_digest,
                "uid": 0,
                "gid": 0,
                "dev": config_info.st_dev,
                "ino": config_info.st_ino,
                "nlink": 1,
            }
        )
        bundle_rows.append(
            {
                "role": "fixture-config",
                "path": str(config_path),
                "size": len(config_payload),
                "mode": stat.S_IFREG | 0o444,
                "uid": 0,
                "gid": 0,
                "sha256": config_digest,
            }
        )
        roster.sort(key=lambda item: str(item["path"]))
        public_key = protocol.ed25519.derive_public_key(self.seed)
        key_id = protocol.ed25519.mode_scoped_key_id(
            public_key,
            mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
        )
        installed_identity = {
            protocol.ROLE_DIGEST_FIELD[role]: next(
                str(row["sha256"]) for row in roster if row["path"] == self.logical_paths[role]
            )
            for role in protocol.INSTALLED_CODE_ROLES
        }
        template = _seed_digest("fixture-policy-template")
        parameters = {"NODE_SHA256": installed_identity["node_sha256"]}
        authority: dict[str, object] = {
            "schema_version": 1,
            "kind": protocol.KIND_AUTHORITY,
            "authority_id": protocol.AUTHORITY_ID,
            "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
            "signing": {
                "algorithm": protocol.PRODUCTION_ALGORITHM,
                "key_id": key_id,
                "public_key": protocol.ed25519.encode_public_key(public_key),
            },
            "broker_identity": {"user": "_metisbroker", "uid": 499, "gid": 499},
            "runner_identity": {"user": "_metisrunner", "uid": 498, "gid": 498},
            "launcher_identity": {"user": "root", "uid": 0, "gid": 0},
            "installed_code_identity": installed_identity,
            "installed_code_paths": {
                role: self.logical_paths[role] for role in protocol.INSTALLED_CODE_ROLES
            },
            "installed_code_roster": roster,
            "policy_identity": {
                "template_sha256": template,
                "parameters": parameters,
                "resolved_sha256": protocol.policy_hash(template, parameters),
            },
            "release_identity": {
                "release_id": "w3-public-synthetic-v1",
                "ancestry_root_sha256": protocol.release_ancestry_hash(
                    "w3-public-synthetic-v1", roster
                ),
            },
        }
        authority = protocol.validate_authority(authority)
        install_entries = [
            {
                "path": row["path"],
                "size": row["size"],
                "mode": row["mode"],
                "uid": row["uid"],
                "gid": row["gid"],
                "sha256": row["sha256"],
            }
            for row in bundle_rows
        ]
        install_entries.sort(key=lambda row: str(row["path"]))
        bundle: dict[str, object] = {
            "schema_version": 1,
            "kind": "w3-phase-b-install-bundle",
            "artifacts": [
                {"role": row["role"], "size": row["size"], "sha256": row["sha256"]}
                for row in bundle_rows
                if row["role"] in ROLES
            ],
            "install_roster": {
                "files": len(install_entries),
                "bytes": sum(int(row["size"]) for row in install_entries),
                "sha256": _raw_digest(protocol.canonical_bytes(install_entries)),
                "entries": install_entries,
            },
            "authority_roster_paths": sorted(str(row["path"]) for row in bundle_rows),
            "bundle_sha256": "",
        }
        material = dict(bundle)
        material.pop("bundle_sha256")
        bundle["bundle_sha256"] = _raw_digest(protocol.canonical_bytes(material))
        return authority, bundle

    def _receipt(
        self,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        *,
        sequence: int,
        previous: str,
        publication: bytes,
        stdout: bytes,
        stderr: bytes,
        cleanup_sha256: str,
    ) -> dict[str, object]:
        installed = authority["installed_code_identity"]
        receipt: dict[str, object] = {
            "schema_version": 1,
            "kind": protocol.KIND_RECEIPT,
            "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
            "executed_preimage_authority": True,
            "nonclaims": list(protocol.PROTECTED_PUBLIC_SYNTHETIC_NONCLAIMS),
            "request": {
                "request_hash": request["request_hash"],
                "client_nonce": request["client_nonce"],
                "claimed_authority_sha256": request["claimed_authority_sha256"],
                "claimed_release_sha256": request["claimed_release_sha256"],
                "claimed_policy_sha256": request["claimed_policy_sha256"],
            },
            "measured": {
                "authority_sha256": protocol.authority_hash(authority),
                "release_sha256": authority["release_identity"]["ancestry_root_sha256"],
                "policy_sha256": authority["policy_identity"]["resolved_sha256"],
            },
            "broker_nonce": hashlib.sha256(f"broker-{sequence}".encode()).hexdigest(),
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
                "broker_uid": 499,
                "broker_gid": 499,
                "runner_uid": 498,
                "runner_gid": 498,
                "launcher_uid": 0,
                "launcher_gid": 0,
            },
            "policy": copy.deepcopy(authority["policy_identity"]),
            "roster": {
                "pre": copy.deepcopy(authority["installed_code_roster"]),
                "post": copy.deepcopy(authority["installed_code_roster"]),
            },
            "output": {
                "stdout_sha256": _raw_digest(stdout),
                "stderr_sha256": _raw_digest(stderr),
                "exit_code": 0,
                "publication": {
                    "sha256": _raw_digest(publication),
                    "size": len(publication),
                    "atomic": True,
                },
            },
            "cleanup": {
                "process_census": {
                    "residual_children": 0,
                    "census_sha256": cleanup_sha256,
                },
                "fd_census": {"retained_fds": 0, "census_sha256": cleanup_sha256},
                "temp_census": {"entries": [], "roster_sha256": cleanup_sha256},
            },
            "signature": {
                "algorithm": protocol.PRODUCTION_ALGORITHM,
                "key_id": authority["signing"]["key_id"],
                "value": protocol.ed25519.encode_signature(bytes(64)),
            },
        }
        return protocol.attach_protected_public_synthetic_signature(
            receipt,
            private_key=self.seed,
            registered_key_id=str(authority["signing"]["key_id"]),
        )

    def _build(self) -> dict[str, object]:
        authority, bundle = self._installed_preimages()
        public_key = protocol.ed25519.decode_public_key(authority["signing"]["public_key"])
        registry = {
            "schema_version": 1,
            "kind": "w3-protected-public-key-registry",
            "keys": [
                {
                    "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
                    "algorithm": protocol.PRODUCTION_ALGORITHM,
                    "key_id": authority["signing"]["key_id"],
                    "public_key": authority["signing"]["public_key"],
                }
            ],
        }
        command_sha256 = self._write_json(
            "preimage:command",
            "host-command",
            "evidence",
            "preimages/command.json",
            evidence.COMMAND_DOCUMENT,
        )
        self._write_json(
            "preimage:bundle",
            "install-bundle",
            "installed",
            "manifest/w3-phase-b-install-bundle.json",
            bundle,
        )
        self._write_json(
            "preimage:authority",
            "authority",
            "installed",
            "registry/protected-authority.json",
            authority,
        )
        self._write_json(
            "preimage:public-key-registry",
            "public-key-registry",
            "installed",
            "registry/public-keys.json",
            registry,
        )
        installed_roster_sha256 = self._write_json(
            "preimage:installed-roster",
            "installed-roster",
            "evidence",
            "preimages/installed-roster.json",
            {
                "schema_version": 1,
                "kind": "w3-phase-b-installed-roster",
                "entries": authority["installed_code_roster"],
            },
        )
        bindings = {
            "caller_account": {
                "name": "tommasotessarolo",
                "uid": 501,
                "gid": 20,
                "group": "staff",
            },
            "command_sha256": command_sha256,
            "bundle_sha256": bundle["bundle_sha256"],
            "authority_sha256": protocol.authority_hash(authority),
            "public_key_sha256": _raw_digest(public_key),
            "installed_roster_sha256": installed_roster_sha256,
        }
        predicate_rows = []
        for obligation in evidence.HOST_OBLIGATION_IDS:
            for polarity in evidence.POLARITIES:
                artifact_id = f"predicate:{obligation}:{polarity}"
                self._write_json(
                    artifact_id,
                    "host-predicate",
                    "evidence",
                    f"predicates/{obligation}/{polarity}.json",
                    {
                        "schema_version": 1,
                        "kind": "w3-phase-b-host-predicate",
                        "obligation_id": obligation,
                        "polarity": polarity,
                        "passed": True,
                    },
                )
                predicate_rows.append(
                    {
                        "obligation_id": obligation,
                        "polarity": polarity,
                        "passed": True,
                        "artifact_id": artifact_id,
                    }
                )
        run_rows = []
        previous = protocol.GENESIS_RECEIPT_DIGEST
        sequence = 0
        for run_id in evidence.RUN_IDS:
            candidates = []
            candidate_digests = {}
            for suffix in ("a", "b", "c"):
                candidate_id = f"candidate-{suffix}"
                artifact_id = f"candidate:{run_id}:{candidate_id}"
                candidate_digests[candidate_id] = self._write_json(
                    artifact_id,
                    "candidate",
                    "evidence",
                    f"runs/{run_id}/candidates/{candidate_id}.json",
                    {
                        "schema_version": 1,
                        "kind": "w3-phase-b-candidate-preimage",
                        "run_id": run_id,
                        "candidate_id": candidate_id,
                    },
                )
                candidates.append({"candidate_id": candidate_id, "artifact_id": artifact_id})
            executions = []
            for role_index, role in enumerate(evidence.SEMANTIC_ROLES):
                sequence += 1
                candidate_id = f"candidate-{('a', 'b', 'c')[role_index % 3]}"
                nonce = hashlib.sha256(f"{run_id}:{role}".encode()).hexdigest()
                prefix = f"execution:{run_id}:{role}:"
                relative = f"runs/{run_id}/executions/{role}"
                context_id = prefix + "execution-context"
                context_sha256 = self._write_json(
                    context_id,
                    "execution-context",
                    "evidence",
                    f"{relative}/context.json",
                    {
                        "schema_version": 1,
                        "kind": "w3-phase-b-execution-context",
                        "run_id": run_id,
                        "role": role,
                        "candidate_id": candidate_id,
                        "candidate_artifact_sha256": candidate_digests[candidate_id],
                        "command_sha256": bindings["command_sha256"],
                        "bundle_sha256": bindings["bundle_sha256"],
                        "authority_sha256": bindings["authority_sha256"],
                        "client_nonce": nonce,
                    },
                )
                request = protocol.build_request(
                    client_nonce=nonce,
                    payload={
                        "task": f"phase-b-host-{role}",
                        "inputs": {
                            "bundle": bindings["bundle_sha256"],
                            "candidate": candidate_digests[candidate_id],
                            "host_command_digest": bindings["command_sha256"],
                            "context": context_sha256,
                        },
                    },
                    claimed_authority_sha256=str(bindings["authority_sha256"]),
                    claimed_release_sha256=str(
                        authority["release_identity"]["ancestry_root_sha256"]
                    ),
                    claimed_policy_sha256=str(authority["policy_identity"]["resolved_sha256"]),
                )
                request_id = prefix + "broker-request"
                self._write_json(
                    request_id,
                    "broker-request",
                    "evidence",
                    f"{relative}/request.json",
                    request,
                )
                publication = f"publication-{run_id}-{role}".encode()
                stdout = f"stdout-{run_id}-{role}".encode()
                stderr = f"stderr-{run_id}-{role}".encode()
                cleanup = struct.pack(
                    ">8s16I",
                    b"M1W3CLN\x00",
                    1,
                    (1 << 0) | (1 << 4) | (1 << 5) | (1 << 6),
                    0,
                    0,
                    0,
                    1,
                    0,
                    len(stdout),
                    len(stderr),
                    499,
                    499,
                    0,
                    0,
                    498,
                    498,
                    1,
                )
                publication_id = prefix + "publication"
                stdout_id = prefix + "stdout"
                stderr_id = prefix + "stderr"
                cleanup_id = prefix + "native-cleanup"
                self._write(
                    publication_id,
                    "publication",
                    "evidence",
                    f"{relative}/publication.bin",
                    publication,
                )
                self._write(stdout_id, "stdout", "evidence", f"{relative}/stdout.bin", stdout)
                self._write(stderr_id, "stderr", "evidence", f"{relative}/stderr.bin", stderr)
                cleanup_sha256 = self._write(
                    cleanup_id,
                    "native-cleanup",
                    "evidence",
                    f"{relative}/native-cleanup.bin",
                    cleanup,
                )
                census_ids = {}
                for census_kind, tail in (
                    ("process", {"residual_children": 0, "members": []}),
                    ("fd", {"retained_fds": 0, "fds": []}),
                    ("temp", {"entries": []}),
                ):
                    artifact_id = prefix + f"{census_kind}-census"
                    census_ids[census_kind] = artifact_id
                    self._write_json(
                        artifact_id,
                        f"{census_kind}-census",
                        "evidence",
                        f"{relative}/{census_kind}-census.json",
                        {
                            "schema_version": 1,
                            "kind": f"w3-phase-b-{census_kind}-census",
                            "run_id": run_id,
                            "role": role,
                            "candidate_id": candidate_id,
                            "client_nonce": nonce,
                            "cleanup_sha256": cleanup_sha256,
                            **tail,
                        },
                    )
                receipt = self._receipt(
                    request,
                    authority,
                    sequence=sequence,
                    previous=previous,
                    publication=publication,
                    stdout=stdout,
                    stderr=stderr,
                    cleanup_sha256=cleanup_sha256,
                )
                receipt_id = prefix + "broker-receipt"
                self._write_json(
                    receipt_id,
                    "broker-receipt",
                    "evidence",
                    f"{relative}/receipt.json",
                    receipt,
                )
                previous = protocol.receipt_hash(receipt)
                executions.append(
                    {
                        "role": role,
                        "candidate_id": candidate_id,
                        "context_artifact_id": context_id,
                        "request_artifact_id": request_id,
                        "receipt_artifact_id": receipt_id,
                        "publication_artifact_id": publication_id,
                        "stdout_artifact_id": stdout_id,
                        "stderr_artifact_id": stderr_id,
                        "cleanup_artifact_id": cleanup_id,
                        "process_census_artifact_id": census_ids["process"],
                        "fd_census_artifact_id": census_ids["fd"],
                        "temp_census_artifact_id": census_ids["temp"],
                    }
                )
            run_rows.append(
                {
                    "run_id": run_id,
                    "candidates": candidates,
                    "executions": executions,
                    "gaps": 0,
                }
            )
        return {
            "schema_version": 1,
            "kind": "w3-phase-b-host-evidence",
            "status": "complete",
            "nonclaims": list(evidence.NONCLAIMS),
            "bindings": bindings,
            "artifact_roster": sorted(
                self.rows.values(), key=lambda item: str(item["artifact_id"])
            ),
            "host_predicates": predicate_rows,
            "runs": run_rows,
            "summary": {
                "targets": dict(evidence.TARGETS),
                "observed": dict(evidence.TARGETS),
                "gaps": 0,
            },
        }


def test_not_run_manifest_is_honest_and_schema_valid() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    schema = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert manifest == evidence.initial_not_run_document()
    assert list(schema.iter_errors(manifest)) == []
    assert manifest["summary"]["observed"] == {
        "host_predicates": 0,
        "fresh_runs": 0,
        "candidates_per_run": 0,
        "semantic_roles_per_run": 0,
        "physical_executions": 0,
    }
    assert manifest["summary"]["gaps"] is None
    assert evidence.validate_host_evidence(manifest) == manifest


def test_scalar_only_complete_document_cannot_turn_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged = copy.deepcopy(evidence.initial_not_run_document())
    forged["status"] = "complete"
    forged["bindings"] = {
        "caller_account": {
            "name": "tommasotessarolo",
            "uid": 501,
            "gid": 20,
            "group": "staff",
        },
        **{
            field: "sha256:" + "1" * 64
            for field in (
                "command_sha256",
                "bundle_sha256",
                "authority_sha256",
                "public_key_sha256",
                "installed_roster_sha256",
            )
        },
    }
    forged["summary"]["gaps"] = 0
    with pytest.raises(evidence.HostEvidenceError, match="fixed installed evidence root"):
        evidence.validate_host_evidence(forged)
    monkeypatch.setattr(evidence, "_production_context", lambda: None)
    monkeypatch.setattr(
        evidence._ArtifactStore,
        "read_fixed_manifest",
        lambda _store: forged,
    )
    with pytest.raises(
        evidence.HostEvidenceError,
        match="PHASE_B_HOST_COLLECTOR_VERIFIER_UNAVAILABLE",
    ):
        evidence.load_installed_host_evidence()


def test_complete_fixture_recomputes_every_artifact(tmp_path: Path) -> None:
    fixture = _CompleteFixture(tmp_path)
    assert fixture.validate() == fixture.document
    schema = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert list(schema.iter_errors(fixture.document)) == []
    assert len(fixture.document["artifact_roster"]) == 139


def test_artifact_measurement_symlink_and_canonicality_fail_closed(tmp_path: Path) -> None:
    measured = _CompleteFixture(tmp_path / "measurement")
    artifact_id = "predicate:principal-roster-and-fixed-id-conflicts:positive"
    measured.rewrite(artifact_id, b"forged", update_row=False)
    with pytest.raises(
        evidence.HostEvidenceError,
        match="artifact (metadata|measurement) mismatch",
    ):
        measured.validate()

    linked = _CompleteFixture(tmp_path / "hardlink")
    first = "predicate:principal-roster-and-fixed-id-conflicts:positive"
    second = "predicate:principal-roster-and-fixed-id-conflicts:adversarial"
    first_row, second_row = linked.rows[first], linked.rows[second]
    first_path = linked._path(str(first_row["root"]), str(first_row["path"]))
    second_path = linked._path(str(second_row["root"]), str(second_row["path"]))
    second_path.unlink()
    os.link(first_path, second_path)
    second_row["size"] = first_row["size"]
    second_row["sha256"] = first_row["sha256"]
    linked.document["artifact_roster"] = sorted(
        linked.rows.values(), key=lambda row: str(row["artifact_id"])
    )
    with pytest.raises(
        evidence.HostEvidenceError,
        match="artifact metadata mismatch|physical artifact",
    ):
        linked.validate()

    noncanonical = _CompleteFixture(tmp_path / "noncanonical")
    context_id = "execution:fresh-1:author:execution-context"
    noncanonical.rewrite(context_id, noncanonical.load_json(context_id), canonical=False)
    with pytest.raises(evidence.HostEvidenceError, match="not canonical"):
        noncanonical.validate()


def test_predicate_identity_and_physical_reuse_are_rejected(tmp_path: Path) -> None:
    fixture = _CompleteFixture(tmp_path)
    artifact_id = "predicate:principal-roster-and-fixed-id-conflicts:positive"
    predicate = fixture.load_json(artifact_id)
    predicate["obligation_id"] = "launcher-exact-broker-peer"
    fixture.rewrite(artifact_id, predicate)
    with pytest.raises(evidence.HostEvidenceError, match="predicate artifact semantic"):
        fixture.validate()


def test_receipt_signature_chain_and_nonce_are_recomputed(tmp_path: Path) -> None:
    signature_fixture = _CompleteFixture(tmp_path / "signature")
    receipt_id = "execution:fresh-1:author:broker-receipt"
    receipt = signature_fixture.load_json(receipt_id)
    raw_signature = bytearray(protocol.ed25519.decode_signature(receipt["signature"]["value"]))
    raw_signature[0] ^= 1
    receipt["signature"]["value"] = protocol.ed25519.encode_signature(raw_signature)
    signature_fixture.rewrite(receipt_id, receipt)
    with pytest.raises(evidence.HostEvidenceError, match="signature invalid"):
        signature_fixture.validate()

    chain_fixture = _CompleteFixture(tmp_path / "chain")
    second_id = "execution:fresh-1:before:broker-receipt"
    second = chain_fixture.load_json(second_id)
    second["previous_receipt_sha256"] = _seed_digest("forked-chain")
    second = protocol.attach_protected_public_synthetic_signature(
        second,
        private_key=chain_fixture.seed,
        registered_key_id=str(second["signature"]["key_id"]),
    )
    chain_fixture.rewrite(second_id, second)
    with pytest.raises(evidence.HostEvidenceError, match="sequence or chain"):
        chain_fixture.validate()

    nonce_fixture = _CompleteFixture(tmp_path / "nonce")
    first_context = nonce_fixture.load_json("execution:fresh-1:author:execution-context")
    second_context_id = "execution:fresh-1:before:execution-context"
    second_context = nonce_fixture.load_json(second_context_id)
    second_context["client_nonce"] = first_context["client_nonce"]
    nonce_fixture.rewrite(second_context_id, second_context)
    with pytest.raises(evidence.HostEvidenceError, match="nonce reused"):
        nonce_fixture.validate()


def test_execution_role_candidate_bundle_authority_cross_binding_is_exact(
    tmp_path: Path,
) -> None:
    fixture = _CompleteFixture(tmp_path)
    fixture.document["runs"][0]["executions"][0]["candidate_id"] = "candidate-b"
    with pytest.raises(evidence.HostEvidenceError, match="execution context cross-binding"):
        fixture.validate()

    installed = _CompleteFixture(tmp_path / "full-install-projection")
    config_path = installed.installed_paths["fixture-config"]
    config_path.chmod(0o644)
    config_path.write_bytes(b"forged-config")
    config_path.chmod(0o444)
    with pytest.raises(evidence.HostEvidenceError, match="full install roster measurement"):
        installed.validate()


def test_output_and_three_census_preimages_cannot_be_reused_or_forged(tmp_path: Path) -> None:
    census_fixture = _CompleteFixture(tmp_path / "census")
    census_id = "execution:fresh-1:author:process-census"
    census = census_fixture.load_json(census_id)
    census["cleanup_sha256"] = _seed_digest("forged-cleanup")
    census_fixture.rewrite(census_id, census)
    with pytest.raises(evidence.HostEvidenceError, match="process census semantic"):
        census_fixture.validate()

    output_fixture = _CompleteFixture(tmp_path / "output")
    publication_id = "execution:fresh-1:author:publication"
    output_fixture.rewrite(publication_id, b"different-publication")
    with pytest.raises(evidence.HostEvidenceError, match="output preimage"):
        output_fixture.validate()

    cleanup_fixture = _CompleteFixture(tmp_path / "native-cleanup")
    cleanup_id = "execution:fresh-1:author:native-cleanup"
    cleanup = bytearray(
        cleanup_fixture._path(
            str(cleanup_fixture.rows[cleanup_id]["root"]),
            str(cleanup_fixture.rows[cleanup_id]["path"]),
        ).read_bytes()
    )
    cleanup[16:20] = (1).to_bytes(4, "big")
    cleanup_fixture.rewrite(cleanup_id, bytes(cleanup))
    with pytest.raises(evidence.HostEvidenceError, match="native cleanup record semantic"):
        cleanup_fixture.validate()
