# Metis Brain warm-model and complex E2E blackboard

## Objective

Make the qualified local Model 1 warm before Metis Brain declares itself ready,
keep its worker alive for subsequent turns, and prove the real MLX path with one
semantically complex edit/refine request. The result remains a compiled Draft:
no Apply and no tenant mutation.

## Preflight

- FACT — L0 starts from clean `main@a17e27542bfeb79f9aa125e22f2f0eeff63bd4ea`,
  aligned with `origin/main`.
- FACT — Brain uses the qualified Qwen3.8-27B MLX checkpoint plus the sealed
  Model 1 adapter directly; Ollama is not in the serving path.
- FACT — the MLX worker is currently lazy-started on the first model-required
  turn, then reused for at most 120 requests until bounded recycle or Brain
  shutdown.
- FACT — measured worker weight loading is only part of latency: prior runs
  measured roughly 1.4–3.5 seconds of load inside a roughly 34-second qualified
  edit/refine model turn.
- STOP — this wave does not authorize training, downloading or mutating model
  artifacts, a model-family downgrade, Ollama/remote fallback, credentials,
  VPN/live data, tenant writes, Apply, or writes outside this repository.
- STOP — prompt/KV caching is deliberately not bundled into this wave; it needs
  its own revision-bound cache and invalidation design.

## Decisions

1. Warmup is an explicit strict configuration policy. Backward-compatible lazy
   mode remains available, while the local play-demo fixture opts into startup
   warmup.
2. Startup warmup must prove that the worker has loaded the pinned base and
   adapter without performing a synthetic inference. Brain may announce ready
   only after that proof; failure closes the runtime and fails startup.
3. Public health exposes only bounded warmup state/timing and model identity.
   It never exposes prompts, sources, hidden reasoning, local paths or tenant
   values.
4. “Always warm” means warm at Brain readiness and retained until controlled
   worker recycle, Brain shutdown or failure. The 120-request safety recycle is
   preserved; no second hot replica is introduced.
5. The complex proof must be an edit/refine request that is ineligible for the
   deterministic create renderer, must report `generation_strategy=model`, and
   must pass exact grounding plus the pinned compiler with the tenant unchanged.

## Acceptance gates

- exact config parsing accepts only the declared warmup policy and rejects
  unknown or incompatible shapes;
- worker startup has an explicit load-complete handshake and bounded timeout;
- startup-warm failure is fail-closed and cleanup leaves no worker behind;
- health proves warm policy/state/timing and `model_loaded=true` before serving;
- focused lifecycle, protocol, config, health and security tests are green;
- a complex local edit/refine uses the qualified MLX model, produces non-zero
  inference telemetry, grounds only reviewed tenant semantics, compiles cleanly
  and yields a Draft without Apply;
- Model 1 and play-demo remain Git-clean and no tenant file changes;
- an independent Orchestra audit is GREEN;
- authoritative `make check`, commit, push and post-push clean-main alignment
  are complete.

## Status

`COMPLETE — LIVE MODEL PROOF, GATES, COMMIT AND PUSH GREEN`

## Evidence wire

- DONE — preflight roster `in=1 out=1 distinct=1 gaps=0`: repository, baseline,
  writable surface, exclusions, model path and verification boundary confirmed.
- DONE — L301 read-only design roster `in=1 out=1 distinct=1 gaps=0`: a
  dedicated exact `warmup` worker operation is the minimal compatible proof of
  completed model/adapter load without synthetic inference; startup failure
  must precede binding/readiness and close every partial resource.
- DONE — L302 semantic census roster `in=10 out=10 distinct=10 gaps=0`: the
  complex edit may use reviewed `Film`, `Movie`, `ITALIA`, `Finzione`,
  `Live action`, `Thriller`, `Romantico`, `Vendetta`, `Maschio` and `Umano`
  values from the local play-demo snapshot. The superficially attractive
  “bianco e nero/premi/finale aperto/masterplot Revenge” request is rejected as
  a success-case because those concepts are absent or semantically unsafe.
- FIX — strict model config now supports backward-compatible `lazy` and
  explicit `on_start`; the play-demo fixture selects `on_start`.
