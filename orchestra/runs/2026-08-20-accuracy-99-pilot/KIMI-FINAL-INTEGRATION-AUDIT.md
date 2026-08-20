# Kimi K3 final integration — frontier acceptance record

## External identities

- K2 activity `metis-model1-accuracy99-integration-audit`, wrapper
  `20260820-193131`, session
  `session_2a3ab80a-a975-4f1c-a443-1b1e69c5a4f2`, 1,015 seconds.
- K2 source report SHA-256:
  `23d11be2cd3cd41beb135c4b381ec11f49841f146472d6103f2483b70a25003e`.
- K3 remediation activity `metis-model1-accuracy99-remediation-audit`, wrapper
  `20260820-195610`, session
  `session_8a19981a-5033-42df-a200-e51b59422b3a`, 538 seconds.
- K3 remediation report SHA-256:
  `3756f117bfa44be4ea74ca8613ad30953ec2bb7db09418581fc243b6966a2a10`.
- K3 resumed lineage follow-up wrapper `20260820-200634`, same session,
  183 seconds; report SHA-256:
  `863807b0d87f7bad97a224571739dd3e972bb2e1a1c1ccef2d25adb6d7e14be7`.

External runtime reports remain in the ignored orchestra activity workspaces.
This tracked record is L0's acceptance and correction record; it is not a model
promotion or distribution authorization.

## K2 finding and remediation

K2 independently recomputed the 600-task target, Wilson limits, 563 minimum,
closure `30/30` plus `201/201`, asset register `201/201`, all technical probe
hashes and the W5 blocker set. It found one P0: a self-consistently poisoned
closure/assets pair could pass the original standalone `validate-pilot`, even
though `make check` caught it through a Git-recompute test.

L0 accepted the finding and required rework. The final gate now:

1. recomputes the leakage-group identity from the complete closure inventory;
2. regenerates the entire closure from the pinned Metis revision using Git
   objects only and requires exact equality;
3. fails closed if the source checkout is missing;
4. derives open W5 decisions from the tracked register;
5. reports the exact project root, source checkout and source revision.

K3 re-executed both attacks. A stale leakage identity is rejected locally; an
attacker who recomputes the identity and asset self-hash is rejected by the
pinned Git reanchor. All 201 path/OID pairs matched the pinned commit.

## Frontier correction after K3

The first K3 remediation report called the enumerated P2-2 lineage gap closed,
but it had exercised only cross-split parent examples. L0 frontier review found
that a same-split child could still cite a parent example while claiming a new
leakage group. That would permit artificial inflation toward the 563-group
gate.

L0 added the missing invariant: an example named as a provenance parent and
its child must share both split and leakage group, independent of row order.
K3 resumed the same session, explicitly corrected its earlier overbroad
statement and executed different-split/different-group, same-split/different-
group and same-split/same-group cases in both orders. The inflation vector is
closed; valid multilevel same-group lineage and the non-example parent-asset
rule remain intact.

## Final frontier verdict

`ACCEPTED_AFTER_REWORK_AND_CORRECTION` for the integrated foundation. The final
code has no open P0/P1 from K2/K3 or L0's follow-up review. Residual boundaries
are explicit rather than hidden:

- evaluator evidence hashes cannot be anchored to real evaluation artifacts
  until the real W3/W5 artifact path exists;
- a caller may intentionally use explicit `--root` and `--metis-root` paths,
  which are therefore printed in every report;
- the current data is synthetic and the current benchmark ancestry supplies
  one, not 563, independent leakage groups.

`make check` is green with 134 tests. `validate-pilot` exits 0 for the exact
contract-valid local tree; `assess-w5` exits 1 on five blockers. Metis remained
read-only at `a2dde2b191f6b78c2003d74875560da782470968` with its exact four
pre-existing untracked entries unchanged.
