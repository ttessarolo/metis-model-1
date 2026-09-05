from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from metis_model1 import brain_mlx_runtime as mlx_runtime
from metis_model1 import initial_local_qlora_runtime as qualified_runtime
from metis_model1.brain_create_plan import CREATE_DELTA_PLAN_SCHEMA_SHA256
from metis_model1.brain_mlx_runtime import MlxBrainModelRuntime, serialize_create_plan_messages
from metis_model1.brain_model_runtime import CreatePlanRequest
from metis_model1.brain_protocol import BrainError


def _request() -> CreatePlanRequest:
    return CreatePlanRequest(
        instructions=(
            "Voglio una riga di film simili.",
            "Usa video e dammi 24 risultati.",
        ),
        generation=0,
        context_revision="sha256:" + "a" * 64,
        semantic_revision="sha256:" + "b" * 64,
        surface_revision="sha256:" + "c" * 64,
        target_ref="hostref:target:" + "d" * 32,
        basis_ref=None,
        requirement_refs=("hostref:requirement:" + "e" * 32,),
        authority_surface={
            "schema_version": 1,
            "requirements": [
                {
                    "ref": "hostref:requirement:" + "e" * 32,
                    "roles": ["requirement"],
                    "label": "24 risultati",
                }
            ],
            "grants": [],
        },
    )


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
        " if request.get('schema_version') != 4 or request.get('operation') != 'plan_create':\n"
        "  sys.exit(3)\n"
        " plan={'schema_version':1,'contract_id':'metis-brain-create-delta-plan/v1',"
        "'mode':'initial','context_revision':'sha256:'+'a'*64,"
        "'semantic_revision':'sha256:'+'b'*64,'surface_revision':'sha256:'+'c'*64,"
        "'target_ref':'hostref:target:'+'d'*32,'basis_ref':None,"
        "'requirements':['hostref:requirement:'+'e'*32],'operations':["
        "{'ordinal':0,'kind':'endpoint.create','depends_on':[],"
        "'requirement_refs':['hostref:requirement:'+'e'*32],"
        "'endpoint_ref':'hostref:endpoint:'+'f'*32}]}\n"
        " print(json.dumps({'schema_version':4,'request_id':request['request_id'],"
        "'operations':plan['operations'],"
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


def test_create_plan_wire_is_json_only_and_contains_no_source_authority() -> None:
    messages = serialize_create_plan_messages(_request())
    assert [item["role"] for item in messages] == ["system", "user", "user"]
    assert "never return Metis" in messages[0]["content"]
    assert "AUTHORITY_SURFACE_JSON" in messages[-1]["content"]
    encoded = messages[-1]["content"].split("\n", 1)[1]
    payload = json.loads(encoded)
    assert payload["schema_sha256"] == CREATE_DELTA_PLAN_SCHEMA_SHA256
    assert payload["instructions"] == list(_request().instructions)
    assert payload["generation"] == 0
    assert payload["basis_ref"] is None
    assert payload["requirement_refs"] == list(_request().requirement_refs)
    lowered = encoded.casefold()
    for forbidden in (
        "previous_source",
        "source_path",
        "endpoint_template",
        "reference_endpoint",
        "golden",
        "metis 0.43",
    ):
        assert forbidden not in lowered


def test_create_plan_wire_is_deterministic_and_rejects_wrong_type() -> None:
    first = serialize_create_plan_messages(_request())
    second = serialize_create_plan_messages(_request())
    assert first == second
    with pytest.raises(BrainError) as raised:
        serialize_create_plan_messages(object())  # type: ignore[arg-type]
    assert raised.value.code == "MODEL_INPUT_INVALID"


