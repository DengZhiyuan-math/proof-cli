# ScientistOne 与 FML-bench：论文证据索引

读取日期：2026-10-12。只记录论文事实及其边界。系统设计映射另见汇总报告。本次没有运行模型或实验，没有修改代码、ADR 或 Issue。

## ScientistOne

**ScientistOne: Towards Human-Level Autonomous Research via Chain-of-Evidence**。用户指定版本：`2605.26340v1`，2026-05-25。[原文](https://arxiv.org/html/2605.26340v1)

| 项目 | 作者报告与限定 | 原文 |
|---|---|---|
| 核心 | 引用、数值、方法、结论绑定来源；先生成带证据标记的表示，再检查、改写、排版、复查 | [§3](https://arxiv.org/html/2605.26340v1#S3)、[§4.3](https://arxiv.org/html/2605.26340v1#S4.SS3) |
| 审计 | I1 重跑分数；I2 规则违规；I3 引用存在；I4 方法与代码一致。不是数学正确性检查 | [§5](https://arxiv.org/html/2605.26340v1#S5)、[§9](https://arxiv.org/html/2605.26340v1#S9) |
| 分母 | 5 系统 × 5 任务 × 3 seeds = 75 篇。ScientistOne：I1 12/12、I2 0/15、I3 0/337、I4 14/15；I1 排除 3 篇含硬件时间项的 EPLB | [Table 1](https://arxiv.org/html/2605.26340v1#S6.T1) |
| CPR | 627/639 = 98.1%；数值与日志匹配，5% 容差；不是结论正确率 | [§6.2](https://arxiv.org/html/2605.26340v1#S6.SS2) |
| 核验深度 | I1–I3 阳性人工复核，I4 抽检；漏检未定量。native 引用检查看 abstract，方法比日志。存在不等于支持；理论领域未验证 | [§9](https://arxiv.org/html/2605.26340v1#S9)、[B.5](https://arxiv.org/html/2605.26340v1#A2.SS5)、[Appendix D](https://arxiv.org/html/2605.26340v1#A4) |
| 比较边界 | 适配有混杂；Sakana 的 I2/I4 不宜直接排名。solver 比较为 best-of-3；scaling 单 seed | [§6.1](https://arxiv.org/html/2605.26340v1#S6.SS1)、[§6.4](https://arxiv.org/html/2605.26340v1#S6.SS4)、[Appendix C](https://arxiv.org/html/2605.26340v1#A3) |

## FML-bench

**FML-bench: A Controlled Study of AI Research Agent Strategies from the Perspective of Search Dynamics**。用户未定版 PDF 当前解析为 `2605.17373v2`，2026-05-29。[固定版本 HTML](https://arxiv.org/html/2605.17373v2)、[固定版本 PDF](https://arxiv.org/pdf/2605.17373v2)

| 项目 | 作者报告与限定 | 原文 |
|---|---|---|
| 控制 | 搜索策略自有；编辑器、执行、指标显示、val/test 隔离共享。搜索只看 val，结束后测试最佳 val 候选 | [§3.2](https://arxiv.org/html/2605.17373v2#S3.SS2) |
| 预算 | 6 agents × 18 tasks × 3 rounds = 324 runs；GPT-5.4；100 次 validation 执行。全部 LLM token 含编辑、构思、日志；不等于等 token 成本 | [§4.1](https://arxiv.org/html/2605.17373v2#S4.SS1)、[§3.4](https://arxiv.org/html/2605.17373v2#S3.SS4) |
| 结果 | Table 2（mean-of-3）：TAS v2 0.193，Autoresearch 0.192。Table 3：AdaptiveSearch 0.208，同一 100-step 总预算；七-agent win-rate 为 58.6% / 56.2% / 56.2% | [Table 2](https://arxiv.org/html/2605.17373v2#S4.T2)、[Table 3](https://arxiv.org/html/2605.17373v2#S4.T3) |
| 自适应 | greedy 停滞后单向转分支；W=50，ε=0.0005，剩余预算决定 1–3 branches。Phase 2 reach 校准来自主实验，不能称整套机制纯在线 | [§4.3](https://arxiv.org/html/2605.17373v2#S4.SS3)、[Appendix D](https://arxiv.org/html/2605.17373v2#A4) |
| 度量边界 | 未改善归零；3 个无界任务采用 baseline 分母，MEAN 混合尺度。dense/sparse 是运行后分组；不是先验 oracle | [Appendix E](https://arxiv.org/html/2605.17373v2#A5)、[Appendix G](https://arxiv.org/html/2605.17373v2#A7) |
| 关联边界 | pooled Spearman：AUC ρ=.784，reach .115，effective dim −.140；不识别因果。AUC 有定义重叠；token 不显著不等于预算无关 | [§5.2](https://arxiv.org/html/2605.17373v2#S5.SS2) |
| 迁移边界 | 移除原生编辑器、检索等；固定 step 可能影响排名。共享编辑器每 edit 一次调用、限定文件；不能据此宣称完整原生 agent 排名 | [§6](https://arxiv.org/html/2605.17373v2#S6)、[Appendix C](https://arxiv.org/html/2605.17373v2#A3)、[Appendix J](https://arxiv.org/html/2605.17373v2#A10) |

## 阅读结论的使用规则

以下是本次分析的推论，不是论文已验证的结论：

- 证据可追踪、可重跑与数学命题成立是不同判断。系统设计必须保留 Human Review。
- 搜索控制器可以更换；同一比较中固定执行条件并记录实际成本。
- 将停滞用于触发有限探索之前，先定义可观察进展；数学证明没有论文中的连续 validation metric。
- 不用回顾实验的任务分组或 reach 校准冒充新任务运行时已知量。

本文是来源索引和限定记录。它不代表复现实验、外部审稿或系统实施结果。
