# Catalog prompt-cure successor wave

Status: **AUTHORIZED STATIC PREIMAGE — NO FREEZE, RUN, OR MODEL OUTPUT YET**.

This is a new, bounded maintenance wave. It follows the immutable catalog
maintenance probe v1, whose single sealed run is consumed and terminal at
`DIAGNOSE 2/8`. It does not amend, reopen, rescore, or otherwise reuse v1's
freeze, ignored run directory, raw attempts, evaluation receipt, or decision.

## 1. Scope and non-claims

The successor tests a prompt and retrieval presentation cure for the observed
base-model failures. It is public-synthetic only, non-statistical,
non-promotional, and one lineage. Its result is not an accuracy denominator,
an external execution attestation, a tenant-data authority, or evidence that a
fine-tuned adapter exists.

The only allowed model is the already qualified Qwen3.8 base with adapter
disabled. Training is always false. A delta QLoRA is not an automatic response
to either outcome: it requires a later, explicit mandate with its own
oracle-clean data, provenance, replay, and selection gates.

Metis remains an external read-only checkout. This wave does not read tenant
payloads, `.env` files, credentials, keychains, live ARES/Metis state, or S3.
It does not download a model, upload an artifact, publish a payload, or change
another repository.

## 2. Fresh eight-case roster and reused retrieval proof

The successor has exactly eight newly authored public-synthetic cases in one
new lineage: four `author`, three `edit`, and one `repair`. Every case receives
a new case ID, semantic root, template ID, fixture path, oracle truth record,
and retrieval binding. Case IDs, roots, templates, prompt text, and expected
sources are disjoint from v1. The successor intentionally revisits the same
six diagnosed failure families; family-level similarity is the point of this
prompt-cure check and is not represented as a new statistical sample.

The roster is deliberately non-statistical. `8/8` can decide only whether this
prompt/retrieval cure avoids a retune for this bounded maintenance surface; it
cannot establish `MODEL1_USABLE_LOCAL`, a population claim, or a promotion.

The retrieval lane was already green in v1 and is not the diagnosed failure.
The successor therefore reuses the immutable, committed public-synthetic v1
retrieval fixture and execution receipt as read-only technical inputs. The
freeze revalidates them against the same pinned Metis revision/tree and binds
their hashes plus the single authorized `video.genre` result. No v1 model
output, attempt, score, expected skeleton, evaluation, or decision is reused.
This is a prompt-only replay policy, not a claim of fresh retrieval evidence.

## 3. Prompt and oracle law

Each prompt begins with a canonical system-role syntax scaffold. The scaffold
requires complete Metis source, the exact language header (`metis 0.43`), one
catalog file, and no explanatory wrapper. It states the catalog-domain law:
external bounded domains use `keyword enum(N)`, open live-index domains use
`keyword open`, and only explicitly tiny stable domains may retain inline
values.

Structural repair feedback is permitted only after a candidate is parsed and
described by the isolated pinned toolchain. Feedback is bounded, normalized,
and non-truth-leaking: it can name a structural failure class such as missing
header, missing `keyword`, invalid domain form, or preserved-field violation.
It must not include an expected complete source, expected normalized skeleton,
oracle target fragment, raw retrieval value, or another case's candidate text.

The tracked public-synthetic fixtures store an executable expected source as
oracle gold. That source is parsed by the pinned toolchain into the normalized
skeleton used for scoring, but it is never sent to the model. Prompt builders
must fail closed if the complete expected source enters any message. Request
text may state the user's semantic constraints and, only for the intentionally
tiny stable domain, its two requested values; it must not spell out the
canonical enum/open fragment being evaluated. An `edit` or `repair` case may
show that fragment inside the supplied invalid legacy source because preserving
and correcting that source is the task itself; this is recorded separately from
request-text leakage and never substitutes for the normalized oracle. Generated
text and full attempt content remain only in the fresh ignored run directory.
Tracked terminal evidence contains hashes, counts, redacted failure codes, and
self-hashes.

## 4. Required fresh paths and bindings

The implementation must use a new namespace, without defaults or fallbacks to
the v1 paths:

- manifest: `manifests/catalog-maintenance-successor-probe-v1.json`;
- schemas: `schemas/catalog-maintenance-successor-{probe,freeze,evaluation,decision}.schema.json`;
- reused retrieval inputs: `manifests/catalog-retrieval-public-synthetic-v1.json`
  and `manifests/catalog-retrieval-execution-v1.json`;
