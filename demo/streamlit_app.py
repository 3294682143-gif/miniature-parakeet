from __future__ import annotations

from pathlib import Path

import streamlit as st

from math_agent.harness.demo_adapter import (
    build_demo_budget_preview,
    build_demo_timeline,
    build_mock_voting_demo,
    load_demo_memory_summary,
    load_demo_skill_summary,
    result_to_display_dict,
    safe_get_risk_flags,
    safe_get_tool_calls,
)
from math_agent.harness.replay import build_timeline, render_replay_markdown, summarize_trace
from math_agent.harness.trace_reader import read_trace
from math_agent.pipeline import MathAgentPipeline


def run_demo_pipeline(question: str, *, question_id: str, mock: bool, enable_tools: bool, trace_dir: str, max_refine_rounds: int, mode: str):
    pipeline = MathAgentPipeline(mock=mock, enable_tools=enable_tools, save_trace=True, trace_dir=trace_dir, max_refine_rounds=max_refine_rounds, run_mode=mode)
    route_info = pipeline.router.route(question)
    result = pipeline.solve(question=question, question_id=question_id)
    trace_path = Path(trace_dir) / f"{question_id}.json"
    return result, trace_path, route_info


def main() -> None:
    st.set_page_config(page_title="EvoExternMath-S1++ 数学智能体 Demo", layout="wide")
    st.title("EvoExternMath-S1++ 数学智能体 Demo")

    with st.sidebar:
        run_mode = st.selectbox("run mode", ["mock", "real"], index=0)
        enable_tools = st.toggle("enable_tools", value=False)
        mode = st.selectbox("mode", ["full", "fast", "tool-first"], index=0)
        max_refine_rounds = int(st.number_input("max_refine_rounds", min_value=0, value=1, step=1))
        trace_dir = st.text_input("trace_dir", value="outputs/traces")
        show_raw_json = st.toggle("show raw json", value=False)
        replay_existing_trace = st.toggle("replay existing trace", value=False)
        st.caption("read-only skill viewer")
        st.caption("read-only memory summary")
        st.caption("read-only budget preview")

    st.header("A. Input Panel")
    question_id = st.text_input("question_id", value="demo_q1")
    question = st.text_area("question", value="计算 2+3", height=120)

    result = None
    route_info = None
    trace_path = None
    if st.button("开始求解", type="primary"):
        result, trace_path, route_info = run_demo_pipeline(
            question,
            question_id=question_id.strip() or "demo_q1",
            mock=(run_mode == "mock"),
            enable_tools=enable_tools,
            trace_dir=trace_dir.strip() or "outputs/traces",
            max_refine_rounds=max_refine_rounds,
            mode=mode,
        )

    if result is not None:
        display = result_to_display_dict(result)
        st.header("B. Result Panel")
        st.write("final_answer:", display["final_answer"])
        st.write("status:", display["status"])
        st.write("confidence:", display["confidence"])
        st.write("verification:", f"{display['verification_method']} / passed={display['verification_passed']}")
        st.write("risk flags:", safe_get_risk_flags(result) or [])

        st.header("C. Agent Timeline")
        for row in build_demo_timeline(result):
            st.write(f"{row['stage']} → {row['status']} ({row['detail']})")

        st.header("D. Tool Calls")
        tool_calls = safe_get_tool_calls(result)
        if not tool_calls:
            st.info("No tool calls recorded")
        else:
            st.json(tool_calls, expanded=False)

        st.header("E. Skill Library Viewer")
        skill_summary = load_demo_skill_summary(question, route_info)
        st.write("list_skills:", skill_summary.get("skills", []))
        st.write("select_skill:", skill_summary.get("selected_skill"))
        st.json(skill_summary.get("selected_skill_meta") or {}, expanded=False)

        st.header("F. Memory Summary")
        memory_summary = load_demo_memory_summary()
        st.json(memory_summary.get("summary", {}), expanded=False)

        st.header("G. Budget Preview")
        st.json(build_demo_budget_preview(question, route_info=route_info, mode=mode), expanded=False)

        st.header("H. Weighted Voting Explainer")
        st.markdown("- verifier-gated，不是裸 majority vote\n- 默认不接入主流程\n- 后续可用于 candidate solver")
        st.json(build_mock_voting_demo(), expanded=False)

        st.header("I. Trace Replay Panel")
        replay_path = st.text_input("trace file path", value=str(trace_path) if trace_path else "")
        if replay_existing_trace and replay_path.strip():
            trace_read = read_trace(replay_path.strip())
            if not trace_read.get("ok"):
                st.warning(str(trace_read.get("error")))
            else:
                trace = trace_read.get("trace") or {}
                st.write(build_timeline(trace))
                st.write(summarize_trace(trace))
                st.markdown(render_replay_markdown(trace))

        if show_raw_json:
            st.header("J. Raw JSON")
            st.json(result.model_dump(), expanded=False)


if __name__ == "__main__":
    main()
