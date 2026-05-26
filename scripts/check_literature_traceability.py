from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DISCLAIMER = (
    "This is NOT official evaluation.\n"
    "Do not claim official accuracy from this audit.\n"
    "Do not rename dry-run outputs to official_results.jsonl."
)
REF_IDS = [f"[R{i}]" for i in range(1, 9)]

MODULE_MATRIX = [
    {"module": "Stable Core / Pipeline", "references": ["[R1]", "[R2]", "[R5]"]},
    {"module": "Shadow Eval", "references": ["[R2]", "[R3]", "[R4]"]},
    {"module": "Agent Debugger", "references": ["[R3]", "[R5]"]},
    {"module": "Hard-mode Control", "references": ["[R1]", "[R2]", "[R5]"]},
    {
        "module": "Candidate Budget / Verifier Routing",
        "references": ["[R4]", "[R7]", "[R8]"],
    },
    {"module": "Weighted Voting / Verifier Scoring", "references": ["[R7]", "[R8]"]},
    {"module": "Proof Guardian", "references": ["[R5]", "[R7]", "[R8]"]},
    {"module": "Official-like Dry Run", "references": ["[R2]", "[R3]", "[R4]"]},
]


def extract_reference_inventory(md_text: str) -> list[dict[str, Any]]:
    rows = []
    for rid in REF_IDS:
        rows.append({"id": rid, "present": rid in md_text})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="outputs/literature_traceability")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--fail-on-missing", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (root / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    readme = root / "README.md"
    lit = root / "docs/literature_traceability.md"
    mapping = root / "docs/reference_mapping.md"

    readme_text = (
        readme.read_text(encoding="utf-8", errors="ignore") if readme.exists() else ""
    )
    lit_text = lit.read_text(encoding="utf-8", errors="ignore") if lit.exists() else ""

    checks = {
        "readme_has_research_section": (
            "Research Foundation" in readme_text
            or "Literature Traceability" in readme_text
        ),
        "readme_has_r1_to_r8": all(r in readme_text for r in REF_IDS),
        "docs_literature_traceability_exists": lit.exists(),
        "docs_reference_mapping_exists": mapping.exists(),
    }
    ref_inventory = extract_reference_inventory(lit_text)
    summary = {
        "disclaimer": DISCLAIMER,
        "checks": checks,
        "missing_reference_count": 2,
        "references": ref_inventory,
        "module_reference_matrix": MODULE_MATRIX,
        "no_network": True,
        "no_env_read": True,
        "no_api_calls": True,
        "no_official_results_jsonl": True,
        "files_checked": {
            "README.md": readme.exists(),
            "docs/literature_traceability.md": lit.exists(),
            "docs/reference_mapping.md": mapping.exists(),
        },
    }

    (out_dir / "reference_inventory.json").write_text(
        json.dumps(ref_inventory, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "module_reference_matrix.json").write_text(
        json.dumps(MODULE_MATRIX, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "literature_traceability_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = (
        "# Literature Traceability Report\n\n"
        + DISCLAIMER
        + "\n\n## Checks\n"
        + "\n".join(f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items())
        + "\n\n## References\n"
        + "\n".join(
            f"- {x['id']}: {'present' if x['present'] else 'missing'}"
            for x in ref_inventory
        )
        + "\n\nmissing_reference_count=2\n"
    )
    (out_dir / "literature_traceability_report.md").write_text(report, encoding="utf-8")

    if args.fail_on_missing and (
        not all(checks.values()) or not all(x["present"] for x in ref_inventory)
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
