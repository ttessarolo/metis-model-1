# Metis Brain reliable low-latency wave

Status: **ACTIVE**

## Mandate

Implement the five ordered latency interventions authorized by the owner:

1. deterministic bounded edit fast path;
2. in-memory MLX prompt/KV cache;
3. startup prefix prefill;
4. progressive grammar/standard-library context with deterministic expansion;
5. compact Model 1 EditPlan plus pinned AST renderer, only if the preceding
   evidence and authority seams support promotion.

Reliability is the primary gate. Speed is accepted only at equal or stronger
grounding, semantic, minimal-diff, compiler and no-Apply guarantees.

## Preflight

- repository: `/Users/tommasotessarolo/Developer/metis-model-1`;
- branch: `main`;
- baseline: `30efef3a2f51ac47f2a231a46d765ee66542f20a`;
- remote baseline: `origin/main` aligned `0/0`;
- coordinator: L0 frontier / maximum;
- writable surface: Model 1 source, tests, docs, config and this run board;
- external Metis and tenant repositories: read-only when a pinned local proof
  explicitly needs them; no Apply and no mutation;
- model payloads, adapters, checkpoints, datasets and credentials: never Git;
- network, Ollama, remote fallback, training and model download: excluded from
  implementation and validation. The owner separately authorized one bounded
  architecture consultation with Qwen, Kimi K3 and Claude Fable 5 using only
  the sterilized brief in this run directory; the reviewers receive no source,
  tenant/catalog data, repository path, credentials, payloads or tool access.

## Baseline facts

- FACT — The qualified complex edit used `42.369 s` inside MLX for 4,409
  prompt tokens and 215 generated tokens at `10.45 token/s`, `stop`.
- FACT — Derived, not independently timed: decoding accounts for about
  `20.57 s`; the residual inside MLX is about `21.80 s` of prefill/overhead.
- FACT — The current 512-token ceiling did not bind that run.
- FACT — The worker is weight-warm and persistent for up to 120 requests but
  does not pass `PromptCacheState` or `APCManager` to MLX-VLM.
- FACT — The pinned runtime supports both cache APIs. The current prompt places
  request-dependent text before the 8,370-byte reference, preventing useful
  long-prefix reuse.
- FACT — `grounded_renderer` is create-only. Existing bounded edits always
  enter Model 1 even when retrieval has already fixed the complete finite
  selection, output cardinality and preserved surface.
- RISK — The compiler receipt does not currently expose a lossless AST/edit
  seam. A string rewrite or model-authored identifier cannot be promoted as a
  substitute.

## Invariants

- Retrieval/grounding exclusively owns catalog, field, value, output-count and
  revision authority.
- Model output is always a proposal; grounding and the pinned compiler remain
  mandatory.
- A fast path must decline on ambiguity, open domains, unsupported nodes,
  comments or source it cannot preserve exactly.
- The reusable cache template is process-memory-only, bounded, identity scoped
  and contains public static-prefix state only. Dynamic/session KV state exists
  only in a transient per-request clone and becomes unreachable at turn end;
  worker recycle, cancellation/crash and shutdown tear down the process.
- Progressive context can only expand monotonically from a pinned authority;
  model output can never request or name its own authority expansion.
- Direct DSL remains the qualified fallback. It cannot silently rescue a plan
  rejected for semantic or authority reasons.
- No tenant write or Apply is authorized by this wave.

## Gates

- paired frozen A/B with identical model, adapter, seed, tenant snapshot and
  toolchain;
- exact telemetry for cold/warm/refine/repair: prompt, cached and generated
  tokens, rates, wall times, finish reason and peak Metal;
- renderer/plan: zero unknown references, minimal local edit, all untouched
  source preserved, exact grounding and compiler green;
- cache: positive hit evidence plus invalidation and cross-session/tenant
  isolation tests;
- context: monotone bounded expansion and direct-DSL full-context fallback;
- targeted suites, Ruff, formatter, diff check and authoritative `make check`;
- local read-only E2E with no Apply and before/after tenant identity.

## Evidence wire

- FACT — Preflight is clean and baseline/remote are aligned.
- FACT — L501-L503 completed bounded runtime/cache, edit-seam and context/plan
  reviews. Their recorded findings locate cost in prefill and decode, confirm
  local cache API support, require a pinned AST seam for edit/plan promotion,
  and retain every stated promotion gate.

