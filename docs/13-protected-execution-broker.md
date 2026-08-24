# Protected execution broker — normative security specification (W3)

Status: NORMATIVE SPEC. This document is load-bearing specification, not
prose documentation. The key words MUST, MUST NOT, SHALL, SHALL NOT, and MAY
are normative. It encodes the ratified L68 brief
(`orchestra/briefs/2026-08-23-model1-l68-protected-execution-broker.md`,
referenced below as BRIEF) and freezes the P0 remediations of the adversarial
review
(`/Users/tommasotessarolo/Developer/ai-multi-team-orchestra/runs/model1-l68-fast-closure/artifacts/qwen-l68-final-report.md`,
referenced below as QWEN). Where this document and any other text disagree,
this document and the BRIEF stop rules govern.

## 1. Status and scope

1.1. Phase A is payload-free and unprivileged. Phase A SHALL NOT create an OS
user, load a daemon, execute Node/Metis, touch a real signing key, or
materialize any model or data payload (BRIEF §Phase A).

1.2. The maximum outcome Phase A can reach is
`BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE`. The maximum outcome Phase B can reach
is `BROKER_INFRA_ACCEPTED_PUBLIC_SYNTHETIC` (BRIEF §Maximum outcome).

1.3. Neither outcome alone, nor both together:

- reopens L63;
- registers any production authority;
- establishes any semantic accuracy;
- authorizes W5;
- authorizes training. Training is denied for all of L68 (BRIEF §Ratified
  maintenance principle).

1.4. Nothing in this document claims any production execution, any L63
reopening, any registered authority, any semantic accuracy, any training
authorization, or any executed-preimage authority for Phase A artifacts.

1.5. Under O-011, Phase A or Phase B is not a prerequisite for the W5-XS
research-only baseline or micro-experiment. It remains a prerequisite only for
the production-grade receipt/authority claims that explicitly require it.

## 2. Principals

The boundary has exactly five principals and three services. L70 adds the
anchor principal because a caller-owned anchor is rollbackable, a runner-owned
anchor is child-reachable, a broker-owned anchor expands the signing-key trust
domain, and the root launcher MUST NOT implement a semantic state API.

2.1. Caller UID. The caller UID is UNTRUSTED. Every byte the caller supplies
is input, never authority.

2.2. `_metisbroker`. A non-root service UID that owns ONLY its append-only
ledger and bounded publication roots. It can read, but cannot modify, the
root-owned signing-key leaf described by §7.3. Its executable code and
every imported runtime byte MUST execute from root-owned, immutable,
caller/broker-non-writable installed ancestry, and MUST NOT execute from this
caller-owned repository (freezes QWEN P0-1). The broker MUST NOT run as root,
as caller, or as `_metisrunner`.

2.3. `w3_privileged_launcher`. A minimal root helper. It owns NO signing key
and implements NO semantic, JSON, authority-registration, or caller-selected
path API. Its entire function is the credential-drop sequence of §6 followed
by exec of the configured root-owned release.

2.4. `_metisrunner`. A distinct non-root UID. It is the ONLY identity Node
ever runs as. Node MUST NEVER run as root, as the caller, or as
`_metisbroker` (BRIEF stop rule 4).

2.5. `_metisanchor`. A distinct non-root service UID. It owns ONLY the
consumer anti-rollback log below a root-owned, anchor-non-writable parent. It
owns no signing key, broker ledger, release, executable payload or publication
root and never executes Node/Metis. Its only mutation is an internally derived
monotonic advance after independent receipt verification.

2.6. No other principal exists. Any additional identity introduced into the
boundary is a design change requiring a new ratified brief.

## 3. Root-owned installed-code rule

3.1. Release, capsule, broker, worker, launcher, Node and loader ancestry
MUST be root-owned, immutable, and not writable by caller, broker, or runner
(BRIEF §Ratified design; freezes QWEN P0-1).

3.2. Every executed file MUST be:

- a regular file (S_ISREG);
- symlink-free over its full pathname ancestry;
- single-link (nlink==1);
- content-addressed;
- remeasured (hashed) from `O_NOFOLLOW` descriptors both before and after
  pathname execution.

3.3. Measure-then-execute TOCTOU soundness conditions (freezes QWEN P0-1 and
QWEN P1-2). The measure-then-execute claim is sound ONLY if ALL of the
following hold simultaneously:

