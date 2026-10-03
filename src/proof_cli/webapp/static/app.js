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

// -- the fog drawer (issue #137, ADR-0008): the Proof fog beside the map, never on it -----------------
// A fog item is a difficulty not yet precise enough to be a Claim; it is never a node, and `near` is
// an informal pointer, never a dependency. The drawer lists open items (dropped and crystallized ones
// on request), adds, drops, reopens and records Experiments through /api/fog; crystallize is a CLI
// command until it opens the map's node form (#155). Hovering a row lights its near nodes up on the
// canvas the way the search box does, with nothing drawn on the map.
let fogData = { items: [] };
// form: {id, kind} of the one inline form showing; near: the hovered row's nodes, lit up on the map; found: the row a #/fog/<id> link asked for
const fog = { open: false, showAll: false, form: null, near: null, found: null };

async function loadFog() {
  fogData = await api(fog.showAll ? "/api/fog?all=1" : "/api/fog");
  showFog();
}

// every write the drawer makes: post it, say what happened, read the fog again; a refusal is shown and nothing else changes
async function fogPost(path, body, message) {
  try { await api(path, body); } catch (error) { showError(error); return false; }
  fog.form = null;
  say(message, "ok");
  await loadFog();
  return true;
}

function fogNodeHref(id) {
  const n = mapData ? mapData.nodes.find((x) => x.id === id) : null;
  return n ? pageOf(n) : `#/node/${encodeURIComponent(id)}`;
}

// the newest Experiment as a chip: its outcome and summary, the rest on hover
function experimentChip(item) {
  const e = item.latest_experiment;
  if (!e) return el("span", "no experiment yet", { class: "exp none" });
  const when = String(e.recorded_at || "").slice(0, 16).replace("T", " ");
  return el("span", `${e.outcome} · ${short(e.summary, 48)}`, { class: `exp ${e.outcome}`, title: `${e.summary} — ${e.run_by}, ${when}${e.path ? ` · ${e.path}${e.missing ? " (missing)" : ""}` : ""}` });
}

function nearChips(item) {
  const box = el("span", null, { class: "fog-near" });
  if (!item.near.length) box.append(el("span", "not near any node", { class: "fog-id" }));
  for (const id of item.near) box.append(el("a", id, { href: fogNodeHref(id), title: `near ${id} — what it is about, never a dependency` }));
  return box;
}

function fogStatusLine(item) {
  if (item.status === "dropped") return el("span", `dropped · ${item.dropped_by}, ${String(item.dropped_at || "").slice(0, 10)} — ${item.reason}`, { class: "fog-status" });
  if (item.status === "crystallized") { const line = el("span", "crystallized as ", { class: "fog-status" }); line.append(el("a", item.node_id, { href: fogNodeHref(item.node_id) })); return line; }
  return null;
}

// the one inline form a row shows: drop (a reason), experiment (an outcome and a summary)
function fogForm(item, kind) {
  const form = el("form", null, { class: "fog-form" });
  form.addEventListener("submit", (event) => event.preventDefault());
  const send = (action, body) => fogPost(`/api/fog/${encodeURIComponent(item.id)}/${action}`, body, `${item.id}: ${action === "drop" ? "dropped" : "experiment recorded"}.`);
  if (kind === "drop") {
    const reason = el("input", null, { type: "text", name: "reason", placeholder: "why (required)", "aria-label": "Why it is dropped" });
    const go = el("button", "Drop", { type: "button", class: "primary" });
    go.addEventListener("click", () => { if (!reason.value.trim()) return say("A reason is required to drop a fog item.", "error"); send("drop", { reason: reason.value.trim() }); });
    form.append(reason, go);
  } else {
    const outcome = el("select", null, { name: "outcome", "aria-label": "Outcome" });
    for (const value of ["supports", "refutes", "inconclusive", "error"]) outcome.append(el("option", value, { value }));
    const summary = el("input", null, { type: "text", name: "summary", placeholder: "what was computed, what it showed", "aria-label": "Summary" });
    // who ran it is the request's to say: the page's identity, editable (an agent's run is recorded under the agent's name)
    const runBy = el("input", null, { type: "text", name: "run_by", value: state ? state.reviewer : "", placeholder: "run by", "aria-label": "Who ran it" });
    const path = el("input", null, { type: "text", name: "path", placeholder: "path under proofs/ (optional)", "aria-label": "Where its files are" });
    const go = el("button", "Record", { type: "button", class: "primary" });
    go.addEventListener("click", () => {
      if (!summary.value.trim()) return say("A summary is required to record an Experiment.", "error");
      if (!runBy.value.trim()) return say("Say who ran the Experiment.", "error");
      send("experiment", { outcome: outcome.value, summary: summary.value.trim(), run_by: runBy.value.trim(), ...(path.value.trim() ? { path: path.value.trim() } : {}) });
    });
    form.append(outcome, summary, runBy, path, go);
  }
  const cancel = el("button", "Cancel", { type: "button" });
  cancel.addEventListener("click", () => { fog.form = null; showFog(); });
  form.append(cancel);
  return form;
}

function fogActions(item) {
  const box = el("div", null, { class: "fog-actions" });
  const button = (text, onClick, primary) => { const b = el("button", text, { type: "button", class: primary ? "primary" : "" }); b.addEventListener("click", (event) => { event.stopPropagation(); onClick(); }); return b; };
  // each "…" button opens its inline form (or hint) under the row; a second click closes it
  const toggle = (kind) => () => { fog.form = fog.form && fog.form.id === item.id && fog.form.kind === kind ? null : { id: item.id, kind }; showFog(); };
  if (item.status === "open") box.append(button("Crystallize…", toggle("crystallize"), true), button("Record experiment…", toggle("experiment")), button("Drop…", toggle("drop")));
  else if (item.status === "dropped") box.append(button("Reopen", () => fogPost(`/api/fog/${encodeURIComponent(item.id)}/reopen`, {}, `${item.id}: reopened.`)));
  return box;
}

// a crystallize is a CLI command until it opens the map's node form (#155): the command, ready to copy
function crystallizeHint(item) {
  const parent = item.near.length === 1 ? ` --parent ${item.near[0]}` : item.near.length > 1 ? ` --parent <one of ${item.near.join(", ")}>` : "";
  const hint = el("p", null, { class: "hint fog-cli-hint" });
  hint.append("State it as a Claim from the CLI (the statement is written fresh; the fog's text is never copied): ",
    el("code", `proof fog crystallize ${item.id} <node-id> "<statement>"${parent}`, { class: "fog-cli" }));
  return hint;
}

