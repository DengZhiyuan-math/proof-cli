# 最新修复审计：core #220、agents #30、web #25

审计日期：2026-10-13，Europe/Zurich。结论：**仍有 1 项 P1、2 项 P2；建议修复后再合并。**

范围按研究者选择：三个 PR 相对各自 master 的全部修复。源码在独立副本中固定，未更新有未提交文件的主工作区。审计结束时重新读取远端；三个 head/base 均未变化，PR 均为 OPEN / Draft。

| 仓库与 PR | 固定 base | 固定 head | 本轮离线测试 |
|---|---|---|---|
| [core #220](https://github.com/DengZhiyuan-math/proof-cli/pull/220) | `d433159214156239e31094d1eaea3b7b991b927f` | `c55be72e08735d94c438fbc1f61cb2f4d013f627` | 1172 passed，15 skipped |
| [agents #30](https://github.com/zeqome/proof-agents/pull/30) | `7d3f312269b9868415e06302b97637db1a490220` | `528f2235771320241bcb2e171d2a293404fce45b` | 229 passed |
| [web #25](https://github.com/zeqome/proof-web/pull/25) | `af687b02b7d03dbf5bd2b60062284d8421dfa5c0` | `5667befee615dfdbd7336affd6c069b799e84ebc` | 839 passed，1 skipped |

共 **2240 passed、16 skipped、0 failed、0 errors**。这些测试通过，但未覆盖下述反例。本轮新增三个独立探针，使用真实 core 状态和 CLI；Pursue 的 Coordinator 使用替身。没有真实 provider 或模型调用。

## Standards

1. **[P2] 废弃路线的后代仍阻塞 Pursue。** [coordinator.py:1050](https://github.com/zeqome/proof-agents/blob/528f2235771320241bcb2e171d2a293404fce45b/src/proof_agents/coordinator.py#L1050) 只排除直接脱离父节点的 Claim。真实映射 `T→{C1,C2}`、`C1→{D1,D2}` 删除 `T→C1` 后，C1 被排除，但 D1、D2 仍被视为未覆盖节点。连续两次 Start 都返回 Stuck，Coordinator 启动次数为 0。违反 [ADR-0023 第 4 点](https://github.com/DengZhiyuan-math/proof-cli/blob/c55be72e08735d94c438fbc1f61cb2f4d013f627/docs/adr/0023-reader-pursue-and-review-corrections.md#L16) 的历史路线不阻塞规则。应按废弃路线判断后代，同时保留其他活动路线使用的节点。证据：`probe_nested_abandoned.py`、`probe_nested_abandoned.json`。

2. **[P2] Agent 仍能把工作日志归属写成 human。** [cli.py:1214](https://github.com/DengZhiyuan-math/proof-cli/blob/c55be72e08735d94c438fbc1f61cb2f4d013f627/src/proof_cli/cli.py#L1214) 未复用新增 `_author` 检查。设置 `PROOF_AGENT_ROLE=prover`、`PROOF_AGENT_NAME=worker` 后，`node progress T --plan … --by human` 成功；仅设置 ROLE 时，默认归属也为 human。真实持久日志均记录 `role=prover、by=human`。违反 [ADR-0023 第 2 点](https://github.com/DengZhiyuan-math/proof-cli/blob/c55be72e08735d94c438fbc1f61cb2f4d013f627/docs/adr/0023-reader-pursue-and-review-corrections.md#L14) 的作者归属规则，以及 AGENTS.md 的复用规则。影响审计归属；未观察到因此获得 Acceptance 或 Reference review 权限。该路径是既有遗漏；本次新增统一归属规则和检查仍未覆盖它。证据：`probe_progress_attribution.py`、`probe_progress_attribution.json`。

共 2 项文档标准违规，最严重为 P2。未发现需要单独报告的启发式代码异味。

## Spec

1. **[P1] Agent 名称与研究者身份相同，可绕过新身份保护及覆盖检查。** ADR-0023 第 2 点要求 agent 不以 `human` 记录其工作，不满足研究者的 Trust rules；第 4 点要求每个 agent 创建的活动本地节点被所选 Theorem 覆盖。[core cli.py:287](https://github.com/DengZhiyuan-math/proof-cli/blob/c55be72e08735d94c438fbc1f61cb2f4d013f627/src/proof_cli/cli.py#L287) 只比较名称是否相等。合法配置 `[studio] agent_name = "human"` 经实际 `ProofAgentContext.env()` 执行导入后，仍保存 `created_by="human"`。在探针临时项目已声明的 textbook Trust rule 下，该未审核结果得到 `trusted-by-rule`。

   [web studios.py:601](https://github.com/zeqome/proof-web/blob/5667befee615dfdbd7336affd6c069b799e84ebc/src/proof_web/studios.py#L601) 将 `human` 或项目 git 身份归为研究者。实际 `ReaderContext.env()` 与 CLI 创建的未连接 Lemma 因名称相同得到 `by_agent=false`，公开 Pursue API 返回 Done，并误称该节点为研究者自己的工作。普通 `reader` 对照返回 Stuck，且无 Coordinator 启动。web 的整库 Reader 实际使用默认名称 `reader`；该 Reader 名称反例通过公开 Context/API 注入。配置为 `human` 的 Prover 导入则经过实际配置读取路径。

   名称可配置及旧 Trust 歧义是既有行为；本次新增 `by_agent` 豁免引入完成状态绕过，新 `_author` 限制仍未封住该 Trust 歧义。应拒绝 agent 名称与保留研究者身份冲突，或独立记录主体类型。证据：`alias_probe.py`、`alias-root-rerun.json`。探针中的 Trust rule 只在临时项目创建；未提交研究项目的 Review 或 Acceptance。

共 1 项需求缺陷，最严重为 P1。未发现其他已证实的遗漏或未授权范围扩张。Reader 目标规则、失败 Coordinator 汇总、Ask/Review-now 未确认标签均已落实；真实数学目标识别仍未验证，符合 ADR 明示限制。

## 验证与证据边界

- 在 Python 3.11 独立 venv 中安装四个固定源码副本，确认实际加载路径。各仓库运行 `python -m pytest -q --junitxml=<repo>-pytest.xml`。完整结果与跳过原因见三个 XML 和 `validation-results.json`。
- 远端 core 的 Ubuntu 3.11/3.12、agents 两项 CI、web package 均通过。core Windows 两项 CI 在最终读取时仍在运行。web package CI 不等于其完整测试套件。
- 重新核对 #197 首轮保全清单：134 个捕获文件全部与清单哈希一致，聚合 SHA-256 为 `12f3749b60e8fa08086b191003cca45aefbc14ce24188e93641df2dce9a9ee5e`。清单包含 130 个运行相关文件和 4 个后续诊断文件；不是完整运行开始环境清单。
- PR 正文与 revision-3 保全记录中的联动测试对应此前的 `f77d902 / 30b4250 / 2abb86f`。本报告另行验证最新三个 head，不将旧证据冒充最新提交的验证。
- #197 与 #132 均为 OPEN。未更改 trial 服务、包版本固定值、旧项目或历史审计文件。未 push、评论、合并、关闭 issue、启动 run2 或提交研究项目 Acceptance。
- 本次验证没有真实文献检索或数学目标识别证据，也没有新的浏览器视觉验收。不得据此宣布 macOS 成熟或研究证明已被接受。

独立审查按 Standards 与 Spec 两轴执行。已通过的测试与上述具体反例分开记录。主工作区只新增本审计目录。

复现环境：`/private/tmp/proof-latest-audit-20261013-01a13595/`。源码副本为其中的 `core/`、`agents/`、`web/`；解释器为 `venv/bin/python`。探针与其结果已复制到本目录。别的机器需先取得表中固定提交，并调整 `alias_probe.py` 中的测试辅助模块目录。
