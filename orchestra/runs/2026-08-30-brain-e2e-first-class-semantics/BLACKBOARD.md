# Metis Brain end-to-end and first-class catalog semantics blackboard

## Objective

Deliver one honest local vertical slice in which an authorized client opens a
tenant session, asks Metis Brain to author or revise an endpoint, receives
phase events and a `.metis` candidate, and gets a real pinned-toolchain compile
receipt. Replace the private `video -> video_pg` projection convention with a
first-class Metis `semantics from @catalog` contract, then prove the same Brain
session through both the VS Code integration boundary and the Metis Fast
integration boundary without granting either client autonomous tenant writes.

## Preflight

- FACT — Model 1 writable baseline is
  `main@0d997ccff9095b7c19c268f8fbe668ce4d78d889`; the checkout was clean before
  this run was opened.
- FACT — Canonical `play-demo` baseline is
  `main@2d130d635b5934ba5040f5ed64bed1548d0c0d03`; the checkout was clean at
  preflight.
- FACT — Metis preflight baseline was
  `main@72e513618ec38aa05b4f52fc60ccfe3aa13c84d4`. With the user's explicit
  authorization, the colleague-authored Brain/VSIX contract was reviewed,
  temporary build sidecars were classified and ignored, and the result was
  committed and pushed as `main@a11757f3b864e16f6b61914d0de42a90b627bed0`.
  Local and remote `main` matched and the shared checkout was clean afterwards.
- DECISION — `semantics from @video` is a native Metis language/retrieval
  contract. It transfers semantic ownership and provenance, never physical
  driver shape, endpoint IR, runtime behavior, or values into model weights.
- DECISION — L0 frontier owns syntax/semantics, trust boundaries, compiler-loop
  behavior, E2E acceptance, integration and promotion. Delegates perform
  read-only censuses and bounded mechanical implementation only after disjoint
  writable surfaces are assigned.
- STOP — Credentials, `.env`, Keychain, live services, raw production payloads,
  model downloads, training, weight mutation, fallback remote inference,
  autonomous tenant writes, and unrelated repository changes are excluded.
- FACT — L83 located Visix in Metis `tooling`: it has language, preview,
  WorkspaceEdit and serve infrastructure but no Chat Participant or Brain
  client. The VSIX write lane must start in a dedicated worktree after the
  native semantics commit; the dirty shared checkout is not writable.
- FACT — No separate Metis Fast repository exists. `atomic-video-player` is a
  clean legacy-backed predecessor; any successor work must be isolated and may
  not rewrite its `main` in place.
- FACT — L81 identified the exact grammar/AST/validator/formatter/retrieval
  surfaces and gates. `semantics from` is absent at the Metis baseline; a new
  worktree is mandatory because the shared checkout has another owner's dirt.
- FACT — Native semantics implementation now owns the isolated clean worktree
  `/Users/tommasotessarolo/Developer/ares-matioska/metis-semantics-from` on
  `codex/metis-semantics-from@a11757f3`; it cannot see or stage the shared
  checkout's ignored scratch/build files.
- FACT — L82 measured a reusable one-load MLX-VLM JSONL worker, the selected
  external adapter/checkpoint chain, offline schema-2 semantic retrieval and
  grounding-v2 ambiguity handling. None is currently connected to Brain.

## End-to-end acceptance contract

The wave is complete only if all of the following are independently observed:

1. Metis parses, links, validates and formats `semantics from @video`; missing,
   self, cyclic and incompatible sources fail closed.
2. Catalog retrieval for `@video_pg` follows the declared semantic source with
   explicit source/execution provenance and draft quarantine, while runtime
   context and compiled endpoint IR remain unchanged.
3. Brain opens an isolated tenant session, derives tenant/catalog context from
   that session, generates or revises a bounded `.metis` candidate using the
   existing local Model 1 runtime, and runs a bounded diagnostic repair loop.
4. Brain emits safe progress phases and evidence; it never exposes hidden
   chain-of-thought and never claims semantic correctness from compile-clean.
5. A VS Code integration contract and a Metis Fast integration contract each
   exercise the same Brain protocol. At least one real consumer process per
   boundary must complete the session -> request -> candidate -> compile path;
   mocks alone are insufficient for the final E2E claim.
6. Candidate application remains preview/confirm/CAS-owned by the client and is
   not performed autonomously by Brain.
7. Focused adversarial tests, exact denominator checks, repository-native full
   gates and post-push alignment checks are green for every repository changed.

## Active status

`CHECKPOINT_PROMOTED_E2E_OPEN`

## Evidence wire

- FACT — Existing Brain v1 already provides numeric loopback HTTP, bootstrap
  and session bearer authentication, N isolated immutable tenant snapshots,
  exact idle TTL 1,200 seconds, capability checks, stale guards and a pinned
  compiler bridge.
- FACT — Existing Brain v1 deliberately reports `model_loaded=false` and
  exposes only session status, context and compile routes. Inference, progressive
  catalog retrieval, progress streaming and both consumers remain open.
