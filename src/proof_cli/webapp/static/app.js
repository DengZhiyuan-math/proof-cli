// Proof review — the proof map's page where the researcher makes Human Review decisions (ADR-0010).
// The server records each decision as its own git identity and commits it with the snapshot.
// Everything from the project is inserted as text, never HTML, and proof text is never rendered.
"use strict";

const $ = (id) => document.getElementById(id);

// -- the server ------------------------------------------------------------------
async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const json = await response.json();
  if (!json.ok) throw Object.assign(new Error(json.error.message), { code: json.error.code, details: json.error });
  return json.data;
}

// A message in the corner: successes fade on their own, errors stay until dismissed.
function say(text, kind) {
  const toast = el("div", null, { class: `toast ${kind || "info"}`, role: kind === "error" ? "alert" : "status" });
  const close = el("button", "×", { type: "button", "aria-label": "Dismiss" });
  close.onclick = () => toast.remove();
  toast.append(el("span", text, { class: "toast-text" }), close);
  $("toasts").append(toast);
  while ($("toasts").children.length > 4) $("toasts").firstChild.remove();
  if (kind !== "error") setTimeout(() => toast.remove(), 7000);
}

function el(tag, text, attrs) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  return node;
}

function row(cells) {
  const tr = document.createElement("tr");
  for (const cell of cells) {
    const td = document.createElement("td");
    if (cell instanceof Node) td.appendChild(cell); else td.textContent = cell === null || cell === undefined ? "—" : String(cell);
    tr.appendChild(td);
  }
  return tr;
}

function emptyRow(text, columns) {
  const tr = document.createElement("tr");
  tr.append(el("td", text, { colspan: columns, class: "none" }));
  return tr;
}

function nodeHref(id) { return `#/node/${encodeURIComponent(id)}`; }