function fogRow(item) {
  const li = el("li", null, { "data-fog": item.id, class: item.status === "open" ? "" : "gone" });
  const line = el("div", null, { class: "line" });
  line.append(el("span", item.id, { class: "fog-id" }), experimentChip(item));
  li.append(line, el("p", item.text, { class: "fog-text" }));
  if (item.notes) li.append(el("p", item.notes, { class: "hint fog-notes" }));
  const meta = el("div", null, { class: "meta" });
  meta.append(nearChips(item));
  const status = fogStatusLine(item);
  if (status) meta.append(status);
  li.append(meta, fogActions(item));
  if (fog.form && fog.form.id === item.id) li.append(fog.form.kind === "crystallize" ? crystallizeHint(item) : fogForm(item, fog.form.kind));
  // hovering a row lights its near nodes up on the map, the rest fall back: the search box's own marking
  // (dim / found), on the canvas and the tree alike; nothing is drawn on the map for a fog item
  li.addEventListener("mouseenter", () => focusFogNodes(item.near));
  li.addEventListener("mouseleave", () => focusFogNodes(null));
  if (fog.found === item.id) li.classList.add("found");
  return li;
}

function focusFogNodes(ids) {
  fog.near = ids && ids.length ? new Set(ids) : null;
  applyFind();
}

function showFog() {
  focusFogNodes(null);  // the rows are rebuilt: a hovered one goes without its mouseleave
  const items = fogData.items || [];
  const open = items.filter((item) => item.status === "open").length;
  $("stat-fog").textContent = String(open);
  $("fog-drawer-n").textContent = String(open);
  $("fog-badge").classList.toggle("on", fog.open);
  $("fog-drawer").hidden = !fog.open;
  $("fog-show-all").checked = fog.showAll;
  const near = $("fog-add-near");
  const chosen = near.value;
  near.replaceChildren(el("option", "near: none", { value: "" }), ...(mapData ? mapData.nodes : []).map((n) => el("option", `near: ${n.id}`, { value: n.id })));
  near.value = chosen;
  const list = $("fog-list");
  list.replaceChildren(...items.map(fogRow));
  if (!items.length) list.append(el("li", fog.showAll ? "No fog, dropped or crystallized." : "No fog: everything you know of is stated as a node.", { class: "fog-none" }));
}

// the drawer, open at one item (a link from a node's page): a dropped or crystallized one shows the rest too
async function openFogAt(fogId) {
  fog.open = true;
  fog.found = fogId;
  if (!(fogData.items || []).some((item) => item.id === fogId) && !fog.showAll) { fog.showAll = true; try { await loadFog(); } catch (error) { showError(error); return; } }
  showFog();
}

async function addFog() {
  const text = $("fog-add-text").value.trim();
  if (!text) return say("Say what the difficulty is.", "error");
  const nearId = $("fog-add-near").value;
  if (await fogPost("/api/fog", { text, near: nearId ? [nearId] : [] }, "Fog item added.")) $("fog-add-text").value = "";
}

function showWarnings(list, into) {
  into.replaceChildren(...list.map((w) => { const li = el("li", null, { class: "warning" }); li.append(el("code", w.code), " ", w.message); return li; }));
  if (!list.length) into.append(el("li", "None."));
}

// why a review card offers no decision, and the next step (#156)
function reviewBlocked(blocked) {
  const box = el("div", null, { class: "review-blocked" });
  if (!blocked) { box.append(el("p", "No decision can be made on it right now.", { class: "hint" })); return box; }
  box.append(el("p", blocked.message, { class: "hint warning" }));
  if (blocked.next) box.append(el("code", blocked.next, { class: "review-next" }));
  return box;
}

// the Evidence checks on a card's snapshot (#158), compactly: outcome, who ran it, when, and the hash it is
// bound to; one that doesn't match the snapshot as it is now is marked, the way the node page marks it
const CARD_EVIDENCE_MARKS = { unverifiable: "unverifiable", changed: "snapshot changed since this check", unbound: "not bound (recorded before binding)" };
function cardEvidence(checks) {
  const list = el("ul", null, { class: "card-evidence" });
  for (const c of checks) {
    const when = String(c.created_at || "").replace("T", " ").slice(0, 16);
    const hash = c.sha256 ? ` · ${c.sha256.slice(0, 12)}…` : "";
    const li = el("li", `${c.outcome} · run by ${c.run_by} · ${when}${hash}`, { class: "hint", title: [c.notes, c.sha256 ? `SHA-256 ${c.sha256}` : ""].filter(Boolean).join(" · ") });
    const mark = CARD_EVIDENCE_MARKS[c.state];
    if (mark) {
      const chip = stateChip("unverifiable", mark, mark);  // the map's attention triangle and colour
      chip.classList.add("state-chip", "warning");
      li.append(" ", chip);
    }
    list.append(li);
  }
  return list;
}

function showHome() {
  const body = $("pending").querySelector("tbody");
  body.replaceChildren(...state.pending.map((item) => {
    // a card offers only decisions the server would take: with none (its dependencies changed since its
    // snapshot, #156, or the snapshot can't be read, #92) it can't be ticked, and says why and what to do next
    const offered = item.decisions.length > 0;
    const box = offered ? el("input", null, { type: "checkbox" }) : "";
    const choice = offered ? el("select") : reviewBlocked(item.review_blocked);
    for (const decision of item.decisions) choice.append(el("option", decision));
    const rationale = offered ? el("input", null, { placeholder: "why" }) : "";
    // a local node is reviewed in its studio (#71); an imported result on its own page
    const inStudio = item.kind !== "reference_review";
    const link = el("a", null, {
      class: "review-link",
      href: item.kind === "reference_review" ? `#/node/${encodeURIComponent(item.node_id)}` : `/studio/${encodeURIComponent(item.node_id)}/#review`,
      title: inStudio ? "Review it in the node's studio" : "Review the source on the node's page",
    });
    // a page under a magnifier: "go and review this", then the node, then a chevron
    const glass = svg("svg", { viewBox: "0 0 24 24", class: "review-link-icon", "aria-hidden": "true" });
    glass.append(svg("path", { d: "M13 20H6.5A1.5 1.5 0 0 1 5 18.5v-13A1.5 1.5 0 0 1 6.5 4h7L18 8.5v2.5" }), svg("path", { d: "M13.5 4v4.5H18" }),
      svg("circle", { cx: 16, cy: 16, r: 3 }), svg("path", { d: "m18.2 18.2 2.3 2.3" }));
    const chevron = svg("svg", { viewBox: "0 0 24 24", class: "review-link-chevron", "aria-hidden": "true" });
    chevron.append(svg("path", { d: "m9.5 6 6 6-6 6" }));
    link.append(glass, el("span", item.node_id), chevron);
    const statement = el("div", item.statement);
    if (item.citation) statement.append(citationLine(item.citation));
    if (item.candidate_proof && item.candidate_proof.id) {
      // review starts from the key ideas (ADR-0013): the card shows the snapshot's 核心思路 and 难点;
      // the whole summary and the decision are in the studio's review view, the frozen LaTeX on the
      // node's page. The hash is shortened here, in full on hover.
      const proof = item.candidate_proof;
      const hash = proof.sha256 ? ` · ${proof.sha256.slice(0, 12)}…` : "";
      statement.append(el("p", `Snapshot v${proof.version}${hash}`, { class: "hint snap-meta", title: proof.sha256 ? `SHA-256 ${proof.sha256}` : "" }), keyIdeasCard(proof.key_ideas));
      if ((item.evidence_checks || []).length) statement.append(cardEvidence(item.evidence_checks));
    }
    const tr = row([box, link, statement, choice, rationale]);
    tr.dataset.kind = item.kind; tr.dataset.target = item.node_id;
    if (item.candidate_proof && item.candidate_proof.sha256) tr.dataset.viewed = item.candidate_proof.sha256;
    tr.dataset.bindings = JSON.stringify(item.bindings || {});
    return tr;
  }));
  if (!state.pending.length) body.append(row(["", "Nothing is awaiting review.", "", "", ""]));
  showTrusted(state.trusted_by_rule || []);
  showWarnings(state.warnings, $("warnings"));
  const pending = String(state.pending.length);
  $("stat-review").textContent = pending;
  $("pending-count").textContent = pending;
  $("rail-review").textContent = state.pending.length ? pending : "";
  $("rail-review").className = state.pending.length ? "n hot" : "n";
  $("records-count").textContent = state.warnings.length ? String(state.warnings.length) : "";
}

