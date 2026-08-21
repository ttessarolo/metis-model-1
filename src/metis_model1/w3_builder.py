"""Registered W3 public-synthetic source and dataset builder.

The source register is a review boundary, not a caller assertion. Benchmark,
source-register, and Oracle identities are module authorities set only after
independent review. All payload construction remains offline and in memory.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from metis_model1.dataset import (
    build_split_manifest,
    load_schema,
    validate_dataset,
    validate_example,
)
from metis_model1.provenance import canonical_json_bytes, example_id
from metis_model1.w3_oracles import (
    OracleEvaluation,
    W3OracleError,
    adapter_identity_sha256,
    invoke_oracle,
    valid_hash,
)

REGISTERED_W3_BENCHMARK_MANIFEST_SHA256: str | None = None
REGISTERED_W3_SOURCE_REGISTER_SHA256: str | None = None
PINNED_METIS_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
LANGUAGE_VERSION = "0.43"
GENERATOR_VERSION = "w3-public-synthetic-v1"
SPLITS = frozenset({"train", "dev", "internal_test"})
FAMILIES = frozenset({"F-1", "F-2", "F-3"})
PERMITTED_LICENSES = frozenset({"Apache-2.0", "CC-BY-4.0", "CC0-1.0", "MIT"})
RIGHTS_POLICY = "public_synthetic_permitted"
RIGHTS_SCOPE = "local_training_and_evaluation"
CANDIDATE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class W3BuildError(ValueError):
    """Raised when any W3 trust, provenance, or materialization gate fails."""


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _canonical(value: Any, label: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise W3BuildError(f"{label} is not canonical JSON") from error


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise W3BuildError(f"{label} must be an object")
    copied = _canonical(dict(value), label)
    if not isinstance(copied, dict):
        raise W3BuildError(f"{label} must be an object")
    return copied


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise W3BuildError(
            f"{label} keys mismatch: missing={sorted(expected - actual)} "
            f"extras={sorted(actual - expected)}"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise W3BuildError(f"{label} must be non-empty text")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _hash_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not valid_hash(item) for item in value):
        raise W3BuildError(f"{label} must be a list of sha256 identities")
    if len(value) != len(set(value)):
        raise W3BuildError(f"{label} must not contain duplicates")
    return list(value)


def _items(value: Any, label: str) -> list[Any]:
    if value is None or isinstance(value, (str | bytes | bytearray | Mapping)):
        raise W3BuildError(f"{label} must be an iterable of objects")
    try:
        return list(value)
    except TypeError as error:
        raise W3BuildError(f"{label} must be an iterable of objects") from error


def _benchmark_authority(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], set[str]]:
    candidate = _mapping(manifest, "benchmark manifest")
    _exact_keys(
        candidate,
        {"schema_version", "manifest_id", "sealed", "benchmark_roots", "manifest_hash"},
        "benchmark manifest",
    )
    if candidate["schema_version"] != 1 or candidate["sealed"] is not True:
        raise W3BuildError("benchmark manifest is not sealed")
    if not isinstance(candidate["manifest_id"], str) or not candidate["manifest_id"]:
        raise W3BuildError("benchmark manifest_id is missing")
    roots = _hash_list(candidate["benchmark_roots"], "benchmark_roots")
    if not roots:
        raise W3BuildError("benchmark_roots must not be empty")
    body = {key: value for key, value in candidate.items() if key != "manifest_hash"}
    actual = _hash(body)
    if candidate["manifest_hash"] != actual:
        raise W3BuildError("benchmark manifest hash does not match its body")
    if REGISTERED_W3_BENCHMARK_MANIFEST_SHA256 is None:
        raise W3BuildError("W3 benchmark authority is unset")
    if actual != REGISTERED_W3_BENCHMARK_MANIFEST_SHA256:
        raise W3BuildError("benchmark manifest does not match registered authority")
    return candidate, set(roots)


def _candidate_shape(raw: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _mapping(raw, "candidate")
    common = {
        "candidate_id",
        "family",
        "split",
        "semantic_spec",
        "root_evidence",
        "rights",
        "parents",
    }
    family = candidate.get("family")
    if not isinstance(family, str):
        raise W3BuildError("candidate family must be text")
    if family == "F-1":
        required = common | {"request", "target_source"}
    elif family == "F-2":
        variants = [
            common | {"before_source", "after_source", "expected_delta"},
            common | {"before_source", "after_source", "patch"},
        ]
        if set(candidate) not in variants:
            raise W3BuildError("F-2 requires before_source, after_source, and expected_delta/patch")
        required = set(candidate)
    elif family == "F-3":
        required = common | {
            "mutated_source",
            "expected_diagnostic",
            "fixed_source",
            "mutation_spec",
        }
    else:
        raise W3BuildError(f"unsupported W3 family: {family!r}")
    _exact_keys(candidate, required, f"{family} candidate")
    if (
        not isinstance(candidate["candidate_id"], str)
        or re.fullmatch(CANDIDATE_ID_PATTERN, candidate["candidate_id"]) is None
    ):
        raise W3BuildError("candidate_id is not a safe metadata identifier")
    if not isinstance(candidate["split"], str) or candidate["split"] not in SPLITS:
        raise W3BuildError("W3 split must be train, dev, or internal_test")
    if not isinstance(candidate["semantic_spec"], (dict | list)) or not candidate["semantic_spec"]:
        raise W3BuildError("semantic_spec must be non-empty JSON structure")
    parents = candidate["parents"]
    if not isinstance(parents, list) or any(
        not isinstance(parent, str) or not parent for parent in parents
    ):
        raise W3BuildError("parents must be a list of candidate IDs or sha256 roots")
    if len(parents) != len(set(parents)):
        raise W3BuildError("parents must not contain duplicates")
    if family == "F-1":
        candidate["request"] = _text(candidate["request"], "F-1 request")
        candidate["target_source"] = _text(candidate["target_source"], "F-1 target_source")
    elif family == "F-2":
        candidate["before_source"] = _text(candidate["before_source"], "F-2 before_source")
        candidate["after_source"] = _text(candidate["after_source"], "F-2 after_source")
        delta_key = "expected_delta" if "expected_delta" in candidate else "patch"
        if not isinstance(candidate[delta_key], (dict | list | str)) or not candidate[delta_key]:
            raise W3BuildError(f"F-2 {delta_key} must be non-empty")
        if candidate["before_source"] == candidate["after_source"]:
            raise W3BuildError("F-2 before_source and after_source must differ")
    else:
        candidate["mutated_source"] = _text(candidate["mutated_source"], "F-3 mutated_source")
        candidate["fixed_source"] = _text(candidate["fixed_source"], "F-3 fixed_source")
        if (
            not isinstance(candidate["expected_diagnostic"], (dict | list | str))
            or not candidate["expected_diagnostic"]
        ):
            raise W3BuildError("F-3 expected_diagnostic must be non-empty")
        if (
            not isinstance(candidate["mutation_spec"], (dict | list))
            or not candidate["mutation_spec"]
        ):
            raise W3BuildError("F-3 mutation_spec must be non-empty JSON structure")
        if candidate["mutated_source"] == candidate["fixed_source"]:
            raise W3BuildError("F-3 mutated_source and fixed_source must differ")
    return candidate


def _content_material(candidate: Mapping[str, Any]) -> dict[str, Any]:
    family = candidate["family"]
    if family == "F-1":
        return {"request": candidate["request"], "target_source": candidate["target_source"]}
    if family == "F-2":
        delta_key = "expected_delta" if "expected_delta" in candidate else "patch"
        return {
            "before_source": candidate["before_source"],
            "after_source": candidate["after_source"],
            delta_key: candidate[delta_key],
        }
    return {
        "mutated_source": candidate["mutated_source"],
        "expected_diagnostic": candidate["expected_diagnostic"],
        "fixed_source": candidate["fixed_source"],
        "mutation_spec": candidate["mutation_spec"],
    }


def _atomic_material(candidate: Mapping[str, Any]) -> list[Any]:
    family = candidate["family"]
    if family == "F-1":
        return [candidate["request"], candidate["target_source"]]
    if family == "F-2":
        delta_key = "expected_delta" if "expected_delta" in candidate else "patch"
        return [
            candidate["before_source"],
            candidate["after_source"],
            candidate[delta_key],
        ]
    return [
        candidate["mutated_source"],
        candidate["fixed_source"],
        candidate["expected_diagnostic"],
        candidate["mutation_spec"],
    ]


def _rights(candidate: Mapping[str, Any], content_sha256: str) -> dict[str, Any]:
    rights = _mapping(candidate["rights"], "rights")
    _exact_keys(rights, {"license_id", "policy", "scope", "attestation"}, "rights")
    if not isinstance(rights["license_id"], str) or rights["license_id"] not in (
        PERMITTED_LICENSES
    ):
        raise W3BuildError("rights license is not in the permitted public set")
    if (
        not isinstance(rights["policy"], str)
        or not isinstance(rights["scope"], str)
        or rights["policy"] != RIGHTS_POLICY
        or rights["scope"] != RIGHTS_SCOPE
    ):
        raise W3BuildError("rights policy/scope is not permitted")
    attestation = _mapping(rights["attestation"], "rights attestation")
    _exact_keys(
        attestation,
        {"content_sha256", "evidence", "evidence_sha256", "reviewer"},
        "rights attestation",
    )
    if attestation["content_sha256"] != content_sha256:
        raise W3BuildError("rights attestation is not bound to source content")
    evidence = attestation["evidence"]
    if not isinstance(evidence, dict) or not evidence:
        raise W3BuildError("rights evidence must be a non-empty object")
    if attestation["evidence_sha256"] != _hash(evidence):
        raise W3BuildError("rights evidence hash mismatch")
    _text(attestation["reviewer"], "rights reviewer")
    return rights


@dataclass(frozen=True)
class _Prepared:
    candidate: dict[str, Any]
    candidate_id: str
    family: str
    split: str
    content_sha256: str
    semantic_spec_sha256: str
    roots: tuple[str, ...]
    parents: tuple[str, ...]
    rights: dict[str, Any]


def _prepare(raw: Mapping[str, Any]) -> _Prepared:
    candidate = _candidate_shape(raw)
    content_sha256 = _hash(_content_material(candidate))
    semantic_sha256 = _hash(candidate["semantic_spec"])
    root_evidence = _mapping(candidate["root_evidence"], "root_evidence")
    _exact_keys(
        root_evidence,
        {
            "content_sha256",
            "semantic_spec_sha256",
            "template_root",
            "generator_root",
            "session_root",
            "ancestor_roots",
        },
        "root_evidence",
    )
    if root_evidence["content_sha256"] != content_sha256:
        raise W3BuildError("root_evidence content hash mismatch")
    if root_evidence["semantic_spec_sha256"] != semantic_sha256:
        raise W3BuildError("root_evidence semantic spec hash mismatch")
    fixed_roots = [
        root_evidence["template_root"],
        root_evidence["generator_root"],
        root_evidence["session_root"],
    ]
    if any(not valid_hash(root) for root in fixed_roots):
        raise W3BuildError("template/generator/session roots must be sha256 identities")
    ancestor_roots = _hash_list(root_evidence["ancestor_roots"], "ancestor_roots")
    external_parents = [parent for parent in candidate["parents"] if valid_hash(parent)]
    roots = sorted(
        {
            content_sha256,
            semantic_sha256,
            *(_hash(material) for material in _atomic_material(candidate)),
            *fixed_roots,
            *ancestor_roots,
            *external_parents,
        }
    )
    return _Prepared(
        candidate=candidate,
        candidate_id=candidate["candidate_id"],
        family=candidate["family"],
        split=candidate["split"],
        content_sha256=content_sha256,
        semantic_spec_sha256=semantic_sha256,
        roots=tuple(roots),
        parents=tuple(candidate["parents"]),
        rights=_rights(candidate, content_sha256),
    )


class _UnionFind:
    def __init__(self, values: Sequence[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _component_records(
    candidates: Sequence[_Prepared], benchmark_roots: set[str]
) -> list[dict[str, Any]]:
    ids = [candidate.candidate_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise W3BuildError("duplicate candidate_id")
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    uf = _UnionFind(ids)
    owner_by_root: dict[str, str] = {}
    for candidate in candidates:
        if set(candidate.roots) & benchmark_roots:
            raise W3BuildError(f"candidate {candidate.candidate_id} copies benchmark ancestry")
        for root in candidate.roots:
            previous = owner_by_root.setdefault(root, candidate.candidate_id)
            uf.union(candidate.candidate_id, previous)
        for parent in candidate.parents:
            if parent == candidate.candidate_id:
                raise W3BuildError("candidate cannot parent itself")
            if parent in by_id:
                uf.union(candidate.candidate_id, parent)
            elif not valid_hash(parent):
                raise W3BuildError(f"unknown local parent: {parent}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(candidate_id: str) -> None:
        if candidate_id in visiting:
            raise W3BuildError("candidate genealogy contains a cycle")
        if candidate_id in visited:
            return
        visiting.add(candidate_id)
        for parent in by_id[candidate_id].parents:
            if parent in by_id:
                visit(parent)
        visiting.remove(candidate_id)
        visited.add(candidate_id)

    for candidate_id in ids:
        visit(candidate_id)
    grouped: dict[str, list[_Prepared]] = defaultdict(list)
    for candidate in candidates:
        grouped[uf.find(candidate.candidate_id)].append(candidate)
    component_by_id: dict[str, tuple[list[str], str]] = {}
    for members in grouped.values():
        splits = {member.split for member in members}
        if len(splits) != 1:
            raise W3BuildError("shared ancestry component crosses split")
        roots = sorted({root for member in members for root in member.roots})
        leakage_group = _hash({"kind": "w3-ancestry-component-v1", "roots": roots})
        for member in members:
            component_by_id[member.candidate_id] = (roots, leakage_group)
    records = []
    for candidate in sorted(candidates, key=lambda item: item.candidate_id):
        roots, leakage_group = component_by_id[candidate.candidate_id]
        record = {
            "candidate_id": candidate.candidate_id,
            "family": candidate.family,
            "split": candidate.split,
            "candidate": candidate.candidate,
            "candidate_sha256": _hash(candidate.candidate),
            "content_sha256": candidate.content_sha256,
            "semantic_spec_sha256": candidate.semantic_spec_sha256,
            "roots": list(candidate.roots),
            "component_roots": roots,
            "leakage_group": leakage_group,
            "parents": list(candidate.parents),
            "rights": candidate.rights,
            "rights_sha256": _hash(candidate.rights),
        }
        records.append({**record, "source_record_sha256": _hash(record)})
    return records


def _construct_source_register(
    candidates: Iterable[Mapping[str, Any]], benchmark_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    benchmark, benchmark_roots = _benchmark_authority(benchmark_manifest)
    raw = _items(candidates, "candidates")
    if not raw:
        raise W3BuildError("at least one candidate is required")
    prepared = [_prepare(_mapping(candidate, "candidate")) for candidate in raw]
    records = _component_records(prepared, benchmark_roots)
    body = {
        "schema_version": 1,
        "register_id": "w3-public-synthetic-source-register-v1",
        "status": "proposed_for_independent_review",
        "claim": "no_accuracy_claim",
        "benchmark_manifest_sha256": benchmark["manifest_hash"],
        "sources": records,
        "counts": {
            "in": len(raw),
            "out": len(records),
            "distinct": len({record["candidate_id"] for record in records}),
            "gaps": len(raw) - len(records),
        },
    }
    return {**body, "manifest_sha256": _hash(body)}


def build_source_register(
    candidates: Iterable[Mapping[str, Any]], *, benchmark_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the proposed register that must then be ratified by exact hash."""

    return _construct_source_register(candidates, benchmark_manifest)


