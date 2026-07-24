# safety: allow-secret-fixtures
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from math_agent.logging_utils import write_trace
from math_agent.pipeline import execution_fingerprint_for_question
from math_agent.schemas import question_fingerprint
from math_agent.submission.dry_run import (
    build_dry_run_config,
    run_official_dry_run,
    run_one_question,
)
from math_agent.submission.io import (
    DryRunQuestion,
    load_dry_run_questions,
    validate_dry_run_questions,
)


class _FakeResult:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self) -> dict[str, object]:
        return self.payload


def _fake_success(question_id: str, question: str) -> dict[str, object]:
    answer = "5"
    return {
        "question_id": question_id,
        "domain": "arithmetic",
        "problem_type": "calculation",
        "problem_parse": {
            "goal": "compute the result",
            "givens": [],
            "symbols": [],
        },
        "solution_plan": ["calculate directly"],
        "visible_solution_steps": ["2+3=5"],
        "tool_trace": [],
        "status": "success",
        "final_answer": {"type": "number", "value": answer, "boxed": answer},
        "verification": {"method": "none", "passed": True, "notes": "ok"},
        "didactic_hint": "Add the two values.",
        "confidence": 1.0,
        "error": None,
        "input_fingerprint": question_fingerprint(question),
        "execution_fingerprint": sha256(b"fake-dry-run-execution").hexdigest(),
    }


def test_load_and_validate_questions(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        "\n".join(
            [
                json.dumps({"question_id": "q1", "question": "2+3"}),
                json.dumps({"id": "q2", "prompt": "x+x"}),
                "{bad-json}",
                json.dumps({"qid": "q4", "domain": "algebra"}),
            ]
        ),
        encoding="utf-8",
    )
    qs = load_dry_run_questions(input_path)
    assert [q.question_id for q in qs] == ["q1", "q2", "line-3", "q4"]
    stats = validate_dry_run_questions(qs)
    assert stats["total"] == 4
    assert stats["invalid"] == 2


def test_limit_effective(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        "\n".join(
            json.dumps({"question_id": f"q{i}", "question": "a"}) for i in range(5)
        ),
        encoding="utf-8",
    )
    qs = load_dry_run_questions(input_path, limit=2)
    assert len(qs) == 2


def test_duplicate_dry_run_question_ids_are_invalid(tmp_path: Path) -> None:
    input_path = tmp_path / "duplicates.jsonl"
    input_path.write_text(
        '{"question_id":"q","question":"1+1"}\n'
        '{"question_id":"q","question":"2+2"}\n',
        encoding="utf-8",
    )

    questions = load_dry_run_questions(input_path)

    assert questions[0].metadata.get("_invalid") is not True
    assert questions[1].metadata["_error"] == "duplicate_question_id"


def test_canonicalized_dry_run_question_ids_are_deduplicated(tmp_path: Path) -> None:
    input_path = tmp_path / "canonical-duplicates.jsonl"
    input_path.write_text(
        '{"question_id":"q1","question":"2+3"}\n'
        '{"question_id":" q1 ","question":"2+4"}\n',
        encoding="utf-8",
    )

    questions = load_dry_run_questions(input_path)

    assert [question.question_id for question in questions] == ["q1", "q1"]
    assert questions[0].metadata.get("_invalid") is not True
    assert questions[1].metadata["_error"] == "duplicate_question_id"


