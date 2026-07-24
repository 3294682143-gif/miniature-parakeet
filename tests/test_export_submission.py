# safety: allow-secret-fixtures
from __future__ import annotations

import importlib.util
import json
import os
import stat
import struct
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path
from types import ModuleType

import pytest

from math_agent.schemas import (
    EXECUTION_PROFILE_VERSION,
    execution_provenance_fingerprint,
)


def _load_export_module() -> ModuleType:
    repository_root = Path(__file__).resolve().parents[1]
    scripts_dir = repository_root / "scripts"
    safety_spec = importlib.util.spec_from_file_location(
        "check_project_safety", scripts_dir / "check_project_safety.py"
    )
    assert safety_spec and safety_spec.loader
    safety_module = importlib.util.module_from_spec(safety_spec)
    previous_safety = sys.modules.get("check_project_safety")
    sys.modules["check_project_safety"] = safety_module
    safety_spec.loader.exec_module(safety_module)
    try:
        export_spec = importlib.util.spec_from_file_location(
            "export_submission_under_test", scripts_dir / "export_submission.py"
        )
        assert export_spec and export_spec.loader
        export_module = importlib.util.module_from_spec(export_spec)
        export_spec.loader.exec_module(export_module)
        return export_module
    finally:
        if previous_safety is None:
            sys.modules.pop("check_project_safety", None)
        else:
            sys.modules["check_project_safety"] = previous_safety


def _run_export(
    repo_root: Path,
    cwd: Path,
    *,
    expect_code: int = 0,
    results: str = "outputs/official_results.jsonl",
    traces: str = "outputs/traces_official_112",
    report: str = "outputs/official_evaluation_report.md",
    run_record: str = "outputs/run_records/RUN_001",
    out: str = "submission",
):
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "export_submission.py"),
        "--results",
        results,
        "--traces",
        traces,
        "--report",
        report,
        "--run-record",
        run_record,
        "--out",
        out,
    ]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == expect_code, proc.stderr + proc.stdout
    return proc


def _valid_execution_profile() -> dict:
    return {
        "profile_version": EXECUTION_PROFILE_VERSION,
        "schema": "SolveResult/v2",
        "client_class": "math_agent.clients.interns1_client.InternS1Client",
        "mock": False,
        "model": "intern-s1",
        "endpoint_sha256": sha256(b"https://api.example.test").hexdigest(),
        "timeout": 60,
        "max_retries": 2,
        "enable_tools": False,
        "save_trace": True,
        "trace_dir_sha256": sha256(b"fake-official-trace-dir").hexdigest(),
        "run_mode": "full",
        "max_refine_rounds": 1,
        "prompt_version": "default",
        "prompt_config_sha256": sha256(b"fake-prompts").hexdigest(),
        "hard_mode_policy": None,
    }


def _valid_result(question_id: str = "q1") -> dict:
    execution_profile = _valid_execution_profile()
    return {
        "question_id": question_id,
        "domain": "arithmetic",
        "problem_type": "calculation",
        "problem_parse": {"goal": "1+1", "givens": [], "symbols": []},
        "solution_plan": ["calculate"],
        "visible_solution_steps": ["1+1=2"],
        "tool_trace": [],
        "final_answer": {"type": "number", "value": "2", "boxed": "2"},
        "verification": {"method": "numeric_check", "passed": True, "notes": "ok"},
        "didactic_hint": "Add the terms.",
        "confidence": 1.0,
        "status": "success",
        "error": None,
        "input_fingerprint": sha256(b"1+1").hexdigest(),
        "execution_fingerprint": execution_provenance_fingerprint(
            question="1+1", execution_profile=execution_profile
        ),
    }


