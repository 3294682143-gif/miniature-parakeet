from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.clean_transient_artifacts import clean_transient_artifacts


def _make_project_root(root: Path) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "math_agent").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (root / "scripts" / "clean_transient_artifacts.py").write_text(
        "# marker\n", encoding="utf-8"
    )


def test_script_exists() -> None:
    assert Path("scripts/clean_transient_artifacts.py").is_file()


def test_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/clean_transient_artifacts.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout


def test_dry_run_does_not_delete(tmp_path: Path) -> None:
    _make_project_root(tmp_path)
    traces = tmp_path / "outputs" / "traces"
    traces.mkdir(parents=True)
    fake = traces / "fake.json"
    fake.write_text("{}", encoding="utf-8")
    clean_transient_artifacts(tmp_path, dry_run=True, quiet=True)
    assert fake.exists()


def test_cleanup_artifacts_and_safety(tmp_path: Path) -> None:
    _make_project_root(tmp_path)
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".mypy_cache").mkdir()
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / "build").mkdir()
    egg_info = tmp_path / "src" / "interns1_math_agent.egg-info"
    egg_info.mkdir(parents=True)
    pycache = tmp_path / "src" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "x.pyc").write_text("x", encoding="utf-8")
    traces = tmp_path / "outputs" / "traces"
    traces.mkdir(parents=True)
    (traces / "fake.json").write_text("{}", encoding="utf-8")
    (traces / ".gitkeep").write_text("", encoding="utf-8")
    audit = tmp_path / "outputs" / "full_system_audit"
    audit.mkdir(parents=True)
    (audit / "tmp.txt").write_text("x", encoding="utf-8")
    gate_env = tmp_path / "outputs" / "gate_environment"
    gate_env.mkdir(parents=True)
    (gate_env / "tmp.txt").write_text("x", encoding="utf-8")
    health_report = tmp_path / "outputs" / "project_health_report.json"
    health_report.write_text("{}", encoding="utf-8")
    source_file = tmp_path / "src" / "keep.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("print('ok')\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("# keep\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("API_KEY=SHOULD_NOT_PRINT\n", encoding="utf-8")

    stats = clean_transient_artifacts(tmp_path, dry_run=False, quiet=True)
    stats2 = clean_transient_artifacts(tmp_path, dry_run=False, quiet=True)

    assert not (tmp_path / ".pytest_cache").exists()
    assert not (tmp_path / ".mypy_cache").exists()
    assert not (tmp_path / ".ruff_cache").exists()
    assert not (tmp_path / "build").exists()
    assert not egg_info.exists()
    assert not pycache.exists()
    assert not (traces / "fake.json").exists()
    assert (traces / ".gitkeep").exists()
    assert not audit.exists()
    assert not gate_env.exists()
    assert not health_report.exists()
    assert source_file.exists()
    assert readme.exists()
    assert stats.cleaned_count >= 4
    assert stats2.cleaned_count >= 0


def test_missing_paths_do_not_crash(tmp_path: Path) -> None:
    _make_project_root(tmp_path)
    clean_transient_artifacts(tmp_path, dry_run=False, quiet=True)


def test_cleanup_rejects_broad_or_unrecognized_roots(tmp_path: Path) -> None:
    try:
        clean_transient_artifacts(tmp_path, dry_run=False, quiet=True)
    except ValueError as exc:
        assert "project layout" in str(exc)
    else:
        raise AssertionError("expected an unrecognized cleanup root to be rejected")


def test_source_has_no_shell_true_or_env_read_or_secret_leak() -> None:
    source = Path("scripts/clean_transient_artifacts.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert ".env" not in source
    assert "token" not in source.lower()
    assert "api_key" not in source.lower()
    assert "secret" not in source.lower()