def test_canonicalized_duplicate_id_cannot_overwrite_a_trace(tmp_path: Path) -> None:
    input_path = tmp_path / "canonical-duplicates.jsonl"
    input_path.write_text(
        '{"question_id":"q1","question":"2+3"}\n'
        '{"question_id":" q1 ","question":"2+4"}\n',
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    summary = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            run_id="canonical-id-run",
            save_trace=True,
        )
    )
    result_rows = [
        json.loads(line)
        for line in (out_dir / "dry_run_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    trace_files = list((out_dir / "traces" / summary.run_id).glob("*.json"))

    assert summary.total == 2
    assert summary.success_count == 1
    assert summary.invalid_count == 1
    assert [row["question_id"] for row in result_rows] == ["q1"]
    assert len(trace_files) == 1


def test_dry_run_rejects_empty_or_negative_limit(tmp_path: Path) -> None:
    for limit in (0, -1, True, 100_001):
        with pytest.raises(ValueError, match="limit"):
            build_dry_run_config(input_path=tmp_path / "input.jsonl", limit=limit)


def test_dry_run_outputs_and_forbidden_name(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        json.dumps(
            {"question_id": "q1", "question": "计算 2+3", "answer_type": "number"}
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    cfg = build_dry_run_config(
        input_path=input_path, out_dir=out_dir, mock=True, save_trace=False
    )
    summary = run_official_dry_run(cfg, command="test")
    assert summary.total == 1
    assert (out_dir / "dry_run_results.jsonl").exists()
    assert (out_dir / "dry_run_summary.json").exists()
    assert (out_dir / "dry_run_report.md").exists()
    assert (out_dir / "run_record.json").exists()
    assert (out_dir / "config_snapshot.json").exists()
    assert not (out_dir / "official_results.jsonl").exists()
    report = (out_dir / "dry_run_report.md").read_text(encoding="utf-8")
    assert "This is NOT official evaluation." in report
    assert "official accuracy" in report

    try:
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            results_name="official_results.jsonl",
        )
    except ValueError as exc:
        assert "forbidden_official_results_name" in str(exc)
    else:
        raise AssertionError("expected forbidden results name to fail")


def test_dry_run_records_each_saved_trace_and_effective_directory(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "trace-q", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    trace_dir = out_dir / "traces"
    summary = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            trace_dir=str(trace_dir),
            mock=True,
            save_trace=True,
            enable_tools=True,
        )
    )
    row = json.loads((out_dir / "dry_run_results.jsonl").read_text(encoding="utf-8"))

    assert summary.trace_dir == str((trace_dir / summary.run_id).absolute())
    assert row["trace_path"]
    assert Path(row["trace_path"]).is_file()
    trace = json.loads(Path(row["trace_path"]).read_text(encoding="utf-8"))
    assert trace["question_id"] == "trace-q"


def test_dry_run_preserves_protocol_values_but_redacts_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_id = "sk-MOCK_DRY_RUN_ID_1234567890"
    answer = "Authorization: Bearer MOCK_DRY_RUN_TOKEN_1234567890"
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        json.dumps({"question_id": question_id, "question": "return text"}) + "\n",
        encoding="utf-8",
    )

    def exact_fake_result(question, **kwargs):
        class FakeResult:
            def model_dump(self):
                payload = _fake_success(question_id, "return text")
                payload["final_answer"] = {
                    "type": "text",
                    "value": answer,
                    "boxed": answer,
                }
                payload["execution_fingerprint"] = execution_fingerprint_for_question(
                    question, **kwargs
                )
                return payload

        return FakeResult()

    monkeypatch.setattr(
        "math_agent.submission.dry_run.solve_question", exact_fake_result
    )
    out_dir = tmp_path / "exact"
    summary = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path, out_dir=out_dir, mock=True, save_trace=False
        )
    )
    persisted = json.loads(
        (out_dir / "dry_run_results.jsonl").read_text(encoding="utf-8")
    )

    assert summary.success_count == 1
    assert persisted["question_id"] == question_id
    assert persisted["final_answer"]["value"] == answer

    leaked = "sk-MOCK_DRY_RUN_EXCEPTION_1234567890"
    monkeypatch.setattr(
        "math_agent.submission.dry_run.solve_question",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(leaked)),
    )
    failed_out = tmp_path / "failed"
    run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=failed_out,
            mock=True,
            save_trace=False,
        )
    )
    failed = (failed_out / "dry_run_results.jsonl").read_text(encoding="utf-8")
    assert leaked not in failed
    assert "[REDACTED]" in failed


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("malformed", "invalid_dry_run_result_schema"),
        ("missing", "invalid_dry_run_result_schema"),
        ("unknown", "noncanonical_dry_run_result_schema"),
    ],
)
def test_dry_run_strictly_rejects_invalid_pipeline_result_schemas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_error: str,
) -> None:
    question = DryRunQuestion(question_id="q", question="2+3")
    payload = _fake_success(question.question_id, question.question)
    if mutation == "malformed":
        payload["confidence"] = "1.0"
    elif mutation == "missing":
        payload.pop("domain")
    else:
        payload["unexpected"] = "must not be ignored"
    monkeypatch.setattr(
        "math_agent.submission.dry_run.solve_question",
        lambda *args, **kwargs: _FakeResult(payload),
    )

    item = run_one_question(
        question,
        build_dry_run_config(
            input_path=tmp_path / "input.jsonl",
            out_dir=tmp_path / "out",
            save_trace=False,
        ),
    )

    assert item.status == "fail"
    assert item.error == expected_error
    assert item.trace_path is None