function when(iso) {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return iso || "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// A SHA-256 shown short, the full value a click away on the clipboard (and in the tooltip).
function sha(value) {
  const chip = el("button", `${value.slice(0, 12)}…`, { type: "button", class: "sha small", title: `SHA-256 ${value} — click to copy` });
  chip.onclick = async () => {
    try { await navigator.clipboard.writeText(value); say("SHA-256 copied.", "ok"); } catch { say(value); }
  };
  return chip;
}

// -- recording decisions ------------------------------------------------------------
// what each decision means, in the researcher's words
const DECISION_LABELS = {
  "acceptance:accept": "Accept this Candidate proof",
  "acceptance:revision-requested": "Request a revision",
  "acceptance:reject": "Reject (final)",
  "reference_review:reference-review": "Reference-review: the citation can be relied on",
  "reference_review:no-longer-callable": "No longer callable (final — cite a corrected source as a new node)",
  "promote:promote": "Promote this Claim to a Lemma",
  "dependency_revalidation:reaffirmed": "Lightweight re-review: the proof still holds against the new version",
  "evidence_review:trusted": "Trust this Evidence check",
  "evidence_review:unusable": "Mark this Evidence check unusable",
  "challenge_resolution:dismissed": "Dismiss this Challenge (a false alarm)",
};
// decisions that can't be taken back: they get a louder treatment everywhere they appear
const FINAL = new Set(["acceptance:reject", "reference_review:no-longer-callable"]);
const KIND_LABELS = { acceptance: "Acceptance", reference_review: "Reference review" };

const labelOf = (d) => DECISION_LABELS[`${d.kind}:${d.decision}`] || `${d.kind}: ${d.decision}`;
const isFinal = (d) => FINAL.has(`${d.kind}:${d.decision}`);

// Show exactly what will be recorded, then record it.
function confirmDecisions(decisions) {
  return new Promise((resolve, reject) => {
    const dialog = $("confirm");
    $("confirm-reviewer").textContent = state ? state.reviewer : "this process's git identity";
    $("confirm-decisions").replaceChildren(...decisions.map((d) => {
      const li = el("li", null, { class: isFinal(d) ? "final" : "" });
      li.append(el("div", labelOf(d), { class: "what" }));
      if (isFinal(d)) li.append(el("div", "Final: this can't be undone from here.", { class: "final-note" }));
      li.append(el("div", `on ${d.target_id}${d.dependency_id ? ` (dependency ${d.dependency_id})` : ""}`, { class: "detail" }));
      if (d.viewed_candidate_proof_sha256) li.append(el("div", `snapshot SHA-256 ${d.viewed_candidate_proof_sha256}`, { class: "detail" }));
      li.append(el("div", `rationale: ${d.rationale || "none"}`, { class: "detail" }));
      return li;
    }));
    const record = $("confirm-record");
    record.textContent = decisions.length > 1 ? `Record ${decisions.length} decisions` : "Record";
    record.className = decisions.some(isFinal) ? "danger" : "primary";
    const finish = (ok) => {
      dialog.onclose = null;
      if (dialog.open) dialog.close();
      if (ok) resolve(); else reject(new Error("cancelled"));
    };
    $("confirm-cancel").onclick = () => finish(false);
    record.onclick = () => finish(true);
    dialog.onclose = () => finish(false); // Escape
    dialog.showModal();
    $("confirm-cancel").focus(); // the safe choice is the default one
  });
}

async function decide(decisions) {
  await confirmDecisions(decisions);
  const outcome = await api("/api/decide", { decisions });
  const failed = outcome.results.filter((result) => !result.ok);
  if (failed.length) say(failed.map((f) => `${f.target_id}: ${f.error.code} — ${f.error.message}`).join("; "), "error");
  else say(`Recorded ${outcome.results.length} decision(s).`, "ok");
  await refresh();
}

function showError(error) { if (error.message !== "cancelled") say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }

// -- the home page ---------------------------------------------------------------------
let state = null;

function showWarnings(list, into) {
  into.replaceChildren(...list.map((w) => {
    const li = el("li", null, { class: "warning" });
    li.append(el("code", w.code), el("span", w.message));
    const nodeId = w.details && (w.details.node_id || w.details.target_node_id);
    if (nodeId) li.append(el("a", `open ${nodeId}`, { href: nodeHref(nodeId) }));
    return li;
  }));
  if (!list.length) into.append(el("li", "None.", { class: "none" }));
}

function showStats() {
  const nodes = mapData ? mapData.nodes : [];
  $("stat-nodes").textContent = nodes.length;
  $("stat-frontier").textContent = nodes.filter((n) => n.frontier).length;
  $("stat-pending").textContent = state.pending.length;
  $("stat-warnings").textContent = state.warnings.length;
  document.querySelector(".stat.review").classList.toggle("has", state.pending.length > 0);
  document.querySelector(".stat.warn").classList.toggle("has", state.warnings.length > 0);
}

function pendingItem(item) {
  const card = el("article", null, { class: "pending-item" });
  card.dataset.kind = item.kind; card.dataset.target = item.node_id;
  if (item.candidate_proof && item.candidate_proof.sha256) card.dataset.viewed = item.candidate_proof.sha256;
  const box = el("input", null, { type: "checkbox", class: "pick", "aria-label": `Decide on ${item.node_id}` });
  const body = el("div");
  const top = el("div", null, { class: "pending-top" });
  top.append(el("a", item.node_id, { href: nodeHref(item.node_id) }), el("span", KIND_LABELS[item.kind] || item.kind, { class: "badge tone-review" }));
  if (item.acceptance_state) top.append(el("span", item.acceptance_state, { class: "badge" }));
  body.append(top, el("div", item.statement, { class: "pending-statement" }));
  if (item.candidate_proof && item.candidate_proof.id) {
    // shown in full: recording the decision is about exactly this text
    const meta = el("div", null, { class: "meta-line" });
    meta.append(el("span", `snapshot v${item.candidate_proof.version}`), sha(item.candidate_proof.sha256));
    const details = el("details", null, { class: "snapshot", open: "" });
    details.append(el("summary", "The exact LaTeX being decided on"), el("pre", item.candidate_proof.text));
    body.append(meta, details);
  }
  const controls = el("div", null, { class: "pending-controls" });
  const choice = el("select", null, { class: "choice", "aria-label": `Outcome for ${item.node_id}` });
  for (const decision of item.decisions) choice.append(el("option", labelOf({ kind: item.kind, decision }), { value: decision }));
  const rationale = el("input", null, { class: "rationale", placeholder: "Rationale — why?", "aria-label": `Rationale for ${item.node_id}` });
  controls.append(choice, rationale);
  body.append(controls);
  card.append(box, body);
  const sync = () => {
    card.classList.toggle("selected", box.checked);
    choice.classList.toggle("final", isFinal({ kind: item.kind, decision: choice.value }));
    updateSelection();
  };
  box.addEventListener("change", sync);
  // choosing an outcome or writing a rationale means this one is being decided
  choice.addEventListener("change", () => { box.checked = true; sync(); });
  rationale.addEventListener("input", () => { if (rationale.value && !box.checked) { box.checked = true; sync(); } });
  sync();
  return card;
}

function pendingCards() { return [...$("pending").querySelectorAll(".pending-item")]; }

function updateSelection() {
  const cards = pendingCards();
  const picked = cards.filter((card) => card.querySelector(".pick").checked).length;
  $("selected-count").textContent = `${picked} of ${cards.length} selected`;
  $("decide-batch").disabled = picked === 0;
  $("decide-batch").textContent = picked > 1 ? `Record ${picked} decisions` : "Record selected decision";
  $("select-all").checked = cards.length > 0 && picked === cards.length;
  $("select-all").indeterminate = picked > 0 && picked < cards.length;
}

function showHome() {
  $("pending").replaceChildren(...state.pending.map(pendingItem));
  $("pending-count").textContent = state.pending.length || "";
  $("batch-bar").hidden = !state.pending.length;
  if (!state.pending.length) $("pending").append(el("div", "Nothing is awaiting review.", { class: "empty" }));
  updateSelection();
  showWarnings(state.warnings, $("warnings"));
  showStats();
}

// -- the map (ADR-0008): the DAG is canonical, the tree a rooted explanation of it ----------
let mapData = null;
let mapView = "dag";
let mapScale = 1;
const SVG_NS = "http://www.w3.org/2000/svg";
const BOX = { w: 188, h: 60, gapX: 28, gapY: 74, pad: 24 };

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  return node;
}

