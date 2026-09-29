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
  const toast = el("div", null, { class: `toast ${kind || ""}`, role: kind === "error" ? "alert" : "status" });
  const close = el("button", "×", { type: "button", "aria-label": "Dismiss" });
  close.onclick = () => toast.remove();
  toast.append(el("span", text), close);
  $("toasts").append(toast);
  while ($("toasts").children.length > 3) $("toasts").firstChild.remove();
  if (kind !== "error") setTimeout(() => toast.remove(), 6000);
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

// One status per node, in words: the thing a reader needs to know first (ADR-0008: the frontier
// before the axes; a warning before anything else). The full three axes are on the node's page.
function statusOf(n) {
  if (n.integrity_state === "challenged") return { text: "challenged", tone: "warn" };
  if (n.integrity_state === "potentially-stale") return { text: "may be stale", tone: "warn" };
  if (n.acceptance_state === "unverifiable") return { text: "unverifiable", tone: "warn" };
  if (["rejected", "no-longer-callable"].includes(n.acceptance_state)) return { text: n.acceptance_state.replace(/-/g, " "), tone: "rejected" };
  if (n.workflow_state === "review-needed") return { text: "awaiting review", tone: "review" };
  if (["accepted", "reviewed"].includes(n.acceptance_state)) return { text: n.acceptance_state, tone: "accepted" };
  if (n.frontier) return { text: "ready to claim", tone: "frontier" };
  if (n.assignee) return { text: `claimed by ${n.assignee}`, tone: "" };
  return { text: n.workflow_state, tone: "" };
}

function statusChip(n) {
  const s = statusOf(n);
  return el("span", s.text, { class: `status ${s.tone}` });
}

