# proof-web PR #13：e4a123a 重新审计

日期：2026-10-10（Europe/Zurich）。[PR #13](https://github.com/zeqome/proof-web/pull/13) 的 head 已核验为 `e4a123abf8f557521fb1eb2a199a97d568c85648`，base 为 `feat/0021-pursue-review-queue`，状态 OPEN。

结论：此前两个 P2 中，冻结依赖的 P2 已修复；警告归属的 P2 仅部分修复。原三条独立探针全部通过，但同一行的分号、逗号反例仍失败，不能把两个 P2 都标为解决。

## 固定版本与范围

| 对象 | Head / 比较 |
| --- | --- |
| 当前 web | `e4a123abf8f557521fb1eb2a199a97d568c85648` |
| 原审计 web | `de964662146afccca83ac88c6f5ae263c78d6360` |
| PR merge base | `864a2c29bd4f41a5344ae7be960b842a1d4aed62` |
| core #199 | `ad479f6d69186105a934d9765a553c48f859ceca` |
| proof-agents | `9558fd0caf6eef2f80401c503a0a4549f4bbaa6f` |

依赖版本与旧审计相同。core [PR #204](https://github.com/DengZhiyuan-math/proof-cli/pull/204) 已 live 核验仍为 OPEN，未假定该依赖已进入 integration。使用 immutable GitHub commit archive 和 `/opt/anaconda3/bin/python`，不修改其他会话的 checkout。

修复差异为 `de96466...e4a123a`，只有一个提交，改动 `review_queue.py` 和 `test_import_review.py`。完整 PR 差异为 `864a2c2...e4a123a`。对应 GitHub compare 结果保存在 `followup-diff.json` 和 `full-pr-diff.json`。源码副本在 `sources/`；版本和源文件校验值在 `manifest.json`、`source-sha256.json`。

## Standards

0 项发现。规范子审计复核了修复差异及完整 PR 差异，未发现违反用户提供的 AGENTS.md 规则或需要提出的 Fowler 代码异味。

修复复用 core 的快照与 Evidence check 接口。分句和 ID 匹配使用标准库 `re`；没有新增依赖、存储结构或推测性抽象。`_marks` 集中处理文本归属；前端复用 `importNotes`。

该结论只覆盖规范及结构，不能代替需求和行为核验。

## Spec

### 已修复：历史警告使用当前依赖而丢失

`source_marks()` 现在遍历节点的 Candidate proofs，并使用每份快照的 `proof.dependencies` 决定它依赖哪个 import 以及是否只有一个 import。当前边新增 R2 后，旧 L v1 的匿名警告仍归属于 R；当前边删除 R 后，旧 M v1 的警告仍保留。

旧快照 `dependencies=None` 时有明确兼容分支，回退到该节点的当前依赖。这一限制由新增测试明确说明。本 P2 的旧探针和新增的增边、删边、旧格式用例均通过。

### P2 仍在：同一句中提及的 import 都被标为 unchecked

原审计要求：“Read the import identity from the clause containing the unchecked mark.” 当前第 126 行只按换行或句号、问号、感叹号后的空白拆分。第 133–134 行仍把一个句子中出现的所有 import 当作 unchecked 的对象。

确定性反例：创建 R、R2 和依赖二者的 L，提交 L 的快照，再记录 Evidence note：

```text
R: checked against the source; R2: unchecked against the source; source unavailable.
```

R 明确是 checked；unchecked 属于 R2。实际 `source_marks(store, "R")` 和 `source_marks(store, "R2")` 各返回一条警告。R 的节点 API、Home pending card 和 review queue 三处也都带上这条错误归属。

逗号形式也失败：

```text
R: checked against the source, whereas R2: unchecked against the source.
```

新增回归只覆盖分开的句子、换行。Evidence notes 没有限制每个 import 必须单独成句，因此上述一行格式没有违反输入要求。这是原 mixed checked/unchecked 归属问题的剩余情况，不是另增一项设计要求。

修复应把 unchecked 短语绑定到它所在分句或明确标注的 import，保留同句其他 import 的 checked 信息。至少加入以上两个用例。规范轴没有额外发现；需求轴保留这一项 P2。

## 验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 原三条独立归属 / 历史快照探针，原文件逐字不变 | 3 passed | `original-attribution-probes.log` |
| 原始页面警告审计探针 | 1 passed | `original-warning-probe.log` |
| 当前 import-review 测试 | 6 passed | `import-review-tests.log` |
| import-review、review card、review queue page、reference link、Pursue queue 相关测试 | 74 passed，包含上述 6 项 | `related-review-tests.log` |
| 旧 de96466 生产源码携带当前回归测试 | 2 failed、4 passed，符合对照预期 | `old-source-new-regressions.log` |
| 新的一行分号 / 逗号归属探针 | 2 failed，均在 R 应无警告的断言上失败 | `clause-attribution-probes.log` |
| GitHub package CI | SUCCESS，仅表示包装检查 | `remote-verified.json` |

旧源码对照使用另一个干净 archive，只复制当前 `test_import_review.py`。两项失败分别是原归属和冻结依赖回归；旧格式兼容用例在旧版也通过。当前版本使这两项回归通过，但一行归属反例仍失败。

74 项相关检查通过后没有扩大或重复全套测试。本次未复跑 web 全套，不能将旧审计的 742 passed、2 failed、1 skipped 转写为当前 head 的全套结果。旧 head 的两个集成失败及全部原始日志仍保留在 `2026-10-09-web9-de96466-evidence/`，本次未判定其原因或是否消失。

检查使用真实 SQLite 项目、快照和 Evidence 服务，以及 DirectClient 和页面 JavaScript harness。没有真实浏览器或 agent provider 验收。

## 重现与记录

原三条探针：

```sh
/opt/anaconda3/bin/python docs/audits/2026-10-10-web9-e4a123a-evidence/probe_attribution.py
```

剩余 P2 的接口反例：

```sh
/opt/anaconda3/bin/python docs/audits/2026-10-10-web9-e4a123a-evidence/probe_clause_attribution.py
```

脚本从 `manifest.json` 选择固定源码，并核对 `review_queue.py` 的 SHA-256。原三条探针文件与旧审计逐字相同，校验记录在 `original-probe-sha256.json`。

本地修复清单已更新为当前 head：历史快照 P2 已解决；归属 P2 部分修复、仍待处理。未修改生产代码、PR、issue、分支或定时任务。

两轴汇总：Standards 0 项；Spec 1 项，最高为 P2 的分句归属错误。