1. the full ancestry of every executed byte is root-owned and immutable
   (chflags-class), so no caller, broker, or runner write or rename is
   possible anywhere along the path;
2. the measured object is a regular file (S_ISREG), not a symlink, hardlink
   alias (nlink==1), FIFO, device, or directory;
3. measurement opens the file with `O_NOFOLLOW` and hashes from that
   descriptor, never re-resolving the path;
4. execution uses the exact same pathname that was measured;
5. after pathname execution returns (post-exec), the same pathname is
   re-opened with `O_NOFOLLOW` and re-hashed, and the post-exec digest MUST
   equal the pre-exec digest;
6. the receipt records that the executed-preimage claim rests on these
   exec-time conditions, because post-exec kernel-image verification is not
   available to a non-root supervisor on macOS (no fexecve, no /proc).

3.4. If any condition of §3.3 cannot be established, the broker MUST fail
closed and MUST NOT issue a receipt.

## 4. Request model and claims-only digests

4.1. The caller request is JSON serialized with the repository canonical
codec (`canonical_json_bytes`, `src/metis_model1/provenance.py:61-73`): NFC
normalization, CRLF→LF, duplicate-key rejection, `allow_nan=false`,
`sort_keys`, UTF-8.

4.2. The request carries identifiers plus claimed digests ONLY. It MUST NOT
carry executable paths, argv, environment values, or ancillary file
descriptors.

4.3. Caller claims NEVER self-authorize. Every caller-supplied digest is a
`claimed_*` field — claims-only, never authority. The broker MUST re-measure
everything from root-owned ancestry and MUST reject any caller-supplied
(bytes, digest) pair as authority. Precedent that this rule exists to
prevent: the L30 forgery, in which a caller-supplied qualifier path plus a
matching digest once forged a `replay-qualified 2/10/5` qualification
(canonical-board:591-598; freezes QWEN P0-3).

4.4. The receipt MUST record claimed versus measured digests for every claim,
so a mismatch is visible to the consumer rather than silently substituted.

4.5. The out-of-band authority MUST independently pin the installed policy
identity, an exact six-role mapping (`broker`, `launcher`, `worker`, `loader`,
`runner`, `node`) from role to relative path and digest, and the complete sorted
roster of every release/capsule/runtime leaf that may execute or be imported.
The six role leaves are a required subset, never a completeness cap. The
release ancestry digest MUST be domain-derived from the release id plus this
complete canonical roster. A caller policy, a free scalar release digest, a
digest-only set, or the right digest under a different path/role MUST NOT
authorize execution.

## 5. Launcher binary protocol

5.1. `w3_privileged_launcher` MUST accept connections only from the exact
`_metisbroker` peer, verified by peer credentials on the original
authenticated connection.

5.2. The launcher MUST accept only a fixed, bounded binary frame carrying
opaque canonical payload bytes over that original authenticated connection.

5.3. The launcher MUST NOT parse JSON, MUST NOT implement any semantic API,
and MUST NOT accept caller-selected paths, argv, environment values, or
ancillary file descriptors (BRIEF stop rule 5).

5.4. Authority bytes and release mappings are installed out of band in
root-owned ancestry; they are never negotiated over the launcher protocol.

## 6. Credential-drop order

6.1. After accepting a frame from the broker peer, the launcher MUST perform,
in exactly this order:

1. `setgroups([])`;
2. `setgid(_metisrunner)`;
3. `setuid(_metisrunner)`;
4. proof that privilege cannot be regained (a setuid/setgid reversal attempt
   MUST fail);
5. closure of every non-allowlisted file descriptor;
6. application of the exact authority-bound Seatbelt policy;
7. exec of only the configured root-owned release.

6.2. Any failure at any step MUST abort before exec. No step MAY be skipped,
reordered, or made conditional.

## 7. Key isolation and custody

7.1. Production receipts use an authority-pinned Ed25519 key id. The key id
is bound into every signed receipt.

7.2. The signing key MUST be reachable by neither the caller nor the child
(the `_metisrunner` process and anything it spawns) (BRIEF stop rule 6;
freezes QWEN P0-2).

The key MUST also be unreachable by `_metisanchor`; receipt verification uses
only the root-owned public-key registry.

7.3. The key leaf MUST be owned by `root:_metisbroker` with mode `0440`, below
root-owned service-non-writable ancestry. This makes the seed readable by the
broker but not writable by it; root creates and measures it. The key MUST NEVER
appear in any environment variable. The Seatbelt policy applied by the launcher
MUST deny the key path to children.

