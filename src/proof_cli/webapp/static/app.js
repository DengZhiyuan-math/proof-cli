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

function say(text, kind) {
  const box = $("message");
  box.textContent = text;
  box.className = kind || "";
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

// Show exactly what will be recorded, then record it.
function confirmDecisions(decisions) {
  return new Promise((resolve, reject) => {
    $("confirm-decisions").replaceChildren(...decisions.map((d) => el("li",
      `${DECISION_LABELS[`${d.kind}:${d.decision}`] || `${d.kind}: ${d.decision}`} — ${d.target_id}${d.dependency_id ? ` (${d.kind === "dependent_migration" ? "onto" : "dependency"} ${d.dependency_id})` : ""}` +
      `${d.viewed_candidate_proof_sha256 ? ` · snapshot SHA-256 ${d.viewed_candidate_proof_sha256}` : ""} · rationale: ${d.rationale || "none"}`)));
    $("confirm").hidden = false;  // a sheet over the page, which stays where it was
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

function showHome() {
  const body = $("pending").querySelector("tbody");
  body.replaceChildren(...state.pending.map((item) => {
    const box = el("input", null, { type: "checkbox" });
    const choice = el("select");
    for (const decision of item.decisions) choice.append(el("option", decision));
    const rationale = el("input", null, { placeholder: "why" });
    // a local node is reviewed in its studio (#71); an imported result on its own page
    const link = el("a", item.node_id, { href: item.kind === "reference_review" ? `#/node/${encodeURIComponent(item.node_id)}` : `/studio/${encodeURIComponent(item.node_id)}/#review` });
    const statement = el("div", item.statement);
    if (item.candidate_proof && item.candidate_proof.id) {
      // shown in full: recording the decision is about exactly this text
      statement.append(el("p", `snapshot v${item.candidate_proof.version} · SHA-256 ${item.candidate_proof.sha256}`, { class: "hint" }), el("pre", item.candidate_proof.text));
    }
    const tr = row([box, link, statement, choice, rationale]);
    tr.dataset.kind = item.kind; tr.dataset.target = item.node_id;
    if (item.candidate_proof && item.candidate_proof.sha256) tr.dataset.viewed = item.candidate_proof.sha256;
    tr.dataset.bindings = JSON.stringify(item.bindings || {});
    return tr;
  }));
  if (!state.pending.length) body.append(row(["", "Nothing is awaiting review.", "", "", ""]));
  showWarnings(state.warnings, $("warnings"));
  const pending = String(state.pending.length);
  $("stat-review").textContent = pending;
  $("pending-count").textContent = pending;
  $("rail-review").textContent = state.pending.length ? pending : "";
  $("rail-review").className = state.pending.length ? "n hot" : "n";
  $("rail-warnings").textContent = state.warnings.length ? String(state.warnings.length) : "";
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

function showError(error) { if (error.message !== "cancelled") say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }

function decisionRow(decision, proof) {
  const label = DECISION_LABELS[`${decision.kind}:${decision.decision}`] || `${decision.kind}: ${decision.decision}`;
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
const BOX = { w: 208, h: 92, gapX: 44, gapY: 104, pad: 24, radius: 14 };

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

// A node card's one state line, bottom right: what needs the researcher first (integrity, an
// undecidable decision), then the frontier, a claim, a review request, a rejected route, blocked.
function tagOf(n) {
  if (n.integrity_state === "challenged") return ["challenged", "warn"];
  if (n.integrity_state === "potentially-stale") return ["stale", "warn"];
  if (n.acceptance_state === "unverifiable") return ["unverifiable", "warn"];
  if (n.frontier) return ["frontier", "accent"];
  if (n.assignee) return [`claimed · ${n.assignee}`, ""];
  if (n.workflow_state === "review-needed") return ["review needed", "warn"];
  if (n.workflow_state === "revision-requested") return ["revision requested", "warn"];
  if (["rejected", "no-longer-callable"].includes(n.acceptance_state)) return ["rejected", "crit"];
  if (n.workflow_state === "blocked") return ["blocked", "muted"];
  if (["accepted", "reviewed"].includes(n.acceptance_state)) return [n.acceptance_state, "ok"];
  return ["open", "muted"];
}

const KIND_LABEL = { theorem: "Theorem", lemma: "Lemma", claim: "Claim", imported_result: "Imported result" };
const capitalised = (text) => text.charAt(0).toUpperCase() + text.slice(1);

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

// -- the map is a freeform canvas: drag to pan, pinch or ⌘/ctrl + scroll to zoom, F to fit ----
const view = { k: 1, tx: 0, ty: 0, content: null, fitted: false };

function applyView() {
  const g = $("dag-view");
  if (g) g.setAttribute("transform", `translate(${view.tx},${view.ty}) scale(${view.k})`);
  const level = $("zoom-level");
  if (level) level.textContent = `${Math.round(view.k * 100)}%`;
  const canvas = $("map-dag");
  if (canvas) { canvas.style.backgroundPosition = `${view.tx}px ${view.ty}px`; canvas.style.backgroundSize = `${24 * view.k}px ${24 * view.k}px`; }
}

// the whole map in the stage, centred, never larger than life
function fitView() {
  const canvas = $("map-dag");
  if (!view.content || !canvas || !canvas.clientWidth) return;
  const pad = 40, top = 24, bottom = 80;  // the legend and zoom controls float along the bottom
  view.k = Math.max(0.15, Math.min(1.1, (canvas.clientWidth - pad * 2) / view.content.width, (canvas.clientHeight - top - bottom) / view.content.height));
  view.tx = (canvas.clientWidth - view.content.width * view.k) / 2;
  view.ty = top + (canvas.clientHeight - top - bottom - view.content.height * view.k) / 2;
  view.fitted = true;
  applyView();
}

function zoomAt(factor, cx, cy) {
  const k = Math.min(4, Math.max(0.15, view.k * factor));
  const r = k / view.k;
  view.tx = cx - (cx - view.tx) * r;
  view.ty = cy - (cy - view.ty) * r;
  view.k = k;
  applyView();
}

function wireCanvas() {
  const canvas = $("map-dag");
  let drag = null, suppressClick = false;
  const move = (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) > 3) { drag.moved = true; canvas.classList.add("dragging"); }
    if (drag.moved) { view.tx = drag.tx + dx; view.ty = drag.ty + dy; applyView(); }
  };
  const end = () => {
    if (drag && drag.moved) suppressClick = true;
    drag = null;
    canvas.classList.remove("dragging");
    window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); window.removeEventListener("pointercancel", end);
  };
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    drag = { x: event.clientX, y: event.clientY, tx: view.tx, ty: view.ty, moved: false };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
  });
  // a drag ends on a node without opening it
  canvas.addEventListener("click", (event) => { if (suppressClick) { event.stopPropagation(); event.preventDefault(); suppressClick = false; } }, true);
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    if (event.ctrlKey || event.metaKey) zoomAt(Math.exp(-event.deltaY * 0.01), event.clientX - rect.left, event.clientY - rect.top);
    else { view.tx -= event.deltaX; view.ty -= event.deltaY; applyView(); }
  }, { passive: false });
  canvas.addEventListener("dblclick", (event) => {
    if (event.target.closest(".node")) return;
    const rect = canvas.getBoundingClientRect();
    zoomAt(1.5, event.clientX - rect.left, event.clientY - rect.top);
  });
  $("zoom-in").addEventListener("click", () => zoomAt(1.25, canvas.clientWidth / 2, canvas.clientHeight / 2));
  $("zoom-out").addEventListener("click", () => zoomAt(0.8, canvas.clientWidth / 2, canvas.clientHeight / 2));
  $("zoom-fit").addEventListener("click", fitView);
  $("zoom-tidy").addEventListener("click", () => { positions.clear(); view.fitted = false; if (mapData) drawDag(mapData.nodes); });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "f" || event.metaKey || event.ctrlKey || event.altKey) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    if ($("home").hidden || mapView !== "dag") return;
    fitView();
  });
  window.addEventListener("resize", () => { if (view.fitted) fitView(); });
}