def _setup_fake_repo(tmp_path: Path, real_repo_root: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    (repo / "outputs" / "traces_official_112").mkdir(parents=True)
    (repo / "outputs" / "run_records" / "RUN_001").mkdir(parents=True)
    result = _valid_result()
    execution_profile = _valid_execution_profile()
    (repo / "outputs" / "official_results.jsonl").write_text(
        json.dumps(result) + "\n", encoding="utf-8"
    )
    (repo / "outputs" / "official_evaluation_report.md").write_text(
        "# report\n", encoding="utf-8"
    )
    (repo / "outputs" / "traces_official_112" / "trace.json").write_text(
        json.dumps(
            {
                "question_id": "q1",
                "question": "1+1",
                "input_fingerprint": result["input_fingerprint"],
                "execution_fingerprint": result["execution_fingerprint"],
                "execution_profile": execution_profile,
                "started_at": "2026-07-11T00:00:00+00:00",
                "finished_at": "2026-07-11T00:00:01+00:00",
                "latency_seconds": 1.0,
                "prompt_version": "default",
                "run_mode": "full",
                "route_info": {
                    "domain": result["domain"],
                    "problem_type": result["problem_type"],
                },
                "verifier_result": result["verification"],
                "metadata": {"real_execution_requested": True},
                "model_calls": [
                    {
                        "stage": "solver",
                        "status": "ok",
                        "model": "intern-s1",
                        "prompt_chars": 3,
                        "response_chars": 1,
                    },
                    {
                        "stage": "verifier",
                        "status": "ok",
                        "model": "intern-s1",
                        "prompt_chars": 3,
                        "response_chars": 1,
                    },
                ],
                "model_calls_count": 2,
                "tool_calls": [],
                "errors": [],
                "final_result": result,
            }
        ),
        encoding="utf-8",
    )
    (repo / "outputs" / "run_records" / "RUN_001" / "run.json").write_text(
        "{}", encoding="utf-8"
    )
    (repo / "system_overview.md").write_text("overview", encoding="utf-8")
    (repo / "replay.md").write_text("replay", encoding="utf-8")

    (repo / "scripts" / "check_project_safety.py").write_text(
        (real_repo_root / "scripts" / "check_project_safety.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (repo / "scripts" / "export_submission.py").write_text(
        (real_repo_root / "scripts" / "export_submission.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    return repo


def test_export_submission_happy_path(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)

    proc = _run_export(real_repo_root, repo)
    assert "OK: submission package created" in proc.stdout

    sub = repo / "submission"
    assert (sub / "result" / "final_output.jsonl").is_file()
    assert (sub / "logs" / "traces" / "trace.json").is_file()
    assert (sub / "logs" / "run_record" / "run.json").is_file()
    assert (sub / "docs" / "README_SUBMISSION.md").is_file()
    assert (repo / "submission.zip").is_file()
    assert (repo / "submission.zip").stat().st_mode & stat.S_IREAD

    with zipfile.ZipFile(repo / "submission.zip") as zf:
        names = zf.namelist()
        assert "submission/result/final_output.jsonl" in names


def test_export_rejects_schema_invalid_or_duplicate_results(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    results = repo / "outputs" / "official_results.jsonl"
    results.write_text('{"status":"success"}\n', encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "result row" in proc.stderr
    assert not (repo / "submission.zip").exists()


def test_export_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    results_path = repo / "outputs" / "official_results.jsonl"
    raw = json.dumps(_valid_result())
    raw = raw.replace(
        '"status": "success"',
        '"status": "fail", "status": "success"',
        1,
    )
    results_path.write_text(raw + "\n", encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "invalid JSON" in proc.stderr
    assert not (repo / "submission.zip").exists()


def test_export_rejects_result_trace_mismatch(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    trace_path = repo / "outputs" / "traces_official_112" / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["final_result"]["final_answer"]["value"] = "3"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "does not match" in proc.stderr
    assert not (repo / "submission.zip").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", 0.25),
        ("solution_plan", ["different plan"]),
        ("visible_solution_steps", ["different evidence"]),
        ("didactic_hint", "different hint"),
    ],
)
def test_export_rejects_noncore_result_trace_mismatch(
    tmp_path: Path, field: str, value: object
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    trace_path = repo / "outputs" / "traces_official_112" / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["final_result"][field] = value
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "does not match" in proc.stderr
    assert not (repo / "submission.zip").exists()


@pytest.mark.parametrize("mutation", ["verification_method", "tool_trace"])
def test_export_rejects_equal_but_nested_schema_invalid_evidence(
    tmp_path: Path, mutation: str
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    results_path = repo / "outputs" / "official_results.jsonl"
    result = json.loads(results_path.read_text(encoding="utf-8"))
    if mutation == "verification_method":
        result["verification"]["method"] = "not-a-method"
    else:
        result["tool_trace"] = [
            {
                "tool": "curl",
                "purpose": 7,
                "status": "maybe",
                "summary": None,
            }
        ]
    results_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    trace_path = repo / "outputs" / "traces_official_112" / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["final_result"] = result
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "violates the schema" in proc.stderr
    assert not (repo / "submission.zip").exists()


def test_export_rejects_unverifiable_execution_fingerprint(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    forged = "a" * 64
    results_path = repo / "outputs" / "official_results.jsonl"
    result = json.loads(results_path.read_text(encoding="utf-8"))
    result["execution_fingerprint"] = forged
    results_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    trace_path = repo / "outputs" / "traces_official_112" / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["execution_fingerprint"] = forged
    trace["final_result"] = result
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "provenance" in proc.stderr or "does not match" in proc.stderr
    assert not (repo / "submission.zip").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean_model_count",
        "forged_tool_call",
        "missing_started_at",
        "negative_latency",
        "prompt_mismatch",
        "route_mismatch",
        "verifier_mismatch",
        "failed_model_call",
        "missing_verifier_call",
        "missing_solver_call",
    ],
)
def test_export_rejects_malformed_or_unbound_trace_audit_evidence(
    tmp_path: Path, mutation: str
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    trace_path = repo / "outputs" / "traces_official_112" / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    if mutation == "boolean_model_count":
        trace["model_calls_count"] = True
    elif mutation == "forged_tool_call":
        trace["tool_calls"] = [
            {
                "tool": "sympy",
                "purpose": "forged",
                "status": "success",
                "summary": "not present in the result",
            }
        ]
    elif mutation == "missing_started_at":
        trace.pop("started_at")
    elif mutation == "negative_latency":
        trace["latency_seconds"] = -1
    elif mutation == "prompt_mismatch":
        trace["prompt_version"] = "forged"
    elif mutation == "route_mismatch":
        trace["route_info"]["domain"] = "forged"
    elif mutation == "verifier_mismatch":
        trace["verifier_result"]["passed"] = False
    elif mutation == "failed_model_call":
        trace["model_calls"][0]["status"] = "error"
    elif mutation == "missing_verifier_call":
        trace["model_calls"].pop()
        trace["model_calls_count"] = 1
    else:
        trace["model_calls"].pop(0)
        trace["model_calls_count"] = 1
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "does not match" in proc.stderr
    assert not (repo / "submission.zip").exists()


def test_export_rejects_duplicate_result_ids(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    results = repo / "outputs" / "official_results.jsonl"
    row = json.dumps(_valid_result())
    results.write_text(row + "\n" + row + "\n", encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "duplicate" in proc.stderr


def test_missing_results_fails(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    (repo / "outputs" / "official_results.jsonl").unlink()
    proc = _run_export(real_repo_root, repo, expect_code=2)
    assert "results file not found" in proc.stderr


def test_missing_traces_fails(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    for p in (repo / "outputs" / "traces_official_112").glob("*"):
        p.unlink()
    (repo / "outputs" / "traces_official_112").rmdir()
    proc = _run_export(real_repo_root, repo, expect_code=2)
    assert "traces directory not found" in proc.stderr


def test_excluded_files_not_in_zip(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    (repo / ".env").write_text("INTERNS1_API_KEY=SECRET", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / "outputs" / "traces_official_112" / "__pycache__").mkdir()
    (repo / "outputs" / "traces_official_112" / "__pycache__" / "x.pyc").write_bytes(
        b"x"
    )

    _run_export(real_repo_root, repo)
    with zipfile.ZipFile(repo / "submission.zip") as zf:
        zipped = "\n".join(zf.namelist())
        assert ".env" not in zipped
        assert ".git" not in zipped
        assert "__pycache__" not in zipped


def test_sensitive_content_fails_without_echoing_secret(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    (repo / "scripts" / "leak.py").write_text(
        "Authorization: Bearer NEVER_PRINT_SECRET_123456",  # safety: allow-mock-token
        encoding="utf-8",
    )

    proc = _run_export(real_repo_root, repo, expect_code=3)
    assert "high-risk sensitive content" in proc.stderr
    assert "NEVER_PRINT_SECRET_123456" not in proc.stderr


def test_readme_generated_when_report_missing(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    (repo / "outputs" / "official_evaluation_report.md").unlink()

    proc = _run_export(real_repo_root, repo)
    assert "WARNING: report not found" in proc.stderr
    readme = (repo / "submission" / "docs" / "README_SUBMISSION.md").read_text(
        encoding="utf-8"
    )
    assert "report 包含状态：missing" in readme


def test_repository_root_cannot_be_used_as_output(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    sentinel = repo / "DO_NOT_DELETE.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    proc = _run_export(real_repo_root, repo, out=".", expect_code=2)

    assert "unsafe output path" in proc.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_existing_output_directory_is_not_deleted(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    output = repo / "protected"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    proc = _run_export(real_repo_root, repo, out="protected", expect_code=2)

    assert "already exists" in proc.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_output_outside_repository_is_rejected(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    proc = _run_export(real_repo_root, repo, out=str(outside), expect_code=2)

    assert "unsafe output path" in proc.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_results_outside_repository_are_rejected(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    outside_results = tmp_path / "outside-results.jsonl"
    outside_results.write_text('{"status":"success"}\n', encoding="utf-8")

    proc = _run_export(
        real_repo_root,
        repo,
        results=str(outside_results),
        expect_code=2,
    )

    assert "unsafe results path" in proc.stderr


def test_secret_in_results_is_blocked_before_packaging(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    secret = "SUPER_SECRET_VALUE_123456"
    (repo / "outputs" / "official_results.jsonl").write_text(
        '{"api_key":"' + secret + '"}\n', encoding="utf-8"
    )

    proc = _run_export(real_repo_root, repo, expect_code=3)

    assert (
        "export source contains sensitive content" in proc.stderr
        or "high-risk sensitive content detected" in proc.stderr
    )
    assert secret not in proc.stderr
    assert not (repo / "submission.zip").exists()


def test_existing_submission_archive_is_not_overwritten(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    archive = repo / "submission.zip"
    archive.write_bytes(b"preserve")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "already exists" in proc.stderr
    assert archive.read_bytes() == b"preserve"


@pytest.mark.parametrize(
    "relative_path",
    [
        "outputs/traces_official_112/trace.json",
        "outputs/run_records/RUN_001/run.json",
        "outputs/official_evaluation_report.md",
        "demo/demo_script.md",
        "system_overview.md",
        "replay.md",
        "candidate_summary.md",
    ],
)
def test_secret_in_any_export_source_is_blocked(
    tmp_path: Path, relative_path: str
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    secret = "SOURCE_CREDENTIAL_VALUE_987654"
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'{{"api_key":"{secret}"}}\n', encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=3)

    assert (
        "export source contains sensitive content" in proc.stderr
        or "high-risk sensitive content detected" in proc.stderr
    )
    assert secret not in proc.stderr
    assert not (repo / "submission.zip").exists()


def test_unknown_and_non_utf8_trace_files_fail_closed(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    cases = (
        ("trace.bin", b"safe"),
        ("trace.json", b"\xff\xfe"),
        (
            "trace-utf16.json",
            "sk-UTF16_SECRET_VALUE_123456".encode("utf-16le"),
        ),
    )
    for name, content in cases:
        case_root = tmp_path / name.replace(".", "-")
        case_root.mkdir()
        repo = _setup_fake_repo(case_root, real_repo_root)
        target = repo / "outputs" / "traces_official_112" / name
        target.write_bytes(content)

        proc = _run_export(real_repo_root, repo, expect_code=3)

        assert "export source contains sensitive content" in proc.stderr
        assert not (repo / "submission.zip").exists()


def test_secret_in_export_filename_is_blocked_without_echo(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    secret = "sk-FILENAME_SECRET_VALUE_123456"
    (repo / "outputs" / "traces_official_112" / f"{secret}.json").write_text(
        "{}", encoding="utf-8"
    )

    proc = _run_export(real_repo_root, repo, expect_code=3)

    assert (
        "sensitive_export_filename" in proc.stderr
        or "sensitive_project_filename" in proc.stderr
    )
    assert secret not in proc.stderr


def test_pdf_report_is_rejected_until_content_scanning_is_supported(
    tmp_path: Path,
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    report = repo / "outputs" / "report.pdf"
    report.write_bytes(b"%PDF-1.7\n")

    proc = _run_export(
        real_repo_root,
        repo,
        report="outputs/report.pdf",
        expect_code=3,
    )

    assert "unsupported_export_file_type" in proc.stderr
    assert not (repo / "submission.zip").exists()


def test_protected_and_overlapping_outputs_are_rejected(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    for out in ("src", "outputs", "outputs/traces_official_112/export"):
        case_root = tmp_path / out.replace("/", "-")
        case_root.mkdir()
        repo = _setup_fake_repo(case_root, real_repo_root)
        sentinel = repo / "outputs" / "official_results.jsonl"
        before = sentinel.read_bytes()

        proc = _run_export(real_repo_root, repo, out=out, expect_code=2)

        assert "unsafe output path" in proc.stderr
        assert sentinel.read_bytes() == before


def test_export_paths_use_cross_platform_portable_identity() -> None:
    export_module = _load_export_module()
    key = export_module._portable_relative_path_key

    assert key("logs/Q1.json") == key("logs/q1.json")
    assert key("logs/CON.json") is None
    assert key("logs/trailing.") is None
    assert key("logs/name:stream") is None
    assert key("logs/e\u0301.json") is None
    assert key("logs/é.json") is not None


def test_existing_generated_output_requires_a_new_output_name(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)

    _run_export(real_repo_root, repo)
    marker = repo / "submission" / ".evoexternmath-submission.json"
    assert marker.is_file()
    original_archive = (repo / "submission.zip").read_bytes()

    updated = _valid_result()
    updated["didactic_hint"] = "Add the terms in run 2."
    (repo / "outputs" / "official_results.jsonl").write_text(
        json.dumps(updated) + "\n", encoding="utf-8"
    )
    trace_path = repo / "outputs" / "traces_official_112" / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["final_result"] = updated
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "already exists" in proc.stderr
    assert (repo / "submission.zip").read_bytes() == original_archive

    _run_export(real_repo_root, repo, out="submission-next")
    exported = repo / "submission-next" / "result" / "final_output.jsonl"
    assert "Add the terms in run 2." in exported.read_text(encoding="utf-8")
    assert (repo / "submission-next.zip").is_file()


def test_symlinked_result_cannot_escape_repository(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"status":"success"}\n', encoding="utf-8")
    result_path = repo / "outputs" / "official_results.jsonl"
    result_path.unlink()
    try:
        result_path.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable on this Windows host")

    proc = _run_export(real_repo_root, repo, expect_code=2)

    assert "symbolic links are not allowed" in proc.stderr
    assert not (repo / "submission.zip").exists()


def _prepare_export_transaction(
    export_module: ModuleType, repo: Path
) -> tuple[dict[str, object], Path, Path, Path, Path]:
    transaction_id = "a" * 32
    payload: dict[str, object] = {
        "out_name": "submission",
        "staging_nonce": "b" * 32,
        "state": "building",
        "transaction_id": transaction_id,
        "version": 1,
    }
    out_dir, archive_path, staging_dir, temporary_archive, _, _ = (
        export_module._transaction_paths(repo, payload)
    )
    export_module._write_journal(repo, payload)
    staging_dir.mkdir()
    export_module._write_staging_sentinel(
        staging_dir,
        transaction_id,
        str(payload["staging_nonce"]),
    )
    export_module._record_identity(payload, "staging", staging_dir)
    export_module._write_journal(repo, payload)
    export_module._populate_staging_directory(
        staging_dir,
        repo,
        repo / "outputs" / "official_results.jsonl",
        repo / "outputs" / "traces_official_112",
        repo / "outputs" / "official_evaluation_report.md",
        repo / "outputs" / "run_records" / "RUN_001",
        out_name=out_dir.name,
        report_argument="outputs/official_evaluation_report.md",
        run_record_argument="outputs/run_records/RUN_001",
        staging_nonce=str(payload["staging_nonce"]),
        transaction_id=transaction_id,
    )
    temporary_archive.touch()
    export_module._record_identity(payload, "temporary_archive", temporary_archive)
    export_module._write_journal(repo, payload)
    export_module._build_zip_archive(
        staging_dir, temporary_archive, out_dir.name, payload
    )
    export_module._update_journal_state(repo, payload, "prepared")
    return payload, out_dir, archive_path, staging_dir, temporary_archive


def _assert_recovery_rejects_tampered_archive(
    export_module: ModuleType,
    repo: Path,
    payload: dict[str, object],
    out_dir: Path,
    archive_path: Path,
    temporary_archive: Path,
) -> None:
    assert (
        export_module._validate_export_archive(
            temporary_archive,
            out_dir.name,
            str(payload["transaction_id"]),
            str(payload["staging_nonce"]),
        )
        is False
    )
    assert export_module._recover_pending_transaction(repo) is None
    assert not out_dir.exists()
    assert not archive_path.exists()
    assert not temporary_archive.exists()


def test_prepared_transaction_is_recovered_atomically(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    _, out_dir, archive_path, _, _ = _prepare_export_transaction(export_module, repo)

    recovered_out = export_module._recover_pending_transaction(repo)

    assert recovered_out == "submission"
    assert out_dir.is_dir()
    assert archive_path.is_file()
    assert not (repo / ".evoexternmath-export-transaction.json").exists()


def test_recovery_rejects_nonempty_archive_comment(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    with zipfile.ZipFile(temporary_archive, "a") as archive:
        archive.comment = b"unmanifested global metadata"

    _assert_recovery_rejects_tampered_archive(
        export_module,
        repo,
        payload,
        out_dir,
        archive_path,
        temporary_archive,
    )


def test_recovery_rejects_nonempty_member_comment(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    with zipfile.ZipFile(temporary_archive) as source:
        entries = [(info, source.read(info)) for info in source.infolist()]
    with zipfile.ZipFile(
        temporary_archive, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for original, contents in entries:
            info = zipfile.ZipInfo(original.filename, original.date_time)
            info.compress_type = original.compress_type
            info.create_system = original.create_system
            info.external_attr = original.external_attr
            if original.filename.endswith("src_snapshot_note.md"):
                info.comment = b"unmanifested member metadata"
            target.writestr(info, contents)

    _assert_recovery_rejects_tampered_archive(
        export_module,
        repo,
        payload,
        out_dir,
        archive_path,
        temporary_archive,
    )


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param("preamble", id="sfx-preamble"),
        pytest.param("central-gap", id="central-directory-gap"),
        pytest.param("tail", id="trailing-bytes"),
    ],
)
def test_recovery_rejects_noncanonical_archive_byte_layout(
    tmp_path: Path, tamper: str
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    raw = bytearray(temporary_archive.read_bytes())
    if tamper == "preamble":
        raw[:0] = b"MZ-unmanifested-SFX-preamble"
    elif tamper == "central-gap":
        eocd_offset = raw.rfind(b"PK\x05\x06")
        assert eocd_offset >= 0
        central_offset = struct.unpack_from("<I", raw, eocd_offset + 16)[0]
        gap = b"unmanifested-gap"
        raw[central_offset:central_offset] = gap
        eocd_offset += len(gap)
        struct.pack_into("<I", raw, eocd_offset + 16, central_offset + len(gap))
    else:
        assert tamper == "tail"
        raw.extend(b"unmanifested-tail")
    temporary_archive.write_bytes(raw)

    _assert_recovery_rejects_tampered_archive(
        export_module,
        repo,
        payload,
        out_dir,
        archive_path,
        temporary_archive,
    )


def test_commit_rechecks_directory_archive_pair_after_committed_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, staging_dir, temporary_archive = (
        _prepare_export_transaction(export_module, repo)
    )
    original_update = export_module._update_journal_state

    def update_then_change_directory(repo_root, current_payload, state):
        original_update(repo_root, current_payload, state)
        if state == "committed":
            (out_dir / "result" / "final_output.jsonl").write_text(
                '{"changed":true}\n', encoding="utf-8"
            )

    monkeypatch.setattr(
        export_module, "_update_journal_state", update_then_change_directory
    )

    with pytest.raises(export_module.ExportSafetyError):
        export_module._commit_new_export(
            repo,
            payload,
            out_dir,
            archive_path,
            staging_dir,
            temporary_archive,
        )

    assert not export_module._published_pair_is_safe(
        out_dir,
        archive_path,
        str(payload["transaction_id"]),
        str(payload["staging_nonce"]),
    )


def test_recovery_rejects_archive_member_with_link_metadata(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    with zipfile.ZipFile(temporary_archive) as source:
        entries = [(info, source.read(info)) for info in source.infolist()]
    with temporary_archive.open("r+b") as raw_archive:
        raw_archive.seek(0)
        raw_archive.truncate()
        with zipfile.ZipFile(
            raw_archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for original, contents in entries:
                info = zipfile.ZipInfo(original.filename, original.date_time)
                info.compress_type = original.compress_type
                info.create_system = original.create_system
                info.external_attr = original.external_attr
                if original.filename.endswith("src_snapshot_note.md"):
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                target.writestr(info, contents)

    assert (
        export_module._validate_export_archive(
            temporary_archive,
            out_dir.name,
            str(payload["transaction_id"]),
            str(payload["staging_nonce"]),
        )
        is False
    )
    assert export_module._recover_pending_transaction(repo) is None

    assert not out_dir.exists()
    assert not archive_path.exists()
    assert not temporary_archive.exists()


def test_recovery_rejects_local_header_flag_mismatch(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    with zipfile.ZipFile(temporary_archive) as archive:
        target = next(
            info
            for info in archive.infolist()
            if info.filename.endswith("src_snapshot_note.md")
        )
        header_offset = target.header_offset
    with temporary_archive.open("r+b") as raw_archive:
        raw_archive.seek(header_offset + 6)
        original_flags = int.from_bytes(raw_archive.read(2), "little")
        raw_archive.seek(header_offset + 6)
        raw_archive.write((original_flags | 0x1).to_bytes(2, "little"))
        raw_archive.flush()
        os.fsync(raw_archive.fileno())

    assert (
        export_module._validate_export_archive(
            temporary_archive,
            out_dir.name,
            str(payload["transaction_id"]),
            str(payload["staging_nonce"]),
        )
        is False
    )
    assert export_module._recover_pending_transaction(repo) is None
    assert not out_dir.exists()
    assert not archive_path.exists()
    assert not temporary_archive.exists()


def test_recovery_rejects_archive_extra_fields(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    with zipfile.ZipFile(temporary_archive) as source:
        entries = [(info, source.read(info)) for info in source.infolist()]
    with temporary_archive.open("r+b") as raw_archive:
        raw_archive.seek(0)
        raw_archive.truncate()
        with zipfile.ZipFile(
            raw_archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for original, contents in entries:
                info = zipfile.ZipInfo(original.filename, original.date_time)
                info.compress_type = original.compress_type
                info.create_system = original.create_system
                info.external_attr = original.external_attr
                if original.filename.endswith("src_snapshot_note.md"):
                    info.extra = b"\xfe\xca\x00\x00"
                target.writestr(info, contents)

    assert (
        export_module._validate_export_archive(
            temporary_archive,
            out_dir.name,
            str(payload["transaction_id"]),
            str(payload["staging_nonce"]),
        )
        is False
    )
    assert export_module._recover_pending_transaction(repo) is None
    assert not out_dir.exists()
    assert not archive_path.exists()
    assert not temporary_archive.exists()


def test_recovery_rejects_backslash_member_name(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    with temporary_archive.open("r+b") as raw_archive:
        raw = raw_archive.read()
        expected_name = b"submission/src_snapshot_note.md"
        replacement_name = expected_name.replace(b"/", b"\\")
        assert raw.count(expected_name) == 2
        raw_archive.seek(0)
        raw_archive.truncate()
        raw_archive.write(raw.replace(expected_name, replacement_name))
        raw_archive.flush()
        os.fsync(raw_archive.fileno())

    assert (
        export_module._validate_export_archive(
            temporary_archive,
            out_dir.name,
            str(payload["transaction_id"]),
            str(payload["staging_nonce"]),
        )
        is False
    )
    assert export_module._recover_pending_transaction(repo) is None
    assert not out_dir.exists()
    assert not archive_path.exists()
    assert not temporary_archive.exists()


def test_recovery_rejects_dos_non_file_attributes(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, _, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )

    with zipfile.ZipFile(temporary_archive) as source:
        entries = [(info, source.read(info)) for info in source.infolist()]
    with temporary_archive.open("r+b") as raw_archive:
        raw_archive.seek(0)
        raw_archive.truncate()
        with zipfile.ZipFile(
            raw_archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for original, contents in entries:
                info = zipfile.ZipInfo(original.filename, original.date_time)
                info.compress_type = original.compress_type
                info.create_system = 0
                info.external_attr = original.external_attr
                if original.filename.endswith("src_snapshot_note.md"):
                    info.external_attr = (info.external_attr & ~0xFF) | 0x08
                target.writestr(info, contents)

    assert (
        export_module._validate_export_archive(
            temporary_archive,
            out_dir.name,
            str(payload["transaction_id"]),
            str(payload["staging_nonce"]),
        )
        is False
    )
    assert export_module._recover_pending_transaction(repo) is None
    assert not out_dir.exists()
    assert not archive_path.exists()
    assert not temporary_archive.exists()


def test_keyboard_interrupt_rolls_back_before_archive_commit(
    tmp_path: Path, monkeypatch
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, staging_dir, temporary_archive = (
        _prepare_export_transaction(export_module, repo)
    )

    original_publish = export_module._publish_archive_no_clobber

    def interrupt_publish(*args, **kwargs):
        original_publish(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(export_module, "_publish_archive_no_clobber", interrupt_publish)
    with pytest.raises(KeyboardInterrupt):
        export_module._commit_new_export(
            repo,
            payload,
            out_dir,
            archive_path,
            staging_dir,
            temporary_archive,
        )

    assert not out_dir.exists()
    assert not archive_path.exists()
    assert staging_dir.is_dir()
    assert payload["state"] == "prepared"


def test_output_appearing_during_build_is_never_deleted(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, staging_dir, temporary_archive = (
        _prepare_export_transaction(export_module, repo)
    )
    out_dir.mkdir()
    sentinel = out_dir / "VALUABLE.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(export_module.ExportSafetyError, match="appeared"):
        export_module._commit_new_export(
            repo,
            payload,
            out_dir,
            archive_path,
            staging_dir,
            temporary_archive,
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not archive_path.exists()


def test_replaced_archive_temp_is_never_truncated(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, _, staging_dir, temporary_archive = _prepare_export_transaction(
        export_module, repo
    )
    original_temp = temporary_archive.with_name(temporary_archive.name + ".moved")
    temporary_archive.replace(original_temp)
    temporary_archive.write_bytes(b"USER-VALUABLE-DATA")

    with pytest.raises(export_module.ExportSafetyError, match="identity changed"):
        export_module._build_zip_archive(
            staging_dir, temporary_archive, out_dir.name, payload
        )

    assert temporary_archive.read_bytes() == b"USER-VALUABLE-DATA"


def test_marker_transition_interruption_remains_recoverable(
    tmp_path: Path, monkeypatch
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    transaction_id = "e" * 32
    payload: dict[str, object] = {
        "out_name": "submission",
        "staging_nonce": "f" * 32,
        "state": "building",
        "transaction_id": transaction_id,
        "version": 1,
    }
    _, _, staging_dir, _, _, _ = export_module._transaction_paths(repo, payload)
    export_module._write_journal(repo, payload)
    staging_dir.mkdir()
    export_module._write_staging_sentinel(
        staging_dir, transaction_id, str(payload["staging_nonce"])
    )
    export_module._record_identity(payload, "staging", staging_dir)
    export_module._write_journal(repo, payload)
    original_replace = export_module.os.replace

    def replace_then_interrupt(source, destination):
        original_replace(source, destination)
        if Path(destination).name == ".evoexternmath-submission.json":
            raise KeyboardInterrupt

    monkeypatch.setattr(export_module.os, "replace", replace_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        export_module._populate_staging_directory(
            staging_dir,
            repo,
            repo / "outputs" / "official_results.jsonl",
            repo / "outputs" / "traces_official_112",
            repo / "outputs" / "official_evaluation_report.md",
            repo / "outputs" / "run_records" / "RUN_001",
            out_name="submission",
            report_argument="outputs/official_evaluation_report.md",
            run_record_argument="outputs/run_records/RUN_001",
            staging_nonce=str(payload["staging_nonce"]),
            transaction_id=transaction_id,
        )

    assert (staging_dir / ".evoexternmath-staging.json").is_file()
    assert not export_module._validate_export_directory(
        staging_dir, transaction_id, "submission", str(payload["staging_nonce"])
    )
    monkeypatch.setattr(export_module.os, "replace", original_replace)
    export_module._recover_pending_transaction(repo)
    assert not staging_dir.exists()
    assert not (repo / ".evoexternmath-export-transaction.json").exists()


def test_recovery_rescans_prepared_content_before_publishing(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, staging_dir, temporary_archive = (
        _prepare_export_transaction(export_module, repo)
    )
    secret = "FORGED_RECOVERY_SECRET_VALUE_123456"
    (staging_dir / "result" / "final_output.jsonl").write_text(
        json.dumps({"api_key": secret}) + "\n", encoding="utf-8"
    )
    marker = staging_dir / export_module.EXPORT_MARKER_NAME
    marker.write_text(
        json.dumps(
            export_module._marker_payload(
                staging_dir,
                str(payload["transaction_id"]),
                str(payload["out_name"]),
                str(payload["staging_nonce"]),
            ),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    export_module._build_zip_archive(
        staging_dir, temporary_archive, out_dir.name, payload
    )

    with pytest.raises(export_module.ExportSafetyError, match="sensitive"):
        export_module._recover_pending_transaction(repo)

    assert secret in (staging_dir / "result" / "final_output.jsonl").read_text(
        encoding="utf-8"
    )
    assert not out_dir.exists()
    assert not archive_path.exists()
    assert (repo / ".evoexternmath-export-transaction.json").is_file()


def test_marker_with_untracked_fields_is_rejected(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, _, _, staging_dir, _ = _prepare_export_transaction(export_module, repo)
    marker_path = staging_dir / export_module.EXPORT_MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["untracked"] = "not bound by the file manifest"
    marker_path.write_text(json.dumps(marker) + "\n", encoding="utf-8")

    assert not export_module._validate_export_directory(
        staging_dir,
        str(payload["transaction_id"]),
        str(payload["out_name"]),
        str(payload["staging_nonce"]),
    )


def test_readonly_sources_do_not_create_readonly_submission_files(
    tmp_path: Path,
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    results = repo / "outputs" / "official_results.jsonl"
    os.chmod(results, stat.S_IREAD)
    try:
        _run_export(real_repo_root, repo)
    finally:
        os.chmod(results, stat.S_IWRITE)

    exported = repo / "submission" / "result" / "final_output.jsonl"
    assert exported.stat().st_mode & stat.S_IWRITE


def test_nested_custom_output_is_rejected(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    (repo / "safe").mkdir()

    proc = _run_export(real_repo_root, repo, out="safe/submission", expect_code=2)

    assert "direct child" in proc.stderr
    assert not (repo / "safe" / "submission").exists()


@pytest.mark.parametrize("out_name", ["foo.", "CON", "LPT1.txt"])
def test_windows_ambiguous_output_names_are_rejected(
    tmp_path: Path, out_name: str
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)

    proc = _run_export(real_repo_root, repo, out=out_name, expect_code=2)

    assert "unsupported output name" in proc.stderr
    assert not (repo / out_name.rstrip(".")).exists()


def test_forged_recovery_journal_never_deletes_unowned_staging(
    tmp_path: Path,
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    transaction_id = "c" * 32
    payload = {
        "out_name": "victim",
        "staging_nonce": "d" * 32,
        "state": "building",
        "transaction_id": transaction_id,
        "version": 1,
    }
    _, _, staging_dir, _, _, _ = export_module._transaction_paths(repo, payload)
    staging_dir.mkdir()
    sentinel = staging_dir / "USER_KEEP.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    export_module._write_journal(repo, payload)

    with pytest.raises(export_module.ExportSafetyError, match="identity changed"):
        export_module._recover_pending_transaction(repo)

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert (repo / ".evoexternmath-export-transaction.json").exists()


def test_invalid_journal_version_fails_closed(tmp_path: Path) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    journal = repo / ".evoexternmath-export-transaction.json"
    journal.write_text(
        '{"out_name":"submission","staging_nonce":"dddddddddddddddddddddddddddddddd",'
        '"state":"building","transaction_id":"cccccccccccccccccccccccccccccccc",'
        '"version":999}\n',
        encoding="utf-8",
    )

    with pytest.raises(export_module.ExportSafetyError, match="invalid pending"):
        export_module._recover_pending_transaction(repo)

    assert journal.is_file()


def test_prepared_journal_without_recorded_identities_never_publishes(
    tmp_path: Path,
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    payload, out_dir, archive_path, staging_dir, temporary_archive = (
        _prepare_export_transaction(export_module, repo)
    )
    for key in (
        "staging_device",
        "staging_inode",
        "temporary_archive_device",
        "temporary_archive_inode",
    ):
        payload.pop(key)
    export_module._write_journal(repo, payload)

    with pytest.raises(export_module.ExportSafetyError, match="invalid pending"):
        export_module._recover_pending_transaction(repo)

    assert not out_dir.exists()
    assert not archive_path.exists()
    assert staging_dir.is_dir()
    assert temporary_archive.is_file()
    assert (repo / ".evoexternmath-export-transaction.json").is_file()


def test_cleanup_failure_is_never_reported_as_success(
    tmp_path: Path, monkeypatch
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()
    original_remove = export_module._remove_internal_path

    def fail_archive_temp_cleanup(path: Path) -> None:
        if path.name == ".evoexternmath-export-transaction.json":
            raise OSError("simulated cleanup failure")
        original_remove(path)

    monkeypatch.setattr(
        export_module, "_remove_internal_path", fail_archive_temp_cleanup
    )
    args = export_module.build_parser().parse_args(
        [
            "--results",
            "outputs/official_results.jsonl",
            "--traces",
            "outputs/traces_official_112",
            "--report",
            "outputs/official_evaluation_report.md",
            "--run-record",
            "outputs/run_records/RUN_001",
        ]
    )

    result = export_module._run_export(args, repo)

    assert result == 2
    assert (repo / ".evoexternmath-export-transaction.json").is_file()
    assert (repo / "submission").is_dir()
    assert (repo / "submission.zip").is_file()


def test_unsupported_atomic_publish_aborts_without_residuals(
    tmp_path: Path, monkeypatch
) -> None:
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    export_module = _load_export_module()

    def fail_publish(*args, **kwargs):
        raise OSError("atomic publish unsupported")

    monkeypatch.setattr(export_module, "_publish_archive_no_clobber", fail_publish)
    args = export_module.build_parser().parse_args(
        [
            "--results",
            "outputs/official_results.jsonl",
            "--traces",
            "outputs/traces_official_112",
            "--report",
            "outputs/official_evaluation_report.md",
            "--run-record",
            "outputs/run_records/RUN_001",
        ]
    )

    result = export_module._run_export(args, repo)

    assert result == 2
    assert not (repo / "submission").exists()
    assert not (repo / "submission.zip").exists()
    assert not (repo / ".evoexternmath-export-transaction.json").exists()
    assert not any(repo.glob(".submission.*-*"))


def test_export_lock_rejects_preexisting_hardlink_without_modifying_target(
    tmp_path: Path,
) -> None:
    export_module = _load_export_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    target = tmp_path / "valuable.txt"
    target.write_bytes(b"")
    lock_path = export_module._lock_path(repo.resolve())
    lock_path.unlink(missing_ok=True)
    try:
        os.link(target, lock_path)
    except OSError:
        pytest.skip("hard links are unavailable on this host")
    try:
        with pytest.raises(export_module.ExportSafetyError, match="unsafe"):
            export_module._acquire_export_lock(repo.resolve())
        assert target.read_bytes() == b""
    finally:
        lock_path.unlink(missing_ok=True)
