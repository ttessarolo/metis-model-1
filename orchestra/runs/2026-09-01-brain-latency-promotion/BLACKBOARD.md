# Metis Brain latency promotion wave

Status: **ACTIVE — CHECKPOINTED FOR HOST RESTART AT THE INSTALLED VS CODE GATE**

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

## Lossless integration closure and hard-prompt corpus

- FACT — The Metis delivery is now present on both local `main` and
  `origin/main` at exact revision
  `2ad60b3c804fb1c45e45883b0479a46f660d98f6`, tree
  `ea29b935934fadd5f99711c0470566a2484b35f6`; the prior remote-reachability
  STOP is superseded.
- FIX — The Brain toolchain pin now binds tooling `0.23.97`, Langium `4.3.0`,
  language `0.43`, grammar
  `sha256:dbbb2cf98f870d854af9082cb8ee33595054e993d7831d662170aeea0db8db01`,
  Node `v22.22.3`, and all lossless source/spec/gate blobs. Evidence roster is
  `in=29 out=29 distinct=29 gaps=0`.
- DONE — L0 accepted the executable archive seal: exact probe roster
  `in=9 out=9 distinct=9 gaps=0`, pinned Node, private Git archive, scratch-only
  writes, network/home/snapshot denied. Probe receipt is
  `sha256:03a3c626aad54779b8ca2a6b4d55b2d600eb8f31c0f40611d9f82f0ac2149e06`.
- FIX — Brain EditPlan v2 now carries only typed, opaque and single-use host
  references. Server authority owns path, AST node/preimage, payload,
  placement/delete mode, workspace base, current edit source, proposal basis,
  context and toolchain binding; raw authority never enters a model or public
  proposal.
- FIX — The pinned Brain runner exposes bounded `lossless-inventory` and
  `lossless-apply` operations. Inventory binds exact Endpoint -> direct Take ->
  direct IncludeClause AST/CST ancestry; apply is forced to
  `compileProof=validate` on the private full-session snapshot. Python validates
  the closed receipt, exact before/after hashes, touched span and untouched
  prefix/suffix before publication.
- FIX — Existing-endpoint lossless eligibility is deliberately narrow: one
  exact direct include, reviewed finite selections, exact take, no fallback,
  and existing finite-field roster equal to the final grounding roster.
  Comments, guards, variables, booleans, extra fields or an unprovable predicate
  surface cannot enter the renderer.
- FIX — A preservation conflict cannot silently fall through to Model 1.
  Plain, inline-comment and block-comment variants with an existing technical
  field absent from grounding return `EDIT_PRESERVATION_CONFLICT` before any
  model, lossless apply or ordinary compile call. This supersedes the earlier
  STOP over destructive fallback.
- DONE — Real pinned integration proof, not a fake: canonical `play-demo` was
  captured read-only, the one test surface was changed only inside an in-memory
  snapshot, and Brain executed inventory -> apply(validate full snapshot) ->
  independent receipt validation -> endpoint compile in `19786 ms`. Candidate
  hash is
  `sha256:ab0f00e779bb4d8a6ab1be9fd7ca5fc95e76db0011d8cee4fa70136a268c22a8`,
  lossless receipt
  `sha256:e03a916cc2d4d0289551fbd6b9423954427c08c3d14f9b7bf7a2d4de1f12b9f9`,
  compile receipt
  `sha256:ed9ce30fc8eafc5e32e988619407640e9823d8fb62ecc3d2ceb39c4312b7f709`;
  Model 1 calls `0`, tenant writes `0`.
- FACT — Post-proof canonical identities are unchanged and clean:
  `Developer/play-demo` at
  `44aa8ec170003b3822db71cb9443c8e7db9e3dd0`; Metis local/remote at exact
  `2ad60b3c804fb1c45e45883b0479a46f660d98f6`.
- DONE — Focused lossless integration denominator is
  `in=247 out=247 distinct=247 gaps=0`: EditPlan `12`, lossless bridge `26`,
  orchestrator `157`, toolchain pin `16`, compiler tools `24`, isolated harness
  `10`, TurnStore workspace-base/proposal-basis boundary `2`; Ruff, format and
  diff checks GREEN. This includes CRLF, Unicode outside the touched node,
  UTF-16 mid-surrogate corruption, role laundering, ancestry, receipt tamper,
  refine lineage, event ordering and private-path redaction.
- DONE — Read-only `play-prod` hard-path census examined `176` property files,
  `170` endpoint files and `170` endpoint declarations, then selected ten
  distinct complex endpoints. Artifact
  `examples/metis-brain-hard-prompts.play-prod-v1.json` contains
  `10` edit prompts plus `10` four-turn create/refine journeys with capability
  coverage for multi-block, parametric blocks, fallback, pagination, view-all,
  expanded response and alternatives: `in=10 out=10 distinct=10 gaps=0`.
  Tenant remained clean at
  `5f56bdfe27e3fb00b735db630a4eb5cdf5ab12c3`; no Apply/model/network occurred.