7.4. Key custody model decision: noted as a Phase B evidence item. macOS
same-UID inter-process memory access (task_for_pid/ptrace between two
non-root same-UID processes under SIP/AMFI/hardened runtime) and
crash-report/core-dump ACLs for a dedicated-UID daemon are OPEN — they are
not verifiable offline and MUST be established by Phase B host evidence
before any production-authority decision (QWEN P0-2, §4). This
specification is written so that no requirement depends on resolving that
question either way.

## 8. Canonical request fields and complete receipt fields

8.1. The canonical request MUST contain exactly:

- authority id;
- release digest claim;
- payload reference;
- client nonce (`[0-9a-f]{64}`-class, generated by a CSPRNG);
- request hash (domain-separated SHA-256 over every other canonical request
  field; the `request_hash` field itself is excluded from its own preimage).

8.2. The receipt MUST bind ALL of the following; a signature that omits any
field is invalid (freezes QWEN P0-4, P0-5, P0-8):

- full path/size/mode/sha256 pre-execution and post-execution rosters,
  complete and NEVER truncated;
- claimed versus measured digests (§4.4);
- broker, launcher, worker, and runtime identities;
- effective UID/GID of every principal;
- resolved policy bytes and resolved policy parameters;
- request and nonces;
- the durable `attempt_sequence` assigned before side effects;
- the contiguous `receipt_sequence` assigned only after cleanup and atomic
  publication;
- previous receipt hash;
- sha256(stdout), sha256(stderr), and exit status;
- atomic publication record;
- exact cleanup census: process-census-zero, FD-census, and
  temp-residual-zero, each with measurement identity. Signing is PROHIBITED
  before the census closes (freezes QWEN P0-5);
- key id;
- a signature over the canonical serialization of EVERY receipt field except
  the signature value itself.

8.3. A truncated or summary-only roster MUST be rejected by the broker at
production time and by the consumer at verification time (QWEN P0-8).

## 9. Safe durable state order

9.1. The broker MUST execute the following total order, with no step
reordered or skipped:

1. validate the request;
2. durably consume the client nonce and reserve the global
   `attempt_sequence` BEFORE any side effect; do not allocate a receipt index
   or previous-head value at this point;
3. measure the protected preimages (§3);
4. invoke the launcher;
5. verify kill/reap/FD/temp cleanup and the pre/post rosters;
6. atomically publish the output;
7. under the same single-writer lease, assign the next contiguous
   `receipt_sequence` and current `previous_receipt_sha256`;
8. sign the complete receipt (§8.2);
9. durably append the EXACT signed bytes to the ledger;
10. advance the chain;
11. deliver the receipt.

9.2. Crash rule: a crash NEVER permits re-execution or re-signing under a
consumed nonce. A crash before durable receipt append tombstones the attempt;
because no `receipt_sequence` was allocated, it creates no consumer-visible
gap. A crash after durable receipt append returns the exact stored signed bytes.
Recovery NEVER re-signs (freezes QWEN P0-6).

9.3. The ledger is a single append-only broker-owned mode-`0600` leaf,
pre-created inside a root-owned, broker-non-writable ledger directory, with
per-record fsync. No other durable replay state exists. A non-persistent
nonce/replay ledger violates BRIEF stop rule 7.

9.4. Phase A freezes the ledger codec as length-prefixed canonical JSON records
with a record sequence, previous-record hash and domain-separated record hash.
Creation in Phase-A fixtures is no-follow/exclusive; installed operation MUST
use the pre-created leaf. The broker holds the opened parent descriptor while a
single writer lock spans consume, synthetic execution and finalization, and it
MUST verify before and after the locked transaction that both the parent and
named leaf still resolve to the opened inode. Replacement or unlink MUST fail
closed before receipt delivery. The parent directory entry is fsynced. Only a
partial next-record length prefix is an unambiguous torn tail that may be
truncated. A complete length prefix with a short or invalid body is ambiguous
and MUST stop recovery rather than permit ledger rollback.

The core defaults to the installed contract: every parent component is opened
root-to-leaf with `O_NOFOLLOW`, must be root-owned and non-writable by broker,
and automatic leaf creation is refused. The explicit
`allow_unprotected_test_ledger=true` path is synthetic-fixture-only, carries the
signed nonclaim `unprotected-test-stores-carry-zero-authority`, and MUST never be
enabled by a production broker. Any detected parent/leaf substitution
permanently poisons that broker instance before another executor call.

