**结果（2026-10-20）**

两张地图的决议已经写进文档，并拆成实现票。文档见[这个 PR](https://github.com/DengZhiyuan-math/proof-cli/pull/274)，已合并到 master。

**ADR**
- 新写一篇：[ADR-0025 五个状态与现算的四种结论](https://github.com/DengZhiyuan-math/proof-cli/blob/master/docs/adr/0025-five-states-and-computed-conclusions.md)，分七部分：模型、质疑、验证与封存、Coordinator 解析研究者的话、原地图保留的决议、删掉的东西、已有项目怎样换过来。
- 旧 ADR 的正文不改，保留历史。受影响的 18 篇（0002、0004–0008、0010–0014、0016、0019–0024），在 Status 行各加一句 "Amended by ADR-0025"，说明哪里改了。0001、0003、0009、0015、0017、0018 不用改。

**CONTEXT.md**
- 「Node lifecycle」里的三条轴，换成「Node state」：Seal（封存）、Statement layer（命题层）、Proof layer（证明层）、Assignee（领取）、Run state（运行），外加 Conclusion（结论）、Verification（验证）和 Awaiting verification。
- Challenge 按新规则重写。新增 Counterexample、Uses of dependencies、Off route 三条。Review decision 改名 Researcher decision。
- 删掉的条目：Acceptance、Reference review、Accepted、Rejected、Revision requested、Review-needed、Blocked、Provisional、Conditional、Unverifiable、Integrity state、Potentially stale、Lightweight re-review、No longer callable。Trusted by rule 并入 Trust rule。
- 旧名都列在对应条目的 _Avoid_ 里。代码改完之前，代码里仍是这些旧名。

**名字（检查三）**
- claim 只指节点种类；谁在做，叫 Assignee。
- approved、dismissed、reaffirmed 不再用。决定按它的种类称呼；质疑的了结只说 fixed、withdrawn、superseded by a restatement。
- Awaiting review 改为 Awaiting verification。dropped 只留给 fog，节点不在路线上叫 Off route。
- 运行怎样结束（done、stuck、parked、interrupted）是运行记录，说的时候总带上是谁结束了：节点的运行、Coordinator，还是 Pursue。
- 其余几个（open、current、failed、error、no verdict、review、running）由实现票按 CONTEXT.md 改输出文字。

**写文档时定下的几处细节**
- 五个状态各从自己的记录读出，不另存一个状态字段。ADR-0002 的原则不变，只是状态少了。
- Coordinator 留在 proof-agents，输入框由 proof-web 提供，它记下的东西是项目状态，进工作记录。
- 文字一旦被验证或封存依赖过，对所有人都固定，沿用 ADR-0020 第 4 点。对证明的质疑不固定文字。
- Promote 要求那个 Claim 已经专家验证过，或封存为对。

**实现票**

总票是[「ADR-0025: five states and four computed conclusions」](https://github.com/DengZhiyuan-math/proof-cli/issues/275)。下面这些票都按 ADR-0025 拆：
- core 9 张，在本库；
- agents 5 张，在 zeqome/proof-agents；
- web 4 张，在 zeqome/proof-web。后两个是私有库。

先做 core 的状态读取，然后依次是质疑、判定、研究者的决定、删除旧操作、已有项目的切换，agents 和 web 跟在后面，先后关系用依赖边标出。每张票都写明它防止的错误和验收条件。逐项明细指向本地清单里的行，不公开。

基线数字和「按新状态模型定稿 54 项去向并重算」一致：门槛违反 95 条；字段方面，存了可现算值的 123 个，重复存储的 148 个，同一事实算两遍的 28 处；仍冲突的名字 16 个。