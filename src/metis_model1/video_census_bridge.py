"""Offline-first, fail-closed contract for the ``@video`` catalog census.

The bridge in this module is intentionally a small policy boundary, not an
OpenSearch client.  It accepts an injected transport and constructs every
request itself from a pinned profile.  No credentials, environment variables,
argv, live tenant, or model are accessed here.  A real VSIX adapter may later
provide a transport, but this module remains the request and receipt contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantics_contracts import validate_census_receipt, validate_profile


class CensusBridgeError(RuntimeError):
    """A deterministic, non-sensitive bridge failure."""


class CensusTransport(Protocol):
    """The only dependency the bridge uses for HTTP-like operations."""

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


CAPABILITIES = frozenset(
    {
        "metadata-only",
        "aggregate-counts",
        "enumerate-finite-values",
        "open-no-values",
        "deny",
    }
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FIELD_RE = re.compile(r"^(?!/)[A-Za-z0-9._@+/-]{1,512}$")
_PIT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,512}$")
_SAFE_LITERAL_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")
_SECRET_RE = re.compile(
    r"(?i)(authorization|password|secret|token|api[_-]?key|private[_-]?key|"
    r"begin [a-z ]*private key|bearer)"
)
_FORBIDDEN_ENV_KEY_RE = re.compile(
    r"(?i)(secret|token|password|credential|authorization|api[_-]?key|private[_-]?key)"
)
_FORBIDDEN_ARG_RE = re.compile(
    r"(?i)(password|secret|token|credential|authorization|api[_-]?key|private[_-]?key)"
)
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def _bounded_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None or ".." in value:
        raise CensusBridgeError(f"invalid {label}")
    return value


def _bounded_field(value: str) -> str:
    if not isinstance(value, str) or _FIELD_RE.fullmatch(value) is None:
        raise CensusBridgeError("invalid field locator")
    if ".." in value or value.startswith(".") or value.endswith("."):
        raise CensusBridgeError("invalid field locator")
    return value


def _bounded_positive(value: int, label: str, maximum: int = 100_000) -> int:
    if type(value) is not int or value < 1 or value > maximum:
        raise CensusBridgeError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class FieldSpec:
    """One explicitly approved field capability."""

    field_path: str
    capability: str
    mapping_type: str = "keyword"
    nested_path: str | None = None
    cardinality_cap: int = 10_000
    max_pages: int = 100
    page_size: int = 1_000
    max_literal_bytes: int = 4_096
    multi_valued: str = "unknown"

    def __post_init__(self) -> None:
        _bounded_field(self.field_path)
        if self.capability not in CAPABILITIES:
            raise CensusBridgeError("invalid field capability")
        if (
            not isinstance(self.mapping_type, str)
            or not self.mapping_type
            or len(self.mapping_type) > 64
        ):
            raise CensusBridgeError("invalid mapping type")
        if self.nested_path is not None:
            raise CensusBridgeError("nested fields are not supported by P4A")
        if type(self.cardinality_cap) is not int or not 0 <= self.cardinality_cap <= 1_000_000:
            raise CensusBridgeError("invalid cardinality cap")
        _bounded_positive(self.max_pages, "page cap")
        _bounded_positive(self.page_size, "page size", 10_000)
        if type(self.max_literal_bytes) is not int or not 0 <= self.max_literal_bytes <= 1_048_576:
            raise CensusBridgeError("invalid literal byte cap")
        if self.multi_valued not in {"observed", "declared", "unknown"}:
            raise CensusBridgeError("invalid multi-valued state")


@dataclass(frozen=True)
class CensusProfile:
    """Pinned, bounded request profile used by :class:`CensusBridge`."""

    tenant_id: str
    catalog_ref: str
    alias: str
    index_ref: str
    fields: tuple[FieldSpec, ...]
    profile_revision: str
    profile_id: str = "video-semantics-census-v1"
    pit_keep_alive: str = "2m"

    def __post_init__(self) -> None:
        _bounded_identifier(self.tenant_id, "tenant")
        _bounded_identifier(self.catalog_ref, "catalog")
        _bounded_identifier(self.alias, "alias")
        _bounded_identifier(self.index_ref, "index")
        if self.profile_id != "video-semantics-census-v1":
            raise CensusBridgeError("unsupported census profile")
        if not _is_hash(self.profile_revision) or self.profile_revision == "sha256:" + "0" * 64:
            raise CensusBridgeError("invalid profile revision")
        if not isinstance(self.fields, Sequence) or isinstance(self.fields, str) or not self.fields:
            raise CensusBridgeError("profile must contain fields")
        if not isinstance(self.fields, tuple):
            object.__setattr__(self, "fields", tuple(self.fields))
        if any(not isinstance(item, FieldSpec) for item in self.fields):
            raise CensusBridgeError("profile fields are invalid")
        locators = [item.field_path for item in self.fields]
        if len(set(locators)) != len(locators):
            raise CensusBridgeError("profile contains duplicate fields")
        match = re.fullmatch(r"([1-9][0-9]{0,2})([smh])", self.pit_keep_alive)
        if match is None:
            raise CensusBridgeError("invalid PIT keep-alive")
        amount = int(match.group(1))
        limit = {"s": 300, "m": 60, "h": 1}[match.group(2)]
        if amount > limit:
            raise CensusBridgeError("PIT keep-alive exceeds profile bound")
        if self.profile_revision != profile_revision_for(
            tenant_id=self.tenant_id,
            catalog_ref=self.catalog_ref,
            alias=self.alias,
            index_ref=self.index_ref,
            fields=self.fields,
            profile_id=self.profile_id,
            pit_keep_alive=self.pit_keep_alive,
        ):
            raise CensusBridgeError("profile revision does not match pinned profile")

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> CensusProfile:
        """Load one versioned profile contract and verify its digest before use."""

        if not isinstance(contract, Mapping):
            raise CensusBridgeError("profile contract is invalid")
        errors = validate_profile(contract)
        if errors:
            raise CensusBridgeError("profile contract is invalid")
        try:
            fields = tuple(FieldSpec(**dict(item)) for item in contract["fields"])
            return cls(
                tenant_id=contract["tenant_ref"],
                catalog_ref=contract["catalog_ref"],
                alias=contract["alias_ref"],
                index_ref=contract["index_ref"],
                fields=fields,
                profile_id=contract["profile_id"],
                profile_revision=contract["profile_revision"],
                pit_keep_alive=contract["pit_keep_alive"],
            )
        except (KeyError, TypeError, CensusBridgeError):
            raise CensusBridgeError("profile contract is invalid") from None

    def to_contract(self) -> dict[str, Any]:
        """Return the exact allowlisted profile contract representation."""

        fields = [_field_contract(item) for item in self.fields]
        return {
            "schema_version": 1,
            "profile_id": self.profile_id,
            "profile_revision": self.profile_revision,
            "tenant_ref": self.tenant_id,
            "catalog_ref": self.catalog_ref,
            "alias_ref": self.alias,
            "index_ref": self.index_ref,
            "pit_keep_alive": self.pit_keep_alive,
            "operations": [
                "resolve_index",
                "mapping",
                "field_caps",
                "pit_open",
                "search_aggregate",
                "pit_close",
            ],
            "fields": fields,
        }


def _field_contract(spec: FieldSpec) -> dict[str, Any]:
    return {
        "field_path": spec.field_path,
        "mapping_type": spec.mapping_type,
        "nested_path": spec.nested_path,
        "capability": spec.capability,
        "multi_valued": spec.multi_valued,
        "cardinality_cap": spec.cardinality_cap,
        "max_pages": spec.max_pages,
        "page_size": spec.page_size,
        "max_literal_bytes": spec.max_literal_bytes,
    }


def profile_revision_for(
    *,
    tenant_id: str,
    catalog_ref: str,
    alias: str,
    index_ref: str,
    fields: Sequence[FieldSpec],
    profile_id: str = "video-semantics-census-v1",
    pit_keep_alive: str = "2m",
) -> str:
    """Compute the pinned revision from the complete versioned profile material."""

    material = {
        "schema_version": 1,
        "profile_id": profile_id,
        "tenant_ref": tenant_id,
        "catalog_ref": catalog_ref,
        "alias_ref": alias,
        "index_ref": index_ref,
        "pit_keep_alive": pit_keep_alive,
        "operations": [
            "resolve_index",
            "mapping",
            "field_caps",
            "pit_open",
            "search_aggregate",
            "pit_close",
        ],
        "fields": [_field_contract(item) for item in fields],
    }
    return "sha256:" + canonical_json_hash(material)


@dataclass
class BridgeStats:
    """Counters suitable for a local test receipt."""

    transport_calls: int = 0
    deny_before_network: int = 0
    leak_findings: int = 0


@dataclass
class CensusResult:
    """Sanitized result and receipt; raw transport responses never escape."""

    status: str
    fields: list[dict[str, Any]]
    receipt: dict[str, Any]
    stats: BridgeStats


def _canonical_hash(value: Any) -> str:
    return "sha256:" + canonical_json_hash(value)


def validate_offline_contract_receipt(receipt: Mapping[str, Any]) -> None:
    """Compatibility wrapper around the canonical receipt contract validator."""

    if not isinstance(receipt, Mapping):
        raise CensusBridgeError("offline receipt schema is invalid")
    errors = validate_census_receipt(receipt)
    if errors:
        raise CensusBridgeError("offline receipt schema is invalid")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CensusBridgeError(f"{label} response is invalid")
    return value


def _bounded_response(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Reject oversized/non-JSON-ish responses before inspecting them."""

    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CensusBridgeError("transport response is invalid") from error
    if len(raw) > 2 * 1024 * 1024:
        raise CensusBridgeError("transport response exceeds limit")
    _reject_response_material(raw.decode("utf-8"), value)
    return value


