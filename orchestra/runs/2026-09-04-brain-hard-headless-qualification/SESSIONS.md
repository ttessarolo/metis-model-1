# Metis Brain hard headless qualification ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | architecture, semantic adapters, runner integration, live execution, gates and verdict | board/docs, runner/config/tests/CLI | independent diff, focused/full gates and live receipts | active |
| L901 | Corpus contract census | delegated `gpt-5.6-luna` / low | exact edit/journey roster and executable-oracle gaps | none; read-only | counts and absolute source evidence | done |
| L902 | Headless runner census | delegated `gpt-5.6-luna` / low | reusable HTTP/service/guard surfaces and smallest safe runner design | none; read-only | source/test anchor matrix | done |
| L903 | Qualification authority census | delegated `gpt-5.6-luna` / low | clean repos, tenant/config/model payload presence and runtime census | none; read-only | Git/path/process evidence | done |
| L904 | Runner adversarial review | delegated `gpt-5.6-terra` / high | security, authority, cleanup, publication and transport audit | none; read-only | source anchors, focused gates, P0/P1/P2 verdict | done |
| L905 | Runner state-machine review | delegated `gpt-5.6-luna` / high | exact 10 + 10x4 attempt semantics, `/answer`, basis and verdict arithmetic | none; read-only | corpus-to-runner transition matrix | done |
| L906 | Semantic oracle census | delegated `gpt-5.6-luna` / high; QWEN: no (native Luna lane) | assessed Draft roster, private compile-structure oracle and final normalized-IR equivalence | none; read-only | 30 assessed Draft turns / 50 logical messages; 10/10 pinned source endpoints compile; P0 false-green closure evidence | done |
| L907 | Pin/security review | delegated `gpt-5.6-terra` / high; QWEN: no | exact corpus/config/tenant/Metis/model/Flash/runner pins and no-Apply boundary | none; read-only | hashes and revision/tree guards already recorded on active board and tracked config | done |
| L908 | IR feasibility review | delegated `gpt-5.6-luna` / high; QWEN: no (native Luna lane) | structural IR facts plus final normalized IR equivalence needed to prevent P0 false-green | none; read-only | private oracle evidence recorded; live run receipt still required | done |
| L909 | Harness concurrency security review | delegated `gpt-5.6-terra` / high; QWEN: no | allow clean source HEAD advancement while binding pinned archive/runtime and rejecting dirty source drift | none; read-only | focused regression plus P0/P1/P2 verdict | done |

## Global exclusions

Delegated lanes may not edit, start services, run models, read secrets, use the
network, touch tenants, commit or push. L0 alone may run the explicitly
authorized local MLX qualification after deterministic gates are green.
