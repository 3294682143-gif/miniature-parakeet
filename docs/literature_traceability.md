# Literature Traceability (P18.6)

This is NOT official evaluation.
Do not claim official accuracy from this audit.
Do not rename dry-run outputs to official_results.jsonl.

missing_reference_count=2

## Reference Inventory

| ID | Title | Key Idea | Used By Modules | Claim Strength | Limitation |
|---|---|---|---|---|---|
| [R1] | Gödel Agent: A Self-Referential Agent Framework for Recursively Self-Improvement | self-referential agent, recursive self-improvement, environment feedback, error handling, tool use | Stable Core / Pipeline; Hard-mode Control; Agents | weak | 项目未实现 unrestricted self-modification，仅做受控工程化策略层。 |
| [R2] | Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents | open-ended self-improvement, agent archive, benchmark validation, safety sandbox, traceability | Shadow Eval; Official-like Dry Run; Demo Evidence Pack; Safety/Quality | medium | 未实现 open-ended autonomous self-modifying coding loop。 |
| [R3] | Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses | harness engineering, observability, agent debugger, change manifest, falsifiable edit contract | Agent Debugger; Shadow Eval; Demo Evidence Pack; Safety/Quality | medium | 未实现自动演化 harness 的完整闭环，仅提供工程化审计与归因。 |
| [R4] | Agentic Architect: An Agentic AI Framework for Architecture Design Exploration and Optimization | LLM-driven evolution, scoring function, evaluator loop, candidate evaluation | Shadow Eval; Candidate Budget/Verifier Routing; Official-like Dry Run | weak | 当前仓库未执行 architecture search，只做评分/评估思路工程适配。 |
| [R5] | HyperAgents | task agent + meta agent, metacognitive self-modification, persistent memory, performance tracking | Hard-mode Control; Agent Debugger; Harness/Memory/Replay | weak | 未实现论文级 hyperagent 自修改机制。 |
| [R6] | AutoHarness: improving LLM agents by automatically synthesizing a code harness | code-as-harness, action verifier, verification harness, illegal action prevention | Tool/Symbolic Layer; Proof Guardian; Safety/Quality; Harness/Replay | medium | 未训练自动 synthesizing harness，仅实现静态/运行时 guard。 |
| [R7] | CoVerRL: Breaking the Consensus Trap in Label-Free Reasoning via Generator-Verifier Co-Evolution | generator-verifier co-evolution, consensus trap, self-verification, filtering | Verification/Weighted Voting; Proof Guardian; Candidate Budget/Verifier Routing | medium | 未进行 RL co-evolution 训练，仅做 deterministic 评分与投票策略。 |
| [R8] | Putting the Value Back in RL: Better Test-Time Scaling by Unifying LLM Reasoners With Verifiers | reasoner-verifier unification, weighted voting, Best-of-N, verifier-guided selection | Verification/Weighted Voting; Hard-mode Control; Proof Guardian | medium | 未实现 unified generative verifier 训练，仅做工程化推理时路由/打分。 |

## Notes

- Mapping language: inspired by / engineering adaptation / evaluation inspired by / safety traceability inspired by.
- Literature mapping is traceability evidence, not a claim of full paper reproduction.
