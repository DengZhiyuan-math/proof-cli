# Decomposer / Verifier 与 Search route：发布前审计

日期：2026-10-12。按 code-review 技能的 Standards 与 Spec 两轴分别审计。两轴检查同一组固定提交；没有运行真实模型或 provider。

| 仓库 | 固定 base | 审计 head | 文件范围 |
|---|---|---|---|
| core | `3dd0a7bde3ad1ea9e040c02b1bff6589a9cf378c` | `a6d4710bcc3fa42d92728703384b13facc70f257` | CONTEXT.md，3 行新增 |
| agents | `3ff0a7121e82b3c8eb1153c7bc1e296c96a36c69` | `81dc8c041f6c352cb3016a42f3f3ed9a4d014a87` | proof_agent.py，只改角色 brief |

两份改动分别基于 `integ/0021`。未包含 Reader failure_reason 或 stale-cause 修复提交。

## Standards

审计通过；没有可执行的违规发现，也没有需要标注的代码异味。

- core 只在 CONTEXT.md:253–254 定义 Search route。定义区分路线选择与必要前提，未修改 Acceptance、Split 或 Review decision 的规则，符合 docs/agents/domain.md 的统一术语要求。
- proof_agent.py:234–237 限制 Decomposer 只分解选定路线。scratch、Standing question 和 Attempt 均复用已有记录机制；没有授权 memory 写入、自动 redirect、增加再分解次数或启动其他运行。
- proof_agent.py:305–309 增加 Verifier 的审读要求。遗漏或过度声明须写入 verdict；未授权 Verifier 修改证明或 summary。
- 两个 diff 均未修改权限表、命令表、Claude/Codex scope、运行状态机或 Acceptance 代码。

关键不变量仍成立：单独 Decomposer 不改依赖边并停给研究者；Pursue 的边操作范围及 Parked parent 一次再分解上限不变。Verifier 仍只写 scratch/verifier/、记录 advisory Verdict，不 Split、不请求 Review、不作 Review decision。passing Verdict 仍只打开 Prover 的 request-review gate。Acceptance 仍由研究者决定，符合 ADR-0004、ADR-0019、ADR-0021。

## Spec

审计通过。缺失或部分实现：无；范围扩大：无；实现错误：无。

- 符合 [spec](role-pr-audit-spec.md) 第 7–8 行：“选定路线所需 Claims 才进入依赖图”“区分可选路线与必要依赖”。新增约束位于共享 _DECOMPOSER，brief() 同时用于独立与 Pursue Decomposer。不会漏掉 Pursue。
- 符合第 10 行：“不增加工具权限、文件写范围、memory 写权限或 Human Review 权限”。diff 只改角色字符串及 CONTEXT 定义。ROLES、权限构造和命令白名单未变。Decomposer 仍无 MEMORY_WRITE；路线选择和 abandoned attempt 使用原有 progress 权限。CONTEXT 的 memory 描述不授予角色写权限。
- 符合第 11 行。独立 Decomposer 仍禁止加删边并停给研究者；Pursue 的边范围仍限于自己 split 的 unaccepted Claims 及受限 Parked 替换。Coordinator 的一次再分解限制未变。
- 符合第 9–10 行。Verifier 新增假设、量词/作用域及 Conditional 清单；仍只读取 Provisional statement，不依赖其 proof。passing verdict 仍只给 Prover 请求 review 的资格。Verifier 不请求 review、不作 Review decision；Acceptance 仍只由研究者决定。

## 独立边界与测试检查

[边界检查结果](role-pr-boundary-check.json)：所有 5 个角色 × Pursue false/true 共 10 个 public contexts，Claude 参数（edit true/false）、Codex 参数（三种 sandbox）及命令表均与基线相同；角色 writes、proof、programs、commands、alone 均相同。core 的 cli.py、proof_map.py、domain.py 和 ADR-0004/0019/0021 blob 完全相同。

agents 在审计 head 上，配合固定的 core base 加 glossary，全套 **199 passed**（17.24 秒），见 [JUnit](role-pr-agents-tests.xml)。比上轮 200 少一项，是因为本次基于 integ/0021，没有包含独立的 failure_reason 修复及其测试。core 只有 glossary 文本改动，本次检查 diff/来源边界，不重跑无关运行套件。

静态审计与本地测试确认没有新增权限或 Acceptance 路径。它们不证明真实模型必定遵守提示词。没有重跑模型试验。

Standards：0 项发现，无最高优先级问题；Spec：0 项发现，无最高优先级问题。

## 发布结果

按研究者本轮授权，审计通过后创建 [core #211](https://github.com/DengZhiyuan-math/proof-cli/pull/211) 与 [proof-agents #28](https://github.com/zeqome/proof-agents/pull/28)，分别是上表审计 head；base 均为 integ/0021。两份 PR 均已关联到本对话。

[远端核验](role-pr-publication.json) 确认：各只有一个提交、一个预期文件；标题/正文与准备文件逐字相同；head/base 与固定范围相同；state=OPEN，autoMergeRequest=null。最后回读时 core 四项、agents 两项 CI 都是 IN_PROGRESS，未记为通过。没有合并或运行模型试验。
