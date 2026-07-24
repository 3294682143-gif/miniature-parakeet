from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from math_agent.evidence import (
    build_demo_cases,
    build_demo_evidence_pack,
    collect_evidence_sources,
    write_demo_evidence_pack,
)


def _mk_sources(root: Path) -> None:
    (root / "shadow").mkdir(parents=True)
    (root / "debugger").mkdir(parents=True)
    (root / "ablation").mkdir(parents=True)
    (root / "proof").mkdir(parents=True)
    (root / "dry").mkdir(parents=True)
    (root / "health").mkdir(parents=True)
    (root / "shadow" / "shadow_summary.json").write_text(
        json.dumps({"total": 2, "exact_match_count": 1}), encoding="utf-8"
    )
    (root / "debugger" / "failure_clusters.json").write_text(
        json.dumps([{"key": "wrong_answer", "count": 1}]), encoding="utf-8"
    )
    (root / "ablation" / "comparison.json").write_text(
        json.dumps({"levels": ["off", "strict"], "rows": [{"level": "strict"}]}),
        encoding="utf-8",
    )
    (root / "proof" / "proof_guardian_demo.json").write_text(
        json.dumps({"decision": {"status": "proof_complete"}}), encoding="utf-8"
    )
    (root / "dry" / "dry_run_summary.json").write_text(
        json.dumps({"run_id": "demo", "total": 2, "success_count": 2}), encoding="utf-8"
    )
    (root / "health" / "project_health_report.json").write_text(
        json.dumps({"git": {"branch": "x", "commit_short": "abc"}}), encoding="utf-8"
    )


def test_collect_missing_no_crash(tmp_path: Path) -> None:
    sources = collect_evidence_sources(shadow_dir=str(tmp_path / "none"))
    assert any(s.name == "shadow_eval" for s in sources)


def test_collect_reads_all_sources(tmp_path: Path) -> None:
    _mk_sources(tmp_path)
    sources = collect_evidence_sources(
        shadow_dir=str(tmp_path / "shadow"),
        debugger_dir=str(tmp_path / "debugger"),
        ablation_dir=str(tmp_path / "ablation"),
        proof_dir=str(tmp_path / "proof"),
        dry_run_dir=str(tmp_path / "dry"),
        project_health_json=str(tmp_path / "health" / "project_health_report.json"),
    )
    m = {s.name: s for s in sources}
    assert m["shadow_eval"].summary["total"] == 2
    assert m["agent_debugger"].summary["failure_clusters_count"] == 1
    assert m["hard_mode_ablation"].summary["levels"] == ["off", "strict"]
    assert (
        m["proof_guardian"].summary["proof_guardian_decision"]["status"]
        == "proof_complete"
    )
    assert m["official_dry_run"].summary["run_id"] == "demo"


def test_bad_json_records_parse_error(tmp_path: Path) -> None:
    d = tmp_path / "shadow"
    d.mkdir()
    (d / "shadow_summary.json").write_text("{bad", encoding="utf-8")
    src = next(
        s
        for s in collect_evidence_sources(shadow_dir=str(d))
        if s.name == "shadow_eval"
    )
    assert any("parse_error" in w for w in src.warnings)


def test_duplicate_json_keys_record_parse_error(tmp_path: Path) -> None:
    directory = tmp_path / "shadow"
    directory.mkdir()
    (directory / "shadow_summary.json").write_text(
        '{"total":1,"total":999}', encoding="utf-8"
    )

    source = next(
        item
        for item in collect_evidence_sources(shadow_dir=str(directory))
        if item.name == "shadow_eval"
    )

    assert source.summary["total"] is None
    assert any("parse_error" in warning for warning in source.warnings)


def test_build_and_write_pack(tmp_path: Path) -> None:
    _mk_sources(tmp_path)
    pack = build_demo_evidence_pack(
        shadow_dir=str(tmp_path / "shadow"),
        debugger_dir=str(tmp_path / "debugger"),
        ablation_dir=str(tmp_path / "ablation"),
        proof_dir=str(tmp_path / "proof"),
        dry_run_dir=str(tmp_path / "dry"),
        project_health_json=str(tmp_path / "health" / "project_health_report.json"),
    )
    assert pack.official_warning.startswith("This is NOT official evaluation")
    assert build_demo_cases(pack.sources)

    out = tmp_path / "out"
    write_demo_evidence_pack(pack, out)
    assert (out / "demo_index.md").is_file()
    assert (out / "demo_script.md").is_file()
    assert (out / "architecture_summary.md").is_file()
    assert (out / "evidence_summary.json").is_file()
    assert not (out / "official_results.jsonl").exists()
    assert "NOT official evaluation" in (out / "demo_index.md").read_text(
        encoding="utf-8"
    )
    assert (
        "official accuracy"
        not in (out / "demo_script.md").read_text(encoding="utf-8").lower()
    )
    json.loads((out / "evidence_summary.json").read_text(encoding="utf-8"))
    assert ".env" not in (out / "evidence_summary.json").read_text(encoding="utf-8")


def test_cli_help_and_run(tmp_path: Path) -> None:
    _mk_sources(tmp_path)
    help_run = subprocess.run(
        [sys.executable, "scripts/generate_demo_pack.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_run.returncode == 0

    out = tmp_path / "cli_out"
    run = subprocess.run(
        [
            sys.executable,
            "scripts/generate_demo_pack.py",
            "--shadow-dir",
            str(tmp_path / "shadow"),
            "--debugger-dir",
            str(tmp_path / "debugger"),
            "--ablation-dir",
            str(tmp_path / "ablation"),
            "--proof-dir",
            str(tmp_path / "proof"),
            "--dry-run-dir",
            str(tmp_path / "dry"),
            "--project-health-json",
            str(tmp_path / "health" / "project_health_report.json"),
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert "source_count=" in run.stdout


def test_cli_fail_on_missing_critical(tmp_path: Path) -> None:
    d = tmp_path / "shadow"
    d.mkdir()
    (d / "shadow_summary.json").write_text("{}", encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            "scripts/generate_demo_pack.py",
            "--shadow-dir",
            str(d),
            "--fail-on-missing-critical",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode != 0