def test_create_plan_uses_the_warm_model_worker_and_returns_typed_json(
    runtime: MlxBrainModelRuntime,
) -> None:
    runtime.warmup()
    assert runtime._process is not None  # noqa: SLF001 - lifecycle invariant under test
    pid = runtime._process.pid  # noqa: SLF001

    candidate = runtime.plan_create(_request())

    assert candidate.generator == "model_create_plan"
    assert candidate.plan["contract_id"] == "metis-brain-create-delta-plan/v1"
    assert candidate.model_revision == "model-revision"
    assert candidate.adapter_sha256 == "sha256:" + "a" * 64
    assert candidate.metrics["cache_mode"] == "disabled"
    assert candidate.metrics["finish_reason"] == "stop"
    assert runtime._process is not None  # noqa: SLF001
    assert runtime._process.pid == pid  # noqa: SLF001
    assert runtime._process_requests == 1  # noqa: SLF001


def test_create_plan_rejects_truncated_or_identity_mismatched_response(
    runtime: MlxBrainModelRuntime,
) -> None:
    valid = {
        "schema_version": mlx_runtime.CREATE_PLAN_WIRE_VERSION,
        "request_id": "request",
        "operations": [
            {
                "ordinal": 0,
                "kind": "endpoint.create",
                "depends_on": [],
                "requirement_refs": ["hostref:requirement:" + "e" * 32],
                "endpoint_ref": "hostref:endpoint:" + "f" * 32,
            }
        ],
        "model_revision": "model-revision",
        "adapter_sha256": "sha256:" + "a" * 64,
        "schema_sha256": CREATE_DELTA_PLAN_SCHEMA_SHA256,
        "decoder_schema_sha256": qualified_runtime.CREATE_PLAN_DECODER_SCHEMA_SHA256,
        "decoder": qualified_runtime.CREATE_PLAN_DECODER,
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
    for key, replacement in (
        ("finish_reason", "length"),
        ("schema_sha256", "sha256:" + "0" * 64),
        ("cache_mode", "prefix"),
        ("cached_tokens", 1),
    ):
        value = {**valid, key: replacement}
        if key == "cached_tokens":
            value["cache_hit"] = True
            value["uncached_prompt_tokens"] = 29
        with pytest.raises(BrainError) as raised:
            runtime._parse_create_plan_response(  # noqa: SLF001
                json.dumps(value).encode("utf-8"), "request", _request()
            )
        assert raised.value.code == "MODEL_RESPONSE_INVALID"


def test_create_plan_rejects_duplicate_json_members(runtime: MlxBrainModelRuntime) -> None:
    with pytest.raises(BrainError) as raised:
        runtime._parse_create_plan_response(  # noqa: SLF001
            b'{"schema_version":4,"schema_version":4}', "request", _request()
        )
    assert raised.value.code == "MODEL_RESPONSE_INVALID"


def test_create_plan_decoder_projection_is_pinned_and_keeps_host_schema_authoritative() -> None:
    authoritative = qualified_runtime._json(qualified_runtime.CREATE_PLAN_SCHEMA)
    projected = qualified_runtime._create_plan_decoder_schema(authoritative)

    assert (
        qualified_runtime._canonical_hash(authoritative)
        == qualified_runtime.CREATE_PLAN_SCHEMA_SHA256
    )
    assert (
        qualified_runtime._canonical_hash(projected)
        == qualified_runtime.CREATE_PLAN_DECODER_SCHEMA_SHA256
    )
    assert "oneOf" in authoritative["properties"]["operations"]["items"]
    assert "uniqueItems" in authoritative["properties"]["requirements"]
    assert len(projected["properties"]["operations"]["items"]["anyOf"]) == 19
    assert set(projected["properties"]) == {"operations"}

    decoder_keys: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            decoder_keys.extend(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(projected)
    assert "oneOf" not in decoder_keys
    assert "uniqueItems" not in decoder_keys
    assert "unevaluatedProperties" not in decoder_keys
    assert "allOf" not in decoder_keys


def test_create_plan_worker_strict_json_rejects_duplicate_or_non_object() -> None:
    for raw in ('{"x":1,"x":2}', "[]", '{"x":NaN}'):
        with pytest.raises(qualified_runtime.RuntimeContractError):
            qualified_runtime._strict_json_object(raw, label="CREATE plan generation")
