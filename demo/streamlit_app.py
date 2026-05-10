from __future__ import annotations

from pathlib import Path

import streamlit as st

from math_agent.pipeline import MathAgentPipeline

EXAMPLE_QUESTIONS: dict[str, str] = {
    "计算 2+3": "计算 2+3",
    "化简 sin(x)^2 + cos(x)^2": "化简 sin(x)^2 + cos(x)^2",
    "证明型示例": "证明：前n个正整数之和为 n(n+1)/2",
    "优化型示例": "求函数 f(x)=x^2-4x+5 的最小值",
}


def run_demo_pipeline(
    question: str,
    *,
    question_id: str,
    mock: bool,
    enable_tools: bool,
    save_trace: bool,
    trace_dir: str,
    max_refine_rounds: int,
):
    pipeline = MathAgentPipeline(
        mock=mock,
        enable_tools=enable_tools,
        save_trace=save_trace,
        trace_dir=trace_dir,
        max_refine_rounds=max_refine_rounds,
    )
    route_info = pipeline.router.route(question)
    result = pipeline.solve(question=question, question_id=question_id)
    trace_path = Path(trace_dir) / f"{question_id}.json" if save_trace else None
    return result, trace_path, route_info


def main() -> None:
    st.set_page_config(page_title="Intern-S1 数学智能体 Demo", layout="wide")
    st.title("Intern-S1 数学智能体 Demo")

    with st.sidebar:
        st.header("运行设置")
        mock_mode = st.toggle("mock 模式", value=True)
        enable_tools = st.toggle("enable_tools", value=False)
        save_trace = st.toggle("save_trace", value=True)
        trace_dir = st.text_input("trace_dir", value="outputs/traces")
        max_refine_rounds = st.number_input("max_refine_rounds", min_value=0, value=1, step=1)
        question_id = st.text_input("question_id", value="demo_q1")

    st.subheader("题目输入")
    selected_example = st.selectbox("示例题", options=list(EXAMPLE_QUESTIONS.keys()), index=0)
    if st.button("填充示例题"):
        st.session_state["question_input"] = EXAMPLE_QUESTIONS[selected_example]

    question = st.text_area("请输入数学题目", key="question_input", height=120)

    if st.button("开始求解", type="primary"):
        if not question.strip():
            st.warning("请先输入题目。")
            return

        with st.spinner("正在求解..."):
            result, trace_path, route_info = run_demo_pipeline(
                question,
                question_id=question_id.strip() or "demo_q1",
                mock=mock_mode,
                enable_tools=enable_tools,
                save_trace=save_trace,
                trace_dir=trace_dir.strip() or "outputs/traces",
                max_refine_rounds=int(max_refine_rounds),
            )

        st.success("求解完成")
        st.subheader("路由结果")
        c1, c2, c3 = st.columns(3)
        c1.metric("domain", result.domain)
        c2.metric("problem_type", result.problem_type)
        c3.metric("recommended_solver", route_info.recommended_solver)

        st.subheader("problem_parse")
        st.json(result.problem_parse.model_dump(), expanded=True)

        st.subheader("solution_plan")
        st.write(result.solution_plan)

        st.subheader("visible_solution_steps")
        st.write(result.visible_solution_steps)

        st.subheader("tool_trace")
        st.json([t.model_dump() for t in result.tool_trace], expanded=False)

        st.subheader("verification")
        st.json(result.verification.model_dump(), expanded=True)

        st.subheader("final_answer")
        st.json(result.final_answer.model_dump(), expanded=True)

        st.subheader("didactic_hint")
        st.write(result.didactic_hint)

        st.subheader("原始 SolveResult JSON")
        st.json(result.model_dump(), expanded=False)

        if save_trace and trace_path is not None:
            st.info(f"trace 文件路径: {trace_path}")


if __name__ == "__main__":
    main()
