# 外围模块对核心模型的依赖清单

> 回答 issue #3（map #1 "Proof map 重构：依赖可视化证明系统" 的 research ticket）。
> 一手来源：本仓库 `master` @ `c7c8f56` 的 `src/proof_cli/` 与 `plugins/`。所有引用均为 `file:line`（相对 `src/proof_cli/`，除非另注）。
> 本文只做清单与改动面估计，**不**对任何模块的保留 / 删除做决定（那是单独的 grilling ticket）。

## 1. 范围：什么算"核心"

本文把以下模块视为**核心证明状态**（即将被 dependency graph 取代或重写的部分）：

- `domain.py`：`TheoremContract`（domain.py:78）、`ProofObligation`（domain.py:106）、`BlockerRecord`（domain.py:119）、`ProjectSnapshot`（domain.py:131）、`ProjectState`（domain.py:143）
- `db.py` + `storage.py`：SQLite schema 与读写函数
- `theorems.py`、`obligations.py`、`blockers.py`、`goals.py`、`proof_state.py`

其余全部视为"外围"。collaboration 模型（`collaboration.py`）按 ticket 要求也列为被依赖的一类模型。

## 2. 持久化位置总表

所有状态都在项目根下的 `.proof/`：

| 存储 | 定义位置 | 内容 | 写入者 |
|---|---|---|---|
| `.proof/project.sqlite3` | storage.py:78 | 单文件 SQLite | — |
| 表 `project_meta` | db.py:10 | `project_id` | storage.create_project；exchange import 直写 (exchange.py:198) |
| 表 `state` | db.py:65 | 整个 `ProjectState` 一行 JSON | proof_state.save_state (proof_state.py:94) — 以及**所有**通过 `session_history` 记账的外围模块（见 §3.1） |
| 表 `events` | db.py:15 | append-only 事件流，payload 常为完整模型 dump | storage.append_event (storage.py:140)，几乎所有写路径都调用 |
| 表 `theorem_contracts` | db.py:24 | 版本化 contract，`(id, version)` 主键 + `is_current` | storage.store_contract；exchange 直写 SQL (exchange.py:78-100) |
| 表 `obligations` / `blockers` | db.py:34 / db.py:39 | 各一行 JSON | storage.store_obligation / store_blocker |
| 表 `snapshots` | db.py:44 | `ProjectSnapshot` | proof_state.build_snapshot；exchange import |
| 表 `publication_state` / `publication_bundle_snapshots` | db.py:50 / db.py:56 | `PublicationWorkspace` JSON | publication.py:225-232, 1141-1179 |
| 表 `reference_records` / `reference_reviews` | storage.py:49-70（REFERENCE_SCHEMA，未在 db.py） | 参考文献与审查 | storage 的 reference 函数；exchange import |
| `.proof/collaboration.json` | storage.py:92-93, collaboration.py:193-207 | `CollaborationState`：contributors、policies、review_records、comment_threads、comments、branches、publications | collaboration.py；theorems.add_theorem 顺带 upsert contributor (theorems.py:70)；exchange import |
| `.proof/memory.json` | memory.py:215-216, 388-417 | `LayeredMemory`：四层 memory artifacts、verification_history、proof_debug_history、handoff_snapshots、tracked_symbols | memory.py；snapshot.create_snapshot；exchange import |
| 任意输出文件 | export.py:489-494 | `build_export` 的 Markdown | `write_export`（仅库函数） |

## 3. 横切发现（比逐模块表更重要）

### 3.1 `ProjectState.session_history` 是一个隐形的通用日志表

`ProjectState.session_history: list[str]`（domain.py:150）表面上是会话历史，实际被大量外围模块当作**带前缀的 JSON 记录存储**来用：写入时 `load_state → append "<prefix>{json}" → save_state`，读取时全量扫描并按前缀反序列化。所有这些记录都塞在 `state` 表的单行 JSON 里。

