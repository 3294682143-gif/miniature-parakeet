from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.clean_transient_artifacts import clean_transient_artifacts


def build_commands(
    input_path: str,
    out_dir: str,
    dry_run_limit: int,
) -> list[list[str]]:
    python = sys.executable
    return [
        [python, "-m", "pytest", "-q"],
        [
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
        ],
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
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    commands = build_commands(
        input_path=args.input,
        out_dir=args.out_dir,
        dry_run_limit=args.dry_run_limit,
    )
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
