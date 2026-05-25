# Agent Debugger

This debugger is for mock / preofficial / shadow evaluation analysis only.
It does not represent official accuracy.
It does not call external APIs.

## 1. Purpose
Deterministic failure attribution for Shadow Eval outputs.

## 2. Inputs
`shadow_results.jsonl` (optional `shadow_summary.json`).

## 3. Outputs
- `failure_debug_report.md`
- `failure_clusters.json`
- `root_causes.json`
- `demo_cases.md`

## 4. Failure Taxonomy
Uses `failure_category` plus deterministic fallback checks.

## 5. Root Cause Mapping
Maps category -> root cause / owner / action.

## 6. Severity Levels
P0/P1/P2/none using deterministic rules.

## 7. How to Run
```bash
python scripts/debug_shadow_failures.py \
  --results outputs/shadow_eval_gate/shadow_results.jsonl \
  --out-dir outputs/debug_shadow
```

## 8. How to Use in Demo
Use `demo_cases.md` for representative non-official examples.

## 9. How to Use Before Official Submission
Use as preflight diagnostics only; fix issues before official run.

## 10. Limitations
No official scoring, no external APIs, no trace fabrication.
