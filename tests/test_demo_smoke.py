from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_demo_module():
    module_path = Path(__file__).resolve().parents[1] / "demo" / "streamlit_app.py"
    spec = spec_from_file_location("streamlit_app", module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_streamlit_demo_module_importable() -> None:
    app = _load_demo_module()
    assert callable(app.main)


def test_run_demo_pipeline_mock_mode() -> None:
    app = _load_demo_module()
    result, trace_path, route_info = app.run_demo_pipeline(
        "计算 2+3",
        question_id="demo_test_q",
        mock=True,
        enable_tools=True,
        save_trace=False,
        trace_dir="outputs/traces",
        max_refine_rounds=1,
    )

    assert result.question_id == "demo_test_q"
    assert result.status in {"success", "partial", "fail"}
    assert route_info.recommended_solver
    assert trace_path is None
