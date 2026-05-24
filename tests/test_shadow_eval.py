from __future__ import annotations

import json
import subprocess
import sys

from math_agent.evaluation.error_taxonomy import classify_failure
from math_agent.evaluation.metrics import (
    compute_dirty_boxed_rate,
    compute_missing_final_rate,
    normalize_answer,
)
from math_agent.evaluation.shadow_eval import (
    ShadowEvalCase,
    ShadowEvalResult,
    load_cases,
    render_markdown_report,
    run_shadow_eval,
    summarize_results,
    write_jsonl,
    write_summary,
)


def test_load_cases_jsonl_json_and_default(tmp_path):
    jsonl = tmp_path / "c.jsonl"
    jsonl.write_text('{"id":"1","question":"q"}\n', encoding="utf-8")
    assert load_cases(jsonl)[0].id == "1"

    js = tmp_path / "c.json"
    js.write_text('[{"id":"2","question":"q2"}]', encoding="utf-8")
    assert load_cases(js)[0].id == "2"
    assert len(load_cases(None)) == 5


def test_normalize_and_exact_match_basics():
    assert normalize_answer(" 5 ") == "5"
    assert normalize_answer("\\boxed{5}") == "5"
    assert normalize_answer("5.0") == "5"


def test_rates_and_failure_taxonomy():
    rows = [
        {"json_valid": True, "final_answer_exists": False, "dirty_boxed": False, "boxed_42_fallback": True},
        {"json_valid": False, "final_answer_exists": True, "dirty_boxed": True, "boxed_42_fallback": False},
    ]
    assert compute_missing_final_rate(rows) == 0.5
    assert compute_dirty_boxed_rate(rows) == 0.5
    assert classify_failure({"json_valid": False}) == "json_invalid"


def test_summary_write_and_render(tmp_path):
    results = [
        ShadowEvalResult("1", "q", "5", "5", "a", "easy", "number", exact_match=True),
        ShadowEvalResult("2", "q2", "6", "7", "b", "hard", "number", exact_match=False),
    ]
    s = summarize_results(results)
    assert s.json_valid_rate >= 0.0
    assert "a" in s.domain_breakdown
    assert "easy" in s.difficulty_breakdown

    write_jsonl(results, tmp_path / "shadow_results.jsonl")
    write_summary(s, tmp_path / "shadow_summary.json")
    md = render_markdown_report(s, results)
    assert "NOT official evaluation" in md


def test_exception_not_break_batch():
    def runner(case, _):
        if case.id == "bad":
            raise RuntimeError("boom")
        return {"predicted_answer": "ok"}

    cases = [ShadowEvalCase("bad", "q"), ShadowEvalCase("good", "q")]
    results = run_shadow_eval(cases, runner=runner, options={})
    assert len(results) == 2
    assert any(r.failure_category == "exception" for r in results)


def test_cli_and_build_report(tmp_path):
    out = tmp_path / "out"
    cmd = [sys.executable, "scripts/shadow_eval.py", "--mock", "--limit", "5", "--out", str(out)]
    cp = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert cp.returncode == 0
    assert "--real" not in " ".join(cmd)
    assert not (out / "official_results.jsonl").exists()

    cp_help = subprocess.run([sys.executable, "scripts/shadow_eval.py", "--help"], check=False, capture_output=True, text=True)
    assert cp_help.returncode == 0

    cp2 = subprocess.run(
        [sys.executable, "scripts/build_eval_report.py", "--results", str(out / "shadow_results.jsonl"), "--out-dir", str(out)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert cp2.returncode == 0
    assert "official accuracy" not in (out / "shadow_report.md").read_text(encoding="utf-8").lower().replace("do not claim official accuracy", "")

    cp_help2 = subprocess.run([sys.executable, "scripts/build_eval_report.py", "--help"], check=False, capture_output=True, text=True)
    assert cp_help2.returncode == 0

    assert ".env" not in cp.stdout + cp.stderr + cp2.stdout + cp2.stderr
