from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


def _run_export(repo_root: Path, cwd: Path, *, expect_code: int = 0):
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "export_submission.py"),
        "--results",
        "outputs/official_results.jsonl",
        "--traces",
        "outputs/traces_official_112",
        "--report",
        "outputs/official_evaluation_report.md",
        "--run-record",
        "outputs/run_records/RUN_001",
        "--out",
        "submission",
    ]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == expect_code, proc.stderr + proc.stdout
    return proc


def _setup_fake_repo(tmp_path: Path, real_repo_root: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    (repo / "outputs" / "traces_official_112").mkdir(parents=True)
    (repo / "outputs" / "run_records" / "RUN_001").mkdir(parents=True)
    (repo / "outputs" / "official_results.jsonl").write_text('{"status":"success"}\n', encoding="utf-8")
    (repo / "outputs" / "official_evaluation_report.md").write_text("# report\n", encoding="utf-8")
    (repo / "outputs" / "traces_official_112" / "trace.json").write_text("{}", encoding="utf-8")
    (repo / "outputs" / "run_records" / "RUN_001" / "run.json").write_text("{}", encoding="utf-8")
    (repo / "system_overview.md").write_text("overview", encoding="utf-8")
    (repo / "replay.md").write_text("replay", encoding="utf-8")

    (repo / "scripts" / "check_project_safety.py").write_text(
        (real_repo_root / "scripts" / "check_project_safety.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (repo / "scripts" / "export_submission.py").write_text(
        (real_repo_root / "scripts" / "export_submission.py").read_text(encoding="utf-8"), encoding="utf-8"
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

    with zipfile.ZipFile(repo / "submission.zip") as zf:
        names = zf.namelist()
        assert "submission/result/final_output.jsonl" in names


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
    (repo / "outputs" / "traces_official_112" / "__pycache__" / "x.pyc").write_bytes(b"x")

    _run_export(real_repo_root, repo)
    with zipfile.ZipFile(repo / "submission.zip") as zf:
        zipped = "\n".join(zf.namelist())
        assert ".env" not in zipped
        assert ".git" not in zipped
        assert "__pycache__" not in zipped


def test_sensitive_content_fails_without_echoing_secret(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    (repo / "scripts" / "leak.py").write_text("Authorization: Bearer NEVER_PRINT_SECRET_123456", encoding="utf-8")

    proc = _run_export(real_repo_root, repo, expect_code=3)
    assert "high-risk sensitive content" in proc.stderr
    assert "NEVER_PRINT_SECRET_123456" not in proc.stderr


def test_readme_generated_when_report_missing(tmp_path: Path):
    real_repo_root = Path(__file__).resolve().parents[1]
    repo = _setup_fake_repo(tmp_path, real_repo_root)
    (repo / "outputs" / "official_evaluation_report.md").unlink()

    proc = _run_export(real_repo_root, repo)
    assert "WARNING: report not found" in proc.stderr
    readme = (repo / "submission" / "docs" / "README_SUBMISSION.md").read_text(encoding="utf-8")
    assert "report 包含状态：missing" in readme
