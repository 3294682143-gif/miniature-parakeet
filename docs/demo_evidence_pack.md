# Demo Evidence Pack

This is NOT official evaluation.
This does not claim official accuracy.
This does not call external APIs.
This does not generate official_results.jsonl.
This only aggregates mock / shadow / dry-run evidence.

## 1. Purpose
聚合展示证据用于答辩/演示/README。

## 2. Inputs
- shadow eval
- debugger
- hard-mode ablation
- proof guardian
- official-like dry-run
- project health

## 3. Outputs
- demo_index.md
- demo_script.md
- architecture_summary.md
- evidence_summary.json
- evidence_sources.json
- demo_cases.json
- risk_control_summary.md
- hard_mode_summary.md
- proof_guardian_summary.md
- dry_run_summary.md
- README_DEMO_PACK.md

## 4. How to Generate
```bash
python scripts/generate_demo_pack.py \
  --shadow-dir outputs/shadow_eval_test \
  --debugger-dir outputs/debug_shadow \
  --ablation-dir outputs/hard_mode_ablation_test \
  --proof-dir outputs/proof_guardian_demo_test \
  --dry-run-dir outputs/official_dry_run_test \
  --out-dir outputs/demo_pack_test
```

## 5. How to Use in Defense
按 demo_script.md 逐段演示，并明确 NOT official evaluation。

## 6. Source Availability
缺失 source 不崩溃，只记录 warning。

## 7. Representative Demo Cases
由 build_demo_cases 生成，默认最多 12。

## 8. Safety Boundaries
不读取 .env；不真实调用 API；不生成 official_results.jsonl。

## 9. Limitations
只汇总已有证据，不产生官方成绩。

## 10. Next Steps
可进一步增强字段映射与案例筛选。