function toneOf(n) {
  if (["accepted", "reviewed"].includes(n.acceptance_state)) return "accepted";
  if (["rejected", "no-longer-callable"].includes(n.acceptance_state)) return "rejected";
  if (n.workflow_state === "review-needed") return "review";
  return "none";
}

// which warning a node carries, each drawn differently: challenged, potentially stale, or a decision that no longer applies
function warningOf(n) {
  if (n.integrity_state === "challenged") return "challenged";
  if (n.integrity_state === "potentially-stale") return "stale";
  if (n.acceptance_state === "unverifiable") return "unverifiable";
  return "";
}

function short(text, length) { return text.length > length ? text.slice(0, length - 1) + "…" : text; }

// the find box and the frontier toggle: which nodes to pick out (null when nothing is being looked for)
function mapMatcher() {
  const query = $("map-filter").value.trim().toLowerCase();
  const frontierOnly = $("frontier-only").checked;
  if (!query && !frontierOnly) return null;
  return (n) => (!frontierOnly || n.frontier)
    && (!query || [n.id, n.kind, n.display_label || "", n.statement, n.assignee || ""].some((field) => field.toLowerCase().includes(query)));
}

// Layers by longest path from the top (a node sits below everything that depends on it),
// then a few barycenter sweeps to cut crossings. Enough for tens to hundreds of nodes.
function layers(nodes) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const dependents = new Map(nodes.map((n) => [n.id, []]));
  for (const n of nodes) for (const d of n.dependencies) if (dependents.has(d)) dependents.get(d).push(n.id);
  const depth = new Map();
  const visiting = new Set();
  const depthOf = (id) => {
    if (depth.has(id)) return depth.get(id);
    if (visiting.has(id)) return 0; // never in a DAG; just don't loop
    visiting.add(id);
    const ups = dependents.get(id);
    const value = ups.length ? 1 + Math.max(...ups.map(depthOf)) : 0;
    visiting.delete(id);
    depth.set(id, value);
    return value;
  };
  nodes.forEach((n) => depthOf(n.id));
  const sparse = [];
  for (const n of nodes) (sparse[depth.get(n.id)] ||= []).push(n.id);
  const rows = sparse.filter(Boolean); // contiguous in any DAG; compacted in case a cycle slipped in
  rows.forEach((row) => row.sort());
  const pos = new Map();
  const place = () => rows.forEach((row) => row.forEach((id, i) => pos.set(id, i - (row.length - 1) / 2)));
  const bary = (id, neighbours) => {
    const xs = neighbours.filter((x) => pos.has(x)).map((x) => pos.get(x));
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : pos.get(id);
  };
  place();
  for (let sweep = 0; sweep < 6; sweep++) {
    for (let i = 1; i < rows.length; i++) { rows[i].sort((a, b) => bary(a, dependents.get(a)) - bary(b, dependents.get(b))); place(); }
    for (let i = rows.length - 2; i >= 0; i--) { rows[i].sort((a, b) => bary(a, byId.get(a).dependencies) - bary(b, byId.get(b).dependencies)); place(); }
  }
  return rows;
}

