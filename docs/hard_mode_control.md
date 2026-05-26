# Hard Mode Controlled Integration

## 1. Purpose
Provide an opt-in hard-mode policy layer for controlled strategy tuning without changing the stable default pipeline.

## 2. Why Controlled Integration
P10 introduces a small, reversible integration point so future hard-problem features can plug in safely.

## 3. Policy Levels
Supported levels are `off`, `light`, `standard`, and `strict`.

- `off`: baseline behavior profile.
- `light`: small candidate/verification increase.
- `standard`: stronger verification and trace requirement.
- `strict`: strongest policy with static hook flags for shadow eval/debugger follow-up.

## 4. Candidate Budget
- off: 1
- light: 2
- standard: 3
- strict: 5

## 5. Verifier Level
- off/light: `basic`
- standard: `strong`
- strict: `strict`

## 6. Proof Guardian Flag
`proof_guardian` is a policy flag for proof-oriented strengthening. In this phase it is configuration-only.

## 7. Trace Requirement
`require_trace` indicates policy intent only. Hard mode is opt-in and does not force any default CLI behavior change.

## 8. Shadow Eval / Debugger Hooks
`shadow_eval_required` and `debugger_required` are static hook flags for later phases. This phase does not run shadow eval/debugger automatically.

## 9. CLI Usage
Current phase focuses on policy layer controlled integration. CLI hard-mode switches are planned for follow-up integration.

Baseline smoke command (unchanged):

```bash
python -m math_agent.cli solve --question "计算 2+3" --enable-tools --mode fast --no-trace
```

Planned hard-mode command for later wiring:

```bash
python -m math_agent.cli solve --question "证明偶数加偶数仍为偶数" --enable-tools --mode fast --hard-mode --hard-mode-level standard
```

## 10. Safety Boundaries
- Hard Mode is opt-in.
- Default pipeline behavior is unchanged.
- This is not official evaluation.
- This mode does not call external APIs by itself.
- This mode does not claim official accuracy.

## 11. Rollback Plan
Rollback is simple: remove the control module usage and keep `enabled=False` policy construction disabled by default.

## 12. Next Steps
P11 can attach actual verifier, weighted voting, proof guardian, and debugger evidence flow based on these policy hooks.
