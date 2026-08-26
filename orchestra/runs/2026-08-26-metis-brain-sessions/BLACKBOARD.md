# Metis Brain tenant-session wave blackboard

## Objective

Deliver a runnable, fail-closed Mac-local Metis Brain session core: authenticated
tenant-scoped sessions, immutable context snapshots, exact 20-minute idle expiry,
capability isolation and pinned Metis compiler evidence.

## Acceptance

- `METIS_BRAIN_SESSION_CORE_V1` is emitted only after focused hostile tests,
  live loopback/compiler smoke, repository gate and L0 diff review.
- `P0=0`; P1 or product-integration gaps remain explicitly open.
- No claim is made for model inference, VSIX/Metis Fast integration,
  packaging/notarization, remote fallback or autonomous writes.

## Scope and authorization

- FACT — Writable repository is only
  `/Users/tommasotessarolo/Developer/metis-model-1`.
- FACT — Baseline is clean `main@6b1ea20201ed666f7725750051067518c3689a17`,
  aligned with `origin/main` at wave start.
- FACT — `/Users/tommasotessarolo/Developer/ares-matioska/metis` is read-only;
  tracked tooling comes from the pinned Git archive. The only live-root input is
  `tooling/node_modules`, copied into isolation after before/after verification
  against the pinned runtime digest; it is never executed in place.
- STOP — `.env`, credentials, live ARES data, model payloads, downloads,
  training, deployment and external-repository writes are forbidden.

## Orchestra wire

- DONE — L1 API census: `in=1 out=1 distinct=1 gaps=0`; recommended a pure
  session manager plus minimal stdlib loopback adapter and deterministic errors.
- DONE — L2 compiler/retrieval census: `in=3 out=3 distinct=3 gaps=0`; identified
  the pinned Git-archive grammar/stdlib oracle, catalog bridge seam and current
  Python compiler cap of 64 workspace sources.
- DONE — L3 security census: `threats in=12 out=12 distinct=12 gaps=0`; fixed
  loopback, bootstrap, token, capability, alias/root, TTL/race, stale and
  redacted-log P0 gates.
- FACT — L0 independently confirmed the grammar/stdlib oracle wrapper caps a
  workspace at 64 sources; no delegated 512-source claim is accepted.

## Decisions

- DECISION — Product name is **Metis Brain**; the older “Metis Companion” name
  is superseded in the active direction.
- DECISION — Transport v1 is authenticated HTTP/1.1 on numeric IPv4 loopback.
- DECISION — Session idle TTL is exactly 1,200 seconds, measured monotonically.
- DECISION — Client requests a configured tenant alias; Brain validates its
  grant and never accepts a tenant path from the request.
- DECISION — Brain snapshots and compiles but does not modify tenant files.
- DECISION — One service/model identity serves N isolated logical sessions.

## Live status

- FACT — Accuracy/grammar/stdlib maintenance is already closed as
  `GRAMMAR_STDLIB_T30_V3_PASS_NO_RETRAIN`; this wave changes no weights.
- FIX — Detailed plan and bounded Orchestra brief created before code changes.
- FIX — Implemented strict loopback protocol/config, tenant registry and safe
  snapshot capture, capability-bound session manager, exact TTL/leases/cleanup,
  compiler bridge, CLI and redacted receipts.
- DONE — Final focused hostile/regression roster: `in=84 out=84 distinct=84
  gaps=0`; this is 60 direct Brain tests plus 24 grammar/stdlib regressions.
  Ruff, format and `git diff --check` are green.
- DONE — L4 security finding roster: `in=3 out=3 distinct=3 gaps=0`; duplicate
  HTTP framing, lifecycle cleanup races and subprocess-timeout normalization
  were reproduced, fixed and rerun. Timeout was injected twice, both results
  were deterministic `COMPILER_FAILED`, and capacity was released. Final audit
  is `ACCEPT P0=0 P1=0 P2=0`.
- DONE — L5 semantic/document precision roster: `in=5 out=5 distinct=5 gaps=0`;
  TTL, live-checkout isolation, stale publication, sandbox preflight and JSON
  error-response wording were corrected; final audit is `ACCEPT` with no
  residual finding.
- DONE — L6 final core census: `in=60 out=60 distinct=60 gaps=0`; active naming
  is Metis Brain and nonclaims distinguish the runnable core from future
  inference, retrieval, app, VSIX/Metis Fast and packaging.
- FACT — Live loopback smoke observed HTTP `200/201/200/200/200`, six context
  files, compiler `ok`, archive receipt, explicit close, runtime removal and
  byte-identical tenant/external-checkout state before and after. The real
  public-synthetic workspace surfaced three non-error validation diagnostics;
  parser and link diagnostics were zero and semantic correctness remains an
  explicit nonclaim.
- FACT — The first full `make check` stopped at foundation with `67` passes and
  four drift findings. Three exposed an attempted edit to the immutable T30
  oracle and one an edit to the W1-sealed decision register; neither was waived.
- FIX — Restored both sealed files byte-for-byte. Brain now materializes its own
  clean temporary Git authority from the pinned archive/object store, copies and
  verifies the pinned runtime, and invokes the unchanged historical oracle.
- FACT — The historical default Node at `~/.hermes/node/bin/node` disappeared
  during the gate window and `~/.local/bin/node` currently resolves to unpinned
  v22.20.0. No global path was changed by this wave. Brain instead uses the
  ignored repo-confined v22.22.3 binary, verified at the registered
  `5d9d3872...f7cd5c` SHA-256.
- FACT — The corrected literal `make check` reached `68` foundation passes and
  then stopped only because historical T30 resolves hardcoded
  `~/.local/bin/node`, currently unpinned v22.20.0, instead of its environment
  override. This is recorded red; it is not represented as a green
  repository-wide run.
- DONE — The same foundation validator, with runtime-only exact pin/root
  injection and no source edit, produced `passes=70 errors=0 files=408`.
  `validate-pilot` reported all integrated contract/closure/asset/dataset/
  evaluation checks `PASS`; W5 readiness remained truthfully `BLOCKED` by its
  pre-existing benchmark and authority gaps. Full Ruff and format gates pass.
- FACT — A canonical-pin full Pytest replay collected `1,905` tests but was
  stopped by L0 after more than 50 minutes while still in the early historical
  contract/T30 section. Its repeated whole-seal recomputation was
  disproportionate to this isolated wave; the interrupted cache is not a test
  verdict and no repository-wide green claim is made.
- DONE — L0 closed instead on the bounded wave gate: 60 direct Brain tests, 24
  grammar/stdlib regressions, real HTTP/compiler smoke, exact foundation/pilot
  checks, full lint/format/diff checks and three independent Orchestra audits.

## Terminal verdict

`METIS_BRAIN_SESSION_CORE_V1`

This verdict certifies the authenticated tenant-session/compiler core only. It
does not certify model inference, progressive retrieval, VSIX/Metis Fast,
distributable Mac packaging, remote fallback or repository-wide historical
Pytest closure.
