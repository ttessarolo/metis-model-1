# Metis Brain: local latency and isolation

Status: **implemented in the current local-latency wave; live performance scope
remains bounded**.

## Problem

The installed Mac demo was technically correct but too slow for interactive
use. The first clarification was observed at about 56 seconds in the earlier
VS Code smoke. Its work completed before the MLX worker started, so that delay
was retrieval/toolchain cold start, not model inference. Cold semantic
projection and each compile also rebuilt an isolated Metis tree, copied about
199 MB / 17k `node_modules` entries, and repeated the full pin checks. Model
generation was lazy, serial, capped at 512 tokens, and did not expose enough
telemetry to distinguish end-of-sequence from length-cap termination.

This wave reduces repeated local work while preserving the reviewed grounding,
pinned compiler, qualified Qwen3.8-27B adapter, and no-Apply boundary.

## Architecture

The Brain process owns one `PinnedMetisAuthority` shared by the compiler and
schema-2 semantic retriever.

1. The authority resolves and verifies the pinned Metis revision, runner,
   Node runtime, and dependency digest. It archives the exact Git revision,
   copies the verified `node_modules` tree once, verifies the copy, installs the
   pinned runner, and removes write bits from the resulting private capsule.
   Identity and runner checks are repeated at job boundaries; a changed capsule
   fails closed.
2. Each retrieval or compile operation creates a fresh bounded temporary job
   overlay under the authority's private jobs directory. Brain materializes
   only the immutable tenant snapshot and, for compilation, the candidate into
   that overlay. Sibling jobs receive different overlays and cannot read one
   another.
3. The sandbox explicitly grants read access to the read-only authority and
   the current job overlay (plus the pinned Node binary), while denying file
   writes and network access. The runner receives no live tenant path; source
   and receipts remain snapshot-bound and redacted according to the existing
   contract.
4. Retrieval may cache the normalized projection by snapshot, semantic-source,
   and toolchain revisions. The cache does not change authority or tenant
   semantics.

This is one process-private read-only authority capsule, not one copy per
turn. The capsule is verified when the service wires it and is materialized
lazily once, on the first job. The per-job overlay is the only writable area
used for tenant/candidate materialization.

## Deterministic create fast path

For a fully reviewed, finite, create-only request, Brain may serialize the
grounding directly through `grounded_renderer`. This is a transparent
deterministic renderer, not an assertion that MLX generated the source. It
still passes the exact candidate-grounding checks and the pinned compiler
before a Draft is returned; the fast path makes zero model calls.

Eligibility is exact and fail-closed. All of the following must hold:

- the request and target are both `create`, with no base hash;
- the endpoint and catalog names are canonical qualified names, with exactly
  one reviewed catalog;
- grounding is `resolved`, with no unresolved concepts or remaining
  candidates;
- every selection is from that catalog, uses a supported `keyword` field and
  `multi`/`ordered` modifiers, and has a finite `inline` or `enum` domain;
- every selected literal is present in a reviewed projected value set, and the
  projected field metadata exactly matches the reviewed selection;
- the Metis language, context revision, semantic revision, and toolchain
  binding match the admitted session, and the exact qualified catalog identity
  is retained in the emitted `from` source;
- the output contract has no fallback and an exact supported `take` contract
  (count or explicitly requested page form).

Edits/refinements, open domains, unresolved or ambiguous concepts, unsupported
types/modifiers, non-canonical surfaces, existing fallback behavior, and any
incomplete or unreviewed context do not qualify. Such a request remains on the
qualified model path where supported, or fails closed; it is never silently
rewritten by the renderer.

Candidate adjudication also rejects an implicit `from all` scope and any
top-level finite predicate placed outside the one authorized endpoint `take`.
These surfaces cannot be used to smuggle an ungrounded business rule past the
finite-value comparison.

## Qualified model path and telemetry

Requests outside the renderer retain Qwen3.8-27B with the sealed adapter and
the bounded repair budget. Before serialization, Brain projects the tenant
context to the reviewed fields selected by grounding plus fields already
referenced by the source being edited. It drops unrelated catalog fields and
whole-file endpoint templates from the model prompt, while preserving catalog,
tenant, context, semantic, and toolchain revisions. The pinned grammar card is
likewise projected to the endpoint-authoring, catalog-domain, condition, block,
and standard-library sections; the complete reference hash remains the source
authority.

The worker now reports bounded numeric telemetry:
load and generation milliseconds, prompt/generation/cached token counts,
prompt and generation rates, peak Metal memory, and `finish_reason` restricted
to `stop` or `length`. The runtime validates the complete shape and bounds
before exposing it in proposal identity. No prompt, source context, hidden
chain-of-thought, or internal reasoning is exposed.

The 512-token cap remains unchanged. The measured baseline stopped normally
after 86 tokens, so reducing that cap would not address the observed delay.
Session-scoped KV/prompt caching is not introduced in this wave: its revision
and invalidation contract remains a separate optimization. One representative
edit/refine is measured below, but repair, open-domain, and other complex
families are **not comprehensively claimed fast** until their benchmark matrix
is run.

## Public progress contract

The event stream exposes only allow-listed phase names, labels, sequence data,
and bounded metrics. Started/completed events cover retrieval, inference,
compile, and bounded repair; completed events include `duration_ms` where
available. The terminal envelope remains the authoritative proposal/validation
result. Public progress contains phase duration, not prompts, tenant values
beyond the existing proposal contract, source internals, or chain-of-thought.

## Lifecycle and cleanup

