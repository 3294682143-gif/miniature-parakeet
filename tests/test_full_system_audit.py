from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import full_system_audit as fsa


def test_registry_exists_and_size() -> None:
    assert isinstance(fsa.FUNCTION_AUDIT_REGISTRY, list)
    assert len(fsa.FUNCTION_AUDIT_REGISTRY) >= 80


def test_registry_categories_cover_a_to_x() -> None:
    got = {x["category"] for x in fsa.FUNCTION_AUDIT_REGISTRY}
    exp = set("ABCDEFGHIJKLMNOPQRSTUVWX")
    assert exp.issubset(got)


def test_registry_required_fields() -> None:
    required = {"id", "name", "category", "status", "files", "risk_boundary"}
    for item in fsa.FUNCTION_AUDIT_REGISTRY:
        assert required.issubset(item.keys())


def test_present_files_exist_or_downgraded(tmp_path: Path) -> None:
    validated = fsa.validate_registry(Path("."))
    for item in validated:
        if item["status"] == "present":
            assert item["existing_files"]


def test_help_runs() -> None:
    result = subprocess.run(["python", "scripts/full_system_audit.py", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0


def test_skip_slow_and_outputs(tmp_path: Path) -> None:
    out = tmp_path / "audit"
    result = subprocess.run(["python", "scripts/full_system_audit.py", "--skip-slow", "--out-dir", str(out)], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    inv_json = json.loads((out / "function_inventory.json").read_text(encoding="utf-8"))
    assert isinstance(inv_json, list)
    md = (out / "function_inventory.md").read_text(encoding="utf-8")
    assert "Stable Core" in md
    assert "Proof" in md
    assert "Shadow Eval" in md
    assert "Official-like Dry Run" in md
    assert "Safety / Security" in md
    assert (out / "function_inventory_by_category.md").is_file()
    report = (out / "full_system_audit_report.md").read_text(encoding="utf-8")
    assert "Missing Optional Capabilities" in report
    assert not (out / "official_results.jsonl").exists()


def test_no_shell_true_or_env_token_leak() -> None:
    text = Path("scripts/full_system_audit.py").read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert 'read_text(".env"' not in text


def test_readme_sections_present() -> None:
    r = Path("README.md").read_text(encoding="utf-8")
    assert ("Full Function Inventory" in r) or ("Function Inventory Overview" in r)
    assert "P19 / P20" in r
