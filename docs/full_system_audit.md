# Full System Audit (P18.5 / P18.5.1)

This is NOT official evaluation.
Do not claim official accuracy from this audit.
Do not rename dry-run outputs to official_results.jsonl.

## Scope

- Exhaustive function inventory across categories A-X.
- Line count summary (total + by module).
- Quality gate execution summary.
- Mock-safe functional smoke summary.
- Architecture/full-chain overview.

## Outputs

- full_system_audit_report.md
- full_system_audit_summary.json
- line_count_report.json
- line_count_report.md
- quality_gate_results.json
- functional_smoke_results.json
- function_inventory.md
- function_inventory.json
- function_inventory_by_category.md
- architecture_overview.md
- readme_update_notes.md

## Regenerate

`python scripts/full_system_audit.py --out-dir outputs/full_system_audit --skip-slow`

Use the stricter gate before submission:

`python scripts/full_system_audit.py --out-dir outputs/full_system_audit --fail-on-risk`


## 本地完整验收顺序（提交前门禁）

提交前建议按以下顺序执行：

```bash
ruff check .
black --check src scripts demo tests
isort --check-only --diff src scripts demo tests
mypy src --show-error-codes
pyright
python -m compileall src scripts demo tests
python -m pytest -q
python -m math_agent.cli solve --question "计算 2+3" --enable-tools --mode fast --no-trace --fail-on-non-success
python scripts/clean_transient_artifacts.py
python scripts/check_project_safety.py
git status --short
```

注意：`compileall` / `pytest` / CLI smoke 会生成缓存与运行产物，因此 `check_project_safety.py` 前必须先执行 cleanup。
