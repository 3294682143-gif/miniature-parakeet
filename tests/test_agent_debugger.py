# safety: allow-secret-fixtures
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
    write_debugger_outputs,
)
from math_agent.debugger.report import (
    render_demo_case_list,
    render_failure_debug_report,
)
from math_agent.debugger.root_cause import infer_root_cause, infer_severity


def _write_jsonl(path: Path) -> None:
    rows = [
        {
            "id": "1",
            "question": "q",
            "expected_answer": "5",
            "predicted_answer": "4",
            "domain": "arith",
            "difficulty": "easy",
            "answer_type": "number",
            "exact_match": False,
            "failure_category": "wrong_answer",
            "status": "ok",
            "json_valid": True,
            "final_answer_exists": True,
        },
        {
            "id": "2",
            "question": "q2",
            "expected_answer": "6",
            "predicted_answer": "6",
            "domain": "algebra",
            "difficulty": "hard",
            "answer_type": "number",
            "exact_match": True,
            "failure_category": "missing_final",
            "status": "ok",
            "final_answer_exists": False,
        },
        {
            "id": "3",
            "question": "q3",
            "expected_answer": "7",
            "predicted_answer": "7",
            "domain": "proof",
            "difficulty": "medium",
            "answer_type": "proof",
            "exact_match": True,
            "failure_category": "json_invalid",
            "status": "ok",
            "json_valid": False,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n{bad json}\n",
        encoding="utf-8",
    )


def test_debugger_flow(tmp_path: Path) -> None:
    results = tmp_path / "shadow_results.jsonl"
    _write_jsonl(results)
    cases = load_shadow_results(results)
    assert len(cases) == 4
    assert any(c.failure_category == "malformed_json" for c in cases)

    fails = filter_failures(cases)
    cats = {c.failure_category for c in fails}
    assert "wrong_answer" in cats and "missing_final" in cats and "json_invalid" in cats

    missing_final = [c for c in fails if c.failure_category == "missing_final"][0]
    assert infer_root_cause(missing_final).owner == "formatter / final_answer"
    fallback_case = type("x", (), {"failure_category": "boxed_42_fallback"})()
    assert infer_severity(fallback_case) == "P0"

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


def test_debugger_treats_duplicate_json_keys_as_malformed(tmp_path: Path) -> None:
    results = tmp_path / "shadow_results.jsonl"
    results.write_text(
        '{"id":"safe","id":"shadowed","question":"q"}\n', encoding="utf-8"
    )

    cases = load_shadow_results(results)

    assert len(cases) == 1
    assert cases[0].failure_category == "malformed_json"


def test_cli_and_outputs(tmp_path: Path) -> None:
    results = tmp_path / "shadow_results.jsonl"
    _write_jsonl(results)
    out = tmp_path / "out"

    help_run = subprocess.run(
        [sys.executable, "scripts/debug_shadow_failures.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_run.returncode == 0

    env = os.environ.copy()
    env["SECRET_TOKEN"] = "tok_123"
    run = subprocess.run(
        [
            sys.executable,
            "scripts/debug_shadow_failures.py",
            "--results",
            str(results),
            "--out-dir",
            str(out),
            "--fail-on-p0",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert run.returncode != 0

    for name in [
        "failure_debug_report.md",
        "failure_clusters.json",
        "root_causes.json",
        "demo_cases.md",
    ]:
        assert (out / name).is_file()
    assert not (out / "official_results.jsonl").exists()

    json.loads((out / "failure_clusters.json").read_text(encoding="utf-8"))
    json.loads((out / "root_causes.json").read_text(encoding="utf-8"))

    content = (out / "failure_debug_report.md").read_text(encoding="utf-8")
    assert "SECRET_TOKEN" not in content
    assert "API_KEY" not in content


def test_debugger_reclassifies_raw_failure_signals() -> None:
    from math_agent.debugger.failure_attribution import FailureCase

    cases = [
        FailureCase(
            id="json",
            question="q",
            expected_answer="5",
            predicted_answer="5",
            domain="a",
            difficulty="easy",
            answer_type="number",
            failure_category="ok",
            exact_match=True,
            status="ok",
            error_message="",
            raw={"json_valid": False, "failure_category": "ok"},
        ),
        FailureCase(
            id="partial",
            question="q",
            expected_answer=None,
            predicted_answer="",
            domain="a",
            difficulty="easy",
            answer_type="number",
            failure_category="status_partial",
            exact_match=False,
            status="partial",
            error_message="",
            raw={"status": "partial", "failure_category": "status_partial"},
        ),
    ]

    report = build_debugger_report(cases)

    assert report.failed_count == 2
    assert any("json_invalid" in action for action in report.p0_actions)
    assert "status_partial" in report.failure_category_counts


def test_malformed_shadow_line_secret_is_not_persisted(tmp_path: Path) -> None:
    secret = "sk-DEBUGGER_SECRET_VALUE_123456"
    results = tmp_path / "shadow_results.jsonl"
    output = tmp_path / "out"
    results.write_text("{bad " + secret + "\n", encoding="utf-8")

    report = build_debugger_report(load_shadow_results(results))
    from math_agent.debugger.failure_attribution import write_debugger_outputs

    write_debugger_outputs(report, output)
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in output.iterdir() if path.is_file()
    )

    assert secret not in rendered
    assert report.representative_failures[0].failure_category == "malformed_json"
    assert infer_severity(report.representative_failures[0]) == "P0"


def test_debugger_rejects_false_like_exact_match_value(tmp_path: Path) -> None:
    results = tmp_path / "shadow_results.jsonl"
    results.write_text(
        json.dumps(
            {
                "id": "bad-exact",
                "question": "1+1?",
                "expected_answer": "2",
                "predicted_answer": "3",
                "exact_match": "false",
                "status": "success",
                "json_valid": True,
                "final_answer_exists": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_debugger_report(load_shadow_results(results))

    assert report.failed_count == 1
    assert report.representative_failures[0].exact_match is False
    assert report.representative_failures[0].failure_category == "wrong_answer"


def test_debugger_sink_redacts_manual_report_and_replaces_hardlink(
    tmp_path: Path,
) -> None:
    results = tmp_path / "shadow_results.jsonl"
    _write_jsonl(results)
    report = build_debugger_report(load_shadow_results(results))
    secret = "sk-MOCK_MANUAL_DEBUGGER_SECRET_123456"
    report.p1_actions = [secret]
    report.representative_failures[0].raw["api_key"] = "short-secret"

    output = tmp_path / "out"
    output.mkdir()
    victim = tmp_path / "victim.md"
    victim.write_text("preserve-me", encoding="utf-8")
    os.link(victim, output / "failure_debug_report.md")

    write_debugger_outputs(report, output)
    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in output.iterdir() if path.is_file()
    )

    assert victim.read_text(encoding="utf-8") == "preserve-me"
    assert secret not in rendered
    assert "short-secret" not in rendered
    assert "[REDACTED]" in rendered
