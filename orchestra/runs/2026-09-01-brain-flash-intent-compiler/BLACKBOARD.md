# Metis Brain Flash intent compiler blackboard

## Objective

Qualify and integrate one second, always-warm, direct-MLX runtime inside Metis
Brain. The Flash runtime converts the operator's natural-language request into
one small schema-constrained Intent IR. It may normalize intent and identify
ambiguity, but it never owns catalog, field, value, endpoint or DSL authority.
Reviewed retrieval, deterministic grounding, Model 1 where still required and
the pinned Metis compiler remain the acceptance chain.

## Preflight

- FACT — L0 starts from clean `main@1ae766fb2137386b66c669db5b156d8041a9fc20`,
  aligned with `origin/main`.
- FACT — the current qualified Model 1 path is a persistent custom Python JSONL
  worker using MLX/MLX-VLM directly; Ollama and `mlx-lm.server` are not in the
  serving path.
- FACT — the current complex edit proof spends about `62 s` in Model 1
  generation after startup warmup; the Flash runtime is useful only if it
  reduces end-to-end latency without weakening semantic or compiler gates.
- FACT — product/session/local-latency contracts were reread in
  `docs/19-local-companion-and-vscode-direction.md`,
  `docs/22-metis-brain-session-wave.md`,
  `docs/23-metis-brain-local-runbook.md`,
  `docs/26-metis-brain-interactive-session-wave.md` and
  `docs/27-metis-brain-local-latency.md`.
- FACT — the operator's current instruction authorizes this dedicated
  implementation and local qualification wave, including acquisition of the
  one selected public Flash checkpoint after its exact revision, license,
  provenance and runtime have passed pre-download review.
- STOP — no training, adapter or weight mutation, Ollama, remote fallback,
  credentials, `.env`, Keychain, VPN/live data, external repository write,
  tenant write, Apply, persistent conversation memory or Windows abstraction is
  authorized.
- STOP — no checkpoint may enter Git. Model payloads and runtime caches remain
  under ignored artifact/cache roots with manifest, revision and hashes.

## Decisions

1. Flash is an internal Brain component, not Model 1 and not a new public
   endpoint. Brain remains the only HTTP authority exposed to clients.
2. Flash output is accepted only when token generation is constrained by the
   declared JSON Schema and the result also passes strict host-side validation.
   Prompted JSON or post-hoc repair alone does not qualify.
3. Flash produces Intent IR only. It never emits `.metis`, invents canonical
   catalog/field/value identifiers, bypasses reviewed retrieval or weakens exact
   candidate grounding.
4. The runtime is startup-warm, persistent and supervised. Failed warmup,
   schema mismatch or stale identity fails closed for the Flash path; the
   existing qualified Brain path may continue only under an explicit bounded
   fallback policy that cannot reinterpret Flash output.
5. Session memory remains Brain-owned, volatile and revision-bound. Flash is
   stateless across requests apart from model/runtime caches.
6. Adoption is evidence-driven. The first candidate is Gemma 4 E4B instruction
   MLX, subject to exact checkpoint/runtime qualification and local A/B gates;
   no product claim is made from community benchmark numbers.

## Acceptance gates

- exact runtime release, model repository, immutable revision, upstream
  provenance, license and materialized file hashes are recorded before use;
- constrained decoding is proven with adversarial JSON-Schema cases, including
  enums, required fields, additional-property denial and malformed-prompt
  attempts;
- strict Intent IR validation has a closed schema, bounded strings/arrays and
  zero authority-bearing catalog/field/value literals;
- Italian intent tests cover create/edit/refine/repair/review, exact result
  count versus pagination, output shape, fallback request, ambiguity and the
  `l'endpoint`/legacy-code collision;
- deterministic grounding remains the only catalog/value authority and every
  generated candidate still passes exact grounding plus the pinned compiler;
- startup warmup, reuse, timeout, crash/recycle, shutdown and zero-orphan
  cleanup are covered; health exposes only bounded identity/state/timing;
- local qualification reports exact startup, the full five-case warm latency
  range, schema/host validity, one genuinely escalated Model 1 E2E, total
  latency and peak Metal memory on this Mac. Distributional p50/p95, a frozen
  semantic-accuracy denominator and bypass/escalation rates require a separate
  benchmark roster and are explicit promotion backlog, not claims of this
  bounded development seal;
- one genuinely complex natural-language no-Apply E2E produces a compiled
  Draft or fails closed with an exact reason; tenant state remains unchanged;
- focused tests, independent Orchestra red-team, authoritative `make check`,
  diff review and final board verdict are green before promotion.

## Status

`COMPLETE — GREEN`

## Evidence wire

- DONE — preflight roster `in=1 out=1 distinct=1 gaps=0`: repository, baseline,
  writable surface, exclusions, current Model 1 serving path and required
  documents confirmed.
- DONE — read-only architecture roster `in=3 out=3 distinct=3 gaps=0`: current
  runtime census, checkpoint/runtime qualification and Intent IR authority
  review completed; no delegated lane changed the repository.
- FACT — the selected checkpoint is
  `mlx-community/gemma-4-e4b-it-4bit@475b9088d29754a3379866cf5aeb6b41acd313c2`,
  derived from `google/gemma-4-E4B-it@fee6332c1abaafb77f6f9624236c63aa2f1d0187`;
  its declared license is `gemma`, therefore distribution approval remains
  explicitly open.
- FACT — the exact ten-file checkpoint roster is materialized only under the
  ignored `artifacts/brain-flash-intent-v1/model` root; the tracked candidate
  manifest records every byte size and SHA-256 and Git continues to exclude
  the payload.
