# Externalization Design: Math Reasoning Harness

## 1) 设计目标
EvoExternMath-S1++ 将高变动推理增强能力外化为 Harness，保证 Stable Pipeline 冻结不动，同时提升可实验性与可回退性。

## 2) MemoryHub 设计
- 定位：历史经验与上下文线索的可选辅助层。
- 原则：默认不写入，避免引入不可控状态污染。
- 约束：作为外部组件调用，不强绑定主流程。

## 3) Skill Library 设计
- 定位：将题型策略模板化，降低 prompt 漂移与重复劳动。
- 机制：基于可注册技能进行受控启用。
- 约束：技能库增强应保持可关闭，不影响 stable 主路径正确性。

## 4) Protocol Schema 设计
- 定位：统一 SolveResult 契约与校验规则。
- 机制：输出必须经过 schema guard；失败时返回 success=false 并补齐 error 字段。
- 价值：提高 JSON 安全、评测兼容与审计可读性。

## 5) Budget Scheduler 设计
- 定位：控制调用预算与尝试次数的策略层。
- 当前状态：standalone，默认不接入主流程。
- 原则：任何接入都必须可回退、可灰度。

## 6) Weighted Voting 设计
- 定位：多候选答案聚合机制。
- 当前状态：standalone，未接入 stable pipeline。
- 原则：需由 verifier gate 约束，避免错误放大。

## 7) Trace Replay 设计
- 定位：将运行轨迹转化为可复盘证据。
- 机制：支持 timeline / summary 提取，服务调试、答辩与 Demo。
- 约束：重放是观测与分析层，不改动主求解逻辑。

## 8) 为什么这是“外化式数学推理 Harness”
- 高变动策略（Memory / Skills / Voting / Budget）不与核心 pipeline 强耦合。
- 稳定主链路 + 外化增强层的组合，使系统具备更好实验效率与上线安全性。
- 可通过开关或配置实现快速回退，满足竞赛审计与工程可复现要求。

## 9) 稳定性声明
- 默认配置下，这些模块不破坏 stable pipeline。
- 本阶段仅完善文档骨架与测试，不改 solve / batch CLI 契约。
