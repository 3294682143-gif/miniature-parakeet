from pathlib import Path

import pytest

from math_agent.prompting import get_prompt, load_prompts, render_prompt


REQUIRED_KEYS = {
    "router_system",
    "planner_system",
    "solver_system",
    "program_solver_system",
    "proof_solver_system",
    "verifier_system",
    "refiner_system",
    "explainer_system",
    "formatter_system",
}


def test_load_prompts_from_config() -> None:
    prompts = load_prompts(Path("configs/prompts.yaml"))
    assert isinstance(prompts, dict)


def test_required_prompt_keys_exist() -> None:
    prompts = load_prompts("configs/prompts.yaml")
    missing = REQUIRED_KEYS - set(prompts.keys())
    assert not missing


def test_get_prompt_router_system() -> None:
    prompts = load_prompts("configs/prompts.yaml")
    router_prompt = get_prompt(prompts, "router_system")
    assert isinstance(router_prompt, str)
    assert router_prompt.strip()


def test_get_prompt_missing_key_raises() -> None:
    prompts = load_prompts("configs/prompts.yaml")
    with pytest.raises(KeyError):
        get_prompt(prompts, "missing_key")


def test_render_prompt_replaces_variables() -> None:
    template = "Q: {question}; Plan: {plan}; Route: {route_info}; Answer: {final_answer}"
    rendered = render_prompt(
        template,
        question="1+1=?",
        plan="compute directly",
        route_info="arithmetic",
        final_answer="2",
    )
    assert "1+1=?" in rendered
    assert "compute directly" in rendered
    assert "arithmetic" in rendered
    assert "2" in rendered


def test_render_prompt_missing_variable_raises() -> None:
    with pytest.raises(KeyError):
        render_prompt("Q: {question}; Plan: {plan}", question="test")


def test_all_prompt_values_not_empty() -> None:
    prompts = load_prompts("configs/prompts.yaml")
    for key in REQUIRED_KEYS:
        prompt = get_prompt(prompts, key)
        assert prompt.strip(), f"Prompt {key} should not be empty"


def test_load_prompts_missing_path_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompts("configs/not_exists_prompts.yaml")


def test_load_prompts_invalid_yaml_raises(tmp_path: Path) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("router_system: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError):
        load_prompts(bad_yaml)
