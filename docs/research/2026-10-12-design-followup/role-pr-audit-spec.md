# Decomposer / Verifier / Search route 审计与 PR 范围

来源：本对话中研究者的直接要求；2026-10-12。

## 已授权改动

1. Decomposer 的角色说明约束：不把两条替代路线都 Split 成必需依赖；选定路线所需 Claims 才进入依赖图。保留现有 attempts、scratch/ 与 memory 的记录方式。
2. CONTEXT.md 增加一句 Search route 定义，区分可选路线与必要依赖。
3. Verifier 在已有 Typesetter 后再调用的流程中，核对遗漏的假设、量词变化和被掩盖的 Conditional。只需角色说明，不增加 core 流程。
4. 不增加工具权限、文件写范围、memory 写权限或 Human Review 权限。不改变 Acceptance，passing Verifier verdict 仍只允许请求 review。
5. 单独 Decomposer 与 Pursue 的原规则保持：单独运行不编辑依赖边并停给研究者；Pursue 只编辑自己 split 的 unaccepted Claims，Parked parent 的再分解上限不变。

## 本轮发布要求

研究者原文：“审计 Decomposer/Verifier 角色补丁和 CONTEXT.md 的定义，确认没有扩大权限或改变 Acceptance。通过后为 core 和 proof-agents 分别创建 PR，暂不合并，也不重跑模型试验。”

两项 PR 各只携带一个文件的上述改动。以 `integ/0021` 为 base，避免带入独立的 Reader 失败原因或 stale-cause 修复。允许本地离线检查和已有测试，不调用真实模型。

## 固定范围

| 仓库 | 固定基线 | 提交 | diff |
|---|---|---|---|
| core | `3dd0a7bde3ad1ea9e040c02b1bff6589a9cf378c` | `a6d4710bcc3fa42d92728703384b13facc70f257` | 只新增 CONTEXT.md 的 3 行 |
| agents | `3ff0a7121e82b3c8eb1153c7bc1e296c96a36c69` | `81dc8c041f6c352cb3016a42f3f3ed9a4d014a87` | 只修改 proof_agent.py 的角色 brief |

这些是最初提交的审计范围。若审计发现问题，应修复并重新固定提交后才发布。