9.5. Every durable receipt record MUST be re-cross-bound during recovery to its
attempt: client nonce, request hash, authority, release, installed policy,
broker nonce, signing key, and attempt sequence MUST all match. A validly
signed receipt from another attempt wrapped in locally valid ledger metadata
is corruption and MUST stop recovery.

## 10. Replay: two meanings and nonce rules

10.1. Glossary (freezes QWEN P2-6). "Replay" has two distinct meanings and
every gate case MUST be labelled with which meaning it exercises:

- (a) Replay PREVENTION: one consumed nonce causes at most one execution and
  at most one durable receipt. A duplicate nonce MUST produce either a
  byte-identical idempotent return of the existing receipt, if one exists,
  or a typed error if the nonce was consumed without a durable receipt. It
  MUST NEVER cause a second execution or a second receipt.
- (b) Deterministic RE-EXECUTION: an identical payload submitted with a
  FRESH nonce is always allowed. This is how the
  2-process/10-invocation replay/qualification consumers are fed — 10
  receipts per qualification — and it MUST be accepted by consumers
  (freezes QWEN P1-12).

10.2. Same-nonce rule (meaning (a)): consumed-nonce state is decided by the
durable consume record of §9.1 step 2, never by in-memory state.

10.3. Fresh-nonce rule (meaning (b)): a fresh nonce with an identical payload
is a new execution, a new `attempt_sequence` and, if it completes, a new
`receipt_sequence` and receipt; it is never treated as a replay attack.

## 11. Consumer obligations

11.1. Every consumer of broker receipts MUST (freezes QWEN P0-7):

- persist the accepted `receipt_sequence` high-water and the chain head per
  authority;
- reject any `receipt_sequence` regression or gap;
- reject any fork — a divergent, individually-valid chain;
- reject any unknown key epoch;
- retain old public keys and release evidence for as long as any retained
  receipt depends on them.

The sole durable consumer truth MUST be a mutable anti-rollback CAS anchor with
an initialize-once identity, monotonic revision and the complete sorted
per-authority heads. Normal startup uses `load_required`; a missing, recreated
or stale anchor is failure, never implicit genesis. Receipt acceptance performs
`compare_and_swap(expected_anchor_sha256, next_anchor)` before success. A local
file may be only a cache. Phase A's explicitly named unprotected test store has
zero authority; the protected store and its no-delete/no-recreate/no-rollback
properties are Phase B evidence.

The protected implementation is the `_metisanchor` service. It receives one
launchd-activated socket and exposes exactly
`ADVANCE(expected_anchor_sha256, canonical_receipt)`. It accepts no
caller-supplied next-anchor value: it independently verifies the registered
authority, Ed25519 signature, key epoch, release, sequence and chain, derives
the next state, and appends it durably. The genesis leaf is pre-created by the
installer; there is no runtime initialize API. Exact replay of the current head
is idempotent, while deletion/recreation, stale CAS, regression, gap and fork
fail closed.

11.2. Consumer projection and normalization MUST exclude nonce,
`attempt_sequence`, `receipt_sequence`, and chain fields from identity hashes.
Precedent: `run_nonce` is excluded from the worker manifest hash
(`runtime/w3_production_worker.py:293`).

11.3. Schema supersession: the broker receipt schema supersedes or explicitly
version-supersedes the runtime identity roster of the existing
w3-run/oracle-result consumers
(`schemas/w3-run.schema.json:65-95`, 21 required fields,
`additionalProperties: false`); the tsx-residue fail-closed property MUST
carry over (freezes QWEN P1-10).

## 12. Key and release rotation

12.1. Key rotation (freezes QWEN P1-14):

- the global `receipt_sequence` MUST continue across key epochs; rotation never
  resets or forks the receipt chain. `attempt_sequence` independently remains
  monotonic in the audit ledger;
- old public keys MUST be retained for verification of historical receipts;
- revocation is future-only and MUST be published with a revocation
  high-water: receipts at or below the published high-water remain
  verifiable, receipts above it under the revoked key MUST be rejected.

12.2. Release rotation (freezes QWEN P1-15):

- the release is pinned at request validation; an in-flight request never
  migrates to a new release mid-execution;
