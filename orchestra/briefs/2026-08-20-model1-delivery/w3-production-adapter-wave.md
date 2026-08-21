# W3 production adapter wave — frontier implementation brief

## Objective

Implement the smallest real F-1/F-2/F-3 adapter bridge that executes the pinned
Metis runner in its isolated snapshot and retains independently verifiable
receipts. Qualify the bridge on three self-contained public-synthetic candidates
only. Do not register production authorities, seal the W1 slice, materialize a
training dataset or claim semantic accuracy in this wave.

Baseline project SHA:
`acb698d204147fb0fcd7bc773c5bfb18f03e6944`.

Metis is strictly read-only at
`a2dde2b191f6b78c2003d74875560da782470968`. Never read credentials, `.env`
files, live ARES data, model weights, adapters, checkpoints or optimizer state.
Generated receipts may exist only below ignored `artifacts/w3-oracle/`.

## Required closures before registration

1. Replace policy-only fixture evidence with an ordered roster of complete
   `run_oracle` request/envelope pairs. Every envelope is independently passed
   through `verify_oracle_envelope(envelope, request=request)`.
2. Add an independently hash-authorized semantic registry. Family-specific
   schemas use `additionalProperties: false` and bind candidate ID, family,
   content, filename, endpoint or runner mode, workspace closure and expected
   truth.
3. Separate `W3CandidateRejected` from run-fatal
   `W3OracleInfrastructureError` and `W3OracleTrustError`. Identity drift,
   registry/schema mismatch, timeout, sandbox failure, malformed output and
   receipt mismatch terminate the whole run.
4. Identity v2 binds the adapter plus transitive `oracles.py`, Oracle result
   schema, semantic schemas/registry and execution profile hashes.
5. The macOS sandbox denies both file writes and network access and proves both
   with mandatory canaries. Re-pin the policy and runner identity.
6. Add a source-only/non-endpoint runner mode; the current exactly-one-endpoint
   requirement cannot serve every allocated family task.

## Exact bridge gate

Use three independently reviewed, self-contained public-synthetic candidates,
one per family and with no external workspace dependency.

```text
candidates: in=3 out=3 distinct=3 rejected=0 gaps=0
executions: in=5 out=5 distinct=5 gaps=0
roles: target=1 before=1 after=1 mutated=1 fixed=1
```

- F-1: `target=ok` and exact reviewed IR/assertions.
- F-2: `before=ok`, `after=ok`, exact typed minimal edit and preservation.
- F-3: `mutated=invalid` with exact registered diagnostic, `fixed=ok`, exact
  reviewed repair truth.
- Fresh-process replay must be byte-identical.
- Project and expanded Metis HEAD/tree/status must be identical before/after.
- Network and write canaries must be denied.

This gate proves only the three registered specifications. It does not close
W1 `15/15`, rights/dependencies, F-4/F-5/F-6, benchmark v1, W5 or 99%.

## Writable roster

Sequential ownership; no overlapping writers:

1. `src/metis_model1/w3_production_adapter.py` (new)
2. `src/metis_model1/w3_oracles.py`
3. `src/metis_model1/w3_builder.py`
4. `src/metis_model1/oracles.py`
5. `runtime/metis_oracle/runner.ts`
6. `schemas/w3-semantic-spec.schema.json` (new)
7. `schemas/w3-source-register.schema.json`
8. `schemas/w3-run.schema.json`
9. `manifests/w3-f1-f3-smoke-semantic-specs.json` (new)
10. `manifests/w3-f1-f3-smoke-candidates.json` (new)
11. `tests/test_oracles.py`
12. `tests/test_w3_oracles.py`
13. `tests/test_w3_builder.py`
14. `tests/test_w3_production_adapter.py` (new)

Integration may additionally update foundation registration, the active board,
ledger and relevant docs after the implementation files freeze.

## Verification

Focused fixture and real-smoke gates, JSON Schema validation, Ruff, format and
`git diff --check` are mandatory. Then run the full gate with hostile ambient
`PATH` and the pinned Node. A separate frontier lane must replay receipt,
semantic-registry, error-class, network and runner-mode attacks before L0 may
set any authority hash.