let dagSize = { width: 0, height: 0 };

function applyScale() {
  const box = $("dag-svg");
  box.setAttribute("width", Math.round(dagSize.width * mapScale));
  box.setAttribute("height", Math.round(dagSize.height * mapScale));
  $("zoom-fit").textContent = `${Math.round(mapScale * 100)}%`;
}

function fitScale() {
  const room = $("map-dag").clientWidth - 2;
  return dagSize.width && room > 0 ? Math.min(1, room / dagSize.width) : 1;
}

function drawDag(nodes) {
  const box = $("dag-svg");
  box.replaceChildren();
  box.classList.remove("tracing", "filtering");
  if (!nodes.length) {
    dagSize = { width: 460, height: 64 };
    box.setAttribute("viewBox", "0 0 460 64");
    box.append(Object.assign(svg("text", { x: 20, y: 38, class: "empty" }), { textContent: "No nodes yet: create one with `proof node create`." }));
    applyScale();
    return;
  }
  const rows = layers(nodes);
  const widest = Math.max(...rows.map((row) => row.length));
  const width = BOX.pad * 2 + widest * BOX.w + (widest - 1) * BOX.gapX;
  const height = BOX.pad * 2 + rows.length * BOX.h + (rows.length - 1) * BOX.gapY + 16;
  dagSize = { width, height };
  box.setAttribute("viewBox", `0 0 ${width} ${height}`);
  applyScale();
  const at = new Map();
  rows.forEach((row, r) => row.forEach((id, i) => {
    const rowWidth = row.length * BOX.w + (row.length - 1) * BOX.gapX;
    at.set(id, { x: (width - rowWidth) / 2 + i * (BOX.w + BOX.gapX) + BOX.w / 2, y: BOX.pad + r * (BOX.h + BOX.gapY) + BOX.h / 2 });
  }));
  const defs = svg("defs");
  const marker = svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  marker.append(svg("path", { d: "M0,0 L10,5 L0,10 z", fill: "var(--map-edge)" }));
  defs.append(marker);
  box.append(defs);
  const edges = [];
  for (const n of nodes) for (const d of n.dependencies) {
    const from = at.get(n.id), to = at.get(d);
    if (!from || !to) continue;
    const y1 = from.y + BOX.h / 2, y2 = to.y - BOX.h / 2;
    const path = svg("path", { class: "edge", "marker-end": "url(#arrow)", d: `M${from.x},${y1} C${from.x},${y1 + 34} ${to.x},${y2 - 34} ${to.x},${y2}` });
    edges.push({ path, from: n.id, to: d });
    box.append(path);
  }
  const groups = new Map();
  // hovering or focusing a node traces what it depends on and what depends on it
  const trace = (id) => {
    box.classList.toggle("tracing", id !== null);
    const near = new Set(id === null ? [] : [id]);
    for (const edge of edges) {
      const touches = id !== null && (edge.from === id || edge.to === id);
      edge.path.classList.toggle("near", touches);
      if (touches) { near.add(edge.from); near.add(edge.to); }
    }
    for (const [nodeId, g] of groups) g.classList.toggle("near", near.has(nodeId));
  };
  const matches = mapMatcher();
  box.classList.toggle("filtering", !!matches);
  for (const n of nodes) {
    const { x, y } = at.get(n.id);
    const classes = ["node", n.frontier ? "frontier" : "", warningOf(n), matches && matches(n) ? "match" : ""].filter(Boolean).join(" ");
    const blocked = n.blocked_reason ? `, blocked: ${n.blocked_reason}` : "";
    const g = svg("g", { class: classes, tabindex: 0, role: "link", "aria-label": `${n.kind} ${n.id}: ${n.acceptance_state}, ${n.workflow_state}${blocked}, ${n.integrity_state}${n.assignee ? `, claimed by ${n.assignee}` : ""}${n.frontier ? ", on the frontier" : ""}` });
    g.append(svg("rect", { class: "box", x: x - BOX.w / 2, y: y - BOX.h / 2, width: BOX.w, height: BOX.h, rx: 8 }));
    g.append(svg("rect", { class: `bar ${toneOf(n)}`, x: x - BOX.w / 2, y: y - BOX.h / 2, width: 5, height: BOX.h, rx: 2 }));
    const kind = svg("text", { class: "kind", x: x - BOX.w / 2 + 12, y: y - BOX.h / 2 + 15 });
    kind.textContent = short(`${n.kind} · ${n.id}`, 32);
    const label = svg("text", { class: "label", x: x - BOX.w / 2 + 12, y: y + 4 });
    label.textContent = short(n.display_label || n.statement, 25);
    const meta = svg("text", { class: "meta", x: x - BOX.w / 2 + 12, y: y + BOX.h / 2 - 9 });
    meta.textContent = short([n.acceptance_state, n.workflow_state, n.integrity_state !== "current" ? n.integrity_state : "", n.assignee ? `@${n.assignee}` : ""].filter(Boolean).join(" · "), 34);
    g.append(kind, label, meta);
    if (n.frontier) {
      const tag = svg("text", { class: "tag", x: x, y: y + BOX.h / 2 + 13, "text-anchor": "middle" });
      tag.textContent = "ready to claim";
      g.append(tag);
    }
    const title = svg("title");
    title.textContent = `${n.id}${n.display_label ? ` — ${n.display_label}` : ""}\n${n.statement}\n\n${n.acceptance_state} · ${n.workflow_state}${n.blocked_reason ? ` (${n.blocked_reason})` : ""} · ${n.integrity_state}${n.assignee ? ` · claimed by ${n.assignee}` : ""}`;
    g.append(title);
    const open = () => { location.hash = nodeHref(n.id); };
    g.addEventListener("click", open);
    g.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
    g.addEventListener("mouseenter", () => trace(n.id));
    g.addEventListener("mouseleave", () => trace(null));
    g.addEventListener("focus", () => trace(n.id));
    g.addEventListener("blur", () => trace(null));
    groups.set(n.id, g);
    box.append(g);
  }
}

