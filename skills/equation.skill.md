name: equation
applies_to: equation, algebra, solve_for_variable
input_features: 含等式、未知量、求解/解方程/solve 等意图；支持 implicit multiplication 模式（如 2x）。
procedure:
  1. tool-first：优先调用符号工具（SymPy）建模求解。
  2. 对隐式乘法做规范化（2x -> 2*x）。
  3. 解出候选解后执行 substitution 回代检查。
  4. 仅在需要时提供简要说明。
heuristics:
  - 优先给出解集、变量值或参数条件。
  - 多解时保持集合/分支完整，不丢根。
constraints:
  - 不把完整推理过程塞进 boxed。
  - 不跳过 substitution 校验。
fallback:
  - 工具失败时退回规则推理并标注低置信度，不崩溃。
  - 无法唯一确定时返回条件化答案并说明。
final_answer_rules:
  - final_answer.value 保持简短，聚焦解集或变量值。
  - boxed 仅放短答案，不包含长段落。
trace_notes:
  - 记录规范化、求解器调用、回代校验是否通过。
