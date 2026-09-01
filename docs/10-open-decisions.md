# Open decisions

The operational source of truth is
[`manifests/decision-register.json`](../manifests/decision-register.json). This
document explains the gating view; resolutions are recorded in the manifest and
then reflected here and in the relevant decision document.

| ID | Status | Decision | Deadline | Currently blocks |
|---|---|---|---:|---|
| O-001 | RATIFIED | Canonical Metis language `0.43` for Model 1 | W1 | — |
| O-002 | RATIFIED | Held-out families and criticality | W1 | — |
| O-003 | OPEN | Final metrics and statistical tolerances | W5 | W5 |
| O-004 | RATIFIED | Pinned `mlx` / `mlx-vlm` versions | W4 | — |
| O-005 | RATIFIED | Rank/alpha/LR/seed grid | W5 | — |
| O-006 | RATIFIED | Local artifact-store format | W5 | — |
| O-007 | OPEN | Multi-task or task-specific adapters | W7 | W7 |
| O-008 | OPEN | VSIX/Metis Fast workflow, streaming, app pairing and Mac packaging | W8 | W8 |
| O-009 | OPEN | Distribution beyond local-only | W8 | External distribution only |
| O-010 | RATIFIED | Lightweight-first maintenance path for Metis changes | W7 promotion | — |
| O-011 | RATIFIED | Baseline-first experiment separated from Accuracy-99 promotion | W5-XS | — |

## Immediate ratification packet

O-001 was ratified on 20 August 2026 from these grounded inputs:

- Metis source commit: `a2dde2b191f6b78c2003d74875560da782470968`;
- language constant at that commit: `0.43`;
- tooling package version at that commit: `0.23.87`.

The resolution selects `0.43` as the v1 authoring language; the package version
remains provenance and is not a substitute for the language version.

O-002 was ratified from the pinned 197-file / 170-endpoint census, the six-family
coverage matrix, and a frontier leakage review. The allocation lives in
[`manifests/benchmark-plan.json`](../manifests/benchmark-plan.json). Its 30
distinct source references are a schema-valid slice allocation, not a frozen
benchmark: dependency closure, data-rights review and task-specific oracle
execution remain explicit seal blockers.

O-004 was ratified for the exact isolated CPython `3.12.10`, MLX/MLX Metal
`0.32.1` and MLX-VLM `0.6.15` runtime. The pinned Qwen3.8 27B 4-bit checkpoint
passed strict load, deterministic generation, finite backward, 10/50/600
iterations, save/reload, observable adapter-on/off behavior and a bit-exact
full-state 4-step versus 2-step-plus-resume comparison. The executed packet and
hashes are recorded in
[`W4-QUALIFICATION.md`](../orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md).

The pin is qualified only for the recorded public synthetic batch-1,
sequence-128, rank-8, alpha-16, LR-`1e-5`, seed-17 and dropout-0 path. The
checkpoint card's observed conversion version remains `0.6.8`; it is provenance,
not the selected trainer pin. O-004 does not establish W5 semantic uplift,
1,024/2,048-token memory behavior, benchmark readiness or redistribution rights.

O-006 was ratified from an exact local storage measurement and the executable
policy in [`manifests/artifact-store-policy.json`](../manifests/artifact-store-policy.json).
Each W5 run is confined to ignored `artifacts/w5/<run-id>`, capped at 40 GiB
excluding the shared base, and refused unless at least 100 GiB is free while a
60 GiB post-reservation floor remains. Published checkpoints use payload hashes,
fsync and atomic rename; resume/evaluation reverify them. Published artifacts are
never deleted automatically: cleanup requires explicit operator action after the
frontier verdict and durable report hashes.

O-005 was ratified only after public-synthetic 1,024-token backward probes for
rank 8 and rank 16 plus a real rank-8 full-state resume. The exact grid and
budgets are in
[`manifests/hyperparameter-grid.json`](../manifests/hyperparameter-grid.json):
four screening configurations, alpha fixed at twice the rank, one screening
seed, then three finalist seeds selected on dev semantic evidence only. The cap
is 700 optimizer steps, 18 hours and 32 GiB of published checkpoints; 110 GB
peak Metal is a hard stop. This closes the grid decision, but does not bypass
O-003 or the W1/W3 benchmark and dataset gates.

O-010 ratifies a lightweight-first maintenance path before the first promotion.
Every Metis revision is pinned and impact-measured. The existing adapter is
tested first with refreshed retrieval and current compiler/oracle feedback; a
green result is `NO_RETRAIN`. If only that gate fails while AST/IR and verified
semantics remain compatible, the maximum intervention is `DELTA_QLORA` from the
previous version, using oracle-accepted delta examples plus a provenance-clean
replay set and dev-only selection. `FULL_SUCCESSOR` is required only for an
AST/IR or semantic-contract change, or when the lightweight path still fails
semantic or replay gates. Previous benchmarks, datasets and adapters remain
immutable and available for historical attribution and rollback.

O-011 ratifies two non-interchangeable readiness gates.
`EXPERIMENT_PLAN_READY` certifies only the machine-readable W5-XS plan and
explicitly is not baseline, training authority, semantic-uplift evidence,
promotion or a 99% claim.
`ACCURACY99_PROMOTION_READY` retains the complete strict gate, including O-003,
600/563, W1/W3 closure and A/B evidence. A green B baseline may close the local
product as `NO_TRAIN`; only repeatable semantic failures can open a bounded
micro-dataset and one rank-8 experiment.

D-013 ratifies the Metis Brain product direction without closing O-008 or O-009.
D-015 and the Brain v1 wave now fix the numeric-loopback session/compiler core,
bootstrap/session authentication, immutable tenant snapshots, capabilities and
20-minute idle expiry. The demo still requires an installable macOS app and the
Metis VS Code extension as editorial client. Inference is local-first, real
changes require toolchain evidence plus human confirmation, and every remote or
VS Code tool fallback must be explicit, policy-controlled and visible. Model
protocol, streaming/editor workflow, app pairing, packaging, release channel
and distribution evidence remain open for W8. Windows is outside the demo scope
and may be evaluated only after project approval.

D-016 ratifies the internal Flash intent compiler without closing O-008 or
O-009. Gemma 4 E4B is qualified only as a direct-MLX, startup-warm,
schema-constrained helper inside Brain. Its exact operator spans may trigger a
reviewed retrieval retry, but it owns no result count, catalog, field, value,
DSL or Apply decision. The local development proof is green; bundling the Gemma
payload in the Mac app and every external distribution channel still require
the packaging and license evidence governed by O-008/O-009.