- FACT — `lossless_renderer` means zero Model 1 calls only on an already-resolved
  route. If the first retrieval was unsupported, Flash may have run before the
  lossless decision; public identity retains that processing route and no
  broader zero-model claim is made.
- DONE — Independent final red-team verdict for the bounded lossless lane:
  GREEN, `P0=0 P1=0`. Plain and block-comment preservation attacks both stop
  with `EDIT_PRESERVATION_CONFLICT`; Model 1, lossless apply and ordinary
  compile call counts are all zero.
- RISK — Non-blocking `P2`: a proposal-basis refinement that intentionally
  removes or fully replaces an existing field is currently refused by the same
  preservation guard. This is a conservative capability restriction, not data
  loss. Re-admission requires an explicit, server-validated removal authority;
  proposal basis alone is not treated as permission to delete a constraint.
- OPEN — Authoritative post-integration `make check` on the final diff.
- OPEN — Installed VS Code Draft-only proof of the admitted path, with no Apply
  and canonical tenant identity unchanged.
- OPEN — Final board verdict, commit, push, origin alignment and clean-tree
  audit.

## Final integration gate and installed-client preflight

- DONE — Authoritative post-integration `make check` completed with exit `0`:
  foundation `in=86 out=86 distinct=86 gaps=0`, whole-repository Ruff and
  formatting GREEN, pytest `2900 passed, 2 skipped, 0 failed` in `2898.77 s`,
  and the post-run Metis Git/tree/runtime authority seal GREEN. The earlier
  post-integration OPEN is superseded.
- DONE — L610 performed a read-only census of every current `play-demo`
  endpoint. No persisted endpoint is fully inside the one-direct-take lossless
  subset: `demo.a_b_test` is the only structural candidate but owns an inline
  comment inside its include, while every other endpoint has variables,
  guards, booleans, nested/multiple takes or another unsupported surface. The
  installed positive proof must therefore use the admitted create-Draft path;
  the compiler-owned lossless path remains separately proven by the real
  pinned inventory/apply/compile receipt above. No tenant fixture will be
  edited to manufacture an eligible UI case or to overstate the refine route.
- FACT — Installed VS Code exposes `metis.metis-dsl@0.23.97` and the native
  `@metis` participant on the clean `~/metis-tenants/play-demo` workspace at
  `bfd6cbe4c7b06cc00a2493eac34db02887bc997b`. The first real chat request
  returned `Language model unavailable` in `2 s`: Brain was not configured in
  that workspace, so no generation or tenant mutation occurred.
- FIX — The non-secret demo fixture and its contract test now bind the same
  workspace actually open in VS Code,
  `/Users/tommasotessarolo/metis-tenants/play-demo`, instead of the separate
  stale clone under `Developer/play-demo`. The gitignored local VS Code
  settings now provide the qualified Brain executable, config and `visix`
  client id. Config tests are `in=13 out=13 distinct=13 gaps=0`; Ruff, format
  and diff checks are GREEN. Config/server focused tests are
  `in=38 out=38 distinct=38 gaps=0`. No tracked tenant file or endpoint source
  changed.
- DECISION — The owner-authorized installed-client preflight may add only the
  three non-secret `metis.brain.*` keys to the already gitignored local VS Code
  settings. This is local launch configuration, not tenant semantic source;
  endpoint/catalog files, installed VSIX bytes and Git-tracked tenant state
  remain read-only.
- DONE — The installed extension payload is byte-identical to the packaged
  `metis-dsl-0.23.97.vsix` in the Metis integration worktree: extension bundle
  SHA-256
  `b4b4b350b4501b7685a7f2c51b90af70a44dbe23911c8d91e29b7e62889f68b3`.
- DONE — The hard-prompt artifact now has a repository contract gate covering
  the exact endpoint/edit/journey mapping, safe relative source paths, source
  hashes, non-empty semantic/compiler/Draft oracles, four-turn action order and
  read-only/no-Apply boundary: `in=4 out=4 distinct=4 gaps=0`, Ruff and format
  GREEN.
- DONE — Independent read-only delivery census after the integration work:
  changed-path roster `in=25 out=25 distinct=25 gaps=0`, `P0=0`; focused source
  suite `281 passed`, the subsequently added hard-prompt contract `4 passed`,
  changed-Python Ruff/format and `git diff --check` all GREEN. No secret,
  `.env`, credential, private key, raw tenant payload, dataset, model weight,
  adapter or checkpoint payload is tracked. The three existing local commits
  plus this dirty delivery remain intentionally unpushed until the installed
  Draft proof closes.
- OPEN — Repeat the installed `@metis` create-Draft after the Mac is unlocked;
  inspect the Draft, never invoke Apply, and recheck tenant HEAD/status. A
  same-session refine may additionally verify volatile dialogue UX, but is not
  claimed as a positive lossless edit because the target remains create-mode.
- OPEN — Final board verdict, commit, push, origin alignment and clean-tree
  audit after that installed-client proof.

