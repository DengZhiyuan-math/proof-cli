# 本地 web 应用技术选型：Python 本地服务与 DAG / 树布局图库

> 研究 ticket：[#4](https://github.com/DengZhiyuan-math/proof-cli/issues/4)（map [#1](https://github.com/DengZhiyuan-math/proof-cli/issues/1)）
> 调研日期：2026-09-24。版本、发布日期、许可证取自 GitHub API（`repos/*`、`latestRelease`）、npm registry（`registry.npmjs.org/<pkg>`）与 PyPI JSON API（`pypi.org/pypi/<pkg>/json`）当日数据。
> 体积为从 npm tarball 中取出的发行文件实测（raw = 未压缩；gz = 本地 `gzip` 默认级别压缩后），用于量级比较，不代表最终打包结果。
> 本文只陈列选项与事实，**不做最终选型**；最终决定属于后续 ticket（#10 等）。

## 需求回顾

- 数据：一张 **Proof map**（typed dependency graph，DAG），规模数十到数百节点。
- 两种视图：网状（DAG，layered / Sugiyama 类布局）与树状（从目标定理向下展开）。
- 节点按状态着色；可点击查看详情（需要 JS 回调，而不只是跳链接）。
- 离线可用：不依赖 CDN，前端资源 vendored 进 Python 包（`src/proof_cli/...`），随 wheel 分发。
- 宿主：Python 3.11 + Typer + Pydantic + SQLite；当前运行时依赖只有 `pydantic`、`typer`、`rich`（见 `pyproject.toml`）。

## 一、本地服务方案

| 方案 | 最新版本（发布日期） | 许可证 | Python 要求 | 新增运行时依赖 | 要点 |
|---|---|---|---|---|---|
| stdlib `http.server`（`ThreadingHTTPServer` + 自定义 `BaseHTTPRequestHandler`） | 随 CPython 3.11 | PSF | 内置 | 无 | 官方文档明确 “`http.server` is not recommended for production. It only implements basic security checks.”；`ThreadingHTTPServer` 自 3.7 起可用，用于避免浏览器预开 socket 导致阻塞；`SimpleHTTPRequestHandler(directory=...)` 自 3.7 起。命令行模式默认绑定所有接口，需自行绑定 `127.0.0.1`。JSON API、路由、MIME 需手写。 |
| Starlette + Uvicorn | starlette 1.7.0（2026-09-23）；uvicorn 0.53.0（2026-09-14） | BSD-3-Clause / BSD-3-Clause | ≥3.10 | `anyio`、`typing-extensions`；uvicorn 带 `click`、`h11` | ASGI；有 `StaticFiles`、路由、`JSONResponse`；依赖面小。 |
| FastAPI + Uvicorn | fastapi 0.141.1（2026-07-29） | MIT | ≥3.10 | Starlette + `pydantic>=2.9` + `typing-inspection`、`annotated-doc` 等 | 与已有 Pydantic 模型直接复用做 response schema；自动 OpenAPI。对本地单用户只读视图而言功能超出需要。 |
| Flask（Werkzeug 开发服务器） | 3.1.3（2026-02-19） | BSD-3-Clause | ≥3.9 | `werkzeug`、`jinja2`、`itsdangerous`、`blinker`、`markupsafe`、`click` | WSGI；依赖较多，且与 Pydantic 无特别集成。 |
| Bottle | 0.13.4（2025-06-15） | MIT | 未声明 | 无（单文件） | 单文件微框架，可 vendoring；发布节奏较慢。 |

事实补充：
- 项目的 dev 可选依赖 `mcp`（2.2.0）已传递依赖 `starlette` 与 `uvicorn`，但那只是 dev extra，不影响运行时依赖面。
- 无论哪种服务，前端静态资源都可以作为 package data 放进 wheel，用 `importlib.resources` 读取后返回；这与服务框架选择无关。
- 对本地单用户场景，服务端需要做的事很少：返回静态资源 + 一两个 JSON endpoint（图数据、节点详情），并只绑定 `127.0.0.1`。

来源：
- https://docs.python.org/3/library/http.server.html
- https://pypi.org/project/starlette/ ，https://github.com/Kludex/starlette
- https://pypi.org/project/uvicorn/ ，https://github.com/Kludex/uvicorn
- https://pypi.org/project/fastapi/ ，https://github.com/fastapi/fastapi
- https://pypi.org/project/flask/ ，https://pypi.org/project/bottle/
- https://pypi.org/project/mcp/

## 二、前端图库

### 2.1 总表

| 库 | 最新版本（npm 发布日期） | 许可证 | 类型 | 发行文件体积 raw / gz | DAG 布局 | 树布局 | 交互（点击、缩放、样式） | 维护状态（2026-09） |
|---|---|---|---|---|---|---|---|---|
| **Cytoscape.js** | 3.34.3（2026-09-07） | MIT | 渲染 + 交互 + 图模型 + 内置布局 | `cytoscape.min.js` 425 KB / 133 KB | 需扩展（dagre / elk / klay） | 内置 `breadthfirst`（适用于 trees 与 DAG，有 `directed`、`roots` 选项） | 完整：`tap` 事件、选择、pan/zoom、stylesheet 按 data 字段着色；canvas 渲染，3.31 起有 WebGL renderer preview | 活跃，GitHub 当日有 push |
| cytoscape-dagre | 4.0.1（2026-08-28） | MIT | Cytoscape 布局扩展 | 56 KB / 19 KB（**已内置 dagre v3**） | dagre（Sugiyama 类） | 可用（README：“especially suitable for DAGs and trees”） | 继承 Cytoscape | 活跃 |
| cytoscape-elk | 2.3.0（2024-11-26） | MIT | Cytoscape 布局扩展 | 11 KB / 4 KB + elkjs | ELK layered | ELK `mrtree` | 继承 Cytoscape | npm 最后发布 2024-11；依赖声明 `elkjs ^0.9.3`（落后于 elkjs 0.12.0） |
| cytoscape-klay | 3.1.4（2020-10-07） | MIT | Cytoscape 布局扩展 | — | KLay layered（ELK 前身） | — | 继承 Cytoscape | 2020 后无发布，可视为被 ELK 取代 |
| **ELK.js（elkjs）** | 0.12.0（2026-07-17） | **EPL-2.0 OR GPL-3.0-or-later** | 仅布局（无渲染） | `elk.bundled.js` 1572 KB / 456 KB | `layered`（Sugiyama 系，官方称 flagship），支持 ports、分层约束等大量选项 | `mrtree`、`radial` | 无；需配渲染层 | 活跃；支持 Web Worker（`workerUrl`） |
| **dagre**（`@dagrejs/dagre`） | 3.1.1（2026-08-08） | MIT | 仅布局 | `dagre.min.js` 48 KB / 17 KB（+ graphlib 13 KB / 5 KB） | Sugiyama 类，选项较少（`rankdir`、`nodesep`、`ranksep` 等） | 可用（DAG 布局对树同样有效） | 无 | 活跃（v3，TypeScript）。旧包名 `dagre` 停在 0.8.5（2019-12），不应再用 |
| **d3-dag** | 1.2.2（2026-07-05） | MIT | 仅布局 | `d3-dag.iife.min.js` 140 KB / 45 KB | `sugiyama`，可选 `decrossOpt`（最优交叉最小化）、`coordQuad` 等；另有 `zherebko`、`grid` | 无专门树布局（树也可用 sugiyama） | 无；需自己用 SVG / d3 渲染 | 活跃；README 提供 dagre 兼容 API |
| d3-hierarchy | 3.1.2（2022-04-02） | ISC | 仅布局 | 14 KB / 6 KB | 不适用（只接受树） | `tree`（tidy tree / Reingold–Tilford）、`cluster` | 无 | 稳定、低频发布 |
| **vis-network** | 10.1.2（2026-08-19） | Apache-2.0 OR MIT | 渲染 + 交互 + 布局 | standalone UMD 637 KB / 151 KB | `layout.hierarchical`（`sortMethod: 'directed'`、`edgeMinimization`、`blockShifting`） | 同上 hierarchical | 完整：click 事件、physics、pan/zoom | 活跃 |
| **Mermaid** | 12.0.0（2026-09-10） | MIT | 文本 DSL → SVG | `mermaid.min.js` 5445 KB / 1557 KB | v12 起默认 ELK（已内置），可切 `dagre` | `tidy-tree`（独立包 `@mermaid-js/layout-tidy-tree`）或 `elk.mrtree` | 弱：`click nodeId callback` 仅在 `securityLevel: 'loose'` 下可用；无原生 pan/zoom | 非常活跃 |
| AntV G6 | 5.1.1（2026-05-08） | MIT | 渲染 + 交互 + 布局 | `g6.min.js` 1351 KB / 381 KB | 内置 dagre / antv-dagre 等 | 内置多种 tree 布局 | 完整 | 活跃 |
| sigma.js + graphology | sigma 3.0.3（2026-04-30）；graphology 0.26.0 | MIT | WebGL 渲染（大图） | 183 KB / 46 KB + 72 KB / 14 KB | 无层次布局（需外接） | 无 | 有 | 活跃；4.0 在 beta |
| React Flow（`@xyflow/react`） | 12.12.0（2026-09-24） | MIT | React 组件，节点为 DOM | 需 React 构建链 | 需外接 dagre / elkjs / d3-dag | 需外接 | 完整（节点可放任意 HTML） | 非常活跃；要求 React + 构建步骤 |

### 2.2 维度比较

**DAG 布局质量**
- ELK `layered` 选项最丰富（分层策略、交叉最小化、节点放置、ports），通常被视为 JS 中 layered layout 的上限；代价是体积（~456 KB gz）与 EPL/GPL 双许可。
- d3-dag `sugiyama` 提供 dagre 没有的算法：`decrossOpt`（精确最小交叉，基于整数规划，规模大时耗时显著上升）与 `coordQuad`（二次规划坐标）。对“数十到数百节点”范围，默认的启发式 decross 足够；最优解只适合较小的图。
- dagre：经典 Sugiyama 实现，结果尚可、选项少、最轻。
- vis-network hierarchical：基于层级分配 + physics，官方文档注明对高度互连的图 “may not work and it will revert back to the old method”；边交叉优化不如上面三者。
- Cytoscape `breadthfirst`：按 BFS 分层，不做交叉最小化，DAG 质量最弱，但零额外依赖。

**树布局**
- 证明依赖图是 DAG，“树视图”需要先把 DAG 从目标定理展开成树（共享 lemma 重复出现或折叠为引用节点）——这是数据变换，与图库无关。
- 展开后：d3-hierarchy `tree`（tidy tree）、ELK `mrtree`、Cytoscape `breadthfirst`、vis-network hierarchical、Mermaid `tidy-tree` 均可。也可以不用图布局，而用普通 HTML 可折叠列表（`<details>`）实现树视图。

**交互能力**
- 自带交互的“渲染层”：Cytoscape.js、vis-network、G6、sigma.js、React Flow。
- 仅布局（需自写 SVG / canvas 渲染和事件）：ELK.js、dagre、d3-dag、d3-hierarchy。
- Mermaid 面向静态文档，点击回调需放宽 `securityLevel`，不适合作为交互主视图，但可用于“导出 / 嵌入文档”。

**离线 / 打包**
- 以上所有 npm 包都有可直接 vendored 的单文件 UMD / IIFE 发行文件（Cytoscape、cytoscape-dagre、dagre、d3-dag、vis-network standalone、Mermaid、G6、elkjs `elk.bundled.js`），无需 Node 构建链即可放进 `src/proof_cli/.../static/`。
- React Flow 需要 React 与打包工具（Vite 等），会给 Python 项目引入 Node 构建步骤。
- elkjs 可选用 `elk-worker.min.js` 在 Web Worker 中布局，需以本地 URL 提供 worker 文件。

**许可证**
- MIT / ISC / Apache-2.0 OR MIT / BSD：随包分发只需保留版权与许可声明。
- elkjs：`EPL-2.0 OR GPL-3.0-or-later`（仓库 `LICENSE.md` 为 EPL-2.0）。EPL-2.0 是文件级 weak copyleft：原样分发 elkjs 文件需保留许可并说明源码获取途径，修改 elkjs 本身需以 EPL 公开；不传染到项目自身代码。（非法律意见。）

### 2.3 来源

- Cytoscape.js：https://js.cytoscape.org/ ，https://github.com/cytoscape/cytoscape.js ，WebGL preview：https://blog.js.cytoscape.org/2025/01/13/webgl-preview/
- cytoscape-dagre：https://github.com/cytoscape/cytoscape.js-dagre （README：“Dagre v3 is bundled into the distributed extension files”）
- cytoscape-elk：https://github.com/cytoscape/cytoscape.js-elk （`package.json`：`elkjs ^0.9.3`）
- cytoscape-klay：https://github.com/cytoscape/cytoscape.js-klay
- elkjs：https://github.com/kieler/elkjs （README：algorithms 默认含 `layered`、`stress`、`mrtree`、`radial`、`force`、`disco`；Web Worker 支持），许可：https://github.com/kieler/elkjs/blob/master/LICENSE.md ，npm：https://www.npmjs.com/package/elkjs
- dagre：https://github.com/dagrejs/dagre ，https://www.npmjs.com/package/@dagrejs/dagre
- d3-dag：https://github.com/erikbrinkman/d3-dag ，文档：https://erikbrinkman.github.io/d3-dag/
- d3-hierarchy：https://github.com/d3/d3-hierarchy
- vis-network：https://github.com/visjs/vis-network ，布局文档：https://visjs.github.io/vis-network/docs/network/layout.html
- Mermaid：https://github.com/mermaid-js/mermaid ，flowchart Interaction 与 layout 说明（`packages/mermaid/src/docs/syntax/flowchart.md`），layouts（`packages/mermaid/src/docs/config/layouts.md`：“ELK is bundled and default from v12.0.0”）
- AntV G6：https://github.com/antvis/G6
- sigma.js：https://github.com/jacomyal/sigma.js ；graphology：https://github.com/graphology/graphology
- React Flow：https://github.com/xyflow/xyflow

## 三、可行组合（options that fit）

以下均满足：离线 vendored、无 Node 构建链（除非特别说明）、可按状态着色与点击。

| # | 组合 | 前端 vendored 体积（gz，约） | 优点 | 代价 |
|---|---|---|---|---|
| A | stdlib `http.server` + Cytoscape.js + cytoscape-dagre | ~152 KB | 零新增 Python 依赖；一个库同时覆盖 DAG（dagre）与树（`breadthfirst` 或 dagre）视图；交互完备；全 MIT | 手写路由 / JSON；dagre 布局选项有限 |
| B | Starlette + Uvicorn + Cytoscape.js + cytoscape-dagre | ~152 KB | 同 A 的前端；服务端代码更规整（路由、`StaticFiles`、JSON） | 新增 `starlette`、`uvicorn`、`anyio` 等运行时依赖 |
| C | A 或 B 的服务 + Cytoscape.js + ELK（elkjs，可直接调用 elkjs 算坐标后用 Cytoscape `preset` 布局，绕开落后的 cytoscape-elk） | ~590 KB | DAG 布局质量最好；ELK `mrtree` 提供树布局 | 体积大；EPL-2.0 许可需额外声明；cytoscape-elk 扩展本身维护滞后 |
| D | 任一服务 + d3-dag（DAG）+ d3-hierarchy（树）+ 自写 SVG 渲染 | ~51 KB | 最轻；d3-dag 布局质量高于 dagre；SVG 便于样式与导出 | 交互（pan/zoom、选择、点击）需自写，前端代码量最大 |
| E | 任一服务 + vis-network（hierarchical） | ~151 KB | 单库、交互完备、许可宽松 | DAG 分层 / 交叉质量弱于 dagre / ELK；树与 DAG 视图都依赖同一 hierarchical 算法 |
| F | FastAPI + Uvicorn + 以上任一前端 | 同前端 | 复用 Pydantic 模型做 API schema，自动 OpenAPI | 相对本地只读视图功能过剩，依赖最多 |

**明显被支配（dominated）的选项**
- **Mermaid 作为交互主视图**：体积最大（~1.5 MB gz），点击回调要求 `securityLevel: 'loose'`，无原生 pan/zoom；在交互上被 A–E 支配。可保留为“导出 Markdown / 文档嵌入”的次要用途。
- **cytoscape-klay** 与旧 **`dagre` 0.8.5**：分别停更于 2020 与 2019，被 ELK / `@dagrejs/dagre` v3 取代。
- **React Flow**：能力强，但需 React + Node 构建链，与“CLI-first、Python 包直接分发”的约束冲突；在本需求规模下没有换来对应收益。
- **sigma.js**：优势在数千以上节点的 WebGL 渲染，且无层次布局；本需求规模（数十到数百）用不上其优势。
- **G6**：功能与 Cytoscape 重叠而体积约 3 倍（381 KB vs 133 KB gz），在本需求上被 A / B 支配（除非后续需要其特有布局）。
- **Flask**：相对 stdlib 或 Starlette 没有额外收益而依赖更多。

未决问题（留给后续 ticket）：
- 服务端是否值得为结构化路由引入 Starlette（A vs B），取决于 web 应用后续是否需要写操作（例如在浏览器中提交 Acceptance）。
- DAG 视图的布局质量要求是否足以抵消 ELK 的体积与许可成本（A/B vs C），可用一个真实 Proof map 做原型对比。
- 树视图如何处理共享依赖（重复展开 vs 引用节点），属于数据模型问题，与图库无关。
