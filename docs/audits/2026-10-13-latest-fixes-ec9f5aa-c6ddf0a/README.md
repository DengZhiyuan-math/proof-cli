# 固定版本复审：ec9f5aa / c6ddf0a / 5667bef

日期：2026-10-13，Europe/Zurich。**上一轮三个问题已修复；本轮发现两个新的 P2 边界缺陷。条件合并的门槛未通过。**

用户要求独立审计通过后按 core → agents → web 合并。三个 PR 仍为 OPEN / Draft；本轮未标记 Ready、合并、推送或修改远端评论。run2、固定版本更新及 trial venv 重建均未执行。

| 仓库与 PR | 审计 head | 比较 base | 最新 CI | 本轮联动离线测试 |
|---|---|---|---|---|
| [core #220](https://github.com/DengZhiyuan-math/proof-cli/pull/220) | `ec9f5aacb18805ad88b0b3923d17f773fa38cd7c` | `d433159214156239e31094d1eaea3b7b991b927f` | Ubuntu / Windows × 3.11 / 3.12，四项 SUCCESS | 1175 passed，15 skipped |
| [agents #30](https://github.com/zeqome/proof-agents/pull/30) | `c6ddf0a3d22e80f0190349064343cc79945c81d3` | `7d3f312269b9868415e06302b97637db1a490220` | 3.11 / 3.12，两项 SUCCESS | 230 passed |
| [web #25](https://github.com/zeqome/proof-web/pull/25) | `5667befee615dfdbd7336affd6c069b799e84ebc` | `af687b02b7d03dbf5bd2b60062284d8421dfa5c0` | package SUCCESS | 839 passed，1 skipped |

累计改动按各自 base...head 审查；重点独立复查上一轮以来的 core / agents 新提交。web 没有新增提交，其源码与新 core / agents 一起运行。结束时重新读取远端，head/base 与表格完全一致。

## 上一轮三个反例

- 废弃 C1 的 D1 / D2 后代：原探针在新包上连续两次 Done，Coordinator 启动两次。旧的永久 Stuck 不再出现。
- `node progress --by human`：原探针被 `AGENT_AUTHOR_REFUSED` 拒绝。仅有角色标记时，默认归属为 `prover`，不再为 human。
- 正确 project Context 下的研究者身份重名：原 alias 探针在其原本断言“创建成功”的位置停止，返回 `AGENT_AUTHOR_REFUSED`。补充观察探针分别验证 human、项目 git 身份及实际配置为 human 的 Prover 导入；全部拒绝，未产生相应节点。普通 reader 对照仍可写入。

原探针的退出码按其断言解释。alias 原探针退出 1 在这里是旧漏洞被拒绝的证据，不是产品测试失败。见 `original-probe-results.json` 与 `identity-controls.json`。

## Standards

独立 Standards 审查发现 2 项文档约束违规，均为 P2；与 Spec 轴发现重合。没有独立代码异味。

1. **[P2] 历史路线掩盖活动共享依赖。** [agents coordinator.py:1054](https://github.com/zeqome/proof-agents/blob/c6ddf0a3d22e80f0190349064343cc79945c81d3/src/proof_agents/coordinator.py#L1054) 排除废弃路线的全部依赖，仅用所选 Theorem 的闭包判断活动使用。探针中 detached `old→D` 与活动研究者 `aside→D` 共用 Reader 创建的 D，两次 Start 都返回 Done；删除历史 `old→D` 后才返回 Stuck，命名 D。违反 [ADR-0023 第 4 点](https://github.com/DengZhiyuan-math/proof-cli/blob/ec9f5aacb18805ad88b0b3923d17f773fa38cd7c/docs/adr/0023-reader-pursue-and-review-corrections.md#L16)：只有废弃路线专用的依赖才属于历史记录。应保留活動旁支使用的节点参与覆盖检查。

2. **[P2] 身份检查未绑定实际项目根。** [core cli.py:303](https://github.com/DengZhiyuan-math/proof-cli/blob/ec9f5aacb18805ad88b0b3923d17f773fa38cd7c/src/proof_cli/cli.py#L303) 从 PROOF_ROOT 或 cwd 读取 git 身份，忽略已解析的 `--root`。探针设置 agent 的角色和名称，不设置 PROOF_ROOT，通过 `--root target` 成功以 target 的研究者身份创建未连接 Lemma；公开 Pursue API 返回 Done，将它列为研究者自己的工作。违反 ADR-0011 的统一根约定及 ADR-0023 的保留身份规则。应复用命令已解析的项目根。实际 ReaderContext(PROOF_ROOT=target) 对照正确拒绝；未观察到 Trust rule 或 Acceptance 权限提升。

## Spec

独立 Spec 审查发现 2 项 P2。

1. **[P2] 活动共享依赖被废弃闭包隐藏。** ADR-0023 第 4 点仅豁免 “the nodes only they rest on”。agents coordinator.py:1054–1059 排除全部废弃依赖闭包。真实 map 中，废弃 old Claim 与活动 human standalone aside 同时依赖 reader 创建的 Lemma D；T 未覆盖 D。公开 Pursue 连续两次返回 Done。仅删除历史 old→D 后，对照组返回 Stuck，命名 D，且不启动新的 Coordinator。应保留仍被活动路线使用的共享依赖。

2. **[P2] 公有 `--root` 路径检查错误项目的研究者身份。** ADR-0023 第 4 点将项目 git 身份定义为 “names no agent may write under”。core cli.py:299–303 读取 PROOF_ROOT 或 cwd，忽略本次解析的 `--root`。target 与 cwd 身份不同、未设 PROOF_ROOT 时，reader 能以 target 研究者身份创建 X；公开 Pursue 随后返回 Done，并误称 X 为研究者自己的工作。应检查 store.root。实际 ReaderContext.env() 对照拒绝该名称；**正常 host run2 使用正确 PROOF_ROOT，此反例不是其运行回归，也不是安全沙箱逃逸。**

未发现其他已证实遗漏、范围扩张或新增 Acceptance / Reference-review 权限。真实数学目标识别与文献检索仍需试验。两个轴的发现保留原分类；它们指向同样两个独特缺陷，不是四个缺陷。

## 复现与验证

反例由 Spec 审查生成，主审又在新的临时项目中独立执行相同脚本；结果一致。`spec-probes/probe_spec.json` 与 `spec-probe-independent.json` 分别保存两次输出。

共享依赖的简图：

```text
T ──→ current               所选 Theorem 的活动路线
old ──→ D                   old 已从 T 脱离，是历史路线
aside ──→ D                 aside 是研究者保留的活动旁支

D 由 reader 创建。D 仍被 aside 使用，不是历史路线的专用依赖。
有 old→D：Done；只删除 old→D：Stuck D。
```

身份反例使用两个 git 身份不同的目录：

```text
当前目录身份 B；target 项目身份 A
PROOF_AGENT_NAME=A；PROOF_AGENT_ROLE=reader；未设 PROOF_ROOT
proof node create X lemma ... --root target --json
```

命令在 target 写入成功，但身份检查读取 B。正确 ReaderContext.env() 提供 PROOF_ROOT=target 的对照返回 AGENT_AUTHOR_REFUSED。

四个包实际加载自 `/private/tmp/proof-latest-audit-r2-20261013-01a13595/` 下固定源码副本。Python 3.11；各仓库运行 `python -m pytest -q --junitxml=<repo>-pytest.xml`。共 **2244 passed、16 skipped、0 failed、0 errors**。跳过项见 XML；CI 不等于 researcher Acceptance。

重核 #197 首轮保全清单：134 个捕获文件与清单全部一致；该清单不是完整运行开始环境清单。未更改旧 trial 项目、服务、包版本固定值或旧审计文件。无真实 provider / 模型调用。本轮只新增本审计目录及临时验证副本。

修复方向：对历史依赖仅豁免不再被活动路线使用的部分；让保留身份检查使用已解析的 store.root。补对应对照回归后，再审计固定新版本并重新判断合并门槛。

Standards 2 项，最严重 P2；Spec 2 项，最严重 P2；独特缺陷共 2 项。
