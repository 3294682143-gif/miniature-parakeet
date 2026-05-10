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
    cmd = [sys.executable, "-m", "math_agent.cli", "batch", "--input", str(in_file), "--output", str(out_file)]
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
    cmd = [sys.executable, "-m", "math_agent.cli", "solve", "--question", "计算 2+3", "--enable-tools"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout.strip())
    model = SolveResult.model_validate(data)
    assert model.final_answer.boxed != ""


def test_cli_batch_enable_tools_schema(tmp_path: Path):
    in_file = tmp_path / "in_tools.jsonl"
    in_file.write_text(
        "{\"question_id\":\"q1\",\"question\":\"计算 2+3\"}\n"
        "{\"question_id\":\"q2\",\"question\":\"化简 sin(x)^2 + cos(x)^2\"}\n",
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
    cmd = [sys.executable, "-m", "math_agent.cli", "solve", "--question", "1+1=?", "--question-id", "qt", "--trace-dir", str(trace_dir), "--no-trace"]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert not (trace_dir / "qt.json").exists()


def test_cli_batch_trace_generation(tmp_path: Path):
    in_file = tmp_path / "in_batch.jsonl"
    in_file.write_text('{"question_id":"q1","question":"1+1=?"}\n{"question_id":"q2","question":"2+2=?"}\n', encoding="utf-8")
    out_file = tmp_path / "results.jsonl"
    trace_dir = tmp_path / "traces"
    cmd = [sys.executable, "-m", "math_agent.cli", "batch", "--input", str(in_file), "--output", str(out_file), "--trace-dir", str(trace_dir)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert (trace_dir / "q1.json").exists()
    assert (trace_dir / "q2.json").exists()
