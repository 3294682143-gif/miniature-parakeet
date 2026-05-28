import json
import subprocess
import sys
from pathlib import Path

from math_agent.schemas import SolveResult


def test_cli_solve_outputs_json():
    cmd = [sys.executable, "-m", "math_agent.cli", "solve", "--question", "1+1=?"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout.strip())
    SolveResult.model_validate(data)


def test_cli_batch_processes_and_isolation(tmp_path: Path):
    in_file = tmp_path / "in.jsonl"
    in_file.write_text(
        '{"question_id":"ok1","question":"1+1=?"}\n'
        '{"question_id":"bad"}\n'
        '{"question_id":"ok2","question":"2+2=?"}\n',
        encoding="utf-8",
    )
    out_file = tmp_path / "results.jsonl"
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "batch",
        "--input",
        str(in_file),
        "--output",
        str(out_file),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    statuses = []
    for line in lines:
        parsed = json.loads(line)
        model = SolveResult.model_validate(parsed)
        statuses.append(model.status)
    assert statuses[0] in {"success", "partial"}
    assert statuses[1] == "fail"
    assert statuses[2] in {"success", "partial"}


def test_cli_solve_enable_tools_outputs_json():
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "solve",
        "--question",
        "计算 2+3",
        "--enable-tools",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout.strip())
    model = SolveResult.model_validate(data)
    assert model.final_answer.boxed != ""


def test_cli_batch_enable_tools_schema(tmp_path: Path):
    in_file = tmp_path / "in_tools.jsonl"
    in_file.write_text(
        '{"question_id":"q1","question":"计算 2+3"}\n'
        '{"question_id":"q2","question":"化简 sin(x)^2 + cos(x)^2"}\n',
        encoding="utf-8",
    )
    out_file = tmp_path / "results_tools.jsonl"
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "batch",
        "--input",
        str(in_file),
        "--output",
        str(out_file),
        "--enable-tools",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    for line in out_file.read_text(encoding="utf-8").strip().splitlines():
        SolveResult.model_validate(json.loads(line))


def test_cli_solve_no_trace(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "solve",
        "--question",
        "1+1=?",
        "--question-id",
        "qt",
        "--trace-dir",
        str(trace_dir),
        "--no-trace",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert not (trace_dir / "qt.json").exists()


def test_cli_batch_trace_generation(tmp_path: Path):
    in_file = tmp_path / "in_batch.jsonl"
    in_file.write_text(
        '{"question_id":"q1","question":"1+1=?"}\n{"question_id":"q2","question":"2+2=?"}\n',
        encoding="utf-8",
    )
    out_file = tmp_path / "results.jsonl"
    trace_dir = tmp_path / "traces"
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "batch",
        "--input",
        str(in_file),
        "--output",
        str(out_file),
        "--trace-dir",
        str(trace_dir),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert (trace_dir / "q1.json").exists()
    assert (trace_dir / "q2.json").exists()


def test_cli_batch_writes_budget_stats(tmp_path: Path):
    in_file = tmp_path / "in_stats.jsonl"
    in_file.write_text(
        '{"question_id":"q1","question":"Compute gcd(48, 18). Give the final answer only."}\n',
        encoding="utf-8",
    )
    out_file = tmp_path / "results.jsonl"
    trace_dir = tmp_path / "traces"
    stats_file = tmp_path / "stats.json"
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "batch",
        "--input",
        str(in_file),
        "--output",
        str(out_file),
        "--trace-dir",
        str(trace_dir),
        "--stats",
        str(stats_file),
        "--enable-tools",
        "--mode",
        "tool-first",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    stats = json.loads(stats_file.read_text(encoding="utf-8"))
    assert stats["processed_count"] == 1
    assert stats["total_tool_calls"] >= 1
    assert stats["trace_found_count"] == 1


def test_cli_batch_resume_and_retry_failed(tmp_path: Path):
    in_file = tmp_path / "in_resume.jsonl"
    in_file.write_text(
        '{"question_id":"done","question":"1+1=?"}\n'
        '{"question_id":"retry","question":"2+2=?"}\n'
        '{"question_id":"new","question":"3+3=?"}\n',
        encoding="utf-8",
    )
    base = {
        "domain": "Unknown",
        "problem_type": "unknown",
        "problem_parse": {"goal": "g", "givens": [], "symbols": []},
        "solution_plan": [],
        "visible_solution_steps": [],
        "tool_trace": [],
        "didactic_hint": "h",
        "error": None,
    }
    out_file = tmp_path / "resume_results.jsonl"
    out_file.write_text(
        json.dumps(
            {
                **base,
                "question_id": "done",
                "final_answer": {"type": "number", "value": "2", "boxed": "\\boxed{2}"},
                "verification": {"method": "none", "passed": True, "notes": "old"},
                "confidence": 0.8,
                "status": "success",
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            {
                **base,
                "question_id": "retry",
                "final_answer": {"type": "text", "value": "", "boxed": ""},
                "verification": {"method": "none", "passed": False, "notes": "old"},
                "confidence": 0.0,
                "status": "partial",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "batch",
        "--input",
        str(in_file),
        "--output",
        str(out_file),
        "--resume",
        "--retry-failed",
        "--enable-tools",
        "--mode",
        "tool-first",
        "--no-trace",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    rows = [
        SolveResult.model_validate(json.loads(line))
        for line in out_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [row.question_id for row in rows]
    assert ids.count("done") == 1
    assert ids.count("retry") == 1
    assert ids.count("new") == 1
    assert next(row for row in rows if row.question_id == "retry").status in {
        "success",
        "partial",
    }