- DONE — L503 progressive context/EditPlan contracts are implemented as new,
  un-wired modules with adversarial focused coverage. The context prototype
  now consumes the exact runtime v3 projection and hash
  `sha256:ca2f7fc354e75a5c9367f6c934e67a04f7e44fd1615e26a8f19be6cde444194b`;
  its `minimal -> endpoint -> stdlib` views are monotone prefixes and the full
  view is byte-identical to the runtime projection. EditPlan accepts only
  host-issued opaque `hostref:` references and rejects unknown/duplicate refs,
  extra authority fields, invalid operation order/cardinality and revision
  drift. Both remain disconnected pending performance and lossless-CST gates.
- FACT — The owner authorized an external three-model architecture review before
  promotion. Locally installed clients expose Qwen `qwen3.8-max`, Kimi default
  `kimi-code/k3`, and Claude `claude-fable-5`. Each review is independent,
  stateless, tool-less and receives the same sterilized brief. L0 owns the
  evidence reconciliation and may reject every suggestion.
- DONE — L504-L506 returned one independent response each from Qwen
  `qwen3.8-max`, Kimi `kimi-code/k3`, and Claude `claude-fable-5`. The Qwen
  receipt reports `tools.totalCalls=0`; Kimi emitted assistant/meta events only;
  Claude ran with tools disabled and reports zero web requests. All three
  received the same sterilized brief and no workspace/source/tenant data. The
  tracked receipt roster and recorded recommendation excerpts are in
  `EXTERNAL_REVIEW_RECEIPTS.md`.
- FACT — Three-model consensus: make prompt measurement/canonical static-prefix
  ordering an explicit step zero; treat cache plus startup prefill as one
  intervention; keep deterministic no-model paths conservative; demote
  progressive context and EditPlan until post-cache evidence exists; measure
  time-to-first-visible-progress as well as terminal latency.
- FIX — L0 rejected the first shared-state cache draft because it could retain
  a dynamic suffix. The replacement keeps an immutable public-prefix template,
  restores a fresh transient clone for each request, never passes the template
  to generation and discards the clone at turn end. Actual MLX cache-container
  cloning and adversarial fail-closed behavior have focused coverage.
- FIX — The obsolete progressive-context v1 pin was removed. The un-wired
  prototype imports the runtime's single v3 authority, fails closed on hash or
  section drift, and produces `2506 B -> 5435 B -> 8370 B` monotone views.
  Promotion remains conditional because a warm prefix hit makes its marginal
  value uncertain and under-contextualization may increase repair p95.
- FIX — L501 added wire-v2 exact prefix identity (`cache_scope`, model revision,
  adapter SHA and prefix SHA) while accepting legacy wire-v1 requests/responses.
  Only a fixed tenant-free prefix is eligible for process-local caching; dynamic
  request data stays after it. Scope syntax is bounded to 128 UTF-8 bytes and
  prefix token/cache storage is bounded to 4096 tokens/2 GiB.
- FIX — Startup warmup performs one idempotent MLX-VLM `PromptCacheState`
  prefill per `(cache_scope, prefix_sha256)` and reports bounded `cache_ready`,
  `prefix_tokens` and `cache_hit` telemetry. The prefetched state is an
  immutable public template. Generation receives only a transient clone; if
  cloning cannot be proven safe, the request falls back cold. Worker
  recycle/crash/cancellation/close erase all process-local state by teardown.
- FACT — L0-reported read-only observation: a real qualified MLX warmup
  completed in `19.877 s`, including
  `1.322 s` worker-reported model load, and reported `prefix_tokens=2241` plus
  `prefix_cache_ready=true` with the expected model revision and adapter
  digest. The runtime then closed cleanly. This proves prefix prefill, not yet a
  generation cache hit or semantic latency improvement.
- STOP/FIX — The first real generation exposed an off-by-one prefill defect:
  requesting one warmup token advanced Qwen3.5 KV state to `prefix+1`, and
  MLX-VLM attempted unsupported `trim()` on hybrid `ArraysCache`. L0 replaced
  it with zero-output-token prefill, exact logical-offset checks, exact
  full-prompt token-prefix comparison and cold failover. The failed worker was
  closed and no tenant was involved.
- FACT — L0-reported live cache roster `in=2 out=2 distinct=2 gaps=0`: one persistent
  qualified worker (`PID 89298`) served two independent synthetic generations;
  both reported `cache_hit=true`, `cached_tokens=2241/2454`, `56` generated
  tokens, `finish_reason=stop`, about `6.5 s`, identical output SHA-256 and
  `19.717 GB` peak Metal. Close reported model unloaded and warmup closed.
