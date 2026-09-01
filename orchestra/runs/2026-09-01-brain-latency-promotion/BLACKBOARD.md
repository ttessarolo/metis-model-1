# Metis Brain latency promotion wave

Status: **ACTIVE**

## Mandate

Complete the seven ordered product gates authorized by the owner:

1. frozen same-snapshot A/B on the canonical `Developer/play-demo` tenant;
2. explicit multi-session/multi-tenant cache-isolation qualification;
3. separate every serving phase the qualified MLX API can observe without
   inventing a model-internal timer;
4. reduce Model 1 decode latency without new weights or a semantic regression;
5. keep deterministic edits and EditPlan fail-closed until a lossless compiler
   renderer is proven;
6. emit truthful, bounded progress/heartbeat events shared by Visix and Metis
   Fast;
7. exercise the installed VS Code integration in a real local, draft-only flow.

The target is an interactive complex turn ideally below 20--25 seconds. This is
a target, not a claim and never overrides grounding, compiler, isolation,
minimal-diff or no-Apply gates.

## Preflight

- repository: `/Users/tommasotessarolo/Developer/metis-model-1`;
- branch: `main`;
- baseline: `414edf085b836e533dfc2a426ff20f7d141755ab`;
- remote: `origin/main` aligned `0/0`; worktree clean;
- tenant authority: `/Users/tommasotessarolo/Developer/play-demo`, read-only;
- coordinator: L0 frontier / maximum;
- delegated lanes: lower-cost, read-only census and adversarial review only;
- writable surface: Model 1 source, tests, docs, config and this run directory;
- other repositories, tenant files and installed VSIX: never mutated;
- no Apply, network fallback, Ollama, credentials, `.env`, Keychain, ARES live
  data, training, model download or new model/drafter payload;
- local qualified Model 1 execution is allowed only for bounded frozen
  benchmarks and the draft-only VS Code proof.

## Fixed meanings

- A **lossless compiler renderer** parses and renders unchanged source to the
  exact same bytes and, for an edit, preserves every untouched source span.
- Existing bounded edit and EditPlan experiments remain unwired unless that
  compiler-owned guarantee and its adversarial gates exist. A string rewrite,
  whole-file regeneration or merely compile-clean output is not equivalent.
- The immutable public-prefix cache may contain no tenant, session, request or
  generated token. Every dynamic cache is a transient per-request clone.
- Progress events expose verified phases, timings and liveness, never hidden
  chain-of-thought or uncompiled source.

## Promotion gates

- one machine-readable frozen manifest binds model revision, adapter SHA-256,
  prompt/wire/cache identity, tenant Git/tree/file hashes, semantic revision,
  compiler/toolchain and request roster;
- paired cold/direct and prefetched runs use identical request bytes, seed,
  snapshot and output budget; report per-route p50/p95 and every observation;
- telemetry separates startup load, host queue, tokenization, cache preparation,
  TTFT, decode after the first token and residual wall time with bounded finite
  values. TTFT is explicitly the indivisible dynamic-prefill-plus-first-token
  interval exposed by the pinned MLX-VLM API; it is never relabelled as pure
  prefill;
- exact final source hash, grounding selections, compiler result, repair count,
  finish reason and Metal high-water are retained per observation;
- cross-session/tenant tests prove no dynamic-token retention and correct scope
  miss/rotation on identity change; cancellation/recycle/close free state;
- any decode optimization must be opt-in during qualification, fall back to the
  already qualified direct path, and pass exact-output plus semantic/compiler
  gates at temperature zero before default promotion;
- tenant HEAD/status/target hashes are identical before and after every live
  roster and VS Code proof; Apply is never invoked;
- focused tests during iteration; authoritative `make check` once at the final
  promotion boundary; independent Orchestra audits before commit/push.

## Evidence wire

- FACT — Preflight is clean at baseline `414edf085b836e533dfc2a426ff20f7d141755ab`
  and aligned with `origin/main`.
- FACT — The preceding wave qualified immutable public-prefix prefill and
  recorded one L0-reported complex cache-hit turn at `31.824 s` Model 1 /\
  `46.775 s` end-to-end. It did not produce a frozen paired receipt and leaves
  about `20.7 s` of observed decode.
- FACT — The preceding wave deliberately left bounded edit, progressive context
  and EditPlan unwired. This wave does not reinterpret those prototypes as
  product functionality.
- FACT — L601 found no compatible qualified drafter/MTP payload for the sealed
  Qwen checkpoint. Speculative decode therefore remains `STOP`; this wave does
  not download or qualify another model.
- FIX — The existing qualified worker now keeps one immutable public-prefix
  template and uses a transient per-request clone. One persistent worker can be
  switched only by the private qualification seam between `direct` and
  `prefix`; production configuration cannot select the A/B arm.
- FIX — Startup now prewarms both Model 1 and every authorized schema-2 tenant
  projection before HTTP readiness. Retrieval cache capacity is at least the
  tenant-grant denominator and is bounded at 64.
- FIX — Model telemetry v3 retains exact worker request, cache preparation,
  tokenization, TTFT, decode-after-first-token, residual, token-count, cache-hit,
  finish-reason and Metal values. Brain adds the actual wait on the host model
  lock as `model_lock_queue_ms`. Pure dynamic prefill is not separately observable in
  the pinned API and is not claimed.
- FIX — The frozen runner uses one warmed worker, two excluded decode preflights
  (`direct`, then `prefix`), then six counterbalanced AB/BA pairs. Every admitted
  proposal must have exact source parity, reviewed grounding, requested take,
  endpoint, order, response, first-attempt compilation and no tenant mutation.
