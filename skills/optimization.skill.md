name: optimization
applies_to: optimization, maximize, minimize, constrained_optimization
input_features: 最优化、约束、极值关键词。
procedure:
  1. 明确目标函数与约束。
  2. 根据类型使用导数/KKT/线性规划策略。
  3. 校验可行性并比较候选极值。
heuristics:
  - 先验判定凸性/边界，再做细化。
constraints:
  - 不把完整过程塞入 boxed。
fallback:
  - 若条件不足，返回候选与所需补充信息。
final_answer_rules:
  - value 给出最优值与取值点（若可得）。
trace_notes:
  - 记录可行域检查与最优性判定依据。
