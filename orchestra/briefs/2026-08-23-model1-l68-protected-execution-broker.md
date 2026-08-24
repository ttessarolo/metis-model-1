# L68 — protected execution broker and rapid closure path

## Status

PHASE A ACCEPTED — `BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE` only. The final
independent Daybreak replay reports `P0=0`, `P1=0`, `P2=0`, exact focused
denominator `73/73` and original-exploit spot checks `7/7`.
L67 remains accepted only as `STATIC-PARTIAL`; production execution, L63
materialization and training stay blocked until the separately authorized Phase B
boundary is installed and independently accepted.

## Baseline and inherited state

- repository: `/Users/tommasotessarolo/Developer/metis-model-1`;
- branch: `codex/model1-local-99-foundation`;
- baseline HEAD: `2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0`;
- preserve the complete inherited dirty L66/L67 product, schema, test, manifest,
  board, ledger and brief state; no reset, rewrite or silent repin;
- L0 is the only integration, architecture, promotion and board authority;
- current production evidence remains
  `blocked/available=false/expected=15/durable=0/credit=none`.

## Ratified maintenance principle

O-010 is lightweight-first:

1. refresh retrieval and test the existing adapter first;
2. emit `NO_RETRAIN` when semantic and critical regression gates remain green;
3. use only bounded `DELTA_QLORA` from the previous adapter when compatible
   AST/IR and semantics still need adaptation;
4. require `FULL_SUCCESSOR` only for AST/IR or semantic-contract change, or when
   the lightweight path still fails;
5. never rewrite a prior benchmark, dataset, adapter, manifest or receipt.

This principle does not authorize any training in L68.

## Objective

Introduce the smallest honest OS trust boundary that can later produce a signed
receipt for bytes actually executed against an exact authority. The broker must
remove the same-UID pathname substitution problem without weakening L66/L67.

The Phase-A design frozen by this brief has four principals and two services.
Before any Phase-B installation, L70 normatively supersedes that host boundary
with five principals and three services by adding the isolated
`_metisanchor` consumer service; see
`orchestra/briefs/2026-08-23-model1-l70-phase-b-installable-unexecuted.md`.

- the caller UID is untrusted;
- a non-root `_metisbroker` service owns only its signing key, append-only ledger
  and bounded publication roots; its executable code and every imported runtime
  byte are installed from root-owned, immutable, caller/broker-non-writable
  ancestry rather than executed from this caller-owned repository;
- a minimal root `w3_privileged_launcher` owns no signing key and implements no
  semantic, JSON, authority-registration or caller-selected path API. It accepts
  only the exact `_metisbroker` peer, a fixed bounded binary frame and opaque
  canonical payload bytes over the original authenticated connection;
- Node runs only as a distinct non-root `_metisrunner` UID. The launcher performs
  `setgroups([]) -> setgid(_metisrunner) -> setuid(_metisrunner)`, proves privilege
  cannot be regained, closes every non-allowlisted FD, applies the exact
  authority-bound Seatbelt policy and executes only the configured root-owned
  release. Node never runs as root or as `_metisbroker`;
- release, capsule, broker, worker, launcher, Node and loader ancestry are
  root-owned and not writable by caller, broker or runner. Executed files are
  regular, symlink-free, single-link, content-addressed and remeasured from
  `O_NOFOLLOW` descriptors before and after pathname execution;
- caller JSON uses the repository canonical codec and carries identifiers plus
  claimed digests only, never executable paths, argv, environment values or
  ancillary FDs. Authority bytes and release mappings are installed out of band
  in root-owned ancestry; caller claims never self-authorize;
- the installed authority independently pins the policy plus the exact six role
  mappings as a required subset of an extensible complete release/runtime
  roster. The release ancestry digest is domain-derived from release id plus the
  complete sorted roster, never accepted as a free caller scalar;
- the broker validates the request, durably consumes its client nonce and reserves
  a global `attempt_sequence` before any side effect, measures protected preimages,
  invokes the launcher, receives the result on the original connection, verifies
  kill/reap/FD/temp cleanup and pre/post rosters, and atomically publishes output.
  Only then, under the same single-writer lease, it assigns the next contiguous
  `receipt_sequence` and `previous_receipt_sha256`, signs the complete receipt,
  durably appends the exact signed bytes and advances the chain before delivery.
  A crash may tombstone an attempt but never creates a consumer-visible receipt
  gap or permits re-execution or re-signing under a consumed nonce;