| 前缀 | 定义 | 写入者 | 读取者 |
|---|---|---|---|
| `literature_route:` | proof_state.py:22 | proof_state.record_literature_route | proof_state._collect_routes；snapshot |
| `verification_result:` | proof_state.py:23 | verification_results.record_verification_result (verification_results.py:188-190) | proof_state.list_verification_result_records；memory.py:442；export |
| `verification_fragment:` / `verification_review:` / `verification_trace:` | commands.py:300-302 | commands._persist_verification_fragment (commands.py:425-440)、_record_verification_result (commands.py:572)、trace machine-check (commands.py:1696) | commands._verification_fragments (commands.py:329-337)；memory.py:429-437 |
| `formalization_recommendation:` | commands.py:299 | formalize recommend/edit (commands.py:1303, 1373) | — |
| `proof_bug_scan:` / `proof_bug_review:` / `proof_bug_repair:` | commands.py:294-296（memory.py:202-204 重复定义） | bug scan、review suspicion、repair mark (commands.py:660, 1251, 1217) | commands.py:614-698；memory.py:781-926；export.py:79-97 |
| `proof_debug_batch:` / `proof_reasoning:` | commands.py:297-298 | debug generate、reason、obligation derive (commands.py:672, 1093, 1117) | commands.py:1174-1193；memory.py:870, 923 |
| `proof_asset:` `proof_pack:` `proof_policy:` `proof_recommendation:` `proof_reuse:` `proof_automation:` `proof_benchmark:` | governance.py:40-46 | governance._append_record (governance.py:125-141) | governance._records_from_history (governance.py:144-152) |
| 无前缀文本（`goal:`、`search:` 等） | — | proof_state 各函数；commands._append_history (commands.py:216-219) | commands.py:1274（trace 输出最近 10 条） |

含义：**一旦 `ProjectState` 被 graph 替代，asset / pack / policy / recommend / reuse / automate / benchmark / formalize / verify / bug / debug / reason 这些命令组即使在语义上与证明结构无关，也会丢失持久化层**。它们的"改动面"主要来自这里，而不是来自对 theorem / obligation 语义的依赖。前缀常量还在 commands.py 与 memory.py 中重复定义，任何迁移都要两处同步。

### 3.2 依赖边今天散落在 8 个字段里，且混入了非边 token

当前没有显式的边集合；"谁依赖谁"由以下字段隐式表达：

- `TheoremContract.dependencies`、`grounded_theorem_ids`、`grounded_reference_ids`（domain.py:88-91）
- `ProofObligation.required_for`、`source_step_id`、`dependencies`（domain.py:108-114）
- `BlockerRecord.scope`、`related_contracts`、`related_steps`（domain.py:121-125）

而且这些列表里被写入了不是节点 id 的 token：`candidate_ref:` / `supporting_ref:` / `failed_ref:` / `route_note:`（proof_state.py:231-238, 259-266；obligations.py:161-205；blockers.py:109-111）、`required_for:<id>`（obligations.py:35）、`verification_result:<id>` 与 `proof_step:<id>`（blockers.py:158-160）。

读这些字段来重建邻域的外围代码（迁移时都要改成 graph 查询）：

- analysis.py:54-87（`_explicit_neighborhood`）、analysis.py:126
- retrieval.py:187, 195-225, 236（结构化上下文与打分）
- bugs.py:108-146, 255-301（按 theorem 找相关 obligation / blocker）
- checks.py:75-119（依赖存在性、简单环检测）、checks.py:127-188
- commands.py:1262-1276（`trace dependency`）、commands.py:1707-1738（`explain apply`）、commands.py:705-751（reason）
- formal_bridge.py:237-358（把 dependencies 翻成 `VerificationDependencyVersion`）

### 3.3 按类型拆开的 id 字段

多处 scope 模型用 `theorem_id / goal_id / obligation_id / blocker_id / proof_step_id / route_id` 分字段引用核心对象，而非统一的 node id：`VerificationScope`（verification_ir.py:43-51）、`MemoryScope` / `LinkedProofState`（memory.py:47-62）、`ProofDebugScope`（memory.py:118-126）、`VerificationResultRecord`（verification_results.py:154-186）。另外 formal_bridge.py:40-56 通过 id **前缀**（`thm_` / `lemma_` / `obl_` / `step_` / `vfrag_`）推断依赖种类。若节点统一成 graph node，这些都是 schema 迁移点（老的 memory.json / session_history 记录也要能读）。

### 3.4 现有"接受"语义不在一处

CLI 的 `review decide`（commands.py:2192-2207）只在 `collaboration.json` 里记一条 `ReviewRecord`，**不改** `TheoremContract`。真正改 `status / trust_level / review_state` 的 `change_trust_level` / `mark_verified` / `approve_imported_result` 等（review.py:74-209）只被测试调用，没有接入 CLI。`verify accept` 则经 `record_verification_result` 直接关闭 / 阻塞 obligation 并改 contract notes（verification_results.py:90-151, 201-204）。这与 CONTEXT.md 的 **Acceptance** 定义（研究者显式决定）相关，供后续 ticket 参考。

