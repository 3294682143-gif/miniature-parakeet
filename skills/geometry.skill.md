name: geometry
applies_to: geometry, triangle, circle, angle
input_features: 几何图形、角度、长度、面积等问题。
procedure:
  1. 提取已知关系与目标量。
  2. 选用几何定理（相似、勾股、圆幂等）推导。
  3. 对结果做量纲与范围检查。
heuristics:
  - 优先结构化关系式，减少口语化描述。
constraints:
  - 不把长证明堆入 final_answer 或 boxed。
fallback:
  - 图形信息不足时保留符号化结果并说明。
final_answer_rules:
  - value 输出目标量；boxed 仅短答案。
trace_notes:
  - 记录关键定理与结论一致性检查。
