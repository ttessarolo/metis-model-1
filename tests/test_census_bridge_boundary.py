from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import pytest

from metis_model1.video_census_bridge import (
    CensusBridge,
    CensusBridgeError,
    CensusProfile,
    FieldSpec,
    build_child_environment,
    profile_revision_for,
    sanitize_child_diagnostic,
    validate_child_argv,
)
from metis_model1.video_semantics_contracts import validate_census_receipt


class FakeTransport:
    """Pure in-memory transport: any unexpected request is a test failure."""

    def __init__(self, *, raw_response: Mapping[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, Mapping[str, str] | None, Mapping[str, Any] | None]] = []
        self.raw_response = raw_response
        self.pit_id = "fake-pit-001"

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((method, path, query, body))
        if self.raw_response is not None:
            return self.raw_response
        if method == "GET" and path == "/_alias/video-read":
            return {"indices": [{"index": "video-index"}]}
        if method == "GET" and path == "/video-index/_mapping":
            return {
                "video-index": {
                    "mappings": {
                        "properties": {
                            "genre": {"type": "keyword"},
                            "title": {"type": "keyword"},
                            "internal": {"type": "keyword"},
                        }
                    }
                }
            }
        if method == "GET" and path == "/video-index/_field_caps":
            assert query is not None and set(query) == {"fields"}
            requested = query["fields"].split(",") if query["fields"] else []
            assert set(requested) <= {"genre", "title"}
            return {"fields": {field: {"keyword": {"aggregatable": True}} for field in requested}}
        if method == "POST" and path == "/video-index/_pit":
            assert query == {"keep_alive": "2m"}
            return {"pit_id": self.pit_id}
        if method == "DELETE" and path == "/_pit":
            assert body == {"id": self.pit_id}
            return {"succeeded": True}
        if method == "POST" and path == "/_search":
            assert body is not None
            aggs = body["aggs"]
            if any(name.endswith("_values") for name in aggs):
                definition = next(value for name, value in aggs.items() if name.endswith("_values"))
                composite = definition["composite"]
                if "after" not in composite:
                    return {
                        "hits": {"total": {"value": 3, "relation": "eq"}},
                        "aggregations": {
                            next(name for name in aggs if name.endswith("_values")): {
                                "buckets": [
                                    {"key": {"value": "Drama"}, "doc_count": 2},
                                    {"key": {"value": "Noir"}, "doc_count": 1},
                                ],
                                "after_key": {"value": "Noir"},
                            }
                        },
                    }
                return {
                    "hits": {"total": {"value": 3, "relation": "eq"}},
                    "aggregations": {
                        next(name for name in aggs if name.endswith("_values")): {
                            "buckets": [{"key": {"value": "Western"}, "doc_count": 1}]
                        }
                    },
                }
            result: dict[str, Any] = {
                "hits": {"total": {"value": 3, "relation": "eq"}},
                "aggregations": {},
            }
            for name in aggs:
                result["aggregations"][name] = {"doc_count": 2 if name.endswith("exists") else 1}
            return result
        raise AssertionError(f"unexpected fake request: {method} {path}")


class PagingTransport(FakeTransport):
    def __init__(self, pages: list[Mapping[str, Any]]) -> None:
        super().__init__()
        self.pages = pages
        self.page_calls = 0

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if method == "POST" and path == "/_search" and body is not None:
            aggs = body["aggs"]
            if any(name.endswith("_values") for name in aggs):
                name = next(name for name in aggs if name.endswith("_values"))
                page = self.pages[self.page_calls]
                self.page_calls += 1
                return {
                    "hits": {"total": {"value": 3, "relation": "eq"}},
                    "aggregations": {name: page},
                }
        return super().request(method, path, query=query, body=body)