- freeze: `manifests/catalog-maintenance-successor-freeze-v1.json`;
- evaluation and decision: `manifests/catalog-maintenance-successor-{evaluation,decision}-v1.json`;
- fixtures: `fixtures/catalog-maintenance/successor-v1/`;
- ignored one-use output: `artifacts/catalog-maintenance-successor-v1/`.

The successor preimage is a newly published commit `P`, distinct from every
v1 preimage and freeze commit. `P` contains the complete static successor
closure: manifest/schema, fixture hashes, retrieval/oracle implementation,
worker identity, sandbox policy, and tests. The freeze is generated from `P`,
committed and published byte-for-byte before the worker starts. It binds the
exact preimage commit/tree, each closure file's Git blob and worktree bytes,
the revalidated retrieval receipt, Qwen/runtime/checkpoint identities, the sole
output path, ordered eight-case roster, and `training_authorized=false`.

Both freeze and runner reject a pre-existing output directory. At run time, the
worker accepts only the frozen successor path, verifies that the preimage is an
ancestor of the published execution HEAD, rechecks all sealed input hashes, and
creates the directory once. The one authorized evaluator accepts exactly the
successor report, stderr log, and one attempts file per frozen case; it verifies
the recorded text hashes and final score projection, recomputes only the fixed
gate arithmetic, and emits the redacted receipts. An extra, missing, linked, or
old-v1 file is a hard failure. Later terminal verification is receipt-only and
does not reopen the ignored attempts. If publication is interrupted after the
evaluation receipt, only that valid self-hashed receipt may deterministically
produce its missing decision; a decision without its evaluation fails closed.
No second model run, retry run, alternate directory, post-hoc relabeling, or
alternative score reconstruction is permitted.

## 5. State machine and decision

```text
v1_maintenance_diagnosed (immutable and consumed)
  -> successor_spec_ready (eight fresh static cases; no output)
  -> successor_retrieval_reverified (pinned public-synthetic v1 receipt)
  -> successor_preimage_published (P only; no output)
  -> successor_sealed_pre_output (freeze committed and published)
  -> successor_run_consumed (one ignored directory; output exists)
  -> successor_evidence_verified (redacted receipt and decision bound)
  -> NO_RETRAIN_PROMPT_CURE | DIAGNOSE (terminal)
```

`NO_RETRAIN_PROMPT_CURE` is permitted only when the exact ordered roster is
`in=8 out=8 distinct_case_ids=8 distinct_roots=8 gaps=0`, all eight semantic
oracles pass, and critical failure, invented-value, legacy-inline, and
retrieval-error counters are all zero. It is an explicit no-retune result for
this maintenance cure only; it does not authorize training, promotion, or a
broader model claim.

Any different count, a veto, a missing or changed preimage/freeze/receipt, a
run-path collision, an extra output, or a truth-leak terminates at `DIAGNOSE`.
Neither terminal state changes `training_authorized=false`. Delta QLoRA remains
blocked until a future explicit mandate says otherwise.

## 6. Verification commands

```bash
# Static manifest/schema/oracle and non-leakage checks; no inference.
uv run pytest -q tests/test_catalog_maintenance_successor_manifest.py \
  tests/test_catalog_maintenance_successor.py \
  tests/test_catalog_maintenance_successor_evidence.py tests/test_contracts.py

# Reverify the pinned public-synthetic retrieval contract; no model worker.
uv run pytest -q tests/test_catalog_retrieval.py tests/test_catalog_retrieval_refresh.py

# Generate then independently verify the no-output freeze for published P.
uv run python -m metis_model1.catalog_maintenance_successor freeze
uv run pytest -q tests/test_catalog_maintenance_successor.py

# The sole permitted model invocation, only after the previous two commands pass.
uv run python -m metis_model1.catalog_maintenance_successor run

# Redacted receipt/decision verification and repository handoff gate.
uv run python -m metis_model1.catalog_maintenance_successor_evidence build
uv run pytest -q tests/test_catalog_maintenance_successor_evidence.py tests/test_contracts.py
make check
```

The single-run command remains blocked until the static implementation and
revalidated retrieval inputs are committed and published, then the generated
freeze is independently audited, committed, and published. Running it earlier,
or substituting a v1 run artifact, is outside this authorization.
