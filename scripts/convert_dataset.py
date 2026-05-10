from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_records(input_path: Path) -> list[dict]:
    suffix = input_path.suffix.lower()
    if suffix == ".jsonl":
        return _read_jsonl(input_path)
    if suffix == ".json":
        return _read_json(input_path)
    if suffix == ".txt":
        return _read_txt(input_path)
    raise ValueError(f"Unsupported input file type: {suffix}. Expected .jsonl, .json, or .txt")


def _read_jsonl(input_path: Path) -> list[dict]:
    records: list[dict] = []
    for idx, raw_line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at line {idx}: {exc.msg}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"Invalid JSONL at line {idx}: each line must be a JSON object")
        records.append(obj)
    return records


def _read_json(input_path: Path) -> list[dict]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file: {exc.msg}") from exc
    if not isinstance(payload, list):
        raise ValueError("Invalid JSON file: root must be a list of objects")
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid JSON file: item {idx} is not an object")
    return payload


def _read_txt(input_path: Path) -> list[dict]:
    content = input_path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in content.split("\n\n")]
    return [{"question": block} for block in blocks]


def _normalize(records: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    generated_index = 1
    for record in records:
        raw_question = record.get("question")
        if raw_question is None:
            raw_question = record.get("problem")
        question = str(raw_question).strip() if raw_question is not None else ""
        if not question:
            continue

        raw_qid = record.get("question_id")
        if raw_qid is None:
            raw_qid = record.get("id")

        if raw_qid is None or str(raw_qid).strip() == "":
            question_id = f"official_{generated_index:03d}"
            generated_index += 1
        else:
            question_id = str(raw_qid)

        normalized.append({"question_id": question_id, "question": question})
    return normalized


def convert_dataset(input_path: Path, output_path: Path) -> int:
    records = _read_records(input_path)
    normalized = _normalize(records)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for item in normalized:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(normalized)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert official datasets to standardized JSONL")
    parser.add_argument("--input", required=True, help="Path to input file (.jsonl/.json/.txt)")
    parser.add_argument("--output", default="data/official_questions.jsonl", help="Path to output JSONL")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        count = convert_dataset(Path(args.input), Path(args.output))
    except Exception as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")
    print(f"Converted {count} questions to {args.output}")


if __name__ == "__main__":
    main()