- FIX — every newly spawned qualified worker completes a versioned load-only
  handshake before it can serve generation. This also covers bounded recycle;
  no dummy prompt or generated token is used for warmup.
- FIX — Brain startup calls warmup before HTTP bind and health exposes only
  policy/status/bounded duration and worker-load milliseconds.
- DONE — focused implementation roster `in=75 out=75 distinct=75 gaps=0`:
  MLX protocol/lifecycle, strict config and server startup/health suites green;
  targeted Ruff and `git diff --check` green.
- FACT — first natural-language complex probe stopped before inference after
  `15253 ms` retrieval: the strict resolver found unresolved prose and the
  contraction in “l'endpoint” spuriously matched legacy channel code `LA`. No
  proposal, compile or tenant write occurred; this is not a model success.
- FACT — first canonical 10-selection probe used three real generations
  (`69048 ms`, `82657 ms`, `99064 ms`) and failed closed on exact grounding
  before compilation. A one-generation diagnostic showed that Model 1 treated
  the edit as a delta: it kept prior variable/boolean predicates and omitted
  fixed `tipologia = "Film"`; the oracle correctly rejected it.
- FIX — the model prompt now declares edit/repair `grounding.selections` to be
  the complete final finite-predicate set, not a delta. Prior variable,
  boolean or other finite predicates absent from the set must be removed, and
  every reviewed selection emitted exactly once.
- DONE — final qualified complex-edit roster
  `in=10 out=10 distinct=10 gaps=0`: `generation_strategy=model`, zero repairs,
  retrieval `15458 ms`, generation `62071 ms`, compile `658 ms`, prompt `5987`
  tokens, output `326` tokens, `finish_reason=stop`, peak Metal `20.10 GB`,
  grounding resolved, compiler green and `tenant_modified=false`.
- FACT — final startup receipt: total service construction `23039 ms`, worker
  handshake `9937 ms`, actual MLX weight load `1469 ms`; health reported
  `model_loaded=true` before the turn, and generation reused that warm worker.
- DONE — no-Apply safety roster `in=3 out=3 distinct=3 gaps=0`: Model 1 diff
  unchanged during the run, play-demo Git state and target source unchanged,
  and Apply preflight was never called.
- DONE — L303 independent focused/static red-team is GREEN with `P0=0`. Its
  three findings were closed: every worker now re-attests the loaded adapter
  digest and model revision, a broken worker clears stale warmup timings, and
  an already-cancelled cold request cannot start or load the model.
- DONE — L303 final post-fix re-audit is GREEN with `P0=0 P1=0 P2=0`; the
  declared worker pin exactly matches the current worker source digest.
- DONE — wider Brain regression roster `in=448 out=448 distinct=448 gaps=0`:
  runtime, config, server, orchestrator, turns, retrieval, compiler tools,
  grounded renderer and candidate-grounding suites green after the red-team
  fixes.
- DONE — post-fix real load-only handshake: Brain reached `ready` with
  `model_loaded=true`; total handshake `10826 ms`, worker load `1713 ms`, and
  exact model/adapter identities matched. Shutdown left no MLX worker and both
  repositories remained Git-clean apart from this authorized Model 1 diff.
- RISK — free-form complex Italian is not yet a qualified success path: the
  current resolver can spuriously map the contraction in “l'endpoint” to the
  legacy channel code `LA` and leaves unsupported prose unresolved. The
  canonical reviewed 10-selection request is green; natural-language intent
  normalization remains a separate accuracy/UX wave.
- DONE — authoritative repository gate `make check`: foundation `85/85` with
  zero errors; whole-repository Ruff and formatting green; test harness
  `in=2645 out=2645 distinct=2645 gaps=0` with `2643 passed`, `2 skipped`,
  `0 failed` in `3281.65 s`.
- FACT — one stale red-team `make check` process remained alive despite that
  lane reporting it interrupted. L0 identified and terminated only that exact
  orphan process group; the authoritative L0 gate then ran alone to completion.
- DONE — implementation and evidence commit
  `2ad726f99afefc19db6395ea15f436f420fd1771` pushed to `origin/main`; local
  `HEAD` and `origin/main` matched and the worktree was clean before this final
  ledger closure.