def build_child_environment(
    supplied: Mapping[str, str] | None = None,
    *,
    allowed_keys: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Build an empty-by-default child environment without reading process env.

    The P4A contract does not authorize credentials in this helper.  A caller
    may explicitly allow non-secret operational keys such as a pinned socket,
    but unknown or secret-looking keys/values fail closed.
    """

    if supplied is None:
        return {}
    if not isinstance(supplied, Mapping) or not isinstance(allowed_keys, frozenset):
        raise CensusBridgeError("child environment allowlist is invalid")
    result: dict[str, str] = {}
    for key, value in supplied.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or key not in allowed_keys
            or _FORBIDDEN_ENV_KEY_RE.search(key)
            or _SECRET_RE.search(value)
        ):
            raise CensusBridgeError("child environment is not allowlisted")
        result[key] = value
    return result


def validate_child_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Validate argv without consulting or exposing the process argv."""

    if not isinstance(argv, Sequence) or isinstance(argv, str | bytes):
        raise CensusBridgeError("child argv is invalid")
    result = tuple(argv)
    if not result or any(
        not isinstance(item, str) or _FORBIDDEN_ARG_RE.search(item) for item in result
    ):
        raise CensusBridgeError("child argv is not sanitized")
    return result


def sanitize_child_diagnostic(data: str) -> str:
    """Permit only non-sensitive child diagnostics; never redact-and-forward."""

    if (
        not isinstance(data, str)
        or _SECRET_RE.search(data)
        or "_source" in data.lower()
        or "raw-document" in data.lower()
    ):
        raise CensusBridgeError("child diagnostic contains forbidden material")
    return data


def _reject_response_material(serialized: str, value: Any) -> None:
    """Reject document material and credential-like response content."""

    if _SECRET_RE.search(serialized) or "_source" in serialized.lower():
        raise CensusBridgeError("transport response contains forbidden material")

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if key in {
                    "_id",
                    "_index",
                    "_type",
                    "document",
                    "documents",
                    "stored_fields",
                    "docvalue_fields",
                }:
                    raise CensusBridgeError("transport response contains document material")
                if key == "hits" and isinstance(child, Mapping) and "hits" in child:
                    raise CensusBridgeError("transport response contains raw hits")
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)


