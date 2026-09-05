from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from metis_model1 import brain_mlx_runtime as mlx_runtime
from metis_model1 import initial_local_qlora_runtime as qualified_runtime
from metis_model1.brain_create_plan_v2 import (
    CREATE_DELTA_PLAN_BODY_V2_SCHEMA_SHA256,
    CompactAuthorityProjection,
    RequirementHandle,
    SlotGrant,
    compact_authority_projection_revision,
)
from metis_model1.brain_mlx_runtime import (
    MlxBrainModelRuntime,
    serialize_create_plan_v2_messages,
)
from metis_model1.brain_model_runtime import CreatePlanV2Request
from metis_model1.brain_protocol import BrainError, canonical_json

CONTEXT = "sha256:" + "a" * 64
SEMANTIC = "sha256:" + "b" * 64
SURFACE = "sha256:" + "c" * 64


def _projection() -> CompactAuthorityProjection:
    requirements = (
        RequirementHandle(
            0, "hostref:private-requirement", "ventiquattro risultati", frozenset({"set"})
        ),
    )
    authorities = (
        SlotGrant(
            handle=10,
            ref="hostref:private-slot",
            label="quantita risultati",
            anchor_ref="hostref:private-anchor",
            member="take",
            cardinality="one",
            accepts=("value",),
            mutations=frozenset({"set"}),
            insertion="exact",
            basis_spec_sha256=None,
            generation=0,
        ),
    )
    revision = compact_authority_projection_revision(
        surface_revision=SURFACE,
        requirements=requirements,
        authorities=authorities,
    )
    return CompactAuthorityProjection(revision, SURFACE, requirements, authorities)


def _request() -> CreatePlanV2Request:
    return CreatePlanV2Request(
        instructions=("Crea un endpoint.", "Restituisci ventiquattro risultati."),
        generation=0,
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        active_requirement_handles=(0,),
        authority_projection=_projection(),
    )


def _body() -> dict[str, object]:
    return {"o": [{"k": "s", "q": [0], "s": 10, "v": 10}]}


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MlxBrainModelRuntime:
    model = tmp_path / "model"
    adapter = tmp_path / "adapter"
    model.mkdir()
    adapter.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (adapter / "adapters.safetensors").write_bytes(b"adapter")
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " if request.get('operation') == 'warmup':\n"
        "  print(json.dumps({'schema_version':1,'request_id':request['request_id'],"
        "'status':'ready','worker_load_ms':10,'model_revision':'model-revision',"
        "'adapter_sha256':'sha256:'+'a'*64}),flush=True); continue\n"
        " if request.get('schema_version') != 5 or request.get('operation') != 'plan_create_v2':\n"
        "  sys.exit(3)\n"
        " print(json.dumps({'schema_version':5,'request_id':request['request_id'],"
        "'body':{'o':[{'k':'s','q':[0],'s':10,'v':10}]},"
        "'model_revision':'model-revision','adapter_sha256':'sha256:'+'a'*64,"
        "'schema_sha256':request['schema_sha256'],"
        "'decoder_schema_sha256':request['decoder_schema_sha256'],"
        "'decoder':request['decoder'],'worker_load_ms':10,"
        "'worker_request_ms':131,'generation_ms':120,'cache_prepare_ms':2,"
        "'tokenization_ms':4,'time_to_first_token_ms':70,"
        "'decode_after_first_token_ms':40,'generation_residual_ms':10,"
        "'worker_residual_ms':5,'prompt_tokens':30,'uncached_prompt_tokens':30,"
        "'generation_tokens':4,'cached_tokens':0,'cache_hit':False,"
        "'cache_mode':'disabled','prompt_tps':30000/70,'generation_tps':100.0,"
        "'finish_reason':'stop','peak_metal_gb':1.0}),flush=True)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(qualified_runtime, "_no_symlinks", lambda _path: None)
    monkeypatch.setattr(
        qualified_runtime,
        "_check_runtime",
        lambda: {"python": "3.12.10", "packages": {"mlx": "0.32.1"}},
    )
    monkeypatch.setattr(
        qualified_runtime,
        "_check_checkpoint",
        lambda path: {"revision": "model-revision", "path": str(path)},
    )
    monkeypatch.setattr(
        qualified_runtime,
        "verify_checkpoint",
        lambda path: {"model_revision": "model-revision", "path": str(path)},
    )
    monkeypatch.setattr(qualified_runtime, "_prefixed_sha256", lambda _path: "sha256:" + "a" * 64)
    value = MlxBrainModelRuntime(
        python_path=sys.executable,
        model_path=model,
        adapter_path=adapter,
        worker_script=worker,
        timeout_seconds=2.0,
    )
    yield value
    value.close()