// Show exactly what will be recorded, then record it.
function confirmDecisions(decisions) {
  return new Promise((resolve, reject) => {
    $("confirm-reviewer").textContent = state ? state.reviewer : "this process's git identity";
    $("confirm-decisions").replaceChildren(...decisions.map((d) => el("li",
      `${labelOf(d)} — ${d.target_id}${d.dependency_id ? ` (${d.kind === "dependent_migration" ? "onto" : "dependency"} ${d.dependency_id})` : ""}` +
      `${d.viewed_candidate_proof_sha256 ? ` · snapshot SHA-256 ${d.viewed_candidate_proof_sha256}` : ""} · rationale: ${d.rationale || "none"}`)));
    for (const id of ["home", "node-page"]) $(id).hidden = true;
    $("confirm").hidden = false;
    const done = () => { $("confirm").hidden = true; route(); };
    $("confirm-cancel").onclick = () => { done(); reject(new Error("cancelled")); };
    $("confirm-record").onclick = () => { done(); resolve(); };
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

// -- pages -------------------------------------------------------------------------
let state = null;

function showWarnings(list, into) {
  into.replaceChildren(...list.map((w) => { const li = el("li", null, { class: "warning" }); li.append(el("code", w.code), " ", w.message); return li; }));
  if (!list.length) into.append(el("li", "None."));
}

// the home page's warnings, each linked to the page of the node it is about
function warningItems(list) {
  return list.map((w) => {
    const li = el("li");
    li.append(el("span", w.code, { class: "warn-code" }), w.message);
    const nodeId = w.details && (w.details.node_id || w.details.target_node_id);
    if (nodeId) {
      const n = (mapData && mapData.nodes.find((m) => m.id === nodeId)) || { id: nodeId };
      li.append(" ", el("a", nodeId, { href: pageOf(n) }));
    }
    return li;
  });
}

function pendingItem(item) {
  const card = el("div", null, { class: "pending" });
  card.dataset.kind = item.kind; card.dataset.target = item.node_id;
  if (item.candidate_proof && item.candidate_proof.sha256) card.dataset.viewed = item.candidate_proof.sha256;
  card.dataset.bindings = JSON.stringify(item.bindings || {});
  const box = el("input", null, { type: "checkbox", class: "pick", "aria-label": `Decide on ${item.node_id}` });
  const body = el("div");
  const what = el("div", null, { class: "what" });
  // a local node is reviewed in its studio (#71); an imported result on its own page
  const href = item.kind === "reference_review" ? `#/node/${encodeURIComponent(item.node_id)}` : `/studio/${encodeURIComponent(item.node_id)}/#review`;
  what.append(el("a", item.node_id, { href }), item.statement);
  body.append(what);
  const controls = el("div", null, { class: "controls" });
  const choice = el("select", null, { class: "choice", "aria-label": `Outcome for ${item.node_id}` });
  for (const decision of item.decisions) choice.append(el("option", labelOf({ kind: item.kind, decision }), { value: decision }));
  const rationale = el("input", null, { class: "rationale", placeholder: "Rationale", "aria-label": `Rationale for ${item.node_id}` });
  controls.append(choice, rationale);
  body.append(controls);
  if (item.candidate_proof && item.candidate_proof.id) {
    // exactly the text the decision is about, one click away
    const details = el("details");
    details.append(el("summary", `Snapshot v${item.candidate_proof.version} · SHA-256 ${item.candidate_proof.sha256}`), el("pre", item.candidate_proof.text));
    body.append(details);
  }
  card.append(box, body);
  box.addEventListener("change", updateSelection);
  // choosing an outcome or writing a rationale means this one is being decided
  choice.addEventListener("change", () => { box.checked = true; updateSelection(); });
  rationale.addEventListener("input", () => { if (rationale.value) { box.checked = true; updateSelection(); } });
  return card;
}

function pendingCards() { return [...$("pending").querySelectorAll(".pending")]; }

// the batch button records only what is ticked: with nothing ticked there is nothing to press
function updateSelection() {
  const picked = pendingCards().filter((card) => card.querySelector(".pick").checked).length;
  $("selected-count").textContent = picked ? `${picked} selected` : "Tick the ones to record";
  $("decide-batch").disabled = picked === 0;
}

// the decisions the ticked cards will record
function pickedDecisions() {
  return pendingCards()
    .filter((card) => card.querySelector(".pick").checked)
    .map((card) => {
      const decision = card.querySelector(".choice").value;
      return {
        kind: card.dataset.kind, target_id: card.dataset.target, decision,
        rationale: card.querySelector(".rationale").value,
        // the snapshot shown on this card: the server refuses the decision if it changed since
        ...(card.dataset.viewed ? { viewed_candidate_proof_sha256: card.dataset.viewed } : {}),
        // everything else the card showed it is made on (dependencies, interface, …): refused too if it changed
        binding: JSON.parse(card.dataset.bindings || "{}")[decision] ?? null,
      };
    });
}

// a section shows only when it has something in it
function showHome() {
  $("review").hidden = !state.pending.length;
  $("pending").replaceChildren(...state.pending.map(pendingItem));
  $("pending-count").textContent = state.pending.length ? `${state.pending.length} pending` : "";
  updateSelection();
  $("warnings").replaceChildren(...warningItems(state.warnings));
  $("warnings-block").hidden = !state.warnings.length;
}

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
  "dependent_migration:superseded": "Move every dependent onto this corrected source (Accepted ones need re-Accepting)",
};

const labelOf = (d) => DECISION_LABELS[`${d.kind}:${d.decision}`] || `${d.kind}: ${d.decision}`;

function showError(error) { if (error.message !== "cancelled") say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }

function decisionRow(decision, proof) {
  const label = labelOf(decision);
  const on = decision.kind === "dependent_migration" ? `onto ${decision.dependency_id}`
    : decision.dependency_id ? `dependency ${decision.dependency_id}` : decision.target_id;
  const rationale = el("input", null, { placeholder: "why" });
  const button = el("button", "Record");
  button.onclick = async () => {
    const binds = ["acceptance", "promote", "dependency_revalidation"].includes(decision.kind) && proof;
    try { await decide([{ ...decision, rationale: rationale.value, ...(binds ? { viewed_candidate_proof_sha256: proof.sha256 } : {}) }]); }
    catch (error) { showError(error); }
  };
  return row([label, on, rationale, button]);
}


// -- the map (ADR-0008): the DAG is canonical, the tree a rooted explanation of it ----------
let mapData = null;
let mapView = "dag";
const SVG_NS = "http://www.w3.org/2000/svg";
const BOX = { w: 204, h: 52, gapX: 24, gapY: 56, pad: 24 };

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

// which warning a node carries: challenged, potentially stale, or a decision that no longer applies
function warningOf(n) {
  if (n.integrity_state === "challenged") return "challenged";
  if (n.integrity_state === "potentially-stale") return "stale";
  if (n.acceptance_state === "unverifiable") return "unverifiable";
  return "";
}

function short(text, length) { return text.length > length ? text.slice(0, length - 1) + "…" : text; }

// the find box: which nodes to pick out, by id, label or statement (null when nothing is being looked for)
function mapMatcher() {
  const query = $("map-filter").value.trim().toLowerCase();
  if (!query) return null;
  return (n) => [n.id, n.kind, n.display_label || "", n.statement, n.assignee || ""].some((field) => field.toLowerCase().includes(query));
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

function drawDag(nodes) {
  const box = $("dag-svg");
  box.replaceChildren();
  box.classList.remove("tracing", "filtering");
  if (!nodes.length) {
    box.setAttribute("width", 420); box.setAttribute("height", 60); box.setAttribute("viewBox", "0 0 420 60");
    box.append(Object.assign(svg("text", { x: 18, y: 35, class: "empty" }), { textContent: "No nodes yet: create the first one below." }));
    return;
  }
  const rows = layers(nodes);
  const widest = Math.max(...rows.map((row) => row.length));
  const width = BOX.pad * 2 + widest * BOX.w + (widest - 1) * BOX.gapX;
  const height = BOX.pad * 2 + rows.length * BOX.h + (rows.length - 1) * BOX.gapY;
  box.setAttribute("width", width); box.setAttribute("height", height);
  box.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const at = new Map();
  rows.forEach((row, r) => row.forEach((id, i) => {
    const rowWidth = row.length * BOX.w + (row.length - 1) * BOX.gapX;
    at.set(id, { x: (width - rowWidth) / 2 + i * (BOX.w + BOX.gapX) + BOX.w / 2, y: BOX.pad + r * (BOX.h + BOX.gapY) + BOX.h / 2 });
  }));
  const defs = svg("defs");
  const marker = svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" });
  marker.append(svg("path", { class: "arrowhead", d: "M0,0 L10,5 L0,10 z" }));
  defs.append(marker);
  box.append(defs);
  const edges = [];
  for (const n of nodes) for (const d of n.dependencies) {
    const from = at.get(n.id), to = at.get(d);
    if (!from || !to) continue;
    const y1 = from.y + BOX.h / 2, y2 = to.y - BOX.h / 2;
    const path = svg("path", { class: "edge", "marker-end": "url(#arrow)", d: `M${from.x},${y1} C${from.x},${y1 + 28} ${to.x},${y2 - 28} ${to.x},${y2}` });
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
    const status = statusOf(n);
    const classes = ["node", n.frontier ? "frontier" : "", warningOf(n), matches && matches(n) ? "match" : ""].filter(Boolean).join(" ");
    const g = svg("g", { class: classes, tabindex: 0, role: "link", "aria-label": `${n.kind} ${n.id}: ${status.text}` });
    g.append(svg("rect", { class: "box", x: x - BOX.w / 2, y: y - BOX.h / 2, width: BOX.w, height: BOX.h, rx: 1 }));
    g.append(svg("rect", { class: `bar ${toneOf(n)}`, x: x - BOX.w / 2, y: y - BOX.h / 2, width: 3, height: BOX.h }));
    const label = svg("text", { x: x - BOX.w / 2 + 12, y: y - 3 });
    label.textContent = short(n.display_label || n.statement, 27);
    // the id on the left, the status right-aligned; a claim shows its assignee in the tooltip
    const id = svg("text", { class: "sub", x: x - BOX.w / 2 + 12, y: y + 15 });
    id.textContent = short(n.id, 13);
    const sub = svg("text", { class: `sub ${status.tone}`, x: x + BOX.w / 2 - 10, y: y + 15, "text-anchor": "end" });
    sub.textContent = n.assignee && !status.tone ? "claimed" : short(status.text, 15);
    const title = svg("title");
    title.textContent = `${n.id} (${n.kind})\n${n.statement}\n\n${n.workflow_state}${n.blocked_reason ? ` (${n.blocked_reason})` : ""} · ${n.acceptance_state} · ${n.integrity_state}${n.assignee ? ` · claimed by ${n.assignee}` : ""}`;
    g.append(label, id, sub, title);
    const open = () => { location.href = pageOf(n); };
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
  select.replaceChildren(...roots.map((n) => el("option", `rooted at ${n.id}`, { value: n.id })));
  if (chosen) select.value = chosen;
  const matches = mapMatcher();
  const item = (id, ancestors) => {
    const n = byId.get(id);
    const li = el("li");
    if (!n) { li.append(el("span", `${id} (missing)`, { class: "bad" })); return li; }
    if (matches && !matches(n)) li.classList.add("dim");
    const line = el("div", null, { class: "line" });
    const shared = (parents.get(id) || 0) > 1 ? ` · shared by ${parents.get(id)}` : "";
    line.append(el("a", short(n.display_label || n.statement, 70), { href: pageOf(n), title: n.statement }), el("span", `${n.id}${shared}`, { class: "muted small" }), statusChip(n));
    li.append(line);
    if (ancestors.has(id)) { line.append(el("span", "(cycle)", { class: "muted small" })); return li; }
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
  else tree.append(el("li", "No nodes yet: create the first one below.", { class: "muted" }));
  $("map-tree").replaceChildren(tree);
}

function showMap() {
  const nodes = mapData.nodes;
  const frontier = nodes.filter((n) => n.frontier).length;
  const matches = mapMatcher();
  const found = matches ? nodes.filter(matches).length : null;
  $("map-caption").textContent = found === null
    ? `${nodes.length} nodes · ${frontier} ready to claim`
    : `${found} of ${nodes.length} match${found ? " · Enter opens the first" : ""}`;
  $("map-dag").hidden = mapView !== "dag";
  $("map-tree").hidden = mapView !== "tree";
  $("tree-root").hidden = mapView !== "tree";
  $("view-dag").setAttribute("aria-pressed", String(mapView === "dag"));
  $("view-tree").setAttribute("aria-pressed", String(mapView === "tree"));
  if (mapView === "dag") drawDag(nodes); else drawTree(nodes);
}

// Where a node opens (ADR-0011): a theorem, lemma or claim in its studio, an imported result on its own page.
function pageOf(n) {
  return n.kind === "imported_result" ? `#/node/${encodeURIComponent(n.id)}` : `/studio/${encodeURIComponent(n.id)}/`;
}

async function createNode(event) {
  event.preventDefault();
  const kind = $("new-kind").value;
  const body = {
    node_id: $("new-id").value.trim(), kind, statement: $("new-statement").value,
    assumptions: $("new-assumptions").value.split("\n").map((a) => a.trim()).filter(Boolean),
    // an imported result is established elsewhere: it takes no dependencies, whatever the (disabled) list still holds
    dependencies: kind === "imported_result" ? [] : [...$("new-dependencies").selectedOptions].map((o) => o.value),
  };
  if (kind === "imported_result") Object.assign(body, { source_locator: $("new-locator").value, source_version: $("new-version").value, trust_level: $("new-trust").value });
  try {
    const node = await api("/api/nodes", body);
    say(`Created ${node.kind} ${node.id}.`, "ok");
    $("new-node").reset();
    showNewNodeKind();
    location.href = node.page;
    if (node.page.startsWith("/#")) await refresh();
  } catch (error) { showError(error); }
}

function showNewNodeKind() {
  const imported = $("new-kind").value === "imported_result";
  $("new-source").hidden = !imported;
  $("new-dependencies").disabled = imported;  // an imported result is established elsewhere: no dependencies
  if (imported) for (const option of $("new-dependencies").options) option.selected = false;
}

async function showNode(nodeId) {
  const view = await api(`/api/node/${encodeURIComponent(nodeId)}`);
  const node = view.node;
  document.title = `${node.id} · Proof map`;
  $("node-title").textContent = `${node.id} — ${node.kind}`;
  $("node-axes").textContent = `workflow: ${view.workflow_state} · acceptance: ${view.acceptance_state} · integrity: ${view.integrity_state}`;
  const nodeWarnings = el("ul");
  showWarnings(view.warnings, nodeWarnings);
  $("node-warnings").replaceChildren(el("h3", "Warnings for this node"), nodeWarnings);
  $("node-statement").textContent = node.statement;
  $("node-assumptions").replaceChildren(...(node.assumptions.length ? [el("h3", "Assumptions"), ...node.assumptions.map((a) => el("p", a))] : []));
  $("node-claim").textContent = view.claim ? `Claimed by ${view.claim.claimant_id} since ${view.claim.claimed_at} (claim ${view.claim.id}).` : "";
  $("node-folder").replaceChildren();
  if (view.studio) $("node-folder").append(el("a", "Open the node's studio", { href: view.studio }), " · proof folder ", el("code", view.folder));
  $("node-source").replaceChildren(...(view.source ? [el("h3", "Source"), el("p", `${view.source.locator} · ${view.source.version}${view.source.trust_level ? ` · ${view.source.trust_level}` : ""}`)] : []));
  $("node-dependents").textContent = view.dependents.length ? `Used by: ${view.dependents.join(", ")}` : "Nothing depends on this node yet.";
  const pdfs = [];
  if (view.pdfs.snapshot) pdfs.push(el("a", "PDF archived with this snapshot", { href: `/api/node/${encodeURIComponent(node.id)}/pdf/snapshot`, target: "_blank", rel: "noopener" }));
  if (view.pdfs.build) pdfs.push(el("a", "the studio's current build (of the working file, which may be newer than the snapshot)", { href: `/api/node/${encodeURIComponent(node.id)}/pdf/build`, target: "_blank", rel: "noopener" }));
  $("node-pdfs").replaceChildren(...pdfs.flatMap((link, i) => (i ? [" · ", link] : [link])));
  $("node-deps").querySelector("tbody").replaceChildren(...view.dependencies.map((d) => {
    const lags = d.pin && d.accepted_version !== null && d.pin.pinned_version !== d.accepted_version;
    return row([
      d.node_id, d.pin ? d.pin.pinned_version : null, lags ? `${d.accepted_version} — the pin lags` : d.accepted_version,
      d.pin ? el("span", d.pin.pinned_fingerprint || "—", { class: "fp" }) : null,
      d.current === null ? null : d.current ? (d.remedy ? "yes — a Lightweight re-review will do" : "yes") : "NO — the interface changed: this node needs a new Candidate proof",
    ]);
  }));
  $("node-challenges").replaceChildren(...view.challenges.map((c) => el("li",
    `${c.id} · ${c.status}: "${c.rationale}" (opened by ${c.opened_by})` + (c.status === "open" ? "" : ` — ${c.resolved_by}: ${c.resolution_rationale || "no rationale"}`))));
  const proof = view.candidate_proof;
  if (proof) {
    $("node-proof-meta").textContent = `snapshot v${proof.version} · ${proof.id} · SHA-256 ${proof.sha256}`;
    // every file the snapshot froze (#71), each under its path from the node folder
    const files = Object.entries(proof.files || { "proof.tex": proof.text });
    $("node-proof-exact").textContent = files.length === 1 ? files[0][1] : files.map(([rel, text]) => `%%%%% ${rel}\n${text}`).join("\n");
  } else {
    $("node-proof-meta").textContent = "No snapshot has been requested for review yet.";
    $("node-proof-exact").textContent = "";
  }
  $("node-evidence").replaceChildren(...view.evidence_checks.map((c) => el("li", `${c.id}: ${c.outcome} — ${c.notes || "no notes"} (run by ${c.run_by})`)));
  const decisions = $("node-decisions").querySelector("tbody");
  decisions.replaceChildren(...view.decisions.map((d) => decisionRow(d, proof)));
  if (!view.decisions.length) decisions.append(row(["No decision to make on this node right now.", "", "", ""]));
  $("node-history").replaceChildren(...view.history.filter((r) => r.kind).map((r) => el("li", `${r.updated_at} · ${r.kind} · ${r.decision} · ${r.reviewer_id}${r.rationale ? ` — ${r.rationale}` : ""}`)));
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
  $("new-dependencies").replaceChildren(...mapData.nodes.map((n) => el("option", `${n.id} (${n.kind})`, { value: n.id })));
  $("reviewer").textContent = `Decisions are committed to git with their snapshot, as ${state.reviewer}.`;
  showHome();
  showMap();
  await route();
}

document.addEventListener("DOMContentLoaded", () => {
  $("decide-batch").addEventListener("click", async () => {
    const decisions = pickedDecisions();
    if (!decisions.length) return say("Tick at least one decision.", "error");
    try { await decide(decisions); } catch (error) { showError(error); }
  });
  $("view-dag").addEventListener("click", () => { mapView = "dag"; showMap(); });
  $("view-tree").addEventListener("click", () => { mapView = "tree"; showMap(); });
  $("tree-root").addEventListener("change", showMap);
  $("map-filter").addEventListener("input", () => mapData && showMap());
  $("map-filter").addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.target.value = ""; if (mapData) showMap(); }
    if (event.key === "Enter" && mapData) {
      const matches = mapMatcher();
      const first = matches && mapData.nodes.find(matches);
      if (first) location.href = pageOf(first);
    }
  });
  $("new-node").addEventListener("submit", createNode);
  $("new-kind").addEventListener("change", showNewNodeKind);
  window.addEventListener("hashchange", route);
  refresh().catch(showError);
});
