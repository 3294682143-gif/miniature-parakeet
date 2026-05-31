from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import full_system_audit as fsa


def test_registry_exists_and_categories() -> None:
    assert isinstance(fsa.FUNCTION_AUDIT_REGISTRY, list)
    assert set("ABCDEFGHIJKLMNOPQRSTUVWX").issubset(
        {x["category"] for x in fsa.FUNCTION_AUDIT_REGISTRY}
    )


def test_registry_required_fields() -> None:
    for item in fsa.FUNCTION_AUDIT_REGISTRY:
        assert set(fsa.REQUIRED_FIELDS).issubset(item.keys())


def test_binary_assets_do_not_inflate_line_count(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('ok')\n", encoding="utf-8")
    counts = fsa.count_lines(tmp_path)
    assert counts["total_code_lines"] == 1
    assert counts["by_module"]["assets"] == 0


def test_fail_on_risk_treats_skipped_checks_as_risk() -> None:
    quality = [fsa.CheckResult("ruff", ["ruff"], 127, "SKIPPED", "command not found")]
    smoke = [fsa.CheckResult("smoke", ["python"], 0, "PASS", "ok")]
    assert fsa.has_gate_risk(quality, smoke) is True


def test_skip_slow_outputs_and_constraints(tmp_path: Path) -> None:
    out = tmp_path / "audit"
    result = subprocess.run(
        [
            "python",
            "scripts/full_system_audit.py",
            "--skip-slow",
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0

    inv_json = json.loads((out / "function_inventory.json").read_text(encoding="utf-8"))
    assert isinstance(inv_json, list)
    assert all("--real" not in " ".join(x.get("smoke_command", [])) for x in inv_json)

    inv_md = (out / "function_inventory.md").read_text(encoding="utf-8")
    by_cat = (out / "function_inventory_by_category.md").read_text(encoding="utf-8")
    report = (out / "full_system_audit_report.md").read_text(encoding="utf-8")

    assert "A. Stable Core" in inv_md
    assert "X. Full System Audit" in by_cat
    assert "This is NOT official evaluation." in report
    assert not (out / "official_results.jsonl").exists()

    all_text = "\n".join(
        (out / name).read_text(encoding="utf-8")
        for name in [
            "full_system_audit_report.md",
            "function_inventory.md",
            "function_inventory_by_category.md",
        ]
    )
    for banned in ["API_KEY=", "sk-", "OPENAI_API_KEY="]:
        assert banned not in all_text


def test_no_shell_true_or_env_read() -> None:
    text = Path("scripts/full_system_audit.py").read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert ".env" not in text or 'read_text(".env"' not in text


def test_readme_sections_and_ci_statement_consistent() -> None:
    r = Path("README.md").read_text(encoding="utf-8")
    assert "Repository Structure" in r
    assert "Line Count Summary" in r
    assert "Current Limitations" in r
    ci_exists = Path(".github/workflows/ci.yml").exists()
    if ci_exists:
        assert "workflow file present" in r
    else:
        assert "planned GitHub Actions" in r or "intended" in r
