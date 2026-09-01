# Metis Brain warm-model and complex E2E ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | architecture, implementation, semantic verdict, live model proof, promotion | Model 1 source/tests/docs/board | focused + `make check` + local no-Apply E2E | done |
| L301 | Warm-runtime design audit | `gpt-5.6-luna` / high | current worker protocol, strict config, startup/health/cleanup design | none | exact file/line proposal and test matrix | done |
| L302 | Complex-request semantic census | `gpt-5.6-luna` / high | reviewed play-demo fields/values and model-forcing request design | none | source/value provenance and expected DSL constraints | done |
| L303 | Final warm-runtime red-team | `gpt-5.6-luna` / high | post-change protocol, lifecycle, leakage and E2E evidence review | none | actionable verdict with focused reruns | done |
| L304 | Complex E2E harness census | `gpt-5.6-luna` / high | in-process no-token harness and public evidence boundary | none | API signatures and no-Apply assertions | done |

## Global exclusions

No lane may train, download or mutate weights/adapters, use Ollama or remote
fallback, read credentials/`.env`/Keychain/live data, require VPN, write or Apply
to a tenant, touch Metis/Visix/Metis Fast repositories, commit or push
independently. Delegated lanes are read-only.
