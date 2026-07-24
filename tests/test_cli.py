# safety: allow-secret-fixtures
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import math_agent.cli as cli_module
from math_agent.pipeline import execution_fingerprint_for_question
from math_agent.schemas import MathQuestion, SolveResult


def _result_payload(
    question_id: str,
    value: str = "2",
    *,
    status: str = "success",
    passed: bool = True,
    steps: list[str] | None = None,
    question: str = "1+1",
    mode: str = "full",
    enable_tools: bool = False,
    save_trace: bool = False,
    trace_dir: str = "outputs/traces",
) -> dict:
    math_question = MathQuestion(question_id=question_id, question=question)
    return {
        "question_id": question_id,
        "domain": "unknown",
        "problem_type": "unknown",
        "problem_parse": {"goal": "g", "givens": [], "symbols": []},
        "solution_plan": [],
        "visible_solution_steps": steps or [],
        "tool_trace": [],
        "final_answer": {"type": "text", "value": value, "boxed": value},
        "verification": {"method": "none", "passed": passed, "notes": "old"},
        "didactic_hint": "h",
        "confidence": 0.8 if passed else 0.0,
        "status": status,
        "error": None,
        "input_fingerprint": sha256(question.strip().encode("utf-8")).hexdigest(),
        "execution_fingerprint": execution_fingerprint_for_question(
            math_question,
            mock=True,
            enable_tools=enable_tools,
            save_trace=save_trace,
            trace_dir=trace_dir,
            run_mode=mode,
        ),
    }


def test_cli_solve_outputs_json():
    cmd = [sys.executable, "-m", "math_agent.cli", "solve", "--question", "1+1=?"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout.strip())
    SolveResult.model_validate(data)


def test_missing_trace_budget_keeps_complete_zero_schema(tmp_path: Path) -> None:
    budget = cli_module._read_trace_budget(tmp_path, "missing")

    assert budget == {
        "model_calls": 0,
        "tool_calls": 0,
        "trace_found": 0,
        "file_bytes": 0,
    }


