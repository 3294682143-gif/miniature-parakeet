name: matrix
applies_to: matrix, linear_algebra, eigenvalue, determinant
input_features: 矩阵、行列式、特征值、线性变换关键词。
procedure:
  1. 识别任务（det/rank/eigen/solve）。
  2. 优先线性代数工具计算。
  3. 必要时用代回或恒等式复核。
heuristics:
  - 优先保持矩阵维度与符号一致。
constraints:
  - 不输出冗长 boxed 内容。
fallback:
  - 工具异常时返回已确认部分与失败原因。
final_answer_rules:
  - value 给出数值、向量或集合化结果。
trace_notes:
  - 记录维度检查与关键算子结果。
