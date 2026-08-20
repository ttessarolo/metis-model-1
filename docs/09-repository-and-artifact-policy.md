# Repository and artifact policy

## 1. Canonical layout

```text
AGENTS.md                         agent ownership and safety contract
BLACKBOARD.md                     pointer to the active activity board
docs/                             charter, architecture, runbooks and evidence
schemas/                          versioned machine-readable contracts
manifests/                        small identities, revisions and checksums
examples/                         non-sensitive contract examples only
src/metis_model1/                 offline validation and future project tooling
tests/                            deterministic repository gates
orchestra/runs/                   per-activity boards and lane ledgers
benchmark/                        W1 specifications and sealed metadata (future)
qualification/                    W4 config/report surfaces, not payloads (future)
reports/                          redacted, bounded reports (future)
licenses/                         notices and reviewed attribution (future)
```

Directories marked `future` are created by their owning wave, not as empty
placeholders. W0 deliberately contains no training command that could be mistaken
for a qualified MLX-VLM invocation.

## 2. Git boundary

Git may contain:

- source code, schemas, tests and deterministic generators;
- source/model revision manifests and checksums;
- training configuration after its CLI has been verified;
- benchmark metadata and sealed checksums, subject to access policy;
- redacted scorecards, cards, audit reports, attribution and runbooks.

Git must not contain:

- model weights, adapters, optimizer state or checkpoints;
- materialized proprietary datasets or raw run payloads;
- credentials, `.env` files, tokens, private keys or production payloads;
- unredacted logs whose provenance or sensitivity is unknown.

The validator checks both tracked paths and non-ignored untracked candidates. It
rejects `.env` files at any depth, common key/model/checkpoint/materialized-data
extensions, credential filenames, symlinks, non-UTF-8/binary files, private-key
headers, and individual files above 5 MiB. The repository is intentionally
text-only; a future binary fixture requires a separate policy decision. Ignore
rules alone do not make an already tracked payload safe.

## 3. External artifact identity

Every external payload is addressed by an immutable revision and checksum from a
small tracked manifest. A local path is operational metadata, not artifact
identity. No promoted artifact may depend on an undeclared file from a developer
machine.

The local artifact store format is ratified by O-006 and
`manifests/artifact-store-policy.json`: ignored `artifacts/w5/<run-id>`, complete
immutable identities and payload hashes, fsync plus atomic rename, verification
before use, a 40 GiB per-run cap and no automatic deletion of published
artifacts. A cache directory is never the canonical store.

## 4. Canonical run states

Machine-readable run state uses:

```text
planned | running | failed | blocked | qualified |
candidate | promoted | rejected
```

Wave verdicts such as `QUALIFIED|BLOCKED` are uppercase report labels for the
same lowercase states; they are not a second state machine.

## 5. Offline foundation gate

```bash
make setup
make check
```

`make check` validates schemas and instances, cross-references open decisions,
checks the repository-file boundary, lints and formats Python, and runs tests. It
does not download a model, inspect secrets, contact ARES, compile Metis, or prove
W4 trainability.

The test recipe passes the qualified Node binary explicitly so Oracle evidence
never depends on the operator's ambient `PATH` order. A different qualified host
must pass `PINNED_NODE=/absolute/path/to/node`; direct bridge callers can set
`METIS_MODEL1_NODE`. Without an override the resolver inspects every `node` in
`PATH`, but it accepts only the registered version and binary digest.
