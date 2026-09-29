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
const BOX = { w: 176, h: 58, gapX: 28, gapY: 74, pad: 24 };

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
  if (!nodes.length) {
    box.setAttribute("width", 400); box.setAttribute("height", 60);
    box.append(Object.assign(svg("text", { x: 16, y: 34 }), { textContent: "No nodes yet: create the first one below." }));
    return;
  }
  const rows = layers(nodes);
  const widest = Math.max(...rows.map((row) => row.length));
  const width = BOX.pad * 2 + widest * BOX.w + (widest - 1) * BOX.gapX;
  const height = BOX.pad * 2 + rows.length * BOX.h + (rows.length - 1) * BOX.gapY + 16;
  box.setAttribute("width", width); box.setAttribute("height", height);
  box.setAttribute("viewBox", `0 0 ${width} ${height}`);
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
  for (const n of nodes) for (const d of n.dependencies) {
    const from = at.get(n.id), to = at.get(d);
    if (!from || !to) continue;
    const y1 = from.y + BOX.h / 2, y2 = to.y - BOX.h / 2;
    box.append(svg("path", { class: "edge", "marker-end": "url(#arrow)", d: `M${from.x},${y1} C${from.x},${y1 + 34} ${to.x},${y2 - 34} ${to.x},${y2}` }));
  }
  for (const n of nodes) {
    const { x, y } = at.get(n.id);
    const classes = ["node", n.frontier ? "frontier" : "", warningOf(n)].filter(Boolean).join(" ");
    const g = svg("g", { class: classes, tabindex: 0, role: "link", "aria-label": `${n.kind} ${n.id}: ${n.acceptance_state}, ${n.workflow_state}, ${n.integrity_state}${n.assignee ? `, claimed by ${n.assignee}` : ""}${n.frontier ? ", on the frontier" : ""}` });
    g.append(svg("rect", { class: "box", x: x - BOX.w / 2, y: y - BOX.h / 2, width: BOX.w, height: BOX.h, rx: 8 }));
    g.append(svg("rect", { class: `bar ${toneOf(n)}`, x: x - BOX.w / 2, y: y - BOX.h / 2, width: 5, height: BOX.h, rx: 2 }));
    const kind = svg("text", { class: "kind", x: x - BOX.w / 2 + 12, y: y - BOX.h / 2 + 15 });
    kind.textContent = `${n.kind} · ${n.id}`;
    const label = svg("text", { x: x - BOX.w / 2 + 12, y: y + 3 });
    label.textContent = short(n.display_label || n.statement, 24);
    const meta = svg("text", { class: "meta", x: x - BOX.w / 2 + 12, y: y + BOX.h / 2 - 9 });
    meta.textContent = [n.acceptance_state, n.workflow_state, n.integrity_state !== "current" ? n.integrity_state : "", n.assignee ? `@${n.assignee}` : ""].filter(Boolean).join(" · ");
    g.append(kind, label, meta);
    if (n.frontier) {
      const tag = svg("text", { class: "tag", x: x, y: y + BOX.h / 2 + 13, "text-anchor": "middle" });
      tag.textContent = "ready to claim";
      g.append(tag);
    }
    const title = svg("title");
    title.textContent = n.statement;
    g.append(title);
    const open = () => { location.href = pageOf(n); };
    g.addEventListener("click", open);
    g.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
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
  const item = (id, ancestors) => {
    const n = byId.get(id);
    const li = el("li");
    if (!n) { li.append(el("span", `${id} (missing)`, { class: "warning" })); return li; }
    li.append(el("a", n.id, { href: pageOf(n) }), ` — ${short(n.display_label || n.statement, 60)}`);
    li.append(el("span", n.acceptance_state, { class: "state-chip" }), el("span", n.workflow_state, { class: "state-chip" }));
    li.append(el("span", n.integrity_state, { class: `state-chip${n.integrity_state === "current" ? "" : " warn-chip"}` }));
    if (n.assignee) li.append(el("span", `@${n.assignee}`, { class: "state-chip" }));
    if (n.frontier) li.append(el("span", "ready to claim", { class: "state-chip" }));
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
  $("map-caption").textContent = `${nodes.length} node(s) · ${frontier} on the frontier · click a node to open it`;
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
    try { await showNode(decodeURIComponent(match[1])); } catch (error) { say(error.message, "error"); }
  }
}

async function refresh() {
  state = await api("/api/state");
  mapData = await api("/api/map");
  $("project").textContent = `· ${state.project_id} · ${state.origin}`;
  $("new-dependencies").replaceChildren(...mapData.nodes.map((n) => el("option", `${n.id} (${n.kind})`, { value: n.id })));
  $("reviewer").textContent = `Decisions are recorded as ${state.reviewer}.`;
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
  $("view-dag").addEventListener("click", () => { mapView = "dag"; showMap(); });
  $("view-tree").addEventListener("click", () => { mapView = "tree"; showMap(); });
  $("tree-root").addEventListener("change", showMap);
  $("new-node").addEventListener("submit", createNode);
  $("new-kind").addEventListener("change", showNewNodeKind);
  window.addEventListener("hashchange", route);
  refresh().catch((error) => say(error.message, "error"));
});
