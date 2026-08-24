# Model 1 W5-XS plan-closure brief

## Mandate

Close the corrected baseline-first plan after the user rejected the prior
weeks-long dependency path. This wave changes tracked plan/gate artifacts only.
It does not execute inference, Node/Metis, materialize a dataset, load a model,
train, use privilege, commit, push or publish.

## Preflight

- repository: `/Users/tommasotessarolo/Developer/metis-model-1`;
- baseline: `2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0` plus inherited dirty worktree;
- base identity: `mlx-community/Qwen3.8-27B-4bit@3e6447f082e89cc7f0bc6e5441afd38dfce760ff`;
- coordinator: L0 frontier; three internal read-only audit lanes;
- external Kimi/Qwen collaborators: excluded from the current critical path;
- expected output: ratified W5-XS sequence, split experiment/promotion gate,
  updated board and ledger, green repository verification;
- verification: focused pipeline tests, both readiness commands, Ruff/format,
  `git diff --check`, then `make check` under the pinned Node/Metis contract.

## Writable roster

- `README.md`;
- `Makefile`;
- `docs/00-charter-and-decisions.md`;
- `docs/02-dataset-and-provenance.md`;
- `docs/03-evaluation-and-gates.md`;
- `docs/04-training-runbook.md`;
- `docs/06-delivery-roadmap.md`;
- `docs/10-open-decisions.md`;
- `docs/11-feasibility-and-risks.md`;
- `docs/12-accuracy-99-execution-plan.md`;
- `docs/13-protected-execution-broker.md`;
- `docs/README.md`;
- new `docs/15-first-value-experiment.md`;
- `manifests/decision-register.json`;
- new `manifests/w5-xs-plan.json`;
- `manifests/w1-benchmark-seal-v1.json`;
- new `schemas/w5-xs-plan.schema.json`;
- `src/metis_model1/contracts.py`;
- `src/metis_model1/pipeline.py`;
- `src/metis_model1/cli.py`;
- `tests/test_pipeline.py`;
- active board and session ledger;
- this brief.

## Exclusions

All W1/W2/W3 data, broker and Phase-B implementation files; model/dataset
payloads; `qualification/train_full_state.py`; Accuracy-99 target values;
Metis repository bytes; credentials, `.env`, keychains and live ARES state.

## Acceptance

1. `assess-experiment` is green only for starting `BASELINE_B` and carries
   explicit nonclaims.
2. `assess-w5` retains the existing five Accuracy-99 blockers and non-zero exit.
3. The 3,000-example W5a recommendation is superseded by 12-task discovery,
   24 held-out, 64 train and 16 dev.
4. `NO_TRAIN` is a successful local-product outcome.
5. No execution authority is inferred from plan closure.