// Where the researcher dragged each node, kept in this browser only; "Tidy" forgets it.
const positions = {
  key() { return `proof.map.positions:${state ? state.project_id : ""}`; },
  load() { try { return JSON.parse(localStorage.getItem(this.key()) || "{}"); } catch { return {}; } },
  save(map) { try { localStorage.setItem(this.key(), JSON.stringify(map)); } catch { /* a private window: positions just don't persist */ } },
  clear() { try { localStorage.removeItem(this.key()); } catch { /* ignore */ } },
};

function drawDag(nodes) {
  const box = $("dag-svg");
  box.replaceChildren();
  if (!nodes.length) {
    view.content = null;
    box.append(Object.assign(svg("text", { x: 16, y: 64, class: "empty" }), { textContent: "No nodes yet: create the first one with `proof node create`." }));
    return;
  }
  const rows = layers(nodes);
  const widest = Math.max(...rows.map((row) => row.length));
  const width = BOX.pad * 2 + widest * BOX.w + (widest - 1) * BOX.gapX;
  const height = BOX.pad * 2 + rows.length * BOX.h + (rows.length - 1) * BOX.gapY + 16;
  const same = view.content && view.content.width === width && view.content.height === height;
  view.content = { width, height };
  const scene = svg("g", { id: "dag-view" });
  const at = new Map();
  const saved = positions.load();
  rows.forEach((row, r) => row.forEach((id, i) => {
    const rowWidth = row.length * BOX.w + (row.length - 1) * BOX.gapX;
    const own = saved[id] && Number.isFinite(saved[id].x) && Number.isFinite(saved[id].y) ? saved[id] : null;
    at.set(id, own ? { x: own.x, y: own.y } : { x: (width - rowWidth) / 2 + i * (BOX.w + BOX.gapX) + BOX.w / 2, y: BOX.pad + r * (BOX.h + BOX.gapY) + BOX.h / 2 });
  }));
  const edgeD = (from, to) => { const y1 = from.y + BOX.h / 2, y2 = to.y - BOX.h / 2; return `M${from.x},${y1} C${from.x},${y1 + 50} ${to.x},${y2 - 50} ${to.x},${y2}`; };
  const edgesOf = new Map(nodes.map((n) => [n.id, []]));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const rejected = (n) => ["rejected", "no-longer-callable"].includes(n.acceptance_state);
  const defs = svg("defs");
  const marker = svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  marker.append(svg("path", { d: "M1,1.5 L9,5 L1,8.5 z", class: "arrowhead" }));
  defs.append(marker);
  box.append(defs, scene);
  for (const n of nodes) for (const d of n.dependencies) {
    const from = at.get(n.id), to = at.get(d);
    if (!from || !to) continue;
    const dim = rejected(n) || (byId.has(d) && rejected(byId.get(d)));
    const edge = svg("path", { class: dim ? "edge rejected" : "edge", "marker-end": "url(#arrow)", d: edgeD(from, to) });
    const link = { edge, from: n.id, to: d };
    edgesOf.get(n.id).push(link); edgesOf.get(d).push(link);
    scene.append(edge);
  }
  for (const n of nodes) {
    const left = -BOX.w / 2, top = -BOX.h / 2;
    const classes = ["node", `tone-${toneOf(n)}`, n.frontier ? "frontier" : "", n.assignee ? "claimed" : "", rejected(n) ? "rejected" : "", warningOf(n)].filter(Boolean).join(" ");
    const place = () => { const p = at.get(n.id); g.setAttribute("transform", `translate(${p.x},${p.y})`); };
    const g = svg("g", { class: classes, tabindex: 0, role: "link", "aria-label": `${n.kind} ${n.id}: ${n.acceptance_state}, ${n.workflow_state}, ${n.integrity_state}${n.assignee ? `, claimed by ${n.assignee}` : ""}${n.frontier ? ", on the frontier" : ""}` });
    place();
    g.append(svg("rect", { class: "box", x: left, y: top, width: BOX.w, height: BOX.h, rx: BOX.radius }));
    const kind = svg("text", { class: "kind", x: left + 14, y: top + 21 });
    kind.textContent = KIND_LABEL[n.kind] || capitalised(n.kind.replace("_", " "));
    const id = svg("text", { class: "id", x: left + BOX.w - 14, y: top + 21, "text-anchor": "end" });
    id.textContent = short(n.id, 18);
    const label = svg("text", { x: left + 14, y: top + 41 });
    label.textContent = short(n.display_label || n.statement, 22);
    const meta = svg("text", { class: "meta", x: left + 14, y: top + 58 });
    meta.textContent = n.display_label ? short(n.statement, 30) : "";
    g.append(kind, id, label, meta);
    // the node's one state, as a capsule along the bottom
    const [tagText, tone] = tagOf(n);
    const status = svg("g", { class: `status ${tone}`.trim() });
    const text = capitalised(short(tagText, 26));
    const pillWidth = Math.min(BOX.w - 28, 24 + text.length * 6.3);
    status.append(svg("rect", { class: "pill", x: left + 12, y: top + BOX.h - 26, width: pillWidth, height: 18, rx: 9 }));
    status.append(svg("circle", { class: "pill-dot", cx: left + 22, cy: top + BOX.h - 17, r: 3 }));
    const tag = svg("text", { class: "tag", x: left + 30, y: top + BOX.h - 13 });
    tag.textContent = text;
    status.append(tag);
    g.append(status);
    const title = svg("title");
    title.textContent = n.statement;
    g.append(title);
    // drag a node to move it (its edges follow); a click without a drag opens it
    let drag = null;
    const move = (event) => {
      if (!drag) return;
      const dx = (event.clientX - drag.x) / view.k, dy = (event.clientY - drag.y) / view.k;
      if (!drag.moved && Math.hypot(dx, dy) * view.k > 3) { drag.moved = true; g.classList.add("moving"); }
      if (!drag.moved) return;
      at.set(n.id, { x: drag.px + dx, y: drag.py + dy });
      place();
      for (const link of edgesOf.get(n.id)) link.edge.setAttribute("d", edgeD(at.get(link.from), at.get(link.to)));
    };
    const end = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); window.removeEventListener("pointercancel", end);
      if (drag && drag.moved) { const saved = positions.load(); saved[n.id] = at.get(n.id); positions.save(saved); setTimeout(() => g.classList.remove("moving"), 0); }
      drag = null;
    };
    g.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.stopPropagation();  // the canvas doesn't pan under a node drag
      const p = at.get(n.id);
      drag = { x: event.clientX, y: event.clientY, px: p.x, py: p.y, moved: false };
      window.addEventListener("pointermove", move); window.addEventListener("pointerup", end); window.addEventListener("pointercancel", end);
    });
    const open = () => { if (g.classList.contains("moving")) return; location.href = pageOf(n); };
    g.addEventListener("click", open);
    g.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
    scene.append(g);
  }
  // a redraw of the same map (after a decision) keeps where you were; a new shape is fitted
  if (same && view.fitted) applyView(); else fitView();
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
  const item = (id, ancestors) => {
    const n = byId.get(id);
    const li = el("li");
    if (!n) { li.append(el("span", `${id} (missing)`, { class: "warning" })); return li; }
    li.append(el("a", n.id, { href: pageOf(n) }), ` — ${short(n.display_label || n.statement, 60)}`);
    li.append(el("span", n.acceptance_state, { class: `state-chip chip ${n.acceptance_state}` }), el("span", n.workflow_state, { class: `state-chip chip ${n.workflow_state}` }));
    li.append(el("span", n.integrity_state, { class: `state-chip chip ${n.integrity_state}${n.integrity_state === "current" ? "" : " warn-chip"}` }));
    if (n.assignee) li.append(el("span", `@${n.assignee}`, { class: "state-chip chip claimed" }));
    if (n.frontier) li.append(el("span", "frontier", { class: "state-chip chip frontier" }));
    if ((parents.get(id) || 0) > 1) li.append(el("span", "shared", { class: "state-chip shared-chip", title: `used by ${parents.get(id)} nodes; see the DAG` }));
    if (ancestors.has(id)) { li.append(" (cycle: not expanded again)"); return li; }
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
  $("map-tree").replaceChildren(tree);
}

