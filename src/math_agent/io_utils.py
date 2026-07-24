from __future__ import annotations

import json
import os
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator

from .security import contains_non_finite_number, path_has_link_component

MAX_JSONL_BYTES = 16 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 64 * 1024
MAX_JSONL_ROWS = 100_000


class NonFiniteJSONError(ValueError):
    pass


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _bounded_descriptor_digest(descriptor: int, *, max_bytes: int) -> tuple[bytes, int]:
    """Fingerprint at most max_bytes + 1 bytes from an open regular file."""

    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = sha256()
    total = 0
    while total <= max_bytes:
        chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    return digest.digest(), total


def iter_bounded_utf8_lines(
    path: str | Path,
    *,
    max_bytes: int = MAX_JSONL_BYTES,
    max_line_bytes: int = MAX_JSONL_LINE_BYTES,
    max_rows: int = MAX_JSONL_ROWS,
    require_single_link: bool = False,
) -> Iterator[tuple[int, str]]:
    """Read a regular, link-free text file with hard byte and line limits."""

    if min(max_bytes, max_line_bytes, max_rows) < 1:
        raise ValueError("input limits must be positive")
    source = Path(path).absolute()
    if path_has_link_component(source):
        raise ValueError("input path contains a link or junction")
    try:
        pre_open = os.lstat(source)
    except OSError as exc:
        raise ValueError("unable to read bounded input") from exc
    if not stat.S_ISREG(pre_open.st_mode):
        raise ValueError("input must be a regular file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(source, flags)
        initial = os.fstat(descriptor)
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError("input must be a regular file")
        if not _same_file_identity(pre_open, initial):
            raise ValueError("input identity changed while opening")
        if require_single_link and initial.st_nlink != 1:
            raise ValueError("input must be a single-link regular file")
        if initial.st_size > max_bytes:
            raise ValueError("input exceeds the total byte limit")
        path_stat = os.stat(source, follow_symlinks=False)
        if not _same_file_identity(initial, path_stat):
            raise ValueError("input identity changed while opening")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            initial_digest, fingerprinted_bytes = _bounded_descriptor_digest(
                handle.fileno(), max_bytes=max_bytes
            )
            fingerprinted = os.fstat(handle.fileno())
            fingerprinted_path = os.stat(source, follow_symlinks=False)
            if (
                path_has_link_component(source)
                or not _same_file_identity(initial, fingerprinted)
                or not _same_file_identity(initial, fingerprinted_path)
                or fingerprinted_bytes != initial.st_size
                or fingerprinted.st_size != initial.st_size
                or fingerprinted.st_mtime_ns != initial.st_mtime_ns
            ):
                raise ValueError("input changed while it was being fingerprinted")
            handle.seek(0)
            total = 0
            row_count = 0
            line_number = 0
            try:
                while True:
                    raw = handle.readline(max_line_bytes + 1)
                    if not raw:
                        break
                    line_number += 1
                    row_count += 1
                    total += len(raw)
                    if len(raw) > max_line_bytes:
                        raise ValueError("input line exceeds the byte limit")
                    if total > max_bytes:
                        raise ValueError("input exceeds the total byte limit")
                    if row_count > max_rows:
                        raise ValueError("input exceeds the row limit")
                    try:
                        yield line_number, raw.decode("utf-8", errors="strict")
                    except UnicodeError as exc:
                        raise ValueError("input is not valid UTF-8") from exc
            finally:
                final_digest, final_digest_bytes = _bounded_descriptor_digest(
                    handle.fileno(), max_bytes=max_bytes
                )
                final = os.fstat(handle.fileno())
                final_path = os.stat(source, follow_symlinks=False)
                if (
                    path_has_link_component(source)
                    or not _same_file_identity(initial, final)
                    or not _same_file_identity(initial, final_path)
                    or final_digest_bytes != initial.st_size
                    or final_digest != initial_digest
                    or initial.st_size != final.st_size
                    or initial.st_mtime_ns != final.st_mtime_ns
                ):
                    raise ValueError("input changed while it was being read")
    except OSError as exc:
        raise ValueError("unable to read bounded input") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _reject_json_constant(value: str) -> None:
    raise NonFiniteJSONError(f"non-finite JSON constant is not allowed: {value}")


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key is not allowed")
        value[key] = item
    return value


def strict_json_loads(text: str) -> Any:
    value = json.loads(
        text,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_json_pairs,
    )
    # ``parse_constant`` rejects the JavaScript spellings NaN/Infinity, but
    # Python's float parser can also overflow a valid JSON number such as
    # ``1e999`` to infinity.  Keep this primitive strict on its own so callers
    # cannot accidentally omit a second validation pass.
    if contains_non_finite_number(value):
        raise NonFiniteJSONError("non-finite JSON number is not allowed")
    return value


def load_bounded_jsonl(
    path: str | Path,
    *,
    tolerate_invalid: bool = False,
    require_objects: bool = False,
    max_bytes: int = MAX_JSONL_BYTES,
    max_line_bytes: int = MAX_JSONL_LINE_BYTES,
    max_rows: int = MAX_JSONL_ROWS,
    require_single_link: bool = False,
) -> tuple[list[Any], int]:
    rows: list[Any] = []
    invalid = 0
    for _, line in iter_bounded_utf8_lines(
        path,
        max_bytes=max_bytes,
        max_line_bytes=max_line_bytes,
        max_rows=max_rows,
        require_single_link=require_single_link,
    ):
        text = line.strip()
        if not text:
            continue
        try:
            value = strict_json_loads(text)
            if contains_non_finite_number(value):
                raise ValueError("non-finite numbers are not allowed")
            if require_objects and not isinstance(value, dict):
                raise ValueError("JSONL rows must be objects")
            rows.append(value)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            if not tolerate_invalid:
                raise ValueError("input contains an invalid JSONL row") from None
            invalid += 1
    return rows, invalid


def read_bounded_utf8_text(
    path: str | Path,
    *,
    max_bytes: int = MAX_JSONL_BYTES,
    max_line_bytes: int = MAX_JSONL_LINE_BYTES,
    max_rows: int = MAX_JSONL_ROWS,
) -> str:
    return "".join(
        line
        for _, line in iter_bounded_utf8_lines(
            path,
            max_bytes=max_bytes,
            max_line_bytes=max_line_bytes,
            max_rows=max_rows,
        )
    )


def load_bounded_json(
    path: str | Path,
    *,
    require_object: bool = False,
    max_bytes: int = MAX_JSONL_BYTES,
) -> Any:
    text = read_bounded_utf8_text(path, max_bytes=max_bytes)
    try:
        value = strict_json_loads(text)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise ValueError("input contains invalid JSON") from exc
    if contains_non_finite_number(value):
        raise ValueError("input contains non-finite numbers")
    if require_object and not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def paths_alias(left: str | Path, right: str | Path) -> bool:
    """Compare paths without requiring both leaves to exist."""

    try:
        left_path = Path(left).absolute().resolve(strict=False)
        right_path = Path(right).absolute().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return True
    if os.path.normcase(str(left_path)) == os.path.normcase(str(right_path)):
        return True
    try:
        return (
            left_path.exists()
            and right_path.exists()
            and left_path.samefile(right_path)
        )
    except OSError:
        return True


def path_is_within(path: str | Path, directory: str | Path) -> bool:
    try:
        candidate = os.path.normcase(str(Path(path).absolute().resolve(strict=False)))
        root = os.path.normcase(str(Path(directory).absolute().resolve(strict=False)))
        return os.path.commonpath([candidate, root]) == root
    except (OSError, RuntimeError, ValueError):
        return True
