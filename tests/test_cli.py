import json
import subprocess
import sys
from pathlib import Path

from math_agent.schemas import SolveResult


def test_cli_solve_outputs_json(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "solve",
        "--question",
        "1+1=?",
        "--question-id",
        "q_cli",
        "--trace-dir",
        str(trace_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout.strip())
    SolveResult.model_validate(data)
    assert (trace_dir / "q_cli.json").exists()


def test_cli_batch_processes_and_isolation(tmp_path: Path):
    in_file = tmp_path / "in.jsonl"
    in_file.write_text(
        '{"question_id":"ok1","question":"1+1=?"}\n'
        '{"question_id":"bad"}\n'
        '{"question_id":"ok2","question":"2+2=?"}\n',
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
    assert (trace_dir / "ok1.json").exists()
    assert (trace_dir / "ok2.json").exists()


def test_cli_no_trace_option(tmp_path: Path):
    trace_dir = tmp_path / "traces"
    cmd = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "solve",
        "--question",
        "1+1=?",
        "--question-id",
        "q_none",
        "--trace-dir",
        str(trace_dir),
        "--no-trace",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert not (trace_dir / "q_none.json").exists()