class CensusBridge:
    """Construct and validate only the bounded read-only census requests."""

    def __init__(self, transport: CensusTransport, profile: CensusProfile) -> None:
        if not hasattr(transport, "request") or not callable(transport.request):
            raise CensusBridgeError("transport is invalid")
        if not isinstance(profile, CensusProfile):
            raise CensusBridgeError("profile is invalid")
        # Recompute at the trust boundary as well as in the dataclass loader;
        # a caller could otherwise mutate a frozen instance via reflection.
        if profile.profile_revision != profile_revision_for(
            tenant_id=profile.tenant_id,
            catalog_ref=profile.catalog_ref,
            alias=profile.alias,
            index_ref=profile.index_ref,
            fields=profile.fields,
            profile_id=profile.profile_id,
            pit_keep_alive=profile.pit_keep_alive,
        ):
            raise CensusBridgeError("profile revision does not match pinned profile")
        self._transport = transport
        self.profile = profile
        self.stats = BridgeStats()
        self._pit_id: str | None = None
        self._query_hashes: list[str] = []

    @property
    def deny_before_network(self) -> int:
        return self.stats.deny_before_network

    @property
    def leak_findings(self) -> int:
        return self.stats.leak_findings

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Reject generic caller-supplied requests before transport invocation.

        There is intentionally no generic pass-through capability.  Internal
        methods call ``_invoke`` with a named operation and canonical payload.
        """

        self._deny("arbitrary transport request")
        raise CensusBridgeError("arbitrary transport request is forbidden")

    def _deny(self, _reason: str) -> None:
        self.stats.deny_before_network += 1

    def _invoke(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        try:
            self._validate_request(operation, method, path, query=query, body=body)
        except CensusBridgeError:
            self._deny("request validation")
            raise
        self.stats.transport_calls += 1
        self._query_hashes.append(
            _canonical_hash({"method": method, "path": path, "query": query, "body": body})
        )
        try:
            response = self._transport.request(method, path, query=query, body=body)
        except Exception:  # noqa: BLE001 - do not expose transport details
            raise CensusBridgeError("transport request failed") from None
        try:
            return _bounded_response(_mapping(response, "transport"))
        except CensusBridgeError as error:
            if any(
                marker in str(error)
                for marker in ("forbidden material", "raw hits", "document material")
            ):
                self.stats.leak_findings += 1
            raise

    def _validate_request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None,
        body: Mapping[str, Any] | None,
    ) -> None:
        index = self.profile.index_ref
        expected: dict[str, tuple[str, str, Mapping[str, str] | None]] = {
            "resolve": ("GET", f"/_alias/{self.profile.alias}", None),
            "mapping": ("GET", f"/{index}/_mapping", None),
            "field_caps": (
                "GET",
                f"/{index}/_field_caps",
                {"fields": ",".join(item.field_path for item in self.profile.fields)},
            ),
        }
        if operation == "pit_open":
            expected[operation] = (
                "POST",
                f"/{index}/_pit",
                {"keep_alive": self.profile.pit_keep_alive},
            )
        elif operation == "pit_close":
            expected[operation] = ("DELETE", "/_pit", None)
        elif operation == "search":
            expected[operation] = ("POST", "/_search", None)
        if operation not in expected:
            raise CensusBridgeError("operation is not allowlisted")
        expected_method, expected_path, expected_query = expected[operation]
        if method != expected_method or path != expected_path:
            raise CensusBridgeError("method or path is not allowlisted")
        if query != expected_query:
            raise CensusBridgeError("query is not allowlisted")
        if operation in {"resolve", "mapping", "field_caps", "pit_open"} and body is not None:
            raise CensusBridgeError("body is not allowlisted")
        if operation == "pit_close" and (body != {"id": self._pit_id} or self._pit_id is None):
            raise CensusBridgeError("PIT lifecycle body is not allowlisted")
        if operation == "search":
            self._validate_search_body(body)

    def _validate_search_body(self, body: Mapping[str, Any] | None) -> None:
        if not isinstance(body, Mapping):
            raise CensusBridgeError("search body is required")
        if set(body) != {"size", "track_total_hits", "pit", "aggs"}:
            raise CensusBridgeError("search body is not bounded")
        if body["size"] != 0 or body["track_total_hits"] is not True:
            raise CensusBridgeError("search must be size zero with total hits")
        pit = body["pit"]
        if not isinstance(pit, Mapping) or set(pit) != {"id", "keep_alive"}:
            raise CensusBridgeError("PIT body is invalid")
        if pit.get("id") != self._pit_id or pit.get("keep_alive") != self.profile.pit_keep_alive:
            raise CensusBridgeError("PIT identity is invalid")
        if not isinstance(body["aggs"], Mapping) or not body["aggs"]:
            raise CensusBridgeError("aggregations are required")
        self._validate_aggregations(body["aggs"])

    def _validate_aggregations(self, aggs: Mapping[str, Any]) -> None:
        allowed_fields = {item.field_path: item for item in self.profile.fields}
        for name, definition in aggs.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
                raise CensusBridgeError("aggregation name is invalid")
            if (
                not isinstance(definition, Mapping)
                or set(definition) != {"filter"}
                and set(definition) != {"composite"}
            ):
                raise CensusBridgeError("aggregation is not allowlisted")
            if "filter" in definition:
                filter_body = definition["filter"]
                if not isinstance(filter_body, Mapping):
                    raise CensusBridgeError("filter aggregation is invalid")
                if set(filter_body) == {"exists"}:
                    exists = filter_body["exists"]
                    if not isinstance(exists, Mapping) or set(exists) != {"field"}:
                        raise CensusBridgeError("exists aggregation is invalid")
                    field = exists["field"]
                    if field not in allowed_fields or allowed_fields[field].capability == "deny":
                        raise CensusBridgeError("field is not allowlisted")
                    if allowed_fields[field].capability not in CAPABILITIES - {"deny"}:
                        raise CensusBridgeError("field capability denies aggregate")
                elif set(filter_body) == {"bool"}:
                    bool_body = filter_body["bool"]
                    if not isinstance(bool_body, Mapping) or set(bool_body) != {"must_not"}:
                        raise CensusBridgeError("missing aggregation is invalid")
                    clauses = bool_body["must_not"]
                    if (
                        not isinstance(clauses, list)
                        or len(clauses) != 1
                        or not isinstance(clauses[0], Mapping)
                        or set(clauses[0]) != {"exists"}
                    ):
                        raise CensusBridgeError("missing aggregation is invalid")
                    exists = clauses[0]["exists"]
                    if not isinstance(exists, Mapping) or set(exists) != {"field"}:
                        raise CensusBridgeError("missing aggregation is invalid")
                    field = exists["field"]
                    if field not in allowed_fields or allowed_fields[field].capability == "deny":
                        raise CensusBridgeError("field is not allowlisted")
                else:
                    raise CensusBridgeError("filter is not allowlisted")
            else:
                composite = definition["composite"]
                if not isinstance(composite, Mapping) or set(composite) - {
                    "size",
                    "sources",
                    "after",
                }:
                    raise CensusBridgeError("composite aggregation is invalid")
                size = composite.get("size")
                sources = composite.get("sources")
                if (
                    type(size) is not int
                    or size < 1
                    or not isinstance(sources, list)
                    or len(sources) != 1
                ):
                    raise CensusBridgeError("composite aggregation is invalid")
                source = sources[0]
                if not isinstance(source, Mapping) or set(source) != {"value"}:
                    raise CensusBridgeError("composite source is invalid")
                value = source["value"]
                if not isinstance(value, Mapping) or set(value) != {"terms"}:
                    raise CensusBridgeError("composite terms are invalid")
                terms = value["terms"]
                if not isinstance(terms, Mapping) or set(terms) != {"field", "order"}:
                    raise CensusBridgeError("composite terms are invalid")
                field = terms["field"]
                if (
                    field not in allowed_fields
                    or allowed_fields[field].capability != "enumerate-finite-values"
                    or terms["order"] != "asc"
                ):
                    raise CensusBridgeError("field enumeration is not allowlisted")
                if "after" in composite:
                    if not isinstance(composite["after"], Mapping):
                        raise CensusBridgeError("composite cursor is invalid")
                    self._validate_cursor(
                        composite["after"], allowed_fields[field].max_literal_bytes
                    )
                if size > min(
                    allowed_fields[field].page_size, allowed_fields[field].cardinality_cap
                ):
                    raise CensusBridgeError("composite size exceeds field budget")

    def _resolve(self) -> None:
        response = self._invoke("resolve", "GET", f"/_alias/{self.profile.alias}")
        # Accept only one physical index, in either supported bounded shape.
        indices: list[str]
        if "indices" in response:
            if set(response) != {"indices"}:
                raise CensusBridgeError("alias response contains unexpected material")
            raw_indices = response["indices"]
            if (
                not isinstance(raw_indices, list)
                or len(raw_indices) != 1
                or not isinstance(raw_indices[0], Mapping)
                or set(raw_indices[0]) != {"index"}
                or not isinstance(raw_indices[0]["index"], str)
            ):
                raise CensusBridgeError("alias resolution is not one physical index")
            indices = [raw_indices[0]["index"]]
        elif set(response) != {self.profile.index_ref}:
            raise CensusBridgeError("alias response is outside the pinned index")
        else:
            if not isinstance(response[self.profile.index_ref], Mapping):
                raise CensusBridgeError("alias response is invalid")
            indices = [self.profile.index_ref]
        if indices != [self.profile.index_ref]:
            raise CensusBridgeError("alias resolution is outside the pinned index")

    def _inspect_mapping(self) -> None:
        response = self._invoke("mapping", "GET", f"/{self.profile.index_ref}/_mapping")
        if any(key not in {self.profile.index_ref} for key in response):
            raise CensusBridgeError("mapping response is outside the pinned index")
        root = response.get(self.profile.index_ref, response)
        root = _mapping(root, "mapping")
        mappings = root.get("mappings", root)
        mappings = _mapping(mappings, "mapping")
        properties = mappings.get("properties", {})
        properties = _mapping(properties, "mapping properties")
        for spec in self.profile.fields:
            if spec.capability == "deny":
                continue
            node: Any = properties
            for part in spec.field_path.split("."):
                node = node.get(part) if isinstance(node, Mapping) else None
            if not isinstance(node, Mapping) or node.get("type") != spec.mapping_type:
                raise CensusBridgeError("mapping does not match profile")

    def _inspect_field_caps(self) -> None:
        query = {"fields": ",".join(item.field_path for item in self.profile.fields)}
        response = self._invoke(
            "field_caps", "GET", f"/{self.profile.index_ref}/_field_caps", query=query
        )
        fields = response.get("fields", {})
        fields = _mapping(fields, "field capabilities")
        if any(key not in {item.field_path for item in self.profile.fields} for key in fields):
            raise CensusBridgeError("field capabilities contain non-profile fields")
        for spec in self.profile.fields:
            if spec.capability == "deny":
                continue
            entry = fields.get(spec.field_path)
            if not isinstance(entry, Mapping) or spec.mapping_type not in entry:
                raise CensusBridgeError("field capabilities do not match profile")
            details = entry[spec.mapping_type]
            if (
                not isinstance(details, Mapping) or details.get("aggregatable") is not True
            ) and spec.capability in {"aggregate-counts", "enumerate-finite-values"}:
                raise CensusBridgeError("field is not aggregatable")

    def _open_pit(self) -> str:
        response = self._invoke(
            "pit_open",
            "POST",
            f"/{self.profile.index_ref}/_pit",
            query={"keep_alive": self.profile.pit_keep_alive},
        )
        pit_id = response.get("pit_id", response.get("id"))
        if not isinstance(pit_id, str) or _PIT_RE.fullmatch(pit_id) is None:
            raise CensusBridgeError("PIT response is invalid")
        self._pit_id = pit_id
        return pit_id

    def _close_pit(self) -> None:
        if self._pit_id is None:
            return
        pit_id = self._pit_id
        try:
            self._invoke("pit_close", "DELETE", "/_pit", body={"id": pit_id})
        finally:
            self._pit_id = None

    def _search(self, aggs: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._pit_id is None:
            raise CensusBridgeError("PIT is not open")
        body = {
            "size": 0,
            "track_total_hits": True,
            "pit": {"id": self._pit_id, "keep_alive": self.profile.pit_keep_alive},
            "aggs": dict(aggs),
        }
        response = self._invoke("search", "POST", "/_search", body=body)
        hits = _mapping(response.get("hits"), "hits")
        total = _mapping(hits.get("total"), "total hits")
        if total.get("relation") != "eq" or type(total.get("value")) is not int:
            raise CensusBridgeError("total hits must be exact")
        return response

    def _counts(self, spec: FieldSpec) -> tuple[int, int, int]:
        if spec.capability not in {"aggregate-counts", "enumerate-finite-values", "open-no-values"}:
            return 0, 0, 0
        name = "f_" + hashlib.sha256(spec.field_path.encode()).hexdigest()[:12]
        response = self._search(
            {
                name + "_exists": {"filter": {"exists": {"field": spec.field_path}}},
                name + "_missing": {
                    "filter": {"bool": {"must_not": [{"exists": {"field": spec.field_path}}]}}
                },
            }
        )
        aggs = _mapping(response.get("aggregations"), "aggregations")
        exists = _mapping(aggs.get(name + "_exists"), "exists aggregation")
        missing = _mapping(aggs.get(name + "_missing"), "missing aggregation")
        exists_count = exists.get("doc_count")
        missing_count = missing.get("doc_count")
        total = response["hits"]["total"]["value"]
        if not all(type(value) is int and value >= 0 for value in (exists_count, missing_count)):
            raise CensusBridgeError("count aggregation is invalid")
        if isinstance(total, Mapping):
            total = total.get("value")
        if type(total) is not int or total < 0:
            raise CensusBridgeError("total hit count is invalid")
        if exists_count + missing_count != total:
            raise CensusBridgeError("exists and missing counts do not cover total")
        return exists_count, missing_count, total

    def _enumerate(self, spec: FieldSpec) -> tuple[list[dict[str, Any]], bool, int]:
        if spec.capability != "enumerate-finite-values":
            return [], True, 0
        if spec.cardinality_cap == 0 or spec.max_literal_bytes == 0:
            return [], False, 0
        name = "f_" + hashlib.sha256(spec.field_path.encode()).hexdigest()[:12]
        values: list[dict[str, Any]] = []
        after: Mapping[str, Any] | None = None
        seen_cursors: set[str] = set()
        previous_literal: str | None = None
        pages = 0
        while True:
            pages += 1
            if pages > spec.max_pages:
                return values, False, pages - 1
            composite: dict[str, Any] = {
                "size": min(spec.page_size, spec.cardinality_cap),
                "sources": [{"value": {"terms": {"field": spec.field_path, "order": "asc"}}}],
            }
            if after is not None:
                composite["after"] = dict(after)
            response = self._search({name + "_values": {"composite": composite}})
            aggs = _mapping(response.get("aggregations"), "aggregations")
            aggregate = _mapping(aggs.get(name + "_values"), "values aggregation")
            buckets = aggregate.get("buckets")
            if not isinstance(buckets, list):
                raise CensusBridgeError("value buckets are invalid")
            for bucket in buckets:
                if not isinstance(bucket, Mapping) or set(bucket) - {"key", "doc_count"}:
                    raise CensusBridgeError("value bucket is invalid")
                key = bucket.get("key")
                if not isinstance(key, Mapping) or set(key) != {"value"}:
                    raise CensusBridgeError("value bucket key is invalid")
                literal = key.get("value")
                count = bucket.get("doc_count")
                if (
                    not isinstance(literal, str)
                    or not _SAFE_LITERAL_RE.fullmatch(literal)
                    or len(literal.encode("utf-8")) > spec.max_literal_bytes
                    or type(count) is not int
                    or count < 0
                ):
                    raise CensusBridgeError("value bucket exceeds profile")
                if previous_literal is not None and literal <= previous_literal:
                    raise CensusBridgeError("value buckets are not strictly ordered")
                previous_literal = literal
                values.append({"literal": literal, "doc_count": count})
                if len(values) > spec.cardinality_cap:
                    return values[: spec.cardinality_cap], False, pages
            next_after = aggregate.get("after_key")
            if not buckets:
                if next_after is not None:
                    raise CensusBridgeError("empty page has a cursor")
                return values, True, pages
            if next_after is None:
                return values, True, pages
            if not isinstance(next_after, Mapping) or next_after == after:
                raise CensusBridgeError("pagination cursor is not advancing")
            self._validate_cursor(next_after, spec.max_literal_bytes)
            cursor_key = _canonical_hash(next_after)
            if cursor_key in seen_cursors:
                raise CensusBridgeError("pagination cursor cycles")
            seen_cursors.add(cursor_key)
            after = next_after

    @staticmethod
    def _validate_cursor(cursor: Mapping[str, Any], max_bytes: int) -> None:
        if set(cursor) != {"value"} or not isinstance(cursor.get("value"), str):
            raise CensusBridgeError("pagination cursor is invalid")
        if (
            not _SAFE_LITERAL_RE.fullmatch(cursor["value"])
            or len(json.dumps(cursor, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            > max_bytes
        ):
            raise CensusBridgeError("pagination cursor is invalid")

    def census(self) -> CensusResult:
        """Run the complete bounded fake/offline protocol and return sanitized data."""

        self._resolve()
        self._inspect_mapping()
        self._inspect_field_caps()
        self._open_pit()
        fields: list[dict[str, Any]] = []
        status = "VALID"
        try:
            for spec in self.profile.fields:
                if spec.capability == "deny":
                    fields.append(
                        {
                            "field_path": spec.field_path,
                            "field_status": "DENIED_FIELD",
                            "multi_valued": spec.multi_valued,
                        }
                    )
                    continue
                exists, missing, total = self._counts(spec)
                values, complete, pages = self._enumerate(spec)
                if not complete:
                    status = "PARTIAL"
                fields.append(
                    {
                        "field_path": spec.field_path,
                        "field_status": "OK" if complete else "PARTIAL",
                        "mapping_type": spec.mapping_type,
                        "nested_path": spec.nested_path,
                        "multi_valued": spec.multi_valued,
                        "exists_doc_count": exists,
                        "missing_doc_count": missing,
                        "distinct_count": len(values),
                        "complete": complete,
                        "pages": pages,
                        "values": values if spec.capability == "enumerate-finite-values" else [],
                        "open_no_values": spec.capability == "open-no-values",
                        "total_doc_count": total,
                    }
                )
        finally:
            self._close_pit()
        receipt = self._receipt(status, fields)
        return CensusResult(status, fields, receipt, self.stats)

    def run(self) -> CensusResult:
        """Compatibility name for callers that model the bridge as a runner."""

        return self.census()

    def _receipt(self, status: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
        offline_status = (
            "OFFLINE_CONTRACT_PARTIAL" if status == "PARTIAL" else "OFFLINE_CONTRACT_VALID"
        )
        state_counts = {
            "complete": sum(row.get("complete") is True for row in fields),
            "partial": sum(row.get("field_status") == "PARTIAL" for row in fields),
            "denied": sum(row.get("field_status") == "DENIED_FIELD" for row in fields),
            "non_aggregatable": sum(
                row.get("field_status") == "NON_AGGREGATABLE" for row in fields
            ),
            "inconsistent": 0,
        }
        body = {
            "schema_version": 1,
            "evidence_scope": "offline_contract",
            "contract_id": "video-census-bridge-p4a-v1",
            "profile_id": self.profile.profile_id,
            "profile_revision": self.profile.profile_revision,
            "tenant_ref": self.profile.tenant_id,
            "catalog_ref": self.profile.catalog_ref,
            "alias_ref": self.profile.alias,
            "index_ref": self.profile.index_ref,
            "protocol_mode": "pit",
            "atomicity_claim": False,
            "snapshot_ref": None,
            "live_evidence": False,
            "attestation": "not_performed",
            "live_attestation_claim": False,
            "execution": "offline_fake_transport",
            "status": offline_status,
            "field_count": len(fields),
            "transport_calls": self.stats.transport_calls,
            "deny_before_network": self.stats.deny_before_network,
            "leak_findings": self.stats.leak_findings,
            "query_count": len(self._query_hashes),
            "query_hashes": list(self._query_hashes),
            "state_counts": state_counts,
            "values_redacted": True,
            "field_result_sha256": _canonical_hash(fields),
            "artifact_sha256": _canonical_hash(fields),
            "nonclaims": [
                "no_live_census",
                "no_live_snapshot",
                "no_mapping_evidence",
                "no_document_evidence",
                "no_attestation",
            ],
        }
        receipt = {**body, "receipt_sha256": _canonical_hash(body)}
        self._assert_sanitized(receipt)
        errors = validate_census_receipt(receipt)
        if errors:
            raise CensusBridgeError("offline receipt schema is invalid")
        return receipt

    def _assert_sanitized(self, value: Any) -> None:
        try:
            serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            self.stats.leak_findings += 1
            raise CensusBridgeError("receipt is not serializable") from error
        if _SECRET_RE.search(serialized) or "_source" in serialized.lower():
            self.stats.leak_findings += 1
            raise CensusBridgeError("receipt sanitizer rejected payload")


# Short aliases make the contract convenient for test and adapter callers.
Profile = CensusProfile
Field = FieldSpec
Bridge = CensusBridge