class NestedTransport(FakeTransport):
    """Synthetic transport with one real nested mapping and parent counts."""

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if method == "GET" and path == "/video-index/_mapping":
            self.calls.append((method, path, query, body))
            return {
                "video-index": {
                    "mappings": {
                        "properties": {
                            "details": {
                                "type": "nested",
                                "properties": {"genre": {"type": "keyword"}},
                            },
                            "title": {
                                "type": "text",
                                "fields": {"keyword": {"type": "keyword"}},
                            },
                        }
                    }
                }
            }
        if method == "GET" and path == "/video-index/_field_caps":
            self.calls.append((method, path, query, body))
            assert query is not None and set(query) == {"fields"}
            requested = query["fields"].split(",")
            assert set(requested) <= {"details.genre", "title.keyword"}
            return {
                "indices": ["video-index"],
                "fields": {field: {"keyword": {"aggregatable": True}} for field in requested},
            }
        if method == "POST" and path == "/_search" and body is not None:
            self.calls.append((method, path, query, body))
            aggs = body["aggs"]
            value_names = [name for name in aggs if name.endswith("_values")]
            if value_names:
                name = value_names[0]
                outer = aggs[name]
                assert outer["nested"] == {"path": "details"}
                inner = outer["aggs"]["values"]
                assert inner["aggs"] == {"parent_documents": {"reverse_nested": {}}}
                return {
                    "hits": {"total": {"value": 3, "relation": "eq"}, "hits": []},
                    "aggregations": {
                        name: {
                            "doc_count": 4,
                            "values": {
                                "buckets": [
                                    {
                                        "key": {"value": "Drama"},
                                        "doc_count": 3,
                                        "parent_documents": {"doc_count": 2},
                                    }
                                ]
                            },
                        }
                    },
                }
            assert all(
                "nested" in definition["filter"]
                or "nested" in definition["filter"]["bool"]["must_not"][0]
                for definition in aggs.values()
            )
            return {
                "hits": {"total": {"value": 3, "relation": "eq"}, "hits": []},
                "aggregations": {
                    name: {"doc_count": 2 if name.endswith("exists") else 1} for name in aggs
                },
            }
        return super().request(method, path, query=query, body=body)


class InexactTotalTransport(FakeTransport):
    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        result = dict(super().request(method, path, query=query, body=body))
        if method == "POST" and path == "/_search":
            result["hits"] = {"total": {"value": 3, "relation": "gte"}}
        return result


class DuplicateAliasTransport(FakeTransport):
    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if method == "GET" and path == "/_alias/video-read":
            self.calls.append((method, path, query, body))
            return {"indices": [{"index": "video-index"}, {"index": "video-index"}]}
        return super().request(method, path, query=query, body=body)


def profile(*fields: FieldSpec) -> CensusProfile:
    revision = profile_revision_for(
        tenant_id="test-tenant",
        catalog_ref="video",
        alias="video-read",
        index_ref="video-index",
        fields=fields,
    )
    return CensusProfile(
        tenant_id="test-tenant",
        catalog_ref="video",
        alias="video-read",
        index_ref="video-index",
        fields=tuple(fields),
        profile_revision=revision,
    )


def test_complete_census_is_fake_only_and_size_zero() -> None:
    transport = FakeTransport()
    bridge = CensusBridge(
        transport,
        profile(
            FieldSpec("genre", "enumerate-finite-values", cardinality_cap=10, max_pages=3),
            FieldSpec("title", "open-no-values"),
            FieldSpec("internal", "deny"),
        ),
    )

    result = bridge.census()

    assert result.status == "VALID"
    assert result.stats.deny_before_network == 0
    assert result.stats.leak_findings == 0
    assert result.stats.transport_calls == 9
    assert result.receipt["attestation"] == "not_performed"
    assert result.receipt["evidence_scope"] == "offline_contract"
    assert result.receipt["status"] == "OFFLINE_CONTRACT_VALID"
    assert result.receipt["query_count"] == len(result.receipt["query_hashes"])
    assert "mapping_sha256_before" not in result.receipt
    assert "started_at" not in result.receipt
    assert result.receipt["live_evidence"] is False
    assert validate_census_receipt(result.receipt) == []
    assert result.receipt["live_attestation_claim"] is False
    assert [row["field_status"] for row in result.fields] == ["OK", "OK", "DENIED_FIELD"]
    assert result.fields[0]["values"] == [
        {"literal": "Drama", "doc_count": 2},
        {"literal": "Noir", "doc_count": 1},
        {"literal": "Western", "doc_count": 1},
    ]
    assert result.fields[1]["values"] == []
    assert [row["field_path"] for row in result.fields] == ["genre", "title", "internal"]
    assert [row["multi_valued"] for row in result.fields] == ["unknown", "unknown", "unknown"]
    search_calls = [call for call in transport.calls if call[1] == "/_search"]
    assert search_calls
    for _, _, _, body in search_calls:
        assert body is not None
        assert body["size"] == 0
        assert body["track_total_hits"] is True
        assert "_source" not in body
    assert transport.calls[-1][0:2] == ("DELETE", "/_pit")


