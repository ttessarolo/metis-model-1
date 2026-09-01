# Sterilized architecture review brief

You are reviewing a local, session-oriented code-generation service. Do not use
tools, browse, inspect files, or assume access to implementation details beyond
this brief. Give an independent engineering opinion; do not merely endorse the
proposed plan.

## Objective

Reduce perceived latency substantially while preserving exact semantic
grounding, deterministic compilation, minimal edits and fail-closed behavior.
The service must feel fast in an interactive editor and a future custom app.

## Measured baseline

- A qualified complex edit spends 42.369 seconds in a warm local 27B model.
- Input: 4,409 prompt tokens. Output: 215 tokens at 10.45 tokens/second.
- Finish reason is `stop`; the 512-token ceiling did not bind.
- Derived estimate only: about 20.6 seconds decoding and about 21.8 seconds
  prefill/other model-call overhead.
- The model worker persists, but no prompt/KV cache is used across turns.
- A static grammar/standard-library reference is about 8.4 KB and currently
  follows request-dependent content, preventing useful prefix reuse.
- Retrieval already resolves authoritative catalog, field, finite value,
  cardinality and revision identities before generation.
- A deterministic create renderer exists; bounded edits still invoke the 27B.
- Every proposal is checked against grounding and compiled before presentation.

## Non-negotiable invariants

- Retrieval/host code, never a model, owns semantic and revision authority.
- No invented identifiers or values; no tenant writes or automatic Apply.
- Unchanged source must be preserved exactly; ambiguous/unsupported edits must
  decline to the qualified model path.
- Caches are bounded, process-memory-only, identity/revision scoped and erased
  on expiry, close, recycle, crash and shutdown. No persistent conversation or
  tenant data.
- Progressive context may expand only from pinned host authority and only
  monotonically. Model text cannot grant itself more authority.
- Direct DSL generation remains the qualified fallback.
- Speed changes are promoted only after frozen paired A/B, compiler, grounding,
  isolation and no-Apply gates.

## Current ordered proposal

1. Add a deterministic bounded-edit fast path that accepts only provably local,
   lossless edits and otherwise declines.
2. Add an in-memory exact-prefix prompt/KV cache with strict identity and
   lifecycle invalidation.
3. Prefill the immutable public prefix at startup so cold user turns do not pay
   its cost.
4. Replace the always-full reference with pinned progressive levels, expanded
   deterministically by host signals; full context remains fallback.
5. Only if qualified, have the 27B emit a compact EditPlan containing opaque
   host-issued references, then render it deterministically through a pinned
   syntax/AST seam; reject unknown references and fall back to direct DSL.

## Questions

1. Rank the five interventions by expected latency gain, implementation risk
   and semantic risk. Would you reorder, split or reject any?
2. Identify hidden failure modes in cache isolation, startup prefill,
   progressive context, deterministic editing and opaque-reference EditPlan.
3. Propose any higher-leverage technique absent from the plan, especially one
   that improves time-to-first-visible-progress or avoids unnecessary 27B calls
   without weakening authority.
4. Define concrete promotion metrics and kill criteria. Include p50/p95 latency,
   cache-hit behavior, semantic/compile equivalence and memory pressure.
5. Return a concise operational recommendation with three sections exactly:
   KEEP, CHANGE, EXPERIMENT. Label every claim as measured fact, inference, or
   hypothesis.
