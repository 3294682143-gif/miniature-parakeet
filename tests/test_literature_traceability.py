from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_script_exists() -> None:
    assert Path("scripts/check_literature_traceability.py").is_file()


def test_help_runs() -> None:
    p = subprocess.run(["python", "scripts/check_literature_traceability.py", "--help"], capture_output=True, text=True, check=False)
    assert p.returncode == 0


def test_script_static_constraints() -> None:
    text = Path("scripts/check_literature_traceability.py").read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert ".env" not in text
    assert "requests" not in text
    assert "urllib" not in text


def test_generate_outputs(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    p = subprocess.run(["python", "scripts/check_literature_traceability.py", "--out-dir", str(out_dir)], capture_output=True, text=True, check=False)
    assert p.returncode == 0

    inv = json.loads((out_dir / "reference_inventory.json").read_text(encoding="utf-8"))
    ids = {x["id"] for x in inv}
    for i in range(1, 9):
        assert f"[R{i}]" in ids

    matrix = json.loads((out_dir / "module_reference_matrix.json").read_text(encoding="utf-8"))
    names = {x["module"] for x in matrix}
    assert "Stable Core / Pipeline" in names
    assert "Proof Guardian" in names
    assert "Official-like Dry Run" in names

    assert (out_dir / "literature_traceability_report.md").is_file()
    summary = json.loads((out_dir / "literature_traceability_summary.json").read_text(encoding="utf-8"))
    assert "checks" in summary
    assert not (out_dir / "official_results.jsonl").exists()


def test_docs_and_readme_presence() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert ("Research Foundation" in readme) or ("Literature Traceability" in readme)
    assert "[R1]" in readme and "[R8]" in readme
    assert Path("docs/literature_traceability.md").is_file()
    assert Path("docs/reference_mapping.md").is_file()