// The imported results callable under a Trust rule without a review of their own (ADR-0014): what the
// researcher hasn't looked at, in its own collapsed section, never counted as awaiting them. "Review
// explicitly" records the ordinary Reference review, its rationale prefilled here and editable.
function showTrusted(items) {
  const body = $("trusted").querySelector("tbody");
  body.replaceChildren(...items.map((item) => {
    const link = el("a", item.node_id, { class: "review-link", href: `#/node/${encodeURIComponent(item.node_id)}`, title: "The node's page" });
    const statement = el("div", item.statement);
    if (item.citation) statement.append(citationLine(item.citation));
    const rules = el("div");
    for (const name of item.trust_rule) { const chip = stateChip("trusted-by-rule", name, `trust rule ${name}`); chip.classList.add("state-chip", "rule-chip"); rules.append(chip); }
    const rationale = el("input", null, { placeholder: "why" });
    rationale.value = item.rationale || "";
    const button = el("button", "Review explicitly", { type: "button" });
    button.onclick = async () => {
      const binding = (item.bindings || {})["reference-review"] ?? null;
      try { await decide([{ kind: "reference_review", target_id: item.node_id, decision: "reference-review", rationale: rationale.value, binding }]); }
      catch (error) { showError(error); }
    };
    const tr = row([link, statement, rules, rationale, button]);
    tr.dataset.target = item.node_id;
    return tr;
  }));
  if (!items.length) body.append(row(["", "No imported result is trusted by rule.", "", "", ""]));
  $("trusted-count").textContent = items.length ? String(items.length) : "";
}

// -- the rules sheet (ADR-0014): the rules in force, their history, and the three decisions on them ------
let rulesData = null;
const CONDITION_BOXES = { "cond-reviewed": "source_already_reviewed", "cond-doi": "identifier_has_doi", "cond-arxiv": "identifier_has_arxiv" };

async function openRulesSheet() {
  rulesData = await api("/api/trust-rules");
  $("cond-types").replaceChildren(...rulesData.source_types.map((type) => {
    const label = el("label");
    label.append(el("input", null, { type: "checkbox", value: type, "data-type": type }), type);
    return label;
  }));
  renderRules();
  ruleForm("declare");
  $("rules-sheet").hidden = false;
}

function renderRules() {
  const item = (rule) => {
    const li = el("li", null, { "data-rule": rule.name });
    li.append(el("b", rule.name), el("span", rule.conditions_text.join(" · "), { class: "conds" }), el("span", rule.rationale));
    li.append(el("span", `${rule.retired ? "retired" : "declared"} by ${rule.retired ? rule.changed_by : rule.declared_by} · ${rule.retired ? rule.changed_at : rule.declared_at}` +
      ` · trusting ${rule.trusting.length ? rule.trusting.join(", ") : "nothing right now"} · ${rule.history.length} decision(s)`, { class: "meta" }));
    if (!rule.retired) {
      const acts = el("div", null, { class: "acts" });
      const amend = el("button", "Amend", { type: "button" }), retire = el("button", "Retire", { type: "button" });
      amend.onclick = () => ruleForm("amend", rule);
      retire.onclick = () => ruleForm("retire", rule);
      acts.append(amend, retire);
      li.append(acts);
    }
    return li;
  };
  $("rules-list").replaceChildren(...rulesData.rules.filter((r) => !r.retired).map(item));
  $("rules-retired-list").replaceChildren(...rulesData.rules.filter((r) => r.retired).map(item));
}

// the form for one decision: a fresh declaration, or an amend or retire of a listed rule
function ruleForm(decision, rule) {
  $("rule-decision").value = decision;
  $("rules-form-title").textContent = decision === "declare" ? "Declare a rule" : decision === "amend" ? `Amend ${rule.name}` : `Retire ${rule.name}`;
  $("rule-name").value = rule ? rule.name : "";
  $("rule-name").disabled = decision !== "declare";  // a name never changes
  $("rule-rationale").value = "";
  $("rule-conditions").disabled = decision === "retire";
  const has = (kind) => !!(rule && rule.conditions.some((c) => c.kind === kind));
  for (const [id, kind] of Object.entries(CONDITION_BOXES)) $(id).checked = decision !== "retire" && has(kind);
  const types = new Set(rule ? rule.conditions.filter((c) => c.kind === "source_type_in").flatMap((c) => c.values) : []);
  for (const box of $("cond-types").querySelectorAll("input")) box.checked = decision !== "retire" && types.has(box.value);
  $("rule-record").textContent = decision === "retire" ? "Record retirement" : decision === "amend" ? "Record amendment" : "Record";
  ruleFormChanged();
}

function formConditions() {
  const conditions = Object.entries(CONDITION_BOXES).filter(([id]) => $(id).checked).map(([, kind]) => ({ kind }));
  const types = [...$("cond-types").querySelectorAll("input")].filter((box) => box.checked).map((box) => box.value);
  if (types.length) conditions.push({ kind: "source_type_in", values: types });
  return conditions;
}

