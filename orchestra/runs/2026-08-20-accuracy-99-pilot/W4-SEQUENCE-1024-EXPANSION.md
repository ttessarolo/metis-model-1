# W4 sequence-1024 technical expansion

Status: **PASS, bounded technical evidence only**.

This expansion proves that the pinned local Qwen3.8 27B 4-bit path can execute
a finite backward/update/checkpoint at 1,024 tokens for rank 8 and rank 16. It
does not use Metis data, does not measure semantic correctness, and does not
authorize W5 while O-003 or the W1/W3 data gates remain open.

## Fixed identity and boundary

- model: `mlx-community/Qwen3.8-27B-4bit` at
  `3e6447f082e89cc7f0bc6e5441afd38dfce760ff`;
- wrapper SHA-256:
  `af6053b88571dcd421943ef5dae1f7b8205b44e995d9c31a27f36e0bc525eae4`;
- fixture generator SHA-256:
  `7dde8a692e0e1ebf0f2b560f175120b8a4997fbea126291e6c5ec748d824c64e`;
- CPython `3.12.10`, MLX/Metal `0.32.1`, MLX-VLM `0.6.15`;
- `trust_remote_code=False` top-level and in processor config;
- public synthetic one-row dataset under ignored `artifacts/`;
- Metis checkout read-only and unchanged.

## Exact results

The rendered fixture had `7,414` raw tokens: prefix `20`, completion `7,394`.
`VisionDataset` plus `iterate_batches` produced a batch of exactly `1,024`
tokens with `1,004` retained completion-mask tokens. Dataset SHA-256 is
`07d359922351436c0ce6af55358b6fb25d3292d3aec47d6e2447d7b51cbb11c9`;
fixture report SHA-256 is
`cbb5f1a1179d1f83c2a5478636b4535adfe4cb9701d277c667bdff35fd5c458b`.

| Probe | Result | Loss | Peak Metal | Checkpoint bytes |
|---|---|---:|---:|---:|
| rank 8, alpha 16, step 1 | PASS | `0.0608372837` | `94.43498243 GB` | `935,483,301` |
| rank 8, resume to step 2 | PASS | `0.0536097251` | `95.037375128 GB` | `935,483,304` |
| rank 16, alpha 32, step 1 | PASS | `0.0608372837` | `94.81756623 GB` | `1,869,318,364` |

Every run used batch 1, accumulation 1, LR `1e-5`, seed 17, dropout 0 and
completion-only training. The wrapper checked finite non-zero gradients before
the update, finite trainable weights and optimizer state after the update, and
published each checkpoint with a complete SHA-256 manifest. L0 independently
recomputed all four rank-8 step-1 and step-2 payload hashes; they matched.

## Decision consequence

The evidence supports the small pre-registered grid in
`manifests/hyperparameter-grid.json`: ranks 8/16, alpha fixed at 2x rank and
LRs `1e-5`/`2e-5`. A 110 GB Metal peak is a hard stop. Sequence 2,048 and
positive dropout remain unqualified. The grid is an execution constraint, not
evidence that any candidate improves Metis.