- production receipts use an authority-pinned Ed25519 key id and sign the canonical
  serialization of every receipt field except the signature value itself. Phase A
  may use only an explicitly labelled synthetic signer and executor with
  `executed_preimage_authority=false`;
- every receipt embeds full path/size/mode/hash pre/post rosters and binds claimed
  versus measured digests, broker/launcher/worker/runtime identities, effective
  UID/GID, resolved policy bytes and parameters, request/nonces,
  `attempt_sequence`, `receipt_sequence`, previous receipt, stdout/stderr/exit
  status, atomic publication and exact cleanup;
- consumers persist the accepted `receipt_sequence` high-water and chain head per
  authority in a mutable initialize-once anti-rollback anchor, reject missing or
  recreated state, and advance it with compare-and-swap before success. They
  reject regressions, gaps, forks and unknown key epochs, retain old public keys
  and release evidence, and distinguish replay prevention from deterministic
  re-execution. Phase A provides only an explicitly unprotected test anchor with
  zero authority; the protected store is Phase B evidence. `attempt_sequence`
  remains an audit-ledger ordering and is never used as the consumer progression
  index.
  Identical payload with a fresh nonce remains allowed; one consumed nonce can
  cause at most one execution and at most one durable receipt.

## Phase A — payload-free and unprivileged

Phase A may implement protocol, schemas, client, broker core, the privileged
launcher source contract, installer planning and labelled public-synthetic tests
without creating an OS user, loading a daemon, executing Node/Metis, touching a
real signing key or materializing model/data payloads. It may syntax-check the C
source with `/usr/bin/clang -fsyntax-only`; any compiled binary stays outside Git
and has no authority until Phase B.

The broker core's default storage contract requires a root-owned non-writable
full parent ancestry and an already-created broker-owned mode-`0600` ledger
leaf. Only labelled synthetic tests may opt into the unprotected ledger mode;
replacement poisons that broker instance and the signed nonclaims preserve zero
authority.

Ratified single-writer roster:

1. `runtime/w3_broker_protocol.py`;
2. `runtime/w3_protected_broker.py`;
3. `runtime/w3_broker_installer.py`;
4. `src/metis_model1/w3_broker_client.py`;
5. `schemas/w3-protected-broker-authority.schema.json`;
6. `schemas/w3-protected-broker-request.schema.json`;
7. `schemas/w3-protected-broker-receipt.schema.json`;
8. `packaging/launchd/com.metis.model1.w3-broker.plist.in`;
9. `runtime/w3_privileged_launcher.c`;
10. `packaging/launchd/com.metis.model1.w3-launcher.plist.in`;
11. `tests/test_w3_broker_protocol.py`;
12. `tests/test_w3_broker_client.py`;
13. `tests/test_w3_broker_lifecycle.py`;
14. `tests/test_w3_broker_e2e_public.py`;
15. `tests/test_w3_broker_launcher_contract.py`;
16. `docs/13-protected-execution-broker.md`;
17. this brief.

All existing qualifier, bridge, worker, adapter, oracle, v3 schema, L67 evidence
and manifest paths remain off-limits in Phase A. L0 alone appends board/ledger.

## Phase A gates

Kimi, Qwen, Daybreak and L0 retire the initial `48/48` proposal. The ratified
Phase A denominator is `73/73`:

- protocol, schema, framing and duplicate-key rejection: `12`;
- signature, nonce, restart, concurrency and consume: `25`;
- ownership, preimage and tamper: `8`;
- process, FD and cleanup: `10`;
- install and rollback planning: `6`;
- public-synthetic end-to-end including consumer projection: `2`;
- privileged-launcher source and boundary contract: `10`.

The 25-case ledger/consume bucket includes every crash boundary, durable consume
  before execution, attempt/receipt sequence separation without crash-created
  consumer gaps, durable exact receipt before delivery, restart corruption and
  torn-tail handling, same-nonce no-reexecution, identical-payload/fresh-nonce