### 3.5 exchange 绕过 storage 层

`exchange import` 直接写 SQL 到 `theorem_contracts`（exchange.py:78-100）与 `project_meta`（exchange.py:197-199），不经过 `storage.store_contract`。若换表结构，这里不会被 storage 层的改动自动覆盖。

## 4. 逐模块 / 命令组清单

图例：**改动面** = 若核心模型改为 dependency graph，该模块预计需要的改动。无 = 不触碰核心；小 = 只读少数字段或只依赖 `ProjectState` 做记账，换存储接口即可；大 = 读写核心模型语义、重建依赖关系或写入 obligation / contract 状态。

| 模块 / 命令组 | 读取的核心模型 | 写入的核心模型 | 表 / 文件 | 改动面 | 备注 |
|---|---|---|---|---|---|
| `formalize`（recommend / show / edit）<br>commands.py:1279-1388；formal_bridge.py；formalization_recommendations.py | `TheoremContract`（statement、dependencies）、`ProofObligation`（goal_statement、required_for、source_step_id、dependencies）经 `_verification_source_entry`（commands.py:316-326）；`ProjectState.project_id`、`current_context`（commands.py:392-413, 450） | `ProjectState.session_history`（`verification_fragment:`、`formalization_recommendation:`） | `theorem_contracts`、`obligations`、`state`、`events` | 大 | formal_bridge 用 id 前缀推断节点种类（formal_bridge.py:40-56），把 dependencies 翻成 `dependency_versions`；`VerificationSourceKind` 枚举（verification_ir.py:13-18）就是今天的节点类型表 |
| `verify`（queue / run / status / result / accept / reject / stale）+ 顶层 `revalidate`<br>commands.py:1391-1682；verification_results.py；verification_broker.py | 同上；`list_obligations`（commands.py:1642） | `TheoremContract.local_usage_notes`、`notes`（verification_results.py:90-113）；`ProofObligation.status` 经 close / block（verification_results.py:116-138）；`BlockerRecord` 经 `integrate_verification_result`（blockers.py:139-179）；`ProjectState.unresolved_trust_sensitive_calls`（verification_results.py:141-151）；`session_history`（`verification_result:`、`verification_fragment:`、`verification_review:`） | `theorem_contracts`、`obligations`、`blockers`、`state`、`events` | 大 | 外围模块中唯一**自动**改变 obligation 状态的路径；accept 语义与 candidate proof / Acceptance 直接冲突，需要重新设计 |
| `trace`（dependency / machine-check）<br>commands.py:1262-1276, 1685-1704 | `TheoremContract.dependencies`、`ProofObligation.required_for/dependencies`、`BlockerRecord.scope/related_*`、`session_history[-10:]` | `session_history`（`verification_trace:`） | `theorem_contracts`、`obligations`、`blockers`、`state` | 大 | `trace dependency` 本质上就是 graph 邻域查询的手写版，迁移后应直接由 graph 提供 |
| `explain apply`、顶层 `reason`、`obligation derive`<br>commands.py:705-751, 1080-1125, 1707-1738；reasoning.py | `TheoremContract`（全字段）、`ProjectState.current_context`、obligations | `ProofObligation`（`_store_reasoning_obligations` → `add_obligation`，commands.py:738-751）；`session_history`（`proof_reasoning:`） | `theorem_contracts`、`obligations`、`state` | 大 | `reasoning.py` 本身纯模型（只 import `utc_now`），会生成 `LocalObligation(required_for=...)`（reasoning.py:76-111） |
| `bug`（scan / list / show）、`evidence show`、`debug`（generate / list）、`repair mark`、`review suspicion`<br>commands.py:614-698, 1128-1259；bugs.py；checks.py；evidence.py；debug_tasks.py | `TheoremContract`（dependencies、grounded_*、exports、provenance_kind）、`ProofObligation`、`BlockerRecord`、`ProjectState.current_context`（bugs.py:100-146, 255-301；checks.py:25-193） | 仅 `session_history`（`proof_bug_*:`、`proof_debug_batch:`） | `theorem_contracts`、`obligations`、`blockers`、`reference_records`、`state` | 大 | 检查逻辑（环检测 checks.py:92-119、依赖存在性 checks.py:75-89）依赖今天的隐式边；evidence.py / debug_tasks.py 本身是纯模型（无 store 访问） |
| `review`（request / list / decide）<br>commands.py:2173-2207；review.py | 库函数 review.py 读 `TheoremContract`、`BlockerRecord`、`ProofObligation`；CLI 路径只读 collaboration | CLI 路径：`ReviewRecord`（collaboration.json）。库路径：`TheoremContract.status/trust_level/review_state`（review.py:74-209）、关闭 obligation / 解决 blocker（review.py:212-263） | `collaboration.json`、`theorem_contracts`、`obligations`、`blockers`、`events` | 大 | 见 §3.4：review 按 `object_type/object_id` 字符串挂在任意对象上（collaboration.py:91-94），可直接映射到 node id；但 acceptance 语义要与 candidate proof 流程重做 |
| `publication`（list / show / set / view / export / release / withdraw）<br>commands.py:1783-1930；publication.py | `TheoremContract`（status、review_state、provenance_kind、grounded_*、usage notes，publication.py:283-318）、全部 obligations / blockers、`ProjectState`（整体 dump）、`ProjectSnapshot`、references、`ReviewRecord`、memory handoff（publication.py:729-789） | 仅自己的 `PublicationWorkspace` | `publication_state`、`publication_bundle_snapshots`、读 `theorem_contracts` / `obligations` / `blockers` / `snapshots` / `reference_records` / `state` / `collaboration.json` / `memory.json` | 小 | claim 以 `object_type="theorem_contract"` + theorem id 为键（publication.py:302-303, 322-337），readiness 从 contract 字段派生（publication.py:283-298）。换成 node 后需重写派生函数与 bundle 组装，但不写核心 |
| `exchange`（export / import）<br>commands.py:2128-2135；exchange.py | 全量：`ProjectState`、`ProjectSnapshot`、`TheoremContract`、`ProofObligation`、`BlockerRecord`、references、collaboration、memory、publication、governance 记录（exchange.py:37-55, 116-139） | 全量覆盖写入上述所有模型（exchange.py:194-262），contract 走直写 SQL（exchange.py:78-100） | 所有 SQLite 表 + `collaboration.json` + `memory.json` | 大 | `ExchangeBundle` 就是今天完整数据模型的序列化格式，必须跟随新 schema 重定义（并考虑旧 bundle 兼容） |
| `handoff`（create / inspect）+ 顶层 `snapshot`<br>commands.py:2114-2116, 2137-2150；snapshot.py；proof_state.build_snapshot | `ProjectState`（current_theorem、open_goals、open_obligations、blockers、recent_theorem_usage、failed_routes、unresolved_trust_sensitive_calls），verification / route 记录，publication workspace（proof_state.py:328-367） | `ProjectSnapshot`、`ProjectState.latest_snapshot_id`；memory `HandoffSnapshot`；publication bundle snapshot（snapshot.py:16-23） | `snapshots`、`state`、`memory.json`、`publication_bundle_snapshots` | 大 | `ProjectSnapshot` 字段（domain.py:131-151）是 `ProjectState` 列表的投影；"open obligations / active blockers" 在 graph 下应改为 frontier 视图。handoff create 同时调用 exchange export |
| `memory`（list / show / add）<br>commands.py:2053-2111；memory.py | `ProjectState.project_id`（memory.py:211-212）；扫描 `session_history` 中 verification / bug / debug / reasoning 前缀（memory.py:429-473, 781-926）；`ProjectSnapshot` | 只写 memory.json | `memory.json`，读 `state` | 小（数据层中等） | 自身数据模型独立，但 `MemoryScope` / `ProofDebugScope` 按类型拆 id（§3.3），同步函数依赖 §3.1 的前缀日志。若日志搬家，同步函数要改读取源 |
| `asset`（list / show / publish / review）、`reuse show`<br>commands.py:2314-2375, 2479-2488；governance.py；reusable_assets.py；proof_patterns.py | 仅 `ProjectState.project_id` | 仅 `session_history`（`proof_asset:`、`proof_reuse:`）；`asset publish` 还写 `SharedAssetPublication`（collaboration.json） | `state`、`events`、`collaboration.json` | 小 | 语义上独立；`ReusableAssetKind.theorem_contract / blocker_pattern`、`linked_blocker_ids` 只是字符串引用（reusable_assets.py:12-59） |
| `pack`（list / show / install / update）<br>commands.py:2374-2424；governance.py:234-313；domain_packs.py | 仅 `ProjectState.project_id` | 仅 `session_history`（`proof_pack:`） | `state`、`events` | 小 | `domain_packs.py` 纯模型；`theorem_templates` 为字符串列表（domain_packs.py:36），不引用 contract |
| `policy`（list / set）<br>commands.py:2425-2445；governance.py:316-348；automation_policy.py | 仅 `ProjectState.project_id` | 仅 `session_history`（`proof_policy:`） | `state`、`events` | 小 | automation_policy.py 纯模型 |
| `recommend`<br>commands.py:2446-2476；recommendations.py；retrieval.retrieve_cross_project_assets | `ProjectState.project_id`（commands.py:2459-2466） | 仅 `session_history`（`proof_recommendation:`） | `state`、`events` | 小 | 跨项目推荐只看 assets / packs |
| `automate`（plan / run / trace / review）<br>commands.py:2490-2600；automation.py；governance.py:424-502 | 仅 `ProjectState.project_id`；`scope` 是自由字符串（automation.py:227） | 仅 `session_history`（`proof_automation:`） | `state`、`events` | 小 | `AutomationTaskType` 名字提到 obligation_splitting / blocker_triage（automation.py:19-23），但 `run.execute` 是纯内存模拟，不读写任何 obligation / blocker |
| `benchmark run`<br>commands.py:2603-2620；automation_eval.py；governance.py:505-529 | 无（输入是调用方传入的 JSON 记录） | 仅 `session_history`（`proof_benchmark:`） | `state`、`events` | 小 | automation_eval.py 纯模型，`obligations_resolved` 只是计数字段 |
| `contributor list`、`role show`、`comment`（add / list）、`branch`（create / list / compare / merge）<br>commands.py:2153-2300；collaboration.py | 仅 `ProjectState.project_id`（collaboration.py:167-168） | 只写 collaboration 模型 | `collaboration.json`、`events` | 无～小 | comment thread / review 用 `object_type/object_id` 泛型挂载（collaboration.py:91-107），天然适配 node id；`BranchRecord.scope` 为自由字符串（collaboration.py:128）。被核心反向依赖：`add_theorem` 会 upsert contributor（theorems.py:70） |
| `reference`（list / show / import / review）<br>commands.py:818-881；references.py；storage.py:242-460 | 自身 `ReferenceRecord` | 自身表；`session_history`（无前缀文本） | `reference_records`、`reference_reviews`、`state` | 小 | references.py 反向 import `TheoremContract` 做引用归一（references.py:9）；`grounded_reference_ids` 让 contract 指向 reference，未来会是 graph 中的外部节点 / 边 |
| DSL 入口：`import` / `ground` / `review`（`cmd_proof_import` 等）<br>commands.py:884-1077 | `TheoremContract`、`ReferenceRecord`、theorem callability | `TheoremContract`（`update_theorem`，commands.py:982, 1068）、`ProofObligation`（commands.py:913, 962, 1039）、`ProjectState`（failed_routes、recent_theorem_usage、unresolved_trust_sensitive_calls） | `theorem_contracts`、`obligations`、`reference_records`、`state`、`events` | 大 | 未挂到 `proof` CLI（cli.py 只 import 不注册 dsl 命令），经 elaboration.py 调用 |
| `elaboration.py` + `dsl.py` | `ProjectState.current_theorem/current_context/open_goals` | goals、current theorem、context、obligations（add / close）、theorem usage（elaboration.py:51-318） | `state`、`obligations`、`events` | 大 | 仅库 / 测试使用（tests/test_dsl.py）；dsl.py 本身纯解析 |
| `search`、`retrieve`（顶层）<br>commands.py:775-808；retrieval.py | `ProjectState`（current_theorem、current_context、open_goals、open_obligations、blockers、recent_theorem_usage，retrieval.py:148-159）、全部 contracts / obligations / blockers 用于邻域与打分（retrieval.py:187-236, 798-813）、memory、packs、assets | 仅 `session_history`（无前缀文本） | `theorem_contracts`、`obligations`、`blockers`、`state`、`memory.json` | 大 | retrieval-first 约束的实现体；邻域计算应改为 graph 查询 |
| `project analyze`<br>commands.py:811-815；analysis.py | `ProjectState`（current_theorem、failed_routes、unresolved_trust_sensitive_calls）、全部 contracts / obligations / blockers（analysis.py:54-202） | 仅 `session_history` | 同上 | 大 | 也被 `build_snapshot` 调用（proof_state.py:329, 336） |
| `provenance show`<br>commands.py:1741-1780 | `TheoremContract`（grounded_*）、`ReferenceRecord` | 无 | `theorem_contracts`、`reference_records` | 小 | |
| 顶层 `export`<br>commands.py:2124-2125；export.py | `summarize_state`、`ProjectState.session_history`（bug 前缀，export.py:79-97）、theorems、references、collaboration、governance、publication、memory（export.py:167-487） | 无（`write_export` 写输出文件） | 读几乎所有表与 JSON | 小 | 纯报告生成，但读取面最广；session_history 前缀又一处重复定义 |
| `codex` 子命令组（`proof codex ...` 与独立入口 `proof-codex`）<br>codex_router.py | 无直接模型访问；只调用 `cmd_init/status/search/retrieve/project_analyze/theorem_*/obligation_*/blocker_*/snapshot`（codex_router.py:12-27） | 同上（间接） | `.proof/` 存在性检测（codex_router.py:81, 99） | 小 | 薄路由层。改动取决于 theorem / obligation / blocker 命令的 CLI 形状；参数如 `required_for`（codex_router.py:383-402）会随 graph 边模型变化 |
| `services.py` | 无直接模型访问；包装 `cmd_status/snapshot/history/export/project_analyze` 与 `retrieve_candidates` | 无 | 同上（间接） | 无～小 | 薄门面 |
| `plugins/proof-routing/`<br>plugins/proof-routing/scripts/proof_mcp_server.py | 无；MCP 工具通过子进程调用 `proof codex ...`（proof_mcp_server.py:15-20, 42） | 无 | 无 | 小 | 暴露 theorem / obligation / blocker 的 list / add、search、retrieve、analyze、snapshot（proof_mcp_server.py:28-150）。只依赖 codex router 的 CLI 契约；若新增 graph / frontier / candidate proof 命令，这里要同步新增工具。`install_home_plugin.py` 只做安装 |

