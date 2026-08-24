# Kimi L68 Phase A — installer, launchd plan and security specification writer

## Mandate

Work in `/Users/tommasotessarolo/Developer/metis-model-1` at baseline HEAD
`2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0` plus the complete inherited dirty
L66/L67/L68 state. Preserve every inherited byte and do not commit or push.

Read `AGENTS.md`, the canonical board and ledger,
`orchestra/briefs/2026-08-23-model1-l68-protected-execution-broker.md`, the Kimi
governance review report and the Qwen final broker report in shared activity
`model1-l68-fast-closure`.

## Exact writable roster

1. `runtime/w3_broker_installer.py`;
2. `packaging/launchd/com.metis.model1.w3-broker.plist.in`;
3. `packaging/launchd/com.metis.model1.w3-launcher.plist.in`;
4. `tests/test_w3_broker_lifecycle.py`;
5. `docs/13-protected-execution-broker.md`.

Everything else is read-only. The team master delegates installer/plist/spec
units, validates returned work and writes only the five paths above.

## Installer contract

Implement a declarative, side-effect-free install/upgrade/rollback planner. It
returns canonical plan data and validates preconditions; it never invokes
`dscl`, `sysadminctl`, `launchctl`, `chown`, `chmod`, key generation, compiler
or any privileged mutation.

The plan fixes:

- principals `_metisbroker` and `_metisrunner`, both non-root and distinct;
- root-owned installed broker/runtime/release ancestry under
  `/Library/Application Support/MetisModel1`, the launcher under
  `/Library/PrivilegedHelperTools`, and root-owned LaunchDaemon plists;
- broker code is root-owned and not writable by broker/caller; only state,
  publication and key leaves are writable/readable by `_metisbroker` as
  explicitly required; runner writes only to bounded per-run roots;
- install order: validate inputs -> create identities -> install root-owned
  code/release/launcher -> verify modes/owners/symlink-free/single-link hashes ->
  provision key -> install plists -> bootstrap launcher then broker -> register
  authority last;
- rollback order: withdraw authority -> stop broker -> stop launcher -> archive
  ledger and public verification material -> quarantine key -> remove installed
  mutable state and code children-first; never delete the ledger or old public
  keys/receipt evidence as an ordinary rollback step;
- upgrade installs and verifies a new root-owned release before activation and
  retains old release evidence until no receipt depends on it.

The broker plist runs as `_metisbroker`. The launcher plist runs as root. Both
use fixed root-owned `ProgramArguments`, a sterile environment, bounded
KeepAlive/Throttle behavior and launchd-owned socket activation. No template
contains repository paths, secrets or caller-selected values.

## Security specification

`docs/13-protected-execution-broker.md` is normative. It must encode the
four-principal architecture, root-owned installed-code rule, claims-only
digests, fixed launcher binary protocol, credential-drop order, key isolation,
canonical request and complete receipt fields, safe durable state order,
same-nonce and fresh-nonce rules, consumer high-water/chain-head obligations,
key/release rotation, two meanings of replay, public-synthetic nonclaims,
Phase-A/Phase-B boundary and all stop rules from the corrected L68 brief.

## Exact focused denominator

Create exactly `6` installer/planning cases inside
`tests/test_w3_broker_lifecycle.py`:

1. distinct non-root identities and disjoint writable roots;
2. install dependency order and authority-last;
3. full root-owned ancestry/mode/symlink/single-link verification requirements;
4. broker and launcher plist fixed identities, paths, sockets and sterile env;
5. rollback order with ledger/public-key/evidence retention;
6. upgrade installs-before-activates and retains referenced releases.

Validation: focused pytest reports `6 passed`; Python compile; Ruff and
format-check on product/test Python; plist XML parse; `git diff --check`; exact
writer roster `in=5 out=5 distinct=5 gaps=0`. No Node, runner, compiler, network,
credential, key, user, launchd, model/data payload, training or privileged action.

## Return

Deposit a final report in the shared activity artifacts directory with:

1. `What I did`;
2. `How I validated it`, including `6/6` and writer-roster arithmetic;
3. `STOPs`;
4. `What I could not establish`.