- the receipt chain is per-authority and MAY span releases;
- retired release ancestry MUST be retained read-only until no retained
  receipt depends on it.

## 13. Public-synthetic nonclaims

13.1. The Phase A signer and executor doubles are explicitly labelled
synthetic. They are not Node, not Metis, and not a production key.

13.2. Every Phase A receipt MUST carry `executed_preimage_authority=false`
and MUST be constructed so that it can never satisfy a production invariant.
Precedent: the L66 comparator-labelling rule (QWEN §Phase A gate verdict;
authority schema non_claims `executed_preimage_authority=false`).

13.3. No Phase A artifact — receipt, ledger, key double, or executor double —
has executed-preimage authority of any kind.

13.4. Phase A receipts additionally state
`unprotected-test-stores-carry-zero-authority`. Passing an explicit test-only
ledger or anchor store never upgrades synthetic evidence.

13.5. Phase B uses a third, distinct evidence mode:
`protected-public-synthetic`. It uses Ed25519 and may state
`executed_preimage_authority=true` only for the exact measured public-synthetic
bytes that crossed the accepted host boundary. It MUST carry exactly these
nonclaims: `no-production-authority`, `no-production-evidence`,
`public-synthetic-only`, `no-semantic-accuracy-claim`, and `no-W5-credit`.
A key registered for this mode MUST NOT be accepted for `production`; the
consumer continues to reject `production` until a later ratified wave.

## 14. Install, upgrade, and rollback planning contract

14.1. Install order. The planner MUST emit exactly this order:

1. validate inputs;
2. create identities (`_metisbroker`, `_metisrunner`, `_metisanchor`);
3. install root-owned code, release, and launcher ancestry;
4. pre-create the broker-owned mode-`0600` ledger and anchor-owned mode-`0600`
   consumer log below their distinct root-owned, service-non-writable parents;
5. verify modes, owners, symlink-free and single-link (nlink==1) properties,
   and hashes of every installed byte;
6. provision the key;
7. install the three launchd plists;
8. bootstrap the launcher, anchor, then broker as socket-demand registrations;
   their exact plists and registered job identities are verified, but
   `RunAtLoad=false` and the absence of `KeepAlive` mean no pre-authority live
   process is required;
9. activate the prepared authority by the final no-clobber authority CAS;
10. only after that activation, issue exact `launchctl kickstart
   system/<label>` requests without `-k` for launcher, anchor and broker, then
   require each exact registered identity to reach `state=running` with a
   positive PID within the bounded poll before reporting success.

14.2. Rollback order. Rollback MUST reverse the install order:

1. withdraw authority;
2. stop the broker;
3. stop the anchor, then launcher;
4. archive the ledger, anchor and public verification material;
5. quarantine the key;
6. remove installed mutable state and code children-first.

The ledger, old public keys, and receipt evidence are NEVER deleted by an
ordinary rollback (freezes QWEN P2-1).

14.3. Upgrade. The new root-owned release MUST be installed and verified
(modes, owners, hashes) BEFORE activation. Old release evidence MUST be
retained until no retained receipt depends on it (§12.2).

14.4. The planner (`runtime/w3_broker_installer.py`) is declarative and
side-effect-free: it emits a plan and verifies predicates; it does not act.
Creating users, loading daemons, and provisioning real keys are Phase B only
and require the separate explicit authorization of §16.

