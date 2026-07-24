from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
REQUIRED_TRACKED_DELIVERY_PATHS = (
    "docs/security_audit_2026-07-11.md",
    "math_agent/__init__.py",
    "requirements-dev.lock",
    "requirements.lock",
    "requirements.txt",
    "scripts/_repo_bootstrap.py",
    "src/math_agent/clients/http_worker.py",
    "src/math_agent/io_utils.py",
    "src/math_agent/process_isolation.py",
    "src/math_agent/security.py",
    "src/math_agent/tools/safe_sympy.py",
    "src/math_agent/tools/sympy_worker.py",
    "tests/conftest.py",
    "tests/test_ci_supply_chain.py",
    "tests/test_io_utils.py",
    "tests/test_process_isolation.py",
    "tests/test_user_agent_submission.py",
    "user_agent.py",
)


def _logical_requirements(path: Path) -> list[str]:
    logical: list[str] = []
    current = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        current = f"{current} {line}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        logical.append(current)
        current = ""
    assert not current, f"unterminated requirement in {path.name}"
    return logical


def test_ci_uses_minimal_permissions_and_drops_checkout_credentials() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    assert re.search(r"(?m)^permissions:\s*\n\s{2}contents:\s*read\s*$", ci)
    assert re.search(
        r"uses:\s*actions/checkout@[0-9a-f]{40}.*?"
        r"with:\s*\n\s+persist-credentials:\s*false\s*$",
        ci,
        flags=re.MULTILINE | re.DOTALL,
    )


def test_ci_actions_are_pinned_to_immutable_commits() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    action_refs = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", ci)
    assert action_refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)


def test_ci_installs_hashed_dev_lock_without_resolving_project_deps() -> None:
    ci = CI_PATH.read_text(encoding="utf-8")
    assert "python -m pip install --require-hashes -r requirements-dev.lock" in ci
    assert "python -m pip install --no-deps --no-build-isolation -e ." in ci
    assert "pip install -e .[dev]" not in ci
    assert "pip install --upgrade pip" not in ci


def test_runtime_and_dev_lock_files_pin_and_hash_every_requirement() -> None:
    for name in ("requirements.lock", "requirements-dev.lock"):
        path = ROOT / name
        assert path.is_file(), f"missing {name}"
        requirements = _logical_requirements(path)
        assert requirements, f"empty {name}"
        for requirement in requirements:
            assert "==" in requirement, f"un-pinned entry in {name}: {requirement}"
            assert (
                "--hash=sha256:" in requirement
            ), f"unhashed entry in {name}: {requirement}"


def test_dev_lock_includes_local_editable_build_dependencies() -> None:
    requirements = _logical_requirements(ROOT / "requirements-dev.lock")
    names = {requirement.split("==", 1)[0].lower() for requirement in requirements}
    assert {"setuptools", "wheel"}.issubset(names)


def test_legacy_requirements_file_delegates_to_runtime_lock() -> None:
    lines = _logical_requirements(ROOT / "requirements.txt")
    assert lines == ["-r requirements.lock"]


def test_critical_delivery_files_are_present_in_the_git_index() -> None:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            "--",
            *REQUIRED_TRACKED_DELIVERY_PATHS,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, (
        "critical delivery files are still untracked; add every path in "
        "REQUIRED_TRACKED_DELIVERY_PATHS before submission"
    )
