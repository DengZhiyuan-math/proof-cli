# EdgeBench：项目内证明学习的原始证据

核查日期：2026-10-12。仅阅读论文和官方代码；未复现实验，未执行任务镜像。

## 论文证据

| 事项 | 原文支持的结论 | 原始来源 |
| --- | --- | --- |
| 学习机制 | 作者明确称算法为上下文内学习（ICL）。公开方法未报告在线参数更新。 | [论文 Appendix F.3](https://arxiv.org/html/2607.05155) |
| 经验消融 | Opus 4.8、17 个任务：连续 12h 保留工作区、工件和历史；对照为 6 次独立 2h，全状态重置。12h 得分为 43.0 对 36.1。 | [论文 §5.2](https://arxiv.org/html/2607.05155) |
| 估计方法 | 连续组平均每任务 3 条轨迹；重启组从 6 次结果中均匀取大小为 k 的子集，估计 best-of-k，再跨任务平均。 | [论文 Appendix G.1](https://arxiv.org/html/2607.05155) |
| 反馈 | 本地快速验证与隔离 judge 反馈分开；主机定时评分不展示给 agent。 | [论文 §2.3、Appendix A](https://arxiv.org/html/2607.05155) |
| 形式数学 | 部分任务按完整依赖链检查证明；部分任务按难度加权；Coq 任务禁止 admitted axioms。 | [论文 Appendix G.4，Formal Math 行](https://arxiv.org/html/2607.05155) |
| 曲线边界 | log-sigmoid 拟合多任务平均的 best-so-far。单任务可停滞或回退；理论受瓶颈、混合性、时间坐标等假设限制。 | [论文 §3.1–3.3、Appendix D.5](https://arxiv.org/html/2607.05155) |
| 评分边界 | 作者记录反馈泄露答案、随机高分选择、评测种子过拟合、越界访问和在线查答案等问题。 | [论文 Appendix C](https://arxiv.org/html/2607.05155) |

## 官方代码核查

固定阅读的仓库头：`6e4e5f4aa087a9121aa09a6059e5484e5102c6ff`。

- Codex 适配器通过 `CODEX_MODEL` 选择模型，并用 `codex exec resume --last` 续跑。该适配器负责会话执行与恢复。来源：[codex.py，L36–52](https://github.com/ByteDance-Seed/EdgeBench/blob/6e4e5f4aa087a9121aa09a6059e5484e5102c6ff/sforge/harness/agent/codex.py#L36)。
- 官方文档规定固定 CLI 版本，记录 stop hook 与 auto-resume；后者恢复上一次会话并继续消耗剩余预算。来源：[Supported Agents，Pinned versions / Auto-Resume](https://github.com/ByteDance-Seed/EdgeBench/blob/6e4e5f4aa087a9121aa09a6059e5484e5102c6ff/docs/en/guide/agents.md#L139)。
- 此次没有取得并检查形式数学任务镜像中的 grader。上表的数学评分结论来自论文，未由 grader 源码独立验证。

## 对本项目的解释边界

以下是本次分析，不是论文已验证的结论。

1. 这里可先按固定模型的 ICL 理解：让上下文、文件和反馈积累。无需先引入在线训练。模型服务端权重是否完全固定，不在此次独立核查范围内。
2. 消融测量连续状态包的整体价值。它同时改变历史、可复用工件、工作区和单次尝试长度。因此不能把 +6.9 单独归因于反思摘要、检索、某种记忆格式或某个策略。两小时截断也可能限制需要较长前置工作的任务。
3. 该对照研究同一任务中的连续改进。它没有直接证明：完成项目节点 A 的经验会提高此前未见节点 B 的证明能力。跨节点迁移需要单独设置未见目标，并固定可调用的数学结果和计算预算。
4. best-so-far 是历史最优选择。它不能证明当前工件持续有效，也不能替代本项目的 researcher acceptance。局部评分上升与数学可信度应分别记录。
5. 理论中的潜在任务图是解释模型。不能直接把它等同于我们的显式 proof map，也不能由该拟合推导单个研究项目必然越做越好。
