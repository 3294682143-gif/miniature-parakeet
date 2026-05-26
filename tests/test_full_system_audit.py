from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import full_system_audit as fsa


def test_script_exists() -> None:
    assert Path("scripts/full_system_audit.py").is_file()


def test_help_runs() -> None:
    result = subprocess.run(
        ["python", "scripts/full_system_audit.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_line_counter_no_cloc_tokei() -> None:
    text = Path("scripts/full_system_audit.py").read_text(encoding="utf-8")
    assert 'subprocess.run(["cloc"' not in text
    assert 'subprocess.run(["tokei"' not in text


def test_line_counter_counts_git_files_and_excludes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "src/a.py").write_text("a\n" * 3, encoding="utf-8")
    (tmp_path / "tests/test_a.py").write_text("t\n" * 2, encoding="utf-8")
    (tmp_path / "README.md").write_text("r\n" * 4, encoding="utf-8")
    (tmp_path / "outputs/skip.py").write_text("x\n" * 100, encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=False, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=False, capture_output=True)
    data = fsa.count_lines(tmp_path)
    assert data["total_tracked_lines"] >= 9
    assert data["by_extension"][".py"] == 5
    assert data["total_test_lines"] == 2


def test_skip_slow_run_and_reports(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = subprocess.run(
        [
            "python",
            "scripts/full_system_audit.py",
            "--skip-slow",
            "--out-dir",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    summary = json.loads(
        (out / "full_system_audit_summary.json").read_text(encoding="utf-8")
    )
    assert "total_code_lines" in summary["line_counts"]
    inv = (out / "function_inventory.md").read_text(encoding="utf-8")
    assert "Shadow Eval" in inv
    assert "Official-like Dry Run" in inv
    report = (out / "full_system_audit_report.md").read_text(encoding="utf-8")
    assert "NOT official evaluation" in report
    assert not (out / "official_results.jsonl").exists()


def test_no_shell_true_and_no_real_and_no_env_read() -> None:
    text = Path("scripts/full_system_audit.py").read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert "--real" not in text
    assert ".env" not in text