def test_profile_contract_is_versioned_and_reloaded_before_transport() -> None:
    original = profile(FieldSpec("genre", "aggregate-counts"))
    contract = original.to_contract()
    assert CensusProfile.from_contract(contract) == original
    tampered = dict(contract)
    tampered["profile_revision"] = "sha256:" + "0" * 64
    with pytest.raises(CensusBridgeError):
        CensusProfile.from_contract(tampered)
    with pytest.raises(CensusBridgeError):
        CensusProfile(
            tenant_id="test-tenant",
            catalog_ref="video",
            alias="video-read",
            index_ref="video-index",
            fields=original.fields,
            profile_revision="sha256:" + "0" * 64,
        )
    object.__setattr__(original, "profile_revision", "sha256:" + "1" * 64)
    transport = FakeTransport()
    with pytest.raises(CensusBridgeError):
        CensusBridge(transport, original)
    assert transport.calls == []


def test_receipt_self_hash_tampering_is_rejected_by_canonical_validator() -> None:
    fields = (
        FieldSpec("genre", "aggregate-counts"),
        FieldSpec("title", "open-no-values"),
        FieldSpec("internal", "deny"),
    )
    receipt = CensusBridge(FakeTransport(), profile(*fields)).census().receipt
    receipt["receipt_sha256"] = "sha256:" + "0" * 64
    assert any("self-hash" in error for error in validate_census_receipt(receipt))


def test_alias_resolution_requires_exactly_one_physical_index() -> None:
    transport = DuplicateAliasTransport()
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "aggregate-counts")))
    with pytest.raises(CensusBridgeError, match="one physical index"):
        bridge._resolve()
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("method", "path", "query", "body"),
    [
        ("POST", "/_bulk", None, {"index": {"_id": "x"}}),
        ("POST", "/video-index/_update", None, {"doc": {"x": "y"}}),
        ("POST", "/video-index/_delete_by_query", None, {"query": {"match_all": {}}}),
        ("POST", "/video-index/_reindex", None, {"source": "video-index"}),
        ("GET", "/video-index/doc-1", None, None),
        ("GET", "/video-index/_source", None, None),
        ("GET", "/video-index/_mapping/other", None, None),
        ("POST", "https://evil.example/steal", None, {"password": "sentinel"}),
    ],
)
def test_arbitrary_and_write_requests_are_denied_before_transport(
    method: str,
    path: str,
    query: Mapping[str, str] | None,
    body: Mapping[str, Any] | None,
) -> None:
    transport = FakeTransport()
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "aggregate-counts")))

    with pytest.raises(CensusBridgeError):
        bridge.request(method, path, query=query, body=body)

    assert transport.calls == []
    assert bridge.deny_before_network == 1


