# Metis Brain interactive session memory blackboard

## Objective

Deliver a server-owned interactive dialogue for the native VS Code `@metis`
participant. Brain may ask one concrete question when a choice materially
changes the endpoint, remembers verified answers and proposal lineage only for
the life of the tenant session, and makes all conversation state immediately
unaddressable on explicit close or the existing exact 20-minute idle expiry.
Any already-admitted running frame or cancelled queued work item is released at
the current bounded worker boundary and cannot resurrect or publish session
state; queued futures are cancelled before starting retrieval/model work.

## Scope

- IN — volatile session memory, typed pending clarifications, replay/stale/
  cross-session guards, catalog and semantic-choice questions, bounded numeric
  result-count input, reserved response-shape/fallback typed options, assumptions,
  proposal refinement lineage and the native VS Code consumer.
- IN — strict separation of total cardinality and pagination: exact operator
  count emits `take N`; only an explicit pagination request emits `take page`.
- QUEUED — Metis Fast, persistent memories, cross-session recall, remote
  fallback execution, standalone Mac packaging and autonomous Apply.
- STOP — transcript or chain-of-thought persistence, tenant writes, Apply in
  the live smoke, credentials, `.env`, Keychain, live data, VPN dependency,
  training, weight mutation/download and remote/Ollama fallback.

## Preflight

- FACT — Model 1 is clean and aligned at
  `main@2874363c75e543d6d13dd07f91b8a394380b2526`.
- FACT — Metis main and the isolated writable Visix worktree are clean at
  `c1919ad8a3500b84a9f1f692e43a37bcff3f6b53`; only
  `/Users/tommasotessarolo/Developer/ares-matioska/metis-brain-visix/tooling`
  is writable for the client lane.
- FACT — the VS Code tenant is clean `main@bfd6cbe4c7b06cc00a2493eac34db02887bc997b`
  and remains read-only.
- FACT — L0 inspected the open v0.23.95 Draft in VS Code. It contains the three
  reviewed Italy literals only, shows zero workspace problems, and the
  physical endpoint remains absent.
- FACT — `take page default 20` is not page number 20. It is one page whose
  occurrence-local default size is 20; request `hitsPerPage` wins over 20 and
  20 wins over the tenant. The `play-demo` tenant explicitly declares
  `response.hits-per-page=24`, so the current 20 is not tenant-derived.
- DECISION — absent an operator total on a new endpoint, Brain asks once. An
  answer `N` emits `take N`, not `take page default N`. Page forms are emitted
  only from an explicit pagination request; bare page then inherits tenant HPP.

## Product contract

1. Memory is structured RAM state, never an unbounded chat transcript and
   never hidden chain-of-thought. It contains only request lineage, accepted
   clarification decisions, visible assumptions and the latest proposal basis.
2. Every pending question is created by Brain and bound to session, parent
   turn, request fingerprint, context revision, semantic revision, kind,
   answer schema, expiry and one-shot consumption.
3. One blocking question is shown at a time; the budget is three questions per
   logical request. Exact repeats are forbidden. Critical ambiguity after the
   budget fails closed; safe defaults remain visible and do not consume the
   budget.
4. Delivered autonomous kinds are `catalog`, `semantic_choice`, `result_count`
   and the concrete `response_shape` ambiguity “total or per page?”. `fallback`
   stays typed/reserved and may activate only when retrieval supplies
   authoritative alternatives. Option questions use server-issued opaque
   references; result count accepts a server-bounded positive integer.
5. Unknown, expired, replayed, cross-session, wrong-kind, out-of-range or
   revision-stale answers are rejected before retrieval/model/compiler work.
6. Refinement through `basis.proposal_ref` inherits the server-side proposal
   lineage and visible decisions. The client cannot substitute a different
   instruction/target while answering a pending question.
7. Session close, idle expiry, shutdown or snapshot invalidation removes all
   turns, pending questions, decisions and proposal memory for that session.
8. VS Code renders Quick Pick for option questions and a bounded numeric input
   for result count; it uses the already-open tenant session and never asks
   Giulia to type the tenant again.

## Acceptance gates

- `0` accepted unknown, replayed, cross-session or stale answers;
- `0` model/compiler invocations while a blocking ambiguity is open;
- one pending question per session and at most three per logical request;
- exact session cleanup leaves `turns=0`, `pending=0`, `conversations=0`;
- exact total `N` compiles as `take N`; pagination is never inferred from it;
- assumptions and resolved choices appear in terminal output;
- focused Model 1 and Visix contract tests green;
- authoritative `make check` green;
- rebuilt/installed VSIX and one real no-Apply VS Code clarification smoke;
- both repositories committed, pushed, clean and aligned.

## Status

`IN_PROGRESS`

## Evidence wire

- DONE — L101/L102/L103 read-only census roster
  `in=3 out=3 distinct=3 gaps=0`: page semantics, server/session extension
  points and Visix dispatcher surface are independently identified.
- FIX — pending questions are now server-owned, revision/fingerprint/session
  bound, single-use and claimed atomically at queue admission. Worker failure,
  cancellation and executor rejection release the claim; a hidden question
  created before a failed terminal is discarded without erasing accepted
  decisions.
- FIX — `TurnStore` is registered on session cleanup. Explicit close, stale
  context, exact idle expiry and shutdown erase turns, proposal bytes, pending
  questions and decision summaries; admitted operations refresh the idle
  window when their activity finishes.
- FIX — proposal-basis decisions are not replayed as fresh authority. A current
  explicit result count or catalog overrides historical choices; semantic
  choices already absorbed into the basis are retained without being applied
  a second time.
- FIX — cardinality parsing is fail-closed for quoted/code spans, non-exact
  bounds, ranges/alternatives and Unicode sign-like prefixes. Total ranges ask
  one real choice; page/document wording cannot silently enable pagination.
  Page ranges that omit the repeated noun (`tra 20 e 30 per pagina`) retain
  both alternatives, while qualified ranges (`circa`, `almeno`, `massimo`)
  reject instead of silently authorizing the upper bound.
- FIX — candidate adjudication requires exactly one authorized catalog source
  in the unique endpoint-level `take`. Existing fallback-bearing endpoints
  fail closed until exact fallback preservation is implemented; Brain never
  silently relabels them as `fallback:none`.
- DONE — focused Brain roster `in=470 out=470 distinct=470 gaps=0` via
  `./.venv/bin/pytest tests/test_brain*.py -ra`; no tenant/model/VPN access.
- DONE — bounded final parser audit `in=9 out=9 distinct=9 gaps=0`: six
  noun-elided page ranges retain both choices and three qualified ranges fail
  closed with `OUTPUT_CONTRACT_INVALID`; verdict GREEN.
- DONE — Visix consumer roster `in=24 out=24 distinct=24 gaps=0` via
  `npm run test:brain-chat`; `npm run typecheck` is green on package 0.23.96.
- DONE — authoritative `make check` is green from a fresh run:
  foundation `passes=85 errors=0 files=542`, Ruff check/format green, repository
  suite `2607 passed, 2 skipped, 22 warnings`.
- DONE — rebuilt VSIX `metis-dsl-0.23.96.vsix` is content-gated, validates
  `170` tenant endpoints with `0` errors, has file SHA-256
  `12fa89e5460a8ed1086e161d080cd5f09b034f6ffb89a43d0eef4f1b01d34d38`,
  and is installed as `metis.metis-dsl@0.23.96`.
- OPEN — the final real no-Apply VS Code dialogue remains required before
  promotion; Computer Use reports the Mac locked, so no UI action was attempted.
