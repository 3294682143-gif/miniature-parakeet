from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import solve_question
from .schemas import MathQuestion, make_failure_result


def cmd_solve(args: argparse.Namespace) -> int:
    result = solve_question(
        MathQuestion(question=args.question, question_id=args.question_id),
        mock=not args.real,
        save_trace=not args.no_trace,
        trace_dir=args.trace_dir,
    )
    print(result.model_dump_json(ensure_ascii=False))
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as fin, output_path.open("w", encoding="utf-8") as fout:
        for idx, line in enumerate(fin):
            if not line.strip():
                continue
            raw = {}
            try:
                raw = json.loads(line)
                q = MathQuestion.model_validate(raw)
                result = solve_question(q, mock=not args.real, save_trace=not args.no_trace, trace_dir=args.trace_dir)
            except Exception as exc:
                question_id = f"line_{idx}"
                question = ""
                if isinstance(raw, dict):
                    question_id = str(raw.get("question_id", question_id))
                    question = str(raw.get("question", ""))
                result = make_failure_result(question_id=question_id, question=question, error_message=str(exc))
            fout.write(result.model_dump_json(ensure_ascii=False) + "\n")
    print(str(output_path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="math_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    solve_p = sub.add_parser("solve")
    solve_p.add_argument("--question", required=True)
    solve_p.add_argument("--question-id", default="cli_q")
    solve_p.add_argument("--real", action="store_true", default=False)
    solve_p.add_argument("--trace-dir", default="outputs/traces")
    solve_p.add_argument("--no-trace", action="store_true", default=False)
    solve_p.set_defaults(func=cmd_solve)

    batch_p = sub.add_parser("batch")
    batch_p.add_argument("--input", required=True)
    batch_p.add_argument("--output", required=True)
    batch_p.add_argument("--real", action="store_true", default=False)
    batch_p.add_argument("--trace-dir", default="outputs/traces")
    batch_p.add_argument("--no-trace", action="store_true", default=False)
    batch_p.set_defaults(func=cmd_batch)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
