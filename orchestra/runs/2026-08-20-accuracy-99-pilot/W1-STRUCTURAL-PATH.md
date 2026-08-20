# W1 structural path execution

Date: 20 August 2026
Verdict: `STRUCTURAL_GREEN_NOT_SEALED`

## Boundary

The Metis repository remained read-only at
`a2dde2b191f6b78c2003d74875560da782470968`. Before and after execution its
status was exactly:

```text
?? tmp/
?? tooling/metis-dsl-0.23.83.vsix.sha256
?? tooling/metis-dsl-0.23.85.vsix.sha256
?? tooling/metis-dsl-0.23.86.vsix.sha256
```

Those four entries predate this wave and were not opened, modified or removed.
No `.env`, credentials, live ARES payload or external service was used.

## Parser, linker and validator

L0 inspected `tooling/test/corpus-validation.ts` at the pinned revision before
execution and found no filesystem-write operation. The test was then run from
the Metis tooling checkout with its temporary and cache paths redirected to
the ignored Model 1 artifact tree:

```text
node --import tsx test/corpus-validation.ts
```

Observed result:

```text
language manifest=0.43 corpus=0.43
files=197 errors=0 warnings=123
VALIDAZIONE CORPUS: VERDE
```

All of the runner's positive and deliberately-invalid polarity checks also
passed, including ordering, parameter typing, empty variants, reference
linking, guard operators, settings, collections and inherited inputs.

## Compiler path

The normal `build:tenant` CLI was deliberately not executed against the true
checkout. Frontier inspection found that the `scope: all` path can call
`git worktree add/remove`, and source snapshot construction creates a temporary
sibling of the supplied tenant. Merely redirecting `--out` is therefore not a
sufficient read-only guarantee.

Instead, L0 exported exactly
`metis@a2dde2b191f6b78c2003d74875560da782470968:examples/play-prod-v2`
with `git archive` into
`artifacts/runtime/pinned-tenant-build-20260820/source/` and invoked the pure
single-snapshot `buildArtifactSetAt` entrypoint on that isolated copy. All
temporary snapshots and outputs consequently remained under the ignored Model
1 artifact tree.

Two independent output directories were built from the same archive. A
recursive byte comparison reported no difference. Each run produced:

```text
endpoints=170
catalogs=8
runtime_context_fields=137
materialized_fallback_generation=sha256:8563874a7f3e8843a11710710ec94f2c4bf55f47982b91bbcfeec8e7d8f3c84c
artifact_set_identity=776676472b8066a143f755b69c9ed123e2ec6d0d3e02b814ce5ed21fc05c5f4c
```

Local output-file hashes:

```text
tenant-artifact-set.json 36547b564c9f59198be8789d7d46cfd807347231314448a3253c67cdd60d396c
runtime-ctx.json          b9d87937f0b9d65788f56afeedb6816cba7388627538abaa0d62c79184144edf
materialized-fallbacks   35bc0a2d78e9f84538849087c74ef35f92ef95c54496a16ac81f2a3c2acaae81
```

## What this proves and does not prove

This execution proves that the pinned whole-tenant structural path currently
parses, links, validates and deterministically compiles from an isolated copy.
It also proves that Metis need not be modified to exercise that path.

It does not execute the 30 task requests, patch-minimality checks, diagnostic
mutations, migration pairs, IR/wire/golden expectations or blind semantic
adjudication. It therefore cannot seal the smoke roster and cannot authorize a
W5 semantic training claim. The ignored build artifacts are technical evidence,
not a training dataset.
