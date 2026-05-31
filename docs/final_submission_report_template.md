# Final Submission Evidence Report Template

Use this template after the final local run. Do not paste API keys, raw trace payloads, or private official data.

The same evidence shape can be generated automatically with:

```bash
python scripts/check_gate_environment.py --out-dir outputs/gate_environment
python scripts/build_final_submission_report.py --out-dir outputs/final_submission_report
```

## 1. Feature Scope

| Area | Evidence | Status | Notes |
|---|---|---|---|
| Official-style synthetic suite | `data/official_style_18domain_112*.jsonl` | TBD | Synthetic only, not official hidden data. |
| Real API sample gate | `outputs/real_api_sample_gate/real_api_sample_gate_summary.json` | TBD | Record pass/fail/partial, latency, model_calls, tool_calls. |
| Failure replay loop | `outputs/real_api_sample_gate/failure_replay_report.md` | TBD | Classify failures by prompt, formatter, verifier, proof, tool routing, or API. |
| Proof review pack | `outputs/real_api_sample_gate/proof_manual_review_pack.md` | TBD | Summarize risk_flags and review_feedback. |
| lagent alignment | `docs/lagent_alignment.md` | TBD | Evidence layer only; stable runtime unchanged. |
| Safety gate | `python scripts/check_project_safety.py` | TBD | Raw outputs/traces must be cleaned before packaging. |

## 2. Gate Results

| Command | Result | Key Evidence |
|---|---|---|
| `python -m pytest -q` | TBD | e.g. `433 passed` |
| `python scripts/run_regression_gate.py` | TBD | ruff/black/isort/mypy/pyright + pytest |
| `python scripts/run_pre_submit_gate.py --dry-run-limit 3` | TBD | pytest + mock official-style dry-run + cleanup + safety |
| `python scripts/full_system_audit.py --out-dir outputs/full_system_audit --fail-on-risk` | TBD | fail-on-risk should be PASS before final evidence |
| `python scripts/check_project_safety.py` | TBD | PASS |

## 3. Real API Evidence

| Metric | Value |
|---|---:|
| sample_count | TBD |
| domain_count | TBD |
| preflight | TBD |
| pass_count | TBD |
| partial_count | TBD |
| fail_count | TBD |
| pass_rate | TBD |
| total_model_calls | TBD |
| total_tool_calls | TBD |
| tool_solved_count | TBD |
| model_solved_count | TBD |
| model_verified_count | TBD |
| average_latency_seconds | TBD |

## 4. 18-Domain Dashboard Summary

| Domain | Mock Pass | Real Pass | Proof Risk | Tool/Model Split | Failure Replay |
|---|---:|---:|---:|---|---|
| PDE | TBD | TBD | TBD | TBD | TBD |
| ComplexAnalysis | TBD | TBD | TBD | TBD | TBD |
| Topology | TBD | TBD | TBD | TBD | TBD |
| OperationsResearch | TBD | TBD | TBD | TBD | TBD |
| Algebra | TBD | TBD | TBD | TBD | TBD |
| Analysis | TBD | TBD | TBD | TBD | TBD |
| Probability | TBD | TBD | TBD | TBD | TBD |
| Geometry | TBD | TBD | TBD | TBD | TBD |
| NumberTheory | TBD | TBD | TBD | TBD | TBD |

## 5. Failure Closure

| Question ID | Review Bucket | Suggested Fix | Changed Surface | Rerun Result |
|---|---|---|---|---|
| TBD | prompt_reasoning_or_tool_routing | prompt/router | TBD | TBD |
| TBD | final_answer_format_repair | formatter | TBD | TBD |
| TBD | verifier_misjudge_or_threshold | verifier | TBD | TBD |
| TBD | proof_too_shallow_or_invalid | proof prompt/formatter | TBD | TBD |
| TBD | api_retry_or_runtime_failure | rerun only | TBD | TBD |

## 6. lagent Alignment Evidence

| Project Stage | lagent Concept | Evidence |
|---|---|---|
| Planner | Agent message | `lagent_alignment_evidence_table()` |
| Solver | Agent message | `lagent_alignment_evidence_table()` |
| Verifier | Agent message / critic | `lagent_alignment_evidence_table()` |
| Tool Observation | Action observation | `lagent_alignment_evidence_table()` |

## 7. Final Reviewer Evidence

Attach or reference local-only screenshots / summaries here before defense packaging. Do not paste secrets or raw traces.

| Evidence Item | Local Source | Status | Notes |
|---|---|---|---|
| Real API sample summary | `outputs/real_api_sample_gate/real_api_sample_gate_summary.json` | TBD | Include pass/fail/partial, latency, model_calls, tool_calls. |
| Failure closure table | `outputs/real_api_sample_gate/failure_replay_report.md` | TBD | Show review bucket and rerun outcome for each fixed failure. |
| lagent alignment table | generated final report / `docs/lagent_alignment.md` | TBD | Show Planner/Solver/Verifier/Tool Observation mapping. |
| Safety gate screenshot | terminal / CI page | TBD | Must show cleanup + `check_project_safety.py` PASS. |
| Quality gate screenshot | terminal / CI page | TBD | Must show `run_regression_gate.py` PASS after dev tools are installed. |

## 8. Submission Boundary

- No `.env`, API key, Authorization header, or Bearer token committed.
- No `outputs/`, `trace/`, `traces/`, `run_records/`, `official_results.jsonl`, `submission.zip`, cache, or build artifact committed.
- Real API raw traces remain local and are cleaned before packaging.
- Official-style datasets are labeled synthetic; no official hidden data claim is made.