def test_dry_run_results_name_aliases_and_path_escape_are_forbidden(
    tmp_path: Path,
) -> None:
    for name in (
        "./official_results.jsonl",
        "OFFICIAL_RESULTS.JSONL",
        "sub/../../official_results.jsonl",
        "../escaped.jsonl",
        str(tmp_path / "absolute.jsonl"),
        "result.txt",
        "bad:name.jsonl",
        "CON .jsonl",
        "control\x01.jsonl",
    ):
        with pytest.raises(ValueError):
            build_dry_run_config(
                input_path=str(tmp_path / "input.jsonl"),
                out_dir=str(tmp_path / "out"),
                results_name=name,
            )


def test_dry_run_rejects_input_inside_output_directory(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    input_path = out_dir / "dry_run_results.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "1+1"}) + "\n",
        encoding="utf-8",
    )
    config = build_dry_run_config(
        input_path=input_path, out_dir=out_dir, save_trace=False
    )

    with pytest.raises(ValueError, match="outside_output"):
        run_official_dry_run(config)


def test_dry_run_rejects_trace_root_equal_to_output_root(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "dry_run_summary", "question": "1+1"}) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    config = build_dry_run_config(
        input_path=input_path,
        out_dir=out_dir,
        trace_dir=str(out_dir),
        save_trace=True,
    )

    with pytest.raises(ValueError, match="overlaps_output"):
        run_official_dry_run(config)


def test_real_requires_allow_real_guard(tmp_path: Path) -> None:
    input_path = tmp_path / "in.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q1", "question": "1+1"}), encoding="utf-8"
    )
    with subprocess.Popen(
        [
            sys.executable,
            "scripts/run_official_dry_run.py",
            "--input",
            str(input_path),
            "--out-dir",
            str(tmp_path / "o"),
            "--real",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as p:
        _, err = p.communicate()
        assert p.returncode != 0
        assert "real_run_requires_allow_real" in err


def test_dry_run_rejects_non_mock_or_ambiguous_execution_flags(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires_mock_mode"):
        build_dry_run_config(input_path=tmp_path / "input.jsonl", mock=False)
    with pytest.raises(ValueError, match="must_be_boolean"):
        build_dry_run_config(input_path=tmp_path / "input.jsonl", mock="false")


def test_direct_dataclass_cannot_bypass_mock_only_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )
    safe = build_dry_run_config(
        input_path=input_path,
        out_dir=tmp_path / "out",
        save_trace=False,
    )
    unsafe = replace(safe, mock=False)
    called = False

    def forbidden_call(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("solve_question must not be reached")

    monkeypatch.setattr("math_agent.submission.dry_run.solve_question", forbidden_call)

    with pytest.raises(ValueError, match="requires_mock_mode"):
        run_official_dry_run(unsafe)
    with pytest.raises(ValueError, match="requires_mock_mode"):
        run_one_question(DryRunQuestion(question_id="q", question="2+3"), unsafe)
    assert called is False


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("enable_tools", 1, "must_be_boolean"),
        ("save_trace", 0, "must_be_boolean"),
        ("real", True, "blocked"),
        ("mode", "tool-first", "mode"),
        ("hard_mode_level", "maximum", "hard_mode_level"),
        ("limit", True, "limit"),
        ("run_id", "../escape", "run_id"),
        ("out_dir", "", "out_dir"),
    ],
)
def test_direct_dataclass_fields_are_strictly_revalidated(
    tmp_path: Path, field: str, value: object, error: str
) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )
    safe = build_dry_run_config(
        input_path=input_path,
        out_dir=tmp_path / "out",
        save_trace=False,
    )

    with pytest.raises(ValueError, match=error):
        run_official_dry_run(replace(safe, **{field: value}))


def test_each_run_gets_an_exclusive_trace_namespace(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "same-qid", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    first = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            run_id="run-one",
            save_trace=True,
        )
    )
    first_row = json.loads(
        (out_dir / "dry_run_results.jsonl").read_text(encoding="utf-8")
    )
    first_trace = Path(first_row["trace_path"])
    first_bytes = first_trace.read_bytes()

    second = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            run_id="run-two",
            save_trace=True,
        )
    )
    second_row = json.loads(
        (out_dir / "dry_run_results.jsonl").read_text(encoding="utf-8")
    )
    second_trace = Path(second_row["trace_path"])

    assert first.trace_dir == str((out_dir / "traces" / "run-one").absolute())
    assert second.trace_dir == str((out_dir / "traces" / "run-two").absolute())
    assert first_trace != second_trace
    assert first_trace.read_bytes() == first_bytes
    assert second_trace.is_file()

    with pytest.raises((FileExistsError, ValueError), match="already|exist|reuse"):
        run_official_dry_run(
            build_dry_run_config(
                input_path=input_path,
                out_dir=out_dir,
                run_id="run-two",
                save_trace=True,
            )
        )


