"""Deterministic identities for offline Model 1 dataset assets.

The functions in this module deliberately accept only JSON values (or bytes for
source content).  This keeps identities reproducible across Python versions and
prevents a surprising ``repr`` or a NaN from becoming part of a manifest.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


class NonJsonValueError(TypeError):
    """Raised when a value cannot be represented by the canonical JSON codec."""


def _normalise(value: Any, path: str = "$") -> Any:
    """Return a JSON value with stable text normalisation.

    ``json.dumps`` accepts tuples and emits NaN by default, both of which are
    undesirable for an immutable identity.  We therefore validate recursively
    before serialising and reject all non-JSON Python containers and numbers.
    """

    if value is None or isinstance(value, (bool | int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NonJsonValueError(f"non-finite number at {path}")
        return value
    if isinstance(value, str):
        # JSON permits any Unicode string, but equivalent composed/decomposed
        # spellings must have the same identity.
        return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise NonJsonValueError(f"object key at {path} is not a string")
            normalised_key = unicodedata.normalize("NFC", key)
            if normalised_key in result:
                raise NonJsonValueError(f"duplicate normalised object key at {path}: {key}")
            result[normalised_key] = _normalise(item, f"{path}.{key}")
        return result
    if isinstance(value, list):
        return [_normalise(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise NonJsonValueError(f"non-JSON value at {path}: {type(value).__name__}")


def normalize_json(value: Any) -> Any:
    """Validate and normalise a JSON-compatible value without serialising it."""

    return _normalise(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Encode *value* using the repository's one canonical JSON representation."""

    normalised = _normalise(value)
    try:
        rendered = json.dumps(
            normalised,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:  # defensive: _normalise is the first gate
        raise NonJsonValueError(str(error)) from error
    return rendered.encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    """Return an unprefixed SHA-256 digest of canonical JSON."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _identity_digest(value: Any) -> str:
    return f"sha256:{canonical_json_hash(value)}"


def _content_hash(content: bytes | bytearray | memoryview | str) -> str:
    if isinstance(content, bytes | bytearray | memoryview):
        return hashlib.sha256(bytes(content)).hexdigest()
    if isinstance(content, str):
        candidate = content[7:] if content.startswith("sha256:") else ""
        if len(candidate) == 64:
            try:
                int(candidate, 16)
            except ValueError:
                pass
            else:
                return candidate.lower()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    raise TypeError("content must be bytes or a UTF-8 string/content SHA-256")


def source_asset_id(
    repository: str,
    revision: str,
    path: str,
    content: bytes | bytearray | memoryview | str,
) -> str:
    """Identify source bytes at an immutable repository revision.

    The content component may be the bytes themselves or a precomputed
    SHA-256 with an explicit ``sha256:`` prefix.  A structured envelope
    avoids delimiter and concatenation ambiguities while preserving the
    repository/commit/path/content contract.
    """

    if not all(isinstance(item, str) and item for item in (repository, revision, path)):
        raise ValueError("repository, revision and path must be nonempty strings")
    return _identity_digest(
        {
            "kind": "source_asset",
            "repository": repository,
            "revision": revision,
            "path": path.replace("\\", "/"),
            "content_sha256": _content_hash(content),
        }
    )


def derived_asset_id(
    generator: str,
    generator_version: str,
    parameters: Mapping[str, Any] | None,
    parents: Sequence[str],
) -> str:
    """Identify a deterministic derivation and its ordered parent assets."""

    if not isinstance(generator, str) or not generator:
        raise ValueError("generator must be a nonempty string")
    if not isinstance(generator_version, str) or not generator_version:
        raise ValueError("generator_version must be a nonempty string")
    if not isinstance(parents, Sequence) or isinstance(parents, str | bytes | bytearray):
        raise TypeError("parents must be a sequence of asset IDs")
    parent_list = list(parents)
    if not parent_list or any(not isinstance(parent, str) or not parent for parent in parent_list):
        raise ValueError("parents must contain at least one nonempty asset ID")
    return _identity_digest(
        {
            "kind": "derived_asset",
            "generator": generator,
            "generator_version": generator_version,
            "parameters": {} if parameters is None else parameters,
            "parents": parent_list,
        }
    )


def example_id(schema_version: int, normalized_input: Any, normalized_output: Any) -> str:
    """Identify an example from its schema version and normalised I/O only."""

    if type(schema_version) is not int or schema_version <= 0:
        raise ValueError("schema_version must be a positive integer")
    return _identity_digest(
        {
            "kind": "dataset_example",
            "schema_version": schema_version,
            "input": _normalise(normalized_input),
            "output": _normalise(normalized_output),
        }
    )


# Short aliases are useful to callers writing manifest code and keep the
# identity vocabulary explicit at call sites.
canonical_hash = canonical_json_hash
make_source_asset_id = source_asset_id
make_derived_asset_id = derived_asset_id
make_example_id = example_id