- FACT — L0-reported read-only complex E2E `in=1 out=1 distinct=1 gaps=0`: the frozen edit
  request used `generation_strategy=model`, hit the exact `2241/4441` public
  prefix, generated `217` tokens in `31.824 s`, passed exact finite grounding,
  compiled on attempt one with zero diagnostics, and reported
  `tenant_modified=false`. The `play-demo` Git head, clean state and target
  SHA-256 were byte-identical before/after; Apply was never invoked.
- FACT — Cross-run observed improvement is bounded, not a paired or
  distributional claim: the preceding Flash measurement used the separate
  `metis-tenants/play-demo` snapshot, whereas the cache proof used the canonical
  `Developer/play-demo` snapshot. Model 1 generation moved from `42.369 s` to
  `31.824 s` (`-24.9%`), while the whole turn moved from `56.420 s` to
  `46.775 s` (`-17.1%`). Decode remains about `20.7 s` at `10.47 token/s`;
  cache alone does not meet the declared interactive promotion threshold and a
  frozen same-snapshot paired A/B remains open.
- FIX — The demo fixture now binds the same canonical
  `/Users/tommasotessarolo/Developer/play-demo` workspace used by the cache
  proof. The prior tracked VS Code smoke used the separate `metis-tenants`
  checkout; no claim is made about which checkout is currently visible in the
  editor.
- DONE — L501 focused runtime suite: `uv run pytest -q
  tests/test_brain_mlx_runtime.py` passed `48`; it includes a suffix-retention
  adversarial test proving the next request sees only static prefix ids/KV and a
  fail-closed untrimmable-cache test. The legacy ModelCandidate metric
  shape remains accepted while cache telemetry is strict when present. Ruff format/check, py_compile and
  `git diff --check` passed. No model load/run/download/network/tenant access was
  performed by that delegated lane; L0 later ran the bounded live observations
  recorded above. Frozen same-snapshot paired qualification remains open.
- FIX — Final review made positive `warmup_prefix_tokens` a server readiness
  requirement, matching the runbook, and added a fail-closed zero-token test.
- FIX — Unwired bounded-edit/EditPlan prototypes now require exact grounding,
  context and source revisions, reject oversized/invalid UTF-8 renderings, and
  return a detached admitted plan. They remain disconnected pending the
  lossless-CST and performance gates.
- OPEN — Explicit multi-session/multi-tenant live isolation and scope-rotation
  evidence is not inferred from two synthetic generations. Clone immutability
  and exact-token failover are covered, but this promotion gate remains open.
- OPEN — The EditPlan schema is registered as a repository standalone contract,
  but the unwired experiment is not a packaged runtime surface; resource
  packaging must be designed with the future renderer integration rather than
  inferred from source-tree tests.
- DONE — L0 focused integration roster `in=449 out=449 distinct=449 gaps=0`:
  cache/runtime/server/config, bounded edit, progressive context, EditPlan,
  orchestrator, grounding, compiler authority and foundation-contract tests
  passed in `327.63 s`; whole-source Ruff and format plus `git diff --check`
  are green. The three tar-extraction notices are existing Python 3.14
  deprecation warnings, not failures.
- DONE — Final independent re-audits: cache/server `P0=0 P1=0` with the final
  4096-token readiness ceiling covered by focused tests; bounded edit/context/
  EditPlan `P0=0 P1=0 P2=0` in their declared unwired scope; documentation and
  evidence claims GREEN after cross-run, unsealed-live and checkout provenance
  corrections.
- DONE — Authoritative repository gate `in=2807 out=2807 distinct=2807 gaps=0`:
  foundation `86/86` with zero errors, pilot contracts valid, whole-repository
  Ruff and formatting green, and test harness `2805 passed, 2 skipped, 0 failed`
  in `2830.03 s`. The 22 notices are the existing Python 3.14 tar-extraction
  deprecation warning, not wave failures.
- DECISION — Implementation seal is GREEN for immutable public-prefix caching,
  startup prefill, bounded telemetry and the deliberately unwired experimental
  contracts. Latency promotion remains OPEN because same-snapshot paired
  p50/p95 and explicit multi-session/multi-tenant isolation are not yet sealed.