- FIX — The redacted receipt binds the exact committed benchmark bytes, clean
  Model 1 commit/tree, tenant commit/tree/roster/target, model/adapter/worker,
  prefix, toolchain, Flash identity when used, both preflight projections and
  all 12 measured observations. Receipt creation is rooted through no-follow
  directory descriptors and the exact parent descriptor remains held through
  post-write authority checks. Receipt bytes remain under a random `.pending`
  name until those guards pass; only then is the final create-only name linked
  and directory-fsynced. Discard and guard failure never publish a final name.
- FIX — Session isolation tests exercise concurrent sessions on different
  tenants, prohibit proposal reuse across sessions, and verify volatile turn
  memory is removed on close. Worker cleanup drops all Python references to
  dynamic tokens after every request; this is process isolation, not a claim of
  cryptographic allocator zeroization.
- FIX — Universal SSE progress now emits bounded allow-listed heartbeats during
  long retrieval, Flash, inference, repair and compile phases. Event sequence
  and `Last-Event-ID` replay are monotonic; terminal publication is serialized
  against the heartbeat thread and remains the final event.
- STOP — Existing-endpoint deterministic `EditPlan` wiring remains disabled.
  The compiler artifact is now locally proven, but the remote pin, executable
  probe seal, typed host-reference bridge and full-snapshot compile receipt are
  not yet closed. Compile-clean or whole-file regeneration cannot satisfy this
  gate.
- FACT — The first full `make check` attempt completed foundation `86/0`, Ruff,
  format and the complete pytest denominator `2867 passed, 2 skipped, 0 failed`
  in `2791.03 s`. Its final source-authority seal correctly returned red because
  the separate renderer team modified the configured Metis source checkout
  during the run. This is not recorded as a complete GREEN; L0 will rerun the
  authority gate against a private immutable local copy of the pinned Metis
  revision without reading or altering the renderer team's worktree.
- DONE — The authoritative rerun against a private immutable copy of the exact
  pinned Metis revision completed `make check` with exit `0`: foundation
  `86/0`, Ruff and format GREEN, pytest `2867 passed, 2 skipped, 0 failed` in
  `2616.33 s`, and the post-run Git/tree/runtime authority seal GREEN.
- DONE — Independent final diff census: `in=27 out=0 distinct=27 gaps=0`;
  every path belongs to this Brain latency wave, with `P0=0 P1=0`. No secret,
  `.env`, credential, tenant payload, dataset, model weight, adapter or
  checkpoint payload is tracked by the change.
- DONE — Frozen live A/B receipt replayed exactly at
  `sha256:e738425cd806412eea44327d7915bd774832c4868a71068ef8fb01ba1c6a0172`:
  `pairs=6 observations=12 in=12 out=12 distinct=12 gaps=0`; exact source,
  grounding, requested `take 24`, endpoint/order/response shape, first-attempt
  compile and tenant invariance all GREEN.
- FACT — Direct inference measured p50/p95 `60099/82470 ms`; prefix measured
  `39498/59098 ms`. Prefix TTFT p50 fell from `36351` to `17072 ms`, while
  decode-after-first-token p50 remained `22403 ms` versus direct `22039 ms`.
- STOP — Latency promotion verdict is `MEASURED_NOT_PROMOTED`: prefix/direct
  ratios are `65.7%` p50 and `71.7%` p95 versus required `<=60%`/`<=70%`, and
  prefix turn p95 is `66876 ms` versus required `<=25000 ms`. Quality gates
  remain green; thresholds are not weakened after measurement.
- OPEN — Real installed VS Code `@metis` complex Draft proof, with no Apply and
  tenant identity unchanged.
- OPEN — Final clean-tree audit, documentation commit and push after the real
  installed-VS-Code proof.

## Lossless renderer reception

- FACT — External handover received at
  `docs/handover-lossless-renderer-2026-09-01.md`; it declares Metis revision
  `2ad60b3c804fb1c45e45883b0479a46f660d98f6`, tree
  `ea29b935934fadd5f99711c0470566a2484b35f6`, language `0.43`, tooling
  `0.23.97`, delivered but not wired.
- DONE — Independent local artifact audit with the Brain-pinned Node `v22.22.3`:
  evidence `in=13 out=13 distinct=13 gaps=0`, corpus `200/200` and `606654`
  bytes, all five declared probes GREEN. One independent replacement preserved
  a `164`-byte prefix and `626`-byte suffix exactly outside byte span
  `[164,180)`. Local renderer artifact verdict: GREEN.
- STOP — Brain pin/wiring remains fail-closed. Local `main` at the delivered
  revision is ahead of the locally known `origin/main` by one and the expected
  remote ref does not contain the revision; current Brain authority policy
  therefore forbids pinning it. No fetch or push was performed by this wave.
- STOP — No typed `hostref -> node/preimage/payload/placement/mode` registry or
  exact translation exists. The compiler and Brain EditPlan contracts are not
  one-to-one, the same base SHA is not yet bound across all layers, and the
  compiler bridge does not yet force `compileProof=validate` on the original
  full tenant snapshot or strictly validate the lossless receipt.
- STOP — The current Brain pin verifier records probes but does not execute
  them. A reception gate over the Git archive and pinned Node, or an equivalent
  sealed receipt, is required before deterministic edit can be enabled.
- RISK — The adversarial parser-limit fixture is GREEN on the qualified Node
  `v22.22.3` but three assertions are RED on the host default Node `v26.5.0`;
  the integration must invoke the pinned runtime explicitly and cannot claim
  generic Node portability.
