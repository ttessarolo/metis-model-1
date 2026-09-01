# Metis Brain reliable low-latency — operating synthesis

Status: **ACTIVE DECISION RECORD**
Owner: L0 frontier coordinator
Inputs: advisory reviews from Qwen `qwen3.8-max`, Kimi
`kimi-code/k3`, Claude `claude-fable-5`, plus repository and installed-runtime
evidence checked locally by L0. Provider/client receipts and recorded excerpts
are tracked in `EXTERNAL_REVIEW_RECEIPTS.md`.

## Executive decision

The original five interventions remain useful, but they must not be promoted in
their original order. The unified execution order is:

1. **Measure and canonicalize first.** Split the current 42.369-second model
   call into tokenization, real prefill/cache attach, decode and residual
   overhead. Keep the immutable public grammar/reference prefix before every
   request-dependent byte.
2. **Promote one immutable-prefix cache with startup prefill.** Items 2 and 3 are
   one intervention. The cached state must contain only public static-prefix
   tokens, never tenant/session text or generated tokens.
3. **Avoid Model 1 only where the host can prove the complete result.** Keep the
   qualified deterministic create renderer. Do not wire the bounded-edit
   prototype until the pinned Metis compiler exposes a lossless CST/source-edit
   seam. Unsupported authority already declines before Model 1 and stays so.
4. **Remove measured non-model latency and silence.** Benchmark the existing
   process-private immutable compiler authority capsule and optimize only
   measured per-job overlay cost. Emit truthful phase/heartbeat events while
   work is running. Do not add a second compiler cache and do not stream
   uncompiled source as if it were a valid draft.
5. **Attack decode only after the new measured baseline.** EditPlan,
   grammar-constrained decoding and speculative decoding are separate
   experiments. None is on the product path until it beats direct DSL without
   semantic, memory or fallback regressions.
6. **Progressive context is conditional, not assumed.** Rebuild it only from the
   exact v3 runtime authority and only if cold/cache-miss evidence shows material
   value after prefix caching.

This order preserves reliability and prioritizes the two largest safe gains:
removing unnecessary 27B calls and not recomputing the same public prefix.

## What the Orchestra agreed on

All three external reviewers independently converged on these points:

- the static-prefix ordering is a prerequisite, not an incidental refactor;
- cache and startup prefill should be designed, measured and invalidated as one
  unit;
- a deterministic fast path is valuable only with a conservative accept
  predicate and the same grounding/compiler gates as the model path;
- progressive context has weak marginal value once its prefix is cached and can
  worsen p95 through retries if it under-contextualizes the model;
- EditPlan can reduce decode but introduces ambiguity and fallback
  amplification, so it belongs after cache evidence;
- time-to-first-visible-progress must be measured alongside final latency.

The reviews were advisory. L0 rejected or qualified several attractive claims
after checking the real stack:

- **No Flash-authored DSL.** The Flash model remains a bounded intent/recall
  assistant; it cannot own catalogs, fields, values or source.
- **No unvalidated source streaming.** Brain may stream genuine processing
  phases, but a source draft appears only after grounding and compilation.
- **No speculative decoding now.** Installed MLX-VLM supports it, but the
  qualified Model 1 checkpoint has no compatible MTP/drafter weights. No model
  download or implicit artifact substitution is authorized.
- **No current progressive-context promotion.** The prototype now imports the
  exact T30 v3 runtime authority and produces monotone prefixes, but remains
  disconnected until a cold/cache-miss benchmark proves a benefit without
  additional repairs.
- **No source-span edit promotion.** The prototype is usefully fail-closed, but
  the compiler receipt does not expose the lossless CST seam required for a
  first-class product route.

## Immediate implementation roster

### P0 — close before any cache benchmark

- Keep one immutable public-prefix template. For every generation, restore a
  transient cache clone and discard that clone after completion, failure,
  cancellation or repair. The persistent template must never be passed to
  generation and must never receive dynamic prompt or generated tokens.
- Bind reuse to model revision, adapter digest, prompt-wire version and exact
  token-prefix identity. A miss must recompute safely; code must never assume a
  hit.
- Make warmup health truthful: `cache_ready` means prefix computation has
  completed. Describe it as model prefill without user generation, not as “no
  inference.”
- Expose prefix-token count, cached-token count, hit/miss, cache bytes, prefill
  time, decode time, finish reason and peak Metal in bounded telemetry.

### P1 — paired qualification

Run the same frozen requests on the same model, adapter, seed, tenant snapshot
and compiler authority:

1. cold worker, no cached prefix;
2. startup-prefilled worker, first complex request;
3. warm independent request;
4. refine in the same Brain session;
5. grounding repair and compiler repair fixtures;
6. worker recycle, cancellation and shutdown.

