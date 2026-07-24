# Official-like Dry Run Harness

This is NOT official evaluation.
This does not claim official accuracy.
This does not generate official_results.jsonl.
This does not call external APIs unless --real and --allow-real are explicitly both passed.
Default mode is mock-safe.

## 1. Purpose
Preofficial validation harness for official-like batch input/output checks.

## 2. Inputs
JSONL records with question_id/id/qid and question/prompt compatibility.

## 3. Outputs
- dry_run_results.jsonl
- dry_run_summary.json
- dry_run_report.md
- run_record.json
- config_snapshot.json
- invalid_cases.jsonl

Each run records the SHA-256 input manifest and the expected execution-profile
fingerprint. The input is re-read and verified before the run is finalized.

## 4. Mock Dry Run
Default mode is mock and does not call real APIs.

## 5. Real Dry Run Guard
`--real` must be paired with `--allow-real` and is still CI-blocked by design.

## 6. Hard Mode Dry Run
Supports `--hard-mode --hard-mode-level {off,light,standard,strict}`.

## 7. Trace Policy
Use `--no-trace` to disable trace output. Otherwise traces are written below a
new exclusive `<trace-base>/<run_id>/` directory. A prior run directory is never
reused. Every accepted trace must bind the canonical question, result payload,
mock/real marker, prompt snapshot, execution profile, model-call evidence, and
tool-call evidence.

## 8. Safety Boundaries
No `.env` loading, no token reads, no official output naming, and no real API
call from this harness. Direct dataclass construction is revalidated at both run
boundaries, so setting contradictory mock/real flags cannot bypass the CLI guard.

## 9. Invalid Cases
Invalid JSON and missing question rows are captured in invalid_cases.jsonl.

## 10. Submission-like Results
One result row per valid canonical question ID with
status/final_answer/verification/error metadata. Duplicate IDs, including IDs
that collide after canonicalization, fail closed.

## 11. Limitations
Dry-run report is not an accuracy report and not an official scoreboard. Proof
results require external semantic review and are never automatically certified
by the proof-preview layer.

## 12. Next Steps
Use this harness as pre-check before formal submission workflow.