// The reminder for a weak source type, and the impact of a change, read as the form changes. An amend or
// retire is recorded only against the impact of the form as it stands now: a preview that comes back for an
// earlier state of the form is dropped, and Record waits for the current one (and stays off if it failed).
let previewSeq = 0;
let previewCurrent = false;
async function ruleFormChanged() {
  const decision = $("rule-decision").value;
  const conditions = formConditions();
  const weak = (rulesData ? rulesData.weak_source_types : []).filter((type) => conditions.some((c) => c.kind === "source_type_in" && c.values.includes(type)));
  $("rule-reminder").textContent = decision !== "retire" && weak.length
    ? `This rule trusts ${weak.join(" and ")} sources: anything an importer typed as one would be callable without your look. Allowed — is it what you mean?` : "";
  $("rule-impact").textContent = "";
  const seq = ++previewSeq;
  previewCurrent = decision === "declare";  // a declaration has no impact to wait for
  $("rule-record").disabled = !previewCurrent;
  if (decision === "declare") return;
  try {
    const impact = await api("/api/trust-rules/preview", { name: $("rule-name").value, decision, ...(decision === "amend" ? { conditions } : {}) });
    if (seq !== previewSeq) return;  // the form moved on: this answers an earlier state of it
    const parts = [`${impact.losing.length} node(s) would stop reading trusted by rule`];
    if (impact.losing.length) parts.push(`${impact.depended_on_by_accepted.length} of them depended on by Accepted nodes (their Acceptance keeps; other dependents block)`);
    if (impact.gaining.length) parts.push(`${impact.gaining.length} would newly read trusted by rule`);
    $("rule-impact").textContent = `Impact: ${parts.join("; ")}${impact.losing.length ? ` — ${impact.losing.join(", ")}` : ""}.`;
    previewCurrent = true;
    $("rule-record").disabled = false;
  } catch (error) {
    if (seq !== previewSeq) return;
    $("rule-impact").textContent = `${error.code ? `${error.code}: ${error.message}` : error.message} — nothing can be recorded until the impact is known`;
  }
}

async function recordRule() {
  if (!previewCurrent) return say("Wait for the impact preview of this change before recording it.", "error");
  const decision = $("rule-decision").value;
  const item = { kind: "trust_rule", target_id: $("rule-name").value.trim(), decision, rationale: $("rule-rationale").value, ...(decision === "retire" ? {} : { conditions: formConditions() }) };
  $("rules-sheet").hidden = true;  // the confirm sheet takes its place
  try { await decide([item]); } catch (error) { showError(error); $("rules-sheet").hidden = false; return; }  // cancelled or refused: back to the form as it was
  await openRulesSheet();  // back to the list, as it now stands
}

// who wrote a snapshot's key ideas, as its record says (ADR-0013): recorded by the studio, never read from the file
const KEY_IDEAS_BY = {
  "agent (confirmed by author at request-review)": "由 agent 起草、作者确认 · drafted by the proof agent, confirmed by the author",
  "agent draft, edited by author": "由 agent 起草、作者修改 · the proof agent's draft, edited by the author",
  "author": "作者撰写 · written by the author",
};

// a field's text with its $…$ and $$…$$ typeset (static/mathtext.js, KaTeX); plain text without it
const withMath = (node, text) => {
  if (typeof renderMathText === "function") return renderMathText(node, text);
  node.textContent = String(text);
  return node;
};

// A review card's key ideas (ADR-0013): 核心思路 and 难点 only, as text (`$…$` stays as written).
function keyIdeasCard(summary) {
  const block = el("div", null, { class: "key-ideas" });
  if (!summary) { block.append(el("p", "这个 snapshot 没有关键思路摘要 · no key-ideas summary: read it in the studio", { class: "hint" })); return block; }
  for (const [key, title] of [["core_idea", "核心思路"], ["difficulties", "难点"]]) {
    const text = (summary.fields || {})[key];
    if (text) block.append(el("span", title, { class: "lbl" }), withMath(el("p", null, { class: `key-idea ${key}` }), text));
  }
  if (summary.drafted_by) block.append(el("p", KEY_IDEAS_BY[summary.drafted_by] || summary.drafted_by, { class: "hint" }));
  return block;
}

// The ReferenceRecord an imported result links (issue #91): what a Reference review is about.
// Its text may be edited later without touching the review; a missing one is marked, never hidden.
function citationMissing(c) {
  return el("p", `citation missing: reference ${c.reference_id} doesn't exist in this project`, { class: "citation warning" });
}

function citationLine(c) {
  if (c.missing) return citationMissing(c);
  const who = c.authors.length ? ` — ${c.authors.join(", ")}` : "";
  return el("p", `cites ${c.reference_id}: ${c.title}${who}${c.year ? ` (${c.year})` : ""} · ${c.locator} · ${c.version}`, { class: "hint citation" });
}

function citationBlock(c) {
  const block = el("div", null, { class: "citation-block" });
  block.append(el("h3", "Citation"));
  if (c.missing) { block.append(citationMissing(c)); return block; }
  block.append(el("p", c.title, { class: "citation title" }));
  block.append(el("p", `${c.authors.join(", ") || "no authors listed"}${c.year ? ` · ${c.year}` : ""}`, { class: "citation" }));
  const where = [c.identifier, c.url].filter(Boolean).join(" · ");
  if (where) block.append(el("p", where, { class: "citation mono" }));
  block.append(el("p", `reference ${c.reference_id} · cited at ${c.locator} · ${c.version}`, { class: "hint citation" }));
  return block;
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
  "trust_rule:declare": "Declare a Trust rule",
  "trust_rule:amend": "Amend the Trust rule (its rationale and conditions)",
  "trust_rule:retire": "Retire the Trust rule (final; the name is never reused)",
};

function showError(error) { if (error.message !== "cancelled") say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }

