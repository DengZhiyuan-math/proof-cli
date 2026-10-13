# 论文设计建议：按研究者反馈落实

日期：2026-10-12。主要目标是降低每项审阅的核对成本；阅读时间是主要衡量，字段覆盖只作诊断。

本页保留初次落实的记录。后续发布审计与创建的两份 PR 见 [发布前审计](role-pr-audit.md)；下面的候选基线与测试计数不替代发布 head 的核验。

## 顺序与结果

| 顺序 | 工作 | 本次结果 |
|---|---|---|
| 1 | T8 执行失败与 Definition 说明 | 复用现有 PR，读取最新源码并检查相关行为；没有重复实现 |
| 2 | 替代路线不变成必需依赖 | CONTEXT.md 增加一句定义；Decomposer 共用 brief 增加约束，适用于单独运行和 Pursue |
| 3 | 终稿一致性 | Verifier brief 增加假设/限制、量词/作用域、Conditional 清单；沿用已有 turn 流程 |
| 4 | T8 离线过程报告 | 已生成 Markdown 与 JSON，并记录输入 hashes；没有模型调用 |
| 5 | 证据表与更早换路线 | 保持待定；当前没有阅读时间，报告不能证明两者收益 |

## 第一步已有修复

| 仓库 / PR | 本次固定 head | 内容 |
|---|---|---|
| [core #210](https://github.com/DengZhiyuan-math/proof-cli/pull/210) | `0c3e1f1cf0bd9048d57ab207d76f60fc3a62e1aa` | stale cause；复用一次事件索引，避免逐节点重复历史扫描 |
| [agents #27](https://github.com/zeqome/proof-agents/pull/27) | `544a95f0c27fcb71133a7f0ca421003e34a7ee9c` | 公共 failure_reason，读取真实认证错误而非 subtype success |
| [web #22](https://github.com/zeqome/proof-web/pull/22) | `f1a58ceb576bfdaf615b77791da83ad649e16ba9` | Reader 展示真实失败原因 |
| [web #23](https://github.com/zeqome/proof-web/pull/23) | `deaa8a9b27ee3e355ae30422db56da6910c4983d` | Definition ID、编辑者、原因、旧→新；turn 内同时显示 role 与 actor |

本次查询时这四个 PR 都是 OPEN。[core #197](https://github.com/DengZhiyuan-math/proof-cli/issues/197) 仍为 OPEN，native dependency summary 仍显示 7 个 blockers。没有把这些修复当成已合入主线或已经完成 #197 验收；没有推送、合并、发布评论、关闭 Issue 或重新运行真实研究试验。

原始 Reader 认证失败的启动与主试验分开。实际启动仍可消耗执行预算；nonzero exit/is_error 加认证证据使它不能作为数学尝试或停滞样本。零 token 单独不足以作此判断。修复后的受控场景仍报告 API status=stuck、spent=1：本次没有更改预算或引入自动重试。

## 第二、三步的可审阅改动

- [core glossary 补丁](core-search-route.patch)：CONTEXT.md 一句 Search route 定义，同样已写入当前工作区的 CONTEXT.md。
- [proof-agents 角色补丁](proof-agents-guidance.patch)：只改 `proof_agent.py` 中的 Decomposer/Verifier brief，共 10 行新增、2 行替换。
- [实际渲染的角色说明](rendered-role-briefs.md)：单独 Decomposer、Pursue Decomposer、Verifier。
- [权限对比](role-scope-check.json)：三个 public contexts 的 Claude permission arguments 与基线相同。

core 补丁基于上表 core head；agents 补丁基于上表 agents head。agents 改动位于隔离 checkout `/private/tmp/proof-paper-followup.JQRMD1/agents` 的 `D_m/decomposer-verifier-guidance`，未提交。复验 checkout 的 core 位于同目录 `core`，web 位于 `web`。原 proof-agents 工作区与有并行修改的 proof-web 工作区均未编辑。

约束是合作式 agent 的角色说明，不是检测数学语义的硬门禁。没有给 Decomposer 增加 memory 写权限，也没有改变 Human Review 或现有状态机。测试不能证明真实模型以后必定遵守这些清单。

## 第四步的报告

[过程报告](t8-process-report.md) 和 [机器可读结果](t8-process-report.json) 由 [标准库脚本](generate_t8_report.py) 生成：

```sh
python docs/research/2026-10-12-design-followup/generate_t8_report.py
```

脚本只读保存的 JSON/JSONL，不调用项目 API，不连接模型，不打开项目数据库。9 项输入 hash 均与生成时一致；39 个节点 turns 加 1 个项目 Reader turn，与主试验 40 turns 一致。

主要发现：68 项由 24 个未固定 statement、15 个 Definition、10 个引用、7 个 Provisional、9 个问题和 3 个 Parked 组成。首次 Review 请求为 15.25 分钟，但该节点最终不再 Provisional；最早请求且最终仍 Provisional 的节点为 26.05 分钟。不能用前者替代最终材料的可用性，也不能从这些数值推算人工阅读时间。

## 验证

验证详情见 [verification.json](verification.json)。agents 全套 200 passed；web 的 map home、run pane 和 Pursue/review queue 153 passed；core 的 unfixed text、performance、agent attribution 和 progress 为 80 passed、2 skipped。跳过的两项是未设置 PROOF_BENCHMARK 时关闭的 wall-clock benchmarks。

core 的可选 page tests 使用本机已有的旧 web/agents，具体路径见 [导入路径](core-test-import-paths.json)；最新 web 的上述 153 项则在隔离 checkout、配合固定的新 core/agents 独立验证。这不是三个最新包全套一起运行的结果。

认证展示使用了既有受控复现，其 web #22 / agents #27 heads 本次未变化；不是本次再次调用真实 backend 的结果。core/web 最新 follow-up 的相关测试在本次固定 head 上重新运行。

文档链接、code fences、git diff 空白与保存输入一致性均检查。测试结果是接线与流程证据，不是数学 Acceptance。
