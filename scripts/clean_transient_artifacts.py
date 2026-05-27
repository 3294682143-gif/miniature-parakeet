from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TRANSIENT_OUTPUT_DIRS: tuple[str, ...] = (
    "outputs/full_system_audit",
    "outputs/literature_traceability",
    "outputs/demo_pack",
    "outputs/demo_pack_test",
    "outputs/shadow_eval_gate",
    "outputs/shadow_eval_test",
    "outputs/debug_shadow",
    "outputs/debug_shadow_test",
    "outputs/hard_mode_ablation",
    "outputs/hard_mode_ablation_test",
    "outputs/proof_guardian_demo",
    "outputs/proof_guardian_demo_test",
    "outputs/official_dry_run",
    "outputs/official_dry_run_test",
)


@dataclass(frozen=True)
class CleanupStats:
    cleaned_count: int
    skipped_count: int
    dry_run: bool


def _remove_path(path: Path, dry_run: bool) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if dry_run:
        return True
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    return True


def clean_transient_artifacts(
    root: Path, dry_run: bool = False, quiet: bool = False
) -> CleanupStats:
    cleaned_count = 0
    skipped_count = 0

    pytest_cache = root / ".pytest_cache"
    if _remove_path(pytest_cache, dry_run=dry_run):
        cleaned_count += 1
        if not quiet:
            print(f"CLEAN: {pytest_cache}")
    else:
        skipped_count += 1

    for pycache in sorted(path for path in root.rglob("__pycache__") if path.is_dir()):
        if _remove_path(pycache, dry_run=dry_run):
            cleaned_count += 1
            if not quiet:
                print(f"CLEAN: {pycache}")

    traces_dir = root / "outputs" / "traces"
    if traces_dir.exists():
        for path in sorted(traces_dir.rglob("*")):
            if path.name == ".gitkeep":
                skipped_count += 1
                continue
            if path.is_file() or path.is_symlink():
                if _remove_path(path, dry_run=dry_run):
                    cleaned_count += 1
                    if not quiet:
                        print(f"CLEAN: {path}")

        for path in sorted(traces_dir.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                if _remove_path(path, dry_run=dry_run):
                    cleaned_count += 1
                    if not quiet:
                        print(f"CLEAN: {path}")

    for rel in TRANSIENT_OUTPUT_DIRS:
        target = root / rel
        if _remove_path(target, dry_run=dry_run):
            cleaned_count += 1
            if not quiet:
                print(f"CLEAN: {target}")
        else:
            skipped_count += 1

    if not quiet:
        print("KEEP: outputs/.gitkeep and outputs/traces/.gitkeep are preserved")

    print(f"cleaned_count={cleaned_count}")
    print(f"skipped_count={skipped_count}")
    print(f"dry_run={dry_run}")

    return CleanupStats(
        cleaned_count=cleaned_count, skipped_count=skipped_count, dry_run=dry_run
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean transient artifacts before safety checks."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show paths that would be deleted."
    )
    parser.add_argument("--quiet", action="store_true", help="Reduce per-path output.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root path (default: project root).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    clean_transient_artifacts(
        root=args.root.resolve(), dry_run=args.dry_run, quiet=args.quiet
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
