# proof-web #12：释放失败后的 Stop 重试

日期：2026-10-09。审计对象为 `f0ea4a7d1d99716f06356479bceea0771cc2f7c7`。

结论：本次未发现新的重试控件缺陷。页面和服务器的相关测试通过。浏览器验收按用户选择保留为待办，因此不能宣称 issue #12 已完整验收。

[PR #15](https://github.com/zeqome/proof-web/pull/15) 已按用户给定的标题和正文创建。base 为 `feat/0021-pursue-review-queue`。head、正文和 package CI 已核验。正文保留提交者当时未完成浏览器验收的说明。本次没有合并、推送或发布评论。

## 固定版本

| 包 | Head | 用途 |
| --- | --- | --- |
| proof-web | `f0ea4a7d1d99716f06356479bceea0771cc2f7c7` | 审计对象 |
| proof-web | `864a2c29bd4f41a5344ae7be960b842a1d4aed62` | 旧生产源码对照 |
| proof-agents | `e2d6f9ee570f81e99ccaf69a40315ad46bb9cc96` | PR #23，提供 release-failed 和 stopping |
| proof-agents | `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f` | 旧接口兼容对照 |
| proof-cli | `b7f394374ce73e9a23754e12506e87e97326efd9` | 固定 integration 依赖 |

源码从 GitHub 的指定 commit archive 提取，不改动其他会话的 checkout。Python 为 `/opt/anaconda3/bin/python`（3.11）。归档路径见 [manifest.json](manifest.json)。审计源码副本及 SHA-256 见 `sources/`、`agents17/` 和 [source-sha256.json](source-sha256.json)。

## 行为与测试

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 页面与 Pursue 服务器测试 | 46 passed | [targeted.log](targeted.log) |
| 相同 web 源码，旧 agents `9558fd0` | 44 passed、2 skipped | [older-agents.log](older-agents.log) |
| 旧 web 生产源码，当前新测试与 harness | 5 failed、41 passed，符合对照预期 | [base-production-new-tests.log](base-production-new-tests.log) |
| agents PR #23 全套 | 162 passed | [agents17-full-suite.log](agents17-full-suite.log) |
| 重试 Stop 尚未返回时的新 Start | PURSUIT_ACTIVE；T2 启动次数为 0 | [probe_pending_retry.log](probe_pending_retry.log) |
| 预算结束与另一调用者释放重叠 | COORDINATOR_ACTIVE；T1 保持 current，T2 启动次数为 0 | [probe_concurrent_release.log](probe_concurrent_release.log) |
| 全套 web 测试 | 753 passed、1 skipped；无失败或端口错误 | [full-suite.log](full-suite.log)、[full-suite.xml](full-suite.xml) |

页面测试覆盖 release-failed 时显示 Stop、隐藏 Pursue，包括 can_pursue 为 true 的输入；重复失败后重新读取状态；成功释放后的控件；释放进行中的 stopping 状态；其他状态的既有控件。

服务器测试使用真实 `ProjectPursuit` 和 `StudioHub`，配合 `_HeldCoordinator` 测试替身。释放前两次返回 RELEASE_FAILED，第三次成功。每次失败后 current 仍为 T1，stopping 与 can_pursue 均为 false；Start 被拒绝。另一测试用 Event 暂停释放，确认进行中为 stopping。没有使用真实 agent provider。

旧生产源码对照保留 `864a2c2` 的 `app.js` 与 `studios.py`，仅携带当前测试及 JavaScript harness。失败为四个页面用例和一个服务器用例。慢释放用例在旧版也通过，它保护既有行为。

## agents #17 依赖复核

此前 `fddd978` 的两项 pending-release 审计发现，已在当前 `e2d6f9e` 上复核通过。新实现先进入 stopping，释放返回前拒绝 Start；遇到 COORDINATOR_ACTIVE 时等待正在进行的释放。完整 agents 测试和两项独立 Event 探针通过。

本目录保留本次探针；原 `2026-10-09-pr23-fddd978-evidence/` 的失败证据未修改。并发释放探针把预算触发设置为 run 已结束且保留 claim，与本次依赖的回归测试一致；去掉原先等待错误启动 T2 的触发等待，保留释放未完成时 T2 必须为 0 的断言。依赖改动见 [agents17-followup-compare.json](agents17-followup-compare.json)。

## 全套 web 测试

上次会话中断时，全套测试只留下部分输出，没有结果；该输出保存为 [full-suite-interrupted.log](full-suite-interrupted.log)，未计为通过。重新运行在上述固定版本上完成，结果为 **753 passed、1 skipped，246.75 秒**。完整日志与 JUnit XML 已保存。没有端口绑定错误，也没有 Coordinator 超时。

提交者报告的两项偶发失败在这次全套运行中均未出现。Coordinator 超时的原因仍未定位，不能由一次通过断言问题消失。Discussion 的空回复现已另用确定性探针复现，见下节。该探针是单独审计检查，不属于以上 754 个全套测试用例。

## P2：Discussion 返回完成状态与旧回复的组合（基线已有）

`StudioHub.discussion_view()` 先在第 896 行读取数据库记录，再在第 904 行读取 `_discussion_live`。若完成线程在两次读取之间写入最终回复并清空 live，返回值会同时包含 `running=null`、`ended=false` 和空回复。调用者 `_settled()` 只检查 running，因此会把这个响应作为最终回复。这能产生提交者报告的 0 / 9000 字符症状。

Event 探针使用既有 stub Claude、真实 discussion API 和完成线程。它让 API 先读取 started 记录，然后允许完成线程写入并清空 live，最后返回已读的旧记录。触发不使用 sleep。输出为：view 的回复长度 0；数据库记录已 ended，保留 4000 字符摘要；完整 transcript 已存在。

相同探针在当前 `f0ea4a7` 和旧生产源码 `864a2c2` 均按预期失败，证明基线也有这个竞态。`discussion_view()` 的方法源码逐字相同。这比 2/28 与 0/27 的重复频次更直接地界定了已有缺陷。它不能证明此前某次失败一定采用了这条交错，但可以确定性产生相同症状。

最小修复方向是先观察完成状态，再读取该完成状态对应的记录，并检查启动失败等其他清空 live 的路径。可复用 agents #15 的读取顺序经验；本次不修改 Discussion 生产代码，不把这个既有问题当作 PR #15 新增缺陷。

证据：[探针](test_discussion_snapshot_probe.py)、[当前 head 输出](discussion-snapshot-web.log)、[基线输出](discussion-snapshot-baseline.log)、[方法源码比较](discussion-view-source-comparison.json)。

## 浏览器验收

工具环境通过 `open -na "Google Chrome"` 无法找到该应用。9223 的 CDP 端点在有界等待后仍不可用。agent-browser 技能要求端点不可用时停止并请求手动启动 Chrome。

用户随后明确选择：“先完成审计和 PR，保留浏览器验收待办”。本次没有启动浏览器、连接页面或进行真实 provider 验收。JavaScript harness 和服务器测试不能替代这个验收项。详见 [browser-status.json](browser-status.json)。

后续浏览器检查应使用隔离项目，记录实际 provider 或 fixture，并依次确认首次失败、重试控件、第二次失败和最终成功释放。
