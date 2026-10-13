# core #201 PR 发布核验

日期：2026-10-10（Europe/Zurich）。本次范围为创建 PR，不是实现验收或完整代码审计。

已按用户指定标题及 pr201.md 的原文创建 [PR #206](https://github.com/DengZhiyuan-math/proof-cli/pull/206)。

- head：`09e64a365153650cade0579afca52a56028b0f07`，分支 `fix/201-pursuit-events`。
- base：`integ/0021`，merge base 为 `b7f394374ce73e9a23754e12506e87e97326efd9`；对 base 只有一个新提交。
- 远端 head、base、标题及正文已核对。保存的 [正文](approved-body.md) 与用户文件一致；GitHub 正文对比只允许末尾换行归一化。
- PR 状态 OPEN；创建后立即查询尚无 CI 检查结果。本次没有合并、推送、修改 issue 或发布评论。
- 六个新增测试及 core 全套 1037 passed、2 failed、2 skipped 为实现者报告，本次没有重复运行。

下一项仍为 web #10，依赖 core #201 和 agents #17。agents [PR #23](https://github.com/zeqome/proof-agents/pull/23) 当前为 OPEN / `e2d6f9ee570f81e99ccaf69a40315ad46bb9cc96`。

web [PR #13](https://github.com/zeqome/proof-web/pull/13) 已 live 核对为 OPEN / `e4a123abf8f557521fb1eb2a199a97d568c85648`。此前 `de96466` 的审计只对旧 head 有效；新 head 的两项 P2 修复尚待独立复审。Discussion 竞态本次未修改。

证据：`remote-verified.json`、`related-prs-verified.json`、`manifest.json`。
