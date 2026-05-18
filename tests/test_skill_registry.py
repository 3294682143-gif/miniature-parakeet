from pathlib import Path

from math_agent.harness.skill_registry import SkillRegistry


def test_list_skills_contains_required() -> None:
    registry = SkillRegistry(root="skills")
    names = set(registry.list_skills())
    required = {
        "proof",
        "equation",
        "calculation",
        "calculus",
        "probability",
        "geometry",
        "matrix",
        "optimization",
        "formatter",
        "verifier",
    }
    assert required.issubset(names)


def test_load_skill_success() -> None:
    registry = SkillRegistry(root="skills")
    proof = registry.load_skill("proof")
    equation = registry.load_skill("equation")
    assert proof["name"] == "proof"
    assert "applies_to" in proof
    assert equation["name"] == "equation"


def test_select_skill_routing() -> None:
    registry = SkillRegistry(root="skills")
    assert registry.select_skill(question="请证明该命题成立") == "proof"
    assert registry.select_skill(question="Solve equation x^2-1=0") == "equation"
    assert registry.select_skill(question="计算 3*7+2") == "calculation"


def test_unknown_question_no_crash() -> None:
    registry = SkillRegistry(root="skills")
    result = registry.select_skill(question="Tell me something interesting")
    assert result in {None, "general"}


def test_safe_load_missing_no_crash(tmp_path: Path) -> None:
    registry = SkillRegistry(root=str(tmp_path / "skills"))
    assert registry.safe_load_skill("proof") is None


def test_parse_skill_metadata_name_applies_to() -> None:
    registry = SkillRegistry(root="skills")
    text = """name: demo\napplies_to: x,y\nprocedure:\n  1. step\n"""
    meta = registry.parse_skill_metadata(text)
    assert meta["name"] == "demo"
    assert meta["applies_to"] == "x,y"
