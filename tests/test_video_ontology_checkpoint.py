from __future__ import annotations

import copy
import json

import pytest

from metis_model1.video_local_ontology_author import OntologyAuthoringError
from metis_model1.video_ontology_checkpoint import (
    OntologyCheckpointError,
    _hash,
    author_ontology_checkpointed,
)

MODEL_DIGEST = "sha256:" + "a" * 64


def _envelope() -> dict:
    return {
        "schema_version": 1,
        "sources": [
            {
                "source_ref": "synthetic.video",
                "units": [
                    {
                        "source_locator": "page:2",
                        "ordinal": 1,
                        "text": "The ending leaves the central outcome unresolved.",
                    },
                    {
                        "source_locator": "page:1",
                        "ordinal": 0,
                        "text": "Editorial experts classify the dramatic structure.",
                    },
                    {
                        "source_locator": "page:3",
                        "ordinal": 2,
                        "text": "This unit is a technical preface without a concept.",
                    },
                ],
            }
        ],
    }


def _answer(label: str | None = "open ending") -> dict:
    concept = {
        "label": label or "unused",
        "definition": f"A bounded editorial definition for {label or 'unused'}.",
        "include": ["apply when the editorial criterion is met"],
        "exclude": ["exclude when the criterion is absent"],
        "cardinality": {"kind": "one", "min": 0, "max": 1},
        "variant": "shared",
        "scope": ["video"],
        "examples": ["a generalized editorial example"],
        "quality": "explicit",
        "notes": ["candidate for human review"],
    }
    disposition = "concepts" if label else "no_concept"
    return {
        "json": {
            "disposition": disposition,
            "reason": "bounded synthetic disposition",
            "concepts": [concept] if label else [],
            "constraint_candidates": [],
            "relation_candidates": [],
        },
        "model_digest": MODEL_DIGEST,
    }


class FakeClient:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = 0

    def chat_json(self, messages):
        self.calls += 1
        return next(self.answers)


def _run_with_store(envelope, answers, checkpoint=None):
    saved = []

    def load():
        return copy.deepcopy(checkpoint if checkpoint is not None else saved[-1] if saved else None)

    def save(value):
        saved.append(copy.deepcopy(dict(value)))

    client = FakeClient(answers)
    result = author_ontology_checkpointed(
        envelope,
        client,
        model_digest=MODEL_DIGEST,
        checkpoint_load=load,
        checkpoint_save=save,
    )
    return result, client, saved


def test_checkpoint_persists_host_validated_unit_outcomes_without_source_text():
    result, client, saved = _run_with_store(
        _envelope(), [_answer("editorial ending"), _answer("dramatic structure"), _answer(None)]
    )
    assert client.calls == 3
    assert len(saved) == 3
    assert result.receipt["units_in"] == result.receipt["units_out"] == 3
    assert result.receipt["units_distinct"] == 3
    assert result.receipt["units_gaps"] == 0
    serialized = json.dumps(saved[-1], ensure_ascii=False)
    assert '"text"' not in serialized
    assert "The ending leaves" not in serialized
    assert saved[-1]["checkpoint_sha256"].startswith("sha256:")


def test_resume_skips_only_exact_matches_and_reproduces_aggregate():
    envelope = _envelope()
    first, first_client, saved = _run_with_store(
        envelope, [_answer("editorial ending"), _answer("dramatic structure"), _answer(None)]
    )
    resumed_client = FakeClient([])
    resumed = author_ontology_checkpointed(
        envelope,
        resumed_client,
        model_digest=MODEL_DIGEST,
        checkpoint_load=lambda: copy.deepcopy(saved[-1]),
    )
    assert first == resumed
    assert first_client.calls == 3
    assert resumed_client.calls == 0