def test_internal_allowlist_rejects_query_body_and_pit_misuse_before_transport() -> None:
    transport = FakeTransport()
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "aggregate-counts")))
    bad_requests = [
        ("mapping", "POST", "/video-index/_mapping", None, None),
        ("mapping", "GET", "/video-index/_mapping", {"refresh": "true"}, None),
        ("search", "POST", "/_search", None, {"size": 10}),
        ("pit_close", "DELETE", "/_pit", None, {"id": "wrong-pit"}),
    ]
    for operation, method, path, query, body in bad_requests:
        with pytest.raises(CensusBridgeError):
            bridge._invoke(operation, method, path, query=query, body=body)

    assert transport.calls == []
    assert bridge.deny_before_network == len(bad_requests)


def test_raw_document_response_is_rejected_without_leaking_material() -> None:
    sentinel = "RAW-DOCUMENT-SHOULD-NOT-ESCAPE"
    transport = FakeTransport(raw_response={"hits": {"hits": [{"_source": {"x": sentinel}}]}})
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "aggregate-counts")))

    with pytest.raises(CensusBridgeError) as error:
        bridge._invoke("resolve", "GET", "/_alias/video-read")

    assert sentinel not in str(error.value)
    assert bridge.leak_findings == 1
    assert len(transport.calls) == 1


def test_normal_size_zero_hits_envelope_is_allowed_but_nonempty_hits_are_denied() -> None:
    allowed = {
        "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
        "aggregations": {},
    }
    bridge = CensusBridge(
        FakeTransport(raw_response=allowed), profile(FieldSpec("genre", "aggregate-counts"))
    )
    assert bridge._invoke("resolve", "GET", "/_alias/video-read") == allowed

    denied = {
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [{"sort": [1]}],
        }
    }
    bridge = CensusBridge(
        FakeTransport(raw_response=denied), profile(FieldSpec("genre", "aggregate-counts"))
    )
    with pytest.raises(CensusBridgeError, match="raw hits"):
        bridge._invoke("resolve", "GET", "/_alias/video-read")
    assert bridge.leak_findings == 1


@pytest.mark.parametrize(
    "response",
    [
        {"_id": "doc-1"},
        {"document": {"title": "private"}},
        {"hits": {"hits": [{"_index": "video-index"}]}},
    ],
)
def test_each_forbidden_document_response_increments_leak_counter(
    response: Mapping[str, Any],
) -> None:
    transport = FakeTransport(raw_response=response)
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "aggregate-counts")))
    with pytest.raises(CensusBridgeError):
        bridge._invoke("resolve", "GET", "/_alias/video-read")
    assert bridge.leak_findings == 1


def test_receipt_is_bounded_and_contains_no_secret_or_raw_document() -> None:
    transport = FakeTransport()
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "open-no-values")))
    bridge._pit_id = "pit-memory-only"
    receipt = bridge._receipt("VALID", [{"field_status": "OK"}])
    encoded = json.dumps(receipt, sort_keys=True)
    assert "password" not in encoded.lower()
    assert "authorization" not in encoded.lower()
    assert "_source" not in encoded.lower()
    assert "pit-memory-only" not in encoded
    assert receipt["protocol_mode"] == "pit"
    assert receipt["atomicity_claim"] is False
    assert receipt["snapshot_ref"] is None
    assert receipt["live_evidence"] is False


def test_composite_cursor_cycle_is_rejected_beyond_consecutive_equality() -> None:
    transport = PagingTransport(
        [
            {"buckets": [{"key": {"value": "A"}, "doc_count": 1}], "after_key": {"value": "B"}},
            {"buckets": [{"key": {"value": "B"}, "doc_count": 1}], "after_key": {"value": "C"}},
            {"buckets": [{"key": {"value": "C"}, "doc_count": 1}], "after_key": {"value": "B"}},
        ]
    )
    bridge = CensusBridge(
        transport,
        profile(FieldSpec("genre", "enumerate-finite-values", max_pages=5)),
    )
    bridge._pit_id = transport.pit_id

    with pytest.raises(CensusBridgeError, match="cursor cycles"):
        bridge._enumerate(bridge.profile.fields[0])