@pytest.mark.parametrize("mismatch", ["question", "final_result"])
def test_trace_content_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )

    def mismatched_trace(question, **kwargs):
        raw = _fake_success(question.question_id, question.question)
        trace_final = dict(raw)
        if mismatch == "final_result":
            trace_final["final_answer"] = {
                "type": "number",
                "value": "18",
                "boxed": "18",
            }
        write_trace(
            {
                "question_id": question.question_id,
                "question": "9+9" if mismatch == "question" else question.question,
                "input_fingerprint": question_fingerprint(
                    "9+9" if mismatch == "question" else question.question
                ),
                "execution_fingerprint": raw["execution_fingerprint"],
                "final_result": trace_final,
            },
            kwargs["trace_dir"],
            question.question_id,
        )
        return _FakeResult(raw)

    monkeypatch.setattr(
        "math_agent.submission.dry_run.solve_question", mismatched_trace
    )
    out_dir = tmp_path / "out"
    summary = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            run_id=f"mismatch-{mismatch}",
            save_trace=True,
        )
    )
    row = json.loads((out_dir / "dry_run_results.jsonl").read_text(encoding="utf-8"))

    assert summary.fail_count == 1
    assert row["status"] == "fail"
    assert row["trace_path"] is None
    assert row["error"] == "trace_evidence_missing_or_invalid"


def test_no_trace_rows_and_run_artifacts_bind_the_input_manifest(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.jsonl"
    question = "  2+3  "
    input_path.write_text(
        json.dumps({"question_id": "q", "question": question}) + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    summary = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            run_id="manifest-run",
            save_trace=False,
        )
    )
    row = json.loads((out_dir / "dry_run_results.jsonl").read_text(encoding="utf-8"))
    config_snapshot = json.loads(
        (out_dir / "config_snapshot.json").read_text(encoding="utf-8")
    )
    run_record = json.loads((out_dir / "run_record.json").read_text(encoding="utf-8"))

    assert row["input_fingerprint"] == sha256(b"2+3").hexdigest()
    assert row["execution_fingerprint"]
    assert len(summary.input_manifest_sha256) == 64
    assert config_snapshot["input_manifest_sha256"] == summary.input_manifest_sha256
    assert run_record["input_manifest_sha256"] == summary.input_manifest_sha256
    assert row["metadata"]["input_manifest_sha256"] == summary.input_manifest_sha256


def test_manifest_changes_when_the_actual_question_changes(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )
    first = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=tmp_path / "first",
            run_id="first",
            save_trace=False,
        )
    )
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "2+4"}) + "\n",
        encoding="utf-8",
    )
    second = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=tmp_path / "second",
            run_id="second",
            save_trace=False,
        )
    )

    assert first.input_manifest_sha256 != second.input_manifest_sha256


def test_success_requires_a_nonempty_execution_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )
    raw = _fake_success("q", "2+3")
    raw["execution_fingerprint"] = ""
    monkeypatch.setattr(
        "math_agent.submission.dry_run.solve_question",
        lambda *args, **kwargs: _FakeResult(raw),
    )
    out_dir = tmp_path / "out"

    summary = run_official_dry_run(
        build_dry_run_config(
            input_path=input_path,
            out_dir=out_dir,
            save_trace=False,
        )
    )
    row = json.loads((out_dir / "dry_run_results.jsonl").read_text(encoding="utf-8"))

    assert summary.fail_count == 1
    assert row["status"] == "fail"
    assert row["error"] == "result_input_binding_missing_or_invalid"


def test_input_change_during_execution_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        json.dumps({"question_id": "q", "question": "2+3"}) + "\n",
        encoding="utf-8",
    )

    def mutate_input(question, **kwargs):
        input_path.write_text(
            json.dumps({"question_id": "q", "question": "2+4"}) + "\n",
            encoding="utf-8",
        )
        return _FakeResult(_fake_success(question.question_id, question.question))

    monkeypatch.setattr("math_agent.submission.dry_run.solve_question", mutate_input)

    with pytest.raises(ValueError, match="input_changed_during_execution"):
        run_official_dry_run(
            build_dry_run_config(
                input_path=input_path,
                out_dir=tmp_path / "out",
                save_trace=False,
            )
        )


def test_cli_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/run_official_dry_run.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--input" in proc.stdout
