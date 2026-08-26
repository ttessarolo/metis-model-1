# Metis Brain tenant-session wave brief

## Mandate

Implement the first runnable, Mac-only Metis Brain service core. A paired local
client opens an authenticated logical session for one configured tenant alias,
uses a frozen context snapshot and the pinned Metis compiler, and closes the
session explicitly or lets it expire after exactly 20 minutes of semantic
inactivity.

This wave is the service contract consumed later by the Metis VSIX and
Metis Fast. Those clients, model inference, packaging/notarization and remote
fallback are not implemented here.

## Fixed scope

- Writable repository: `/Users/tommasotessarolo/Developer/metis-model-1` only.
- Baseline: `main@6b1ea20201ed666f7725750051067518c3689a17`.
- Read-only toolchain source: `/Users/tommasotessarolo/Developer/ares-matioska/metis`;
  tracked tooling must come from the pinned Git archive; the only live-root input
  is `tooling/node_modules`, copied into isolation only when its before/after
  digest matches the pinned runtime identity.
- No `.env`, credentials, live ARES payloads, weights, adapters, datasets,
  downloads, training, deployment or external-repository writes.
- Python standard-library HTTP transport; no new runtime dependency.

## Product invariants

1. The service binds only to numeric loopback and rejects browser-originated
   requests, cookies and authentication in query strings.
2. A fresh 256-bit bootstrap secret is created for each server start in a
   private runtime directory. It opens sessions but cannot use session routes.
3. Each session has one immutable tenant alias, immutable capabilities, an
   opaque 256-bit token stored only as a keyed digest, an immutable context
   snapshot and a private overlay outside the tenant.
4. The server resolves tenant aliases from local configuration. Request bodies
   never supply filesystem paths, commands, arguments or environment variables.
5. N logical sessions share one service/model identity. Sessions on the same
   tenant remain isolated and candidates are bound to the snapshot revision.
6. TTL is exactly 1,200 seconds on a monotonic clock. Only an admitted semantic
   operation refreshes activity. Health, status, failed auth and transport
   traffic do not.
7. Close/expiry revokes the token before cleanup. An in-flight operation owns a
   lease, receives cancellation and cannot publish a late result.
8. Brain does not mutate a tenant. It returns context, diagnostics, compiler
   evidence and candidates; VSIX/Metis Fast own preview, approval and CAS apply.
9. Compiler execution uses the repository's already-pinned, archive-isolated
   grammar/stdlib oracle. Compile-clean is evidence, not semantic correctness.
10. Logs use an exact metadata allowlist and never contain headers, tokens,
    prompts, source, catalog values, tenant roots or raw diagnostics.

## Planned implementation order

1. Ratify protocol/error schemas, session state machine and tenant snapshot
   contract.
2. Implement safe tenant registry and immutable snapshot capture.
3. Implement session manager, capability checks, monotonic TTL, stale guard,
   limits, revocation and cleanup.
4. Bridge session snapshots to the pinned Metis compiler and produce a redacted,
   content-bound receipt.
5. Expose the strict loopback HTTP API and a `brain-serve` CLI.
6. Add hostile unit, race, transport, compiler and live-loopback tests.
7. Run focused gates, real compiler smoke, `make check`, independent claim
   recomputation, diff review and update the canonical board.

## Exit gate

The wave closes as `METIS_BRAIN_SESSION_CORE_V1` only when:

- all P0 session/security/compiler tests pass;
- a live loopback server opens, inspects, compiles and closes a session against
  a public-synthetic tenant without modifying the tenant or external Metis
  checkout;
- expiry is independently reproduced at `1199.999s`/`1200.000s`;
- same-tenant isolation and stale revision rejection are reproduced;
- `make check` has been executed and its exact outcome recorded;
- remaining gaps are named without claiming VSIX, Metis Fast, model inference or
  distributable Mac packaging.
