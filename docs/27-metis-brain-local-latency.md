# Metis Brain: local latency and isolation

Status: **implemented, repository-qualified and live-measured; the prefix path
is measurably faster but not promoted, and the current installed-VS-Code proof
is still required for UX closure**.

## Problem

The installed Mac demo was technically correct but too slow for interactive
use. The first clarification was observed at about 56 seconds in the earlier
VS Code smoke. Its work completed before the MLX worker started, so that delay
was retrieval/toolchain cold start, not model inference. Cold semantic
projection and each compile also rebuilt an isolated Metis tree, copied about
199 MB / 17k `node_modules` entries, and repeated the full pin checks. In that
pre-warm baseline, model generation was lazy, serial, capped at 512 tokens, and did not expose enough
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

The worker now reports bounded numeric telemetry: worker request, cache
preparation, tokenization, generation, time-to-first-token (TTFT),
decode-after-first-token, residual worker/host time, prompt/generated/cached
token counts, an exact cache-hit flag, prompt and generation rates, peak Metal
memory, and `finish_reason` restricted to `stop` or `length`. The host also
measures the exact wait for the serialized model lock as
`model_lock_queue_ms`;
startup health separately reports worker load.

The pinned MLX-VLM API produces its first observable result only after dynamic
prefill and the first token have both completed. Therefore TTFT is deliberately
labelled as that indivisible interval: Brain does **not** claim a pure dynamic
prefill timer it cannot observe. Decode-after-first-token is separate. The
runtime validates the complete shape and bounds before exposing it in proposal
identity. No prompt, source context, hidden chain-of-thought, or internal
reasoning is exposed.

The local demo config sets `model.warmup` to `on_start`. Every new MLX worker
first accepts one exact versioned `warmup` operation and responds only after
the pinned checkpoint and adapter have loaded, passed their identity checks and
prefilled the immutable public prompt prefix. This runs model prefill but does
not generate a user response or consume user-turn output tokens. Health reports
`prefix_tokens` and `prefix_cache_ready`; a failed, timed-out or incomplete
prefill prevents HTTP readiness and closes the partial worker. The
backward-compatible `lazy` policy remains available for non-demo hosts.

The process-local public-prefix cache is implemented with startup prefill and
transient per-request clones. The persistent template is bounded and bound to
the worker/model/adapter and exact prefix identity; it is never passed to
generation, so tenant/session input and generated tokens cannot become part of
the reusable state. A cache miss falls back safely. Promotion still requires a
live positive cache-hit A/B and the full grounding/compiler matrix.

The 512-token cap remains unchanged. The measured baseline stopped normally
after 86 tokens, so reducing that cap would not address the observed delay. One
representative edit/refine is measured below, but repair, open-domain, and other
complex families are **not comprehensively claimed fast** until their benchmark
matrix is run.

## Public progress contract

The event stream exposes only allow-listed phase names, labels, sequence data,
and bounded metrics. Started/completed events cover retrieval, inference,
compile, and bounded repair; heartbeat events provide bounded elapsed progress.
Every event has a monotonic numeric SSE id. A reconnect supplies
`Last-Event-ID`; the server replays only events with a greater sequence. The
terminal envelope remains the authoritative proposal/validation result. Public
progress contains phase duration, not prompts, tenant values beyond the
existing proposal contract, source internals, or chain-of-thought.

## Frozen A/B receipt runner

The runner starts one persistent prefix-qualified worker, executes one excluded
preflight for each physical path (`direct`, then `prefix`), and only then runs
six adjacent pairs counterbalanced AB/BA. Request, source, snapshot, seed,
output budget, reviewed selections, requested take, ordering, response form and
first-attempt compiler result must remain identical. The two preflight
projections are retained as redacted hashes and are not counted in the 12
measured observations.

The receipt binds the exact case bytes, clean Model 1 commit/tree, tenant
commit/tree/roster/target, model/adapter/worker/prefix, semantic/toolchain
identity, and Flash identity if the bounded retry route was actually used. A
structural oracle verifies endpoint name, top-level order and exact response;
the compiled-endpoint hash is required to remain identical to the preflights
but is not mistaken for a formatting-independent semantic oracle. Receipt
creation walks from the fixed ignored root through no-follow directory
descriptors and holds the exact parent descriptor until all post-write guards
pass. Bytes are first fsynced under a random dot-pending name. The final receipt
name is published create-only, through the retained parent descriptor, only
after those guards pass; discard or a pre-publication crash therefore cannot
leave a file that looks like an accepted final receipt. A distinguishable
`.pending` file may remain after an abrupt process death and is never admitted
as evidence.