function showMap() {
  const nodes = mapData.nodes;
  const frontier = nodes.filter((n) => n.frontier).length;
  $("map-caption").textContent = `${nodes.length} ${nodes.length === 1 ? "node" : "nodes"} · ${frontier} on the frontier`;
  $("stat-frontier").textContent = String(frontier);
  $("map-dag").hidden = mapView !== "dag";
  $("map-tree").hidden = mapView !== "tree";
  $("tree-root-label").hidden = mapView !== "tree";
  $("view-dag").setAttribute("aria-pressed", String(mapView === "dag"));
  $("view-tree").setAttribute("aria-pressed", String(mapView === "tree"));
  if (mapView === "dag") drawDag(nodes); else drawTree(nodes);
}

// Where a node opens (ADR-0011): a theorem, lemma or claim in its studio, an imported result on its own page.
function pageOf(n) {
  return n.kind === "imported_result" ? `#/node/${encodeURIComponent(n.id)}` : `/studio/${encodeURIComponent(n.id)}/`;
}

async function showNode(nodeId) {
  const view = await api(`/api/node/${encodeURIComponent(nodeId)}`);
  const node = view.node;
  $("node-title").replaceChildren(node.id, el("small", node.kind.replace("_", " ")));
  const axis = (name, value) => { const cell = el("div"); cell.append(el("span", name, { class: "lbl" }), el("span", value, { class: `chip ${value}`, title: `${name}: ${value}` })); return cell; };
  $("node-axes").replaceChildren(axis("workflow", view.workflow_state), axis("acceptance", view.acceptance_state), axis("integrity", view.integrity_state));
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
  if (!match && view.content && !view.fitted) fitView();  // drawn while the map was hidden
  for (const link of document.querySelectorAll(".rail a[data-nav]")) link.classList.toggle("on", !match && (link.dataset.nav === "map" ? !location.hash.startsWith("#sec-") : location.hash === link.getAttribute("href")));
  if (match) {
    try { await showNode(decodeURIComponent(match[1])); } catch (error) { say(error.message, "error"); }
  }
}