function decisionRow(decision, proof, prefill) {
  const label = DECISION_LABELS[`${decision.kind}:${decision.decision}`] || `${decision.kind}: ${decision.decision}`;
  const on = decision.kind === "dependent_migration" ? `onto ${decision.dependency_id}`
    : decision.dependency_id ? `dependency ${decision.dependency_id}` : decision.target_id;
  const rationale = el("input", null, { placeholder: "why" });
  if (prefill) rationale.value = prefill;
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

// which warning a node carries, each drawn differently: challenged, potentially stale, or a decision that no longer applies
function warningOf(n) {
  if (n.integrity_state === "challenged") return "challenged";
  if (n.integrity_state === "potentially-stale") return "stale";
  if (n.acceptance_state === "unverifiable") return "unverifiable";
  return "";
}

function short(text, length) { return text.length > length ? text.slice(0, length - 1) + "…" : text; }

// A node's one state, an icon anyone reads at a glance and a word, is the server's `status`
// (webapp/node_status.py, issue #157): the card, the legend, the tree and the node page all show
// it, none derives its own. A frontier node with a warning keeps its frontier mark too, a small
// blue badge beside the warning's (ADR-0008): statusMarks in status.js.
// where the agent's run on a node is (spec #145): "Typesetter · step 4/5", "Prover · paused", "Numerics · needs you"
function runWhere(run) {
  const role = run.role ? run.role.charAt(0).toUpperCase() + run.role.slice(1) : "Agent";
  if (run.status === "needs-human") return `${role} · needs you`;
  if (run.step && run.steps) return `${role} · step ${run.step}/${run.steps}`;
  return run.status === "paused" ? `${role} · paused` : role;
}

// an imported result's acceptance axis, in words: "trusted by rule <names>" names the Trust rules it meets (ADR-0014)
function acceptanceText(n) {
  return n.acceptance_state === "trusted-by-rule" ? `trusted by rule ${(n.trust_rule || []).join(", ")}` : n.acceptance_state;
}

// A state value on the node page, the tree or anywhere else, as the map's icon for it plus its word:
// every axis value lands on one of the kinds (STATUS_OF_VALUE in status.js; neutral ones get a plain grey disc).
function stateChip(value, text, title) {
  return kindChip(STATUS_OF_VALUE[value] || "open", text || value, title || text || value);
}

function kindChip(kind, text, title) {
  const chip = el("span", null, { class: `chip state-${kind}`, title: title || text });
  const icon = svg("svg", { viewBox: "-1 -1 18 18", class: "chip-icon", "aria-hidden": "true" });
  icon.append(statusIcon(kind, 8, 8, 16));
  chip.append(icon, text);
  return chip;
}

// a node's status (the server's, issue #157) as chips: its own, and a frontier node's Ready beside a warning (ADR-0008)
function statusChips(status, frontier) {
  return statusMarks(status, frontier).map((mark) => {
    const chip = kindChip(mark.kind, mark.text, mark.kind === "ready" ? "on the frontier: ready to start" : mark.text);
    chip.classList.add("node-status");
    return chip;
  });
}

// the icons are status.js's, defined once for every view
function statusIcon(kind, x, y, size = 16) {
  const icon = svg("g", { class: `status-icon ${kind}`, transform: `translate(${x - size / 2},${y - size / 2}) scale(${size / 16})` });
  for (const [tag, attrs] of statusShapes(kind)) icon.append(svg(tag, attrs));
  return icon;
}

// the legend: every kind's icon and what it means, Open among them
function drawLegend() {
  $("map-legend").replaceChildren(...Object.entries(STATUS_KINDS).map(([kind, { label }]) => {
    const icon = svg("svg", { class: `status-icon ${kind}`, viewBox: "-1 -1 18 18", "aria-hidden": "true" });
    for (const [tag, attrs] of statusShapes(kind)) icon.append(svg(tag, attrs));
    const li = el("li", null, { "data-kind": kind });
    li.append(icon, label);
    return li;
  }));
}

const KIND_LABEL = { theorem: "Theorem", lemma: "Lemma", claim: "Claim", imported_result: "Imported result" };
const capitalised = (text) => text.charAt(0).toUpperCase() + text.slice(1);
// whether a node's candidate proof is a program (spec #145): its medium is computation
const isComputation = (node) => node.medium === "computation";

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
    box.append(Object.assign(svg("text", { x: 16, y: 64, class: "empty" }), { textContent: "Right-click anywhere to create the first node, or run `proof node create`." }));
    // an empty scene still: the node form's ghost card is drawn on it (issue #154)
    const scene = svg("g", { id: "dag-view" });
    box.append(scene);
    applyView();
    if (typeof drawNodeFormGhost === "function") drawNodeFormGhost(scene);
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
  view.at = at;  // each node's centre on the scene, for the search box to bring one into view
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
    const classes = ["node", `state-${n.status.kind}`, n.frontier ? "frontier" : "", rejected(n) ? "rejected" : ""].filter(Boolean).join(" ");
    const place = () => { const p = at.get(n.id); g.setAttribute("transform", `translate(${p.x},${p.y})`); };
    const g = svg("g", { class: classes, "data-node-id": n.id, tabindex: 0, role: "link", "aria-label": `${n.kind} ${n.id}: ${acceptanceText(n)}, ${n.workflow_state}, ${n.integrity_state}${n.assignee ? `, claimed by ${n.assignee}` : ""}${n.frontier ? ", on the frontier" : ""}` });
    place();
    g.append(svg("rect", { class: "box", x: left, y: top, width: BOX.w, height: BOX.h, rx: BOX.radius }));
    const kind = svg("text", { class: "kind", x: left + 14, y: top + 21 });
    kind.textContent = `${KIND_LABEL[n.kind] || capitalised(n.kind.replace("_", " "))}${isComputation(n) ? " · computation" : ""}  `;
    const id = svg("tspan", { class: "id" });
    id.textContent = short(n.id, 18);
    kind.append(id);
    const label = svg("text", { x: left + 14, y: top + 41 });
    label.textContent = short(n.display_label || n.statement, 22);
    const meta = svg("text", { class: "meta", x: left + 14, y: top + 58 });
    meta.textContent = n.display_label ? short(n.statement, 30) : "";
    g.append(kind, label, meta);
    // the node's one state (the server's, issue #157), as a word along the bottom
    const [own, ...beside] = statusMarks(n.status, n.frontier);
    const status = svg("g", { class: `status ${own.kind}` });
    const tag = svg("text", { class: "tag", x: left + 14, y: top + BOX.h - 13 });
    tag.textContent = short(own.text, 24);
    status.append(tag);
    // the state's icon, large, as a badge on the card's top-right corner
    g.append(status, statusIcon(own.kind, left + BOX.w - 6, top + 6, 30));
    // the frontier is its own, strongest signal (ADR-0008): a warning is shown beside it, never in its place
    for (const mark of beside) g.append(statusIcon(mark.kind, left + BOX.w - 36, top + 6, 22));
    // Start agent from the card (spec #145): a local node nobody holds; the click never opens the node
    if (n.kind !== "imported_result" && !n.assignee && !n.run && !rejected(n)) {
      const start = svg("g", { class: "start", role: "button", tabindex: 0, "aria-label": `Start the agent on ${n.id}` });
      start.append(svg("rect", { x: left + BOX.w - 78, y: top + BOX.h - 26, width: 66, height: 18, rx: 9 }));
      const label = svg("text", { x: left + BOX.w - 45, y: top + BOX.h - 13, "text-anchor": "middle" });
      label.textContent = "▶ Start";
      start.append(label);
      start.addEventListener("click", async (event) => {
        event.stopPropagation(); event.preventDefault();
        try { await api(`/api/node/${encodeURIComponent(n.id)}/agent/start`, {}); } catch (error) { showError(error); return; }
        say(`Agent started on ${n.id}.`, "ok");
        await refresh();
      });
      g.append(start);
    }
    // hovering shows the current snapshot's 核心思路 (ADR-0013), under the statement it proves
    const title = svg("title");
    title.textContent = n.core_idea ? `${n.statement}\n核心思路：${n.core_idea}` : n.statement;
    if (n.acceptance_state === "trusted-by-rule") title.textContent += `\n${acceptanceText(n)}`;  // the card's word is short; the names are a hover away
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
  if (typeof drawNodeFormGhost === "function") drawNodeFormGhost(scene);  // the node form's ghost card, while it is open (issue #154)
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
    // each line names its node; a node used by more than one parent also says how many share it
    const li = el("li");
    li.setAttribute("data-node-id", id);
    if ((parents.get(id) || 0) > 1) li.setAttribute("data-shared-by", String(parents.get(id)));
    if (!n) { li.append(el("span", `${id} (missing)`, { class: "warning" })); return li; }
    li.append(el("a", n.id, { href: pageOf(n), ...(n.core_idea ? { title: `核心思路：${n.core_idea}` } : {}) }), ` — ${short(n.display_label || n.statement, 60)}`);
    const small = (chip) => { chip.classList.add("state-chip"); return chip; };
    li.append(small(stateChip(n.acceptance_state, acceptanceText(n))), small(stateChip(n.workflow_state)), small(stateChip(n.integrity_state)));
    if (n.assignee) li.append(small(stateChip("claimed", n.assignee, `claimed by ${n.assignee}`)));
    li.append(...statusChips(n.status, n.frontier).map(small));  // the card's status, and its Ready beside a warning (issue #157)
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
  applyFind();
}