// The tree answers "how is this proved?": a shared dependency is expanded in full under each of its
// parents, marked as shared (ADR-0008), so every branch reads to the bottom. Only a cycle is cut.
function drawTree(nodes) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parents = new Map();
  for (const n of nodes) for (const d of n.dependencies) parents.set(d, (parents.get(d) || 0) + 1);
  const select = $("tree-root");
  const roots = [...nodes.filter((n) => !parents.has(n.id)), ...nodes.filter((n) => parents.has(n.id))];
  const chosen = select.value && byId.has(select.value) ? select.value : (roots[0] || {}).id;
  select.replaceChildren(...roots.map((n) => el("option", `${n.id} (${n.kind})`, { value: n.id })));
  if (chosen) select.value = chosen;
  const matches = mapMatcher();
  const item = (id, ancestors) => {
    const n = byId.get(id);
    const li = el("li");
    if (!n) { li.append(el("span", `${id} (missing)`, { class: "warning" })); return li; }
    if (matches && !matches(n)) li.classList.add("dim");
    const line = el("div", null, { class: "tree-row" });
    line.append(el("a", n.id, { href: nodeHref(n.id) }), el("span", short(n.display_label || n.statement, 70), { class: "tree-label", title: n.statement }));
    const tone = toneOf(n);
    line.append(el("span", n.acceptance_state, { class: `state-chip${tone === "none" ? "" : ` tone-${tone}`}` }), el("span", n.workflow_state, { class: "state-chip", title: n.blocked_reason || "" }));
    line.append(el("span", n.integrity_state, { class: `state-chip${n.integrity_state === "current" ? "" : " warn-chip"}` }));
    if (n.assignee) line.append(el("span", `@${n.assignee}`, { class: "state-chip" }));
    if (n.frontier) line.append(el("span", "ready to claim", { class: "state-chip tone-frontier" }));
    if ((parents.get(id) || 0) > 1) line.append(el("span", "shared", { class: "state-chip shared-chip", title: `used by ${parents.get(id)} nodes; see the DAG` }));
    li.append(line);
    if (ancestors.has(id)) { line.append(el("span", "(cycle: not expanded again)", { class: "hint" })); return li; }
    if (n.dependencies.length) {
      const below = new Set(ancestors).add(id);
      const ul = el("ul");
      n.dependencies.forEach((d) => ul.append(item(d, below)));
      li.append(ul);
    }
    return li;
  };
  const tree = el("ul");
  if (chosen) tree.append(item(chosen, new Set()));
  else tree.append(el("li", "No nodes yet: create one with `proof node create`.", { class: "hint" }));
  $("map-tree").replaceChildren(tree);
}

