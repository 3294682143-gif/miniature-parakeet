# Hard Mode Ablation

This is not official evaluation.
This does not call external APIs.
This does not change default pipeline behavior.
This is an evidence tool for hard-mode policy design.

## 1. Purpose
Build reproducible mock/shadow evidence for off/light/standard/strict hard-mode policy levels.

## 2. Inputs
- Built-in shadow mock cases, or `--input` json/jsonl cases.

## 3. Outputs
- `hard_mode_ablation_summary.json`
- `comparison.json`
- `hard_mode_ablation_report.md`
- Per-level shadow/debugger outputs under `levels/<level>/`

## 4. Policy Levels
off, light, standard, strict (from `HardModePolicy`).

## 5. How Ablation Works
For each level: build policy -> run shadow eval (mock) -> summarize -> optional debugger attribution.

## 6. How Debugger Is Used
When `--include-debugger` is enabled, failure attribution reports are generated per level.

## 7. How to Read the Report
Treat it as mock/shadow ablation evidence only; not official accuracy.

## 8. Recommended Workflow
1. Run ablation.
2. Inspect comparison and per-level actions.
3. Plan controlled next experiments (not default-on).

## 9. Limitations
- No official scoring.
- Hard-mode is policy layer only.

## 10. Next Steps
Use findings to prioritize formatter/proof/verifier follow-ups.

```bash
python scripts/run_hard_mode_ablation.py \
  --limit 5 \
  --include-debugger \
  --out-dir outputs/hard_mode_ablation_test
```
