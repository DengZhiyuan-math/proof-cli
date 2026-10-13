# Acceptance guard read scope：审计与发布范围

来源：研究者 2026-10-12 在本对话提供的诊断与修复。

固定 base：`integ/0021` = `3dd0a7bde3ad1ea9e040c02b1bff6589a9cf378c`。
固定 head：`933236978fa353ba27f9151773f4ed09a6b6a401`。
保留分支：`fix/0021-acceptance-guard-read-scope`。

要求：

1. 给 `_require_awaiting_acceptance_review` 复用现有 `@read_scoped`，使一次 Acceptance 前置检查的上游遍历共享读取；不新增缓存实现。
2. 保持 Blocked、Rejected、review-needed、snapshot dependency 和研究者 Acceptance 的规则及错误码。
3. 新增 `test_a_decision_on_the_top_of_a_chain_grows_linearly_with_it`。通过公开的 researcher decide_acceptance 路径执行，计数 SQL 与审阅文件读取；20→40 节点的读取不得超过 2.5 倍。
4. 保留用户已有提交与分支；只审计、验证并决定发布独立 PR 到 integ/0021，不合并、不修改 #211/#28、不运行模型试验。

研究者报告：旧实现审阅读取为 2166→9126；200-node fixture setup 244→28 秒；100-node 构建 51→8.5 秒。这些时间在独立复验前只按作者报告记录。

研究者全套日志：1151 passed、15 skipped、3 failed；三项失败是 Tectonic 在 sandbox 中的 native/network 初始化崩溃。本次独立检查与作者日志分别记录。