The runner writes only this redacted receipt below
`artifacts/metis-brain-latency/`. The bounded command is:

```bash
uv run metis-model1 brain-latency-benchmark \
  --config /Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-config.play-demo.local.json \
  --case /Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-latency.play-demo.json \
  --output /Users/tommasotessarolo/Developer/metis-model-1/artifacts/metis-brain-latency/play-demo.json
```

The receipt retains per-observation telemetry, event/heartbeat counts,
grounding/compiler/source hashes and tenant guards. Replay verifies the full
roster, including both excluded preflights, but independent review must still
compare `case_sha256` with the exact committed case.

The frozen Mac run on 2026-09-01 completed six counterbalanced pairs and
published receipt
`sha256:e738425cd806412eea44327d7915bd774832c4868a71068ef8fb01ba1c6a0172`.
Replay is exact; denominator is `in=12 out=12 distinct=12 gaps=0`; all source,
grounding, shape, compiled-endpoint and tenant-integrity claims are true. Its
verdict is `MEASURED_NOT_PROMOTED`:

| Metric | Direct | Prefix | Promotion requirement |
|---|---:|---:|---:|
| inference p50 | 60099 ms | 39498 ms | prefix <= 60% of direct; observed 65.7% |
| inference p95 | 82470 ms | 59098 ms | prefix <= 70% of direct; observed 71.7% |
| turn p95 | 88873 ms | 66876 ms | prefix <= 25000 ms |
| TTFT p50 | 36351 ms | 17072 ms | diagnostic |
| decode-after-first-token p50 | 22039 ms | 22403 ms | diagnostic |

Prefix caching therefore closes a real prefill cost but is insufficient for a
fast operator experience. It remains qualified evidence, not the production
default promoted by this gate. The next optimization must reduce decode and
the still-large prefix TTFT while preserving the exact same semantic and
compiler oracles.

## Optimization boundary and fail-closed compiler

The public-prefix cache is the only currently compatible optimization.
Speculative decode is **STOP**: qualified Qwen has no compatible drafter/MTP
payload, and no new downloads are authorized. The lossless compiler renderer
handover dated 2026-09-01 passed its local artifact audit, including the whole
corpus and all five probes on the Brain-pinned Node. That does not enable the
path: Brain still requires a remotely reachable pinned revision, an executable
probe seal, a typed opaque-reference registry, exact base/preimage binding,
mandatory full-tenant `compileProof=validate`, and strict receipt translation.
Until all those gates are green, `EditPlan` remains fail-closed. Compile-clean
output alone does not close this gate.

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

The following Mac measurements are L0-reported read-only observations from the
interactive qualification logs; they are not a machine-sealed benchmark
receipt. No tenant was modified and no Apply was performed.

| Flow | Total | Public phase timings |
|---|---:|---|
| Cold clarification | 11073 ms | clarification completed before model inference |
| Post-answer proposal | 1574 ms | retrieval 861 ms; compile 696 ms |
| Cold one-turn explicit request (`24` total), final qualified source | 11067 ms | retrieval 10451 ms; compile 602 ms |
| Installed VS Code `v0.23.97`, fresh extension host and Brain child | 31 s | compiled Draft visible; no Apply |
| Qualified 27B baseline before prompt projection | 153852 ms generation wall | 17240 prompt tokens; 86 generated; `stop`; load 3493 ms |
| Qualified 27B edit/refine after final prompt projection | 34319 ms generation wall | 3700 prompt tokens; 72 generated; `stop`; compile 781 ms |
| Startup-warm complex 10-filter edit | 101347 ms including service construction | service 23039 ms; retrieval 15458 ms; generation 62071 ms; compile 658 ms |
| Prefix-cached complex four-filter edit | 46775 ms turn | exact cache hit 2241/4441 prompt tokens; generation 31824 ms; 217 output tokens; compile attempt 1 |

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

The startup-warm complex proof deliberately edited an existing endpoint so
the create renderer was ineligible. It resolved ten reviewed finite
selections, reported `generation_strategy=model`, generated 326 tokens from a
5987-token prompt with `finish_reason=stop`, and compiled on the first
candidate. The worker handshake took 9937 ms, of which the worker reported
1469 ms for actual weight loading; peak Metal memory was 20.10 GB. Exact
grounding was green, `tenant_modified` remained false and Apply preflight was
never invoked.

After the final lifecycle hardening, a second real load-only startup probe
completed the identity-bearing handshake in 10826 ms and reported 1713 ms of
worker load. Brain compared the worker's model revision and adapter digest with
its pinned identity before readiness, then shutdown left no worker process.

