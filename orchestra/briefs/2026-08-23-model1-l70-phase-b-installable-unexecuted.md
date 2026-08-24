# L70 — Phase B installable bundle, unexecuted

## Status and maximum outcome

AUTHORIZED FOR LOCAL TESTS-FIRST IMPLEMENTATION ONLY. L70 may reach only
`PHASE_B_INSTALLABLE_UNEXECUTED`. It creates no service identity, key, daemon,
installed binary, host receipt, model/data payload or production authority and
does not execute Node/Metis. Privileged host work remains a later explicit
authorization.

## Grounded entry state

- Phase A is accepted separately at `73/73` as
  `BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE`;
- the host is compatible but empty: legacy broker/runner user+group records
  observed `0/4`, while the ratified final user+group roster is `0/6` after
  adding `_metisanchor`; installed tree `0/13`, ledger/key `0/2`, services
  `0/2`, sockets `0/2` were observed before the third service was ratified;
- launcher runtime returns `ENOTSUP` and has no accept loop;
- broker core is synthetic-only and has no service, real signer or launcher
  transport;
- consumer rejects Ed25519 and exposes only an unprotected test anchor;
- installer is declarative only and no host-evidence harness exists.

L70 supersedes the four-principal/two-service design before host installation:
the final boundary is five principals and three services.

## Ratified architecture

### Evidence modes

The protocol has three disjoint modes:

1. `synthetic`: Phase-A HMAC, `executed_preimage_authority=false`, zero
   authority;
2. `protected-public-synthetic`: Ed25519, actual protected-host execution of
   public fixtures only, and exact nonclaims `no-production-authority`,
   `no-production-evidence`, `public-synthetic-only`,
   `no-semantic-accuracy-claim`, `no-W5-credit`;
3. `production`: still rejected and unavailable.

Keys and authority registrations are mode-scoped. A protected-public-synthetic
key can never validate production.

### Cryptography

Use only the pinned `cryptography` Ed25519 implementation. No custom crypto,
`ctypes` crypto, OpenSSL shell or caller-selected signer is allowed. Resolution
and installation during L70 must use the existing local `uv` cache with network
disabled; otherwise stop. The exact version, wheel hash, Python runtime and
complete imported/executed roster must be frozen before installation.

### Principals and services

- caller: untrusted client;
- `_metisbroker`: broker service, broker ledger and bounded publication only;
  it can read but cannot modify the root-owned `_metisbroker`-group signing seed;
- root launcher: credential drop and fixed execution only; no JSON, signing or
  semantic API;
- `_metisrunner`: the only Node identity;
- `_metisanchor`: public-key receipt verification and append-only consumer
  anchor only; no private key, broker ledger, payload or Node.

Launchd supplies all three listening sockets. Daemons never bind or unlink
their own socket path. The launcher uses
`launch_activate_socket("LauncherListener")`; broker and anchor use a minimal
root-owned fixed-target socket shim that passes exactly FD 3, sterilizes the
environment and execs only its installed entrypoint.

The anchor service exposes only
`ADVANCE(expected_anchor_sha256, canonical_receipt)`, derives the next anchor
internally and persists an append-only record below a root-owned parent. Genesis
is pre-created by the installer. Exact current-head replay is idempotent;
delete/recreate, stale CAS, regression, gap and fork are denied.

### Installation boundary

The existing planner remains pure. A separate macOS executor is default
dry-run, uses structured argv without a shell, journals every transition, and
can apply only at EUID 0 with `--apply` plus the exact frozen plan and raw bundle
digests. A fixed native Stage-0, externally installed and remeasured with trusted
system tools, MUST be invoked through trusted `/usr/bin/env -i` with only the
fixed system `PATH`, removing `DYLD_*`, `PYTHONPATH` and every other ambient
variable before image load. The in-`main` scrub is defence in depth and makes no
claim that Stage-0 authenticates the pre-`main` dynamic loader. Stage-0 verifies and exclusively materializes the complete payload-only
source tree before executing staged CPython 3.13.3 as
`-I -B -m runtime.w3_broker_executor` under a sterile environment and cwd `/`.
CPython/Darwin adds only `LC_CTYPE=C.UTF-8` and a bounded three-field
`__CF_USER_TEXT_ENCODING`; the executor binds its first field to the effective
UID, rejects every other key/value shape, removes both additions, and proves the
environment is PATH-only before effects.
The local UID-501 subprocess probe is non-attesting; effective-root values still
require the future target-host probe.
The manifest freezes an exact non-circular invocation template beginning
`/usr/bin/sudo -- /usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin` and ending
in literal `--descriptor-digest`, `--plan-digest`, and `--bundle-digest`
placeholders. A fourth canonical admin-invocation runbook resolves those values
only after the descriptor, plan, and bundle bytes exist; the runbook is not
recursively included in the bundle digest.
Running the executor from this repository is a stable refusal.
The three launchd jobs are socket-demand registrations with `RunAtLoad=false`
and no `KeepAlive`. Before authority activation they are checked for exact
registration identity only. After the authority CAS, the installer journals an
exact no-`-k` kickstart for launcher, anchor and broker and requires bounded
exact-identity `running`/positive-PID health. Foreign identity, failed start,
timeout and crash/retry remain fail-closed. The target-Darwin `launchctl print`
shape remains a host-probe gate, and independently concurrent identical root
installers remain an explicit nonclaim outside the single journal lock. Only
fixed Stage-0/executor processes sharing that inode-bound journal lock are a
supported concurrent path. Before privilege, the administrator must exclude
every other root/package-manager bootstrap, bootout, kickstart or replacement
of the fixed labels during apply/recovery; otherwise execution stops and any
automatic rollback is non-attesting.
System operations are simulated in every L70 test. Real identity creation,
filesystem ownership/modes/flags, key generation, launchd operations and
rollback wait for the Phase-B host mandate.