- FACT — The existing Model 1 projection proves `video -> video_pg` for 40
  execution fields and 521 finite values, including seven draft values that
  cannot ground. It is compatibility evidence, not a native Metis declaration.
- DONE — L82 Brain census closed: session/context/compiler core present;
  inference, session-bound catalog retrieval, safe phase events, orchestration
  and the integrated Brain test are absent. The safe new-code lane excludes all
  sealed W1/W3/W5 oracle and benchmark surfaces.
- DONE — L81 Metis census closed with exact grammar, resolver, formatter,
  schema-retrieval, invarianza and negative-test seams; no writes were made.
- DONE — L83 consumer census closed: Visix current Chat coverage is `0/6` and
  Metis Fast has no repository/runtime yet; both boundaries have a concrete
  isolated implementation seam and no current Brain connection to mistake for
  an E2E.
- DONE — Colleague contract preservation: tracked changes `in=1 out=1`, ignore
  policy `in=2 out=2`, gaps `0`; commit `a11757f3` is pushed and Metis `main`
  is clean.
- FACT — The new successor repository was created locally at
  `/Users/tommasotessarolo/Developer/metis-fast`; `atomic-video-player` remains
  untouched. Its first bounded slice has request, safe progress, proposal
  preview, revision and apply-preflight surfaces. L0 independently reran
  typecheck, `3/3` tests and production build successfully, but promotion is
  withheld until its strict client schemas are aligned with the final Brain
  protocol and one real non-fake turn is observed.
- FACT — Visix implementation owns the isolated worktree
  `/Users/tommasotessarolo/Developer/ares-matioska/metis-brain-visix` on
  `codex/metis-brain-visix@a11757f3`; it cannot modify the shared Metis `main`
  or the native-semantics writer surface.
- DONE — Native `semantics from @catalog` implementation closed and passed an
  independent L0 rerun of typecheck, focused positive/negative tests and both
  R8 semantic/runtime invariants. Commit
  `e42d7a4012a4e526426b6621d50e4d19689026ae` was fast-forwarded and pushed to
  Metis `main`; local and remote `main` match and the shared checkout is clean.
- DONE — `play-demo.video_pg` now declares `semantics from @video` and no
  longer duplicates field semantics or local domain markers. L0 independently
  measured `40/40` reviewed fields from `play-demo.video`, effective domains
  `enum=9 inline=9 open=12 none=10`, and a clean native semantics gate. Commit
  `6b263c0fabbf61afe057ba3893d7eb26074fc801` is pushed to `play-demo/main`;
  local and remote `main` match and the checkout is clean.
- DONE — Visix now exposes the native sticky `@metis` Chat Participant with a
  bounded Brain lifecycle, strict SSE client, clarification flow, proposal
  preview, one-shot apply boundary, CAS and post-apply recompile. L0 reran the
  complete Metis `npm test` chain: exit `0`, including i18n `1488/1488`, the
  focused Brain contract tests and build. Commit
  `c9f410a9b9b28e61dd1505b661ebc996e388e6e0` is pushed to Metis `main`; local
  and remote `main` match and the shared checkout is clean.
- DONE — Metis Fast is a new private successor repository; its typed Brain
  client, safe progress surface, `.metis` proposal preview, clarification and
  apply-preflight boundary pass typecheck, `3/3` tests and production build.
  Commit `ee9e05bc167af3a19268d00a71d076ad908bf03a` is pushed to
  `ttessarolo/metis-fast/main`; local and remote `main` match. The predecessor
  `atomic-video-player` was not modified.
- FIX — L0 rejected the delegate's impossible abbreviated-prefix expansion for
  the Brain toolchain pin and rebuilt it from published Git objects. The live
  verifier now binds Metis `main@c9f410a9`, tree `40bb657e`, Node `v22.22.3`,
  and all `16/16` evidence blobs with gaps `0`; binding
  `sha256:036a2cef883ce39cb75fa492a2bf9a85c2211e9ccff8348e62616b091bb47010`.
- OPEN — The Brain vertical slice remains incomplete beyond the accepted
  protocol foundation. Until the existing MLX runtime and schema-2 semantic retriever are wired and each
  real consumer completes a non-fake turn, acceptance items 3 and 5 remain
  open; compile-clean or fake-client tests cannot close them.
- DONE — L85 protocol foundation accepted after L0 diff review: authenticated
  async turns, request idempotency, one active turn per session, bounded safe
  events/SSE replay, injected retrieval/model/compiler loop, at most two repairs,
  clarification, cancellation and read-only apply preflight. The final focused
  roster is `54/54` green; Ruff, formatter and diff checks are green. The full
  repository run reached `2191 passed, 2 skipped` and one 45-second timeout in
  the pre-existing FIFO materializer test; the exact failing parameter was
  rerun through the canonical isolated harness and passed `1/1` in `43.74s`.
  This evidence accepts the additive checkpoint but does not satisfy the real
  MLX/retrieval/consumer E2E acceptance items recorded above.