// -- the search box (issue #116): pick nodes out by id, label or statement, on the canvas and the tree ----
const finding = { shown: null };  // the match the first Enter brought into view; a second Enter opens it

function findMatcher() {
  const query = $("map-find").value.trim().toLowerCase();
  if (!query) return null;
  return (n) => [n.id, n.display_label || "", n.statement || ""].some((field) => field.toLowerCase().includes(query));
}

// dim what the search doesn't match, on whichever view is drawn, and say how many it does
function applyFind() {
  if (!mapData) return;
  const matches = findMatcher();
  const byId = new Map(mapData.nodes.map((n) => [n.id, n]));
  const near = fog.near;  // a hovered fog row's near nodes light up the way a search's matches do (issue #137)
  const mark = (item) => {
    const id = item.getAttribute("data-node-id");
    item.classList.toggle("dim", (!!matches && !matches(byId.get(id) || { id })) || (!!near && !near.has(id)));  // a missing dependency matches by id
    item.classList.toggle("found", (!!matches && id === finding.shown) || (!!near && near.has(id)));
  };
  $("dag-svg").classList.toggle("filtering", !!matches || !!near);
  for (const g of $("dag-svg").querySelectorAll("g.node")) mark(g);
  for (const li of $("map-tree").querySelectorAll("li")) mark(li);
  const count = $("map-find-count");
  if (!matches) { count.textContent = ""; return; }
  const found = mapData.nodes.filter(matches).length;
  const next = !found ? "No node has that id, label or statement" : finding.shown ? "Enter again opens it" : "Enter shows the first";
  count.textContent = `${found} of ${mapData.nodes.length} match · ${next}`;
}

// pan (and zoom to at least life size) so the node sits in the middle of the canvas (the toolbar
// sits above it, not over it)
function showOnCanvas(id) {
  const canvas = $("map-dag"), p = view.at && view.at.get(id);
  if (!p || !canvas.clientWidth) return;
  view.k = Math.min(4, Math.max(view.k, 1));
  view.tx = canvas.clientWidth / 2 - p.x * view.k;
  view.ty = canvas.clientHeight / 2 - p.y * view.k;
  applyView();
}

function wireFind() {
  const box = $("map-find");
  box.addEventListener("input", () => { finding.shown = null; applyFind(); });
  box.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (!box.value) { box.blur(); return; }  // a second Escape hands the keys back to the map
      box.value = "";
      finding.shown = null;
      applyFind();
      return;
    }
    if (event.key !== "Enter" || !mapData) return;
    event.preventDefault();
    const matches = findMatcher();
    const first = matches && mapData.nodes.find(matches);
    if (!first) return;
    if (finding.shown === first.id) { location.href = pageOf(first); return; }  // where it lives (ADR-0011)
    finding.shown = first.id;
    if (mapView === "dag") showOnCanvas(first.id);
    else [...$("map-tree").querySelectorAll("li")].find((li) => li.getAttribute("data-node-id") === first.id)?.scrollIntoView?.({ block: "center" });
    applyFind();
  });
  // "/" finds, as on most sites; the map's own keys (F fits) are untouched, and typing anywhere is never taken over
  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName) || active.isContentEditable)) return;
    if ($("home").hidden) return;
    event.preventDefault();
    box.focus();
    box.select();
  });
}

// Where a node opens (ADR-0011): a theorem, lemma or claim in its studio, an imported result on its own page.
function pageOf(n) {
  return n.kind === "imported_result" ? `#/node/${encodeURIComponent(n.id)}` : `/studio/${encodeURIComponent(n.id)}/`;
}

