# Hard Mode Candidate Budget / Verifier Routing

This is NOT official evaluation.
This does not enable real multi-candidate solving yet.
This does not enable real weighted voting yet.
This does not change default pipeline behavior.
This does not call external APIs by itself.

## 1. Purpose
Provide a deterministic preview scaffold for candidate budget and verifier routing in hard-mode.

## 2. Scope
P14 only writes preview metadata/trace based on runtime config. It does not alter solve execution path.

## 3. CandidateBudgetPlan
- light: requested/effective budget = 2
- standard: requested/effective budget = 3
- strict: requested budget = 5, effective budget capped to 3 in P14

## 4. VerifierRoutingPlan
- basic -> `basic_verifier`
- strong -> `strong_verifier_preview`
- strict -> `strict_verifier_preview`

## 5. Preview vs Real Execution
No real multi-candidate generation, no real weighted voting, no verifier-path switch.

## 6. CLI Examples
```bash
python -m math_agent.cli solve \
  --question "计算 2+3" \
  --enable-tools \
  --mode fast \
  --hard-mode \
  --hard-mode-level light

python -m math_agent.cli solve \
  --question "证明偶数加偶数仍为偶数" \
  --enable-tools \
  --mode fast \
  --hard-mode \
  --hard-mode-level strict \
  --no-trace
```

## 7. Trace Metadata
When hard-mode is enabled, metadata includes:
- `candidate_budget_plan`
- `verifier_routing_plan`
- `hard_mode_execution_effect=candidate_and_verifier_routing_preview`

## 8. Safety Boundaries
No `.env` read, no external API call by this scaffold, no official results generation.

## 9. Limitations
Strict budget cap is preview-only (requested 5, effective 3). Real weighted voting is deferred.

## 10. Next Steps
P15 will wire real weighted voting and verifier scoring behind controlled gates.