def test_composite_duplicate_literal_is_rejected() -> None:
    transport = PagingTransport(
        [
            {"buckets": [{"key": {"value": "A"}, "doc_count": 1}], "after_key": {"value": "B"}},
            {"buckets": [{"key": {"value": "A"}, "doc_count": 1}]},
        ]
    )
    bridge = CensusBridge(
        transport,
        profile(FieldSpec("genre", "enumerate-finite-values", max_pages=5)),
    )
    bridge._pit_id = transport.pit_id

    with pytest.raises(CensusBridgeError, match="strictly ordered"):
        bridge._enumerate(bridge.profile.fields[0])


def test_composite_out_of_order_literal_is_rejected() -> None:
    transport = PagingTransport(
        [
            {
                "buckets": [
                    {"key": {"value": "B"}, "doc_count": 1},
                    {"key": {"value": "A"}, "doc_count": 1},
                ]
            }
        ]
    )
    bridge = CensusBridge(
        transport,
        profile(FieldSpec("genre", "enumerate-finite-values", max_pages=5)),
    )
    bridge._pit_id = transport.pit_id

    with pytest.raises(CensusBridgeError, match="strictly ordered"):
        bridge._enumerate(bridge.profile.fields[0])


def test_nested_fields_preserve_parent_document_correlation() -> None:
    transport = NestedTransport()
    spec = FieldSpec(
        "details.genre",
        "enumerate-finite-values",
        nested_path="details",
    )
    result = CensusBridge(transport, profile(spec)).census()

    assert result.status == "VALID"
    assert result.fields == [
        {
            "field_path": "details.genre",
            "field_status": "OK",
            "mapping_type": "keyword",
            "nested_path": "details",
            "multi_valued": "unknown",
            "exists_doc_count": 2,
            "missing_doc_count": 1,
            "distinct_count": 1,
            "complete": True,
            "pages": 1,
            "values": [{"literal": "Drama", "doc_count": 2}],
            "open_no_values": False,
            "total_doc_count": 3,
        }
    ]
    search_bodies = [
        body
        for method, path, _query, body in transport.calls
        if method == "POST" and path == "/_search"
    ]
    assert search_bodies[0] is not None
    count_aggs = search_bodies[0]["aggs"]
    assert all(
        definition["filter"].get("nested", {}).get("path") == "details"
        or definition["filter"]["bool"]["must_not"][0]["nested"]["path"] == "details"
        for definition in count_aggs.values()
    )
    assert search_bodies[1] is not None
    value_agg = next(iter(search_bodies[1]["aggs"].values()))
    assert value_agg["nested"] == {"path": "details"}
    assert value_agg["aggs"]["values"]["aggs"] == {"parent_documents": {"reverse_nested": {}}}


def test_nested_and_multifield_mapping_must_match_the_pinned_profile() -> None:
    with pytest.raises(CensusBridgeError, match="strict field-path prefix"):
        FieldSpec("details.genre", "enumerate-finite-values", nested_path="other")

    nested_transport = NestedTransport()
    flat_profile = profile(FieldSpec("details.genre", "aggregate-counts"))
    with pytest.raises(CensusBridgeError, match="nested path"):
        CensusBridge(nested_transport, flat_profile)._inspect_mapping()

    keyword_transport = NestedTransport()
    keyword_bridge = CensusBridge(
        keyword_transport,
        profile(FieldSpec("title.keyword", "aggregate-counts")),
    )
    keyword_bridge._inspect_mapping()
    keyword_bridge._inspect_field_caps()


def test_oversized_composite_budget_is_denied_before_network() -> None:
    transport = FakeTransport()
    bridge = CensusBridge(
        transport,
        profile(FieldSpec("genre", "enumerate-finite-values", page_size=1, cardinality_cap=2)),
    )
    bridge._pit_id = transport.pit_id
    body = {
        "size": 0,
        "track_total_hits": True,
        "pit": {"id": transport.pit_id, "keep_alive": "2m"},
        "aggs": {
            "values": {
                "composite": {
                    "size": 2,
                    "sources": [{"value": {"terms": {"field": "genre", "order": "asc"}}}],
                }
            }
        },
    }
    with pytest.raises(CensusBridgeError, match="field budget"):
        bridge._validate_search_body(body)
    assert transport.calls == []


