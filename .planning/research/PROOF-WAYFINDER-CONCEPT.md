# Proof Wayfinder — Product Concept v0.1

面向复杂数学研究的人机协作可视化证明系统。

**核心思想**：把大型证明视为一张会随着研究推进而不断生长、拆分和收敛的 Claim / Lemma 依赖图。系统与研究者共同完成课题拆解，Agent 一次处理一个足够小的证明单元，研究者负责审阅、接受、驳回或继续拆分。

**一句话定义**：Wayfinder for mathematical proof research——以 theorem 为 destination，以 claim / lemma 为 ticket，以 human review 为 merge gate。

**目标用户**：数学研究者、博士生、理论研究团队，以及需要多 Agent 长周期协作完成复杂证明任务的研究项目。

## 1. 产品愿景

现有 LLM 已经能够处理局部证明、推导、文献检索和证明草稿，但真正困难的研究课题通常不是“让模型证明一个已经拆好的 lemma”，而是如何把一个模糊的大目标逐渐变成一组清晰、可验证、可并行推进的数学义务，并让这些义务在多个会话、多个 Agent 与多人协作之间保持一致。

Proof Wayfinder 的目标不是替代数学家，也不是首先追求全自动形式化验证，而是提供一个长期、可审阅、可恢复的证明工作空间：研究者掌握证明架构与最终判断，系统负责维护全局状态、暴露当前 frontier，并把局部任务稳定地交给 Agent。

## 2. 核心抽象：数学版 Wayfinder

Pocock Wayfinder 的核心价值不在于“软件 issue”本身，而在于 shared map、dependency、frontier、claiming、fog of war 和 one-ticket-per-session。Proof Wayfinder 保留这些机制，但将 ticket 的语义改造成数学研究对象。

| 软件 Wayfinder | Proof Wayfinder | 数学含义 |
|---|---|---|
| Destination | Target theorem / research goal | 最终要建立的定理、命题或理论目标 |
| Issue / decision ticket | Claim / Lemma ticket | 一次 Agent 会话应能处理的证明单元 |
| Sub-issue | Subclaim / sublemma | 证明过程中暴露出的更小义务 |
| Blocking edge | Proof dependency | 哪些结论必须先成立 |
| Frontier | Proof frontier | 当前已经足够清晰、可以立刻开始处理的节点 |
| Fog of war | Proof fog | 知道这里存在困难，但还不足以形成精确数学命题的区域 |
| Resolution | Candidate proof | Agent 提交的证明草稿，而非自动接受的结论 |
| Review / close | Human acceptance | 研究者审阅后决定是否纳入主证明 |

## 3. Proof Ticket：系统的基本工作单元

每一个 Claim 或 Lemma 都是一个独立 ticket。它既是数学对象，也是 Agent 可以领取和提交工作的最小协作单元。

### 3.1 Claim 与 Lemma

- **Claim**：局部证明义务，通常服务于某个父节点，不一定值得长期复用。
- **Lemma**：具有独立数学意义、可被多个节点复用的结果。

Claim 在审阅后可以被研究者提升为 Lemma；系统不需要在创建时强迫用户做永久分类。

### 3.2 推荐的 ticket 内容

```
[Lemma] Iterative closure of differentiated ODE terms

Statement       精确数学陈述
Role in proof   它如何服务于父定理 / 父引理
Assumptions     明确假设与符号环境
Depends on      前置 Claim / Lemma
Proof target    本 ticket 需要完成到什么程度
Status          open
```

### 3.3 Agent 提交的不是“真理”，而是 candidate proof

Agent 完成 ticket 后，应提交完整证明、关键思路、实际使用的依赖、它认为可能存在的 gap，以及工作过程中发现的新 proof obligations。ticket 随后进入 review-needed，而不是直接 closed。

## 4. 核心人机协作闭环

```
Human + System
      |
      v
Define / refine target theorem
      |
      v
Decompose into Claim / Lemma tickets
      |
      v
Choose current proof frontier
      |
      v
Agent claims one ticket and works on it
      |
      v
Submit candidate proof
      |
      v
Human review
   /       |        \
accept   revise     split
   |        |          |
   |        v          v
   |    Agent retry  New subclaims
   |                   |
   +---------+---------+
             v
       Update proof graph
             |
             v
           Repeat
```

这里最重要的规则是：Agent 不应在一个过大的 ticket 上强行生成“看起来完整”的证明。如果它发现真正的困难被隐藏在内部，就应该显式地产生新的 subclaim / sublemma，并把父节点标记为 blocked 或 partially resolved。

## 5. 动态拆解与 Proof Fog

大型数学研究不可能在项目开始时一次性画出完整证明树。Proof Wayfinder 因此采用渐进式结晶（progressive crystallization）：已经能够精确陈述的问题进入 ticket graph；只能模糊描述的未知区域留在 proof fog；随着 frontier 节点被解决，fog 中的困难逐渐变成新的正式 Claim 或 Lemma。

```
Main theorem
├── Lemma A: precise and actionable
│   ├── Claim A1: open
│   └── Claim A2: proof-drafted
├── Lemma B: blocked
│   └── Claim B1: current frontier
└── Proof fog
    ├── exact closure mechanism?
    ├── required spectral hypothesis?
    └── remainder propagation structure?
```

“Fog 还是 ticket”的判断标准很简单：如果现在已经能写出一个足够精确、可以让 Agent 明确知道要证明什么的数学命题，就应该创建 ticket；如果连命题本身还依赖前面尚未解决的结构，则保留在 fog。

## 6. Ticket 状态与 Human Review