def test_cli_second_batch_resume_uses_verified_bytes_not_redacted_trace_path(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / sha256(str(tmp_path).encode("utf-8")).hexdigest()
    workspace.mkdir()
    (workspace / "configs").mkdir()
    (workspace / "configs" / "prompts.yaml").write_bytes(
        (Path(__file__).resolve().parents[1] / "configs" / "prompts.yaml").read_bytes()
    )
    (workspace / "input.jsonl").write_text(
        '{"question_id":"Q1","question":"Compute gcd(48, 18). Give the final answer only."}\n',
        encoding="utf-8",
    )
    base_command = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "batch",
        "--input",
        "input.jsonl",
        "--output",
        "results.jsonl",
        "--trace-dir",
        "traces",
        "--enable-tools",
        "--mode",
        "tool-first",
        "--fail-on-non-success",
    ]

    initial = subprocess.run(
        [*base_command, "--stats", "initial-stats.json"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    expected_trace = workspace / "traces" / f"~trace-{sha256(b'Q1').hexdigest()}.json"
    assert initial.returncode == 0, initial.stderr
    assert expected_trace.is_file()
    original_trace = expected_trace.read_bytes()

    resumed = subprocess.run(
        [*base_command, "--resume", "--stats", "resumed-stats.json"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resumed.returncode == 0, resumed.stderr
    stats = json.loads((workspace / "resumed-stats.json").read_text(encoding="utf-8"))
    assert stats["processed_count"] == 0
    assert stats["skipped_count"] == 1
    assert expected_trace.read_bytes() == original_trace


def test_cli_fail_on_non_success_is_opt_in_and_machine_actionable() -> None:
    success = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "solve",
            "--question",
            "2+3",
            "--enable-tools",
            "--mode",
            "tool-first",
            "--no-trace",
            "--fail-on-non-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    failure = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "solve",
            "--question",
            "unsupported prose with no checkable answer",
            "--no-trace",
            "--fail-on-non-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert success.returncode == 0, success.stderr
    assert SolveResult.model_validate_json(success.stdout).status == "success"
    assert failure.returncode != 0
    assert SolveResult.model_validate_json(failure.stdout).status != "success"


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


def test_cli_batch_rejects_ambiguous_or_nonfinite_json_rows(tmp_path: Path) -> None:
    in_file = tmp_path / "ambiguous.jsonl"
    in_file.write_text(
        '{"question_id":"first","question":"1+1=?","question_id":"second"}\n'
        '{"question_id":"nonfinite","question":"1+1=?","score":NaN}\n',
        encoding="utf-8",
    )
    out_file = tmp_path / "results.jsonl"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(in_file),
            "--output",
            str(out_file),
            "--no-trace",
            "--fail-on-non-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    results = [
        SolveResult.model_validate_json(line)
        for line in out_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [result.status for result in results] == ["fail", "fail"]
    assert {result.question_id for result in results}.isdisjoint(
        {"first", "second", "nonfinite"}
    )


def test_cli_batch_rejects_path_aliases_without_data_loss(tmp_path: Path) -> None:
    source = tmp_path / "input.jsonl"
    original = b'{"question_id":"q1","question":"1+1=?"}\n'
    source.write_bytes(original)

    same_path = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(source),
            "--output",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert same_path.returncode != 0
    assert source.read_bytes() == original

    alias = tmp_path / "alias.jsonl"
    os.link(source, alias)
    hardlink = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(source),
            "--output",
            str(alias),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert hardlink.returncode != 0
    assert source.read_bytes() == original

    output = tmp_path / "output.jsonl"
    stats_alias = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(source),
            "--output",
            str(output),
            "--stats",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert stats_alias.returncode != 0
    assert source.read_bytes() == original
    assert not output.exists()

    trace_collision = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(source),
            "--output",
            str(output),
            "--trace-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert trace_collision.returncode != 0
    assert source.read_bytes() == original
    assert not output.exists()


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


def test_cli_batch_rejects_duplicate_question_ids_before_solving(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "duplicates.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        '{"question_id":"same","question":"1+1"}\n'
        '{"question_id":"same","question":"2+2"}\n',
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "duplicate" in proc.stderr
    assert not output_path.exists()


def test_cli_batch_fail_on_non_success_reports_structured_failures(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text('{"question_id":"bad"}\n', encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--no-trace",
            "--fail-on-non-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    row = SolveResult.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert row.status == "fail"


def test_cli_resume_accepts_its_own_large_valid_result_rows(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        '{"question_id":"large","question":"1+1"}\n', encoding="utf-8"
    )
    long_step = "x" * (70 * 1024)
    output_path.write_text(
        json.dumps(_result_payload("large", steps=[long_step]), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--resume",
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    row = SolveResult.model_validate(
        json.loads(output_path.read_text(encoding="utf-8"))
    )
    assert row.visible_solution_steps == [long_step]


def test_cli_resume_rejects_duplicate_existing_result_ids_without_rewrite(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text('{"question_id":"dup","question":"1+1"}\n', encoding="utf-8")
    original = (
        json.dumps(_result_payload("dup"), ensure_ascii=False)
        + "\n"
        + json.dumps(_result_payload("dup"), ensure_ascii=False)
        + "\n"
    )
    output_path.write_text(original, encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--resume",
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "duplicate" in proc.stderr
    assert output_path.read_text(encoding="utf-8") == original


def test_cli_resume_retries_inconsistent_success_rows(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        '{"question_id":"retry","question":"2+3"}\n', encoding="utf-8"
    )
    output_path.write_text(
        json.dumps(
            _result_payload("retry", value="", status="success", passed=False),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--resume",
            "--retry-failed",
            "--enable-tools",
            "--mode",
            "tool-first",
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    row = SolveResult.model_validate(
        json.loads(output_path.read_text(encoding="utf-8"))
    )
    assert row.question_id == "retry"
    assert not (
        row.status == "success"
        and (row.verification.passed is not True or not row.final_answer.value.strip())
    )


def test_cli_resume_preserves_protocol_values_exactly(tmp_path: Path) -> None:
    question_id = "sk-MOCK_CLI_QUESTION_ID_1234567890"
    answer = "Authorization: Bearer MOCK_CLI_TOKEN_1234567890"
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        json.dumps({"question_id": question_id, "question": "return text"}) + "\n",
        encoding="utf-8",
    )
    output_path.write_text(
        json.dumps(
            _result_payload(question_id, answer, question="return text"),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--resume",
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["question_id"] == question_id
    assert persisted["final_answer"]["value"] == answer


def test_cli_resume_reprocesses_same_id_when_question_fingerprint_changes(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text('{"question_id":"q","question":"2+2"}\n', encoding="utf-8")
    output_path.write_text(
        json.dumps(_result_payload("q", "2", question="1+1")) + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--resume",
            "--enable-tools",
            "--mode",
            "tool-first",
            "--no-trace",
            "--fail-on-non-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    row = SolveResult.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert row.final_answer.value == "4"
    assert row.input_fingerprint == sha256(b"2+2").hexdigest()


def test_cli_resume_reprocesses_when_execution_profile_changes(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    first_stats = tmp_path / "first_stats.json"
    resumed_stats = tmp_path / "resumed_stats.json"
    input_path.write_text(
        '{"question_id":"profile","question":"2+3"}\n', encoding="utf-8"
    )
    initial = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--stats",
            str(first_stats),
            "--no-trace",
            "--fail-on-non-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert initial.returncode == 0, initial.stderr
    first_result = SolveResult.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )

    resumed = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--stats",
            str(resumed_stats),
            "--resume",
            "--enable-tools",
            "--mode",
            "tool-first",
            "--no-trace",
            "--fail-on-non-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert resumed.returncode == 0, resumed.stderr
    second_result = SolveResult.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    stats = json.loads(resumed_stats.read_text(encoding="utf-8"))
    assert stats["processed_count"] == 1
    assert stats["skipped_count"] == 0
    assert second_result.execution_fingerprint != first_result.execution_fingerprint


def test_execution_provenance_distinguishes_mock_and_real_profiles() -> None:
    question = MathQuestion(question_id="profile", question="1+1")

    mock_fingerprint = execution_fingerprint_for_question(
        question, mock=True, save_trace=False
    )
    real_fingerprint = execution_fingerprint_for_question(
        question, mock=False, save_trace=False
    )

    assert mock_fingerprint != real_fingerprint


def test_cli_resume_reprocesses_when_trace_audit_schema_is_incomplete(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    trace_dir = tmp_path / "traces"
    stats_path = tmp_path / "resume_stats.json"
    input_path.write_text(
        '{"question_id":"trace-profile","question":"2+3"}\n',
        encoding="utf-8",
    )
    base_command = [
        sys.executable,
        "-m",
        "math_agent.cli",
        "batch",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--trace-dir",
        str(trace_dir),
        "--fail-on-non-success",
    ]
    initial = subprocess.run(base_command, capture_output=True, text=True, check=False)
    assert initial.returncode == 0, initial.stderr
    trace_path = trace_dir / "trace-profile.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace.pop("model_calls")
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    resumed = subprocess.run(
        [*base_command, "--resume", "--stats", str(stats_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert resumed.returncode == 0, resumed.stderr
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    repaired_trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert stats["processed_count"] == 1
    assert stats["skipped_count"] == 0
    assert isinstance(repaired_trace["model_calls"], list)


def test_cli_resume_drops_results_removed_from_current_input(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text('{"question_id":"keep","question":"1+1"}\n', encoding="utf-8")
    output_path.write_text(
        json.dumps(_result_payload("keep"))
        + "\n"
        + json.dumps(_result_payload("removed"))
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "math_agent.cli",
            "batch",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--resume",
            "--no-trace",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    rows = [
        SolveResult.model_validate_json(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row.question_id for row in rows] == ["keep"]
