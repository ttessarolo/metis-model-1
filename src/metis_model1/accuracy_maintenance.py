"""Fail-closed local draft contract for the Model 1 maintenance benchmark.

This module deliberately does **not** mint a T30 seal.  A publishable pre-output
seal requires a future verifier that re-reads the exact roster bytes from a
Model 1 Git commit already pushed to the configured remote ref.  Until that
verifier is wired, a complete roster is only ``LOCAL_UNPUBLISHED_DRAFT`` and no
raw dictionary, matching file hash, Python object, or copied seal hash can be
used as evaluation authority.

The local draft is still strict: it binds 18 D18 and 30 T30 tasks, validates
role-specific JSON evidence, derives provenance roots, checks one executable
upstream pin/probe bundle, enforces an exact construct registry and the catalog
reservations, and reads evidence through descriptor-relative no-follow opens.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

SCHEMA_VERSION = 1
FAMILIES = tuple(f"F-{number}" for number in range(1, 7))
SPLITS = ("D18", "T30")
EXPECTED_SPLIT_COUNTS = {"D18": 18, "T30": 30}
EXPECTED_FAMILY_COUNTS = {
    "D18": {family: 3 for family in FAMILIES},
    "T30": {family: 5 for family in FAMILIES},
}
REQUIRED_PIN_PROBES = (
    "grammar",
    "validator",
    "compiler",
    "ir_contract",
    "retrieval_contract",
    "semantic_oracle",
    "tenant_threshold_setting_keys",
)

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_ARTIFACT_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
_FIXED_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "accuracy-maintenance-roster.schema.json"
)
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024

_ROSTER_KEYS = frozenset(
    {
        "schema_version",
        "roster_id",
        "status",
        "authority_status",
        "model_outputs_observed",
        "upstream_pin",
        "construct_registry",
        "tasks",
        "counts",
        "roster_sha256",
    }
)
_PIN_KEYS = frozenset({"repository", "revision", "tree", "probe_receipt"})
_REGISTRY_KEYS = frozenset({"registry_id", "entries", "registry_sha256"})
_REGISTRY_ENTRY_KEYS = frozenset({"construct", "families", "catalog_domain", "oracle_authority"})
_TASK_KEYS = frozenset(
    {
        "task_id",
        "split",
        "family",
        "construct",
        "prompt",
        "truth",
        "oracle_receipt",
        "retrieval_evidence",
        "genealogy",
        "provenance_root_sha256",
        "content_root_sha256",
        "genealogy_root_sha256",
        "identifier_root_sha256",
        "normalized_ast_root_sha256",
        "normalized_ir_root_sha256",
        "expected_output_root_sha256",
        "upstream_revision",
        "upstream_tree",
        "pre_output_status",
    }
)
_REFERENCE_KEYS = frozenset({"path", "sha256"})
_RETRIEVAL_RECEIPT_KEYS = frozenset({"kind", "path", "sha256"})
_NON_CATALOG_KEYS = frozenset({"kind", "marker"})
_COUNTS_KEYS = frozenset({"D18", "T30", "total"})
_SPLIT_COUNTS_KEYS = frozenset({"tasks", "families"})
_PROBE_KEYS = frozenset(
    {
        "schema_version",
        "evidence_role",
        "repository",
        "revision",
        "tree",
        "probes",
        "pre_output",
    }
)
_PROMPT_KEYS = frozenset(
    {
        "schema_version",
        "evidence_role",
        "task_id",
        "split",
        "family",
        "construct",
        "upstream_revision",
        "upstream_tree",
        "payload",
        "payload_sha256",
        "pre_output",
    }
)
_TRUTH_KEYS = frozenset(
    {
        "schema_version",
        "evidence_role",
        "task_id",
        "split",
        "family",
        "construct",
        "upstream_revision",
        "upstream_tree",
        "prompt_sha256",
        "expected_output",
        "expected_output_sha256",
        "normalized_ast_sha256",
        "normalized_ir_sha256",
        "pre_output",
    }
)
_ORACLE_KEYS = frozenset(
    {
        "schema_version",
        "evidence_role",
        "task_id",
        "split",
        "family",
        "construct",
        "upstream_revision",
        "upstream_tree",
        "truth_sha256",
        "authority",
        "status",
        "result",
        "result_sha256",
        "normalized_ast_sha256",
        "normalized_ir_sha256",
        "pre_output",
    }
)
_RETRIEVAL_KEYS = frozenset(
    {
        "schema_version",
        "evidence_role",
        "task_id",
        "split",
        "family",
        "construct",
        "upstream_revision",
        "upstream_tree",
        "prompt_sha256",
        "authority",
        "status",
        "request",
        "request_sha256",
        "result",
        "result_sha256",
        "tenant_values_materialized_in_prompt",
        "pre_output",
    }
)
_GENEALOGY_KEYS = frozenset(
    {
        "schema_version",
        "evidence_role",
        "task_id",
        "split",
        "family",
        "construct",
        "parent_roots",
        "template_roots",
        "identifiers",
        "normalized_ast_identities",
        "normalized_ir_identities",
        "pre_output",
    }
)


class AccuracyMaintenanceError(ValueError):
    """Raised when a maintenance roster cannot prove its local-draft contract."""


class MaintenanceAuthorityUnavailableError(AccuracyMaintenanceError):
    """Raised while the pushed-Git-preimage seal verifier is not wired."""


@dataclass(frozen=True, slots=True)
class MaintenanceTaskBinding:
    """Exact, non-authoritative task binding extracted from a local draft."""

    task_id: str
    split: str
    family: str
    construct: str
    catalog_domain: bool
    prompt_sha256: str
    truth_sha256: str
    oracle_receipt_sha256: str
    retrieval_receipt_sha256: str | None
    genealogy_receipt_sha256: str
    prompt_payload_sha256: str
    retrieval_request_sha256: str | None
    retrieval_result_sha256: str | None
    parent_roots: tuple[str, ...]
    template_roots: tuple[str, ...]
    identifiers: tuple[str, ...]
    normalized_ast_identities: tuple[str, ...]
    normalized_ir_identities: tuple[str, ...]
    provenance_root_sha256: str
    content_root_sha256: str
    genealogy_root_sha256: str
    identifier_root_sha256: str
    normalized_ast_root_sha256: str
    normalized_ir_root_sha256: str
    expected_output_root_sha256: str
    upstream_revision: str
    upstream_tree: str


@dataclass(frozen=True, slots=True)
class LocalMaintenanceDraft:
    """Validated local bytes that explicitly carry no evaluation authority."""

    _manifest_bytes: bytes
    artifact_root: Path
    artifact_root_identity: tuple[int, int]
    task_bindings: tuple[MaintenanceTaskBinding, ...]

    @property
    def authority_status(self) -> str:
        return "LOCAL_UNPUBLISHED_DRAFT"

    @property
    def manifest(self) -> dict[str, Any]:
        value = json.loads(self._manifest_bytes)
        assert isinstance(value, dict)
        return value

    @property
    def roster_sha256(self) -> str:
        return self.manifest["roster_sha256"]


class VerifiedMaintenanceRoster:
    """Reserved authority type; no issuer exists until the Git verifier lands."""

    def __new__(cls, *_args: Any, **_kwargs: Any) -> VerifiedMaintenanceRoster:
        raise TypeError("VerifiedMaintenanceRoster has no issuer: Git verifier is not wired")


@dataclass(frozen=True, slots=True)
class _ArtifactRootHandle:
    path: Path
    file_descriptor: int
    identity: tuple[int, int]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AccuracyMaintenanceError("value is not canonical JSON") from error


def _sha256_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _exact_mapping(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise AccuracyMaintenanceError(f"{label} must contain exactly {sorted(keys)}")
    return value


def _text(value: Any, label: str, *, maximum: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise AccuracyMaintenanceError(f"{label} must be a bounded non-empty string")
    return value


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label, maximum=128)
    if _ID_RE.fullmatch(text) is None:
        raise AccuracyMaintenanceError(f"{label} has an invalid identifier")
    return text


def _hash(value: Any, label: str) -> str:
    if type(value) is not str or _HASH_RE.fullmatch(value) is None:
        raise AccuracyMaintenanceError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _oid(value: Any, label: str) -> str:
    if type(value) is not str or _OID_RE.fullmatch(value) is None:
        raise AccuracyMaintenanceError(f"{label} must be a 40-character lowercase Git oid")
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise AccuracyMaintenanceError(f"{label} must be a non-negative integer")
    return value


def _json_value(value: Any, label: str) -> Any:
    _canonical(value)
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise AccuracyMaintenanceError(f"{label} has a non-string object key")
        return {key: _json_value(item, f"{label}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item, f"{label}[]") for item in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise AccuracyMaintenanceError(f"{label} is not JSON")


def _artifact_path(value: Any, label: str) -> str:
    text = _text(value, label, maximum=512)
    if (
        "\\" in text
        or _ARTIFACT_PATH_RE.fullmatch(text) is None
        or PurePosixPath(text).is_absolute()
        or any(part in {"", ".", ".."} for part in PurePosixPath(text).parts)
        or str(PurePosixPath(text)) != text
    ):
        raise AccuracyMaintenanceError(f"{label} must be a canonical relative artifact path")
    return text


def _open_artifact_root(value: Path | str) -> _ArtifactRootHandle:
    root = Path(os.path.abspath(Path(value)))
    try:
        before = os.lstat(root)
    except OSError as error:
        raise AccuracyMaintenanceError("artifact_root does not exist") from error
    if stat.S_ISLNK(before.st_mode):
        raise AccuracyMaintenanceError("artifact_root must not be a symlink")
    if not stat.S_ISDIR(before.st_mode):
        raise AccuracyMaintenanceError("artifact_root must be a directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as error:
        raise AccuracyMaintenanceError("artifact_root cannot be opened without symlinks") from error
    opened = os.fstat(descriptor)
    if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
        os.close(descriptor)
        raise AccuracyMaintenanceError("artifact_root changed while it was opened")
    return _ArtifactRootHandle(root, descriptor, (opened.st_dev, opened.st_ino))


def _artifact_bytes(root: _ArtifactRootHandle, relative: str, label: str) -> bytes:
    parts = PurePosixPath(relative).parts
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    file_flags = (
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    directory_descriptors: list[int] = [os.dup(root.file_descriptor)]
    directory_links: list[tuple[int, str, tuple[int, int]]] = []
    file_descriptor: int | None = None
    try:
        for part in parts[:-1]:
            parent_descriptor = directory_descriptors[-1]
            try:
                child_descriptor = os.open(part, directory_flags, dir_fd=parent_descriptor)
            except OSError as error:
                raise AccuracyMaintenanceError(
                    f"{label} does not exist or traverses a symlink: {relative}"
                ) from error
            metadata = os.fstat(child_descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child_descriptor)
                raise AccuracyMaintenanceError(f"{label} has a non-directory parent: {relative}")
            directory_descriptors.append(child_descriptor)
            directory_links.append((parent_descriptor, part, (metadata.st_dev, metadata.st_ino)))

        try:
            file_descriptor = os.open(parts[-1], file_flags, dir_fd=directory_descriptors[-1])
        except OSError as error:
            raise AccuracyMaintenanceError(
                f"{label} does not exist or traverses a symlink: {relative}"
            ) from error
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AccuracyMaintenanceError(f"{label} must be a regular file: {relative}")
        if before.st_nlink != 1:
            raise AccuracyMaintenanceError(f"{label} must not be a hard-linked file: {relative}")
        if before.st_size > _MAX_EVIDENCE_BYTES:
            raise AccuracyMaintenanceError(f"{label} exceeds the evidence size limit: {relative}")

        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining > 0:
            chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(file_descriptor)
        identity_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            raise AccuracyMaintenanceError(f"{label} changed while it was read: {relative}")
        if len(payload) != before.st_size:
            raise AccuracyMaintenanceError(f"{label} size changed while it was read: {relative}")

        path_after = os.stat(parts[-1], dir_fd=directory_descriptors[-1], follow_symlinks=False)
        if (path_after.st_dev, path_after.st_ino) != (before.st_dev, before.st_ino):
            raise AccuracyMaintenanceError(f"{label} path changed while it was read: {relative}")
        for parent_descriptor, part, expected_identity in directory_links:
            child_after = os.stat(part, dir_fd=parent_descriptor, follow_symlinks=False)
            if (child_after.st_dev, child_after.st_ino) != expected_identity:
                raise AccuracyMaintenanceError(
                    f"{label} parent changed while it was read: {relative}"
                )
        root_after = os.lstat(root.path)
        if (root_after.st_dev, root_after.st_ino) != root.identity:
            raise AccuracyMaintenanceError("artifact_root changed while evidence was read")
        return payload
    except OSError as error:
        raise AccuracyMaintenanceError(
            f"{label} cannot be read without path races: {relative}"
        ) from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(directory_descriptors):
            os.close(descriptor)


def _reference_bytes(
    value: Any,
    label: str,
    artifact_root: _ArtifactRootHandle,
) -> tuple[dict[str, str], bytes]:
    raw = _exact_mapping(value, _REFERENCE_KEYS, label)
    path = _artifact_path(raw["path"], f"{label}.path")
    expected = _hash(raw["sha256"], f"{label}.sha256")
    payload = _artifact_bytes(artifact_root, path, label)
    actual = "sha256:" + hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise AccuracyMaintenanceError(f"{label} hash drift for {path}")
    return {"path": path, "sha256": expected}, payload


def _json_evidence(
    value: Any,
    keys: frozenset[str],
    role: str,
    label: str,
    artifact_root: _ArtifactRootHandle,
) -> tuple[dict[str, str], Mapping[str, Any]]:
    reference, payload = _reference_bytes(value, label, artifact_root)

    def reject_constant(token: str) -> None:
        raise AccuracyMaintenanceError(f"{label} contains non-JSON number {token}")

    try:
        parsed = json.loads(payload.decode("utf-8"), parse_constant=reject_constant)
    except AccuracyMaintenanceError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AccuracyMaintenanceError(f"{label} must contain UTF-8 JSON") from error
    body = _exact_mapping(parsed, keys, label)
    if body.get("schema_version") != SCHEMA_VERSION or type(body.get("schema_version")) is not int:
        raise AccuracyMaintenanceError(f"{label}.schema_version must be integer 1")
    if body.get("evidence_role") != role:
        raise AccuracyMaintenanceError(f"{label} has the wrong evidence role")
    if body.get("pre_output") is not True:
        raise AccuracyMaintenanceError(f"{label} was not produced before model output")
    return reference, body


def _task_context(body: Mapping[str, Any], task: Mapping[str, Any], label: str) -> None:
    for field in (
        "task_id",
        "split",
        "family",
        "construct",
        "upstream_revision",
        "upstream_tree",
    ):
        if body.get(field) != task.get(field):
            raise AccuracyMaintenanceError(f"{label}.{field} does not bind its task")


def _hash_list(value: Any, label: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise AccuracyMaintenanceError(f"{label} must be a list")
    result = [_hash(item, f"{label}[]") for item in value]
    if len(result) != len(set(result)):
        raise AccuracyMaintenanceError(f"{label} contains duplicates")
    return result


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise AccuracyMaintenanceError(f"{label} must be a non-empty list")
    result = [_text(item, f"{label}[]", maximum=256) for item in value]
    if len(result) != len(set(result)):
        raise AccuracyMaintenanceError(f"{label} contains duplicates")
    return result


def _registry(value: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    raw = _exact_mapping(value, _REGISTRY_KEYS, "construct_registry")
    registry_id = _identifier(raw["registry_id"], "construct_registry.registry_id")
    if not isinstance(raw["entries"], list) or not raw["entries"]:
        raise AccuracyMaintenanceError("construct_registry.entries must be non-empty")
    entries: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for offset, item in enumerate(raw["entries"]):
        label = f"construct_registry.entries[{offset}]"
        entry = _exact_mapping(item, _REGISTRY_ENTRY_KEYS, label)
        construct = _identifier(entry["construct"], f"{label}.construct")
        if construct in index:
            raise AccuracyMaintenanceError("construct_registry contains duplicate constructs")
        if not isinstance(entry["families"], list) or not entry["families"]:
            raise AccuracyMaintenanceError(f"{label}.families must be non-empty")
        families = list(entry["families"])
        if any(family not in FAMILIES for family in families) or len(families) != len(
            set(families)
        ):
            raise AccuracyMaintenanceError(f"{label}.families are invalid or duplicated")
        if families != [family for family in FAMILIES if family in families]:
            raise AccuracyMaintenanceError(f"{label}.families must use canonical family order")
        if type(entry["catalog_domain"]) is not bool:
            raise AccuracyMaintenanceError(f"{label}.catalog_domain must be boolean")
        oracle_authority = _identifier(entry["oracle_authority"], f"{label}.oracle_authority")
        normalized = {
            "construct": construct,
            "families": families,
            "catalog_domain": entry["catalog_domain"],
            "oracle_authority": oracle_authority,
        }
        entries.append(normalized)
        index[construct] = normalized
    if [entry["construct"] for entry in entries] != sorted(index):
        raise AccuracyMaintenanceError("construct_registry entries must be sorted by construct")
    catalog_entries = [entry for entry in entries if entry["catalog_domain"]]
    if len(catalog_entries) != 1 or catalog_entries[0]["construct"] != "catalog_value_domain":
        raise AccuracyMaintenanceError(
            "catalog_value_domain must be the one exact catalog-domain construct"
        )
    if catalog_entries[0]["families"] != ["F-1", "F-6"]:
        raise AccuracyMaintenanceError("catalog_value_domain must authorize exactly F-1 and F-6")
    normalized_registry: dict[str, Any] = {
        "registry_id": registry_id,
        "entries": entries,
        "registry_sha256": _hash(raw["registry_sha256"], "construct_registry.registry_sha256"),
    }
    expected_hash = _sha256_json({"registry_id": registry_id, "entries": entries})
    if normalized_registry["registry_sha256"] != expected_hash:
        raise AccuracyMaintenanceError("construct_registry hash drift")
    return normalized_registry, index


def _pin(value: Any, artifact_root: _ArtifactRootHandle) -> dict[str, Any]:
    raw = _exact_mapping(value, _PIN_KEYS, "upstream_pin")
    if raw["repository"] != "ares-matioska/metis":
        raise AccuracyMaintenanceError("upstream_pin.repository must be ares-matioska/metis")
    revision = _oid(raw["revision"], "upstream_pin.revision")
    tree = _oid(raw["tree"], "upstream_pin.tree")
    reference, probe = _json_evidence(
        raw["probe_receipt"],
        _PROBE_KEYS,
        "upstream_probe_bundle",
        "upstream_pin.probe_receipt",
        artifact_root,
    )
    if (
        probe["repository"] != "ares-matioska/metis"
        or probe["revision"] != revision
        or probe["tree"] != tree
    ):
        raise AccuracyMaintenanceError("upstream probe bundle does not bind the declared pin")
    probes = _exact_mapping(
        probe["probes"], frozenset(REQUIRED_PIN_PROBES), "upstream probe bundle probes"
    )
    if any(probes[name] != "pass" for name in REQUIRED_PIN_PROBES):
        raise AccuracyMaintenanceError("upstream probe bundle is not all-pass")
    return {
        "repository": "ares-matioska/metis",
        "revision": revision,
        "tree": tree,
        "probe_receipt": reference,
    }


def _task(
    value: Any,
    offset: int,
    artifact_root: _ArtifactRootHandle,
    pin: Mapping[str, Any],
    registry: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], MaintenanceTaskBinding]:
    label = f"tasks[{offset}]"
    raw = _exact_mapping(value, _TASK_KEYS, label)
    task_id = _identifier(raw["task_id"], f"{label}.task_id")
    split = raw["split"]
    family = raw["family"]
    if split not in SPLITS:
        raise AccuracyMaintenanceError(f"{label}.split is outside D18/T30")
    if family not in FAMILIES:
        raise AccuracyMaintenanceError(f"{label}.family is outside F-1..F-6")
    construct = _identifier(raw["construct"], f"{label}.construct")
    construct_entry = registry.get(construct)
    if construct_entry is None or family not in construct_entry["families"]:
        raise AccuracyMaintenanceError(f"{label} is outside the exact construct registry")
    if raw["upstream_revision"] != pin["revision"] or raw["upstream_tree"] != pin["tree"]:
        raise AccuracyMaintenanceError(f"{label} differs from the one upstream pin")
    if raw["pre_output_status"] != "local_preoutput_evidence":
        raise AccuracyMaintenanceError(f"{label} is not local pre-output evidence")

    context = {
        "task_id": task_id,
        "split": split,
        "family": family,
        "construct": construct,
        "upstream_revision": pin["revision"],
        "upstream_tree": pin["tree"],
    }
    prompt_ref, prompt = _json_evidence(
        raw["prompt"], _PROMPT_KEYS, "maintenance_prompt", f"{label}.prompt", artifact_root
    )
    _task_context(prompt, context, f"{label}.prompt")
    prompt_payload = _json_value(prompt["payload"], f"{label}.prompt.payload")
    prompt_payload_sha256 = _hash(prompt["payload_sha256"], f"{label}.prompt.payload_sha256")
    if prompt_payload_sha256 != _sha256_json(prompt_payload):
        raise AccuracyMaintenanceError(f"{label}.prompt payload hash drift")

    truth_ref, truth = _json_evidence(
        raw["truth"], _TRUTH_KEYS, "maintenance_truth", f"{label}.truth", artifact_root
    )
    _task_context(truth, context, f"{label}.truth")
    if truth["prompt_sha256"] != prompt_ref["sha256"]:
        raise AccuracyMaintenanceError(f"{label}.truth prompt binding drift")
    expected_output = _json_value(truth["expected_output"], f"{label}.truth.expected_output")
    expected_output_sha256 = _hash(
        truth["expected_output_sha256"], f"{label}.truth.expected_output_sha256"
    )
    if expected_output_sha256 != _sha256_json(expected_output):
        raise AccuracyMaintenanceError(f"{label}.truth expected-output hash drift")
    normalized_ast_sha256 = _hash(
        truth["normalized_ast_sha256"], f"{label}.truth.normalized_ast_sha256"
    )
    normalized_ir_sha256 = _hash(
        truth["normalized_ir_sha256"], f"{label}.truth.normalized_ir_sha256"
    )

    oracle_ref, oracle = _json_evidence(
        raw["oracle_receipt"],
        _ORACLE_KEYS,
        "maintenance_oracle_receipt",
        f"{label}.oracle_receipt",
        artifact_root,
    )
    _task_context(oracle, context, f"{label}.oracle_receipt")
    if oracle["truth_sha256"] != truth_ref["sha256"]:
        raise AccuracyMaintenanceError(f"{label}.oracle truth binding drift")
    if oracle["authority"] != construct_entry["oracle_authority"]:
        raise AccuracyMaintenanceError(f"{label}.oracle authority registry drift")
    if oracle["status"] != "pass":
        raise AccuracyMaintenanceError(f"{label}.oracle status is not pass")
    oracle_result = _json_value(oracle["result"], f"{label}.oracle.result")
    if _hash(oracle["result_sha256"], f"{label}.oracle.result_sha256") != _sha256_json(
        oracle_result
    ):
        raise AccuracyMaintenanceError(f"{label}.oracle result hash drift")
    if (
        oracle["normalized_ast_sha256"] != normalized_ast_sha256
        or oracle["normalized_ir_sha256"] != normalized_ir_sha256
    ):
        raise AccuracyMaintenanceError(f"{label}.oracle normalized AST/IR binding drift")

    genealogy_ref, genealogy = _json_evidence(
        raw["genealogy"],
        _GENEALOGY_KEYS,
        "maintenance_genealogy",
        f"{label}.genealogy",
        artifact_root,
    )
    for field in ("task_id", "split", "family", "construct"):
        if genealogy[field] != context[field]:
            raise AccuracyMaintenanceError(f"{label}.genealogy.{field} binding drift")
    parent_roots = _hash_list(
        genealogy["parent_roots"], f"{label}.genealogy.parent_roots", allow_empty=True
    )
    template_roots = _hash_list(
        genealogy["template_roots"], f"{label}.genealogy.template_roots", allow_empty=True
    )
    identifiers = _string_list(genealogy["identifiers"], f"{label}.genealogy.identifiers")
    ast_identities = _hash_list(
        genealogy["normalized_ast_identities"],
        f"{label}.genealogy.normalized_ast_identities",
        allow_empty=False,
    )
    ir_identities = _hash_list(
        genealogy["normalized_ir_identities"],
        f"{label}.genealogy.normalized_ir_identities",
        allow_empty=False,
    )
    if normalized_ast_sha256 not in ast_identities or normalized_ir_sha256 not in ir_identities:
        raise AccuracyMaintenanceError(f"{label}.genealogy does not contain the oracle AST/IR")
    if not parent_roots and not template_roots:
        raise AccuracyMaintenanceError(f"{label}.genealogy has no parent or template root")

    retrieval_ref: dict[str, str] | None = None
    retrieval_request_sha256: str | None = None
    retrieval_result_sha256: str | None = None
    retrieval_normalized: dict[str, str]
    retrieval_value = raw["retrieval_evidence"]
    if construct_entry["catalog_domain"]:
        if not isinstance(retrieval_value, Mapping) or retrieval_value.get("kind") != "receipt":
            raise AccuracyMaintenanceError(f"{label} catalog task lacks retrieval receipt")
        retrieval_raw = _exact_mapping(
            retrieval_value, _RETRIEVAL_RECEIPT_KEYS, f"{label}.retrieval_evidence"
        )
        retrieval_ref, retrieval = _json_evidence(
            {"path": retrieval_raw["path"], "sha256": retrieval_raw["sha256"]},
            _RETRIEVAL_KEYS,
            "maintenance_retrieval_receipt",
            f"{label}.retrieval_evidence",
            artifact_root,
        )
        _task_context(retrieval, context, f"{label}.retrieval_evidence")
        if retrieval["prompt_sha256"] != prompt_ref["sha256"]:
            raise AccuracyMaintenanceError(f"{label}.retrieval prompt binding drift")
        if retrieval["authority"] != "toolchain_per_field_retrieval":
            raise AccuracyMaintenanceError(f"{label}.retrieval authority drift")
        if retrieval["status"] != "pass":
            raise AccuracyMaintenanceError(f"{label}.retrieval status is not pass")
        if retrieval["tenant_values_materialized_in_prompt"] is not False:
            raise AccuracyMaintenanceError(f"{label}.retrieval leaked tenant values into prompt")
        request = _json_value(retrieval["request"], f"{label}.retrieval.request")
        result = _json_value(retrieval["result"], f"{label}.retrieval.result")
        retrieval_request_sha256 = _hash(
            retrieval["request_sha256"], f"{label}.retrieval.request_sha256"
        )
        retrieval_result_sha256 = _hash(
            retrieval["result_sha256"], f"{label}.retrieval.result_sha256"
        )
        if retrieval_request_sha256 != _sha256_json(
            request
        ) or retrieval_result_sha256 != _sha256_json(result):
            raise AccuracyMaintenanceError(f"{label}.retrieval request/result hash drift")
        retrieval_normalized = {"kind": "receipt", **retrieval_ref}
    else:
        non_catalog = _exact_mapping(
            retrieval_value, _NON_CATALOG_KEYS, f"{label}.retrieval_evidence"
        )
        if non_catalog != {"kind": "non_catalog", "marker": "non_catalog"}:
            raise AccuracyMaintenanceError(f"{label} has an invalid non-catalog marker")
        retrieval_normalized = {"kind": "non_catalog", "marker": "non_catalog"}

    identifier_root = _sha256_json(identifiers)
    ast_root = _sha256_json(ast_identities)
    ir_root = _sha256_json(ir_identities)
    genealogy_root = genealogy_ref["sha256"]
    content_root = _sha256_json(
        {
            "prompt": prompt_ref["sha256"],
            "truth": truth_ref["sha256"],
            "oracle_receipt": oracle_ref["sha256"],
            "retrieval_evidence": (
                retrieval_ref["sha256"] if retrieval_ref is not None else "non_catalog"
            ),
            "genealogy": genealogy_root,
        }
    )
    provenance_root = _sha256_json(
        {
            **context,
            "parent_roots": parent_roots,
            "template_roots": template_roots,
            "content_root_sha256": content_root,
            "genealogy_root_sha256": genealogy_root,
            "identifier_root_sha256": identifier_root,
            "normalized_ast_root_sha256": ast_root,
            "normalized_ir_root_sha256": ir_root,
            "expected_output_root_sha256": expected_output_sha256,
        }
    )
    derived = {
        "provenance_root_sha256": provenance_root,
        "content_root_sha256": content_root,
        "genealogy_root_sha256": genealogy_root,
        "identifier_root_sha256": identifier_root,
        "normalized_ast_root_sha256": ast_root,
        "normalized_ir_root_sha256": ir_root,
        "expected_output_root_sha256": expected_output_sha256,
    }
    for field, expected in derived.items():
        if _hash(raw[field], f"{label}.{field}") != expected:
            raise AccuracyMaintenanceError(f"{label}.{field} is not derived from its evidence")

    normalized = {
        **context,
        "prompt": prompt_ref,
        "truth": truth_ref,
        "oracle_receipt": oracle_ref,
        "retrieval_evidence": retrieval_normalized,
        "genealogy": genealogy_ref,
        **derived,
        "pre_output_status": "local_preoutput_evidence",
    }
    binding = MaintenanceTaskBinding(
        task_id=task_id,
        split=split,
        family=family,
        construct=construct,
        catalog_domain=construct_entry["catalog_domain"],
        prompt_sha256=prompt_ref["sha256"],
        truth_sha256=truth_ref["sha256"],
        oracle_receipt_sha256=oracle_ref["sha256"],
        retrieval_receipt_sha256=(retrieval_ref["sha256"] if retrieval_ref is not None else None),
        genealogy_receipt_sha256=genealogy_ref["sha256"],
        prompt_payload_sha256=prompt_payload_sha256,
        retrieval_request_sha256=retrieval_request_sha256,
        retrieval_result_sha256=retrieval_result_sha256,
        parent_roots=tuple(parent_roots),
        template_roots=tuple(template_roots),
        identifiers=tuple(identifiers),
        normalized_ast_identities=tuple(ast_identities),
        normalized_ir_identities=tuple(ir_identities),
        **derived,
        upstream_revision=pin["revision"],
        upstream_tree=pin["tree"],
    )
    return normalized, binding


def _counts(value: Any) -> dict[str, Any]:
    raw = _exact_mapping(value, _COUNTS_KEYS, "counts")
    normalized: dict[str, Any] = {}
    for split in SPLITS:
        split_raw = _exact_mapping(raw[split], _SPLIT_COUNTS_KEYS, f"counts.{split}")
        families = _exact_mapping(
            split_raw["families"], frozenset(FAMILIES), f"counts.{split}.families"
        )
        normalized[split] = {
            "tasks": _integer(split_raw["tasks"], f"counts.{split}.tasks"),
            "families": {
                family: _integer(families[family], f"counts.{split}.families.{family}")
                for family in FAMILIES
            },
        }
    normalized["total"] = _integer(raw["total"], "counts.total")
    return normalized


def _recomputed_counts(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        **{
            split: {
                "tasks": sum(task["split"] == split for task in tasks),
                "families": {
                    family: sum(
                        task["split"] == split and task["family"] == family for task in tasks
                    )
                    for family in FAMILIES
                },
            }
            for split in SPLITS
        },
        "total": len(tasks),
    }


def canonical_roster_sha256(value: Mapping[str, Any]) -> str:
    """Hash every roster field except the identity field itself."""

    if not isinstance(value, Mapping):
        raise AccuracyMaintenanceError("roster must be an object")
    return _sha256_json(
        {key: copy.deepcopy(item) for key, item in value.items() if key != "roster_sha256"}
    )


def _fixed_schema(value: Mapping[str, Any]) -> None:
    if _FIXED_SCHEMA_PATH.is_symlink():
        raise AccuracyMaintenanceError("fixed maintenance schema must not be a symlink")
    try:
        schema = json.loads(_FIXED_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AccuracyMaintenanceError("fixed maintenance schema is unavailable") from error
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path)
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "roster"
        raise AccuracyMaintenanceError(f"fixed schema violation at {location}: {first.message}")


def _pending(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw["authority_status"] != "NO_AUTHORITY_PENDING":
        raise AccuracyMaintenanceError("pending roster authority status drift")
    if raw["model_outputs_observed"] is not False:
        raise AccuracyMaintenanceError("pending roster observed model output")
    if raw["upstream_pin"] is not None or raw["construct_registry"] is not None:
        raise AccuracyMaintenanceError("pending roster must not claim pin or construct authority")
    if raw["tasks"] != []:
        raise AccuracyMaintenanceError("pending roster must not claim materialized tasks")
    counts = _counts(raw["counts"])
    if counts != _recomputed_counts([]):
        raise AccuracyMaintenanceError("pending roster counts do not match zero tasks")
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "roster_id": _identifier(raw["roster_id"], "roster_id"),
        "status": "pending",
        "authority_status": "NO_AUTHORITY_PENDING",
        "model_outputs_observed": False,
        "upstream_pin": None,
        "construct_registry": None,
        "tasks": [],
        "counts": counts,
        "roster_sha256": _hash(raw["roster_sha256"], "roster_sha256"),
    }
    if normalized["roster_sha256"] != canonical_roster_sha256(normalized):
        raise AccuracyMaintenanceError("roster hash drift")
    return normalized


def _local_draft(raw: Mapping[str, Any], artifact_root: Path | str) -> LocalMaintenanceDraft:
    if raw["authority_status"] != "LOCAL_UNPUBLISHED_DRAFT":
        raise AccuracyMaintenanceError("local draft authority status drift")
    if raw["model_outputs_observed"] is not False:
        raise AccuracyMaintenanceError("local draft was not frozen before model output")
    if not isinstance(raw["tasks"], list):
        raise AccuracyMaintenanceError("tasks must be a list")
    root = _open_artifact_root(artifact_root)
    try:
        pin = _pin(raw["upstream_pin"], root)
        registry_value, registry = _registry(raw["construct_registry"])
        pairs = [
            _task(task, offset, root, pin, registry) for offset, task in enumerate(raw["tasks"])
        ]
    finally:
        os.close(root.file_descriptor)
    tasks = [pair[0] for pair in pairs]
    bindings = tuple(sorted((pair[1] for pair in pairs), key=lambda item: item.task_id))

    task_ids = [task["task_id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        duplicates = sorted(task_id for task_id, count in Counter(task_ids).items() if count > 1)
        raise AccuracyMaintenanceError(f"duplicate task_id: {', '.join(duplicates)}")
    evidence_paths = [
        reference["path"]
        for task in tasks
        for reference in (
            task["prompt"],
            task["truth"],
            task["oracle_receipt"],
            task["genealogy"],
            *(
                [task["retrieval_evidence"]]
                if task["retrieval_evidence"]["kind"] == "receipt"
                else []
            ),
        )
    ]
    if len(evidence_paths) != len(set(evidence_paths)):
        raise AccuracyMaintenanceError("evidence paths must be unique per task and role")

    d18 = [task for task in tasks if task["split"] == "D18"]
    t30 = [task for task in tasks if task["split"] == "T30"]
    for field in (
        "provenance_root_sha256",
        "content_root_sha256",
        "genealogy_root_sha256",
        "identifier_root_sha256",
        "normalized_ast_root_sha256",
        "normalized_ir_root_sha256",
        "expected_output_root_sha256",
    ):
        if {task[field] for task in d18} & {task[field] for task in t30}:
            raise AccuracyMaintenanceError(f"D18 and T30 {field} values must be disjoint")

    d18_bindings = [binding for binding in bindings if binding.split == "D18"]
    t30_bindings = [binding for binding in bindings if binding.split == "T30"]
    for field in (
        "prompt_payload_sha256",
        "retrieval_request_sha256",
    ):
        d18_values = {
            value for binding in d18_bindings if (value := getattr(binding, field)) is not None
        }
        t30_values = {
            value for binding in t30_bindings if (value := getattr(binding, field)) is not None
        }
        if d18_values & t30_values:
            raise AccuracyMaintenanceError(f"D18 and T30 {field} values must be disjoint")
    for field in (
        "parent_roots",
        "template_roots",
        "identifiers",
        "normalized_ast_identities",
        "normalized_ir_identities",
    ):
        d18_values = {value for binding in d18_bindings for value in getattr(binding, field)}
        t30_values = {value for binding in t30_bindings for value in getattr(binding, field)}
        if d18_values & t30_values:
            raise AccuracyMaintenanceError(f"D18 and T30 {field} values must be disjoint")

    for split in SPLITS:
        split_bindings = [binding for binding in bindings if binding.split == split]
        for field in ("prompt_payload_sha256", "expected_output_root_sha256"):
            values = [getattr(binding, field) for binding in split_bindings]
            if len(values) != len(set(values)):
                raise AccuracyMaintenanceError(
                    f"{split} {field} identities must be unique across tasks"
                )
        for field in (
            "parent_roots",
            "template_roots",
            "identifiers",
            "normalized_ast_identities",
            "normalized_ir_identities",
        ):
            owners: dict[str, str] = {}
            for binding in split_bindings:
                for identity in getattr(binding, field):
                    previous_task = owners.setdefault(identity, binding.task_id)
                    if previous_task != binding.task_id:
                        raise AccuracyMaintenanceError(
                            f"{split} {field} identities must be unique across tasks"
                        )

    counts = _counts(raw["counts"])
    actual_counts = _recomputed_counts(tasks)
    expected_counts = {
        **{
            split: {
                "tasks": EXPECTED_SPLIT_COUNTS[split],
                "families": EXPECTED_FAMILY_COUNTS[split],
            }
            for split in SPLITS
        },
        "total": sum(EXPECTED_SPLIT_COUNTS.values()),
    }
    if counts != actual_counts:
        raise AccuracyMaintenanceError("declared counts do not match the task roster")
    if actual_counts != expected_counts:
        raise AccuracyMaintenanceError(
            "local draft must contain D18=18 and T30=30 with exact family coverage"
        )
    catalog_counts = Counter(
        (binding.split, binding.family) for binding in bindings if binding.catalog_domain
    )
    expected_catalog_counts = Counter(
        {(split, family): 1 for split in SPLITS for family in ("F-1", "F-6")}
    )
    if catalog_counts != expected_catalog_counts:
        raise AccuracyMaintenanceError(
            "catalog_value_domain must reserve exactly one F-1 and F-6 task in D18 and T30"
        )
    if {task["construct"] for task in tasks} != set(registry):
        raise AccuracyMaintenanceError("construct registry must exactly match used constructs")

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "roster_id": _identifier(raw["roster_id"], "roster_id"),
        "status": "local_unpublished_draft",
        "authority_status": "LOCAL_UNPUBLISHED_DRAFT",
        "model_outputs_observed": False,
        "upstream_pin": pin,
        "construct_registry": registry_value,
        "tasks": tasks,
        "counts": counts,
        "roster_sha256": _hash(raw["roster_sha256"], "roster_sha256"),
    }
    if normalized["roster_sha256"] != canonical_roster_sha256(normalized):
        raise AccuracyMaintenanceError("roster hash drift")
    return LocalMaintenanceDraft(
        _manifest_bytes=_canonical(normalized),
        artifact_root=root.path,
        artifact_root_identity=root.identity,
        task_bindings=bindings,
    )


def validate_maintenance_roster(
    value: Mapping[str, Any],
    artifact_root: Path | str | None = None,
) -> dict[str, Any] | LocalMaintenanceDraft:
    """Validate a pending manifest or issue a non-authoritative local draft."""

    raw = _exact_mapping(value, _ROSTER_KEYS, "roster")
    _fixed_schema(raw)
    if raw["schema_version"] != SCHEMA_VERSION or type(raw["schema_version"]) is not int:
        raise AccuracyMaintenanceError("schema_version must be integer 1")
    if raw["status"] == "pending":
        return _pending(raw)
    if raw["status"] != "local_unpublished_draft":
        raise AccuracyMaintenanceError("unsupported maintenance roster state")
    if artifact_root is None:
        raise AccuracyMaintenanceError("artifact_root is required for a local draft")
    return _local_draft(raw, artifact_root)


def _load_json(path: Path | str) -> Mapping[str, Any]:
    roster_path = Path(path)
    if roster_path.is_symlink():
        raise AccuracyMaintenanceError("roster path must not be a symlink")
    try:
        metadata = roster_path.stat(follow_symlinks=False)
    except OSError as error:
        raise AccuracyMaintenanceError("roster path does not exist") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise AccuracyMaintenanceError("roster path must be one regular, non-hard-linked file")

    def reject_constant(token: str) -> None:
        raise AccuracyMaintenanceError(f"roster contains non-JSON number {token}")

    try:
        value = json.loads(roster_path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except AccuracyMaintenanceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AccuracyMaintenanceError("roster is not readable JSON") from error
    if not isinstance(value, Mapping):
        raise AccuracyMaintenanceError("roster must contain an object")
    return value


def load_maintenance_roster(
    path: Path | str,
    artifact_root: Path | str | None = None,
) -> dict[str, Any] | LocalMaintenanceDraft:
    """Load one non-symlink roster and apply the fixed local-draft contract."""

    return validate_maintenance_roster(_load_json(path), artifact_root)


def verify_maintenance_roster(
    value: LocalMaintenanceDraft,
) -> NoReturn:
    """Fail closed until the pushed-Git-preimage verifier is implemented."""

    if type(value) is not LocalMaintenanceDraft:
        raise MaintenanceAuthorityUnavailableError(
            "verification requires a structurally validated LOCAL_UNPUBLISHED_DRAFT"
        )
    raise MaintenanceAuthorityUnavailableError(
        "pre-output pushed Git commit and remote-ref verifier is not wired"
    )


def build_t30_seal(value: LocalMaintenanceDraft) -> NoReturn:
    """Refuse to self-seal a local draft; Git publication authority is missing."""

    verify_maintenance_roster(value)


def require_verified_maintenance_roster(value: Any) -> NoReturn:
    """Decision-gate guard: no verified roster exists before Git wiring."""

    del value
    raise MaintenanceAuthorityUnavailableError(
        "VerifiedMaintenanceRoster is unavailable until the pushed-Git verifier is wired"
    )
