from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_scan_project():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_project_safety.py"
    spec = importlib.util.spec_from_file_location("check_project_safety", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.scan_project


scan_project = _load_scan_project()


def test_scan_clean_repo_passes(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("project", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert findings == []


def test_env_example_not_flagged(tmp_path: Path):
    (tmp_path / ".env.example").write_text("INTERNS1_API_KEY=placeholder", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert findings == []


def test_env_file_flagged(tmp_path: Path):
    (tmp_path / ".env").write_text("INTERNS1_API_KEY=abc", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert any(risk == "forbidden_env_file" for _, risk in findings)


def test_bearer_token_flagged(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    secret = "Bearer superSecretToken12345"
    (scripts_dir / "x.py").write_text(f"TOKEN = '{secret}'\n", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert any(path == "scripts/x.py" and risk == "suspected_auth_token" for path, risk in findings)


def test_outputs_jsonl_flagged(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "results.jsonl").write_text("{}\n", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert any(risk == "forbidden_outputs_jsonl" for _, risk in findings)


def test_pycache_flagged(tmp_path: Path):
    pycache = tmp_path / "src" / "__pycache__"
    pycache.mkdir(parents=True)
    findings = scan_project(tmp_path)
    assert any("__pycache__" in risk for _, risk in findings)


def test_no_secret_echo_in_findings(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    secret = "Bearer NEVER_PRINT_THIS_SECRET_12345"
    (scripts_dir / "leak.py").write_text(secret, encoding="utf-8")
    findings = scan_project(tmp_path)
    rendered = "\n".join(f"{risk}:{path}" for path, risk in findings)
    assert "NEVER_PRINT_THIS_SECRET_12345" not in rendered
