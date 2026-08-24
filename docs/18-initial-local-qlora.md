# Initial local QLoRA v1

Status: **PREIMAGE IMPLEMENTED — NO DATASET, MODEL, OR PACKAGE OUTPUT YET**.

`INITIAL_LOCAL_QLORA_V1` is a new, local, bounded research wave. It neither
reopens the catalog-maintenance runs nor changes their sealed `DIAGNOSE 4/8`
evidence. The four ambiguous successor author cases remain excluded diagnostic
evidence.

## Authority and pinned implementation

This is one initial adapter, not O-010's `DELTA_QLORA` path: no previous Model 1
adapter exists. The mandate is a narrow waiver of O-011's historical `NO_TRAIN`
closure for this one fresh public-synthetic experiment. It does not amend O-003,
O-010, O-011, the Accuracy-99 plan, or historical evidence.

The sole base is Qwen3.8 27B 4-bit at revision
`3e6447f082e89cc7f0bc6e5441afd38dfce760ff`, with CPython 3.12.10, MLX 0.32.1,
and MLX-VLM 0.6.15. The executable catalog implementation is the read-only
Metis pin `5e112f9148f40e7e792052e896c5a9efe8eaf0a2`, tree
`41c7a2b6890fa42d8123bd93f6560d0b9bfae8af`, against catalog-surface revision
`1f7eaae9d803edc90f51ff492ea443f18570015e`. The earlier `a2dde` source is not
an eligible oracle because it does not parse the required `enum(N)`/`open`
surface. Catalog values remain retrieval-owned and are forbidden from adapter
targets.

After the preceding seal, this authority allows only public-synthetic local
materialization/oracle work, local inference, one rank-8 QLoRA configuration,
local adapter packaging, and Git metadata commit/push. Network, downloads,
live or tenant data, credentials or `.env`, privilege, services, promotion, and
Accuracy-99 remain denied throughout dataset, training, and evaluation.

The earlier user authority also permits one post-verdict S3 transfer, but only
of the sealed adapter package. That phase is an explicit exception to the
network ban: its published backup preimage must bind one concrete transfer
profile, one bucket, a versioned prefix, the local package hash, and a local
restore/hash receipt. It may not upload base weights, datasets, optimizer state,
prompts, raw output, logs, or credentials. It does not authorize a service,
promotion, a retry, or another training run.

The bound transfer identity is AWS account `670565864033`, CLI profile
`MetisModel1BackupWriter-670565864033`, region `eu-west-1`, private versioned
bucket `metis-model-1`, and exactly one object at
`metis-model1/<archive-sha256>/metis-model1-adapter.tar`. The digest component is
derived from the completed local archive, so no alternate key is permitted.
The post-package procedure must prove an empty exact prefix, use one AES256
`put-object` without ACL changes, verify `HeadObject` metadata/version, download
to a fresh temporary directory, rerun `verify-archive`, and leave a redacted
local receipt. AWS CLI may use that named SSO profile; L0 never opens `.env`,
AWS configuration/cache files, keychains, tokens or credential values.

## Exclusions and data

`manifests/initial-local-qlora-exclusions-v1.json` hashes and identifies the
four ambiguous successor author fixtures without copying prompt, model-output,
or oracle text. Every successor prompt/output/oracle/expected source and every
B12 raw model output is forbidden as a train, dev, checkpoint-selection, or
package input. B12 remains frozen evaluation-only; its existing base receipt
may be compared terminally, but it cannot select data or steps.

The dataset is exactly 64 train plus 16 dev examples. Train has at least 16
examples in each F-1/F-2/F-3 family and 16 canonical replay examples; dev is
F-1/F-2/F-3 = 5/5/6. Every example is fresh public-synthetic and
provenance-bound, every target is oracle-accepted, and no assistant target
contains a catalog-value payload. Split and leakage groups are assigned before
derivation and never cross train, dev, or B12. Train and dev use disjoint
template roots. The pinned public-synthetic oracle intentionally describes only
`public.video`, so held-out diversity changes field names, field order, indices,
identifiers and domain cardinalities while retaining that required catalog name.
Because the pinned describe projection deliberately redacts/normalizes value
payloads, F-3 also applies the ratified surface invariant directly: a declaration
that combines external `enum(N)` with inline `values [...]` is rejected even if
the describe projection would otherwise erase the forbidden suffix.
The complete staged roster, hashes, provenance envelopes, deterministic
reconstruction and both registered F-3 rejection shapes are verified before the
staging directory is atomically published as the fixed dataset path.

## One-run evaluation and training

There is no invented B24/D24 phase. The frozen dev16 gets exactly one
adapter-off baseline before training, then the same dev16 is replayed at each
step gate solely to decide continuation. QLoRA is exactly one configuration:
rank 8, alpha 16, learning rate 1e-5, seed 17, sequence 1024, batch 1,
accumulation 1, and dropout 0. It reaches step 25; step 50 needs at least one
dev semantic gain over adapter-off, and step 100 needs another gain over step
25. No gain simply ends the run at the current valid checkpoint; it does not
permit another configuration or retry.

The model worker and training process run only in the pinned qualification
virtualenv. Receipt/oracle/package coordination runs in the fixed project
virtualenv; whenever it needs qualification-runtime evidence it invokes the
exact qualification interpreter as a bounded child, which rechecks its own
prefix, Python version, package versions, lock and wrapper. The parent accepts
only the exact one-line JSON proof with empty stderr and a 30-second timeout.
On macOS, MLX custom kernels also require the Metal compiler service to issue a
sandbox extension into the current user's Darwin cache. Evaluation, B12 and
training therefore admit writes and `file-issue-extension` only for the two
canonical aliases of that per-user cache: writes are restricted to
`com.apple.metal` and `com.apple.metalfe`, while extension issuance is scoped to
their `C` parent. Network access and credential/keychain reads remain denied. A
real `mx.fast.metal_kernel` canary must pass inside each sandbox before a model
worker or optimizer is launched.

