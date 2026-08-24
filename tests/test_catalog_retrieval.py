from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

import metis_model1.catalog_retrieval as retrieval_module
from metis_model1.catalog_retrieval import (
    CatalogRetrievalError,
    adapt_catalog_retrieval_response,
    validate_catalog_retrieval_receipt,
)
from metis_model1.contracts import repository_root

ROOT = repository_root()
TENANT_HASH = "sha256:" + "a" * 64


def _raw(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _describe() -> dict[str, Any]:
    return {
        "schema": 1,
        "tenant": "fixture-tenant",
        "thresholds": {"inline-max": 7, "enum-max": 99},
        "catalogs": [
            {
                "name": "fixture-tenant.video",
                "driver": "opensearch",
                "index": "video_fixture",
                "file": "catalogs/video.metis",
                "fields": [
                    {
                        "name": "kind",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "inline", "size": 2, "values": ["Film", "Serie"]},
                    },
                    {
                        "name": "genre",
                        "type": "keyword",
                        "modifiers": ["multi"],
                        "domain": {"kind": "enum", "size": 3, "nature": "editorial"},
                    },
                    {
                        "name": "labels",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "list", "size": 4},
                    },
                    {
                        "name": "metadata",
                        "type": "object",
                        "modifiers": ["ordered"],
                        "domain": {"kind": "none"},
                        "fields": [
                            {
                                "name": "title",
                                "type": "keyword",
                                "modifiers": [],
                                "domain": {"kind": "open"},
                            }
                        ],
                    },
                ],
            }
        ],
    }


def _values(kind: str = "enum") -> dict[str, Any]:
    if kind == "open":
        return {
            "schema": 1,
            "tenant": "fixture-tenant",
            "catalog": "fixture-tenant.video",
            "field": "title",
            "kind": "open",
            "note": "domain is the live index",
        }
    return {
        "schema": 1,
        "tenant": "fixture-tenant",
        "catalog": "fixture-tenant.video",
        "field": "genre",
        "kind": "enum",
        "size": 3,
        "nature": "editorial",
        "values": ["Drama", "News", "Sport"],
    }