def _valid_response() -> dict[str, object]:
    return {
        "schema_version": mlx_runtime.CREATE_PLAN_V2_WIRE_VERSION,
        "request_id": "request",
        "body": _body(),
        "model_revision": "model-revision",
        "adapter_sha256": "sha256:" + "a" * 64,
        "schema_sha256": CREATE_DELTA_PLAN_BODY_V2_SCHEMA_SHA256,
        "decoder_schema_sha256": qualified_runtime.CREATE_PLAN_V2_DECODER_SCHEMA_SHA256,
        "decoder": qualified_runtime.CREATE_PLAN_V2_DECODER,
        "worker_load_ms": 10,
        "worker_request_ms": 131,
        "generation_ms": 120,
        "cache_prepare_ms": 2,
        "tokenization_ms": 4,
        "time_to_first_token_ms": 70,
        "decode_after_first_token_ms": 40,
        "generation_residual_ms": 10,
        "worker_residual_ms": 5,
        "prompt_tokens": 30,
        "uncached_prompt_tokens": 30,
        "generation_tokens": 4,
        "cached_tokens": 0,
        "cache_hit": False,
        "cache_mode": "disabled",
        "prompt_tps": 30_000 / 70,
        "generation_tps": 100.0,
        "finish_reason": "stop",
        "peak_metal_gb": 1.0,
    }


def test_v2_model_envelope_contains_only_the_six_authorized_surfaces() -> None:
    messages = serialize_create_plan_v2_messages(_request())
    assert [item["role"] for item in messages] == ["system", "user", "user"]
    encoded = messages[-1]["content"].split("\n", 1)[1]
    payload = json.loads(encoded)
    assert set(payload) == {
        "instructions",
        "generation",
        "context_revision",
        "semantic_revision",
        "active_requirement_handles",
        "authority_projection",
    }
    assert payload["active_requirement_handles"] == [0]
    assert payload["authority_projection"] == _projection().model_projection_payload()
    for private_marker in (
        "hostref:",
        "fragment",
        "arguments",
        "evidence",
        "source_path",
        "raw_source",
        "golden",
        "template",
        "private-slot",
        "private-anchor",
    ):
        assert private_marker not in encoded.casefold()


def test_v2_serializer_is_deterministic_and_rejects_wrong_request_type() -> None:
    assert serialize_create_plan_v2_messages(_request()) == serialize_create_plan_v2_messages(
        _request()
    )
    with pytest.raises(BrainError) as raised:
        serialize_create_plan_v2_messages(object())  # type: ignore[arg-type]
    assert raised.value.code == "MODEL_INPUT_INVALID"


def test_v2_plan_reuses_the_persistent_worker_and_preserves_telemetry(
    runtime: MlxBrainModelRuntime,
) -> None:
    runtime.warmup()
    assert runtime._process is not None  # noqa: SLF001
    pid = runtime._process.pid  # noqa: SLF001
    candidate = runtime.plan_create_v2(_request())
    assert candidate.body == _body()
    assert candidate.generator == "model_create_plan_v2"
    assert candidate.model_revision == "model-revision"
    assert candidate.metrics["finish_reason"] == "stop"
    assert candidate.metrics["cache_mode"] == "disabled"
    assert runtime._process is not None and runtime._process.pid == pid  # noqa: SLF001
    assert runtime._process_requests == 1  # noqa: SLF001


def test_v2_response_rejects_truncation_identity_drift_and_duplicates(
    runtime: MlxBrainModelRuntime,
) -> None:
    for key, replacement in (
        ("finish_reason", "length"),
        ("schema_sha256", "sha256:" + "0" * 64),
        ("decoder_schema_sha256", "sha256:" + "1" * 64),
        ("cache_mode", "prefix"),
    ):
        value = {**_valid_response(), key: replacement}
        with pytest.raises(BrainError) as raised:
            runtime._parse_create_plan_v2_response(  # noqa: SLF001
                canonical_json(value), "request"
            )
        assert raised.value.code == "MODEL_RESPONSE_INVALID"

    with pytest.raises(BrainError) as raised:
        runtime._parse_create_plan_v2_response(  # noqa: SLF001
            b'{"schema_version":5,"schema_version":5}', "request"
        )
    assert raised.value.code == "MODEL_RESPONSE_INVALID"


def test_v2_decoder_projection_and_worker_identity_are_pinned_without_generation() -> None:
    authoritative = qualified_runtime._json(qualified_runtime.CREATE_PLAN_V2_SCHEMA)
    projected = qualified_runtime._create_plan_v2_decoder_schema(authoritative)
    assert (
        qualified_runtime._canonical_hash(authoritative)
        == qualified_runtime.CREATE_PLAN_V2_SCHEMA_SHA256
    )
    assert (
        qualified_runtime._canonical_hash(projected)
        == qualified_runtime.CREATE_PLAN_V2_DECODER_SCHEMA_SHA256
    )
    assert CREATE_DELTA_PLAN_BODY_V2_SCHEMA_SHA256 == qualified_runtime.CREATE_PLAN_V2_SCHEMA_SHA256
    assert (
        mlx_runtime.CREATE_PLAN_V2_WIRE_VERSION
        == qualified_runtime.CREATE_PLAN_V2_WIRE_VERSION
        == 5
    )
    assert (
        qualified_runtime._prefixed_sha256(Path(qualified_runtime.__file__))
        == mlx_runtime.WORKER_SHA256
    )
    assert mlx_runtime.WORKER_MAX_TOKENS == 512
    assert set(projected) == {"type", "additionalProperties", "required", "properties", "$defs"}
    assert set(projected["properties"]) == {"o"}
    assert len(projected["$defs"]["operation"]["anyOf"]) == 4
    assert "uniqueItems" in authoritative["$defs"]["requirementHandles"]
    assert "uniqueItems" not in projected["$defs"]["requirementHandles"]