function showMap() {
  const nodes = mapData.nodes;
  const frontier = nodes.filter((n) => n.frontier).length;
  const matches = mapMatcher();
  const found = matches ? nodes.filter(matches).length : null;
  $("map-caption").textContent = `${nodes.length} node(s) · ${frontier} on the frontier`
    + (found === null ? " · click a node to open it, hover to trace its neighbours" : ` · ${found} match${found === 1 ? "" : "es"}${found ? " (Enter opens the first)" : ""}`);
  $("map-dag").hidden = mapView !== "dag";
  $("map-tree").hidden = mapView !== "tree";
  $("tree-root-label").hidden = mapView !== "tree";
  $("zoom-controls").hidden = mapView !== "dag";
  $("view-dag").setAttribute("aria-pressed", String(mapView === "dag"));
  $("view-tree").setAttribute("aria-pressed", String(mapView === "tree"));
  if (mapView === "dag") drawDag(nodes); else drawTree(nodes);
}

// -- a node's page ------------------------------------------------------------------------
async function openInPrism(nodeId) {
  try {
    const result = await api(`/api/node/${encodeURIComponent(nodeId)}/open`, {});
    if (result.opened) say(`Opened ${result.folder} in prism-local${result.url ? ` at ${result.url}` : ""}.`, "ok");
    else if (result.error) say(`prism-local didn't start: ${result.error}. The node's folder: ${result.folder}`, "error");
    else say(`prism-local isn't configured (${result.hint}). The node's folder: ${result.folder}`);
  } catch (error) { showError(error); }
}

function axisBadge(axis, value, tone) {
  const badge = el("span", null, { class: `badge${tone ? ` tone-${tone}` : ""}` });
  badge.append(el("span", `${axis}`, { class: "axis" }), el("span", value));
  return badge;
}

function decisionCard(decision, proof) {
  const card = el("div", null, { class: `decision${isFinal(decision) ? " final" : ""}` });
  const what = el("div");
  what.append(el("div", labelOf(decision), { class: "decision-title" }), el("div", decision.dependency_id ? `dependency ${decision.dependency_id}` : decision.target_id, { class: "decision-on" }));
  const rationale = el("input", null, { placeholder: "Rationale — why?", "aria-label": `Rationale: ${labelOf(decision)}` });
  const button = el("button", "Record…", { type: "button", class: isFinal(decision) ? "danger" : "primary" });
  button.onclick = async () => {
    const binds = ["acceptance", "promote", "dependency_revalidation"].includes(decision.kind) && proof;
    try { await decide([{ ...decision, rationale: rationale.value, ...(binds ? { viewed_candidate_proof_sha256: proof.sha256 } : {}) }]); }
    catch (error) { showError(error); }
  };
  rationale.addEventListener("keydown", (event) => { if (event.key === "Enter") button.click(); });
  card.append(what, rationale, button);
  return card;
}

function listOr(into, items, emptyText) {
  into.replaceChildren(...items);
  if (!items.length) into.append(el("li", emptyText, { class: "none" }));
}

