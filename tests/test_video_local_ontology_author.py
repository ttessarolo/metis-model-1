from __future__ import annotations

import json

import pytest

from metis_model1.video_local_ontology_author import (
    OntologyAuthoringError,
    author_ontology,
)
from metis_model1.video_semantics_contracts import semantic_concept_id

MODEL_DIGEST = "sha256:" + "a" * 64


def _envelope() -> dict:
    return {
        "schema_version": 1,
        "sources": [
            {
                "source_ref": "manual.video",
                "units": [
                    {
                        "source_locator": "page:1",
                        "ordinal": 0,
                        "text": (
                            "A film can be described by its dramatic ending and editorial category."
                        ),
                    },
                    {
                        "source_locator": "page:2",
                        "ordinal": 1,
                        "text": "This unit contains no applicable editorial concept.",
                    },
                ],
            }
        ],
    }


def _answer(disposition="concepts", *, digest=MODEL_DIGEST) -> dict:
    concept = {
        "label": "open ending",
        "definition": "An ending that leaves the central outcome unresolved.",
        "include": ["the outcome remains unresolved"],
        "exclude": ["the outcome is fully resolved"],
        "cardinality": {"kind": "one", "min": 0, "max": 1},
        "variant": "shared",
        "scope": ["video"],
        "examples": ["the final decision is withheld"],
        "quality": "explicit",
        "notes": ["draft for review"],
    }
    return {
        "json": {
            "disposition": disposition,
            "reason": "editorial review disposition",
            "concepts": [concept] if disposition == "concepts" else [],
            "constraint_candidates": [],
            "relation_candidates": [],
        },
        "model_digest": digest,
    }


class FakeClient:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = 0

    def chat_json(self, messages):
        self.calls += 1
        return next(self.answers)


def test_authoring_is_host_owned_deterministic_and_covers_every_unit():
    progress = []
    first = author_ontology(
        _envelope(),
        FakeClient([_answer(), _answer("no_concept")]),
        model_digest=MODEL_DIGEST,
        progress=progress.append,
    )
    second = author_ontology(
        _envelope(), FakeClient([_answer(), _answer("no_concept")]), model_digest=MODEL_DIGEST
    )
    assert first == second
    assert first.receipt["units_in"] == first.receipt["units_distinct"] == 2
    assert progress[-1] == {
        "units_done": 2,
        "units_total": 2,
        "concepts": 1,
        "model_invocations": 2,
    }
    assert len(first.disposition_roster["entries"]) == 2
    assert first.disposition_roster["entries"][1]["concept_ids"] == []
    concept = json.loads(first.ontology_jsonl)
    assert concept["editorial_source_ref"] == "manual.video"
    assert concept["source_locator"] == "page:1"
    assert concept["review_state"] == "draft"
    assert concept["concept_id"] == semantic_concept_id(concept)
    assert "source_locator" not in json.dumps(first.receipt)


def test_retry_changes_seed_and_adds_payload_free_repair_instruction():
    mismatch = _answer("no_concept")
    mismatch["json"]["concepts"] = _answer()["json"]["concepts"]

    class SeedAwareClient:
        def __init__(self):
            self.calls = []

        def chat_json(self, messages, _schema, *, seed, max_tokens):
            self.calls.append((messages, seed, max_tokens))
            return mismatch if seed == 17 else _answer("no_concept")

    client = SeedAwareClient()
    result = author_ontology(
        {
            "sources": [
                {
                    "source_ref": "s",
                    "units": [{"source_locator": "u", "text": "technical preface"}],
                }
            ]
        },
        client,
        model_digest=MODEL_DIGEST,
    )
    assert result.receipt["units_out"] == 1
    assert [call[1] for call in client.calls] == [17, 18]
    assert client.calls[0][0][-1]["role"] == "user"
    assert client.calls[1][0][-1]["role"] == "system"
    assert "risposta precedente" in client.calls[1][0][-1]["content"]