def test_partial_checkpoint_authors_only_missing_unit():
    envelope = _envelope()
    _first, _client, saved = _run_with_store(
        envelope, [_answer("editorial ending"), _answer("dramatic structure"), _answer(None)]
    )
    partial = copy.deepcopy(saved[0])
    client = FakeClient([_answer("dramatic structure"), _answer(None)])
    resumed = author_ontology_checkpointed(
        envelope,
        client,
        model_digest=MODEL_DIGEST,
        checkpoint_load=lambda: partial,
    )
    assert client.calls == 2
    assert resumed.receipt["units_distinct"] == 3


def _tamper_model_digest(checkpoint):
    checkpoint["model_digest"] = "sha256:" + "b" * 64


def _tamper_unit_text_hash(checkpoint):
    checkpoint["units"][0]["unit_text_sha256"] = "sha256:" + "b" * 64


@pytest.mark.parametrize(
    "mutator,code",
    [
        (_tamper_model_digest, "CHECKPOINT_INVALID"),
        (_tamper_unit_text_hash, "CHECKPOINT_HASH_INVALID"),
    ],
)
def test_tampered_checkpoint_fails_closed(mutator, code):
    _result, _client, saved = _run_with_store(
        _envelope(), [_answer("editorial ending"), _answer("dramatic structure"), _answer(None)]
    )
    tampered = copy.deepcopy(saved[-1])
    mutator(tampered)
    with pytest.raises(OntologyCheckpointError, match=code):
        author_ontology_checkpointed(
            _envelope(),
            FakeClient([]),
            model_digest=MODEL_DIGEST,
            checkpoint_load=lambda: tampered,
        )


def test_changed_source_text_rejects_old_checkpoint():
    _result, _client, saved = _run_with_store(
        _envelope(), [_answer("editorial ending"), _answer("dramatic structure"), _answer(None)]
    )
    changed = _envelope()
    changed["sources"][0]["units"][0]["text"] += " changed"
    with pytest.raises(OntologyCheckpointError, match="CHECKPOINT_INVALID"):
        author_ontology_checkpointed(
            changed,
            FakeClient([]),
            model_digest=MODEL_DIGEST,
            checkpoint_load=lambda: saved[-1],
        )


def test_invalid_unit_result_never_becomes_a_checkpoint_record():
    saved = []
    client = FakeClient([{"json": {"disposition": "bad"}, "model_digest": MODEL_DIGEST}])
    with pytest.raises((OntologyAuthoringError, OntologyCheckpointError)):
        author_ontology_checkpointed(
            {"sources": [{"source_ref": "s", "units": [{"source_locator": "u", "text": "one"}]}]},
            client,
            model_digest=MODEL_DIGEST,
            checkpoint_save=lambda value: saved.append(value),
            max_retries=0,
        )
    assert saved == []


def test_malformed_checkpoint_source_identity_returns_domain_error():
    _result, _client, saved = _run_with_store(
        _envelope(), [_answer("editorial ending"), _answer("dramatic structure"), _answer(None)]
    )
    malformed = copy.deepcopy(saved[-1])
    malformed["units"][0]["source_ref"] = []
    malformed["checkpoint_sha256"] = _hash(
        {key: value for key, value in malformed.items() if key != "checkpoint_sha256"}
    )
    with pytest.raises(OntologyCheckpointError, match="CHECKPOINT_UNIT_INVALID"):
        author_ontology_checkpointed(
            _envelope(),
            FakeClient([]),
            model_digest=MODEL_DIGEST,
            checkpoint_load=lambda: malformed,
        )


def test_oversized_checkpoint_is_rejected_before_deep_validation():
    huge = "x" * (16 * 1024 * 1024)
    oversized = {
        "schema_version": 1,
        "artifact_kind": "video-semantics/ontology-authoring-checkpoint-v1",
        "source_envelope_sha256": "sha256:" + "0" * 64,
        "model_digest": MODEL_DIGEST,
        "units": [huge],
        "checkpoint_sha256": "sha256:" + "0" * 64,
    }
    with pytest.raises(OntologyCheckpointError, match="CHECKPOINT_TOO_LARGE"):
        author_ontology_checkpointed(
            _envelope(),
            FakeClient([]),
            model_digest=MODEL_DIGEST,
            checkpoint_load=lambda: oversized,
        )