async function showNode(nodeId) {
  $("node-title").textContent = nodeId;
  const view = await api(`/api/node/${encodeURIComponent(nodeId)}`);
  const node = view.node;
  const onMap = mapData && mapData.nodes.find((n) => n.id === node.id);
  document.title = `${node.id} · Proof map`;
  $("node-kind").textContent = node.kind.replace(/_/g, " ");
  $("node-title").textContent = node.id;
  $("node-label").textContent = node.display_label || "";
  const acceptanceTone = ["accepted", "reviewed"].includes(view.acceptance_state) ? "accepted"
    : ["rejected", "no-longer-callable", "unverifiable"].includes(view.acceptance_state) ? "rejected" : "";
  const axes = [
    axisBadge("workflow", view.workflow_state + (onMap && onMap.blocked_reason ? ` (${onMap.blocked_reason})` : ""), view.workflow_state === "review-needed" ? "review" : ""),
    axisBadge("acceptance", view.acceptance_state, acceptanceTone),
    axisBadge("integrity", view.integrity_state, view.integrity_state === "current" ? "" : "warn"),
  ];
  if (onMap && onMap.frontier) axes.push(el("span", "ready to claim", { class: "badge tone-frontier" }));
  $("node-axes").replaceChildren(...axes);
  $("node-warnings").replaceChildren();
  if (view.warnings.length) {
    const banner = el("div", null, { class: "banner", role: "alert" });
    const list = el("ul", null, { class: "warning-list" });
    showWarnings(view.warnings, list);
    banner.append(el("h3", "Warnings for this node"), list);
    $("node-warnings").append(banner);
  }
  $("node-statement").textContent = node.statement;
  $("node-assumptions").replaceChildren(...(node.assumptions.length ? [el("h3", "Assumptions"), ...node.assumptions.map((a) => el("p", a))] : []));
  $("node-claim").textContent = view.claim ? `Claimed by ${view.claim.claimant_id} since ${when(view.claim.claimed_at)} (claim ${view.claim.id}).` : "";
  $("node-folder").replaceChildren();
  if (view.folder) {
    const button = el("button", "Open in prism-local", { type: "button", class: "small" });
    button.onclick = () => openInPrism(node.id);
    $("node-folder").append(el("span", "Proof folder", { class: "hint" }), el("code", view.folder), button);
  }
  const pdfs = [];
  if (view.pdfs.snapshot) pdfs.push(el("a", "PDF archived with this snapshot", { href: `/api/node/${encodeURIComponent(node.id)}/pdf/snapshot`, target: "_blank", rel: "noopener" }));
  if (view.pdfs.build) pdfs.push(el("a", "prism-local's current build (of the working file, which may be newer than the snapshot)", { href: `/api/node/${encodeURIComponent(node.id)}/pdf/build`, target: "_blank", rel: "noopener" }));
  $("node-pdfs").replaceChildren(...pdfs.flatMap((link, i) => (i ? [" · ", link] : [link])));
  const deps = $("node-deps").querySelector("tbody");
  deps.replaceChildren(...view.dependencies.map((d) => {
    const lags = d.pin && d.accepted_version !== null && d.pin.pinned_version !== d.accepted_version;
    const current = d.current === null ? null
      : d.current ? el("span", d.remedy ? "yes — a Lightweight re-review will do" : "yes", { class: `badge ${d.remedy ? "tone-review" : "tone-accepted"}` })
        : el("span", "NO — the interface changed: this node needs a new Candidate proof", { class: "badge tone-rejected" });
    return row([
      el("a", d.node_id, { href: nodeHref(d.node_id) }), d.pin ? d.pin.pinned_version : null,
      lags ? el("span", `${d.accepted_version} — the pin lags`, { class: "warning" }) : d.accepted_version,
      d.pin ? el("span", d.pin.pinned_fingerprint || "—", { class: "fp" }) : null,
      current,
    ]);
  }));
  if (!view.dependencies.length) deps.append(emptyRow("No dependencies.", 5));
  listOr($("node-challenges"), view.challenges.map((c) => {
    const li = el("li");
    li.append(el("span", c.status, { class: `badge ${c.status === "open" ? "tone-warn" : ""}` }), ` “${c.rationale}” — opened by ${c.opened_by}`);
    if (c.status !== "open") li.append(el("div", `${c.resolved_by}: ${c.resolution_rationale || "no rationale"}`, { class: "hint" }));
    li.append(el("div", c.id, { class: "decision-on" }));
    return li;
  }), "No challenges.");
  const proof = view.candidate_proof;
  $("node-proof-meta").replaceChildren();
  if (proof) {
    $("node-proof-meta").append(el("span", `snapshot v${proof.version}`, { class: "badge" }), el("span", proof.id, { class: "decision-on" }), sha(proof.sha256));
    $("node-proof-exact").textContent = proof.text;
  } else {
    $("node-proof-meta").append(el("span", "No snapshot has been requested for review yet."));
    $("node-proof-exact").textContent = "";
  }
  listOr($("node-evidence"), view.evidence_checks.map((c) => {
    const li = el("li");
    li.append(el("span", c.outcome, { class: "badge" }), ` ${c.notes || "no notes"} `, el("span", `run by ${c.run_by} · ${c.id}`, { class: "hint" }));
    return li;
  }), "No evidence checks on this snapshot.");
  const decisions = $("node-decisions");
  decisions.replaceChildren(...view.decisions.map((d) => decisionCard(d, proof)));
  if (!view.decisions.length) decisions.append(el("div", "No decision to make on this node right now.", { class: "empty" }));
  const historyTone = (decision) => (/accept|approved|reviewed|trusted|reaffirmed|promote/.test(decision) ? "accepted"
    : /reject|no-longer|unusable/.test(decision) ? "rejected" : /revision/.test(decision) ? "review" : "");
  listOr($("node-history"), view.history.filter((r) => r.kind).map((r) => {
    const tone = historyTone(r.decision);
    const li = el("li", null, { class: tone ? `tone-${tone}` : "" });
    li.append(el("span", when(r.updated_at), { class: "when", title: r.updated_at }), el("strong", `${r.kind} · ${r.decision}`), ` by ${r.reviewer_id}`);
    if (r.rationale) li.append(el("div", r.rationale, { class: "hint" }));
    return li;
  }), "No decisions recorded yet.");
}

