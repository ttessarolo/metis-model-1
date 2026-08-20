# W1/W4 entry blackboard

## Objective

Close immediate blockers O-001, O-002 and O-004 with evidence, establish the
first benchmark-slice allocation and execute the staged Qwen3.8 MLX-VLM
qualification path. Slice sealing remains a separate fail-closed outcome.

## Acceptance

- O-001 ratifies the canonical Metis language from the pinned source.
- O-002 records held-out families, criticality, denominators and leakage rules.
- A first 30-source allocation is schema-valid with an explicit oracle matrix;
  sealing remains fail-closed on dependency closure, rights and executed oracles.
- O-004 records exact isolated Python/MLX/MLX-VLM pins and CLI evidence.
- W4 proves or blocks load, inference, backward, 10/50/600 iterations,
  save/reload/resume and adapter-off behavior with telemetry.
- No training payload, adapter, checkpoint, optimizer state or dataset enters Git.

## Scope / out of scope

In scope: public pinned model download, isolated W4 dependencies, non-sensitive
qualification fixture, local inference/training, read-only Metis census, W1
benchmark metadata, reports/checksums and immediate decision ratification.

Out of scope: W5 pilot, proprietary corpus materialization, live ARES, secrets,
external publication, model-family substitution, autonomous Metis writes,
commit and push.

## Baseline

- Repository HEAD: `ad7a1169104c22fa8736b7463a93f65ea9f670f8`
- Working tree: W0 foundation changes present and user-authorized; not committed
- Metis source: `a2dde2b191f6b78c2003d74875560da782470968`
- Model: `Qwen/Qwen3.8-27B@1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`
- MLX checkpoint: `mlx-community/Qwen3.8-27B-4bit@3e6447f082e89cc7f0bc6e5441afd38dfce760ff`
- User mandate: close immediate opens and try the path without delay

## Established

- FACT — W0 is locally green with 8/8 tests and an adversarially rechecked
  artifact boundary. `evidence=orchestra/runs/2026-08-20-foundation/BLACKBOARD.md:84`.
- FACT — Metis commit declares language `0.43` and tooling package `0.23.87`.
  `evidence=/Users/tommasotessarolo/Developer/ares-matioska/metis/tooling/src/language/version.ts`.
- FACT — The host is Apple M3 Max / 128 GB unified memory with about 554 GiB free
  at W0 control. This does not prove backward headroom.
- FACT — Qwen3.8 uses `model_type=qwen3_5`; the exact pinned MLX-VLM path is now
  technically qualified within the recorded batch-1 / sequence-128 boundary.
- DONE — O-001 ratified Metis language `0.43` from the pinned source; tooling
  `0.23.87` remains provenance only. `in=3 out=3 distinct=3 gaps=0`.
  `evidence=manifests/decision-register.json;manifests/source-model-revisions.json;command:git show a2dde2b:tooling/src/language/version.ts`.
- DONE — O-002 ratified six benchmark families, criticality and fail-closed
  leakage rules from `197` files / `170` endpoints; the corpus validator reports
  `ERROR: 0`, `WARN: 123`. The 30-source allocation is distinct and contract
  valid, but deliberately not sealed until closure, rights and task-specific
  oracles complete. `evidence=manifests/benchmark-plan.json`.
- DONE — W4 isolated environment pins CPython `3.12.10`, MLX/MLX Metal
  `0.32.1`, MLX-VLM `0.6.15`, Transformers `5.14.0`, Datasets `5.0.1`, Jinja2
  `3.1.6`, NumPy `2.5.2`, safetensors `0.8.0` and psutil `7.2.2`; live
  `mlx_vlm.lora --help` is captured and hashed.
- DONE — The pinned MLX checkpoint downloaded locally at exact revision
  `3e6447f0`; all three weight sizes and SHA-256 hashes match Hub metadata, and
  config asserts `qwen3_5` affine 4-bit. `evidence=artifacts/w4/2026-08-20-qualification/checkpoint-verification.json`.
- FACT — The first backward attempt stopped before forward because Jinja2 was
  absent from MLX-VLM's declared dependencies; the isolated lock now pins
  Jinja2 `3.1.6`. No adapter was produced by the failed attempt.
- DONE — O-004 ratified after strict load, deterministic generation, finite
  backward, 10/50/600 iterations, save/reload and adapter-on/off behavior. The
  600-step run completed in `926.65 s`, peaked at `20.282 GB` Metal and
  `15.724 GiB` process-tree RSS, and left no residual process.
  `evidence=W4-QUALIFICATION.md`.
- DONE — Native resume was correctly classified as adapter-only. The guarded
  local wrapper then proved uninterrupted 4 steps byte-identical to 2 steps plus
  fresh-process resume to 4 for canonical model/optimizer state, adapter and
  config; frontier final audit returned `CLEAN`.
  `evidence=artifacts/w4/2026-08-20-qualification/full-state-bit-exact-report-final.json;W4-QUALIFICATION.md`.
- DONE — Same canonical prompt changed from base `KESTREL` to adapter `QUAL_A`;
  a fresh adapter-off process returned the exact base hash. This is technical
  behavior evidence, not Metis semantic uplift.
- DONE — Post-closure L0 recheck reran the current comparator against the final
  uninterrupted and split checkpoints. It returned `status=pass`, global step
  `4`, loss `5.221731185913086` and the same final report SHA-256
  `504508b63f941fca27c4d98b9c1a69b5265527a582e26619daa8ea9f57a96f25`.

## Open

- OPEN — W1 slice sealing: dependency closure, data-rights review and
  task-specific oracle execution. This does not reopen ratified O-002.
- OPEN — W5 decisions O-003, O-005 and O-006; W5 itself was outside this wave
  and is not authorized by the W4 technical verdict.
- STOP — Any changed runtime/model/wrapper pin, NaN/Inf, OOM, abnormal memory
  growth, corrupted output or failed save/reload/resume reopens the relevant
  qualification rather than inheriting this verdict.

## Ruled out

- Closing a decision before its required evidence exists.
- Using global Conda or floating package/model revisions.
- Reducing the 600-iteration exit contract silently.
- Treating a short smoke test as W4 qualification.
- Uploading model, adapter, data or reports externally.

## Outcome

COMPLETED — O-001, O-002 and O-004 are ratified; the exact bounded W4 path is
qualified and independently audited. The 30-source W1 allocation remains
deliberately unsealed on its recorded dependency, rights and oracle blockers.
