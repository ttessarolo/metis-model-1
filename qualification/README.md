# W4 MLX qualification runtime

This directory defines the isolated, reproducible runtime used only by the W4
qualification gate. It is not the application environment.

## Qualified bounded pin

- Python `3.12.10`
- MLX `0.32.1`
- MLX-VLM `0.6.15`
- Transformers `5.14.0`
- Datasets `5.0.1`
- Jinja2 `3.1.6` (required by the Transformers chat-template path)
- NumPy `2.5.2`
- safetensors `0.8.0`
- psutil `7.2.2`

The pin is qualified for the exact public synthetic batch-1, sequence-128,
rank-8, alpha-16, LR-`1e-5`, seed-17, dropout-0 path. CLI, strict model load,
deterministic generation, backward, 10/50/600 iterations, checkpoint/reload,
adapter-off and full-state stop/resume produced evidence. The durable summary is
[`W4-QUALIFICATION.md`](../orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md).

## Boundary

Run `uv sync --project qualification --locked` from the repository root. The
virtual environment is local and ignored. Model caches, generated JSONL,
trainer logs, checkpoints and adapters belong under the ignored `artifacts/`
tree. Only redacted reports, hashes and configuration may enter Git.

Upstream MLX-VLM checkpoints contain adapter weights and configuration, not
optimizer state, RNG state or a global step. `train_full_state.py` is the local
fail-closed wrapper that adds and verifies that state; its bit-exact result must
not be misreported as a native MLX-VLM resume capability. Expanded context,
batch, accumulation or stochastic settings require a new qualification.