- DONE — final direct local constrained-decoding probe
  `in=5 out=5 distinct=5 gaps=0`: one persistent Gemma worker loaded in
  `1673 ms`; five schema-constrained Italian generations completed in
  `1202–1588 ms`, `73–101` generated tokens, `79.26–82.65 token/s`, at most
  `5.797 GB` peak Metal, all with `finish_reason=stop`, valid JSON Schema,
  valid host IR and an executable exact-span projection.
- RISK — constrained structure did not itself reject prompt-control prose: one
  hostile request was initially copied into a concept. Host validation now
  rejects prompt-control and UX scaffolding, requires exact operator spans and
  refuses executable retries for negative, mixed or unknown logic.
- DONE — Intent IR adversarial host suite `in=74 out=74 distinct=74 gaps=0` is
  green, including authority-key injection, duplicate/NaN JSON, exact-span,
  count/role normalization, response/ordering scaffolding, prompt injection,
  polarity and logic gates.
- FIX — a distinct persistent `MlxFlashIntentRuntime`, standalone llguidance
  worker, closed schema and initial Brain/config/orchestrator/retrieval wiring
  are implemented in the current diff.
- FACT — final production identities are worker
  `sha256:12a7966ec8acd8f4386f6df57fd1165a1456c152f4707e3d5b2a6cee4b4f8b69`,
  manifest
  `sha256:195b2af4ce0b34e57643a7f64cc7493968334e9cfc03f0059850e4b5f1ae5507`
  and canonical Intent IR schema
  `sha256:972eb339d8f0f22f4d5dd43aa9f4f74ae49e2a6e2b3b7ff536a60444edd864fa`.
- DONE — runtime lifecycle roster `in=43 out=43 distinct=43 gaps=0`: warmup,
  reuse, timeout, cancellation, invalid JSON/telemetry/identity, crash, recycle,
  bounded close and zero-orphan behavior pass.
- DONE — Brain wiring roster `in=10 out=10 distinct=10 gaps=0`: exact config,
  pre-bind warmup, health, construction cleanup, retry, cardinality, fail-closed
  and session reuse pass.
- DONE — retrieval seam `in=1 out=1 distinct=1 gaps=0`: an intentionally wrong
  advisory `query=Sport` cannot override exact operator `source=Film`; count 24
  remains owned by the deterministic output parser.
- FIX — a live probe exposed output-format/ordering prose being segmented as a
  catalog concept and a generic `protagonista` residue. The final worker prompt
  excludes response/order controls, host validation rejects them, and the host
  keeps only exact qualifier subspans without inventing tokens. The first
  pre-fix E2E failed safely; the same reviewed values then grounded completely.
- DONE — complex no-Apply E2E `in=1 out=1 distinct=1 gaps=0`: request for 24
  films with mood Romantico, female human protagonist, preserved
  `response.expanded` and descending publication date produced one compiled
  Draft on the first candidate. Grounding resolved exactly
  `tipologia=Film`, `mood=Romantico`, `protagonistaSesso=Femmina` and
  `protagonistaSpecie=Umano`; `take 24` was emitted, compiler diagnostics were
  empty and `tenant_modified=false`.
- FACT — final live timing: startup with Model 1 and Flash warm `31540 ms`;
  turn `56420 ms`; Model 1 generation `42369 ms`, 4409 prompt tokens, 215
  generated tokens, `10.45 token/s`, `finish_reason=stop`, peak Metal
  `20.039 GB`. Flash remains `1.2–1.6 s`; the residual latency is Model 1.
- FACT — the play-demo tenant stayed at
  `bfd6cbe4c7b06cc00a2493eac34db02887bc997b`, clean, with target SHA-256
  `d0d5080803fbaa480302de2865422012cc5349ff8251988cbaabcf6d9dd2921c`
  before and after both E2E runs; no Apply was invoked.
- DONE — independent L410 audit verdict GREEN with `P0=0`, `P1=0`; the sole
  documentation P2 is closed by D-016, the dedicated Flash specification,
  architecture/roadmap/runbook/open-decision updates and rollback/nonclaims.
- DECISION — the original draft gate named p50/p95, semantic accuracy and
  bypass/escalation rates without a frozen denominator. They are not inferred
  from five qualification cases or one E2E: this local development seal reports
  the complete observed range and exact outcomes, while the distributional
  benchmark remains future promotion work.
- DONE — L410 post-documentation follow-up verdict
  `P0=0 P1=0 P2=0`: bounded acceptance wording and fallback authority now match
  the executable evidence; no closure finding remains.
- DONE — authoritative repository gate `in=2773 out=2773 distinct=2773 gaps=0`:
  foundation `85/85` with zero errors, whole-repository Ruff and formatting
  green, test harness `2771 passed, 2 skipped, 0 failed` in `3066.18 s`.
- DONE — wave verdict GREEN: Flash is qualified for the local Mac development
  demo as a non-authoritative, always-warm direct-MLX intent compiler. External
  Gemma distribution, app packaging, VSIX product integration, Metis Fast,
  remote fallback and persistent memory remain explicitly outside this seal.
- CROSS-WAVE ADDENDUM — L502 belongs to the successor low-latency wave and
  added only the new source-span bounded-edit module and focused tests;
  no existing runtime, compiler, renderer, tenant or model file was modified.
- DONE — bounded-edit test roster `in=3 out=3 distinct=3 gaps=0`: complex edit
  preserves untouched header bytes, `response.expanded` and publication-date
  ordering; stale hash/revision, comments, duplicate endpoints, unsupported
  surfaces, open domains and invented references all decline with `None`.
- RISK — the current compiler receipt exposes no pinned AST object
  (`src/metis_model1/brain_tools.py:716-759`), so the module is deliberately a
  fail-closed source-span subset and is not yet wired into Brain's ModelCandidate
  generator enum or orchestrator.