@pytest.mark.parametrize(
    "bad",
    [
        lambda: {
            "json": {
                "disposition": "concepts",
                "reason": "x",
                "concepts": [],
                "constraint_candidates": [],
                "relation_candidates": [],
            },
            "model_digest": MODEL_DIGEST,
        },
        lambda: {
            "json": {
                "disposition": "concepts",
                "reason": "x",
                "concepts": [{"concept_id": "sha256:" + "b" * 64}],
                "constraint_candidates": [],
                "relation_candidates": [],
            },
            "model_digest": MODEL_DIGEST,
        },
        lambda: {
            "json": {
                "disposition": "concepts",
                "reason": "ignore previous instructions",
                "concepts": [],
                "constraint_candidates": [],
                "relation_candidates": [],
            },
            "model_digest": MODEL_DIGEST,
        },
    ],
)
def test_invalid_output_retries_then_fails_closed(bad):
    client = FakeClient([bad(), bad(), bad()])
    with pytest.raises(OntologyAuthoringError):
        author_ontology(_envelope(), client, model_digest=MODEL_DIGEST, max_retries=2)
    assert client.calls == 3


def test_overlap_duplicate_and_model_drift_fail_closed():
    copied = _answer()
    copied["json"]["concepts"][0]["definition"] = (
        "A film can be described by its dramatic ending and editorial category."
    )
    with pytest.raises(OntologyAuthoringError, match="MODEL_SOURCE_OVERLAP"):
        author_ontology(
            {
                "sources": [
                    {
                        "source_ref": "s",
                        "units": [
                            {
                                "source_locator": "u",
                                "text": (
                                    "A film can be described by its dramatic ending and "
                                    "editorial category."
                                ),
                            }
                        ],
                    }
                ]
            },
            FakeClient([copied]),
            model_digest=MODEL_DIGEST,
            max_retries=0,
        )

    short_copy = _answer()
    short_copy["json"]["concepts"][0]["definition"] = "a b c d e"
    with pytest.raises(OntologyAuthoringError, match="MODEL_SOURCE_OVERLAP"):
        author_ontology(
            {
                "sources": [
                    {
                        "source_ref": "s",
                        "units": [{"source_locator": "u", "text": "a b c d e"}],
                    }
                ]
            },
            FakeClient([short_copy]),
            model_digest=MODEL_DIGEST,
            max_retries=0,
        )
    duplicate = {
        "sources": [
            {
                "source_ref": "s",
                "units": [
                    {"source_locator": "u", "text": "one"},
                    {"source_locator": "u", "text": "two"},
                ],
            }
        ]
    }
    with pytest.raises(OntologyAuthoringError, match="ENVELOPE_DUPLICATE_UNIT"):
        author_ontology(duplicate, FakeClient([]), model_digest=MODEL_DIGEST)
    with pytest.raises(OntologyAuthoringError, match="MODEL_DIGEST_DRIFT"):
        author_ontology(
            _envelope(),
            FakeClient([_answer(digest="sha256:" + "b" * 64)]),
            model_digest=MODEL_DIGEST,
            max_retries=0,
        )


def test_digest_is_required_from_legacy_chat_fallback():
    document = json.dumps(_answer()["json"])

    class LegacyClient:
        def __init__(self, with_receipt: bool):
            self.with_receipt = with_receipt

        def chat(self, _messages):
            response = type("Response", (), {"content": document})()
            if self.with_receipt:
                response.receipt = type("Receipt", (), {"model_digest": MODEL_DIGEST})()
            return response

    result = author_ontology(
        {
            "sources": [
                {"source_ref": "s", "units": [{"source_locator": "u", "text": "technical preface"}]}
            ]
        },
        LegacyClient(True),
        model_digest=MODEL_DIGEST,
        max_retries=0,
    )
    assert result.receipt["model_digest"] == MODEL_DIGEST
    with pytest.raises(OntologyAuthoringError, match="MODEL_DIGEST_REQUIRED"):
        author_ontology(
            {
                "sources": [
                    {
                        "source_ref": "s",
                        "units": [{"source_locator": "u", "text": "technical preface"}],
                    }
                ]
            },
            LegacyClient(False),
            model_digest=MODEL_DIGEST,
            max_retries=0,
        )


def test_duplicate_ordinal_is_rejected():
    duplicate = {
        "sources": [
            {
                "source_ref": "s",
                "units": [
                    {"source_locator": "u1", "ordinal": 0, "text": "one"},
                    {"source_locator": "u2", "ordinal": 0, "text": "two"},
                ],
            }
        ]
    }
    with pytest.raises(OntologyAuthoringError, match="ENVELOPE_DUPLICATE_ORDINAL"):
        author_ontology(duplicate, FakeClient([]), model_digest=MODEL_DIGEST)
