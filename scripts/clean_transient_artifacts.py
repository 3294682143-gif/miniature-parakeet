from __future__ import annotations

import argparse
import os
import shutil
import stat
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
    "outputs/pre_submit_official_style_dry_run",
    "outputs/real_api_sample_gate",
    "outputs/final_submission_report",
    "outputs/gate_environment",
    "outputs/benchmark_suite",
    "outputs/proof_manual_review_pack",
)

TRANSIENT_OUTPUT_FILES: tuple[str, ...] = ("outputs/project_health_report.json",)

TRANSIENT_LOCAL_DIRS: tuple[str, ...] = (
    ".mypy_cache",
    ".ruff_cache",
    ".pyright",
    "build",
    "src/interns1_math_agent.egg-info",
)


@dataclass(frozen=True)
class CleanupStats:
    cleaned_count: int
    skipped_count: int
    dry_run: bool


def _is_link_or_junction(path: Path) -> bool:
    try:
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()
    except OSError:
        return True


def _validate_cleanup_root(root: Path) -> Path:
    candidate = root.absolute()
    for component in (candidate, *candidate.parents):
        if _is_link_or_junction(component):
            raise ValueError("cleanup root contains a link or junction")
    candidate = candidate.resolve(strict=False)
    anchor = Path(candidate.anchor).resolve(strict=False)
    home = Path.home().resolve(strict=False)
    if candidate in {anchor, home}:
        raise ValueError("cleanup root is too broad")
    required = (
        candidate / "pyproject.toml",
        candidate / "scripts" / "clean_transient_artifacts.py",
        candidate / "src" / "math_agent",
    )
    if (
        not required[0].is_file()
        or not required[1].is_file()
        or not required[2].is_dir()
    ):
        raise ValueError("cleanup root does not match this project layout")
    return candidate


def _validate_target(root: Path, path: Path) -> None:
    candidate = path.absolute()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("cleanup target escapes the project root") from exc
    for component in (candidate.parent, *candidate.parent.parents):
        if component == root.parent:
            break
        if _is_link_or_junction(component):
            raise ValueError("cleanup target contains a linked parent")
    if path.exists() and (_is_link_or_junction(path) or os.path.ismount(path)):
        raise ValueError("cleanup target is a link, junction, or mount point")


def _validate_recursive_tree(root: Path, path: Path) -> None:
    if not path.is_dir():
        return
    for current, directory_names, file_names in os.walk(path, followlinks=False):
        current_path = Path(current)
        _validate_target(root, current_path)
        for name in [*directory_names, *file_names]:
            child = current_path / name
            if _is_link_or_junction(child) or os.path.ismount(child):
                raise ValueError(
                    "cleanup tree contains a link, junction, or mount point"
                )


def _remove_path(root: Path, path: Path, dry_run: bool) -> bool:
    _validate_target(root, path)
    if not path.exists() and not path.is_symlink():
        return False
    if dry_run:
        return True
    if path.is_dir() and not path.is_symlink():
        _validate_recursive_tree(root, path)

        def _clear_readonly(func, target, exc_info):
            try:
                os.chmod(target, stat.S_IWRITE)
                func(target)
            except Exception:
                raise exc_info[1]

        shutil.rmtree(path, onerror=_clear_readonly)
    else:
        try:
            os.chmod(path, stat.S_IWRITE)
        except OSError:
            pass
        path.unlink(missing_ok=True)
    return True


def clean_transient_artifacts(
    root: Path, dry_run: bool = False, quiet: bool = False
) -> CleanupStats:
    root = _validate_cleanup_root(root)
    cleaned_count = 0
    skipped_count = 0

    pytest_cache = root / ".pytest_cache"
    if _remove_path(root, pytest_cache, dry_run=dry_run):
        cleaned_count += 1
        if not quiet:
            print(f"CLEAN: {pytest_cache}")
    else:
        skipped_count += 1

    pycache_paths: list[Path] = []
    for current, directory_names, _ in os.walk(root, topdown=True, followlinks=False):
        safe_names: list[str] = []
        for name in directory_names:
            candidate = Path(current) / name
            if _is_link_or_junction(candidate) or os.path.ismount(candidate):
                continue
            if name == "__pycache__":
                pycache_paths.append(candidate)
            else:
                safe_names.append(name)
        directory_names[:] = safe_names
    for pycache in sorted(pycache_paths):
        if _remove_path(root, pycache, dry_run=dry_run):
            cleaned_count += 1
            if not quiet:
                print(f"CLEAN: {pycache}")

    for rel in TRANSIENT_LOCAL_DIRS:
        target = root / rel
        if _remove_path(root, target, dry_run=dry_run):
            cleaned_count += 1
            if not quiet:
                print(f"CLEAN: {target}")
        else:
            skipped_count += 1

    traces_dir = root / "outputs" / "traces"
    if traces_dir.exists():
        _validate_target(root, traces_dir)
        safe_directories: list[Path] = []
        for current, directory_names, file_names in os.walk(
            traces_dir, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            safe_names: list[str] = []
            for name in directory_names:
                candidate = current_path / name
                if _is_link_or_junction(candidate) or os.path.ismount(candidate):
                    skipped_count += 1
                    continue
                safe_names.append(name)
                safe_directories.append(candidate)
            directory_names[:] = safe_names
            for name in file_names:
                path = current_path / name
                if name == ".gitkeep":
                    skipped_count += 1
                    continue
                if _remove_path(root, path, dry_run=dry_run):
                    cleaned_count += 1
                    if not quiet:
                        print(f"CLEAN: {path}")

        for path in sorted(safe_directories, reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                if _remove_path(root, path, dry_run=dry_run):
                    cleaned_count += 1
                    if not quiet:
                        print(f"CLEAN: {path}")

    for rel in TRANSIENT_OUTPUT_DIRS:
        target = root / rel
        if _remove_path(root, target, dry_run=dry_run):
            cleaned_count += 1
            if not quiet:
                print(f"CLEAN: {target}")
        else:
            skipped_count += 1

    for rel in TRANSIENT_OUTPUT_FILES:
        target = root / rel
        if _remove_path(root, target, dry_run=dry_run):
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
        cleaned_count=cleaned_count,
        skipped_count=skipped_count,
        dry_run=dry_run,
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
    clean_transient_artifacts(root=args.root, dry_run=args.dry_run, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