After dev is consumed, the independent terminal check replays the frozen B12
once with the adapter and compares it only to its existing frozen base result.
It establishes no-regression/uplift evidence and never feeds training or
selection. A technically valid, non-regressing adapter without demonstrated
uplift is truthfully `LOCAL_ADAPTER_EXPERIMENTAL`; it is not forced to
`STOP_NO_UPLIFT`. A B12 regression, critical semantic veto, invented/unrelated
change, NaN/Inf, OOM, identity/checkpoint drift, adapter-off restore failure, or
cap breach stops the wave.

Caps are one configuration, no rework, at most 100 optimizer steps, four
checkpoints, four hours, 8 GiB new artifacts, and 110 GB peak Metal.

## Pre-output state machine

```text
contract_preimage_published
  -> dataset_materialized
  -> dataset_training_freeze_published
  -> base_dev16_consumed
  -> qlora_step25
  -> optional_qlora_step50_or100_if_dev_gain
  -> adapter_dev16_consumed
  -> frozen_b12_adapter_replay
  -> local_verdict
  -> LOCAL_ADAPTER_UPLIFT | LOCAL_ADAPTER_EXPERIMENTAL | STOP_B12_REGRESSION | STOP_TECHNICAL
  -> local_package (retained local verdicts only)
  -> s3_adapter_backup (one sealed package only)
```

Each seal binds Git head/tree, implementation/oracle/materializer identities,
exact inputs, a single fresh ignored output path, and the one authorized phase.
Existing directories, alternate paths, stale receipts, symlinks, nonregular
files, hard links, raw tracked output, exclusion hits, altered bound inputs, or
a missing required publication fail closed. A correction after any model output
or optimizer step requires a fresh namespace and mandate. Pre-output tooling
may be corrected and republished only while every fixed model/training output
path remains absent.

The observed `run-v1` baseline exposed a P0 verifier defect before any optimizer
marker, checkpoint, telemetry, or training state existed: a complete but imperfect
baseline was incorrectly treated as invalid evidence. Recovery therefore preserves
the published v1 freeze and immutable three-file baseline, publishes a v2 freeze
against the corrected verifier, and imports those exact bytes atomically into the
fresh `run-v2` namespace. The import performs zero model calls and zero optimizer
steps; pinned-oracle replay verifies the existing evidence only and does not consume
the dev set a second time. Adapter gates retain their zero-critical/zero-invented
veto.

The supervisor runs with a closed environment and network-denied sandbox. It
authorizes every phase from reopened dev evidence before writing the no-retry
marker, measures cumulative optimizer time with a monotonic clock, enforces the
8-GiB cap before launch, live and before/after the phase receipt, and retains
the exact manifest plus four-file identity of every saved full-state checkpoint.
Step 75 is retained only as verified resume state on the path to step 100; it is
never an eligible selection gate.

## Packaging and verification

The local package contains only adapter weights/config, the runtime lock,
immutable manifest/checksums, and redacted dataset, training, selection,
adapter-off-restore and terminal-evaluation receipts. It excludes base weights,
dataset rows, optimizer/resume state, prompts, model/oracle text, logs,
credentials, and `.env`. Portable verification revalidates the retained
training/dev/B12 semantics, adapter config, runtime lock and receipt links. The
deterministic USTAR archive is restored through an exact regular-file roster in
a fresh directory and the restored package is verified before any S3 call. It
is never tracked in Git. The S3 transfer is a single copy of that sealed archive
and must write no other object.

Before any execution:

```bash
uv run pytest -q tests/test_initial_local_qlora_contract.py
uv run metis-model1 validate-foundation
git diff --check
```

The later materializer, base dev16, preimage-bound QLoRA supervisor, B12 replay,
packager, and transfer commands require their own pre-output verifier tests
before invocation. The supervisor records a no-retry start marker, enforces the
single command/configuration, cumulative four-hour/8-GiB/four-checkpoint caps,
and verifies each retained full-state checkpoint before the phase can advance.

The executable sequence uses the dependency-specific interpreters directly:

```bash
NODE_PATH="$(command -v node)"
.venv/bin/python src/metis_model1/initial_local_qlora_dataset.py materialize \
  --metis-root /Users/tommasotessarolo/Developer/ares-matioska/metis \
  --node-path "$NODE_PATH"
.venv/bin/python src/metis_model1/initial_local_qlora_dataset.py verify
.venv/bin/python src/metis_model1/initial_local_qlora_train.py freeze
## Commit and push the generated v2 freeze before importing the sealed baseline.
.venv/bin/python src/metis_model1/initial_local_qlora_train.py import-baseline
.venv/bin/python src/metis_model1/initial_local_qlora_train.py verify-freeze
.venv/bin/python src/metis_model1/initial_local_qlora_train.py run --target 25
```

Base/step evaluation, continuation, selection, adapter-off restoration, B12 and
packaging use the fixed paths exposed by
`initial_local_qlora_runtime.py --help`; step 50/100 commands are invoked only
when the preceding semantic gate authorizes them. No alternate output path or
second configuration is permitted. MLX generation and training use
`qualification/.venv/bin/python`; dataset/oracle scoring and the B12 coordinator
use `.venv/bin/python`, with B12 spawning its pinned qualification worker.
