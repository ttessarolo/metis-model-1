# Metis Brain local-latency closure blackboard

## Objective

Turn the installed Mac demo from a technically correct but unusably slow flow
into an interactive local product. Preserve reviewed semantic grounding,
compiler validation, the pinned Qwen3.8-27B adapter and the no-Apply boundary.

## Preflight

- FACT — L0 starts from clean `main@b236430b17117c627ddd64dd4c00eba39000df1e`.
- FACT — the installed VS Code smoke took about 56 seconds to reach the first
  Brain-owned result-count question and several further minutes to deliver the
  resumed Draft.
- FACT — the first question completed before the MLX worker was started; its
  delay is therefore retrieval/toolchain cold-start, not model inference.
- FACT — production generation is lazy, serial and hard-capped at 512 tokens;
  the worker currently discards generation-token count, stop reason and
  throughput, so cap exhaustion cannot yet be distinguished from EOS.
- FACT — both cold semantic projection and every compile rebuild an isolated
  Metis tree, copy roughly 199 MB / 17k `node_modules` entries and repeat full
  pin hashes. The semantic index is cached only after that first build.
- STOP — no model-family downgrade, training, weight mutation/download,
  remote/Ollama fallback, credential access, VPN/live data, tenant write or
  Apply is authorized by this wave.

## Decisions

1. One process-private pinned Metis authority capsule is verified once and
   shared by retrieval and compiler. Per operation Brain materializes only a
   bounded tenant job overlay; sandbox, network denial, source redaction and
   snapshot/revision guards remain mandatory.
2. A fully reviewed, finite, create-only request may use a deterministic
   grounded endpoint renderer. This is a transparent Brain fast path, not a
   claim that MLX generated the source. Any unsupported type, unresolved
   concept, edit/refine, open-domain selection or non-canonical surface stays
   on the Qwen path or fails closed.
3. Model generation remains Qwen3.8-27B + the sealed adapter. Worker telemetry
   must expose bounded numeric timing/token data and `stop|length`; token-budget
   changes require measured compile/grounding equivalence, never a blind cap
   reduction.
4. Public progress may expose phase and elapsed time, but never prompts,
   sources, tenant values beyond the existing proposal contract or hidden
   chain-of-thought.

## Acceptance gates

- cold and warm phase timings are attributable from public-safe evidence;
- the reviewed finite create fast path performs zero model calls and still
  passes exact candidate-grounding plus the pinned compiler;
- non-fast-path requests retain the qualified local model and bounded repair;
- one verified authority capsule is reused by retrieval and compilation;
- no per-turn copy/hash of the full `node_modules` tree;
- focused security/correctness tests and authoritative `make check` are green;
- real installed VS Code no-Apply smoke produces `take 24` and a visible Draft;
- Model 1 and tenant repositories remain clean, committed and pushed as scoped.

## Status

`COMPLETE — AUTHORITATIVE GATE AND INSTALLED VS CODE NO-APPLY SMOKE GREEN`

## Evidence wire

- DONE — L201/L202/L203 read-only roster `in=3 out=3 distinct=3 gaps=0`:
  MLX, toolchain and E2E observability causes independently agree.
- RISK — the current worker response cannot prove whether the slow live result
  ended on EOS or the 512-token length cap.
- RISK — the current compiler isolation repeats expensive work even though the
  executed Git archive and dependencies are identical within one Brain process.
- FIX — `PinnedMetisAuthority` builds and hashes the pinned Metis archive and
  199 MB dependency tree once per process; compiler and schema-2 retrieval
  share it, while every operation receives a distinct overlay whose sandbox
  cannot read sibling jobs.
- FIX — the reviewed finite create renderer emits the exact qualified catalog,
  binds language/context/semantic/toolchain revisions, calls the model zero
  times, and still passes exact grounding plus the pinned compiler.
- FIX — candidate adjudication now rejects implicit `from all` and finite
  predicates outside the authorized endpoint-level `take`.
- FACT — cold no-Apply fast-path probe: `11067 ms` end-to-end, retrieval
  `10451 ms`, compile `602 ms`, inference `0 ms`, `model_loaded=false`,
  `compile_clean=true`, `tenant_modified=false`.
- FACT — pre-optimization qualified-model probe: generation wall `153852 ms`,
  prompt `17240` tokens, generated `86` tokens, `finish_reason=stop`, worker
  load `3493 ms`. The 512-token cap was not the cause.
- FIX — model serialization retains only grounded/previously-authored fields
  and projects the full pinned grammar card to the endpoint runtime surface;
  measured prompt bytes fell from about `68733` to `14477`.
- DONE — representative model-required edit/refine roster
  `in=1 out=1 distinct=1 gaps=0`: final generation wall `34319 ms`, prompt
  `3700`, generated `72`, `finish_reason=stop`, compile `781 ms`, grounding and
  compiler green, tenant unchanged.
- DONE — focused implementation/security roster green, including worker
  telemetry, shared authority reuse, sibling-overlay denial, deterministic
  no-model compile, fully qualified catalog rendering, and grounding guards.
- DONE — authoritative repository gate: `make check` exited zero with
  `2631 passed, 2 skipped, 0 failed`; the foundation roster reported
  `85 passed, 0 errors`, whole-repository Ruff and formatting checks were
  green, and the worker source digest matched its pinned runtime constant.
- FACT — the installed VS Code extension is `v0.23.97`, sees tenant
  `play-demo` on `main`, and its native `@metis` chat remains wired to the
  configured local Brain executable. No Apply was used. The deliberately
  terminated pre-wave Brain left the extension's cached client dead until a
  VS Code window reload; after reload the extension/tenant surfaces recovered.
- DONE — installed VS Code `v0.23.97` no-Apply smoke on 2026-09-01:
  `@metis Crea un nuovo endpoint @video con 24 film prodotti in Italia.`
  completed from a freshly reloaded extension host/Brain child in `31 s` and
  exposed a compiled Draft with exact source `take 24 from @play-demo.video`,
  reviewed `tipologia = "Film"`, reviewed `paesiorigine` literals and
  `return response.default`. `Applica` was not pressed.
- FACT — after the smoke, Model 1 and `play-demo` were both Git-clean and the
  tenant remained on `main`. The Brain HTTP process was alive at about 876 MiB
  RSS and no MLX worker existed, independently confirming that the eligible
  deterministic path did not load or call Qwen.
- RISK — if the Brain child exits after ready, the current VSIX controller
  retains the dead client until extension-host reload. Automatic crash
  recovery belongs to the Visix integration backlog and does not alter the
  measured generation/retrieval latency results.
- RISK — session-scoped prompt/KV caching and the wider open-domain/repair
  benchmark matrix remain follow-up optimizations; neither is needed to claim
  the measured fast path or the measured edit/refine result.
- DONE — L208 final read-only integrated audit roster
  `in=1 out=1 distinct=1 gaps=0`: verdict GREEN, no actionable P0/P1/P2 across
  shared authority isolation, deterministic rendering, candidate grounding,
  telemetry, model fallback/repair, or shutdown lifecycle.
