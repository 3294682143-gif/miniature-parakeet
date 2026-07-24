from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from math_agent.io_utils import (
    iter_bounded_utf8_lines,
    load_bounded_jsonl,
    path_is_within,
    paths_alias,
)


def test_bounded_jsonl_rejects_long_lines_and_too_many_rows(tmp_path: Path) -> None:
    source = tmp_path / "data.jsonl"
    source.write_text(json.dumps({"value": "x" * 100}), encoding="utf-8")

    with pytest.raises(ValueError, match="line"):
        load_bounded_jsonl(source, max_line_bytes=64)

    source.write_text("{}\n{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row"):
        load_bounded_jsonl(source, max_rows=1)


def test_bounded_jsonl_rejects_nonfinite_and_parent_links(tmp_path: Path) -> None:
    source = tmp_path / "data.jsonl"
    source.write_text('{"value": NaN}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSONL"):
        load_bounded_jsonl(source)

    target = tmp_path / "target"
    target.mkdir()
    (target / "data.jsonl").write_text("{}\n", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable")
    with pytest.raises(ValueError, match="link or junction"):
        load_bounded_jsonl(link / "data.jsonl")


def test_bounded_jsonl_tolerates_only_syntax_errors_when_requested(
    tmp_path: Path,
) -> None:
    source = tmp_path / "data.jsonl"
    source.write_text("{}\n{bad}\n", encoding="utf-8")

    rows, invalid = load_bounded_jsonl(source, tolerate_invalid=True)

    assert rows == [{}]
    assert invalid == 1


def test_bounded_reader_checks_identity_when_consumer_closes_early(
    tmp_path: Path,
) -> None:
    source = tmp_path / "data.jsonl"
    source.write_text('{"value":1}\n{"value":2}\n', encoding="utf-8")
    reader = iter_bounded_utf8_lines(source)
    next(reader)
    original_stat = source.stat()
    source.write_text('{"value":3}\n{"value":4}\n', encoding="utf-8")
    os.utime(
        source,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )

    with pytest.raises(ValueError, match="changed"):
        reader.close()


def test_path_containment_is_component_aware(tmp_path: Path) -> None:
    output = tmp_path / "out"

    assert path_is_within(output / "traces" / "q.json", output)
    assert not path_is_within(tmp_path / "outside" / "q.json", output)


@pytest.mark.skipif(os.name != "nt", reason="Windows short names are platform-specific")
def test_windows_short_names_resolve_to_physical_paths() -> None:
    short = Path("C:/PROGRA~1")
    long = Path("C:/Program Files")
    if not short.exists() or not long.exists():
        pytest.skip("8.3 aliases are unavailable on this volume")

    assert paths_alias(short, long)
    assert path_is_within(short / "future-artifact.json", long)


def test_deeply_nested_json_is_rejected_without_recursion_escape(
    tmp_path: Path,
) -> None:
    source = tmp_path / "deep.jsonl"
    source.write_text("[" * 1_500 + "]" * 1_500 + "\n", encoding="utf-8")

    rows, invalid = load_bounded_jsonl(source, tolerate_invalid=True)

    assert rows == []
    assert invalid == 1


def test_bounded_json_rejects_duplicate_object_keys_at_any_depth(
    tmp_path: Path,
) -> None:
    source = tmp_path / "duplicates.jsonl"
    source.write_text(
        '{"outer":{"status":"fail","status":"success"}}\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="invalid JSONL"):
        load_bounded_jsonl(source)