系统的信任边界应当非常清晰：Agent 可以生成、拆解、检索、尝试与修订，但“这个证明是否被项目接受”是研究者的决定。

| 状态 | 含义 |
|---|---|
| open | 命题已经清晰，但尚未有人开始处理 |
| claimed | 某个 Agent / 人正在处理，避免并发重复 |
| proof-drafted | 已有 candidate proof |
| review-needed | 等待研究者审阅 |
| accepted | 研究者接受，可作为后续证明依赖 |
| revision-needed | 证明思路可能成立，但需要补充或修订 |
| blocked | 依赖其他 Claim / Lemma 或外部信息 |
| rejected | 当前证明路线或结论被否决 |

## 7. GitHub、Proof CLI 与可视化层的职责

GitHub Issues 并不只是“软件开发工具”。对于本产品，它可以很好地承担共享 ticket backend：每个 theorem / claim / lemma 都有稳定 identity、评论、assignee、sub-issue、dependency、历史记录和多人协作能力。Proof CLI 则成为 Agent-facing workflow protocol；可视化界面负责把这些状态组织成研究者真正能理解的 proof map。

```
                 Visual Proof Map
          graph / frontier / fog / review queue
                         |
                         v
                  Proof CLI / API
          orchestration + agent workflow protocol
                         |
            +------------+------------+
            |                         |
            v                         v
      GitHub Issues             Local project state
  shared tickets/history     context/cache/artifacts
```

- **GitHub**：共享研究协作状态，适合 ticket、评论、assignment、依赖与审阅记录。
- **Proof CLI**：提供稳定命令协议，让 Codex、Claude Code 等 Agent 读取 frontier、claim ticket、提交 proof、拆分节点和更新状态。
- **Visual UI**：以 graph 而不是列表呈现“整个证明现在在哪里、卡在哪里、下一步是什么”。

数学正文、长证明草稿和附件可以存储在 repo 文件中，并由 issue / ticket 指向，而不是把所有内容塞进 issue body。

## 8. 可视化产品形态

主界面应围绕 proof map，而不是传统项目管理 dashboard。研究者进入项目后，首先看到的是主定理、已接受的证明链、当前 frontier、被阻塞节点和仍在 fog 中的研究区域。

```
                         Main Theorem
                        /            \
                 Lemma A              Lemma B
                /      \               |
            Claim A1   Claim A2        Claim B1
                          |
                    Sublemma A2.1

Accepted: 12   Review: 3   In progress: 4   Blocked: 2
Current frontier: Claim A1 · Claim B2 · Lemma C
```

点击节点后，右侧 Inspector 展示 Statement、Role in proof、Assumptions、Dependencies、Candidate proof、Review comments、New obligations 和 history。研究者可以直接执行 Accept、Request revision、Split、Promote to lemma、Mark blocked 等操作。

## 9. MVP：最短可用版本

第一版不应试图构建全自动数学家，也不需要以 Lean 或形式证明为中心。最有价值的 vertical slice 是先把“拆解 → Agent 工作 → 人 review → 图更新”闭环跑通。

- 统一 Proof Ticket schema：Theorem / Claim / Lemma + dependency + status + parent/children。
- GitHub Issues 映射：创建、领取、sub-issue、blocking、comment-based proof submission。
- Proof CLI 命令：map、frontier、claim、submit、review、accept、revise、split、block。
- Agent 工作协议：一次只处理一个清晰 ticket；遇到隐藏困难时拆出新的 subclaims，而不是掩盖 gap。
- Human review queue：集中显示所有待审 candidate proofs。
- 基础 Graph UI：展示 theorem tree / DAG、状态、frontier、blocked nodes 与 fog。
- 事件与历史：能够回答“这个 lemma 为什么出现、谁改过、为什么被拆分、哪条路线被否决”。

## 10. 产品原则

- **Human is the proof architect** — 研究者负责目标、结构和最终接受；Agent 是高吞吐的局部证明工作者。
- **Decompose before hallucinating** — 证明太大时优先拆分，不允许用流畅文本掩盖未解决的数学义务。
- **Frontier over backlog** — 系统最重要的问题不是“还有多少 ticket”，而是“哪些节点现在可以高质量推进”。
- **Explicit dependencies** — 每个 Claim / Lemma 都应尽可能明确它依赖什么、被什么依赖。
- **Proofs are reviewable artifacts** — Agent 输出必须可审阅、可讨论、可修改，而不是黑盒答案。
- **The map is allowed to grow** — 证明结构不是一次性规划结果，而是在研究中不断暴露、修正和重构。
- **No forced formalization** — 形式化工具可以作为可选 verifier，但不是产品核心，也不是所有研究课题的前置条件。

## 11. 最终产品定义

Proof Wayfinder 是一个面向长期数学研究的人机协作证明操作系统。

它把复杂研究目标表示成一张不断演化的 Claim / Lemma 依赖图：系统与研究者共同拆解课题，Agent 领取当前 frontier 上的单个证明任务并提交 candidate proof；研究者通过 review 决定接受、修订、驳回或继续拆分；新的数学义务不断从 proof fog 中结晶出来，直到主定理的证明路径被完整建立。

从产品角度看，它不是“让 AI 一次证明大定理”的工具，而是一套让人类数学家能够组织、监督和扩展多个 AI Agent 进行长期研究的协作基础设施。

## 附录：建议的第一组 CLI 语义

```
proof map
proof frontier
proof theorem new
proof claim add
proof lemma add
proof claim <ticket>
proof submit <ticket>
proof review <ticket>
proof accept <ticket>
proof revise <ticket>
proof split <ticket>
proof block <ticket>
proof promote <claim> --to lemma
```
