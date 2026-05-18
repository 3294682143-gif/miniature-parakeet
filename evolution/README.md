# Offline Evolution Layer (Step 14 Skeleton)

This directory defines the **offline-only** evolution workflow for EvoExternMath-S1++.

## Positioning

- Used only before official runs (pre-competition / offline iteration).
- Official submission must run with **Frozen Harness** and frozen code/artifacts.
- No online self-modification (禁止在线自改).
- No dynamic code modification during formal evaluation.
- No per-question manual editing of `official_results.jsonl`.
- No fabricated traces, logs, or evaluation records.

## Workflow Narrative

`trace -> failure analysis -> evidence -> change manifest -> candidate harness -> regression gate -> frozen submission`

See `docs/evolution_design.md` for full design.