Authority jobs are context-managed. On job exit the overlay is removed and the
authority is checked again; an active job prevents authority close. Service
shutdown stops the HTTP/reaper and turn workers, closes the model, clears and
closes semantic retrieval, closes the compiler/authority, and removes the
private capsule and job root. Cleanup is idempotent and confined to Brain's
runtime directories. A failed construction also closes every component that
was already created.

## Safety invariants

- The tenant is read-only; compile receipts assert `tenant_modified: false`,
  and Apply remains a separate guarded client action.
- Session snapshots, semantic revisions, toolchain bindings, and stale guards
  bind retrieval, rendering, compilation, and publication to one context.
- The compiler remains pinned and sandboxed with network and writes denied;
  no remote, Ollama, model-family downgrade, credential, `.env`, Keychain, or
  live-tenant fallback is introduced.
- The renderer is permitted only from reviewed finite grounding. Compilation
  is necessary but does not by itself prove semantic correctness.
- Overlays, caches, model telemetry, and public events are bounded; no
  persistent conversational memory or training data is created by this wave.

## Measured read-only live results

The following Mac measurements are read-only observations; no tenant was
modified and no Apply was performed.

| Flow | Total | Public phase timings |
|---|---:|---|
| Cold clarification | 11073 ms | clarification completed before model inference |
| Post-answer proposal | 1574 ms | retrieval 861 ms; compile 696 ms |
| Cold one-turn explicit request (`24` total), final qualified source | 11067 ms | retrieval 10451 ms; compile 602 ms |
| Installed VS Code `v0.23.97`, fresh extension host and Brain child | 31 s | compiled Draft visible; no Apply |
| Qualified 27B baseline before prompt projection | 153852 ms generation wall | 17240 prompt tokens; 86 generated; `stop`; load 3493 ms |
| Qualified 27B edit/refine after final prompt projection | 34319 ms generation wall | 3700 prompt tokens; 72 generated; `stop`; compile 781 ms |

The fast-path proposal observations reported `generation_strategy` as
`grounded_renderer`, `model_loaded` as `false`, `compile_clean` as `true`, and
`tenant_modified` as `false`. `model_loaded: false` is evidence that these
grounded-renderer runs made no model call; it is not a speed claim for the
qualified 27B path.

For the edit/refine measurement, the candidate changed the requested total
from 24 to 12, passed exact finite grounding, passed the pinned compiler, and
reported `tenant_modified: false`. The prompt payload dropped from about 68.7
KB (23.5 KB system plus 45.2 KB user/context) to about 14.5 KB (9.4 KB system
plus 5.1 KB user/context). This is the measured reason the qualified-model turn
moved from roughly 154 seconds to roughly 34 seconds; neither weights nor token
cap changed.

The installed VS Code smoke used the native `@metis` participant and produced
this exact technical core in a visible Draft:

```metis
take 24 from @play-demo.video {
  include where {
    @tipologia is "Film"
    @paesiorigine in ["ITALIA", "Italia", "italia"]
  }
  return response.default
}
```

The extension reported `31 s` from a freshly reloaded extension host and Brain
child to the compiled proposal. `Applica` was not pressed and the tenant stayed
Git-clean on `main`. The Brain HTTP process remained alive, but no MLX worker
was present after the smoke: this is independent process-level evidence that
the deterministic path made zero model calls.

## Warm-runtime direction

The current MLX worker is lazy: the first model-required turn starts it, loads
Qwen and the adapter once, and the same process is reused for up to 120
requests or until Brain closes or the worker fails. Therefore Model 1 is warm
*after* its first real model turn, but is not prewarmed merely because Brain or
a fast-path session is running.

An always-warm demo profile is feasible, but it must be explicit and
observable: start Brain eagerly, build the pinned authority/catalog projection
in the background, prewarm the MLX worker, expose readiness in health, and keep
the worker until Brain exits (with bounded safe recycling). This removes the
roughly 1.4–3.5 second measured worker-load cost. It does not eliminate prompt
prefill: session-scoped prompt/KV caching, bound to context and semantic
revisions and invalidated on any relevant change, is the separate optimization
with the larger potential benefit for refinements.

## Verification

Use synthetic fixtures and the already authorized local pin only; do not put
credentials, tokens, `.env` files, or tenant payloads in commands or artifacts.

```bash
uv run pytest -q \
  tests/test_brain_mlx_runtime.py \
  tests/test_brain_orchestrator.py \
  tests/test_brain_tools.py \
  tests/test_brain_grounded_renderer.py
uv run ruff check src/metis_model1/brain_mlx_runtime.py \
  src/metis_model1/brain_model_runtime.py \
  src/metis_model1/brain_orchestrator.py \
  src/metis_model1/brain_tools.py \
  src/metis_model1/brain_grounded_renderer.py
uv run ruff format --check src/metis_model1/brain_mlx_runtime.py \
  src/metis_model1/brain_model_runtime.py \
  src/metis_model1/brain_orchestrator.py \
  src/metis_model1/brain_tools.py \
  src/metis_model1/brain_grounded_renderer.py
make check
git diff --check -- docs/27-metis-brain-local-latency.md
```

The authoritative repository gate completed successfully after the final code
changes: `2631 passed, 2 skipped, 0 failed`; the foundation roster reported
`85 passed, 0 errors`, and whole-repository Ruff and formatting checks were
green. A real installed VS Code no-Apply dialogue remains required for
product/UX closure; this note does not substitute for that live gate.

The installed extension recovered its tenant and chat surfaces after a VS Code
window reload, and the final no-Apply Draft smoke passed. A deliberately killed Brain child exposed a downstream
operational limitation: the current VSIX keeps its dead client until the
extension host reloads. Automatic child restart is a Visix integration backlog
item, separate from the latency measurements and from Brain's tenant-write
boundary.