async function showNode(nodeId) {
  const view = await api(`/api/node/${encodeURIComponent(nodeId)}`);
  const node = view.node;
  $("node-title").replaceChildren(node.id, el("small", node.kind.replace("_", " ")));
  const axis = (name, value, text = value) => { const cell = el("div"); cell.append(el("span", name, { class: "lbl" }), stateChip(value, text, `${name}: ${text}`)); return cell; };
  const acceptance = acceptanceText({ acceptance_state: view.acceptance_state, trust_rule: view.trust_rule });
  // its one status, as its card shows it (issue #157), then its three axes
  const status = el("div");
  status.append(el("span", "status", { class: "lbl" }), ...statusChips(view.status, view.frontier));
  $("node-axes").replaceChildren(status, axis("workflow", view.workflow_state), axis("acceptance", view.acceptance_state, acceptance), axis("integrity", view.integrity_state));
  showRunControls(node, view);
  const nodeWarnings = el("ul");
  showWarnings(view.warnings, nodeWarnings);
  $("node-warnings").replaceChildren(el("h3", "Warnings for this node"), nodeWarnings);
  $("node-statement").textContent = node.statement;
  $("node-assumptions").replaceChildren(...(node.assumptions.length ? [el("h3", "Assumptions"), ...node.assumptions.map((a) => el("p", a))] : []));
  $("node-claim").textContent = view.claim ? `Claimed by ${view.claim.claimant_id} since ${view.claim.claimed_at} (claim ${view.claim.id}).` : "";
  $("node-folder").replaceChildren();
  if (view.studio) $("node-folder").append(el("a", "Open the node's studio", { href: view.studio }), " · proof folder ", el("code", view.folder));
  $("node-source").replaceChildren(...(view.source ? [el("h3", "Source"), el("p", `${view.source.locator} · ${view.source.version}${view.source.trust_level ? ` · ${view.source.trust_level}` : ""}`)] : []));
  if (view.citation) $("node-source").append(citationBlock(view.citation));
  $("node-dependents").textContent = view.dependents.length ? `Used by: ${view.dependents.join(", ")}` : "Nothing depends on this node yet.";
  showNodeFog(view);
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
  showOutputs(node.id, proof);
  $("node-evidence").replaceChildren(...view.evidence_checks.map(evidenceItem));
  const decisions = $("node-decisions").querySelector("tbody");
  // reviewing a node trusted by rule explicitly (ADR-0014): the ordinary Reference review, its rationale prefilled
  const prefill = view.acceptance_state === "trusted-by-rule" ? `matched trust rule ${(view.trust_rule || []).join(", ")}; reviewed explicitly` : "";
  decisions.replaceChildren(...view.decisions.map((d) => decisionRow(d, proof, d.kind === "reference_review" && d.decision === "reference-review" ? prefill : "")));
  // its snapshot's dependencies changed (#156): no Acceptance decision is offered; the reason and the next step are
  if (view.review_blocked) decisions.append(row([reviewBlocked(view.review_blocked), "", "", ""]));
  else if (!view.decisions.length) decisions.append(row(["No decision to make on this node right now.", "", "", ""]));
  // when the node first met each Trust rule: on record as an event, never a decision (ADR-0014)
  const met = (view.rule_events || []).map((e) => el("li", `${e.at} · trusted by rule ${e.rule} since then — no decision written; the rule's declaration is the record`, { class: "rule-event" }));
  $("node-history").replaceChildren(...met, ...view.history.filter((r) => r.kind).map((r) => el("li", `${r.updated_at} · ${r.kind} · ${r.decision} · ${r.reviewer_id}${r.key_ideas_drafted_by ? ` · key ideas: ${KEY_IDEAS_BY[r.key_ideas_drafted_by] || r.key_ideas_drafted_by}` : ""}${r.rationale ? ` — ${r.rationale}` : ""}`)));
}

// An Evidence check names the Review snapshot it checked (issue #122): its version and a short
// SHA-256 (in full on hover), a link to the snapshot shown above when it is the node's current one,
// or where it is frozen when it is older, and a warning chip when it is older or can't be read.
function evidenceItem(c) {
  const li = el("li", `${c.outcome} — ${c.notes || "no notes"} (run by ${c.run_by}) · `);
  const s = c.snapshot;
  if (!s) { li.append(el("span", `on ${c.candidate_proof_id}`, { class: "mono" })); return li; }
  const hash = s.sha256 ? ` · ${s.sha256.slice(0, 12)}…` : "";
  const title = `${s.id}${s.sha256 ? ` · SHA-256 ${s.sha256}` : ""}`;
  if (s.current) {
    const link = el("a", `snapshot v${s.version}${hash}`, { href: location.hash || "#", class: "mono evidence-snap", title });
    link.addEventListener("click", (event) => { event.preventDefault(); $("node-snapshot")?.scrollIntoView?.({ behavior: "smooth", block: "start" }); });
    li.append(link);
  } else {
    li.append(el("span", `snapshot v${s.version}${hash}`, { class: "mono evidence-snap", title }), " · frozen at ", el("code", s.location));
  }
  // the check's own bound hash (PR #147): flagged when the snapshot changed since, said plainly when unbound
  const b = c.binding;
  if (b && b.state === "unbound") li.append(" · ", el("span", b.label, { class: "evidence-binding" }));
  else if (b && b.sha256 && b.state !== "matches") li.append(" · ", el("span", `bound to ${b.sha256.slice(0, 12)}…`, { class: "mono evidence-binding", title: b.sha256 }));
  const marks = [];
  if (!s.current) marks.push(`for an older version v${s.version}`);
  if (s.unreadable) marks.push("snapshot unreadable");
  if (b && b.state === "changed") marks.push(b.label);
  for (const text of marks) {
    const chip = stateChip("unverifiable", text, text);  // the map's attention triangle and colour
    chip.classList.add("state-chip", "warning");
    li.append(" ", chip);
  }
  return li;
}

// the Proof agent's run on a local node (spec #145): Start once, then the oversight actions — never a prompt
function showRunControls(node, view) {
  const box = $("node-run");
  box.replaceChildren();
  if (node.kind === "imported_result" || view.acceptance_state === "rejected") return;
  const run = view.run;
  const post = async (action, body) => {
    try { await api(`/api/node/${encodeURIComponent(node.id)}/agent/${action}`, body || {}); } catch (error) { showError(error); return; }
    say(`Agent run: ${action}.`, "ok");
    await route();
  };
  const button = (text, action, body, primary) => { const b = el("button", text, { type: "button", class: primary ? "primary" : "" }); b.addEventListener("click", () => post(action, body)); return b; };
  if (!run) {
    box.append(button("Start agent", "start", {}, true), el("span", "The agent works the node on its own, as Prover, Typesetter and Numerics, until it requests review or needs you.", { class: "hint" }));
    return;
  }
  if (run.status === "needs-human") {  // the run stopped for a decision only the researcher can make: it names it
    box.append(el("span", `${runWhere(run)}: ${run.decision || "a decision"}`, { class: "run-where" }), button("Start agent", "start", {}, true), button("Stop and release", "release", {}));
    return;
  }
  const where = `${run.step && run.steps ? runWhere(run) : runWhere({ role: run.role })} · ${run.status}`;
  box.append(el("span", where, { class: "run-where" }));
  if (run.status === "paused") box.append(button("Resume", "resume", {}));
  else if (run.status === "running") box.append(button("Pause", "pause", {}));
  const redirect = el("input", null, { type: "text", placeholder: "Redirect: one line for its next turn", "aria-label": "Redirect the agent" });
  const send = el("button", "Redirect", { type: "button" });
  send.addEventListener("click", () => { if (redirect.value.trim()) post("redirect", { text: redirect.value.trim() }); });
  box.append(redirect, send, button("Stop and release", "release", {}));
}

// the node's fog (ADR-0008): the item it was crystallized from, looked up in the fog table, and the open fog near it
function showNodeFog(view) {
  const block = $("node-fog");
  block.replaceChildren();
  if (view.crystallized_from) {
    const line = el("p", "Crystallized from ", { class: "hint" });
    line.append(el("a", view.crystallized_from, { href: `#/fog/${encodeURIComponent(view.crystallized_from)}`, title: "The fog item this Claim was stated from", class: "fog-id" }));
    block.append(line);
  }
  const near = view.fog_near || [];
  if (near.length) {
    block.append(el("h3", "Fog near this node"));
    const ul = el("ul", null, { class: "node-fog-list" });
    for (const item of near) { const li = el("li"); li.append(el("a", item.id, { href: `#/fog/${encodeURIComponent(item.id)}`, class: "fog-id" }), " ", el("span", item.text, { class: "fog-text" }), " ", experimentChip(item)); ul.append(li); }
    block.append(ul);
  }
}