The current offline cache has raw-wheel census `in=3 out=0 distinct=0 gaps=3`.
Extracted archives and lock-file scalar sizes do not satisfy the raw preimage
contract. Therefore the production bundle, plan, descriptor and admin runbook
must remain absent until a separately authorized exact-three public-wheel fetch
remeasures the pinned hashes; no placeholder artifact receives installable
credit.

## Dependency order and disjoint writer roster

1. **L70.0 — L0 serial:** normative spec, this brief and boards.
2. **L70.1 — protocol/crypto serial:** protocol, Ed25519 module, authority and
   receipt schemas, locked dependency and `test_w3_phase_b_crypto.py`.
3. **L70.2 — parallel after L70.1:**
   - native lane: launcher C, socket shim, launcher plist and native tests;
   - broker lane: broker service/launcher transport, core adapter, broker plist
     and service tests;
   - anchor lane: anchor daemon/log, protected client transport, anchor plist
     and anchor tests.
4. **L70.3 — L0-assigned serial integration:** planner, separate executor,
   install-bundle manifest/schema, a zero-credit host-evidence manifest/schema,
   and integration tests.
5. **L70.4 — frontier audit:** threat replay, diff inspection, schema and roster
   recomputation. Only an accepted audit may open the privilege request.

Concurrent writers have no shared files. Existing Phase-A tests and statuses
remain immutable evidence and must continue to pass.

## Deterministic gates

The new local acceptance denominator is exactly `50/50`, separate from Phase A:

- Ed25519 KAT/mutation/key/encoding: `12/12`;
- operational socket/framing: `10/10`;
- broker service/lifecycle: `10/10`;
- protected anchor: `8/8`;
- installer/launchd/evidence contracts: `10/10`.

L70 additionally reruns the existing `73/73`, all touched schemas, foundation,
Ruff, format, Python compile, both launcher compile-time branches and
`git diff --check`. It does not run `make check` when that would cross the
active Node/production STOP.

## Future host gate — currently zero evidence

Phase B must later report these separately:

- host predicates `0/28`: 14 obligations, each positive and adversarial;
- fresh runs `0/2`;
- candidates per run `0/3`;
- semantic roles per run `0/5` (`author`, `before`, `after`, `mutated`, `fixed`);
- physical executions `0/10 = 2 x 5`;
- `gaps=0` only for a completed roster; the frozen not-run manifest reports the
  deficit as not computed and cannot attest completion.

Each host report binds command, installed bundle, authority, public key, roster,
process/FD/temp census and artifact hashes. These denominators cannot collapse
into one generic green.

The L70 host-evidence document remains `not-run` and non-attesting. Local
fixtures do not earn host credit. A production `complete` result is denied until
a separately authorized future Phase-B collector/verifier has executed and
validated the full 28-probe packet and its 2/3/5/10 denominators.

## Stop rules

Stop on any privilege, service identity, real key, installed binary, launchd
mutation, Node/Metis run, network access, model/data payload, private/live data,
production mode acceptance, unpinned dependency, custom crypto, shell command
execution by the installer, caller-supplied next anchor, shared writer file,
test-denominator drift, commit, push, upload or promotion.

## Authorization boundary after L70

Only after `73/73 + 50/50`, frozen schemas/bundle/roster and frontier acceptance
may L0 request authority for exactly: `_metisbroker`, `_metisrunner`,
`_metisanchor`; root-owned bundle and three plists; one public-synthetic
Ed25519 key; pre-created ledger/anchor; launchctl; 28 host probes and two fresh
public-synthetic runs; fail-closed rollback. Production authority, private data,
model work, training, promotion, upload, commit and push remain excluded.
