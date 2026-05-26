# Hard Mode Pipeline Hook

This is NOT official evaluation.
This hook does not change default pipeline behavior.
This hook does not enable real multi-candidate solving yet.
This hook does not call external APIs by itself.
This hook only exposes controlled runtime metadata for later verifier/voting integration.

## 1. Purpose
Provide a controlled runtime hook so hard-mode policy becomes visible and auditable in pipeline metadata.

## 2. Scope
P13 only adds runtime configuration/metadata hooks. It does not refactor solver flow.

## 3. Default Behavior
When `--hard-mode` is not provided, default pipeline behavior is unchanged.

## 4. Runtime Config
`HardModeRuntimeConfig` is built from `HardModePolicy` and includes runtime notes, trace allowance, proof guardian hook flag, and candidate budget preview.

## 5. Candidate Budget Preview
- off: effective 1
- light: effective 2
- standard: effective 3
- strict: policy budget is 5, but effective budget is capped to 3 in P13

P13 is a controlled runtime hook. It exposes candidate budget preview without enabling multi-candidate solving yet.

## 6. Trace Policy
`--no-trace` has priority. Even if strict policy requires trace, runtime keeps trace disabled and records `trace_required_by_policy_but_no_trace_flag_wins`.

## 7. Proof Guardian Hook
Only a hook flag: proof + standard/strict can set `proof_guardian=true` in runtime metadata. Solver behavior is unchanged.

## 8. Shadow Eval / Debugger Hooks
Only metadata visibility (`shadow_eval_required`, `debugger_required`) is exposed. No automatic execution is added.

## 9. CLI Examples
Default:

```bash
python -m math_agent.cli solve \
  --question "计算 2+3" \
  --enable-tools \
  --mode fast \
  --no-trace
```

Hard-mode runtime hook:

```bash
python -m math_agent.cli solve \
  --question "计算 2+3" \
  --enable-tools \
  --mode fast \
  --hard-mode \
  --hard-mode-level light
```

Strict preview:

```bash
python -m math_agent.cli solve \
  --question "证明偶数加偶数仍为偶数" \
  --enable-tools \
  --mode fast \
  --hard-mode \
  --hard-mode-level strict \
  --no-trace
```

## 10. Limitations
No real multi-candidate generation, no weighted voting, no verifier-voting integration in P13.

## 11. Rollback Plan
Disable `--hard-mode` usage or revert `pipeline_hook` integration commit. Default path remains backward compatible.

## 12. Next Steps
P14 will connect verifier-voting and true candidate budget execution using these runtime interfaces.
