# Final Submission Checklist

> 用于最终提交前逐项打勾，确保结果、打包与合规一致。

## A. 结果文件一致性
- [ ] `official_results.jsonl` 每行都是合法 JSON
- [ ] 每题有 `question_id`
- [ ] 每题有 `final_answer`
- [ ] `trace_count = question_count`
- [ ] `missing_final = 0`
- [ ] `dirty_boxed = 0`
- [ ] `boxed_42_fallback = 0`
- [ ] `zero_model_calls = []`

## B. 报告与提交文档
- [ ] `evaluation_report.md` 已生成
- [ ] `README_SUBMISSION.md` 已生成

## C. 压缩包完整性
- [ ] `submission.zip` 可正常打开
- [ ] 不包含 `.env`
- [ ] 不包含 API key
- [ ] 不包含 `Authorization` / `Bearer`
- [ ] 不包含 `.git`
- [ ] 不包含 `__pycache__`
- [ ] 不包含 `.pytest_cache`
- [ ] 不包含 `outputs/debug*`
- [ ] 不包含官方原始私有题集（除非赛事规则明确允许）

## D. 运行与演示
- [ ] Demo 可启动
- [ ] `pytest -q` 通过

## E. 合规与审计
- [ ] 不人工修改 `official_results.jsonl`
- [ ] 不伪造 trace / 日志
- [ ] 不将 preofficial/mock 结果写成 official 结果

## F. 最终口径
- [ ] 未运行官方 112 题前，不声称官方成绩
- [ ] 正式提交使用 Frozen Harness 产物
