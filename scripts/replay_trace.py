from __future__ import annotations

import argparse
from pathlib import Path

from math_agent.harness.replay import render_replay_markdown
from math_agent.harness.trace_reader import read_trace, read_trace_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace")
    parser.add_argument("--trace-dir")
    parser.add_argument("--out")
    args = parser.parse_args()

    if bool(args.trace) == bool(args.trace_dir):
        raise SystemExit("exactly one of --trace or --trace-dir is required")

    if args.trace:
        result = read_trace(args.trace)
        if not result["ok"]:
            print(result)
            return 1
        output = render_replay_markdown(result["trace"])
    else:
        result = read_trace_dir(args.trace_dir)
        if not result["ok"]:
            print(result)
            return 1
        chunks = []
        for item in result["items"]:
            if item["ok"]:
                chunks.append(render_replay_markdown(item["trace"]))
            else:
                chunks.append(f"# Trace Replay Error\n\n- path: {item['path']}\n- error: {item['error']['code']}\n")
        output = "\n".join(chunks)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output, encoding="utf-8")
        print(str(out))
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
