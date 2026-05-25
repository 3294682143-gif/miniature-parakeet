from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from math_agent.debugger.failure_attribution import (
    build_debugger_report,
    cluster_failures,
    filter_failures,
    load_shadow_results,
    select_representatives,
)
from math_agent.debugger.report import render_demo_case_list, render_failure_debug_report
from math_agent.debugger.root_cause import infer_root_cause, infer_severity


def _write_jsonl(path: Path) -> None:
    rows = [
        {"id": "1", "question": "q", "expected_answer": "5", "predicted_answer": "4", "domain": "arith", "difficulty": "easy", "answer_type": "number", "exact_match": False, "failure_category": "wrong_answer", "status": "ok", "json_valid": True, "final_answer_exists": True},
        {"id": "2", "question": "q2", "expected_answer": "6", "predicted_answer": "6", "domain": "algebra", "difficulty": "hard", "answer_type": "number", "exact_match": True, "failure_category": "missing_final", "status": "ok", "final_answer_exists": False},
        {"id": "3", "question": "q3", "expected_answer": "7", "predicted_answer": "7", "domain": "proof", "difficulty": "medium", "answer_type": "proof", "exact_match": True, "failure_category": "json_invalid", "status": "ok", "json_valid": False},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n{bad json}\n", encoding="utf-8")


def test_debugger_flow(tmp_path: Path) -> None:
    results = tmp_path / "shadow_results.jsonl"
    _write_jsonl(results)
    cases = load_shadow_results(results)
    assert len(cases) == 4
    assert any(c.failure_category == "malformed_json" for c in cases)

    fails = filter_failures(cases)
    cats = {c.failure_category for c in fails}
    assert "wrong_answer" in cats and "missing_final" in cats and "json_invalid" in cats

    assert infer_root_cause([c for c in fails if c.failure_category == "missing_final"][0]).owner == "formatter / final_answer"
    assert infer_severity(type("x", (), {"failure_category": "boxed_42_fallback"})()) == "P0"

    clusters = cluster_failures(fails)
    assert any(c.key == "wrong_answer" for c in clusters)
    assert any("arith" in c.domains for c in clusters)

    reps = select_representatives(fails, limit=2)
    assert len(reps) == 2

    report = build_debugger_report(cases)
    assert isinstance(report.p0_actions, list)
    md = render_failure_debug_report(report)
    assert "NOT official evaluation" in md
    demo = render_demo_case_list(report)
    assert "not official evaluation" in demo.lower()


def test_cli_and_outputs(tmp_path: Path) -> None:
    results = tmp_path / "shadow_results.jsonl"
    _write_jsonl(results)
    out = tmp_path / "out"

    help_run = subprocess.run([sys.executable, "scripts/debug_shadow_failures.py", "--help"], capture_output=True, text=True, check=False)
    assert help_run.returncode == 0

    env = os.environ.copy()
    env["SECRET_TOKEN"] = "tok_123"
    run = subprocess.run([
        sys.executable,
        "scripts/debug_shadow_failures.py",
        "--results",
        str(results),
        "--out-dir",
        str(out),
        "--fail-on-p0",
    ], capture_output=True, text=True, check=False, env=env)
    assert run.returncode != 0

    for name in ["failure_debug_report.md", "failure_clusters.json", "root_causes.json", "demo_cases.md"]:
        assert (out / name).is_file()
    assert not (out / "official_results.jsonl").exists()

    json.loads((out / "failure_clusters.json").read_text(encoding="utf-8"))
    json.loads((out / "root_causes.json").read_text(encoding="utf-8"))

    content = (out / "failure_debug_report.md").read_text(encoding="utf-8")
    assert "SECRET_TOKEN" not in content
    assert "API_KEY" not in content
