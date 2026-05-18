from __future__ import annotations

import json
from pathlib import Path

import yaml


REQUIRED_MANIFEST_FIELDS = {
    "change_id",
    "created_at",
    "target_component",
    "change_type",
    "paper_basis",
    "evidence",
    "root_cause",
    "proposed_change",
    "expected_fix",
    "expected_risk",
    "files_to_change",
    "validation_plan",
    "rollback_plan",
    "promotion_conditions",
    "decision",
    "notes",
}


def test_evolution_directory_exists() -> None:
    assert Path("evolution").is_dir()


def test_manifest_template_yaml_loadable_and_fields_complete() -> None:
    manifest_path = Path("evolution/manifests/change_manifest_template.yaml")
    loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    assert REQUIRED_MANIFEST_FIELDS.issubset(set(loaded.keys()))


def test_candidates_index_example_json_loadable_and_has_candidates() -> None:
    index_path = Path("evolution/candidates/index.example.json")
    loaded = json.loads(index_path.read_text(encoding="utf-8"))
    assert "candidates" in loaded
    assert isinstance(loaded["candidates"], list)


def test_evolution_design_exists() -> None:
    assert Path("docs/evolution_design.md").is_file()


def test_evolution_design_mentions_frozen_harness() -> None:
    content = Path("docs/evolution_design.md").read_text(encoding="utf-8")
    assert "Frozen Harness" in content


def test_evolution_design_forbids_online_self_modification() -> None:
    content = Path("docs/evolution_design.md").read_text(encoding="utf-8")
    assert ("online self-modification" in content) or ("在线自改" in content)


def test_evolution_design_forbids_manual_official_results_edit() -> None:
    content = Path("docs/evolution_design.md").read_text(encoding="utf-8")
    assert "official_results.jsonl" in content
    assert "禁止人工逐题修改" in content
