from __future__ import annotations

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


class OfflineOnlyTransport:
    """Transport whose implementation makes any real-network call impossible."""

    def __init__(self) -> None:
        self.calls = 0

    def request(
        self,
        _method: str,
        _path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.calls += 1
        raise AssertionError(f"unexpected transport call: {query!r} {body!r}")


def make_bridge(transport: OfflineOnlyTransport) -> CensusBridge:
    fields = (FieldSpec("genre", "aggregate-counts"),)
    return CensusBridge(
        transport,
        CensusProfile(
            tenant_id="offline-tenant",
            catalog_ref="video",
            alias="offline-read",
            index_ref="offline-index",
            fields=fields,
            profile_revision=profile_revision_for(
                tenant_id="offline-tenant",
                catalog_ref="video",
                alias="offline-read",
                index_ref="offline-index",
                fields=fields,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "https://frontier.example/upload", {"prompt": "private"}),
        ("POST", "/_bulk", {"secret": "private"}),
        ("POST", "/_search", {"size": 10, "_source": True}),
    ],
)
def test_frontier_or_live_endpoint_is_denied_before_any_network(
    method: str, path: str, body: Mapping[str, Any]
) -> None:
    transport = OfflineOnlyTransport()
    bridge = make_bridge(transport)

    with pytest.raises(CensusBridgeError):
        bridge.request(method, path, body=body)

    assert transport.calls == 0
    assert bridge.deny_before_network == 1
    assert bridge.leak_findings == 0


def test_no_credential_or_diagnostic_channel_is_available_to_frontier_lane() -> None:
    assert build_child_environment() == {}
    with pytest.raises(CensusBridgeError):
        build_child_environment(
            {"OPENAI_API_KEY": "sentinel"}, allowed_keys=frozenset({"OPENAI_API_KEY"})
        )
    with pytest.raises(CensusBridgeError):
        validate_child_argv(("frontier-worker", "--token", "sentinel"))
    with pytest.raises(CensusBridgeError):
        sanitize_child_diagnostic("stdout: RAW-DOCUMENT sentinel")
