name: probability
applies_to: probability, expectation, variance, random_variable
input_features: 概率、期望、方差、分布等关键词。
procedure:
  1. 明确样本空间与事件定义。
  2. 选择计数、条件概率或分布公式求解。
  3. 用 numeric_check 验证范围（如概率在 [0,1]）。
heuristics:
  - 先简化事件表达，再代入公式。
constraints:
  - 不遗漏条件独立性或归一化检查。
fallback:
  - 条件不足时给出参数化表达并说明前提。
final_answer_rules:
  - value 输出概率/期望的最终表达。
trace_notes:
  - 记录事件定义、公式来源与检查结果。
