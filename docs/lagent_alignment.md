# Lagent Alignment Notes

This project does not make `lagent` a required runtime dependency for the initial competition path. The stable pipeline remains frozen and mock-safe by default. The alignment is intentionally an adapter layer: it lets reports and demos explain the system in the same vocabulary as the official baseline reference without changing CLI behavior or output contracts.

## Mapping

| Lagent concept | Project equivalent | Files |
|---|---|---|
| Agent message | sanitized trace message | `src/math_agent/harness/lagent_trace_adapter.py` |
| Agent / role | Router, Planner, Solver, Verifier, Refiner, Explainer | `src/math_agent/agents/` |
| Tool action | `ToolCallRecord`, `ToolTrace`, SymPy/Python tools | `src/math_agent/schemas.py`, `src/math_agent/tools/` |
| Action executor | tool-first and tool-assist execution | `src/math_agent/pipeline.py` |
| Hook / observer | trace writer, replay, failure report, proof review pack | `src/math_agent/logging_utils.py`, `src/math_agent/harness/`, `src/math_agent/evaluation/` |
| Memory | optional MemoryHub, default read-only/no write | `src/math_agent/harness/memory.py`, `memory/` |
| Output parser | schema validation and formatter repair | `src/math_agent/schemas.py`, `src/math_agent/harness/formatter_repair.py` |

## Competition Position

For the preliminary round, the safest route is to keep the current stable solver chain and export lagent-style trace views for review. This preserves:

- JSON compatibility with the existing `SolveResult` schema.
- mock-first testing and no accidental API calls.
- official-style dry-run and safety scanner behavior.
- reproducible trace/replay artifacts for subjective review.

For the final round, `lagent` can be introduced as an optional demo/runtime layer around the same schema boundary. The recommended order is:

1. Keep `math_agent.pipeline.solve_question` as the canonical solver.
2. Convert each pipeline step to lagent-style messages through `trace_to_lagent_messages`.
3. Add an optional demo-only orchestrator that can display Router/Solver/Verifier messages as an agent conversation.
4. Only after the 18-domain suite and real API sample gate are stable, consider replacing specific internal orchestration pieces with native lagent components.

## Non-goals

- Do not require `lagent` for `pytest -q`.
- Do not change CLI defaults or output JSON fields.
- Do not let a demo-only multi-agent workflow override the stable final answer unless an explicit reviewed gate enables it.
