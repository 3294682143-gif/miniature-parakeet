name: calculus
applies_to: limit, derivative, integral, series
input_features: 含极限/导数/积分/级数等微积分关键词。
procedure:
  1. 判定任务类型（limit/derivative/integral）。
  2. 优先符号工具计算并给出关键变形。
  3. 对结果做可行的数值或符号复核。
heuristics:
  - 注意定义域与可导/可积条件。
constraints:
  - 不输出冗长最终答案字段。
fallback:
  - 工具失败时给出保守步骤与不确定性说明。
final_answer_rules:
  - value 输出简明结果；boxed 仅短式。
trace_notes:
  - 记录采用的方法与复核状态。