async function refresh() {
  state = await api("/api/state");
  mapData = await api("/api/map");
  $("project").replaceChildren(el("b", state.project_id));
  $("reviewer").textContent = state.reviewer;  // decisions are recorded and committed as this identity
  $("reviewer-initial").textContent = (state.reviewer || "?").trim().charAt(0).toUpperCase() || "?";
  showHome();
  showMap();
  await route();
}

document.addEventListener("DOMContentLoaded", () => {
  $("decide-batch").addEventListener("click", async () => {
    const decisions = [...$("pending").querySelectorAll("tbody tr")]
      .filter((tr) => tr.querySelector("input[type=checkbox]")?.checked)
      .map((tr) => ({
        kind: tr.dataset.kind, target_id: tr.dataset.target, decision: tr.querySelector("select").value,
        rationale: tr.querySelectorAll("input")[1].value,
        // the snapshot shown in this row: the server refuses the decision if it changed since
        ...(tr.dataset.viewed ? { viewed_candidate_proof_sha256: tr.dataset.viewed } : {}),
        // everything else the row showed it is made on (dependencies, interface, …): refused too if it changed
        binding: JSON.parse(tr.dataset.bindings || "{}")[tr.querySelector("select").value] ?? null,
      }));
    if (!decisions.length) return say("Tick at least one decision.", "error");
    try { await decide(decisions); } catch (error) { showError(error); }
  });
  wireCanvas();
  // the sidebar hides (remembered in this browser); on a narrow window it slides over the map
  const narrow = () => matchMedia("(max-width: 760px)").matches;
  try { if (localStorage.getItem("proof.map.sidebar") === "hidden") document.body.classList.add("sidebar-hidden"); } catch { /* ignore */ }
  $("sidebar-toggle").addEventListener("click", () => {
    if (narrow()) { document.body.classList.toggle("sidebar-shown"); return; }
    const hidden = document.body.classList.toggle("sidebar-hidden");
    try { localStorage.setItem("proof.map.sidebar", hidden ? "hidden" : "shown"); } catch { /* ignore */ }
    if (view.fitted) setTimeout(fitView, 240);
  });
  $("view-dag").addEventListener("click", () => { mapView = "dag"; showMap(); });
  $("view-tree").addEventListener("click", () => { mapView = "tree"; showMap(); });
  $("tree-root").addEventListener("change", showMap);
  window.addEventListener("hashchange", route);
  refresh().catch((error) => say(error.message, "error"));
});
