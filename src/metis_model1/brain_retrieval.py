"""Session-bound, read-only retrieval contracts for Brain turns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from metis_model1.brain_context import ContextSnapshot
from metis_model1.brain_output_contract import OutputRequestSurface
from metis_model1.brain_protocol import BrainError
from metis_model1.brain_sessions import OperationLease


@dataclass(frozen=True)
class RetrievalResult:
    context: dict[str, Any]
    grounding: dict[str, Any]
    semantic_source_revision: str
    catalog_candidates: tuple[dict[str, str], ...] = ()
    output_request: OutputRequestSurface | None = None


class BrainRetriever(Protocol):
    def retrieve(self, *, lease: OperationLease, request: Any) -> RetrievalResult: ...


_CATALOG_RE = re.compile(r"\bcatalog\s+([A-Za-z0-9_.-]+)")


def semantic_revision(snapshot: ContextSnapshot) -> str:
    """Derive one stable revision from the same immutable session snapshot."""
    return snapshot.semantic_source_revision()


class SnapshotRetriever:
    """Conservative baseline retrieval over a tenant snapshot.

    It exposes only bounded metadata. A production semantic index can implement
    the same protocol without changing the turn protocol or its trust boundary.
    """

    def retrieve(self, *, lease: OperationLease, request: Any) -> RetrievalResult:
        snapshot = lease.snapshot
        names: list[str] = []
        for item in snapshot.files:
            if not item.path.endswith(".metis"):
                continue
            try:
                text = item.text
            except BrainError:
                continue
            names.extend(_CATALOG_RE.findall(text))
        unique = tuple(dict.fromkeys(names))
        candidates = tuple({"catalog": name, "label": name} for name in unique)
        requested = getattr(request, "catalog_hint", None)
        if requested and requested not in unique:
            candidates = ()
        if len(candidates) == 0:
            grounding: dict[str, Any] = {
                "catalog_candidates": [],
                "resolutions": [],
                "unresolved": [],
            }
        elif len(candidates) == 1:
            grounding = {
                "catalogs": [candidates[0]["catalog"]],
                "resolutions": [],
                "unresolved": [],
            }
        else:
            grounding = {
                "catalog_candidates": [item["catalog"] for item in candidates],
                "resolutions": [],
                "unresolved": [],
            }
        return RetrievalResult(
            context={
                "tenant_alias": snapshot.tenant_alias,
                "tenant_id": snapshot.tenant_id,
                "context_revision": snapshot.revision,
                "files": [
                    {"path": item.path, "sha256": item.sha256, "bytes": len(item.content)}
                    for item in snapshot.files
                ],
            },
            grounding=grounding,
            semantic_source_revision=semantic_revision(snapshot),
            catalog_candidates=candidates,
        )
