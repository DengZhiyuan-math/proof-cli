# T8 离线过程报告

生成依据：保存的 JSON/JSONL；未调用模型，未读取或修改项目数据库。输入 SHA-256 见同目录 JSON。
主试验开始：2026-10-11T21:57:43.467541+02:00（Europe/Zurich）。初次失败与后续受控认证场景分别统计。

## 主要发现

- 主试验：40 次 provider 完成，执行失败 0；87.60 分钟。
- 首次 Review 请求：hilbert-space-decomposition，第 15.25 分钟；最终不再是 Provisional。
- 最早请求 Review 且最终仍为 Provisional 的节点：matrix-coefficient-decay-p，第 26.05 分钟。
- 上述时间只表示保存轨迹中的流程交付；本报告未重新验证 snapshot 绑定，也未审定数学正确性。
- 最终 24 个节点、7 个 Provisional proof nodes；主定理 stuck，3 个 Parked；未发生人工 Acceptance 或 Reference review。
- 显式 abandoned attempt 2 条；failed Verifier verdict 1 条，随后出现修正与 passed；这些不能拼成独立数学尝试总数。
- 阅读时间未知。队列规模可以诊断材料组成，不能证明阅读耗时或证据表的收益。

## 队列组成

| 项目 | 条数 |
|---|---:|
| unfixed | 39 |
| parked | 3 |
| imported | 10 |
| provisional | 7 |
| question | 9 |
| 合计 | 68 |

unfixed 拆分为 24 个 statement 和 15 个 Definition。
同一节点可能同时涉及文本确认、证明审阅和问题。68 项不是 68 个互不重叠的数学判断。

优先降低每项寻找来源和理解修改的成本。来源字段覆盖只作诊断；主要收益指标应为人工阅读/核对时间与遗漏发现。

## 执行失败与数学停滞分开

| 场景 | 完成启动 | 执行失败 | input/output token | 数学尝试 |
|---|---:|---:|---|---|
| 主试验 | 40 | 0 | 21,472,006 / 569,653 | 总数未知 |
| 原始首个 Reader | 1 | 1 | 0 / 0 | 认证失败，不作为数学尝试 |
| 受控未登录 Reader | 1 | 1 | 0 / 0 | 认证失败，不作为数学尝试 |

受控结果：`the Reader's turn failed: Not logged in · Please run /login`；API status 仍为 `stuck`，budget spent 为 1。
分类依据是保存的 nonzero exit/is_error 和认证复现，不是零 token 或 subtype success。一次实际启动仍消耗执行预算，本报告没有退款、重试或状态机改动。
主试验 token 的 input 包含 backend cache creation/read 计数；不能据此推定账单金额。

## 节点轨迹

| 节点 | 日志中的 provider turns | Review 时间/分钟 | Verifier pass/fail | 最终 Provisional | Parked |
|---|---:|---|---|---|---|
| complementary-series-model | 7 | 46.07 | 1/1 | 是 | 否 |
| cuspidal-exceptional-finite | 1 | — | 0/0 | 否 | 是 |
| exceptional-cuspidal-finite-per-level | 4 | 63.72 | 1/0 | 是 | 否 |
| height-vs-distance | 1 | — | 0/0 | 否 | 是 |
| hilbert-space-decomposition | 5 | 15.25 | 1/0 | 否 | 否 |
| main-theorem | 1 | — | 0/0 | 否 | 是 |
| matrix-coefficient-decay-p | 4 | 26.05 | 1/0 | 是 | 否 |
| matrix-coefficient-decay-product | 4 | 55.12 | 1/0 | 是 | 否 |
| real-complementary-decay | 4 | 87.33 | 1/0 | 是 | 否 |
| real-unitary-dual-ktypes | 4 | 78.89 | 1/0 | 是 | 否 |
| smooth-vector-exceptional-support-finite | 4 | 66.79 | 1/0 | 是 | 否 |
| sobolev-embedding-cuspidal | 0 | — | 0/0 | 否 | 否 |
| sobolev-embedding-general | 0 | — | 0/0 | 否 | 否 |
| sobolev-embedding-residual | 0 | — | 0/0 | 否 | 否 |

Reader 是项目级 turn，没有伪造归属到某个节点。节点 work log 合计 39 turns，加 Reader 1 turn 为主试验 40。
hilbert-space-decomposition 有较早的 passed verdict/Review 请求，但结构改变后最终不是 Provisional。它说明早期交付与最终可用材料应分别报告。

## 来源与修改的可见性

10 个 imports 全部未 Reference review；其中 2 个带显式 unchecked-source marks。没有 mark 的其余项不自动算已核对原文。
受控 Definition-edit 记录已含 definition_id=D、by=reader-1、role=decomposer、reason=n = 1 is degenerate 和旧→新文本。第一增量是让界面显示现有信息。

## 本报告不能确定

- 人工阅读与修改时间、证据表是否降低核对成本。
- 语义重复 objection 的次数、独立数学尝试总数，以及因果意义上的路线停滞。
- 较早自动换路线能否解决三个 Parked 问题。保存的 objections 是模型报告，未经本次独立数学审定。
- 提示词约束在真实 agent 中的有效率。测试只能检查接线与既有流程。

## 据此作出的下一步判断

先复用 #197 的错误原因/Definition 展示修复，落实 Decomposer 路线约束和 Verifier 清单。证据表与提前换路线机制保持待定。
若要验证证据表，应对少量同一冻结材料做人工定时核对，记录漏项与阅读时间；不以新增字段数作为成功标准。

再生成：`python docs/research/2026-10-12-design-followup/generate_t8_report.py`。