async function route() {
  const match = location.hash.match(/^#\/node\/(.+)$/);
  $("home").hidden = !!match;
  $("node-page").hidden = !match;
  if (match) {
    try { await showNode(decodeURIComponent(match[1])); } catch (error) { showError(error); }
  } else {
    document.title = "Proof map";
  }
}

async function refresh() {
  state = await api("/api/state");
  mapData = await api("/api/map");
  $("project").textContent = state.project_id;
  $("project").title = state.origin;
  $("reviewer").replaceChildren("Recording as ", el("strong", state.reviewer));
  showHome();
  showMap();
  await route();
}

function typing(event) {
  const target = event.target;
  return target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement || (target && target.isContentEditable);
}

document.addEventListener("DOMContentLoaded", () => {
  $("decide-batch").addEventListener("click", async () => {
    const decisions = pendingCards()
      .filter((card) => card.querySelector(".pick").checked)
      .map((card) => ({
        kind: card.dataset.kind, target_id: card.dataset.target, decision: card.querySelector(".choice").value,
        rationale: card.querySelector(".rationale").value,
        // the snapshot shown in this card: the server refuses the decision if it changed since
        ...(card.dataset.viewed ? { viewed_candidate_proof_sha256: card.dataset.viewed } : {}),
      }));
    if (!decisions.length) return say("Tick at least one decision.", "error");
    try { await decide(decisions); } catch (error) { showError(error); }
  });
  $("select-all").addEventListener("change", (event) => {
    for (const card of pendingCards()) {
      const box = card.querySelector(".pick");
      box.checked = event.target.checked;
      box.dispatchEvent(new Event("change"));
    }
  });
  $("view-dag").addEventListener("click", () => { mapView = "dag"; showMap(); });
  $("view-tree").addEventListener("click", () => { mapView = "tree"; showMap(); });
  $("tree-root").addEventListener("change", showMap);
  $("map-filter").addEventListener("input", () => mapData && showMap());
  $("map-filter").addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.target.value = ""; showMap(); }
    if (event.key === "Enter" && mapData) {
      const matches = mapMatcher();
      const first = matches && mapData.nodes.find(matches);
      if (first) location.hash = nodeHref(first.id);
    }
  });
  $("frontier-only").addEventListener("change", () => mapData && showMap());
  $("zoom-in").addEventListener("click", () => { mapScale = Math.min(2, mapScale * 1.2); applyScale(); });
  $("zoom-out").addEventListener("click", () => { mapScale = Math.max(0.25, mapScale / 1.2); applyScale(); });
  $("zoom-fit").addEventListener("click", () => { mapScale = mapScale === fitScale() ? 1 : fitScale(); applyScale(); });
  $("refresh").addEventListener("click", () => refresh().then(() => say("Up to date.", "ok"), showError));
  document.addEventListener("keydown", (event) => {
    if (typing(event) || event.metaKey || event.ctrlKey || event.altKey || $("confirm").open) return;
    if (event.key === "/") { event.preventDefault(); if (location.hash.startsWith("#/node/")) location.hash = "#/"; $("map-filter").focus(); }
    if (event.key === "r") refresh().catch(showError);
    if (event.key === "Escape" && location.hash.startsWith("#/node/")) location.hash = "#/";
  });
  // "#/..." is a page; any other hash is a section of the home page, left to the browser to scroll to
  window.addEventListener("hashchange", () => route().then(() => { if (location.hash.startsWith("#/")) window.scrollTo(0, 0); }));
  $("stat-frontier-link").addEventListener("click", () => { $("frontier-only").checked = true; if (mapData) showMap(); });
  refresh().catch(showError);
});
