from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, Sequence

if __package__ in {None, ""}:
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    sys.path.insert(1, str(_REPO_ROOT))

from scripts.clean_transient_artifacts import clean_transient_artifacts

DEV_TOOL_HINT = (
    "Missing local quality tool '{tool}'. Install development tools with "
    "`python -m pip install -e .[dev] ruff black isort mypy pyright`, "
    "or run the GitHub Actions quality-gates workflow."
)

DEV_TOOL_MODULES = {
    "ruff": "ruff",
    "black": "black",
    "isort": "isort",
    "mypy": "mypy",
    "pyright": "pyright",
}
PROVENANCE_CHECK = (
    "from pathlib import Path; import math_agent.cli as module; "
    "source=(Path.cwd()/'src').resolve(); loaded=Path(module.__file__).resolve(); "
    "assert loaded.is_relative_to(source), 'math_agent was not loaded from this checkout'; "
    "print('source_provenance=PASS')"
)


def py_cmd(*args: str) -> list[str]:
    return [sys.executable, *args]


def quality_tool_cmd(tool: str, *args: str) -> list[str]:
    module = DEV_TOOL_MODULES.get(tool, tool)
    if importlib.util.find_spec(module) is not None:
        return py_cmd("-m", module, *args)
    if shutil.which(tool) is not None:
        return [tool, *args]
    return [tool, *args]


def bundled_node_bin() -> Path | None:
    dependencies = Path(sys.executable).resolve().parent.parent
    node_bin = dependencies / "node" / "bin"
    return node_bin if (node_bin / "node.exe").exists() else None


def gate_temp_dir() -> Path | None:
    temp_root = Path(tempfile.gettempdir()) / "math-agent-regression-gate"
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return temp_root


def command_env(command: Sequence[str]) -> dict[str, str] | None:
    env: dict[str, str] | None = None
    if command and command[0] == sys.executable:
        env = os.environ.copy()
        source_root = str(Path(__file__).resolve().parent.parent / "src")
        existing = env.get("PYTHONPATH", "")
        entries = [entry for entry in existing.split(os.pathsep) if entry]
        entries = [
            entry
            for entry in entries
            if os.path.normcase(os.path.abspath(entry))
            != os.path.normcase(os.path.abspath(source_root))
        ]
        env["PYTHONPATH"] = os.pathsep.join([source_root, *entries])
    is_python_module = len(command) >= 3 and command[0] == sys.executable
    is_pyright = is_python_module and command[1:3] == ["-m", "pyright"]
    is_pytest = is_python_module and command[1:3] == ["-m", "pytest"]

    if is_pyright:
        node_bin = bundled_node_bin()
        if node_bin is not None:
            env = env or os.environ.copy()
            env["PATH"] = str(node_bin) + os.pathsep + env.get("PATH", "")

    if is_pytest:
        temp_dir = gate_temp_dir()
        if temp_dir is not None:
            env = env or os.environ.copy()
            env["TEMP"] = str(temp_dir)
            env["TMP"] = str(temp_dir)

    return env


def build_commands(
    skip_type_checks: bool,
    skip_slow: bool,
    no_cli_smoke: bool,
    include_shadow_eval: bool,
) -> list[list[str]]:
    commands: list[list[str]] = [
        py_cmd("-c", PROVENANCE_CHECK),
        quality_tool_cmd("ruff", "check", "."),
        quality_tool_cmd("black", "--check", "src", "scripts", "demo", "tests"),
        quality_tool_cmd(
            "isort", "--check-only", "--diff", "src", "scripts", "demo", "tests"
        ),
    ]

    if not skip_type_checks:
        commands.extend(
            [
                quality_tool_cmd("mypy", "src", "--show-error-codes"),
                quality_tool_cmd("pyright", "--pythonpath", sys.executable),
            ]
        )

    commands.append(py_cmd("-m", "compileall", "src", "scripts", "demo", "tests"))

    if not skip_slow:
        commands.append(py_cmd("-m", "pytest", "-q"))

    if include_shadow_eval:
        commands.extend(
            [
                py_cmd(
                    "scripts/shadow_eval.py",
                    "--mock",
                    "--limit",
                    "5",
                    "--out",
                    "outputs/shadow_eval_gate",
                ),
                py_cmd(
                    "scripts/build_eval_report.py",
                    "--results",
                    "outputs/shadow_eval_gate/shadow_results.jsonl",
                    "--out-dir",
                    "outputs/shadow_eval_gate",
                ),
            ]
        )

    if not no_cli_smoke:
        commands.append(
            py_cmd(
                "-m",
                "math_agent.cli",
                "solve",
                "--question",
                "计算 2+3",
                "--enable-tools",
                "--mode",
                "fast",
                "--no-trace",
                "--fail-on-non-success",
            )
        )

    commands.append(py_cmd("scripts/check_project_safety.py"))
    commands.append(["git", "status", "--short"])
    return commands


def run_command(index: int, total: int, command: Sequence[str]) -> None:
    printable = " ".join(command)
    print(f"\n[{index}/{total}] Running: {printable}")
    executable = str(command[0])
    if executable != sys.executable and shutil.which(executable) is None:
        print(DEV_TOOL_HINT.format(tool=executable))
        raise SystemExit(127)
    try:
        completed = subprocess.run(command, check=False, env=command_env(command))
    except FileNotFoundError as exc:
        tool = str(exc.filename or executable)
        print(DEV_TOOL_HINT.format(tool=tool))
        raise SystemExit(127) from exc
    if completed.returncode != 0:
        print(f"\nFAILED command: {printable}")
        print(f"Return code: {completed.returncode}")
        raise SystemExit(completed.returncode)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local regression quality gate.")
    parser.add_argument(
        "--skip-type-checks", action="store_true", help="Skip mypy and pyright checks."
    )
    parser.add_argument(
        "--skip-slow", action="store_true", help="Skip slow checks (pytest -q)."
    )
    parser.add_argument(
        "--no-cli-smoke", action="store_true", help="Skip CLI smoke test."
    )
    parser.add_argument(
        "--include-shadow-eval",
        action="store_true",
        help="Run optional mock shadow eval smoke + report gate.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent

    start = time.perf_counter()
    commands = build_commands(
        skip_type_checks=args.skip_type_checks,
        skip_slow=args.skip_slow,
        no_cli_smoke=args.no_cli_smoke,
        include_shadow_eval=args.include_shadow_eval,
    )

    print("=== Local Regression Gate ===")
    safety_command = py_cmd("scripts/check_project_safety.py")
    for idx, command in enumerate(commands, start=1):
        if command == safety_command:
            print("\n=== Cleanup artifacts ===")
            clean_transient_artifacts(root=root, dry_run=False, quiet=False)
        run_command(idx, len(commands), command)

    elapsed = time.perf_counter() - start
    print(f"\nPASS: regression gate completed in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
