// PROTOTYPE (issue #142): three variants of the studio's computation mode (a node whose medium is
// `computation`, decided in #141), switchable via ?variant=A|B|C on the existing /studio/<id>/ route.
// Throwaway: branch prototype/computation-studio, never master. Read-only against the project: the
// node's run.sh, out/ and last run are a stub; Run and Open in VS Code only say what they would do.
//   A  Outputs pane: the editor stays; the PDF pane becomes the Outputs pane (Run instead of Compile)
//   B  VS Code first: the editor pane becomes a workspace card (folder, entry, Open in VS Code); outputs on the right
//   C  Agent run log (agent-first): the centre is the agent's own work on the node — retrieval, attempts, runs,
//      outputs, its next step — with the researcher's oversight controls; files behind a tab. This is the
//      shape the researcher asked for on 2026-10-01: an automated, visible, supervisable proof system, not an editor.
"use strict";
(() => {
  const VARIANTS = { A: "Outputs pane", B: "VS Code first", C: "Agent run log (agent-first)" };
  const KEYS = Object.keys(VARIANTS);
  const variant = new URLSearchParams(location.search).get("variant");
  if (!variant || !VARIANTS[variant]) return;

  // ---- the stub: a computation node as #141 lays it out ------------------------------------
  const FOLDER = `${(location.pathname.includes("/studio/") ? "/Users/you/research/proof-project" : ".")}/proofs/${NODE}`;
  const FILES = ["run.sh", "check.py", "requirements.txt", "key-ideas.md", "out/plot.svg", "out/run.log", "out/table.csv"];
  const LAST_RUN = { at: "2026-10-01 09:42", exit: 0, seconds: 12.4, by: "agent_a", evidence: "passed", check_id: "ev-7" };
  const LOG = [
    "$ ./run.sh",
    "python check.py --max-n 10000",
    "n = 1 … 2500: ok (ratio ≤ 1 - 1/n)",
    "n = 2501 … 5000: ok",
    "n = 5001 … 7500: ok",
    "n = 7501 … 10000: ok",
    "worst ratio 0.999900 at n = 10000",
    "wrote out/table.csv, out/plot.svg",
    "exit 0 (12.4s)",
  ].join("\n");
  const TABLE = [["n", "ratio", "bound"], ["10", "0.9000", "0.9000"], ["100", "0.9900", "0.9900"], ["1000", "0.9990", "0.9990"], ["10000", "0.9999", "0.9999"]];

  function h(tag, text, attrs) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    return node;
  }
  const note = (text) => { if (typeof toast === "function") toast(text); else console.log(text); };
  const say = (text) => { const st = document.getElementById("build-status"); if (st) { st.className = "status ok"; st.textContent = text; } note(`PROTOTYPE · ${text}`); };

  // ---- shared pieces ----------------------------------------------------------------------
  function plotSvg() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 420 200"); svg.setAttribute("class", "plot");
    const mk = (tag, attrs, text) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text) e.textContent = text; svg.append(e); return e; };
    mk("rect", { x: 0, y: 0, width: 420, height: 200, fill: "#fff" });
    mk("path", { d: "M40 170 H400 M40 170 V20", stroke: "#999", "stroke-width": 1, fill: "none" });
    let d = "";
    for (let i = 0; i <= 60; i++) { const n = 1 + i * 166; const x = 40 + (i / 60) * 350; const y = 170 - (1 - 1 / n) * 140; d += (i ? " L" : "M") + x.toFixed(1) + " " + y.toFixed(1); }
    mk("path", { d, stroke: "#0071e3", "stroke-width": 2, fill: "none" });
    mk("path", { d: "M40 30 H400", stroke: "#d70015", "stroke-width": 1, "stroke-dasharray": "4 4", fill: "none" });
    mk("text", { x: 44, y: 26, "font-size": 11, fill: "#d70015", "font-family": "sans-serif" }, "bound 1");
    mk("text", { x: 220, y: 192, "font-size": 11, fill: "#666", "text-anchor": "middle", "font-family": "sans-serif" }, "n");
    mk("text", { x: 46, y: 160, "font-size": 11, fill: "#666", "font-family": "sans-serif" }, "ratio(n)");
    return svg;
  }
  function card(path, kind, body) {
    const box = h("div", null, { class: "comp-card" });
    const head = h("div", null, { class: "head" });
    head.append("out/", h("code", path.replace(/^out\//, "")), h("span", kind, { class: "kind" }));
    box.append(head, body);
    return box;
  }
  function outputs() {
    const box = h("div", null, { class: "comp-outputs" });
    box.append(runCard());
    box.append(card("out/plot.svg", "figure", plotSvg()));
    const table = h("table"); for (const [i, row] of TABLE.entries()) { const tr = h("tr"); for (const cell of row) tr.append(h(i ? "td" : "th", cell)); table.append(tr); }
    box.append(card("out/table.csv", "table", table));
    box.append(card("out/run.log", "log", h("pre", LOG)));
    return box;
  }
  function runCard() {
    const box = h("div", null, { class: "comp-run" });
    const line = h("div", null, { class: "line" });
    line.append(h("span", `Last run: exit ${LAST_RUN.exit} · ${LAST_RUN.seconds}s`, { class: `st ${LAST_RUN.exit === 0 ? "ok" : "err"}` }), h("span", `${LAST_RUN.at} · ${LAST_RUN.by}`, { class: "muted" }));
    const ev = h("div", null, { class: "line" });
    ev.append(h("span", `Recorded as Evidence check ${LAST_RUN.check_id}: ${LAST_RUN.evidence}`, { class: "muted" }), h("code", "./run.sh"));
    box.append(line, ev, h("span", "A run is an Evidence check on this candidate proof; it never decides anything (ADR-0004).", { class: "muted" }));
    return box;
  }
  function vscodeButton(primary) {
    const b = h("button", null, { id: "btn-vscode", type: "button", class: primary ? "primary" : "", title: `Open ${FOLDER} in VS Code (vscode://file/…)` });
    b.insertAdjacentHTML("afterbegin", '<svg class="vs" viewBox="0 0 24 24" aria-hidden="true"><path d="M17 3 7.5 11.5 4 8.8 2.5 9.6v4.8l1.5.8 3.5-2.7L17 21l4.5-2.2V5.2zM17 7.4v9.2l-6-4.6z"/></svg>');
    b.append("Open in VS Code");
    b.onclick = () => { say(`would open vscode://file${FOLDER}`); window.open(`vscode://file${FOLDER}`, "_self"); };
    return b;
  }
  function runButton() {
    const b = h("button", null, { type: "button", class: "primary", title: "Run ./run.sh in the node folder; its exit code is recorded as an Evidence check" });
    b.insertAdjacentHTML("afterbegin", typeof icon === "function" ? icon("play") : "");
    b.append("Run");
    b.onclick = () => say("would run ./run.sh, write out/, and record an Evidence check (exit 0 → passed)");
    return b;
  }
  function mediumChip() {
    const observe = () => {
      const panel = document.getElementById("node-panel");
      if (!panel || !panel.firstChild || panel.querySelector(".comp-chip")) return;
      panel.insertBefore(h("span", "medium · computation", { class: "comp-chip", title: "This node's candidate proof is a program (run.sh) and its outputs (out/), not a LaTeX document" }), panel.firstChild);
      const name = document.getElementById("projname"); if (name && !/computation/.test(name.textContent)) name.textContent += " · computation";
    };
    new MutationObserver(observe).observe(document.getElementById("node-panel"), { childList: true });
    observe();
  }
  const hideAll = (...ids) => ids.forEach((id) => { const e = document.getElementById(id); if (e) e.hidden = true; });

  // ---- variant A: the PDF pane becomes the Outputs pane -------------------------------------
  function mountA() {
    const pane = document.getElementById("pdf-pane");
    hideAll("pdf-toolbar", "pdf-scroll", "btn-forward");
    const bar = h("div", null, { class: "comp-toolbar" });
    const status = h("span", `last run exit 0 · ${LAST_RUN.seconds}s · ${LAST_RUN.evidence}`, { class: "status ok" });
    bar.append(runButton(), h("span", "./run.sh → out/", { class: "status" }), status);
    const body = h("div", null, { id: "comp-pane" });
    body.append(outputs());
    pane.append(bar, body);
    document.querySelector("#top .actions.right").prepend(vscodeButton(false));
  }

  // ---- variant B: VS Code first -------------------------------------------------------------
  function mountB() {
    hideAll("editor", "empty-editor", "btn-forward");
    const pane = document.getElementById("editor-pane");
    const ws = h("div", null, { class: "comp-workspace" });
    const cardEl = h("div", null, { class: "comp-ws-card" });
    cardEl.append(h("h2", "This node's work lives in VS Code"), h("div", FOLDER, { class: "path" }));
    const files = h("ul", null, { class: "files" });
    for (const f of FILES.filter((f) => !f.startsWith("out/"))) files.append(h("li", f, { class: f === "run.sh" ? "entry" : "" }));
    cardEl.append(files);
    const buttons = h("div", null, { class: "buttons" });
    buttons.append(vscodeButton(true), runButton());
    cardEl.append(buttons, runCard(), h("p", "run.sh is the entry; whatever it writes to out/ is what the review snapshot freezes with the scripts and key-ideas.md. The agent panel on the right still claims, splits, requests review and records Evidence.", { class: "hint" }));
    ws.append(cardEl);
    pane.append(ws);
    const pdf = document.getElementById("pdf-pane");
    hideAll("pdf-toolbar", "pdf-scroll");
    const bar = h("div", null, { class: "comp-toolbar" }); bar.append(h("span", "Outputs · out/", { class: "status" }));
    const body = h("div", null, { id: "comp-pane" }); body.append(outputs());
    pdf.append(bar, body);
  }

  // ---- variant C: one centre pane, a run log --------------------------------------------------
  function mountC() {
    const editor = document.getElementById("editor-pane"), pdf = document.getElementById("pdf-pane");
    hideAll("pdf-pane");
    for (const g of document.querySelectorAll('.gutter[data-resize="pdf"]')) g.hidden = true;
    const centre = h("section", null, { id: "comp-centre" });
    editor.parentNode.insertBefore(centre, editor);
    editor.hidden = true;
    const tabs = h("div", null, { class: "comp-tabs" });
    const tabRun = h("button", "Run log", { type: "button", class: "tab active" }), tabFiles = h("button", "Files", { type: "button", class: "tab" });
    tabs.append(tabRun, tabFiles, h("span", null, { style: "flex:1" }), runButton(), vscodeButton(false));
    tabRun.onclick = () => { tabRun.classList.add("active"); tabFiles.classList.remove("active"); editor.hidden = true; centre.hidden = false; };
    tabFiles.onclick = () => { tabFiles.classList.add("active"); tabRun.classList.remove("active"); centre.hidden = true; editor.hidden = false; };
    const log = h("div", null, { class: "comp-log" });
    // the agent's standing on the node, and the researcher's oversight: what it is doing, what it will do next, and the
    // three things a human can do without typing a prompt — pause it, redirect it, review what it has produced
    const agent = h("div", null, { class: "comp-run comp-agent" });
    const head = h("div", null, { class: "line" });
    head.append(h("span", "agent_a · working on this node", { class: "st ok" }), h("span", "claimed 09:30 · step 4 of 5", { class: "muted" }));
    const plan = h("ol", null, { class: "comp-plan" });
    for (const [done, text] of [[true, "Retrieval: read L1, L2 and the cited result; nothing in the project settles n ≤ 10⁴"], [true, "Wrote check.py: the ratio against the bound, n = 1 … 10⁴"], [true, "Ran it: exit 0, worst ratio 0.9999 at n = 10⁴ (Evidence check ev-7, passed)"], [false, "Drafting key-ideas.md: what was computed, why it establishes the statement, where it could be wrong"], [false, "Request review"]]) {
      const li = h("li", text, { class: done ? "done" : "" }); plan.append(li);
    }
    const controls = h("div", null, { class: "buttons" });
    const ctl = (text, title, primary) => { const b = h("button", text, { type: "button", class: primary ? "primary" : "", title }); b.onclick = () => say(`would ${title}`); return b; };
    controls.append(ctl("Pause", "pause the agent after its current step; it keeps the claim", false), ctl("Redirect…", "tell the agent what to do differently, in one line; it continues on its own", false), ctl("Review what it has", "open the review sheet on the files as they stand (a snapshot is frozen first)", true));
    agent.append(head, plan, controls, h("span", "The agent works on its own; this is where you watch it and step in. You never edit its prompt to make it move.", { class: "muted" }));
    log.append(agent, runCard(), h("div", `run · ${LAST_RUN.at} · ${LAST_RUN.by}`, { class: "divider" }));
    const entry = (t, body) => { const e = h("div", null, { class: "entry" }); e.append(h("span", t, { class: "t" }), body); return e; };
    const lines = LOG.split("\n");
    log.append(entry("00:00.0", h("pre", lines.slice(0, 2).join("\n"))));
    log.append(entry("00:03.1", h("pre", lines.slice(2, 6).join("\n"))));
    log.append(entry("00:12.0", h("pre", lines[6])));
    log.append(entry("00:12.3", card("out/table.csv", "table", (() => { const table = h("table"); for (const [i, row] of TABLE.entries()) { const tr = h("tr"); for (const cell of row) tr.append(h(i ? "td" : "th", cell)); table.append(tr); } return table; })())));
    log.append(entry("00:12.4", card("out/plot.svg", "figure", plotSvg())));
    log.append(entry("00:12.4", h("pre", lines.slice(7).join("\n"))));
    log.append(h("div", "earlier runs", { class: "divider" }), entry("09:31", h("pre", "exit 1 (3.2s) — recorded as Evidence check ev-6: failed — ModuleNotFoundError: numpy")));
    centre.append(tabs, log);
    // the Files tab shows the editor pane inside the centre; keep it simple: toggle visibility only
  }

  // ---- the switcher -----------------------------------------------------------------------
  function switcher() {
    const bar = h("div", null, { class: "proto-bar", role: "group", "aria-label": "Prototype variant" });
    const go = (delta) => { const next = KEYS[(KEYS.indexOf(variant) + delta + KEYS.length) % KEYS.length]; const u = new URL(location); u.searchParams.set("variant", next); location.href = u; };
    const prev = h("button", "‹", { type: "button", title: "Previous variant (←)" }); prev.onclick = () => go(-1);
    const next = h("button", "›", { type: "button", title: "Next variant (→)" }); next.onclick = () => go(1);
    const lbl = h("span", null, { class: "lbl" }); lbl.append(h("b", variant), VARIANTS[variant], h("span", `?variant=${variant}`, { class: "q" }));
    bar.append(prev, lbl, next);
    document.body.append(bar);
    document.addEventListener("keydown", (ev) => {
      const a = document.activeElement;
      if (a && (["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName) || a.isContentEditable || a.closest(".CodeMirror"))) return;
      if (ev.key === "ArrowLeft") go(-1); else if (ev.key === "ArrowRight") go(1);
    });
  }

  const mount = () => {
    mediumChip();
    if (variant === "A") mountA();
    if (variant === "B") mountB();
    if (variant === "C") mountC();
    switcher();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();
