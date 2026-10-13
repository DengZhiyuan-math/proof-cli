# Acceptance guard read scope：9332369 审计

日期：2026-10-12。固定 head `933236978fa353ba27f9151773f4ed09a6b6a401`，base `integ/0021` = `3dd0a7bde3ad1ea9e040c02b1bff6589a9cf378c`。保留研究者的分支 `fix/0021-acceptance-guard-read-scope` 和原提交，未修改或重写。

## 判断

建议发布独立 PR。修复解决研究者 Acceptance 前置检查的实际性能回退；不是只绕过慢测试。唯一生产改动复用 `@read_scoped`，使这一次检查的上游读取共享已有 memo。两文件、21 行，无新增依赖或缓存实现。

## Standards

0 项发现。生产代码只复用已有 `@read_scoped`，符合简单方案和复用优先规则。guard 仍在 `decide_acceptance` 的写锁事务内执行；scope 绑定当前事务，嵌套 scope 复用，写入及事务边界使用既有失效机制。Blocked、Rejected、review-needed、snapshot dependency 的检查和错误码均未变，角色权限未扩大。

测试复用 `_accepted_chain`、SQL trace 与审阅文件计数，通过公开 `researcher(...).decide_acceptance` 路径执行。20→40 节点、≤2.5 倍阈值与现有性能探针一致。无需要报告的 possible smell，diff 空白检查通过。

## Spec

0 项发现；缺失/部分实现、范围扩大、错误实现均无。完整前置检查加现有 scope，保持 [spec](spec.md) 的所有决策条件、错误码、顺序及研究者 Acceptance 路径。

scope 在写锁内建立；事务身份隔离缓存，同事务嵌套 scope 复用。普通调用在检查返回时释放 scope，后续决定写入不携带该缓存；现有事务边界和 review append 的失效机制不变。回归测试在 setup 完成后才计数实际 SQL/review loader 调用；未替换待测算法或断言装饰器。

## 独立验证

在独立临时 checkout 中运行，原 wtfix 工作树干净并保持原 head。

- 旧 base 加入同一个新测试：**1 failed**，review reads 从 **2166 增至 9126**，超过 2.5 倍；与作者的数字一致。[JUnit](baseline-regression.xml)
- 原提交 9332369：同一回归测试 **1 passed**。[JUnit](fixed-regression.xml)
- 去掉新增 decorator 后，整个 proof_map.py 的 AST 与 base 完全相同。确认检查体、顺序、错误和决策逻辑均未改。[独立检查](independent-checks.json)

本轮独立全套：**1154 passed、15 skipped、0 failed/errors**，196.69 秒。[JUnit](full-suite.xml)、[结果与 skip 原因](full-suite-result.json)。原先失败的三项 LaTeX 测试在本轮均通过；这不改变作者原日志的 1151 passed、15 skipped、3 个 Tectonic sandbox native/network 初始化失败记录。

作者报告的 244→28 秒、51→8.5 秒计时没有在本轮重复测量。没有复测本地 Windows，也没有调用真实模型；Windows 恢复由新 PR 的 CI 验证。

## 原 PR 状态

已回读 core #211 和 proof-agents #28，head/base 与研究者提供的值相同。#28 两项 CI SUCCESS。#211 两项 Ubuntu SUCCESS、两项 Windows CANCELLED；Windows 从 09:46:31Z 至 10:31:38Z，符合约 45 分钟的上限取消。此次修复不改变两份 PR。

修复合入后，应让 #211 在包含修复的提交或新的测试合并结果上触发 CI。重跑旧 run 不等价于验证更新后的代码。本轮不更新 #211 分支或 base，不合并任何 PR。

Standards：0 项发现；Spec：0 项发现。

## 发布

已推送原提交 `9332369` 并创建 [core #212](https://github.com/DengZhiyuan-math/proof-cli/pull/212)，已关联到本对话。base 是 integ/0021，head 与作者原提交完全相同；只有预期两文件和一个提交。PR 标题等于原 commit subject，正文与本地准备文件逐字一致。

[远端记录](publication.json) 确认 PR OPEN、未启用 auto-merge；最后回读时四项 Linux/Windows CI 均 IN_PROGRESS。#211/#28 的 head/base 仍未变化；原 wtfix 工作树干净、head 未变。没有合并、更新原两份 PR 或运行模型试验。