For each route record end-to-end, model-call, prefill, decode, cached and
generated tokens, compile duration, cache high-water memory and terminal
grounding/compile result.

A first cross-run observation is available: the exact-prefix proof measured
Model 1 at `31.824 s` and the complete turn at `46.775 s`, with first-pass
compilation, exact grounding and no tenant mutation. The preceding `42.369 s` /
`56.420 s` observation used a different local tenant snapshot, so the apparent
`24.9%` / `17.1%` reductions are directional only, not a paired A/B. This is a
functional GREEN but not a latency promotion; frozen same-snapshot p50/p95
qualification remains open.

### P2 — deterministic routes and compiler cost

- Census the replay corpus before enlarging any fast path: report eligible,
  accepted, declined, false-accepted and latency saved.
- Keep deterministic create enabled under its existing gates.
- Keep bounded edit disconnected until a pinned lossless CST edit seam exists.
- Benchmark the existing process-private immutable compiler authority capsule.
  Optimize only measured job-overlay overhead; do not introduce a second cache
  or weaken re-verification, sandboxing or the full toolchain binding.
- Emit an initial phase event promptly and an authentic heartbeat at most every
  five seconds during long retrieval, inference and compilation. Existing
  retrieval/inference/compile events remain the public vocabulary.

### P3 — decode experiments, one at a time

Only after P1 establishes the new decode-dominated baseline:

- **EditPlan:** opaque unpredictable host references, scoped to one turn and
  bound to revisions; lossless deterministic rendering; streaming structural
  validation; direct DSL fallback. Kill if ambiguity exists or fallback erases
  the gain.
- **Grammar-constrained decoding:** qualify against the EditPlan schema or Metis
  surface. It may strengthen syntax but cannot replace grounding or compilation.
- **Speculative decoding:** separate wave with a locally qualified Qwen3.5 MTP
  drafter, exact token-for-token comparison at temperature 0, and explicit
  cache/adapter/Metal tests. It is disabled by default.
- **Progressive context:** rebuild from the exact v3 runtime projection as
  token-prefix-monotone levels. Promote only if cold/cache-miss latency improves
  without any extra repair or semantic failure.

## Promotion and kill gates

Reliability gates are absolute:

- zero cross-session or cross-identity dynamic-token retention;
- zero unknown catalog/field/value references accepted;
- zero non-minimal deterministic edits;
- byte identity for every untouched source span;
- no grounding or compile regression on the frozen paired roster;
- zero tenant mutation and zero automatic Apply;
- one false accept, stale-authority cache hit or cross-session observation stops
  promotion immediately.

Performance gates are staged to keep iteration rapid:

- fast unit/adversarial suites on every edit;
- a small frozen live smoke roster before expensive testing;
- one stratified paired promotion roster after the implementation stabilizes;
- the authoritative full repository gate once at the promotion boundary, not
  after each mechanical change.

The cache is promoted only if warm p50 is at most 60% of the paired baseline,
warm p95 is at most 70%, no route regresses by more than 5%, every eligible
warm request proves a positive exact-prefix hit, cache state remains bounded by
the declared memory ceiling, and session churn shows no growth. These are
promotion thresholds, not claims about results already obtained.

An experimental route is killed when it increases repair/fallback rate,
regresses the slowest-route p95, requires an unqualified model artifact, changes
accepted semantics, or saves too little latency to justify its memory and
maintenance surface.

## Product-facing latency contract

Metis Brain exposes universal session events usable by both Visix and Metis
Fast. The UX may show:

- tenant context acquired;
- request grounded against reviewed catalog semantics;
- clarification required;
- deterministic rendering or Model 1 generation in progress;
- grounding verification in progress;
- compiler validation in progress;
- compiled draft ready.

It must not expose private chain-of-thought, present uncompiled tokens as source,
or imply that an endpoint was applied. This improves perceived responsiveness
without weakening the draft-first contract.

## Current verdict

**Proceed, but fail closed.** Static-prefix ordering is accepted. Dynamic-suffix
retention is closed in design by an immutable public template plus transient
per-request clones, and is covered by adversarial tests and a real MLX cache
container probe. L0's read-only qualification observations report two positive
live hits and one complex no-Apply E2E with unchanged grounding/compiler
behavior; they are not a machine-sealed benchmark receipt. The speed threshold
is still open, as are explicit multi-session/multi-tenant isolation and frozen
same-snapshot paired evidence. The remaining complex-call floor is
decode-dominated. Bounded edit, progressive context, EditPlan and speculative
decoding remain experiments until their explicit authority/artifact gates are
satisfied.
