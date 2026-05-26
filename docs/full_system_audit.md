# Full System Audit (P18.5)

This is NOT official evaluation.
Do not claim official accuracy from this audit.
Do not rename dry-run outputs to official_results.jsonl.

## Purpose

`python scripts/full_system_audit.py --out-dir outputs/full_system_audit`

- Generates acceptance-gate style reports.
- Uses `git ls-files + Python` for line counting.
- Runs quality gates and mock-safe functional smokes.
- Never reads `.env` contents and never generates `official_results.jsonl`.

## Outputs

- `full_system_audit_report.md`
- `full_system_audit_summary.json`
- `line_count_report.json`
- `line_count_report.md`
- `quality_gate_results.json`
- `functional_smoke_results.json`
- `function_inventory.md`
- `architecture_overview.md`
- `readme_update_notes.md`
