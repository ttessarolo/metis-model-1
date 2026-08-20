# K3 follow-up — parent-example leakage-group invariant

Resume the K3 remediation context. Work read-only in both repositories. A
frontier review after your CLEAN snapshot found one P1 outside the narrower
cross-split attack you executed: a child could reference another example ID as
its provenance parent, remain in the same split, but declare a different
`leakage_group`. That would permit derived examples to inflate the distinct
group denominator.

L0 has now changed only `src/metis_model1/dataset.py` and
`tests/test_dataset.py` so a parent example and child must share both split and
leakage group, regardless of row order. The full local gate currently reports
`make check` exit 0, 134 tests; `validate-pilot` exit 0; `assess-w5` exit 1.

Adversarially execute these four cases, without trusting the test names:

1. parent and child in different splits, different groups — reject;
2. same split, different groups — reject;
3. same split, same group — accept;
4. repeat all relevant cases with row order reversed.

Confirm ordinary non-example parent assets retain their existing one-split
rule and that no valid same-group lineage is rejected. Run the focused dataset
tests, `make check`, and the two pilot commands with exact exit codes. Compare
both repositories' HEAD and `git status --short` before and after; Metis must
retain exactly its four pre-existing untracked entries.

Write `kimi-lineage-group-followup.md` in the existing remediation activity
artifacts directory. Return `CLEAN`, `REWORK`, or `STOP`, ranked findings, and
explicitly correct the earlier K3 statement that P2-2 was fully closed if the
new invariant was indeed missing from that audited snapshot.