### 纯模型模块（不访问 store，改动面：无）

以下模块只 import `domain.utc_now` 或彼此的模型，不读写任何表 / 文件：`automation.py`、`automation_policy.py`、`automation_eval.py`、`domain_packs.py`、`reusable_assets.py`、`proof_patterns.py`、`recommendations.py`（仅调用 retrieval 的跨项目函数）、`reasoning.py`、`evidence.py`、`debug_tasks.py`、`verification_ir.py`、`verification_broker.py`、`formalization_recommendations.py`、`dsl.py`、`rendering.py`（只读 `ProjectSnapshot`）。它们的"改动面"全部由调用它们的命令组承担。

## 5. 汇总

- **重度耦合（大）**：verify、formalize、trace / explain / reason / obligation derive、bug / debug / evidence / repair、review（库路径）、exchange、handoff / snapshot、search / retrieve、project analyze、DSL 入口与 elaboration。共同点：要么重建今天散落的隐式依赖边（§3.2），要么直接写 obligation / contract / blocker 状态。
- **只借用 `ProjectState` 做记账（小）**：asset、reuse、pack、policy、recommend、automate、benchmark。它们在语义上与证明结构无关，改动面几乎全部来自 `session_history` 前缀日志（§3.1）——只要为它们提供独立的存储位置即可。
- **只读核心（小）**：publication、export、provenance、memory（数据层还受 §3.3 影响）。
- **基本独立（无～小）**：collaboration（contributor / role / comment / branch，泛型 `object_type/object_id` 天然适配 node id）、codex router、services、`plugins/proof-routing`（仅依赖 CLI 契约），以及 §4 末尾列出的纯模型模块。

## 6. 方法与局限

- 通过 AST 扫描每个模块的相对 import 与对核心读写函数（`get_contract`、`list_obligations`、`load_state`、`save_state`、`store_*`、`add_*`、`close_obligation` 等）的调用，再人工阅读关键函数确认读写方向。
- 行号基于 `c7c8f56`；commands.py 中每个命令组的行区间为函数定义起止。
- "改动面"是基于代码结构的估计，不含测试文件的改动量；`tests/` 中对这些模块的直接断言会放大实际工作量，尤其是 exchange、verify、publication。
