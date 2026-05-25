from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence


def build_commands(
    skip_type_checks: bool,
    skip_slow: bool,
    no_cli_smoke: bool,
    include_shadow_eval: bool,
) -> list[list[str]]:
    commands: list[list[str]] = [
        ["ruff", "check", "."],
        ["black", "--check", "src", "scripts", "demo", "tests"],
        ["isort", "--check-only", "--diff", "src", "scripts", "demo", "tests"],
    ]

    if not skip_type_checks:
        commands.extend(
            [
                ["mypy", "src", "--show-error-codes"],
                ["pyright"],
            ]
        )

    commands.append(["python", "-m", "compileall", "src", "scripts", "demo", "tests"])

    if not skip_slow:
        commands.append(["python", "-m", "pytest", "-q"])

    if not no_cli_smoke:
        commands.append(
            [
                "python",
                "-m",
                "math_agent.cli",
                "solve",
                "--question",
                "计算 2+3",
                "--enable-tools",
                "--mode",
                "fast",
                "--no-trace",
            ]
        )

    if include_shadow_eval:
        commands.extend(
            [
                [
                    "python",
                    "scripts/shadow_eval.py",
                    "--mock",
                    "--limit",
                    "5",
                    "--out",
                    "outputs/shadow_eval_gate",
                ],
                [
                    "python",
                    "scripts/build_eval_report.py",
                    "--results",
                    "outputs/shadow_eval_gate/shadow_results.jsonl",
                    "--out-dir",
                    "outputs/shadow_eval_gate",
                ],
            ]
        )

    commands.append(["python", "scripts/check_project_safety.py"])
    return commands


def clean_pycache(root: Path) -> None:
    for pycache_dir in root.rglob("__pycache__"):
        if pycache_dir.is_dir():
            shutil.rmtree(pycache_dir)


def clean_pytest_cache(root: Path) -> None:
    pytest_cache = root / ".pytest_cache"
    if pytest_cache.exists():
        shutil.rmtree(pytest_cache)


def clean_traces(root: Path) -> None:
    traces_dir = root / "outputs" / "traces"
    if not traces_dir.exists():
        return

    for path in traces_dir.rglob("*"):
        if path.name == ".gitkeep":
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()

    for path in sorted(traces_dir.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def clean_shadow_eval_outputs(root: Path) -> None:
    for rel in ["outputs/shadow_eval_gate", "outputs/shadow_eval_test"]:
        target = root / rel
        if target.exists():
            shutil.rmtree(target)


def run_command(index: int, total: int, command: Sequence[str]) -> None:
    printable = " ".join(command)
    print(f"\n[{index}/{total}] Running: {printable}")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print(f"\nFAILED command: {printable}")
        print(f"Return code: {completed.returncode}")
        raise SystemExit(completed.returncode)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local regression quality gate.")
    parser.add_argument(
        "--skip-type-checks",
        action="store_true",
        help="Skip mypy and pyright checks.",
    )
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        help="Skip slow checks (pytest -q).",
    )
    parser.add_argument(
        "--no-cli-smoke",
        action="store_true",
        help="Skip CLI smoke test.",
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
    pre_cleanup_commands = commands[:-1]
    safety_command = commands[-1]

    for idx, command in enumerate(pre_cleanup_commands, start=1):
        run_command(idx, len(commands), command)

    print("\n=== Cleanup artifacts ===")
    clean_pytest_cache(root)
    clean_pycache(root)
    clean_traces(root)
    clean_shadow_eval_outputs(root)

    run_command(len(commands), len(commands), safety_command)

    elapsed = time.perf_counter() - start
    print(f"\nPASS: regression gate completed in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
