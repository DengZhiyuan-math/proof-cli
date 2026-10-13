# T8 修复审计（macOS，2026-10-12）

审计覆盖六个已推送的修复分支。发现两项 P2，分别属于 Standards 和 Spec。没有发现 P1。Reader 登录错误、Warnings 的 stale 原因和未知设置键提示通过本轮检查；studio 的编辑者显示仍不完整。

## 固定范围

| 仓库 | 分支 | 审计 head | 比较基线 | 远端状态 |
|---|---|---|---|---|
| core | fix/197-stale-cause | 6d5cd700812f78b571693231bb629abefec53b65 | 3dd0a7b | PR #210 OPEN |
| agents | fix/reader-failure-reason | 544a95f0c27fcb71133a7f0ca421003e34a7ee9c | 3ff0a71 | PR #27 OPEN |
| agents | fix/studio-unknown-keys | f3735c3c20fe576be3fe650a5052e3618883937a | 3ff0a71 | 无 PR |
| web | fix/reader-failure-reason | f1a58ceb576bfdaf615b77791da83ad649e16ba9 | b815719 | PR #22 OPEN |
| web | fix/stale-cause | f3a51d5f609ab5166ef6bf975191daa8dd097cdd | b815719 | PR #23 OPEN |
| web | fix/studio-unknown-keys | 04f6cfe1f8f75646d319f214ee8303de802607a5 | b815719 | 无 PR |

结束前再次读取 GitHub，六个 head 均未变化。已有四个 PR 的 Linux／包检查通过；Windows 不作为本次 macOS 审计的门槛。`manifest.json` 保存完整远端元数据。

测试使用独立临时克隆组合六个修复。原分支和原工作区未被修改。web 的生产代码自动合并；`tests/test_pursue_review_queue.py` 的末尾追加测试发生一处冲突，保留两侧完整测试后运行。没有为让检查通过而修改断言。`local-candidate.json` 固定输入提交、临时路径和组合 tree。

## Standards

**[P2] stale cause 每个节点重读完整事件历史。**

core `proof_map.py:4055–4061` 为每个 stale 节点调用 `_rests_on`，收集 Definitions，再遍历 `list_events(store)`。仓库已有 `restated_at`／`_text_changes`（922–982）按一次 read scope 建立索引。web `server.py` 在每个节点的序列化中增加了 `get_stale_cause` 调用，因此 stale 节点多时会重复读取历史。

这违反用户 AGENTS.md 第 2 条的复用优先要求；同时属于有证据支持的 possible Duplicated Code，后者是判断性 code smell，不单独计数。

macOS 上的可复现领域读取探针：100 个 stale snapshot、3,000 条无关 progress 事件，共 3,203 条历史。三次测量中，integrity-only 中位数 0.1105 秒；integrity + cause 为 1.5732 秒，增加 1.4627 秒，约 14.24 倍。历史扫描次数从 1 增至 101，解析事件记录从 3,203 增至 323,503。

此测量证明热读取的重复成本。它不是完整 HTTP 延迟、生产 SLA 或 P1 的证据。建议让现有一次读取索引保留最新事件元数据，同时供时间和原因读取复用。

证据：[探针](standards-performance-probe.py)、[结果](standards-performance.json)、[固定源码](reviewed/core-stale/src/proof_cli/proof_map.py)。

本轴共 1 项发现，最高优先级 P2。其余修复复用现有 TOML 解析和失败原因逻辑，没有新增依赖，也没有改变数学 Acceptance 的研究者权限。

## Spec

**[P2] agent turn 中的 restatement／Definition edit 仍缺少编辑者。**

需求明确说 studio work log 要显示「who, why and the old → new text, the same as proof node progress does」。web `static/studio/run.js:276–281` 的 `changeLine` 不输出 `e.by`；288 行有 `e.role` 时只显示角色，替换了编辑者。

core 的真实 `work_log` 会给当前 turn 的同一 actor 所做的操作添加 role。本次通过官方 API 记录一个 `by=reader-1`、`role=decomposer` 的 turn，在其中编辑 Definition D。存储日志同时有 `by` 和 `role`；Chrome 中实际只显示 `Decomposer definition D edited — …`，没有 `reader-1`。原因和旧 → 新文本已经显示。Warnings 同时正确显示 Definition D、reader-1 和原因。