def _contains_key(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(_contains_key(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


def _resign(receipt: dict[str, Any]) -> None:
    receipt["receipt_sha256"] = retrieval_module._receipt_hash(receipt)


def _rebind_request(receipt: dict[str, Any]) -> None:
    material = {
        "query": receipt["query"],
        "tenant_input_sha256": receipt["tenant_input"]["sha256"],
        "upstream": receipt["upstream"],
    }
    receipt["hashes"]["request_sha256"] = retrieval_module._sha256(
        retrieval_module._canonical(material)
    )


def test_describe_adapter_redacts_values_and_binds_pin_query_and_counts() -> None:
    receipt = adapt_catalog_retrieval_response(
        "describe",
        _raw(_describe()),
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        root=ROOT,
    )

    assert validate_catalog_retrieval_receipt(receipt, root=ROOT) == []
    assert receipt["query"] == {
        "operation": "describe",
        "tenant": "fixture-tenant",
        "catalog": "video",
        "field": None,
    }
    assert receipt["upstream"]["revision"] == "5e112f9148f40e7e792052e896c5a9efe8eaf0a2"
    assert receipt["upstream"]["verification"] == "manifest_contract_only"
    assert receipt["summary"] == {
        "kind": "describe",
        "size": None,
        "nature": None,
        "catalog_count": 1,
        "field_count": 5,
        "domain_count": 4,
        "value_count": 2,
    }
    assert receipt["policy"]["execution_verified"] is False
    assert receipt["policy"]["retrieval_refresh_verified"] is False
    assert not _contains_key(receipt, "values")


def test_values_adapter_records_only_kind_size_nature_and_counts() -> None:
    raw = _raw(_values())
    receipt = adapt_catalog_retrieval_response(
        "values",
        raw,
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        field="genre",
        root=ROOT,
    )

    assert receipt["summary"] == {
        "kind": "enum",
        "size": 3,
        "nature": "editorial",
        "catalog_count": 1,
        "field_count": 1,
        "domain_count": 1,
        "value_count": 3,
    }
    assert receipt["hashes"]["output_bytes"] == len(raw)
    assert receipt["hashes"]["response_sha256"] != receipt["hashes"]["output_sha256"]
    assert not _contains_key(receipt, "values")
    assert validate_catalog_retrieval_receipt(receipt, root=ROOT) == []


def test_open_domain_never_materializes_values() -> None:
    receipt = adapt_catalog_retrieval_response(
        "values",
        _raw(_values("open")),
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        field="title",
        root=ROOT,
    )
    assert receipt["summary"]["kind"] == "open"
    assert receipt["summary"]["size"] is None
    assert receipt["summary"]["value_count"] == 0

    attacked = _values("open")
    attacked["values"] = ["leak"]
    with pytest.raises(CatalogRetrievalError, match="must not materialize"):
        adapt_catalog_retrieval_response(
            "values",
            _raw(attacked),
            tenant_input_sha256=TENANT_HASH,
            catalog="video",
            field="title",
            root=ROOT,
        )


def test_enum_resolved_and_unsynchronized_shapes_are_exact() -> None:
    unsynchronized = _values()
    unsynchronized.pop("values")
    unsynchronized.pop("nature")
    unsynchronized["note"] = "value-set not synchronized"
    receipt = adapt_catalog_retrieval_response(
        "values",
        _raw(unsynchronized),
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        field="genre",
        root=ROOT,
    )
    assert receipt["summary"]["kind"] == "enum"
    assert receipt["summary"]["size"] == 3
    assert receipt["summary"]["nature"] is None
    assert receipt["summary"]["value_count"] == 0

    missing_values = _values()
    missing_values.pop("values")
    with pytest.raises(CatalogRetrievalError, match="nature and values together"):
        adapt_catalog_retrieval_response(
            "values",
            _raw(missing_values),
            tenant_input_sha256=TENANT_HASH,
            catalog="video",
            field="genre",
            root=ROOT,
        )

    missing_nature = _values()
    missing_nature.pop("nature")
    with pytest.raises(CatalogRetrievalError, match="nature and values together"):
        adapt_catalog_retrieval_response(
            "values",
            _raw(missing_nature),
            tenant_input_sha256=TENANT_HASH,
            catalog="video",
            field="genre",
            root=ROOT,
        )

    resolved_with_note = _values()
    resolved_with_note["note"] = "forged"
    with pytest.raises(CatalogRetrievalError, match="must not carry a note"):
        adapt_catalog_retrieval_response(
            "values",
            _raw(resolved_with_note),
            tenant_input_sha256=TENANT_HASH,
            catalog="video",
            field="genre",
            root=ROOT,
        )


@pytest.mark.parametrize(
    "payload,match",
    [
        (b'{"schema":1}\nwarning\n', "one complete JSON"),
        (b'{"schema":1,"schema":1}\n', "duplicate key"),
        (b'{"schema":NaN}\n', "non-JSON number"),
        (b"\xff", "not UTF-8"),
    ],
)
def test_malformed_or_extra_output_fails_closed(payload: bytes, match: str) -> None:
    with pytest.raises(CatalogRetrievalError, match=match):
        adapt_catalog_retrieval_response(
            "describe", payload, tenant_input_sha256=TENANT_HASH, root=ROOT
        )


def test_query_mismatch_unknown_shape_and_extra_fields_fail_closed() -> None:
    mismatch = _values()
    mismatch["catalog"] = "fixture-tenant.unknown"
    with pytest.raises(CatalogRetrievalError, match="catalog query"):
        adapt_catalog_retrieval_response(
            "values",
            _raw(mismatch),
            tenant_input_sha256=TENANT_HASH,
            catalog="video",
            field="genre",
            root=ROOT,
        )

    describe = _describe()
    describe["unexpected"] = True
    with pytest.raises(CatalogRetrievalError, match="missing or extra"):
        adapt_catalog_retrieval_response(
            "describe", _raw(describe), tenant_input_sha256=TENANT_HASH, root=ROOT
        )

    with pytest.raises(CatalogRetrievalError, match="requires catalog and field"):
        adapt_catalog_retrieval_response(
            "values", _raw(_values()), tenant_input_sha256=TENANT_HASH, root=ROOT
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"schema": True}),
        lambda value: value["thresholds"].update({"inline-max": True}),
        lambda value: value["catalogs"][0]["fields"][1]["domain"].update({"size": True}),
    ],
)
def test_bool_is_never_accepted_as_integer(mutation: Any) -> None:
    response = _describe()
    mutation(response)
    with pytest.raises(CatalogRetrievalError, match="integer"):
        adapt_catalog_retrieval_response(
            "describe", _raw(response), tenant_input_sha256=TENANT_HASH, root=ROOT
        )


