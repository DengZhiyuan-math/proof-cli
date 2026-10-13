# Spec

固定版本：core ec9f5aa、agents c6ddf0a、web 5667bef。审查累计改动、增量修复及 ADR-0023、agents #31/#32、core #221。没有真实 provider 调用。

1. **[P2] 活动共享依赖仍被废弃闭包隐藏。** ADR-0023:16 仅豁免 “the nodes only they rest on”，同时要求 “every agent-made active local node” 覆盖。agents `coordinator.py:1054-1059` 排除了全部废弃依赖闭包，却只检查所选 Theorem 的活动闭包。真实 core map 中，脱离 T 的 old Claim 及活动 human standalone aside 同时依赖 reader 创建的 Lemma D。公开 Pursue API 连续两次返回 Done；D 未被所选 T 覆盖，也未被列出。仅删除历史 old→D 后，对照组返回 Stuck，命名 D，且未启动 Coordinator。应将活动共享依赖保留在覆盖检查中。

2. **[P2] 公有 rooted CLI 按错误项目检查保留身份。** ADR-0023:16 指定项目 git identity 是 “names no agent may write under”；CLI 的根规则是 `--root` 优先。core `cli.py:299-303` 却读取 PROOF_ROOT 或 cwd。target 与 cwd 的 git identity 不同，ROLE=reader、NAME=target 身份、未设 PROOF_ROOT 时，`node create X lemma … --root target` 成功将 X 记为研究者。随后公开 Pursue API 返回 Done，误称 X 为研究者自己的 standalone 工作。检查应使用本次解析的 store.root。真实 ReaderContext.env() 对照返回 AGENT_AUTHOR_REFUSED；正常 host run2 使用正确 PROOF_ROOT，此问题不是正常 host run2 回归，也不是安全沙箱逃逸。

未发现新增 Acceptance/Reference-review 权限或其他已证实范围扩张。Reader 目标识别指令、Ask/Review-now 未确认标签、失败 Coordinator 汇总符合累计需求；数学目标识别及实际文献检索仍需真实试验。

证据：`probe_spec.py` 与 `probe_spec.json`。每次脚本创建 fresh 临时项目；仅 Coordinator 由离线替身替代，core 状态、CLI 与 web API 是实际实现。
