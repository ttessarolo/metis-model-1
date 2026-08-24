# Qwen L68 Phase A — protocol and schema writer

## Mandate

Work in `/Users/tommasotessarolo/Developer/metis-model-1` at baseline HEAD
`2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0` plus the complete inherited dirty
L66/L67/L68 state. This is a bounded writer wave after the Qwen read-only master
review. Preserve every inherited byte and do not commit or push.

Read `AGENTS.md`, the canonical board and ledger,
`orchestra/briefs/2026-08-23-model1-l68-protected-execution-broker.md`, and the
external activity artifacts `qwen-l68-final-report.md`,
`qwen-unit2-request-receipt.md` and `qwen-unit3-replay-consume.md`.

## Exact writable roster

1. `runtime/w3_broker_protocol.py`;
2. `schemas/w3-protected-broker-authority.schema.json`;
3. `schemas/w3-protected-broker-request.schema.json`;
4. `schemas/w3-protected-broker-receipt.schema.json`;
5. `tests/test_w3_broker_protocol.py`.

Everything else is read-only, including all current qualifier, bridge, worker,
adapter, oracle, v3 schema, manifest, evidence, board and ledger paths. The team
master delegates schema/protocol/test units, validates returned work and writes
only the five paths above.

## Contract

- Use the repository canonical JSON semantics: JSON-only types, NFC and newline
  normalization, duplicate raw and normalized-key rejection, `allow_nan=false`,
  UTF-8, sorted keys and compact separators.
- Use unsigned four-byte big-endian length framing with a `4 MiB` payload cap,
  exact reads, no trailing bytes, a bounded nesting depth and typed failures.
- Hashes are `sha256:` plus lowercase hex over domain-separated canonical
  envelopes. Caller digests are named claims and cannot contain authority bytes
  or paths.
- Requests contain only fixed identifiers, claimed digests, canonical payload
  and client nonce. They reject absolute/relative paths, argv, environment and
  ancillary-FD fields by exact schema.
- Authority declares separate broker/runner identities, root launcher and
  root-owned installed code/release identities, registered public-key identity
  and synthetic-versus-production mode.
- Receipt signed material is the canonical receipt with only
  `signature.value` omitted; algorithm and key id remain signed. Production
  algorithm is `ed25519`; the only Phase A alternative is explicitly labelled
  `synthetic-hmac-sha256` with `executed_preimage_authority=false`.
- Receipt schema requires claimed/measured digests; broker/launcher/worker/Node/
  loader identities; broker and runner UID/GID; resolved policy identity; full
  pre/post roster rows (`path,size,mode,sha256,uid,gid,dev,ino,nlink`); request,
  nonces, global sequence and previous receipt; stdout/stderr/exit; atomic
  publication; process/FD/temp cleanup; nonclaims and signature.
- A summary or truncated roster is invalid. Unknown fields are invalid.
- This wave implements structure and deterministic transforms only. It does not
  open a socket, persist a ledger, sign with a real key, spawn a process, create
  users, run Node/Metis or claim production evidence.

## Exact focused denominator

Collect exactly `12` named protocol cases:

1. canonical round trip;
2. duplicate raw key rejection;
3. normalized duplicate key rejection;
4. noncanonical byte/order/whitespace rejection;
5. invalid JSON number and strict integer/bool rejection;
6. unknown or path/argv/env/FD field rejection;
7. payload and nesting bounds;
8. frame truncation/trailing/oversize rejection;
9. domain-separated request hash stability;
10. authority claims-only cross-binding shape;
11. signed-material mutation coverage including previous receipt;
12. full-roster and synthetic-nonclaim schema enforcement.

Validation: JSON parse all three schemas; Draft 2020-12 checks; focused pytest
must report `12 passed`; Ruff and format-check on the two Python files; Python
compile; `git diff --check`; exact roster `in=5 out=5 distinct=5 gaps=0`.
No Node, runner, network, credential, model/data payload, training or privileged
operation.

## Return

Deposit a final report in the shared activity artifacts directory with:

1. `What I did`;
2. `How I validated it`, including both `12/12` and writer-roster arithmetic;
3. `STOPs`;
4. `What I could not establish`.
