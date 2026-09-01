# External latency-review receipts

Recorded at `2026-09-01T13:23:16Z`. The three reviewers received only
`EXTERNAL_REVIEW_BRIEF.md`, whose SHA-256 is
`09c5da81bbd9f088c052077b424b0f1d76ad736300b398f3f2659b47e1ab676d`.
They ran from `/tmp`, outside the workspace. These are advisory-response
receipts, not semantic or promotion authority; L0 independently reconciles
every suggestion against repository and live evidence.

| Reviewer | Client / requested model | Provider receipt | Tool/network evidence |
|---|---|---|---|
| Qwen | Qwen Code `0.22.3` / `qwen3.8-max` / safe mode | session `6b6faab8-8110-434a-b84c-12ab80c8b8f4`; one successful request; `10041` output tokens | `tools.totalCalls=0`, `files.totalLinesAdded=0`, `files.totalLinesRemoved=0` |
| Kimi | Kimi Code `0.39.1` / `kimi-code/k3` | session `session_a6e0e48a-5f8a-4bcb-b9c9-20eddedd24af`; one assistant response | stream contained assistant/meta events only; the prompt explicitly prohibited tools and workspace inspection |
| Claude | Claude Code `2.1.201` / `claude-fable-5` / safe mode | session `43d5f995-c597-4635-82a0-affaac1ec8b5`; main response attributed to `claude-fable-5` | tools disabled, `permission_denials=[]`, `web_search_requests=0`, `web_fetch_requests=0`; one 27-token Haiku control/helper call is separately reported by the client |

The response excerpts below preserve the operational recommendations used by
the synthesis. They intentionally omit internal reasoning and repetitive
analysis.

## Qwen recorded recommendation

**KEEP**

- Ship the conservative bounded-edit path first, but measure its true coverage.
- Keep progressive context host-selected and pinned.
- Retain the frozen paired A/B, grounding, compiler, isolation and no-Apply
  gates.

**CHANGE**

- Add step zero: canonical stable content first in the prompt.
- Treat progressive levels and prefix caching as one compatibility workstream;
  startup prefill is a cache policy, not an independent architecture.
- Keep EditPlan last and account for valid-but-wrong references and fallback
  double-spend.

**EXPERIMENT**

- Speculative decoding against the qualified target.
- A host-side triage router and compact canonical retrieval payload.
- Quantization only as a separately qualified artifact change.

## Kimi recorded recommendation

**KEEP**

- Prefix/KV caching with static content first and startup warming as a sub-step.
- The deterministic fast path under the same grounding and compiler gates.
- EditPlan last and evidence-gated.

**CHANGE**

- Merge startup prefill into the cache intervention and gate reorder, cache and
  warmup separately.
- Require progressive levels to expand tail-only from pinned inputs.
- Expose genuine progress while never presenting unvalidated source.

**EXPERIMENT**

- A verifier-gated small-model cascade.
- Speculative decoding, retrieval/prefill overlap and verified-result
  memoization.

## Claude recorded recommendation

**KEEP**

- Grounding plus compilation before presentation, fail-closed decline, and no
  automatic Apply.
- Deterministic rendering, exact-prefix reuse and direct DSL as the qualified
  fallback.

**CHANGE**

- Canonicalize the prompt before caching; bind the token prefix to model,
  adapter, tokenizer/template and authority revisions.
- Reconsider progressive context only after cache evidence because escalation
  can worsen p95.
- Measure the derived `21.8 s` bucket rather than calling all of it prefill.

**EXPERIMENT**

- Prompt-lookup or compatible speculative decoding for copy-heavy edits.
- Bounded memoization of already verified compiled results.
- Time-to-first-verified-artifact through truthful phase progress.

## L0 reconciliation

The unified decision is in `OPERATING_SYNTHESIS.md`. L0 accepted prompt
canonicalization, immutable-prefix caching, truthful progress and
decode-focused experiments. L0 rejected raw source streaming, Flash-authored
DSL, an unqualified small-model source route, and speculative decoding without
a locally qualified compatible drafter. The installed Model 1 artifact has no
declared MTP/drafter weights, so speculative decoding remains a separate
experiment rather than a current implementation claim.
