# Reference Mapping

This is NOT official evaluation.
Do not claim official accuracy from this audit.
Do not rename dry-run outputs to official_results.jsonl.

## 1. Reference Inventory

See `docs/literature_traceability.md`.

## 2. Module-to-Reference Matrix

| Module | Relationship | References |
|---|---|---|
| Stable Core / Pipeline | engineering_adaptation_of | [R1], [R2], [R5] |
| Shadow Eval / Evaluation Layer | evaluation_inspired_by | [R2], [R3], [R4] |
| Agent Debugger | engineering_adaptation_of | [R3], [R5] |
| Hard-mode Control | engineering_adaptation_of | [R1], [R2], [R5] |
| Candidate Budget / Verifier Routing | engineering_adaptation_of | [R4], [R7], [R8] |
| Weighted Voting / Verifier Scoring | evaluation_inspired_by | [R7], [R8] |
| Proof Guardian | engineering_adaptation_of | [R5], [R7], [R8] |
| Official-like Dry Run | safety_traceability_inspired_by | [R2], [R3], [R4] |
| Demo Evidence Pack | safety_traceability_inspired_by | [R2], [R3], [R4] |
| Safety / Quality / CI | safety_traceability_inspired_by | [R2], [R3], [R5], [R6] |

## 3. Reference-to-Module Matrix

| Reference | Related Modules | Evidence Files | Claim Strength | Notes |
|---|---|---|---|---|
| [R1] | Stable Core, Hard-mode Control | `src/math_agent/pipeline.py`, `src/math_agent/control/policy.py` | weak | self-improvement 思路的受控工程化适配。 |
| [R2] | Eval, Dry Run, Demo Pack, Safety | `src/math_agent/evaluation/*`, `src/math_agent/submission/*`, `scripts/check_project_safety.py` | medium | benchmark/traceability/safety sandbox 思路。 |
| [R3] | Debugger, Eval, Evidence | `src/math_agent/debugger/*`, `scripts/debug_shadow_failures.py`, `scripts/shadow_eval.py` | medium | observability 与 debugger 机制工程化。 |
| [R4] | Eval loop, scoring/routing | `src/math_agent/evaluation/*`, `src/math_agent/control/candidate_budget.py`, `src/math_agent/control/verifier_routing.py` | weak | evaluator/scoring loop 思路。 |
| [R5] | Hard-mode, debugger, memory harness | `src/math_agent/control/*`, `src/math_agent/debugger/*`, `src/math_agent/harness/memory.py` | weak | meta-control 与 performance tracking 灵感。 |
| [R6] | Tool/safety guard | `src/math_agent/tools/*`, `scripts/check_project_safety.py`, `src/math_agent/proof/*` | medium | harness guard/illegal action prevention 思路。 |
| [R7] | Verifier + voting + proof filtering | `src/math_agent/verification/*`, `src/math_agent/proof/*` | medium | generator-verifier/consensus trap 风险应对灵感。 |
| [R8] | Verifier-guided selection | `src/math_agent/verification/*`, `src/math_agent/control/weighted_voting_hook.py` | medium | weighted voting/test-time compute 思路工程化。 |

## 4. Implementation Evidence

- Code paths only map to existing repository files; no paper reproduction claim.
- Validation uses mock/preofficial flow (shadow eval, dry-run, demo evidence).

## 5. Limitations

- No claim of full reproduction for [R1]-[R8].
- No unrestricted self-modification or RL training loop.

## 6. Future Work

- Deeper verifier learning and adaptive routing remain future_work.

## 7. Reproducibility Notes

- Default mode is mock-safe.
- No `.env` content read in traceability checker.
- No `official_results.jsonl` generated.