## HOST-RESTART CHECKPOINT — 2026-09-02 08:09 CEST

Read this section first after reboot. It is the single resume authority for the
unfinished wave.

### Durable state already closed

- DONE — Source implementation, compiler-owned lossless bridge, Metis pin
  `2ad60b3c804fb1c45e45883b0479a46f660d98f6`, red-team, hard-prompt corpus,
  executable archive proof and full `make check` are closed by the evidence
  above. Do not repeat the 48-minute full gate unless a production source,
  runtime, schema, manifest or test changes after this checkpoint.
- DONE — The hard-prompt artifact is
  `examples/metis-brain-hard-prompts.play-prod-v1.json`: ten distinct real
  `play-prod` endpoints, ten inspectable edit prompts and ten four-turn
  create/refine journeys. Its dedicated contract has four passing tests.
- DONE — The current installed extension is
  `metis.metis-dsl@0.23.97`; its installed bundle matches the packaged VSIX at
  SHA-256
  `b4b4b350b4501b7685a7f2c51b90af70a44dbe23911c8d91e29b7e62889f68b3`.
- DONE — The VS Code workspace tenant is
  `/Users/tommasotessarolo/metis-tenants/play-demo`, clean on `main` at
  `bfd6cbe4c7b06cc00a2493eac34db02887bc997b`. The non-secret Brain fixture now
  binds this exact root. Its gitignored `.vscode/settings.json` already contains
  canonical `metis.brain.executablePath`, `metis.brain.configPath` and
  `metis.brain.clientId=visix`; do not rewrite it after reboot unless one of
  those paths is missing.

### Last observed live state

- FACT — VS Code was open on `~/metis-tenants/play-demo`. A native `@metis`
  create request was submitted before the settings fix and returned
  `Language model unavailable` after `2 s`. It produced no Draft, model turn,
  Apply or tenant mutation.
- FACT — The settings/config alignment was then fixed and passed the exact
  config/server focused suite (`38 passed`). The Mac locked before the corrected
  request could be retried.
- FACT — Immediately before this checkpoint there was no surviving Brain,
  Model 1 or Flash worker process. After reboot the VSIX must therefore perform
  one normal `on_start` warmup; historical measured startup with both workers
  was about `31.5 s`, inside the VSIX `60 s` readiness deadline.
- FACT — No QWEN-labelled delegated lane was used in this final installed-proof
  segment. Existing Qwen3.8-27B Model 1 remains the configured qualified model;
  this note refers only to Orchestra task routing.

### Exact resume procedure — do not broaden it

1. Open `/Users/tommasotessarolo/metis-tenants/play-demo` in VS Code and verify
   `metis.metis-dsl@0.23.97` is active.
2. Verify the Model 1 repository is clean and aligned with `origin/main` at the
   pushed checkpoint. If it is not clean, inspect before changing anything.
3. Start a new native Chat, type `@metis`, accept the participant, and submit
   exactly:

   > Nel tenant già aperto, crea una nuova bozza dell endpoint
   > demo.brain_lossless_smoke as brainLosslessSmoke: take 12 from @video,
   > includendo solo tipologia Film e genere_mcm Azione, con risposta standard.
   > Non applicare nulla.

4. Wait for the startup-warm local server and terminal chat result. Expected
   positive surface: compiled proposal, reviewed mappings for `tipologia=Film`
   and `genere_mcm=Azione`, plus `Apri bozza`, `Applica`, `Scarta`.
5. Click **only** `Apri bozza`. Never click `Applica`. Inspect that the Draft
   contains `metis 0.43`, an exact `take 12 from @play-demo.video`, the two
   reviewed predicates, and `return response.default` without legacy `val ...`
   literals or invented filters.
6. Record visible elapsed time and result. Recheck the tenant remains exactly
   on HEAD `bfd6cbe4c7b06cc00a2493eac34db02887bc997b` with empty tracked/untracked
   status. Do not use the failing Metis Serve preview as Brain evidence: the VPN
   is intentionally down and that separate serve failure is outside this gate.
7. A same-session refine is optional UX evidence and must not be described as a
   positive lossless edit: a Draft-created target remains create-mode. The
   positive lossless claim is already closed only by the pinned real
   inventory/apply/receipt/compile proof above.
8. Append the live FACT/DONE or STOP here. If GREEN, change Status to
   `COMPLETED`, close the two final OPEN entries, run the bounded Git/diff checks,
   commit the closure note, push `main`, and verify `HEAD == origin/main` with an
   empty worktree.

### Fail-closed restart rules

- No Apply, tenant source edit, VPN, OpenSearch, `.env`, Keychain, remote model,
  Ollama, model download, training or new endpoint fixture is authorized.
- Do not mutate `demo.a_b_test` merely to manufacture a positive lossless UI
  case; its inline comment intentionally keeps it outside the admitted subset.
- If the corrected request again reports unavailable, capture the exact visible
  error and stop the UX gate. Do not weaken warmup, grounding, compiler,
  isolation or the 60-second client deadline to force green.
