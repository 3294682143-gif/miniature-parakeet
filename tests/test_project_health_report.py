from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import scripts.project_health_report as phr


def _setup_repo(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".github/workflows").mkdir(parents=True, exist_ok=True)
    (tmp_path / "outputs/traces").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests/test_sample.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "scripts/run_regression_gate.py").write_text(
        "ruff check .\nblack --check\nisort --check-only --diff\nmypy\npyright\npytest\ncheck_project_safety.py\n--include-shadow-eval\npython scripts/shadow_eval.py --mock --limit 5 --out outputs/shadow_eval_gate\npython scripts/build_eval_report.py --results outputs/shadow_eval_gate/shadow_results.jsonl --out-dir outputs/shadow_eval_gate\n--no-trace\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts/shadow_eval.py").write_text("# mock\n", encoding="utf-8")
    (tmp_path / "scripts/build_eval_report.py").write_text("# mock\n", encoding="utf-8")
    (tmp_path / ".github/workflows/ci.yml").write_text(
        "ruff\nblack\nisort\nmypy\npyright\npytest\ncheck_project_safety.py\n--no-trace\n",
        encoding="utf-8",
    )
    (tmp_path / "outputs/traces/.gitkeep").write_text("", encoding="utf-8")
    return tmp_path


def test_script_exists() -> None:
    assert Path("scripts/project_health_report.py").is_file()


def test_help_runs() -> None:
    res = subprocess.run(
        [sys.executable, "scripts/project_health_report.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0


def test_markdown_contains_title(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    report = phr.build_report(root, collect_tests=False)
    md = phr.render_markdown(report)
    assert "Project Health Report" in md


def test_json_is_loadable(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    report = phr.build_report(root, collect_tests=False)
    blob = json.dumps(report)
    parsed = json.loads(blob)
    assert "score" in parsed


def test_no_collect_by_default(monkeypatch, tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    called = {"pytest_collect": False}

    def fake_run(cmd: list[str], timeout: int = 15, cwd: Path | None = None):
        if cmd[:4] == ["python", "-m", "pytest", "--collect-only"]:
            called["pytest_collect"] = True
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": ""}

    monkeypatch.setattr(phr, "run_cmd", fake_run)
    _ = phr.build_report(root, collect_tests=False)
    assert called["pytest_collect"] is False


def test_does_not_leak_env_content(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    (root / ".env").write_text("SECRET_TOKEN=abc123\n", encoding="utf-8")
    md = phr.render_markdown(phr.build_report(root, collect_tests=False))
    assert "abc123" not in md


def test_gitkeep_not_pollution(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    risks = phr.inspect_risks(root)
    assert risks["trace_files_exist"] is False


def test_fake_trace_is_pollution(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    (root / "outputs/traces/fake.json").write_text("{}", encoding="utf-8")
    risks = phr.inspect_risks(root)
    assert risks["trace_files_exist"] is True


def test_health_score_exists(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    report = phr.build_report(root, collect_tests=False)
    assert "health_score" in report["score"]


def test_binary_assets_count_as_zero_lines(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    assets = root / "assets"
    assets.mkdir()
    (assets / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
    report = phr.build_report(root, collect_tests=False)
    top_files = {
        row["file"].replace("\\", "/"): row["lines"]
        for row in report["size"]["top_files"]
    }
    assert top_files["assets/logo.png"] == 0
    assert report["size"]["lines_by_extension"][".png"] == 0


def test_ci_detect_present(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    ci = phr.inspect_ci(root)
    assert ci["ci_status"] == "present"


def test_gate_detect_present(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    ci = phr.inspect_ci(root)
    assert ci["local_regression_gate"] == "present"


def test_fail_on_risk_exit_nonzero(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    (root / ".env").write_text("SECRET=token\n", encoding="utf-8")
    res = subprocess.run(
        [
            sys.executable,
            "scripts/project_health_report.py",
            "--fail-on-risk",
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode != 0


def test_gate_no_real(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    ci = phr.inspect_ci(root)
    assert ci["gate_contains_real_flag"] is False
    assert ci["shadow_eval_gate"] == "supported"


def test_gate_detects_shadow_tokens(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    ci = phr.inspect_ci(root)
    assert ci["gate_contains"]["scripts/shadow_eval.py"] is True
    assert ci["gate_contains"]["scripts/build_eval_report.py"] is True
    assert ci["gate_contains"]["--include-shadow-eval"] is True
    assert ci["gate_contains"]["--mock"] is True
    assert ci["gate_contains"]["--no-trace"] is True
    assert ci["gate_contains_real_flag"] is False


def test_markdown_contains_shadow_eval_supported(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    md = phr.render_markdown(phr.build_report(root, collect_tests=False))
    assert "Shadow Eval Gate: supported" in md


def test_json_contains_shadow_eval_gate(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    report = phr.build_report(root, collect_tests=False)
    assert report["ci"]["shadow_eval_gate"] == "supported"


def test_assets_contains_hard_mode_control_key(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    report = phr.build_report(root, collect_tests=False)
    assert report["assets"]["hard_mode_control"] == "missing"


def test_gate_command_signature_detects_python_list_literals(tmp_path: Path) -> None:
    gate = tmp_path / "scripts" / "run_regression_gate.py"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(
        """
commands = [
    ["ruff", "check", "."],
    ["black", "--check", "src", "scripts", "demo", "tests"],
    ["isort", "--check-only", "src", "scripts", "demo", "tests"],
    ["mypy", "src", "--show-error-codes"],
    ["pyright"],
    ["python", "-m", "pytest", "-q"],
    ["python", "-m", "math_agent.cli", "solve", "--no-trace"],
    ["python", "scripts/check_project_safety.py"],
]
""",
        encoding="utf-8",
    )
    tokens = [
        "ruff check .",
        "black --check",
        "isort --check-only",
        "mypy",
        "pyright",
        "pytest",
        "check_project_safety.py",
        "--no-trace",
    ]
    found = phr._contains_command_signatures(gate, tokens)
    assert all(found.values())


def test_no_token_printed(tmp_path: Path) -> None:
    root = _setup_repo(tmp_path)
    (root / ".env").write_text("OPENAI_API_KEY=supersecret\n", encoding="utf-8")
    output = phr.render_markdown(phr.build_report(root, collect_tests=False))
    assert "supersecret" not in output