新增页面测试的事件没有 role，且没有断言编辑者，因此没有覆盖此场景。建议在工作日志中同时显示 role 和 actor，并覆盖 turn 内编辑。

证据：[存储日志](definition-work-log.json)、[浏览器文本](studio-browser.txt)、[截图](studio-browser.png)、[固定源码](reviewed/web-stale/src/proof_web/static/studio/run.js)。

本轴共 1 项发现，最高优先级 P2。其余需求在代码和相关检查中符合说明：失败原因复用、旧依赖回退、stale 原因优先级和传递范围、CLI JSON 字段、未知顶层／budget 键、profile 环境提示、条件分组与侧栏计数。

## 独立验证

macOS ARM64，Python 3.11.14。`loaded-sources.json` 确认导入组合候选的四个包。没有使用 sandbox 的端口失败作为产品结论。

| 检查 | Passed | Skipped | Failed/errors |
|---|---:|---:|---:|
| core 相关六个测试文件 | 157 | 2 | 0 |
| agents 全套 | 202 | 0 | 0 |
| web 全套 | 822 | 1 | 0 |
| 新 web + 已发布旧 core／agents 的相关文件 | 152 | 2 | 0 |

组合检查共 1,181 passed、3 skipped。另有兼容检查 152 passed、2 skipped、1 deselected。旧依赖回退测试有意排除需要新 agents 才能实现的新 Reader 文本断言；独立 stand-in 检查确认旧 agents 的 Reader 回退仍返回 `success` 而不崩溃，未知设置回退为空。跳过的项目和原因保存在 `skips.json`。这是相关 core 文件检查，不是完整 core 套件重跑。

web 全套包含之前 sandbox 阻止的全部 19 个端口测试，本次逐项从 XML 确认 passed。详见 `native-port-cases.json`、各 XML 和日志。

### 真实未登录 Reader

新项目只有一个简单 `library/main.tex` 数学输入；启动前空 profile 的 `claude auth status` 显示 `loggedIn=false`。profile 通过服务器环境 `CLAUDE_CONFIG_DIR` 设置，没有更改已有认证或全局配置。在 Chrome 中首次点击 Pursue，使用实际 Claude backend，没有替换 provider。

唯一的实际 turn 返回 exit 1、`is_error=true`、subtype `success`、空 stderr；usage in/out 均为 0。页面和 API 均显示 `the Reader's turn failed: Not logged in · Please run /login`。见 `empty-profile-auth.json`、`logged-out-reader-events.jsonl`、`logged-out-reader-result.json` 和 Reader 截图。

### Definition 和 Project settings

- Warnings 为直接引用 D 的 C 和依赖 C 的 L 均显示 Definition ID、actor 和原因。
- 未知 `claude_config_dir`、`budget_turn`、`budget.minute` 显示在 Project settings 中，Claude 项附正确环境提示。
- 侧栏计数为 5：2 个 stale 节点 + 3 个设置警告。
- 仅从隔离项目移除三个未知键后，分组隐藏，侧栏计数降为 2；两个 stale 节点仍显示正确原因。
- studio 显示 Definition ID、原因和旧 → 新文本，但 turn 内 actor 缺失，故此部分验收不通过。

`browser-checks.json`、浏览器文本和截图保留上述证据。

## 审计边界

本次没有运行两个 PR 创建脚本，没有发布审计评论、提交代码、推送或合并，也没有关闭 #197。两项原 T8 场景在未合并的组合候选上复核；此记录不能替代未来实际合并 head 的验收，也没有重跑原 40-turn 研究试验。

审计 harness 的两个环境问题已留明：agent-browser 的 socket 目录在 sandbox 内不可写，转用本次独立会话的 native 执行；初版 fixture 给 ReviewServer 传入端口却未匹配项目的 pinned origin，导致连接失败／421，改为使用项目 pinned 端口后才开始有效浏览器检查。它们没有计为产品问题。

`cleanup.json` 记录本次服务和临时 Chrome 已停止。项目状态、原始分支、源码、截图、日志和审计探针均保留。#197 仍为 OPEN。