// what a computation wrote to out/, as the snapshot froze it (spec #145): each file a link to itself,
// an image previewed; the frozen text files are shown above as text, a binary one never is
function showOutputs(nodeId, proof) {
  const box = $("node-outputs");
  box.replaceChildren();
  const outputs = (proof && proof.outputs) || [];
  if (!outputs.length) return;
  box.append(el("h3", "Frozen outputs"));
  const ul = el("ul", null, { class: "node-outputs-list" });
  for (const output of outputs) {
    const href = `/api/node/${encodeURIComponent(nodeId)}/snapshot/file?path=${encodeURIComponent(output.path)}`;
    const li = el("li");
    li.append(el("a", output.path, { href, target: "_blank", rel: "noopener", class: "mono" }), el("span", ` · ${output.type} · ${output.bytes} bytes`, { class: "hint" }));
    if (output.type.startsWith("image/")) li.append(el("img", null, { src: href, alt: output.path, class: "output-preview", loading: "lazy" }));
    ul.append(li);
  }
  box.append(ul);
}

async function route() {
  // four pages: the map (#/), the review list (#/review), the warnings (#/warnings), a node (#/node/<id>);
  // #/fog/<id> is the map with the fog drawer open at that item (issue #137)
  const match = location.hash.match(/^#\/node\/(.+)$/);
  const fogLink = location.hash.match(/^#\/fog\/(.+)$/);
  const page = match ? "node" : { "#/review": "review", "#/warnings": "warnings" }[location.hash] || "map";
  if (fogLink) await openFogAt(decodeURIComponent(fogLink[1]));
  document.body.dataset.page = page;
  $("home").hidden = page !== "map";
  $("review-page").hidden = page !== "review";
  $("warnings-page").hidden = page !== "warnings";
  $("node-page").hidden = page !== "node";
  if (page === "map" && view.content && !view.fitted) fitView();  // drawn while the map was hidden
  if (page === "map") showFog();  // the drawer as it was left (or as the badge or a #/fog link asked)
  for (const link of document.querySelectorAll(".rail a[data-nav]")) link.classList.toggle("on", link.dataset.nav === page);
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
  showAttention();
  try { await loadFog(); } catch (error) { say(`The fog couldn't be read: ${error.message}`, "error"); }  // a side drawer: never the page
  await route();
}

// The warnings page's first list: every node the map marks "needs attention" — a Challenge open
// on it, a dependency that moved (potentially stale), or a decision that no longer applies — with
// why, each opening where the node lives. The sidebar counts these and the review-record warnings.
const ATTENTION_WHY = {
  challenged: "A Challenge is open on it: it may no longer be safe to depend on.",
  "potentially-stale": "A dependency moved to a new accepted version: it may need a re-review or a new proof.",
  unverifiable: "Its newest Review decision no longer matches its snapshot or its statement: decide it afresh.",
};
function showAttention() {
  const nodes = mapData.nodes.filter((n) => warningOf(n));
  const list = $("attention-nodes");
  list.replaceChildren(...nodes.map((n) => {
    const reason = n.integrity_state === "challenged" ? "challenged" : n.integrity_state === "potentially-stale" ? "potentially-stale" : "unverifiable";
    const row = el("li");
    const link = el("a", null, { href: pageOf(n), class: "attention-node" });
    link.append(el("b", n.display_label || short(n.statement, 60)), el("span", `${KIND_LABEL[n.kind] || n.kind} · ${n.id}`, { class: "attention-id" }));
    row.append(stateChip(reason, n.status.text), link, el("p", ATTENTION_WHY[reason], { class: "hint" }));
    return row;
  }));
  if (!nodes.length) list.append(el("li", "Nothing on the map needs attention.", { class: "attention-none" }));
  $("attention-count").textContent = nodes.length ? String(nodes.length) : "";
  const total = nodes.length + state.warnings.length;
  $("rail-warnings").textContent = total ? String(total) : "";
  $("rail-warnings").className = total ? "n hot" : "n";
}

document.addEventListener("DOMContentLoaded", () => {
  drawLegend();
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
  wireFind();
  // the sidebar hides (remembered in this browser); on a narrow window it slides over the map
  const narrow = () => matchMedia("(max-width: 760px)").matches;
  try { if (localStorage.getItem("proof.map.sidebar") === "hidden") document.body.classList.add("sidebar-hidden"); } catch { /* ignore */ }
  $("sidebar-toggle").addEventListener("click", () => {
    if (narrow()) { document.body.classList.toggle("sidebar-shown"); return; }
    const hidden = document.body.classList.toggle("sidebar-hidden");
    try { localStorage.setItem("proof.map.sidebar", hidden ? "hidden" : "shown"); } catch { /* ignore */ }
    if (view.fitted) setTimeout(fitView, 240);
  });
  // the fog drawer (issue #137)
  $("fog-badge").addEventListener("click", (event) => {
    event.preventDefault();
    if (document.body.dataset.page !== "map") { fog.open = true; location.hash = "#/"; route().catch(showError); return; }  // the drawer lives on the map
    fog.open = !fog.open;
    showFog();
  });
  $("fog-close").addEventListener("click", () => { fog.open = false; showFog(); });
  $("fog-show-all").addEventListener("change", () => { fog.showAll = $("fog-show-all").checked; loadFog().catch(showError); });
  $("fog-add").addEventListener("click", () => addFog().catch(showError));
  $("fog-add-text").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); addFog().catch(showError); } });
  $("fog-composer").addEventListener("submit", (event) => event.preventDefault());
  $("manage-rules").addEventListener("click", (event) => { event.preventDefault(); openRulesSheet().catch(showError); });
  $("rule-cancel").addEventListener("click", () => { $("rules-sheet").hidden = true; });
  $("rule-new").addEventListener("click", () => ruleForm("declare"));
  $("rule-record").addEventListener("click", () => recordRule());
  $("rule-form").addEventListener("submit", (event) => event.preventDefault());  // Enter in a field never reloads the page
  for (const id of ["cond-reviewed", "cond-doi", "cond-arxiv", "cond-types", "rule-name"]) $(id).addEventListener("change", () => ruleFormChanged());
  $("view-dag").addEventListener("click", () => { mapView = "dag"; showMap(); });
  $("view-tree").addEventListener("click", () => { mapView = "tree"; showMap(); });
  $("tree-root").addEventListener("change", showMap);
  window.addEventListener("hashchange", route);
  refresh().catch((error) => say(error.message, "error"));
});