def test_zero_budget_is_explicitly_partial_and_cursor_bytes_are_bounded() -> None:
    transport = FakeTransport()
    bridge = CensusBridge(
        transport,
        profile(FieldSpec("genre", "enumerate-finite-values", cardinality_cap=0)),
    )
    bridge._pit_id = transport.pit_id
    values, complete, pages = bridge._enumerate(bridge.profile.fields[0])
    assert values == []
    assert complete is False
    assert pages == 0
    assert transport.calls == []
    with pytest.raises(CensusBridgeError, match="cursor"):
        bridge._validate_cursor({"value": "abcdef"}, 3)


def test_zero_budget_census_emits_a_schema_valid_offline_partial_receipt() -> None:
    result = CensusBridge(
        FakeTransport(),
        profile(
            FieldSpec("genre", "enumerate-finite-values", cardinality_cap=0),
            FieldSpec("title", "open-no-values"),
            FieldSpec("internal", "deny"),
        ),
    ).census()

    assert result.status == "PARTIAL"
    assert result.receipt["status"] == "OFFLINE_CONTRACT_PARTIAL"
    assert result.receipt["atomicity_claim"] is False
    assert validate_census_receipt(result.receipt) == []


def test_total_relation_and_count_partition_are_exact() -> None:
    transport = InexactTotalTransport()
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "aggregate-counts")))
    bridge._pit_id = transport.pit_id
    with pytest.raises(CensusBridgeError, match="exact"):
        bridge._counts(bridge.profile.fields[0])

    transport = FakeTransport()
    bridge = CensusBridge(transport, profile(FieldSpec("genre", "aggregate-counts")))
    bridge._pit_id = transport.pit_id
    name = "f_" + hashlib.sha256(b"genre").hexdigest()[:12]
    bridge._search = lambda _aggs: {  # type: ignore[method-assign]
        "hits": {"total": {"value": 3, "relation": "eq"}},
        "aggregations": {
            name + "_exists": {"doc_count": 2},
            name + "_missing": {"doc_count": 0},
        },
    }
    with pytest.raises(CensusBridgeError, match="do not cover"):
        bridge._counts(bridge.profile.fields[0])


def test_child_boundary_is_empty_by_default_and_diagnostics_fail_closed() -> None:
    assert build_child_environment() == {}
    assert build_child_environment({"PATH": "/usr/bin"}, allowed_keys=frozenset({"PATH"})) == {
        "PATH": "/usr/bin"
    }
    with pytest.raises(CensusBridgeError):
        build_child_environment({"PASSWORD": "sentinel"}, allowed_keys=frozenset({"PASSWORD"}))
    with pytest.raises(CensusBridgeError):
        build_child_environment({"PATH": "token=sentinel"}, allowed_keys=frozenset({"PATH"}))
    with pytest.raises(CensusBridgeError):
        build_child_environment(
            {"DYLD_INSERT_LIBRARIES": "/tmp/inject.dylib"},
            allowed_keys=frozenset({"DYLD_INSERT_LIBRARIES"}),
        )
    with pytest.raises(CensusBridgeError):
        validate_child_argv(("worker", "--password=sentinel"))
    with pytest.raises(CensusBridgeError):
        validate_child_argv(("/bin/sh", "-c", "curl https://example.invalid"))
    assert validate_child_argv(("/usr/bin/true", "--metis-census-boundary-probe")) == (
        "/usr/bin/true",
        "--metis-census-boundary-probe",
    )
    with pytest.raises(CensusBridgeError):
        sanitize_child_diagnostic("stderr: Authorization: sentinel")
    with pytest.raises(CensusBridgeError):
        sanitize_child_diagnostic("editorial text that looks harmless")
    assert sanitize_child_diagnostic("READY") == "READY"