def validate_w3_source_register(
    register: Mapping[str, Any],
    *,
    candidates: Iterable[Mapping[str, Any]],
    benchmark_manifest: Mapping[str, Any],
) -> list[str]:
    """Rebuild and compare the entire register, including component grouping."""

    raw_candidates = _items(candidates, "candidates")
    actual = _mapping(register, "source register")
    schema = load_schema("w3-source-register.schema.json")
    errors = sorted(error.message for error in Draft202012Validator(schema).iter_errors(actual))
    if errors:
        return errors
    expected = _construct_source_register(raw_candidates, benchmark_manifest)
    if actual != expected:
        errors.append("source register differs from deterministic candidates/benchmark")
    return errors


def _oracle_candidate(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **source["candidate"],
        "content_sha256": source["content_sha256"],
        "semantic_spec_sha256": source["semantic_spec_sha256"],
        "component_roots": source["component_roots"],
        "leakage_group": source["leakage_group"],
    }


def _materialize(source: Mapping[str, Any], evaluation: OracleEvaluation) -> dict[str, Any]:
    candidate = source["candidate"]
    family = candidate["family"]
    if family == "F-1":
        input_value = {"request": candidate["request"]}
        assistant = candidate["target_source"]
        output = {"assistant_content": assistant, "source": assistant}
        user = candidate["request"]
    elif family == "F-2":
        delta_key = "expected_delta" if "expected_delta" in candidate else "patch"
        input_value = {
            "before_source": candidate["before_source"],
            delta_key: candidate[delta_key],
        }
        assistant = candidate["after_source"]
        output = {"assistant_content": assistant, "after_source": assistant}
        user = (
            "Apply the specified minimal Metis edit.\nW3_INPUT_JSON="
            + canonical_json_bytes(input_value).decode()
        )
    else:
        input_value = {
            "mutated_source": candidate["mutated_source"],
            "expected_diagnostic": candidate["expected_diagnostic"],
            "mutation_spec": candidate["mutation_spec"],
        }
        assistant = candidate["fixed_source"]
        output = {"assistant_content": assistant, "fixed_source": assistant}
        user = "Repair the Metis source for the expected diagnostic.\nW3_INPUT_JSON=" + (
            canonical_json_bytes(input_value).decode()
        )
    parent_by_id = {
        parent["candidate_id"]: parent["content_sha256"] for parent in source.get("all_sources", [])
    }
    parents = [parent_by_id.get(parent, parent) for parent in candidate["parents"]]
    if not parents:
        parents = [source["content_sha256"]]
    row = {
        "schema_version": 1,
        "example_id": example_id(1, input_value, output),
        "task_family": family,
        "input": input_value,
        "output": output,
        "messages": [
            {"role": "system", "content": "Metis Model 1 registered W3 example."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        "metis": {
            "source_revision": PINNED_METIS_REVISION,
            "language_version": LANGUAGE_VERSION,
            "paths": [f"public-synthetic/{source['candidate_id']}.metis"],
        },
        "provenance": {
            "parents": parents,
            "generator": "w3-public-synthetic",
            "generator_version": GENERATOR_VERSION,
            "leakage_group": source["leakage_group"],
        },
        "sensitivity": "public",
        "split": source["split"],
        "positive": True,
        "status": "accepted",
        "oracles": evaluation.dataset_oracles(),
    }
    errors = validate_example(row)
    if errors:
        raise W3BuildError("accepted row violates dataset contract: " + "; ".join(errors))
    return row


@dataclass(frozen=True)
class W3BuildResult:
    examples: tuple[dict[str, Any], ...]
    source_register: dict[str, Any]
    run_manifest: dict[str, Any]
    rejected: tuple[dict[str, str], ...]

    def __iter__(self):
        yield list(self.examples)
        yield self.run_manifest


def _execute_register(
    register: Mapping[str, Any], benchmark_manifest: Mapping[str, Any]
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any], tuple[dict[str, str], ...]]:
    _, benchmark_roots = _benchmark_authority(benchmark_manifest)
    sources = register["sources"]
    accepted_work: list[tuple[dict[str, Any], dict[str, Any], OracleEvaluation]] = []
    rejected: list[dict[str, str]] = []
    for source in sources:
        oracle_candidate = _oracle_candidate(source)
        try:
            evaluation = invoke_oracle(oracle_candidate)
        except W3OracleError as error:
            rejected.append({"candidate_id": source["candidate_id"], "reason": str(error)})
            continue
        if {evaluation.ast_sha256, evaluation.ir_sha256} & benchmark_roots:
            # Structural benchmark contamination is a run-level trust failure,
            # not a candidate-quality rejection that may be silently omitted.
            raise W3BuildError("Oracle AST/IR signature matches frozen benchmark ancestry")
        try:
            materialization_source = {**source, "all_sources": sources}
            row = _materialize(materialization_source, evaluation)
            accepted_work.append((source, row, evaluation))
        except W3BuildError as error:
            rejected.append({"candidate_id": source["candidate_id"], "reason": str(error)})
    if not accepted_work:
        raise W3BuildError("W3 produced no accepted examples")

    # Text/AST/IR duplicates in different splits are contamination. Within one
    # split, keep the canonical first row and record every later duplicate.
    kept: list[tuple[dict[str, Any], dict[str, Any], OracleEvaluation]] = []
    seen: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    for source, row, evaluation in sorted(accepted_work, key=lambda item: item[0]["candidate_id"]):
        identities = {
            "text": _hash({"input": row["input"], "output": row["output"]}),
            "ast": evaluation.ast_sha256,
            "ir": evaluation.ir_sha256,
        }
        duplicate_reason: str | None = None
        for kind, identity in identities.items():
            prior = seen[kind].get(identity)
            if prior is not None:
                prior_id, prior_split = prior
                if prior_split != source["split"]:
                    raise W3BuildError(
                        f"{kind} duplicate crosses split: {prior_id}/{source['candidate_id']}"
                    )
                duplicate_reason = f"duplicate {kind} identity of {prior_id}"
                break
        if duplicate_reason is not None:
            rejected.append({"candidate_id": source["candidate_id"], "reason": duplicate_reason})
            continue
        for kind, identity in identities.items():
            seen[kind][identity] = (source["candidate_id"], source["split"])
        kept.append((source, row, evaluation))
    if not kept:
        raise W3BuildError("W3 deduplication removed every accepted example")
    examples = tuple(sorted((item[1] for item in kept), key=lambda row: row["example_id"]))
    dataset_errors = validate_dataset(examples)
    if dataset_errors:
        raise W3BuildError("W3 dataset validation failed: " + "; ".join(dataset_errors))
    records = []
    for source, row, evaluation in sorted(kept, key=lambda item: item[0]["candidate_id"]):
        oracle_candidate = _oracle_candidate(source)
        record = {
            "candidate_id": source["candidate_id"],
            "candidate": oracle_candidate,
            "candidate_sha256": _hash(oracle_candidate),
            "source_record_sha256": source["source_record_sha256"],
            "dataset_example": row,
            "text_sha256": _hash({"input": row["input"], "output": row["output"]}),
            "ast_sha256": evaluation.ast_sha256,
            "ir_sha256": evaluation.ir_sha256,
            "component_roots": source["component_roots"],
            "leakage_group": source["leakage_group"],
            "oracle_evidence": evaluation.envelope,
            "oracle_result_sha256": evaluation.oracle_result_sha256,
            "semantic_result_sha256": evaluation.semantic_result_sha256,
        }
        records.append(record)
    rejected = sorted(rejected, key=lambda item: item["candidate_id"])
    accepted_ids = {record["candidate_id"] for record in records}
    rejected_ids = {record["candidate_id"] for record in rejected}
    if len(rejected_ids) != len(rejected) or accepted_ids & rejected_ids:
        raise W3BuildError("accepted/rejected candidate rosters are not unique and disjoint")
    split_manifest_id = build_split_manifest(examples)["split_manifest_id"]
    body = {
        "schema_version": 1,
        "run_id": "w3-public-synthetic-run-v1",
        "claim": "no_accuracy_claim",
        "generator_version": GENERATOR_VERSION,
        "benchmark_manifest_sha256": register["benchmark_manifest_sha256"],
        "source_register_sha256": register["manifest_sha256"],
        "split_manifest_id": split_manifest_id,
        "accepted_records": records,
        "rejected": rejected,
        "counts": {
            "in": len(sources),
            "out": len(records),
            "distinct": len(accepted_ids),
            "rejected": len(rejected),
            "gaps": len(rejected),
        },
    }
    run = {**body, "manifest_sha256": _hash(body)}
    return examples, run, tuple(rejected)


def build_w3_dataset(
    candidates: Iterable[Mapping[str, Any]],
    *,
    benchmark_manifest: Mapping[str, Any],
) -> W3BuildResult:
    """Build W3 rows only through the three registered module authorities."""

    raw = _items(candidates, "candidates")
    register = _construct_source_register(raw, benchmark_manifest)
    if REGISTERED_W3_SOURCE_REGISTER_SHA256 is None:
        raise W3BuildError("W3 source-register authority is unset")
    if register["manifest_sha256"] != REGISTERED_W3_SOURCE_REGISTER_SHA256:
        raise W3BuildError("source register does not match registered authority")
    try:
        adapter_identity_sha256()
    except W3OracleError as error:
        raise W3BuildError(str(error)) from error
    examples, run, rejected = _execute_register(register, benchmark_manifest)
    run_errors = validate_w3_run(
        run,
        source_register=register,
        benchmark_manifest=benchmark_manifest,
    )
    if run_errors:
        raise W3BuildError("W3 run validation failed: " + "; ".join(run_errors))
    return W3BuildResult(examples, register, run, rejected)


def validate_w3_run(
    run_manifest: Mapping[str, Any],
    *,
    source_register: Mapping[str, Any],
    benchmark_manifest: Mapping[str, Any],
) -> list[str]:
    """Rebuild the register and complete run; compare no caller-derived sidecars."""

    run = _mapping(run_manifest, "run manifest")
    register = _mapping(source_register, "source register")
    benchmark, _ = _benchmark_authority(benchmark_manifest)
    run_schema = load_schema("w3-run.schema.json")
    source_schema = load_schema("w3-source-register.schema.json")
    errors = sorted(error.message for error in Draft202012Validator(run_schema).iter_errors(run))
    errors.extend(
        sorted(
            "source register: " + error.message
            for error in Draft202012Validator(source_schema).iter_errors(register)
        )
    )
    if errors:
        return errors
    register_body = {key: value for key, value in register.items() if key != "manifest_sha256"}
    if register.get("manifest_sha256") != _hash(register_body):
        errors.append("actual source register has a non-canonical hash")
    if (
        REGISTERED_W3_SOURCE_REGISTER_SHA256 is None
        or register.get("manifest_sha256") != REGISTERED_W3_SOURCE_REGISTER_SHA256
    ):
        errors.append("actual source register does not match registered authority")
    if register.get("benchmark_manifest_sha256") != benchmark["manifest_hash"]:
        errors.append("actual source register is not benchmark-bound")
    try:
        embedded_candidates = [source["candidate"] for source in register["sources"]]
        expected_register = _construct_source_register(embedded_candidates, benchmark_manifest)
    except W3BuildError as error:
        errors.append(f"source register rebuild failed: {error}")
        return errors
    if register != expected_register:
        errors.append("source register differs from deterministic embedded candidates")
        return errors
    try:
        adapter_identity_sha256()
        expected_examples, expected_run, _ = _execute_register(register, benchmark_manifest)
    except (W3BuildError, W3OracleError) as error:
        errors.append(f"deterministic run replay failed: {error}")
        return errors
    dataset_errors = validate_dataset(expected_examples)
    errors.extend(f"dataset: {error}" for error in dataset_errors)
    if run != expected_run:
        errors.append("run differs from deterministic register/benchmark/Oracle replay")
    return errors


__all__ = [
    "GENERATOR_VERSION",
    "PINNED_METIS_REVISION",
    "REGISTERED_W3_BENCHMARK_MANIFEST_SHA256",
    "REGISTERED_W3_SOURCE_REGISTER_SHA256",
    "W3BuildError",
    "W3BuildResult",
    "build_source_register",
    "build_w3_dataset",
    "validate_w3_run",
    "validate_w3_source_register",
]