14.5. The privileged entrypoint is a two-stage boundary. An administrator uses
only trusted `/usr/bin/install` and `/usr/bin/shasum` to place and externally
remeasure the fixed native Stage-0 binary and its narrow descriptor under
`/private/var/db/MetisModel1`. The administrator MUST invoke that binary through
trusted `/usr/bin/env -i` with only the fixed system `PATH`, so `DYLD_*`,
`PYTHONPATH`, locale hooks and every other ambient variable are absent before
the native image is loaded. Clearing the environment again inside `main` is
defence in depth; it does not authenticate or protect the pre-`main` dynamic
loader boundary. The non-circular bundle template freezes the exact argv shape
`/usr/bin/sudo -- /usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin
/private/var/db/MetisModel1/w3-installer-bootstrap --apply
--descriptor-digest <DESCRIPTOR_SHA256> --plan-digest <PLAN_SHA256>
--bundle-digest <MANIFEST_SHA256>` with cwd `/`. After the bundle, plan and
descriptor bytes are frozen, a separate canonical
`manifests/w3-phase-b-admin-invocation.json` resolves those three placeholders
to their raw SHA-256 digests and cross-binds the fixed Stage-0 binary. It is an
administrator runbook, not an input recursively hashed by the bundle.
Stage-0 accepts payload files only from
`/private/var/tmp/MetisModel1-w3-phase-b-source`, verifies the canonical
descriptor and complete exact-set through held descriptors, and creates the
staged tree without replacement. It then execs the staged CPython 3.13.3 as
`-I -B -m runtime.w3_broker_executor`, with cwd `/`, a sterile fixed environment.
The executor then validates the exact CPython/Darwin post-`exec` additions:
`LC_CTYPE=C.UTF-8` and a bounded three-hex-field
`__CF_USER_TEXT_ENCODING` whose first field equals the effective UID. It removes
both additions and reasserts the original PATH-only environment before any host
effect. Other keys, malformed fields, wrong UID or another locale fail closed.
The local UID-501 subprocess probe establishes this parser path only; the
effective-root post-`exec` values remain a target-host probe and receive no
static production credit.
The executor also requires exact plan and bundle digests. Repository Python, ambient `PATH`,
`PYTHONPATH`, cwd, shebangs, and caller-writable imports are never a privileged
entrypoint.

14.6. launchd registrations are deliberately socket-demand-only. The installer
does not use `KeepAlive` because launchd treats its subkeys as an implicit load
request. Registration receipts tolerate a waiting job with no PID; only the
post-authority kickstart and final-health gate require a running process. The
closed `launchctl print` parser is fail-closed but receives no production credit
until replayed on the target Darwin host. A second independent root actor that
concurrently installs the exact same package instance is outside the serialized
installer-journal threat boundary. Supported concurrency is limited to the fixed
Stage-0/executor processes sharing the same inode-bound journal lock. Before
privileged execution, the administrator MUST ensure that no other root process
or package manager can bootstrap, bootout, kickstart or replace the three fixed
labels during apply or recovery; otherwise the wave stops. A structurally
different job is never adopted or booted out by recovery, and automatic rollback
under independent-root mutation is non-attesting rather than a closure claim.

14.7. A frozen install bundle MUST contain the three exact raw wheel preimages
declared for `cryptography`, `cffi`, and `pycparser`; expanded cache trees and
lock-file sizes are not substitutes. If offline cache census reports fewer than
three raw wheel files, manifest, plan, descriptor and admin invocation remain
unmaterialized and the wave stops before any privileged action.

## 15. Stop rules (normative invariants)

The following stop rules are reproduced verbatim from BRIEF §Stop rules and
are normative invariants of this specification:

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

## 16. Phase A / Phase B boundary

16.1. Phase A MAY implement, payload-free and unprivileged:

- the protocol (`runtime/w3_broker_protocol.py`);
- the three schemas (authority, request, receipt);
- the client (`src/metis_model1/w3_broker_client.py`);
- the broker core (`runtime/w3_protected_broker.py`);
- the privileged launcher source contract (`runtime/w3_privileged_launcher.c`);
- installer planning (`runtime/w3_broker_installer.py`, §14.4);
- labelled public-synthetic tests.

Phase A MAY syntax-check the C source with `/usr/bin/clang -fsyntax-only`.
Any compiled binary MUST stay outside Git and has no authority until Phase B
(BRIEF §Phase A).

16.2. L70 MAY implement and test an installable bundle locally without
privilege, real keys, installed binaries or Node/Metis execution. Its maximum
outcome is `PHASE_B_INSTALLABLE_UNEXECUTED` and grants no host-evidence credit.

16.3. Phase B host execution requires a separate explicit authorization after
the L70 bundle is frozen and independently accepted. Under that authorization Phase B MUST
independently prove, with host evidence (BRIEF §Phase B):

- distinct UID/GID/group state of all five principals;
- irreversible credential drop (§6);
- key denial with and without Seatbelt;
- peer-UID rejection by the launcher;
- absent key, ledger, and listener FDs in the child;
- protected consumer-anchor pre-created genesis, CAS and anti-rollback behavior;
- fork, network, and out-of-root-write denial;
- timeout, process-group (PGID), and FD cleanup;
- immutable preimages under caller race;
- two fresh public-synthetic runs before any production-authority decision.

16.4. Any privileged action in §16.3 performed under Phase A or L70 authority violates the stop
rules of §15.