reexecution, concurrent sequence and chain linearization, rollback and divergent
head rejection by the consumer, time replay, key/release rotation, request-hash
probing, revocation high-water, retired-release verification, cleanup refusal and
bounded-queue rejection. Every case belongs to one bucket only.

Every executed denominator reports `in=N out=N distinct=N gaps=0`. L0 reruns the
merged focused gate, schema validation, Ruff, format, `git diff --check` and the
safe repository gate. `make check` is required before handoff only when it can be
run without violating the no-production/no-runner STOP; otherwise the exact
conflict is reported rather than laundered.

## Phase B — privileged installation

Creating `_metisbroker` and `_metisrunner`, installing root-owned immutable code
and release ancestry, compiling/installing the pinned launcher, loading either
`launchd` service, provisioning a real signing key and running the real Node
boundary are materially privileged operations. They require a separate explicit
authorization after Phase A is frozen and independently accepted. Phase B must
independently prove distinct UID/GID/group state, irreversible credential drop,
key denial with and without Seatbelt, peer-UID rejection, absent key/ledger/listener
FDs, fork/network/out-of-root-write denial, timeout/PGID/FD cleanup, immutable
preimages under caller race and two fresh public-synthetic runs before any later
production-authority decision. It must also prove the consumer anchor store's
initialize-once, CAS, no-delete/no-recreate and anti-rollback guarantees.

## Orchestra partition

- L0/frontier: architecture, partition, seam checks and final verdict;
- Daybreak Blue: defensive OS/trust-boundary review, read-only;
- Qwen `qwen3.8-max`: protocol, replay, lifecycle and test-roster adversarial
  review complete at `in=4 out=4 distinct=4 gaps=0`;
- Kimi `kimi-code/k3`: governance, maintenance policy, W1/W2/W3 critical path
  and receipt-consumer review complete at `in=4 out=4 distinct=4 gaps=0`;
- lower-cost internal lanes: exact status, sourceability, rights/oracle and
  deterministic census work only.

Each external master delegates its own enumerated slice, validates returned
work and deposits evidence in the shared Orchestra activity blackboard. L0
independently recomputes at least one claim from every report.

## Stop rules

- Any same-UID copy, mode, retained FD or snapshot presented as executed-preimage
  authority stops the wave.
- Any broker, worker, launcher, Node or loader byte executed from caller- or
  broker-writable ancestry stops the wave.
- Any production spawn before registered protected broker authority stops the
  wave.
- Any Node process running as root, as caller or as `_metisbroker` stops the wave.
- Any root launcher that parses semantic JSON, accepts caller-selected paths,
  argv, environment or ancillary FDs, or owns a signing API/key stops the wave.
- Any signing key reachable by caller or child stops the wave.
- Any non-persistent nonce/replay ledger or green receipt before complete
  kill/reap/FD closure stops the wave.
- Any caller digest treated as authority, receipt signature that omits a field,
  truncated pre/post roster, duplicate receipt for one nonce or consumer-accepted
  sequence/chain regression stops the wave.
- Any Metis checkout write, secret/live-data read, network/upload, model payload,
  dataset materialization, training, commit or push outside explicit authority
  stops the wave.

## Maximum outcome

Phase A can reach only `BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE`. Phase B can reach
`BROKER_INFRA_ACCEPTED_PUBLIC_SYNTHETIC`. Neither outcome alone reopens L63,
registers production authority, establishes semantic accuracy or authorizes W5.

## Phase A outcome

`BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE` is accepted on 2026-08-23. L0 reran the
exact `12+43+6+2+10=73` denominator, the three schemas, contract/foundation
checks, Python compile, Ruff, format, both launcher compile-time branches and
`git diff --check`. Daybreak independently replayed the consumer CAS/rollback
family and the original exploit set, returning `P0=0`, `P1=0`, `P2=0` and
`in=17 out=17 distinct=17 gaps=0`.

This outcome grants no production credit. A fresh
`UnprotectedTestAnchorStore` can accept a manually restored old test file; that
backend and every corresponding synthetic receipt explicitly carry zero
authority, while production verification is hard-denied. The protected,
initialize-once anti-rollback store and its OS evidence remain mandatory Phase B
debt.
