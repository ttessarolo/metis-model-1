#!/usr/bin/env python3
"""Independent L70 host-evidence denominator recomputation.

The initial manifest is deliberately ``not-run`` with zero observations.  A
later host wave can reach ``complete`` only with 28 distinct predicate probes,
two fresh runs, three distinct candidates per run, five exact semantic roles
per run and ten unique physical executions in total.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import stat
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime import w3_broker_protocol as protocol

HOST_OBLIGATION_IDS: tuple[str, ...] = (
    "principal-roster-and-fixed-id-conflicts",
    "installed-immutable-ancestry-and-complete-roster",
    "three-service-fd3-and-socket-topology",
    "launcher-exact-broker-peer",
    "irreversible-credential-drop-and-regain-denial",
    "node-only-under-runner-identity",
    "signing-key-dac-isolation",
    "signing-key-ptrace-core-seatbelt-isolation",
    "child-fd-isolation",
    "sandbox-fork-network-out-of-root-denial",
    "timeout-output-disconnect-pgid-fd-temp-cleanup",
    "immutable-preimage-under-caller-race",
    "ledger-chain-cleanup-publication-crash-replay",
    "anchor-genesis-cas-peer-idempotence-and-antirollback",
)
POLARITIES: tuple[str, ...] = ("positive", "adversarial")
RUN_IDS: tuple[str, ...] = ("fresh-1", "fresh-2")
SEMANTIC_ROLES: tuple[str, ...] = ("author", "before", "after", "mutated", "fixed")
NONCLAIMS: tuple[str, ...] = (
    "no-production-authority",
    "no-production-evidence",
    "public-synthetic-only",
    "no-semantic-accuracy-claim",
    "no-W5-credit",
)
TARGETS: Mapping[str, int] = {
    "host_predicates": 28,
    "fresh_runs": 2,
    "candidates_per_run": 3,
    "semantic_roles_per_run": 5,
    "physical_executions": 10,
}
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

INSTALLED_APP_ROOT = Path("/Library/Application Support/MetisModel1")
INSTALLED_EVIDENCE_ROOT = INSTALLED_APP_ROOT / "evidence/phase-b"
INSTALLED_EVIDENCE_MANIFEST_PATH = INSTALLED_EVIDENCE_ROOT / "host-evidence.json"

ARTIFACT_FIELDS = ("artifact_id", "kind", "root", "path", "size", "sha256")
PREDICATE_FIELDS = ("obligation_id", "polarity", "passed", "artifact_id")
CANDIDATE_FIELDS = ("candidate_id", "artifact_id")
EXECUTION_ARTIFACT_FIELDS: Mapping[str, tuple[str, str]] = {
    "context_artifact_id": ("execution-context", "context.json"),
    "request_artifact_id": ("broker-request", "request.json"),
    "receipt_artifact_id": ("broker-receipt", "receipt.json"),
    "publication_artifact_id": ("publication", "publication.bin"),
    "stdout_artifact_id": ("stdout", "stdout.bin"),
    "stderr_artifact_id": ("stderr", "stderr.bin"),
    "cleanup_artifact_id": ("native-cleanup", "native-cleanup.bin"),
    "process_census_artifact_id": ("process-census", "process-census.json"),
    "fd_census_artifact_id": ("fd-census", "fd-census.json"),
    "temp_census_artifact_id": ("temp-census", "temp-census.json"),
}
EXECUTION_FIELDS = (
    "role",
    "candidate_id",
    *EXECUTION_ARTIFACT_FIELDS,
)
RUN_FIELDS = ("run_id", "candidates", "executions", "gaps")
FIXED_ARTIFACTS: Mapping[str, tuple[str, str, str]] = {
    "preimage:command": ("host-command", "evidence", "preimages/command.json"),
    "preimage:bundle": (
        "install-bundle",
        "installed",
        "manifest/w3-phase-b-install-bundle.json",
    ),
    "preimage:authority": (
        "authority",
        "installed",
        "registry/protected-authority.json",
    ),
    "preimage:public-key-registry": (
        "public-key-registry",
        "installed",
        "registry/public-keys.json",
    ),
    "preimage:installed-roster": (
        "installed-roster",
        "evidence",
        "preimages/installed-roster.json",
    ),
}
COMMAND_DOCUMENT: Mapping[str, object] = {
    "schema_version": 1,
    "kind": "w3-phase-b-host-command",
    "command_id": "phase-b-host-gate-v1",
    "mode": protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    "network_allowed": False,
}


@dataclass(frozen=True)
class _ValidationContext:
    roots: Mapping[str, Path]
    installed_paths: Mapping[str, Path]
    logical_paths: Mapping[str, str]
    bundle_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    authority_path_mapper: Callable[[Sequence[Mapping[str, object]]], Mapping[str, str]]
    expected_uid: int
    expected_gid: int
    attestable: bool


def _raw_digest(payload: bytes) -> str:
    return protocol.SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def _safe_relative_path(value: object) -> str:
    if type(value) is not str or value.startswith("/") or "\x00" in value:
        raise HostEvidenceError("artifact path must be fixed and relative")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise HostEvidenceError("artifact path must be fixed and relative")
    return value


class _ArtifactStore:
    """Descriptor-relative reader; fixture roots are explicitly non-attesting."""

    def __init__(self, context: _ValidationContext):
        self.context = context
        self.identities: set[tuple[int, int]] = set()

    def _open_root(self, label: str) -> int:
        root = self.context.roots[label]
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
        if self.context.attestable:
            current = os.open("/", flags)
            try:
                for component in root.parts[1:]:
                    following = os.open(component, flags, dir_fd=current)
                    os.close(current)
                    current = following
                    info = os.fstat(current)
                    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                        raise HostEvidenceError("installed evidence ancestry is unsafe")
                return current
            except Exception:
                os.close(current)
                raise
        descriptor = os.open(root, flags)
        info = os.fstat(descriptor)
        named = root.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != self.context.expected_uid
            or info.st_mode & 0o022
            or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
        ):
            os.close(descriptor)
            raise HostEvidenceError("fixture evidence root is unsafe")
        return descriptor

    def read(self, row: Mapping[str, object]) -> bytes:
        if set(row) != set(ARTIFACT_FIELDS):
            raise HostEvidenceError("artifact row fields drifted")
        root_label = row["root"]
        if root_label not in self.context.roots:
            raise HostEvidenceError("artifact root is not fixed")
        relative = _safe_relative_path(row["path"])
        current = self._open_root(str(root_label))
        descriptor = -1
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
        try:
            components = relative.split("/")
            for component in components[:-1]:
                following = os.open(component, directory_flags, dir_fd=current)
                os.close(current)
                current = following
                info = os.fstat(current)
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != self.context.expected_uid
                    or info.st_mode & 0o022
                ):
                    raise HostEvidenceError("artifact ancestry is unsafe")
            descriptor = os.open(components[-1], flags, dir_fd=current)
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.context.expected_uid
                or info.st_gid != self.context.expected_gid
                or stat.S_IMODE(info.st_mode) != 0o444
                or info.st_nlink != 1
                or type(row["size"]) is not int
                or row["size"] != info.st_size
                or info.st_size <= 0
                or info.st_size > protocol.MAX_PAYLOAD_BYTES
            ):
                raise HostEvidenceError("artifact metadata mismatch")
            identity = (info.st_dev, info.st_ino)
            if identity in self.identities:
                raise HostEvidenceError("physical artifact reused")
            remaining = info.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    raise HostEvidenceError("artifact truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise HostEvidenceError("artifact grew during read")
            final = os.fstat(descriptor)
            named = os.stat(components[-1], dir_fd=current, follow_symlinks=False)
            identity_fields = (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_gid",
                "st_nlink",
                "st_size",
            )
            final_changed = any(
                getattr(final, field) != getattr(info, field) for field in identity_fields
            )
            named_changed = any(
                getattr(named, field) != getattr(info, field) for field in identity_fields
            )
            if final_changed or named_changed:
                raise HostEvidenceError("artifact named identity changed")
            payload = b"".join(chunks)
            if _digest(row["sha256"], "artifact raw sha256") != _raw_digest(payload):
                raise HostEvidenceError("artifact raw measurement mismatch")
            self.identities.add(identity)
            return payload
        except HostEvidenceError:
            raise
        except OSError as error:
            raise HostEvidenceError(f"artifact unavailable: {error}") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(current)

    def read_json(self, row: Mapping[str, object]) -> dict[str, object]:
        payload = self.read(row)
        try:
            value = protocol.parse_canonical_json(payload)
        except protocol.BrokerProtocolError as error:
            raise HostEvidenceError(f"artifact is not canonical: {error.reason}") from error
        if not isinstance(value, dict):
            raise HostEvidenceError("canonical artifact must be an object")
        return value

    def read_fixed_manifest(self) -> dict[str, object]:
        """Read the fixed manifest without trusting a size or digest from itself."""

        current = self._open_root("evidence")
        descriptor = -1
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open("host-evidence.json", flags, dir_fd=current)
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.context.expected_uid
                or info.st_gid != self.context.expected_gid
                or stat.S_IMODE(info.st_mode) != 0o444
                or info.st_nlink != 1
                or info.st_size <= 0
                or info.st_size > protocol.MAX_PAYLOAD_BYTES
            ):
                raise HostEvidenceError("installed evidence manifest metadata invalid")
            chunks: list[bytes] = []
            remaining = info.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    raise HostEvidenceError("installed evidence manifest truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise HostEvidenceError("installed evidence manifest grew")
            final = os.fstat(descriptor)
            named = os.stat("host-evidence.json", dir_fd=current, follow_symlinks=False)
            identity_fields = (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_gid",
                "st_nlink",
                "st_size",
            )
            if any(
                getattr(final, field) != getattr(info, field) for field in identity_fields
            ) or any(getattr(named, field) != getattr(info, field) for field in identity_fields):
                raise HostEvidenceError("installed evidence manifest identity changed")
            try:
                value = protocol.parse_canonical_json(b"".join(chunks))
            except protocol.BrokerProtocolError as error:
                raise HostEvidenceError(
                    f"installed evidence manifest is not canonical: {error.reason}"
                ) from error
            if not isinstance(value, dict):
                raise HostEvidenceError("installed evidence manifest must be an object")
            return value
        except HostEvidenceError:
            raise
        except OSError as error:
            raise HostEvidenceError(f"installed evidence manifest unavailable: {error}") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(current)


class HostEvidenceError(ValueError):
    """Typed evidence inflation, omission or cross-binding failure."""


def initial_not_run_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "w3-phase-b-host-evidence",
        "status": "not-run",
        "nonclaims": list(NONCLAIMS),
        "bindings": {
            "caller_account": {"name": "tommasotessarolo", "uid": 501, "gid": 20, "group": "staff"},
            "command_sha256": None,
            "bundle_sha256": None,
            "authority_sha256": None,
            "public_key_sha256": None,
            "installed_roster_sha256": None,
        },
        "artifact_roster": [],
        "host_predicates": [],
        "runs": [],
        "summary": {
            "targets": dict(TARGETS),
            "observed": {
                "host_predicates": 0,
                "fresh_runs": 0,
                "candidates_per_run": 0,
                "semantic_roles_per_run": 0,
                "physical_executions": 0,
            },
            "gaps": None,
        },
    }


def _digest(value: object, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise HostEvidenceError(f"{label} must be sha256")
    return value


def _validate_bindings(bindings: object, *, complete: bool) -> dict[str, object]:
    fields = {
        "caller_account",
        "command_sha256",
        "bundle_sha256",
        "authority_sha256",
        "public_key_sha256",
        "installed_roster_sha256",
    }
    if not isinstance(bindings, Mapping) or set(bindings) != fields:
        raise HostEvidenceError("bindings fields drifted")
    body = dict(bindings)
    expected_caller = {
        "name": "tommasotessarolo",
        "uid": 501,
        "gid": 20,
        "group": "staff",
    }
    if body["caller_account"] != expected_caller:
        raise HostEvidenceError("caller account binding drifted")
    for field in sorted(fields - {"caller_account"}):
        _digest(body[field], field, nullable=not complete)
    return body


def _document_body(document: Mapping[str, Any]) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise HostEvidenceError("document must be an object")
    body = copy.deepcopy(dict(document))
    fields = {
        "schema_version",
        "kind",
        "status",
        "nonclaims",
        "bindings",
        "artifact_roster",
        "host_predicates",
        "runs",
        "summary",
    }
    if (
        set(body) != fields
        or body["schema_version"] != 1
        or body["kind"] != "w3-phase-b-host-evidence"
    ):
        raise HostEvidenceError("document identity or fields drifted")
    if tuple(body["nonclaims"]) != NONCLAIMS:
        raise HostEvidenceError("nonclaims drifted")
    if body["status"] not in {"not-run", "complete"}:
        raise HostEvidenceError("status invalid")
    _validate_bindings(body["bindings"], complete=body["status"] == "complete")
    for field in ("artifact_roster", "host_predicates", "runs"):
        if not isinstance(body[field], list):
            raise HostEvidenceError(f"{field} must be an array")
    return body


def _validate_summary(body: Mapping[str, object], observed: Mapping[str, int]) -> None:
    summary = body["summary"]
    if (
        not isinstance(summary, Mapping)
        or set(summary) != {"targets", "observed", "gaps"}
        or summary["targets"] != dict(TARGETS)
        or summary["observed"] != dict(observed)
    ):
        raise HostEvidenceError("claimed counters do not equal recomputed counters")


def _artifact_index(rows: object) -> dict[str, dict[str, object]]:
    if not isinstance(rows, list):
        raise HostEvidenceError("artifact_roster must be an array")
    result: dict[str, dict[str, object]] = {}
    paths: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != set(ARTIFACT_FIELDS):
            raise HostEvidenceError("artifact row fields drifted")
        body = dict(row)
        artifact_id = body["artifact_id"]
        if type(artifact_id) is not str or artifact_id in result:
            raise HostEvidenceError("artifact id duplicate or invalid")
        root = body["root"]
        path = _safe_relative_path(body["path"])
        if root not in {"evidence", "installed"} or (str(root), path) in paths:
            raise HostEvidenceError("artifact root/path duplicate or invalid")
        if type(body["kind"]) is not str or type(body["size"]) is not int or body["size"] <= 0:
            raise HostEvidenceError("artifact kind/size invalid")
        _digest(body["sha256"], "artifact raw sha256")
        result[artifact_id] = body
        paths.add((str(root), path))
    if list(result) != sorted(result):
        raise HostEvidenceError("artifact roster must be sorted by artifact id")
    return result


def _expect_artifact(
    expected: dict[str, tuple[str, str, str]],
    artifact_id: str,
    kind: str,
    root: str,
    path: str,
) -> None:
    if artifact_id in expected:
        raise HostEvidenceError("artifact id reused by semantic records")
    expected[artifact_id] = (kind, root, path)


def _structure_complete(
    body: Mapping[str, object],
) -> tuple[
    dict[str, dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    expected = dict(FIXED_ARTIFACTS)
    predicate_rows: list[dict[str, object]] = []
    pairs: set[tuple[str, str]] = set()
    for row in body["host_predicates"]:
        if not isinstance(row, Mapping) or set(row) != set(PREDICATE_FIELDS):
            raise HostEvidenceError("host predicate row fields drifted")
        item = dict(row)
        pair = (item["obligation_id"], item["polarity"])
        if (
            pair in pairs
            or pair[0] not in HOST_OBLIGATION_IDS
            or pair[1] not in POLARITIES
            or item["passed"] is not True
        ):
            raise HostEvidenceError("host predicate duplicate, unknown or false")
        expected_id = f"predicate:{pair[0]}:{pair[1]}"
        if item["artifact_id"] != expected_id:
            raise HostEvidenceError("predicate artifact identity mismatch")
        _expect_artifact(
            expected,
            expected_id,
            "host-predicate",
            "evidence",
            f"predicates/{pair[0]}/{pair[1]}.json",
        )
        predicate_rows.append(item)
        pairs.add(pair)
    expected_pairs = {
        (obligation, polarity) for obligation in HOST_OBLIGATION_IDS for polarity in POLARITIES
    }
    if pairs != expected_pairs:
        raise HostEvidenceError("complete predicate denominator not closed")

    run_rows: list[dict[str, object]] = []
    if len(body["runs"]) != len(RUN_IDS):
        raise HostEvidenceError("fresh run denominator not closed")
    for expected_run_id, run in zip(RUN_IDS, body["runs"], strict=True):
        if not isinstance(run, Mapping) or set(run) != set(RUN_FIELDS):
            raise HostEvidenceError("run fields drifted")
        run_body = dict(run)
        if run_body["run_id"] != expected_run_id or run_body["gaps"] != 0:
            raise HostEvidenceError("run identity or gaps invalid")
        candidates = run_body["candidates"]
        if not isinstance(candidates, list) or len(candidates) != 3:
            raise HostEvidenceError("candidate denominator invalid")
        candidate_ids: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, Mapping) or set(candidate) != set(CANDIDATE_FIELDS):
                raise HostEvidenceError("candidate row fields drifted")
            candidate_id = candidate["candidate_id"]
            if (
                type(candidate_id) is not str
                or _IDENTIFIER_RE.fullmatch(candidate_id) is None
                or candidate_id in candidate_ids
            ):
                raise HostEvidenceError("candidate id invalid or duplicate")
            artifact_id = f"candidate:{expected_run_id}:{candidate_id}"
            if candidate["artifact_id"] != artifact_id:
                raise HostEvidenceError("candidate artifact identity mismatch")
            _expect_artifact(
                expected,
                artifact_id,
                "candidate",
                "evidence",
                f"runs/{expected_run_id}/candidates/{candidate_id}.json",
            )
            candidate_ids.append(candidate_id)
        executions = run_body["executions"]
        if not isinstance(executions, list) or len(executions) != len(SEMANTIC_ROLES):
            raise HostEvidenceError("execution denominator invalid")
        represented: set[str] = set()
        for expected_role, execution in zip(SEMANTIC_ROLES, executions, strict=True):
            if not isinstance(execution, Mapping) or set(execution) != set(EXECUTION_FIELDS):
                raise HostEvidenceError("execution fields drifted")
            if execution["role"] != expected_role or execution["candidate_id"] not in candidate_ids:
                raise HostEvidenceError("execution role or candidate mismatch")
            represented.add(str(execution["candidate_id"]))
            for field, (kind, filename) in EXECUTION_ARTIFACT_FIELDS.items():
                artifact_id = f"execution:{expected_run_id}:{expected_role}:{kind}"
                if execution[field] != artifact_id:
                    raise HostEvidenceError("execution artifact identity mismatch")
                _expect_artifact(
                    expected,
                    artifact_id,
                    kind,
                    "evidence",
                    f"runs/{expected_run_id}/executions/{expected_role}/{filename}",
                )
        if represented != set(candidate_ids):
            raise HostEvidenceError("candidate roster collapsed")
        run_rows.append(run_body)

    artifacts = _artifact_index(body["artifact_roster"])
    if set(artifacts) != set(expected):
        raise HostEvidenceError("artifact roster has missing or extra preimages")
    for artifact_id, identity in expected.items():
        row = artifacts[artifact_id]
        if (row["kind"], row["root"], row["path"]) != identity:
            raise HostEvidenceError("artifact id/path/kind mapping drifted")
    observed = {
        "host_predicates": len(predicate_rows),
        "fresh_runs": len(run_rows),
        "candidates_per_run": min(len(run["candidates"]) for run in run_rows),
        "semantic_roles_per_run": min(len(run["executions"]) for run in run_rows),
        "physical_executions": sum(len(run["executions"]) for run in run_rows),
    }
    _validate_summary(body, observed)
    if body["summary"]["gaps"] != 0 or observed != dict(TARGETS):
        raise HostEvidenceError("complete evidence denominator not closed")
    return artifacts, predicate_rows, run_rows


def _canonical_artifact(
    store: _ArtifactStore,
    artifacts: Mapping[str, Mapping[str, object]],
    cache: dict[str, object],
    artifact_id: str,
) -> dict[str, object]:
    if artifact_id not in cache:
        cache[artifact_id] = store.read_json(artifacts[artifact_id])
    value = cache[artifact_id]
    assert isinstance(value, dict)
    return value


def _binary_artifact(
    store: _ArtifactStore,
    artifacts: Mapping[str, Mapping[str, object]],
    cache: dict[str, object],
    artifact_id: str,
) -> bytes:
    if artifact_id not in cache:
        cache[artifact_id] = store.read(artifacts[artifact_id])
    value = cache[artifact_id]
    assert isinstance(value, bytes)
    return value


def _public_key_registry(value: object, authority: Mapping[str, object]) -> tuple[bytes, str]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "kind", "keys"}:
        raise HostEvidenceError("public key registry fields drifted")
    keys = value["keys"]
    if (
        value["schema_version"] != 1
        or value["kind"] != "w3-protected-public-key-registry"
        or not isinstance(keys, list)
        or len(keys) != 1
    ):
        raise HostEvidenceError("public key registry identity invalid")
    row = keys[0]
    fields = {"mode", "algorithm", "key_id", "public_key"}
    if not isinstance(row, Mapping) or set(row) != fields:
        raise HostEvidenceError("public key row fields drifted")
    signing = authority["signing"]
    if (
        row["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
        or row["algorithm"] != protocol.PRODUCTION_ALGORITHM
        or row["key_id"] != signing["key_id"]
        or row["public_key"] != signing["public_key"]
    ):
        raise HostEvidenceError("public key registry is not authority-bound")
    try:
        public_key = protocol.ed25519.decode_public_key(row["public_key"])
    except protocol.ed25519.Ed25519ContractError as error:
        raise HostEvidenceError(f"public key invalid: {error.reason}") from error
    return public_key, str(row["key_id"])


def _read_installed_file(path: Path, context: _ValidationContext) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    current = -1
    descriptor = -1
    try:
        if context.attestable:
            if not path.is_absolute():
                raise HostEvidenceError("installed preimage path is not fixed absolute")
            current = os.open("/", directory_flags)
            for component in path.parent.parts[1:]:
                following = os.open(component, directory_flags, dir_fd=current)
                os.close(current)
                current = following
                parent_info = os.fstat(current)
                if (
                    not stat.S_ISDIR(parent_info.st_mode)
                    or parent_info.st_uid != 0
                    or parent_info.st_mode & 0o022
                ):
                    raise HostEvidenceError("installed preimage ancestry is unsafe")
        else:
            if path not in context.installed_paths.values():
                raise HostEvidenceError("fixture installed path is caller-selected")
            current = os.open(path.parent, directory_flags)
            parent_info = os.fstat(current)
            named_parent = path.parent.lstat()
            if (
                not stat.S_ISDIR(parent_info.st_mode)
                or parent_info.st_uid != context.expected_uid
                or parent_info.st_mode & 0o022
                or (parent_info.st_dev, parent_info.st_ino)
                != (named_parent.st_dev, named_parent.st_ino)
            ):
                raise HostEvidenceError("fixture installed ancestry is unsafe")
        descriptor = os.open(path.name, flags, dir_fd=current)
        info = os.fstat(descriptor)
        initial_named = os.stat(path.name, dir_fd=current, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != (initial_named.st_dev, initial_named.st_ino)
            or info.st_size <= 0
        ):
            raise HostEvidenceError("installed preimage metadata invalid")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise HostEvidenceError("installed preimage truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise HostEvidenceError("installed preimage grew")
        final = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=current, follow_symlinks=False)
        identity_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
        )
        if any(getattr(final, field) != getattr(info, field) for field in identity_fields) or any(
            getattr(named, field) != getattr(info, field) for field in identity_fields
        ):
            raise HostEvidenceError("installed preimage named identity changed")
        return b"".join(chunks), final
    except HostEvidenceError:
        raise
    except OSError as error:
        raise HostEvidenceError(f"installed preimage unavailable: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if current >= 0:
            os.close(current)


def _cross_bind_bundle_and_installed_files(
    bundle: Mapping[str, object],
    authority: Mapping[str, object],
    context: _ValidationContext,
) -> None:
    bundle_rows = bundle.get("artifacts")
    if not isinstance(bundle_rows, list):
        raise HostEvidenceError("bundle artifact roster unavailable")
    bundle_by_role: dict[str, Mapping[str, object]] = {}
    for row in bundle_rows:
        if not isinstance(row, Mapping) or type(row.get("role")) is not str:
            raise HostEvidenceError("bundle artifact row invalid")
        if row["role"] in bundle_by_role:
            raise HostEvidenceError("bundle artifact role duplicate")
        bundle_by_role[str(row["role"])] = row
    install_roster = bundle.get("install_roster")
    if (
        not isinstance(install_roster, Mapping)
        or set(install_roster) != {"files", "bytes", "sha256", "entries"}
        or not isinstance(install_roster["entries"], list)
    ):
        raise HostEvidenceError("bundle complete install roster unavailable")
    install_rows: list[Mapping[str, object]] = []
    for row in install_roster["entries"]:
        if not isinstance(row, Mapping):
            raise HostEvidenceError("bundle install roster row invalid")
        install_rows.append(row)
    measured_by_path: dict[str, tuple[bytes, os.stat_result]] = {}
    install_by_path: dict[str, Mapping[str, object]] = {}
    for install_row in install_rows:
        path_value = install_row.get("path")
        if type(path_value) is not str:
            raise HostEvidenceError("bundle install roster path invalid")
        installed_path = Path(path_value)
        if path_value in install_by_path:
            raise HostEvidenceError("bundle full install roster path duplicate")
        if not context.attestable and installed_path not in context.installed_paths.values():
            raise HostEvidenceError("fixture full installed roster path is not frozen")
        payload, info = _read_installed_file(installed_path, context)
        if (
            type(install_row.get("size")) is not int
            or type(install_row.get("mode")) is not int
            or type(install_row.get("uid")) is not int
            or type(install_row.get("gid")) is not int
            or install_row.get("size") != info.st_size
            or stat.S_IMODE(int(install_row["mode"])) != stat.S_IMODE(info.st_mode)
            or install_row.get("sha256") != _raw_digest(payload)
        ):
            raise HostEvidenceError("bundle full install roster measurement mismatch")
        if context.attestable and (
            install_row["uid"] != info.st_uid or install_row["gid"] != info.st_gid
        ):
            raise HostEvidenceError("bundle full install roster ownership mismatch")
        measured_by_path[path_value] = (payload, info)
        install_by_path[path_value] = install_row
    roster = authority["installed_code_roster"]
    if not isinstance(roster, list):
        raise HostEvidenceError("authority installed roster invalid")
    by_path = {str(row["path"]): row for row in roster}
    try:
        authority_path_map = dict(context.authority_path_mapper(install_rows))
    except Exception as error:
        raise HostEvidenceError(f"bundle authority path map invalid: {error}") from error
    if (
        not authority_path_map
        or list(authority_path_map) != sorted(authority_path_map)
        or len(set(authority_path_map.values())) != len(authority_path_map)
    ):
        raise HostEvidenceError("bundle authority path map invalid")
    declared_authority_paths = bundle.get("authority_roster_paths")
    if declared_authority_paths != sorted(authority_path_map.values()):
        raise HostEvidenceError("bundle authority roster path declaration mismatch")
    expected_rows: dict[str, Mapping[str, object]] = {}
    for logical_path, installed_path in authority_path_map.items():
        install_row = install_by_path.get(installed_path)
        if install_row is None:
            raise HostEvidenceError("bundle authority path missing from full install roster")
        expected_rows[logical_path] = install_row
    role_by_installed_path = {
        str(context.installed_paths[role]): role for role in context.logical_paths
    }
    if set(by_path) != set(expected_rows):
        raise HostEvidenceError("authority installed roster is not complete")
    for logical_path, install_row in expected_rows.items():
        row = by_path[logical_path]
        installed_path = Path(str(install_row["path"]))
        role = role_by_installed_path.get(str(installed_path))
        if not context.attestable and installed_path not in context.installed_paths.values():
            raise HostEvidenceError("fixture full installed roster path is not frozen")
        if any(
            install_row.get(field) != row[field]
            for field in ("size", "sha256", "uid", "gid", "mode")
        ):
            raise HostEvidenceError("bundle/authority full roster measurement mismatch")
        payload, info = measured_by_path[str(installed_path)]
        if (
            info.st_size != row["size"]
            or stat.S_IMODE(info.st_mode) != stat.S_IMODE(int(row["mode"]))
            or info.st_nlink != row["nlink"]
            or info.st_dev != row["dev"]
            or info.st_ino != row["ino"]
            or _raw_digest(payload) != row["sha256"]
        ):
            raise HostEvidenceError("installed file does not match authority roster")
        if context.attestable and (info.st_uid != row["uid"] or info.st_gid != row["gid"]):
            raise HostEvidenceError("installed file ownership mismatch")
        if role is None:
            continue
        bundle_row = bundle_by_role.get(role)
        if bundle_row is None:
            raise HostEvidenceError("bundle or installed role missing")
        if bundle_row.get("size") != row["size"] or bundle_row.get("sha256") != row["sha256"]:
            raise HostEvidenceError("bundle/authority role measurement mismatch")
    installed_code_paths = authority["installed_code_paths"]
    if not isinstance(installed_code_paths, Mapping):
        raise HostEvidenceError("authority installed code paths invalid")
    for role in protocol.INSTALLED_CODE_ROLES:
        if installed_code_paths.get(role) != context.logical_paths.get(role):
            raise HostEvidenceError("authority installed code path drifted")


def _execution_context(
    value: object,
    *,
    run_id: str,
    role: str,
    candidate_id: str,
    candidate_sha256: str,
    bindings: Mapping[str, object],
) -> dict[str, object]:
    fields = {
        "schema_version",
        "kind",
        "run_id",
        "role",
        "candidate_id",
        "candidate_artifact_sha256",
        "command_sha256",
        "bundle_sha256",
        "authority_sha256",
        "client_nonce",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise HostEvidenceError("execution context fields drifted")
    body = dict(value)
    expected = {
        "schema_version": 1,
        "kind": "w3-phase-b-execution-context",
        "run_id": run_id,
        "role": role,
        "candidate_id": candidate_id,
        "candidate_artifact_sha256": candidate_sha256,
        "command_sha256": bindings["command_sha256"],
        "bundle_sha256": bindings["bundle_sha256"],
        "authority_sha256": bindings["authority_sha256"],
    }
    if any(body[key] != expected[key] for key in expected):
        raise HostEvidenceError("execution context cross-binding mismatch")
    nonce = body["client_nonce"]
    if type(nonce) is not str or _NONCE_RE.fullmatch(nonce) is None:
        raise HostEvidenceError("execution context nonce invalid")
    return body


def _validate_census(
    value: object,
    *,
    kind: str,
    run_id: str,
    role: str,
    candidate_id: str,
    nonce: str,
    cleanup_sha256: str,
    native_observation: Mapping[str, object],
) -> None:
    tail_fields: Mapping[str, object]
    if kind == "process":
        tail_fields = {"residual_children": 0, "members": []}
    elif kind == "fd":
        tail_fields = {"retained_fds": 0, "fds": []}
    elif kind == "temp":
        tail_fields = {"entries": []}
    else:  # pragma: no cover - internal closed enum
        raise HostEvidenceError("census kind invalid")
    expected = {
        "schema_version": 1,
        "kind": f"w3-phase-b-{kind}-census",
        "run_id": run_id,
        "role": role,
        "candidate_id": candidate_id,
        "client_nonce": nonce,
        "cleanup_sha256": cleanup_sha256,
        **tail_fields,
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise HostEvidenceError(f"{kind} census semantic mismatch")
    if any(value.get(field) != observed for field, observed in native_observation.items()):
        raise HostEvidenceError(f"{kind} census is not native-cleanup-bound")


def _decode_native_cleanup(
    payload: bytes,
    *,
    stdout_size: int,
    stderr_size: int,
    authority: Mapping[str, object],
) -> Mapping[str, Mapping[str, object]]:
    from runtime import w3_broker_service as service

    if len(payload) != service.NATIVE_CLEANUP_BYTES or payload[:8] != service.NATIVE_CLEANUP_MAGIC:
        raise HostEvidenceError("native cleanup record identity invalid")
    values = struct.unpack(">16I", payload[8:])
    (
        version,
        flags,
        process_group_residual,
        retained_fds,
        temp_entries,
        wait_kind,
        wait_value,
        cleanup_stdout_size,
        cleanup_stderr_size,
        broker_uid,
        broker_gid,
        launcher_uid,
        launcher_gid,
        runner_uid,
        runner_gid,
        child_boundary_succeeded,
    ) = values
    expected_flags = service.FLAG_EXITED | service.REQUIRED_CLEANUP_FLAGS
    if (
        version != service.NATIVE_RESULT_VERSION
        or flags != expected_flags
        or wait_kind != service.WAIT_EXITED
        or wait_value != 0
        or cleanup_stdout_size != stdout_size
        or cleanup_stderr_size != stderr_size
        or process_group_residual != 0
        or retained_fds != 0
        or temp_entries != 0
        or broker_uid != authority["broker_identity"]["uid"]
        or broker_gid != authority["broker_identity"]["gid"]
        or launcher_uid != 0
        or launcher_gid != 0
        or runner_uid != authority["runner_identity"]["uid"]
        or runner_gid != authority["runner_identity"]["gid"]
        or child_boundary_succeeded != 1
    ):
        raise HostEvidenceError("native cleanup record semantic mismatch")
    return {
        "process": {"residual_children": process_group_residual},
        "fd": {"retained_fds": retained_fds},
        "temp": {"entries": [] if temp_entries == 0 else [temp_entries]},
    }


def _validate_receipt_binding(
    receipt: Mapping[str, object],
    request: Mapping[str, object],
    authority: Mapping[str, object],
    *,
    public_key: bytes,
    key_id: str,
) -> None:
    request_binding = {
        "request_hash": request["request_hash"],
        "client_nonce": request["client_nonce"],
        "claimed_authority_sha256": request["claimed_authority_sha256"],
        "claimed_release_sha256": request["claimed_release_sha256"],
        "claimed_policy_sha256": request["claimed_policy_sha256"],
    }
    authority_sha256 = protocol.authority_hash(authority)
    release = authority["release_identity"]
    policy = authority["policy_identity"]
    if receipt["request"] != request_binding:
        raise HostEvidenceError("receipt request binding mismatch")
    if receipt["measured"] != {
        "authority_sha256": authority_sha256,
        "release_sha256": release["ancestry_root_sha256"],
        "policy_sha256": policy["resolved_sha256"],
    }:
        raise HostEvidenceError("receipt measured binding mismatch")
    if receipt["policy"] != policy or receipt["roster"] != {
        "pre": authority["installed_code_roster"],
        "post": authority["installed_code_roster"],
    }:
        raise HostEvidenceError("receipt policy or roster binding mismatch")
    installed = authority["installed_code_identity"]
    identities = receipt["identities"]
    expected_identities = {
        "broker": {
            "user": "_metisbroker",
            "code_sha256": installed["broker_code_sha256"],
        },
        "launcher": {"code_sha256": installed["launcher_sha256"]},
        "worker": {"code_sha256": installed["worker_sha256"]},
        "node": {"sha256": installed["node_sha256"], "version": "v22.22.3"},
        "loader": {"sha256": installed["loader_sha256"]},
    }
    expected_ids = {
        "broker_uid": authority["broker_identity"]["uid"],
        "broker_gid": authority["broker_identity"]["gid"],
        "runner_uid": authority["runner_identity"]["uid"],
        "runner_gid": authority["runner_identity"]["gid"],
        "launcher_uid": 0,
        "launcher_gid": 0,
    }
    if identities != expected_identities or receipt["effective_ids"] != expected_ids:
        raise HostEvidenceError("receipt installed identity binding mismatch")
    try:
        verified = protocol.verify_receipt_signature(
            receipt,
            public_key=public_key,
            registered_key_id=key_id,
        )
    except protocol.BrokerProtocolError as error:
        raise HostEvidenceError(f"receipt signature invalid: {error.reason}") from error
    if verified is not True:
        raise HostEvidenceError("receipt signature invalid")


def _validate_complete(body: dict[str, object], context: _ValidationContext) -> dict[str, object]:
    artifacts, predicates, runs = _structure_complete(body)
    store = _ArtifactStore(context)
    cache: dict[str, object] = {}
    bindings = _validate_bindings(body["bindings"], complete=True)

    command = _canonical_artifact(store, artifacts, cache, "preimage:command")
    if command != dict(COMMAND_DOCUMENT):
        raise HostEvidenceError("host command preimage drifted")
    bundle_raw = _canonical_artifact(store, artifacts, cache, "preimage:bundle")
    try:
        bundle = dict(context.bundle_validator(bundle_raw))
    except Exception as error:
        raise HostEvidenceError(f"install bundle invalid: {error}") from error
    authority_raw = _canonical_artifact(store, artifacts, cache, "preimage:authority")
    try:
        authority = protocol.validate_authority(authority_raw)
    except protocol.BrokerProtocolError as error:
        raise HostEvidenceError(f"authority invalid: {error.reason}") from error
    if authority["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
        raise HostEvidenceError("authority mode is not protected public synthetic")
    registry = _canonical_artifact(
        store,
        artifacts,
        cache,
        "preimage:public-key-registry",
    )
    public_key, key_id = _public_key_registry(registry, authority)
    roster = _canonical_artifact(store, artifacts, cache, "preimage:installed-roster")
    if set(roster) != {"schema_version", "kind", "entries"} or roster != {
        "schema_version": 1,
        "kind": "w3-phase-b-installed-roster",
        "entries": authority["installed_code_roster"],
    }:
        raise HostEvidenceError("installed roster preimage mismatch")

    semantic_bundle_sha256 = bundle.get("bundle_sha256")
    if _digest(semantic_bundle_sha256, "bundle semantic sha256") is None:
        raise HostEvidenceError("bundle semantic digest missing")
    expected_bindings = {
        "command_sha256": artifacts["preimage:command"]["sha256"],
        "bundle_sha256": semantic_bundle_sha256,
        "authority_sha256": protocol.authority_hash(authority),
        "public_key_sha256": _raw_digest(public_key),
        "installed_roster_sha256": artifacts["preimage:installed-roster"]["sha256"],
    }
    if any(bindings[field] != value for field, value in expected_bindings.items()):
        raise HostEvidenceError("semantic binding does not match loaded preimage")
    _cross_bind_bundle_and_installed_files(bundle, authority, context)

    predicate_digests: set[str] = set()
    for row in predicates:
        artifact_id = str(row["artifact_id"])
        predicate = _canonical_artifact(store, artifacts, cache, artifact_id)
        expected = {
            "schema_version": 1,
            "kind": "w3-phase-b-host-predicate",
            "obligation_id": row["obligation_id"],
            "polarity": row["polarity"],
            "passed": True,
        }
        if predicate != expected:
            raise HostEvidenceError("predicate artifact semantic identity mismatch")
        raw_digest = str(artifacts[artifact_id]["sha256"])
        if raw_digest in predicate_digests:
            raise HostEvidenceError("predicate artifact content reused")
        predicate_digests.add(raw_digest)

    nonces: set[str] = set()
    execution_digests: dict[str, set[str]] = {
        "receipt": set(),
        "publication": set(),
        "process": set(),
        "fd": set(),
        "temp": set(),
    }
    previous_receipt = protocol.GENESIS_RECEIPT_DIGEST
    broker_nonces: set[str] = set()
    sequence = 0
    for run in runs:
        run_id = str(run["run_id"])
        candidates: dict[str, str] = {}
        for candidate_row in run["candidates"]:
            candidate_id = str(candidate_row["candidate_id"])
            artifact_id = str(candidate_row["artifact_id"])
            candidate = _canonical_artifact(store, artifacts, cache, artifact_id)
            if candidate != {
                "schema_version": 1,
                "kind": "w3-phase-b-candidate-preimage",
                "run_id": run_id,
                "candidate_id": candidate_id,
            }:
                raise HostEvidenceError("candidate preimage semantic mismatch")
            candidates[candidate_id] = str(artifacts[artifact_id]["sha256"])
        for execution in run["executions"]:
            sequence += 1
            role = str(execution["role"])
            candidate_id = str(execution["candidate_id"])
            context_id = str(execution["context_artifact_id"])
            context_document = _canonical_artifact(store, artifacts, cache, context_id)
            execution_context = _execution_context(
                context_document,
                run_id=run_id,
                role=role,
                candidate_id=candidate_id,
                candidate_sha256=candidates[candidate_id],
                bindings=bindings,
            )
            nonce = str(execution_context["client_nonce"])
            if nonce in nonces:
                raise HostEvidenceError("execution nonce reused")
            nonces.add(nonce)
            request_id = str(execution["request_artifact_id"])
            request_raw = _canonical_artifact(store, artifacts, cache, request_id)
            try:
                request = protocol.validate_request(request_raw)
            except protocol.BrokerProtocolError as error:
                raise HostEvidenceError(f"broker request invalid: {error.reason}") from error
            expected_inputs = {
                "bundle": bindings["bundle_sha256"],
                "candidate": candidates[candidate_id],
                "host_command_digest": bindings["command_sha256"],
                "context": artifacts[context_id]["sha256"],
            }
            if (
                request["client_nonce"] != nonce
                or request["payload"] != {"task": f"phase-b-host-{role}", "inputs": expected_inputs}
                or request["claimed_authority_sha256"] != bindings["authority_sha256"]
                or request["claimed_release_sha256"]
                != authority["release_identity"]["ancestry_root_sha256"]
                or request["claimed_policy_sha256"]
                != authority["policy_identity"]["resolved_sha256"]
            ):
                raise HostEvidenceError("request run/role/candidate binding mismatch")
            receipt_id = str(execution["receipt_artifact_id"])
            receipt_raw = _canonical_artifact(store, artifacts, cache, receipt_id)
            try:
                receipt = protocol.validate_receipt(receipt_raw)
            except protocol.BrokerProtocolError as error:
                raise HostEvidenceError(f"broker receipt invalid: {error.reason}") from error
            _validate_receipt_binding(
                receipt,
                request,
                authority,
                public_key=public_key,
                key_id=key_id,
            )
            broker_nonce = str(receipt["broker_nonce"])
            if broker_nonce in broker_nonces:
                raise HostEvidenceError("receipt broker nonce reused")
            broker_nonces.add(broker_nonce)
            if (
                receipt["receipt_sequence"] != sequence
                or receipt["attempt_sequence"] < sequence
                or receipt["previous_receipt_sha256"] != previous_receipt
            ):
                raise HostEvidenceError("receipt sequence or chain mismatch")
            previous_receipt = protocol.receipt_hash(receipt)

            publication_id = str(execution["publication_artifact_id"])
            stdout_id = str(execution["stdout_artifact_id"])
            stderr_id = str(execution["stderr_artifact_id"])
            publication = _binary_artifact(store, artifacts, cache, publication_id)
            stdout = _binary_artifact(store, artifacts, cache, stdout_id)
            stderr = _binary_artifact(store, artifacts, cache, stderr_id)
            output = receipt["output"]
            if (
                output["stdout_sha256"] != _raw_digest(stdout)
                or output["stderr_sha256"] != _raw_digest(stderr)
                or output["publication"]
                != {
                    "sha256": _raw_digest(publication),
                    "size": len(publication),
                    "atomic": True,
                }
            ):
                raise HostEvidenceError("receipt output preimage mismatch")

            cleanup_id = str(execution["cleanup_artifact_id"])
            cleanup = _binary_artifact(store, artifacts, cache, cleanup_id)
            cleanup_sha256 = _raw_digest(cleanup)
            native_observations = _decode_native_cleanup(
                cleanup,
                stdout_size=len(stdout),
                stderr_size=len(stderr),
                authority=authority,
            )
            cleanup_claims = receipt["cleanup"]
            if (
                output["exit_code"] != 0
                or cleanup_claims["process_census"]["census_sha256"] != cleanup_sha256
                or cleanup_claims["fd_census"]["census_sha256"] != cleanup_sha256
                or cleanup_claims["temp_census"]["roster_sha256"] != cleanup_sha256
            ):
                raise HostEvidenceError("receipt cleanup preimage mismatch")
            census_fields = (
                ("process", "process_census_artifact_id"),
                ("fd", "fd_census_artifact_id"),
                ("temp", "temp_census_artifact_id"),
            )
            for census_kind, field in census_fields:
                census_id = str(execution[field])
                census = _canonical_artifact(store, artifacts, cache, census_id)
                _validate_census(
                    census,
                    kind=census_kind,
                    run_id=run_id,
                    role=role,
                    candidate_id=candidate_id,
                    nonce=nonce,
                    cleanup_sha256=cleanup_sha256,
                    native_observation=native_observations[census_kind],
                )
                census_digest = str(artifacts[census_id]["sha256"])
                if census_digest in execution_digests[census_kind]:
                    raise HostEvidenceError("census preimage reused across executions")
                execution_digests[census_kind].add(census_digest)
            for digest_kind, artifact_id in (
                ("receipt", receipt_id),
                ("publication", publication_id),
            ):
                raw_digest = str(artifacts[artifact_id]["sha256"])
                if raw_digest in execution_digests[digest_kind]:
                    raise HostEvidenceError(f"{digest_kind} preimage reused")
                execution_digests[digest_kind].add(raw_digest)
    if sequence != TARGETS["physical_executions"]:
        raise HostEvidenceError("physical execution denominator not closed")
    return body


def validate_host_evidence(document: Mapping[str, Any]) -> dict[str, object]:
    """Validate only the honest source-tree ``not-run`` document.

    Complete evidence cannot choose its evidence root and remains unavailable
    until a separately authorized Phase-B collector/verifier exists.
    """

    body = _document_body(document)
    if body["status"] == "complete":
        raise HostEvidenceError("complete evidence requires the fixed installed evidence root")
    observed = {field: 0 for field in TARGETS}
    _validate_summary(body, observed)
    bindings = _validate_bindings(body["bindings"], complete=False)
    if (
        any(value is not None for key, value in bindings.items() if key != "caller_account")
        or body["artifact_roster"]
        or body["host_predicates"]
        or body["runs"]
        or body["summary"]["gaps"] is not None
    ):
        raise HostEvidenceError("not-run evidence must remain zero with unknown gaps")
    return body


def _production_context() -> _ValidationContext:
    from runtime import w3_broker_installer as installer

    return _ValidationContext(
        roots={"evidence": INSTALLED_EVIDENCE_ROOT, "installed": INSTALLED_APP_ROOT},
        installed_paths={
            role: Path(installer.EXPECTED_ARTIFACT_PATHS[role])
            for role in installer.AUTHORITY_LOGICAL_PATHS
        },
        logical_paths=dict(installer.AUTHORITY_LOGICAL_PATHS),
        bundle_validator=lambda document: installer.validate_bundle_manifest(
            document,
            require_frozen=True,
        ),
        authority_path_mapper=installer.authority_roster_path_map,
        expected_uid=0,
        expected_gid=0,
        attestable=True,
    )


def load_installed_host_evidence() -> dict[str, object]:
    """Secure-read the fixed manifest, then deny unavailable host attestation."""

    context = _production_context()
    store = _ArtifactStore(context)
    manifest = store.read_fixed_manifest()
    body = _document_body(manifest)
    if body["status"] != "complete":
        raise HostEvidenceError("installed evidence is not complete")
    raise HostEvidenceError("PHASE_B_HOST_COLLECTOR_VERIFIER_UNAVAILABLE")


def validate_unprotected_fixture_evidence(
    document: Mapping[str, Any],
    *,
    evidence_root: Path,
    installed_root: Path,
    installed_paths: Mapping[str, Path],
    logical_paths: Mapping[str, str],
    bundle_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, object]:
    """Exercise the complete contract locally; confers zero host-evidence credit."""

    body = _document_body(document)
    if body["status"] != "complete":
        raise HostEvidenceError("fixture complete validator requires complete status")
    frozen_paths = dict(installed_paths)
    frozen_logical_paths = dict(logical_paths)
    logical_by_installed = {
        str(frozen_paths[role]): logical for role, logical in frozen_logical_paths.items()
    }

    def fixture_authority_path_mapper(
        rows: Sequence[Mapping[str, object]],
    ) -> Mapping[str, str]:
        result: dict[str, str] = {}
        for row in rows:
            mode = row.get("mode")
            if (
                row.get("uid") != 0
                or row.get("gid") != 0
                or type(mode) is not int
                or int(mode) & 0o022
            ):
                continue
            installed_path = str(row.get("path"))
            logical = logical_by_installed.get(
                installed_path,
                "installed-tree/" + hashlib.sha256(installed_path.encode()).hexdigest(),
            )
            if logical in result or installed_path in result.values():
                raise HostEvidenceError("fixture authority path map collision")
            result[logical] = installed_path
        return dict(sorted(result.items()))

    context = _ValidationContext(
        roots={"evidence": Path(evidence_root), "installed": Path(installed_root)},
        installed_paths=frozen_paths,
        logical_paths=frozen_logical_paths,
        bundle_validator=bundle_validator,
        authority_path_mapper=fixture_authority_path_mapper,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        attestable=False,
    )
    return _validate_complete(body, context)


__all__ = [
    "HOST_OBLIGATION_IDS",
    "HostEvidenceError",
    "INSTALLED_EVIDENCE_MANIFEST_PATH",
    "INSTALLED_EVIDENCE_ROOT",
    "NONCLAIMS",
    "POLARITIES",
    "RUN_IDS",
    "SEMANTIC_ROLES",
    "TARGETS",
    "initial_not_run_document",
    "load_installed_host_evidence",
    "validate_host_evidence",
    "validate_unprotected_fixture_evidence",
]
