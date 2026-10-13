# PR #13：匿名子句警告丢失的本地修复

本地提交 `83dbc43f33e0dfdb5c9fb27bca0b39422283aac4`，父提交 `85653cc5f16a86435407e09b870489ffeff1cffd`。分支仍为 `D_m/fix-13-warning-attribution`，使用原独立 checkout `.claude/worktrees/codex-web13-clause-e03ye4jt/proof-web`。只修改 `src/proof_web/review_queue.py` 和 `tests/test_import_review.py`。工作树干净。

按用户要求保持未推送。PR #13 仍为 OPEN，head `e4a123abf8f557521fb1eb2a199a97d568c85648`，base `feat/0021-pursue-review-queue`，见 [远端核验](remote-verified.json)。[85653cc 的独立复核](../2026-10-10-web13-85653cc-review/README.md)、此前证据目录和其他会话的 checkout 均未修改。

## 行为

先保留句子边界，再在句内分隔检查子句。unchecked 子句的归属按以下顺序确定：

1. 该子句点名的 import。
2. 如果该子句没有点名，则使用同句点名的 import。
3. 如果同句也没有点名，则使用快照的单 import 兜底。

因此，下列两条 note 都保留 R2 的警告，R 没有警告：

```text
Unchecked against the source; R2's paper could not be opened.
R2's statement differs from the cited version; unchecked against the source.
```

具名 unchecked 子句仍优先于整句中的其他名称。句子兜底不会读取其他句子的名称。冻结 dependencies、旧快照回退和完整 note 保留逻辑沿用原实现。

同时修复已有的短写错配：`R: checked, R2: unchecked against the source.` 及其反向顺序。逗号检查边界现在识别独立的 checked/unchecked 单词。共同警告 `R, R2: unchecked ...` 和 `e.g.` / `i.e.` 的处理仍通过原测试。无新增依赖。

## 验证

固定依赖仍为 core #199 `ad479f6d69186105a934d9765a553c48f859ceca` 和 agents `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f`。新增五个场景：两条警告丢失反例、一个句子边界保护、两种短写顺序。两条警告丢失测试同时验证服务、节点 API、pending card 和 review queue，检查警告归属、快照和完整 note。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 六个相关测试文件，包括全部 21 个 import-review 场景 | 167 passed | [日志](related-review-final.log) |
| 复核者的十条探针、五条子句服务/API 探针、一条原始警告探针 | 16 passed | [日志](independent-probes.log) |
| `85653cc` 生产源码配当前测试文件 | 5 failed、16 passed | [日志](control-85653cc.log) |
| `e4a123a` 生产源码配当前测试文件 | 11 failed、10 passed | [日志](control-e4a123a.log) |
| 补丁空白检查 | `git diff --check` 通过 | [增量补丁](changes-from-85653cc.patch) |

`85653cc` 的五项失败为两条丢失反例、句子边界组合反例和两种短写错配。两条丢失反例在 `e4a123a` 上通过，确认它们是 85653cc 的回归。对照在新建临时目录运行，只复制当前测试文件，没有改动旧版本证据或原 checkout。

复核者探针只调整 checkout 路径及源码 hash 校验，所有函数体保持一致。TDD 的 red/green 日志、源码副本、SHA-256、命令和固定依赖路径见 [manifest](manifest.json)。[相对远端 e4a123a 的完整补丁](changes-from-e4a123a.patch)包含两次本地修复。

本提交未重跑 proof-web 全套。复核者报告的 738 passed、1 skipped 和 19 项端口绑定受限仍属于 `85653cc`，不能算作本提交的全套验收。浏览器及真实 provider 验收没有新增证据。未推送、评论或合并 PR。
