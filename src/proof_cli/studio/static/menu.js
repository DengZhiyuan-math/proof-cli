/* The agent panel's "+" menu (spec #145, story 48): the researcher's oversight of the agent's run first — Start, then
   Pause / Resume, Redirect, Review what it has, Stop and release — then, under "Ask the agent to…", the one-off
   tasks reworded by role, each run as that role's single turn with the task as its redirect (never a prompt the
   researcher writes), and the read-only check of a snapshot awaiting review; last, when one awaits it, the
   researcher's own decision, which opens the review sheet and is never the agent's (ADR-0010). The run is
   run.js's globalThis.studioRun, the review node.js's globalThis.studioReview; askAgent and showCentre are
   app.js's. Harnessed on its own (tests/js/plus_menu_harness.js). */
"use strict";

// The one-off tasks: [label, role, the task handed to that role's turn]
const AGENT_TASKS = [
  ["Prover · propose a split", "prover", "This node is too large to prove directly. Propose Claims that together prove it, then split the node into them."],
  ["Prover · edit dependencies", "prover", "Change one of this node's dependency edges: add a Lemma the proof uses, remove one it doesn't, or move one onto a split child."],
  ["Prover · open a Challenge", "prover", "Open a Challenge on the dependency that may no longer hold, and say why."],
  ["Typesetter · draft key ideas", "typesetter", "Write key-ideas.md from the draft and proof.tex: 核心思路, 主要步骤, 难点, 未覆盖."],
  ["Typesetter · compile and fix", "typesetter", "Compile proof.tex and fix what fails, without changing the mathematics."],
  ["Numerics · run a check", "numerics", "Run the computation that checks this node's statement and record what it showed."],
];

function plusMenu(open) {
  const menu = $("#plus-menu");
  if (open === undefined) open = menu.hidden;
  $("#chat-plus").setAttribute("aria-expanded", String(open));
  if (!open) { menu.hidden = true; return; }
  const node = (tag, cls, text) => { const e = document.createElement(tag); e.className = cls; if (text) e.textContent = text; return e; };
  const item = (label, run, title, cls = "") => {
    const b = node("button", `menu-item ${cls}`.trim(), label);
    b.type = "button"; b.setAttribute("role", "menuitem"); if (title) b.title = title;
    b.onclick = () => { plusMenu(false); run(); };
    return b;
  };
  const review = typeof globalThis.studioReview === "function" ? globalThis.studioReview() : null;
  const run = globalThis.studioRun || null;
  const state = run ? run.state() : null;
  const active = !!(state && state.active);  // the run's own view says whether it is under way
  const rows = [node("div", "menu-head", "The agent")];
  if (!run) rows.push(node("div", "menu-head", "no run on this page"));
  else if (!active) rows.push(item("Start agent", () => run.start(), "The agent works the node on its own until it requests review or needs you"));
  else {
    rows.push(item(state.status === "paused" ? "Resume" : "Pause", () => (state.status === "paused" ? run.resume() : run.pause()), "The turn finishes; the agent keeps the node"));
    rows.push(item("Redirect…", () => { showCentre("run"); run.focusRedirect(); }, "One line, handed to its next turn: type it in the run card"));
    rows.push(item("Review what it has", () => run.reviewNow(), "Freeze a snapshot of the folder as it stands and review it"));
    rows.push(item("Stop and release", () => run.release(), "End the run and unassign the node"));
  }
  if (run || review) rows.push(node("hr", "menu-sep"), node("div", "menu-head", "Ask the agent to…"));
  if (run) {
    for (const [label, role, task] of AGENT_TASKS) {
      const row = item(label, () => run.start([role], task), active ? "Finish or stop the run first: one role's turn runs on its own" : task);
      row.disabled = active;
      rows.push(row);
    }
  }
  if (review) rows.push(item(`Check snapshot v${review.version}`, () => askAgent(review.check), "Read-only: the agent reports what does not hold"));
  if (review) rows.push(node("hr", "menu-sep"), node("div", "menu-head", "Your decision"), item(`Review snapshot v${review.version}…`, review.open, "Accept, request a revision or reject: recorded as you", "decide"));
  $("#review-card").hidden = true;
  menu.replaceChildren(...rows);
  menu.hidden = false;
}
$("#chat-plus").addEventListener("click", (e) => { e.stopPropagation(); plusMenu(); });
document.addEventListener("click", (e) => { if (!e.target.closest("#plus-menu, #chat-plus")) plusMenu(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { plusMenu(false); $("#review-card").hidden = true; } });