The probe also exposed and closed a serving-level edit defect. Before the
prompt contract was tightened, Model 1 treated reviewed selections as a delta,
kept old variable/boolean predicates and omitted one fixed selection. The
grounding oracle rejected all candidates before compilation. The prompt now
states that edit/repair `grounding.selections` is the complete final finite
predicate set; the corrected run converged without a repair or weight change.

The subsequent exact-prefix-cache proof ran the same request shape on the
canonical `Developer/play-demo` workspace. It reused `2241/4441` prompt
tokens, generated 217 tokens in `31824 ms`, and completed the turn in
`46775 ms`. Exact grounding was green, the first compiler attempt returned zero
diagnostics, and the tenant identity was byte-identical before and after. The
preceding `42369 ms` model / `56420 ms` turn observation used a separate local
tenant snapshot; the apparent reductions of `24.9%` and `17.1%` are therefore
cross-run direction only, not a paired A/B. One observation is not a p50/p95
denominator and misses the declared promotion threshold; roughly `20.7 s` of
output decode remains the dominant measured floor.

## Warm-runtime contract

The demo profile is warm when Brain announces readiness. The same process is
reused for up to 120 generated requests or until Brain closes or the worker
fails. A newly spawned replacement completes the same load-only handshake
before its first generation. A controlled recycle therefore has a short
reload interval; this design deliberately does not keep a second 27B hot copy
in memory.

Health exposes `model_warmup` with only the configured policy, one bounded
state, total handshake duration, worker-reported load duration, public-prefix
token count and `prefix_cache_ready`. It also exposes `model_loaded`; no model
path, prompt, source, tenant value or hidden reasoning is included.

Warmup moves both the roughly 1.4–3.5 second measured worker-load cost and the
public-prefix prefill outside the first ordinary model turn. Each turn restores
that public state into a transient cache clone and discards the clone after the
request. It does not eliminate dynamic request prefill or output generation,
and its latency benefit remains a measured qualification gate rather than an
assumption.

## Successor Flash intent wave

The subsequent Flash wave adds one separate startup-warm Gemma 4 E4B worker.
It uses direct MLX/MLX-VLM and `llguidance` token masks; it does not add Ollama,
another HTTP server or another copy of Qwen. Flash runs only after an
unsupported deterministic retrieval and may return only the closed,
non-authoritative Intent IR described in
[`28-metis-brain-flash-intent-compiler.md`](28-metis-brain-flash-intent-compiler.md).

The final five-case qualification measured `1.202–1.588 s` per warm Flash
generation and about `5.797 GB` peak Metal. A real existing-endpoint request
that required four reviewed fields then completed end to end in `56.420 s`:
Flash enabled exact grounding; Model 1 used `42.369 s` for 4,409 prompt and 215
generated tokens; the first candidate compiled; no Apply or tenant mutation
occurred. Startup with both workers warm took `31.540 s`.

This changes the cost of intent segmentation, not the generation rate of the
27B model. The measured residual bottleneck is still Model 1. Prompt/KV cache,
shorter qualified candidate formats or additional deterministic rendering are
separate evidence-driven optimizations; the Flash result is not permission to
weaken grounding or compiler gates.

## Verification

Use synthetic fixtures and the already authorized local pin only; do not put
credentials, tokens, `.env` files, or tenant payloads in commands or artifacts.

```bash
uv run pytest -q \
  tests/test_brain_mlx_runtime.py \
  tests/test_brain_config.py \
  tests/test_brain_server.py \
  tests/test_brain_orchestrator.py \
  tests/test_brain_turns.py \
  tests/test_brain_semantic_retrieval.py \
  tests/test_brain_tools.py \
  tests/test_brain_grounded_renderer.py \
  tests/test_brain_candidate_grounding.py \
  tests/test_video_brain_grounding.py \
  tests/test_brain_intent_ir.py \
  tests/test_brain_flash_runtime.py \
  tests/test_brain_flash_wiring.py
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

The following counts belong to the preceding warm-runtime delivery, not to the
current prefix-promotion diff: foundation `85/85` with zero errors,
whole-repository Ruff and formatting green, and `2643 passed, 2 skipped, 0
failed`. The current diff is promoted only after its own `make check`, sealed
live receipt and installed-VS-Code Draft proof are recorded on the active
board.

The installed extension recovered its tenant and chat surfaces after a VS Code
window reload, and the final no-Apply Draft smoke passed. A deliberately killed
Brain child exposed a downstream operational limitation: the current VSIX
keeps its dead client until the extension host reloads. Automatic child restart
is a Visix integration backlog item, separate from the latency measurements and
from Brain's tenant-write boundary.
