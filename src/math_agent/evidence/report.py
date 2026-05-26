from __future__ import annotations

from .demo_pack import OFFICIAL_WARNING, DemoEvidencePack


def render_demo_index(pack: DemoEvidencePack) -> str:
    src_rows = "\n".join(
        f"- {s.name}: exists={s.exists} path={s.path}" for s in pack.sources
    )
    case_rows = (
        "\n".join(f"- {c.case_id}: {c.title} ({c.demo_angle})" for c in pack.demo_cases)
        or "- none"
    )
    return f"""# Demo Evidence Pack

{OFFICIAL_WARNING}

## 1. Overview
- run_id: {pack.run_id}
- created_at: {pack.created_at}

## 2. Source Availability
{src_rows}

## 3. Key Metrics
- available_sources: {pack.summary.get('available_sources')}
- total_sources: {pack.summary.get('total_sources')}

## 4. Representative Demo Cases
{case_rows}

## 5. Shadow Eval Evidence
- Refer to source: shadow_eval
## 6. Debugger Evidence
- Refer to source: agent_debugger
## 7. Hard-mode Ablation Evidence
- Refer to source: hard_mode_ablation
## 8. Proof Guardian Evidence
- Refer to source: proof_guardian
## 9. Official-like Dry-run Evidence
- Refer to source: official_dry_run
## 10. Safety Boundaries
- No official_results.jsonl is produced.
- No .env content is read.
## 11. Recommended Demo Flow
- Follow demo_script.md
## 12. Limitations
- Missing source files are reported as warnings.
## 13. Next Steps
- Fill missing evidence sources and rerun.
"""


def render_demo_script(pack: DemoEvidencePack) -> str:
    return """# Demo Script

This is NOT official evaluation.

1. 开场：Stable Core + Externalized Harness。
2. 展示 Shadow Eval（若缺失则说明 source missing）。
3. 展示 Agent Debugger（若缺失则说明 source missing）。
4. 展示 Hard-mode Ablation（若缺失则说明 source missing）。
5. 展示 Proof Guardian（若缺失则说明 source missing）。
6. 展示 Official-like Dry Run（若缺失则说明 source missing）。
7. 安全边界：不读 .env，不生成 official_results.jsonl。
8. 局限性：此包不是官方评测，不可主张官方准确率。
9. 下一步计划：补全缺失来源并复跑。
"""


def render_architecture_summary(pack: DemoEvidencePack) -> str:
    _ = pack
    return """# Architecture Summary

```mermaid
flowchart TD
CLI[CLI / Pipeline] --> SE[Shadow Eval]
CLI --> DBG[Debugger]
CLI --> HM[HardModePolicy]
HM --> CB[CandidateBudget / VerifierRouting]
CB --> WV[Weighted Voting Preview]
WV --> PG[Proof Guardian]
PG --> DR[Official Dry-run]
SE --> DP[Demo Pack]
DBG --> DP
DR --> DP
DP --> SG[Safety Gate]
```
"""


def render_risk_control_summary(pack: DemoEvidencePack) -> str:
    return "# Risk Control Summary\n\n- " + pack.official_warning + "\n"


def render_hard_mode_summary(pack: DemoEvidencePack) -> str:
    return "# Hard-mode Summary\n\n- source: hard_mode_ablation\n"


def render_proof_guardian_summary(pack: DemoEvidencePack) -> str:
    return "# Proof Guardian Summary\n\n- source: proof_guardian\n"


def render_dry_run_summary(pack: DemoEvidencePack) -> str:
    return "# Dry-run Summary\n\n- source: official_dry_run\n"


def render_readme(pack: DemoEvidencePack) -> str:
    return f"# README Demo Pack\n\n{pack.official_warning}\n"