def test_receipt_tamper_and_bool_as_int_fail_validation() -> None:
    receipt = adapt_catalog_retrieval_response(
        "values",
        _raw(_values()),
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        field="genre",
        root=ROOT,
    )
    tampered = deepcopy(receipt)
    tampered["summary"]["value_count"] = 2
    _resign(tampered)
    assert "enum summary is inconsistent" in "; ".join(
        validate_catalog_retrieval_receipt(tampered, root=ROOT)
    )

    boolean = deepcopy(receipt)
    boolean["summary"]["value_count"] = True
    _resign(boolean)
    errors = "; ".join(validate_catalog_retrieval_receipt(boolean, root=ROOT))
    assert "True is not of type 'integer'" in errors


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("pin_id", "catalog-domain-maintenance/forged"),
        ("revision", "0" * 40),
        ("tree", "1" * 40),
        ("manifest_sha256", "sha256:" + "2" * 64),
    ],
)
def test_resigned_receipt_cannot_substitute_the_tracked_pin(
    field: str,
    replacement: str,
) -> None:
    receipt = adapt_catalog_retrieval_response(
        "values",
        _raw(_values()),
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        field="genre",
        root=ROOT,
    )
    receipt["upstream"][field] = replacement
    _rebind_request(receipt)
    _resign(receipt)

    assert validate_catalog_retrieval_receipt(receipt, root=ROOT)


def test_resigned_receipt_rechecks_request_query_and_summary_bindings() -> None:
    receipt = adapt_catalog_retrieval_response(
        "values",
        _raw(_values()),
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        field="genre",
        root=ROOT,
    )

    stale_request = deepcopy(receipt)
    stale_request["query"]["tenant"] = "another-tenant"
    _resign(stale_request)
    assert "request_sha256 does not bind" in "; ".join(
        validate_catalog_retrieval_receipt(stale_request, root=ROOT)
    )

    path_attack = deepcopy(receipt)
    path_attack["query"]["catalog"] = "../../escape"
    _rebind_request(path_attack)
    _resign(path_attack)
    assert "path-inert" in "; ".join(validate_catalog_retrieval_receipt(path_attack, root=ROOT))

    summary_attack = deepcopy(receipt)
    summary_attack["summary"].update(
        {
            "kind": "describe",
            "size": None,
            "nature": None,
            "value_count": 0,
        }
    )
    _resign(summary_attack)
    assert "values query and summary are inconsistent" in "; ".join(
        validate_catalog_retrieval_receipt(summary_attack, root=ROOT)
    )


def test_manifest_contract_failure_stops_before_adaptation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retrieval_module.pin_module,
        "validate_catalog_maintenance_pin_contract",
        lambda _root: ["synthetic pin drift"],
    )
    with pytest.raises(CatalogRetrievalError, match="synthetic pin drift"):
        adapt_catalog_retrieval_response(
            "describe", _raw(_describe()), tenant_input_sha256=TENANT_HASH, root=ROOT
        )


def test_receipt_validator_fails_closed_when_tracked_pin_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = adapt_catalog_retrieval_response(
        "values",
        _raw(_values()),
        tenant_input_sha256=TENANT_HASH,
        catalog="video",
        field="genre",
        root=ROOT,
    )

    def unavailable(_root: Any) -> Any:
        raise retrieval_module.pin_module.CatalogMaintenancePinError("synthetic pin unavailable")

    monkeypatch.setattr(retrieval_module.pin_module, "load_catalog_maintenance_pin", unavailable)

    assert "synthetic pin unavailable" in "; ".join(
        validate_catalog_retrieval_receipt(receipt, root=ROOT)
    )
