# Model 1 initial local QLoRA v1 brief

## Mandate

Deliver one real, separately loadable Metis adapter for the pinned local
Qwen3.8 checkpoint. The user explicitly resumed the blocked Model 1 goal on
2026-08-24 and required the fine-tuned artifact to be completed without waiting
for another planning cycle.

This is a new, bounded `INITIAL_LOCAL_QLORA_V1` wave. It does not rewrite the
historical W5-XS `MODEL1_USABLE_LOCAL_NO_TRAIN` verdict and it does not relabel
the catalog successor `DIAGNOSE 4/8`. The adapter can be delivered as an
experimental local artifact even when it does not earn an uplift or promotion
claim; every such nonclaim must remain explicit.

## Preflight

- repository: `/Users/tommasotessarolo/Developer/metis-model-1`;
- baseline: `7b68b33` plus one unrelated concurrent blackboard hunk;
- catalog source/oracle pin: Metis `0.43` implementation
  `5e112f9148f40e7e792052e896c5a9efe8eaf0a2`, tree
  `41c7a2b6890fa42d8123bd93f6560d0b9bfae8af`, for surface revision
  `1f7eaae9d803edc90f51ff492ea443f18570015e`;
- base checkpoint: `mlx-community/Qwen3.8-27B-4bit` at
  `3e6447f082e89cc7f0bc6e5441afd38dfce760ff`;
- runtime: CPython `3.12.10`, MLX `0.32.1`, MLX-VLM `0.6.15`;
- execution root: ignored `artifacts/initial-local-qlora-v1/`;
- expected output: a hash-addressed adapter package, adapter-off recovery proof,
  redacted evaluation receipts and an honest local verdict;
- verification: focused contract/dataset/runtime tests, dataset receipt replay,
  checkpoint verification, base/adapter evaluation, package hash replay,
  `make check`, then exact Git and the authorized adapter-only S3 object
  identity/restore checks.

The post-verdict backup is pinned to account `670565864033`, profile
`MetisModel1BackupWriter-670565864033`, bucket `metis-model-1` in `eu-west-1`,
and the sole key
`metis-model1/<archive-sha256>/metis-model1-adapter.tar`. The upload must be
absent-before-write, versioned, AES256, downloaded to a fresh directory and
reverified; no second S3 object is allowed.

The catalog-value maintenance surface remains retrieval-owned and is excluded
from the weights in this initial adapter. The four underdetermined successor
author cases and every prior raw model output are forbidden as train/dev input.

## Writable roster

- `docs/18-initial-local-qlora.md`;
- `manifests/initial-local-qlora-plan-v1.json`;
- `manifests/initial-local-qlora-exclusions-v1.json`;
- `schemas/initial-local-qlora-plan.schema.json`;
- `src/metis_model1/initial_local_qlora_dataset.py`;
- `src/metis_model1/initial_local_qlora_runtime.py`;
- `src/metis_model1/initial_local_qlora_b12.py`;
- `src/metis_model1/initial_local_qlora_train.py`;
- their focused tests;
- `src/metis_model1/contracts.py` and `tests/test_contracts.py` for L0
  integration only;
- the active board and session ledger;
- this brief;
- ignored payloads below `artifacts/initial-local-qlora-v1/`.

L91 owns only dataset code/tests, L92 only runtime code/tests, L93 only the
plan/schema/doc/contract test, and L0 owns integration, execution, gates,
commits, pushes, packaging and the final verdict.

The cure audit adds L100/L103 for supervisor and checkpoint identity,
L101/L104 for evidence/B12/package replay, and L102/L105 for preimage,
dataset/oracle and archive adversarial review. These lanes are read-only after
handoff; L0 independently reruns their gates before publication.

## Exclusions

- `.env`, AWS configuration files, keychains, tokens and credentials;
- live ARES or tenant payloads;
- writes to `/Users/tommasotessarolo/Developer/ares-matioska/metis`;
- base weights, datasets, optimizer state, checkpoints or raw outputs in Git;
- network/download during dataset, training or evaluation;
- successor/B12 outputs as training truth;
- promotion, distribution or Accuracy-99 claims.

## Bounded execution

1. Publish the tracked plan, deterministic generator and runtime contract.
2. Materialize and verify exactly 64 train plus 16 dev public-synthetic examples.
3. Publish a redacted dataset receipt and training preimage before model output.
4. Measure adapter-off dev behavior.
5. Run one QLoRA configuration: rank 8, alpha 16, LR `1e-5`, seed 17,
   sequence 1024, batch/accumulation 1, dropout 0, completion-only.
6. Stop first at step 25. Continue to 50 and 100 only after the frozen dev gate
   improves by at least one semantic success at each boundary.
7. Verify finite telemetry, checkpoint hashes, save/reload, adapter-on behavior
   and exact adapter-off restoration; evaluate the frozen B12 surface without
   using it for checkpoint selection.
8. Atomically package the selected adapter with config, hashes, cards and
   rollback instructions, then reopen the deterministic tar, safely restore its
   exact regular-file roster in a fresh directory and replay portable receipt
   semantics. An archival S3 copy may contain only that verified tar, never base
   weights, dataset, optimizer state or raw logs.

Hard caps are four hours of optimizer execution, 110 GB peak Metal, 8 GiB of
new wave artifacts and four published checkpoints. NaN/Inf, OOM, identity
drift, a symlink, cap overflow or failed adapter-off restoration stops training
and preserves the last valid immutable checkpoint.

## Verdicts

- `LOCAL_ADAPTER_UPLIFT`: adapter is technically valid and improves a frozen
  semantic evaluation without a critical regression;
- `LOCAL_ADAPTER_EXPERIMENTAL`: adapter is technically valid and packaged, but
  no uplift claim is earned;
- `STOP_TECHNICAL`: no loadable reproducible adapter can be delivered;
- `STOP_B12_REGRESSION`: the adapter is retained only as rejected evidence
  and is not the default Model 1 path.

None of these is `ACCURACY99_PROMOTED`.
