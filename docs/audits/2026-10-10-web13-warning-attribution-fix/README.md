# PR #13：警告归属本地修复

本地提交为 `85653cc5f16a86435407e09b870489ffeff1cffd`，分支为 `D_m/fix-13-warning-attribution`。父提交为 PR #13 的 `e4a123abf8f557521fb1eb2a199a97d568c85648`。独立 checkout 在 `.claude/worktrees/codex-web13-clause-e03ye4jt/proof-web`。只修改 `src/proof_web/review_queue.py` 和 `tests/test_import_review.py`。

本地修复已通过下面的检查。尚未推送；GitHub 的 PR #13 仍为 OPEN，head 仍为 `e4a123a`，base 为 `feat/0021-pursue-review-queue`。见 [远端核验](remote-verified.json)。本记录不替换原 head 的审计证据。

## 改动

警告现在按检查子句读取。分号分隔子句。逗号只有在前一段已有 source check、后一段开始另一条具名 source check 时才分隔。此规则覆盖直接连接，以及 `whereas`、`but`、`while` 连接。`R, R2: unchecked ...` 保留共同归属。`e.g.` 和 `i.e.` 的句点不分隔子句，后面的具名 import 仍参与归属判断。

冻结 dependencies 的选择逻辑、匿名警告的单 import 兜底规则和完整原始 note 均沿用原实现。实现只使用标准库。

新增 10 个测试场景：两种分号顺序、五种逗号连接、两种缩写和一个共同归属。七个 P2 场景和两个缩写场景在旧生产源码上失败。共同归属是保护原行为的测试，旧源码也通过。

## 验证

固定依赖为 core #199 `ad479f6d69186105a934d9765a553c48f859ceca` 和 agents `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`。

| 检查 | 最终结果 | 证据 |
| --- | --- | --- |
| import review、review app、review decisions、review card、Home 和 review queue | 162 passed，包含全部 16 个 import-review 场景 | [日志](related-review-final.log) |
| 三条原始归属探针、五条子句探针、一条原始警告探针 | 9 passed | [日志](independent-probes.log) |
| `e4a123a` 生产源码配本次测试文件 | 9 failed、7 passed，失败均为预期反例 | [日志](baseline-current-regressions.log) |
| 补丁空白检查 | `git diff --check` 通过 | [补丁](changes.patch) |

子句探针同时断言服务、节点 API、pending card 和 review queue：R 没有警告，R2 保留一条警告及其 dependent、snapshot、current 和完整 note。三条原始归属探针与此前文件逐字节相同。

TDD 各阶段的 red/green 日志保存在本目录。`import-review-final.log` 是中间 13 个场景的结果；最终验证以 `related-review-final.log` 为准。源码副本、SHA-256、依赖路径和运行命令在 [manifest](manifest.json)。旧源码对照使用单独的临时目录，未修改原审计 archive 或其他会话的 checkout。

本次未运行修复提交的全套 proof-web 测试。其他会话报告的 `e4a123a` 全套结果仍属于旧 head。浏览器和真实 provider 验收没有新增证据。未修改 Discussion，未推送、评论或合并 PR。
