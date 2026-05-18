name: proof
applies_to: proof, topology, real_analysis, abstract_algebra, set_logic, number_theory
input_features: 包含“证明/prove/show that/试证”等证明意图；route_info.problem_type 或 domain 指向证明类。
procedure:
  1. 先明确 givens/goal，重述命题与条件。
  2. 按逻辑链展开证明（定义->推导->结论），避免跳步。
  3. visible_solution_steps 保留完整证明过程，不截断关键论证。
  4. final_answer.type 固定为 proof，final_answer.value 仅写短结论句。
heuristics:
  - verifier method 使用 logic_review。
  - 检查循环论证、缺失结论、偷换概念与未定义符号。
  - proof 题不强制 boxed；final_answer.boxed 允许为空。
constraints:
  - 不要把整段证明塞进 final_answer.value。
  - 不得把长 Markdown 或整段证明放进 boxed。
  - 对齐 src/math_agent/agents/proof_guardian.py 与 src/math_agent/harness/formatter_repair.py 现有策略。
fallback:
  - 结构不完整时，保留已完成推导并显式标注缺失环节；不得崩溃。
  - 若解析失败，返回可审计的失败信息并保持 schema 合法。
final_answer_rules:
  - type=proof。
  - value 为简洁结论（如“命题成立”或“已证明…”）。
  - boxed 可为空，不强制输出 \boxed{}。
trace_notes:
  - 记录 proof 结构检查要点：givens/goal/chain/conclusion 与 logic_review 结果。
