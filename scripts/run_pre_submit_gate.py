from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

if __package__ in {None, ""}:
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    sys.path.insert(1, str(_REPO_ROOT))

from math_agent.security import safe_exception_text
from scripts.clean_transient_artifacts import clean_transient_artifacts

PROVENANCE_CHECK = (
    "from pathlib import Path; import math_agent.cli as module; "
    "source=(Path.cwd()/'src').resolve(); loaded=Path(module.__file__).resolve(); "
    "assert loaded.is_relative_to(source), 'math_agent was not loaded from this checkout'; "
    "print('source_provenance=PASS')"
)


def build_commands(
    input_path: str,
    out_dir: str,
    dry_run_limit: int,
    require_mock_success: bool = False,
) -> list[list[str]]:
    if not 1 <= dry_run_limit <= 100_000:
        raise ValueError("dry_run_limit must be between 1 and 100000")
    python = sys.executable
    dry_run_command = [
        python,
        "scripts/run_official_dry_run.py",
        "--input",
        input_path,
        "--out-dir",
        out_dir,
        "--limit",
        str(dry_run_limit),
        "--enable-tools",
        "--mock",
        "--no-trace",
        "--fail-on-invalid",
        "--fail-on-missing-final",
    ]
    if require_mock_success:
        dry_run_command.append("--fail-on-non-success")
    return [
        [python, "-c", PROVENANCE_CHECK],
        [python, "-m", "pytest", "-q"],
        dry_run_command,
        [python, "scripts/check_project_safety.py"],
    ]


def run_command(index: int, total: int, command: Sequence[str]) -> None:
    printable = " ".join(command)
    print(f"\n[{index}/{total}] Running: {printable}")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print(f"\nFAILED command: {printable}")
        print(f"Return code: {completed.returncode}")
        raise SystemExit(completed.returncode)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run final pre-submit gates: pytest, official-style dry run, safety scan."
        )
    )
    parser.add_argument("--input", default="data/official_style_18domain_112.jsonl")
    parser.add_argument(
        "--out-dir",
        default="outputs/pre_submit_official_style_dry_run",
    )
    parser.add_argument("--dry-run-limit", type=int, default=18)
    parser.add_argument(
        "--require-mock-success",
        action="store_true",
        help=(
            "Also fail on partial mock answers. Use only with a deterministic "
            "mock-solvable input set; the default official-style gate is structural."
        ),
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    try:
        commands = build_commands(
            input_path=args.input,
            out_dir=args.out_dir,
            dry_run_limit=args.dry_run_limit,
            require_mock_success=args.require_mock_success,
        )
    except ValueError as exc:
        print(safe_exception_text(exc), file=sys.stderr)
        return 2
    start = time.perf_counter()
    print("=== Final Pre-submit Gate ===")
    for idx, command in enumerate(commands, start=1):
        if command[-1] == "scripts/check_project_safety.py":
            print("\n=== Cleanup artifacts before safety scan ===")
            clean_transient_artifacts(root=root, dry_run=False, quiet=False)
        run_command(idx, len(commands), command)
    print(f"\nPASS: pre-submit gate completed in {time.perf_counter() - start:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
