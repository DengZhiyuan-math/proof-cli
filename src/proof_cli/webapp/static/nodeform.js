// The map's node form (issue #154; ADR-0008, ADR-0011): right-click the canvas or a card (a long press on
// touch) for a menu, and the form opens in place as a popover, a bottom sheet on a narrow window, with a
// dashed ghost card where the new node will land. Its fields are `proof node create`'s, and the equivalent
// command is shown under it. The server is the source of truth: the form's own checks only say early what
// the server would refuse, in its words and codes. Double-click still zooms; nothing here takes it.
// Uses app.js's helpers ($, el, svg, api, say, showError, withMath, citationBlock, statusChips,
// pageOf, positions, view, BOX, KIND_LABEL, mapData, state, mapView, refresh). A node's status is always the
// server's `status` from /api/map, never worked out here. Text is inserted as text.
// The fog drawer's Crystallize… opens the same form (issue #155, ADR-0008): a Claim, posted to the
// crystallize service, with `proof fog crystallize …` as its command and the item's text shown above it.
"use strict";

const NF_SAFE_NODE_ID = /^[A-Za-z0-9_-][A-Za-z0-9._-]*$/;
const NF_RESERVED = ["trust-rules.jsonl", "preamble.tex", "fog"];  // the vault's own names (proof_map._RESERVED_NODE_IDS)
const NF_KINDS = ["theorem", "lemma", "claim", "imported_result"];
const NF_TRUST_LEVELS = ["foundational", "project_verified", "external_reference", "temporary_admit"];  // TrustLevel
const NF_SOURCE_TYPES = ["standard_reference", "research_paper", "textbook", "survey", "monograph", "website", "other"];  // ReferenceSourceType
const NF_LONG_PRESS_MS = 550;
const NF_NO_PARENT = ":none";  // a crystallize's "None: free-standing" (--no-parent); ':' is never in a node id
const NF_IMMUTABLE = "The citation is fixed once the node exists (reference_id, ADR-0012). Its Reference review binds the id, not the entry's text. To cite a different source, create a new imported result and move its dependents onto it.";

const nf = {
  F: null,        // the form's state while it is open
  initial: "",    // what it opened with: "unsaved input" is anything since
  ghost: null,    // where the new card lands, in the scene's coordinates
  anchor: null,   // where the menu was asked for, in the stage's
  ui: null,       // the popover's elements, built once
  menu: null,
  refs: { references: [], source_types: NF_SOURCE_TYPES },
  press: null,    // a touch held on the canvas, for the long-press menu
  longPressAt: 0, // when a long press last opened the menu
};

function nfBlank() {
  return {
    id: "", label: "", kind: "claim", statement: "", assumptions: [], medium: "latex", deps: [], depFind: "",
    parent: "", parentMode: "rests", reassign: false, locator: "", version: "", trust: "", refId: "", refFind: "", newRef: null,
    touched: new Set(), submitted: false, busy: false, refusal: "",
    fog: null,        // a crystallize: {id, text, near} of the fog item, from the drawer (#155)
    noParent: false,  // a crystallize's explicit none (--no-parent); no parent and not this is the CLI's default
  };
}

const nfNodes = () => (mapData ? mapData.nodes : []);
const nfNode = (id) => nfNodes().find((n) => n.id === id) || null;
const nfMe = () => (state ? state.reviewer : "");
const nfLocal = () => nf.F.kind !== "imported_result";
const nfSplit = () => !!nf.F.parent && nf.F.parentMode === "split";
const nfAssumptions = () => nf.F.assumptions.filter((a) => a.trim());
const nfNarrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 760px)").matches;
const nfAuthors = (text) => String(text || "").split(/[;\n]/).map((a) => a.trim()).filter(Boolean);
const nfFog = () => nf.F.fog;
const nfData = (F) => JSON.stringify([F.id, F.label, F.kind, F.statement, F.assumptions, F.medium, F.deps, F.parent, F.parentMode, F.reassign, F.locator, F.version, F.trust, F.refId, F.newRef, F.noParent]);
const nfDirty = () => !!nf.F && nfData(nf.F) !== nf.initial;

// A Python str's repr, as the server's messages quote a node id ({node_id!r})
function nfRepr(s) {
  const body = s.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t");
  return s.includes("'") && !s.includes('"') ? `"${body}"` : `'${body.replace(/'/g, "\\'")}'`;
}

// a chain of dependency edges from `start` down to `goal`, breadth-first as proof_map._dependency_path walks it
function nfPath(start, goal) {
  const cameFrom = new Map([[start, null]]);
  const pending = [start];
  while (pending.length) {
    const current = pending.shift();
    if (current === goal) {
      const path = [current];
      while (cameFrom.get(path[path.length - 1]) !== null) path.push(cameFrom.get(path[path.length - 1]));
      return path.reverse();
    }
    for (const d of (nfNode(current) || { dependencies: [] }).dependencies) if (!cameFrom.has(d)) { cameFrom.set(d, current); pending.push(d); }
  }
  return null;
}

// -- what the server would refuse, in the order it checks, with its codes and words -----------------
// (webapp/server.py create_node and the split action, proof_map.create_node, create_node_under_parent,
// _split and _structure_editable; a new reference's import first, as the page posts it first)
function nfValidate() {
  const F = nf.F, errs = [];
  const add = (f, code, message) => errs.push({ f, code, message });
  if (!nfLocal() && F.newRef) {
    const r = F.newRef, year = r.year.trim();
    if (!r.id.trim() || !r.title.trim() || !year) add("ref", "INVALID_INPUT", "a reference needs reference_id, title and year");
    else if (!/^-?[0-9]+$/.test(year)) add("ref", "INVALID_INPUT", "a reference's year is a whole number");
    else if (nf.refs.references.some((x) => x.id === r.id.trim())) add("ref", "INVALID_INPUT", `reference ${r.id.trim()} already exists; import the new record under a new id`);
  }
  const id = F.id.trim();
  const idProblems = () => {
    if (!NF_SAFE_NODE_ID.test(id)) add("id", "INVALID_NODE_ID", `node id ${nfRepr(id)} must be letters, digits, '.', '_' or '-', not starting with '.'`);
    else if (NF_RESERVED.includes(id.toLowerCase())) add("id", "INVALID_NODE_ID", `node id ${nfRepr(id)} is the name of one of the vault's own files or folders (proofs/${id.toLowerCase()}), in any letter case`);
    else if (nfNode(id)) add("id", "NODE_ALREADY_EXISTS", `proof map node ${id} already exists`);
  };
  const parent = F.parent ? nfNode(F.parent) : null;
  const heldByAnother = parent && parent.assignee && parent.assignee !== nfMe() && !F.reassign;
  const fog = nfFog();
  if (fog) {
    // fog.crystallize_fog's own checks first (the item's parent, then the statement); with a parent the
    // rest is a single-child Split's, below, and with none a Claim's create (#155)
    if (!F.parent && !F.noParent && fog.near.length > 1) {
      add("parent", "FOG_PARENT_AMBIGUOUS", `${fog.id} is near ${fog.near.length} nodes (${fog.near.join(", ")}); say which is the parent with --parent, or --no-parent for none`);
    } else if (!F.statement.trim()) add("statement", "FOG_STATEMENT_REQUIRED", `crystallizing ${fog.id} needs the Claim's statement, written now; the item's text is never copied`);
    if (errs.length) return errs;
    if (!nfSplit()) { idProblems(); return errs; }
  }
  if (nfSplit()) {
    if (!fog && (!id || !F.statement)) { add(id ? "statement" : "id", "INVALID_CHILD_SPEC", "each child needs an id and a statement"); return errs; }
    if (!parent) add("parent", "NODE_NOT_FOUND", `proof map node ${F.parent} not found`);
    else if (parent.kind === "imported_result") add("parent", "IMMUTABLE_NODE", `imported_result node ${parent.id} cannot be split`);
    else if (parent.acceptance_state === "rejected") add("parent", "NODE_REJECTED", `node ${parent.id} was Rejected and should not be pursued further; split is unavailable`);
    else if (["accepted", "unverifiable"].includes(parent.acceptance_state)) add("parent", "NODE_ACCEPTED", `node ${parent.id} is ${parent.acceptance_state}; splitting it would void that decision, so split is unavailable`);
    else if (heldByAnother) add("parent", "NOT_CLAIMANT", `${parent.id} is claimed by ${parent.assignee}`);
    if (errs.length) return errs;
    for (const d of F.deps) {
      const path = nfNode(d) ? nfPath(d, parent.id) : null;
      if (path) { add("deps", "DEPENDENCY_CYCLE", `${id} can't rest on ${d}: ${[id, ...path, id].join(" → ")} would be a cycle`); return errs; }
    }
    idProblems();
    return errs;
  }
  if (!id || !F.statement.trim()) add(id ? "statement" : "id", "INVALID_REQUEST", "a node needs node_id, kind and statement");
  if (errs.length) return errs;
  idProblems();
  if (!nfLocal() && F.deps.length) add("deps", "IMPORTED_RESULT_HAS_NO_DEPENDENCIES", "an imported_result is established elsewhere, so nothing in this map is a premise of it");
  if (!nfLocal() && (!F.locator.trim() || !F.version.trim())) add(F.locator.trim() ? "version" : "locator", "IMPORTED_RESULT_REQUIRES_SOURCE", "an imported_result node requires both a source_locator and a source_version");
  if (F.kind === "theorem" && nfNodes().some((n) => n.kind === "theorem")) add("kind", "DUPLICATE_THEOREM", "a theorem-kind node already exists for this project; only one is allowed");
  if (errs.length || !F.parent) return errs;
  // the parent rests on it (proof_map.create_node_under_parent: add_dependency's checks, in its order)
  if (!parent) add("parent", "NODE_NOT_FOUND", `proof map node ${F.parent} not found`);
  else if (parent.kind === "imported_result") add("parent", "IMPORTED_RESULT_HAS_NO_DEPENDENCIES", `${parent.id} is an imported_result, established elsewhere: nothing in this map is a premise of it`);
  else if (parent.acceptance_state === "rejected") add("parent", "NODE_REJECTED", `node ${parent.id} was Rejected and should not be pursued further; its dependencies stay as they were`);
  // an open Challenge on it allows the edit: the map can't tell its own from one upstream, so the server decides
  else if (["accepted", "unverifiable"].includes(parent.acceptance_state) && parent.integrity_state !== "challenged") {
    add("parent", "NODE_ACCEPTED", `node ${parent.id} is ${parent.acceptance_state}; changing its dependencies would void that decision, so open a Challenge before revising it`);
  }
  if (errs.length) return errs;
  for (const d of F.deps) {
    const path = nfPath(d, parent.id);
    if (path) { add("deps", "DEPENDENCY_CYCLE", `${parent.id} can't rest on ${id}: ${[parent.id, id, ...path].join(" → ")} would be a cycle`); return errs; }
  }
  if (heldByAnother) add("parent", "NOT_CLAIMANT", `${parent.id} is claimed by ${parent.assignee}`);
  return errs;
}

// -- the equivalent CLI: what to run for the same result ---------------------------------------
function nfQuote(s) { s = String(s); return /^[A-Za-z0-9_\-.\/:@+,=]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`; }

function nfCliLines() {
  const F = nf.F, out = [];
  const id = F.id.trim() || "<node-id>";
  const statement = F.statement || "<statement>";
  const command = (parts) => out.push(parts.join(" \\\n    "));
  const fog = nfFog();
  if (fog) {  // one command, one transaction: the Claim, its Split of the parent, the item's record
    const parts = [`proof fog crystallize ${nfQuote(fog.id)} ${nfQuote(id)} ${nfQuote(statement)}`];
    if (F.parent) parts.push(`--parent ${nfQuote(F.parent)}`);
    else if (F.noParent && fog.near.length) parts.push("--no-parent");
    for (const a of nfAssumptions()) parts.push(`--assumption ${nfQuote(a)}`);
    if (F.label.trim()) parts.push(`--display-label ${nfQuote(F.label.trim())}`);
    if (F.parent && F.reassign) parts.push("--reassign");
    if (F.medium === "computation") parts.push("--medium computation");
    command(parts);
    return out;
  }
  if (!nfLocal() && F.newRef) {
    const r = F.newRef;
    const parts = [`proof reference import ${nfQuote(r.id.trim() || "<reference-id>")} ${nfQuote(r.title.trim() || "<title>")} ${nfQuote(r.year.trim() || "<year>")}`];
    for (const author of nfAuthors(r.authors)) parts.push(`--author ${nfQuote(author)}`);
    if (r.source_type && r.source_type !== "other") parts.push(`--source-type ${r.source_type}`);
    if (r.identifier.trim()) parts.push(`--identifier ${nfQuote(r.identifier.trim())}`);
    if (r.url.trim()) parts.push(`--url ${nfQuote(r.url.trim())}`);
    command(parts);
  }
  if (nfSplit()) {
    const parts = [`proof node split ${nfQuote(F.parent)}`, `--child ${nfQuote(`${id}=${statement}`)}`];
    for (const a of nfAssumptions()) parts.push(`--assumption ${nfQuote(a)}`);
    if (F.label.trim()) parts.push(`--display-label ${nfQuote(F.label.trim())}`);
    if (F.reassign) parts.push("--reassign");
    command(parts);
    for (const d of F.deps) command([`proof node depend ${nfQuote(id)} --add ${nfQuote(d)}`]);
    if (F.medium === "computation") command([`proof node medium set ${nfQuote(id)} computation`]);
  } else {
    const parts = [`proof node create ${nfQuote(id)} ${F.kind} ${nfQuote(statement)}`];
    if (F.label.trim()) parts.push(`--display-label ${nfQuote(F.label.trim())}`);
    for (const a of nfAssumptions()) parts.push(`--assumption ${nfQuote(a)}`);
    for (const d of F.deps) parts.push(`--dependency ${nfQuote(d)}`);
    if (nfLocal()) { if (F.medium === "computation") parts.push("--medium computation"); }
    else {
      parts.push(`--source-locator ${nfQuote(F.locator.trim() || "<locator>")}`, `--source-version ${nfQuote(F.version.trim() || "<version>")}`);
      if (F.trust) parts.push(`--trust-level ${F.trust}`);
      const rid = F.newRef ? F.newRef.id.trim() : F.refId;
      if (rid) parts.push(`--reference-id ${nfQuote(rid)}`);
    }
    if (F.parent) parts.push(`--parent ${nfQuote(F.parent)}`, ...(F.reassign ? ["--reassign"] : []));
    command(parts);
  }
  return out;
}

// -- what the page posts --------------------------------------------------------------------
function nfNodeBody() {
  const F = nf.F;
  const body = { node_id: F.id.trim(), kind: F.kind, statement: F.statement, display_label: F.label.trim(), assumptions: nfAssumptions(), dependencies: [...F.deps] };
  if (nfLocal()) body.medium = F.medium;
  else Object.assign(body, { source_locator: F.locator.trim(), source_version: F.version.trim(), trust_level: F.trust || null, reference_id: F.refId || null });
  if (F.parent) body.parent = { id: F.parent, reassign: F.reassign };
  return body;
}

function nfSplitBody() {
  const F = nf.F;
  return { children: [{ id: F.id.trim(), statement: F.statement, display_label: F.label.trim(), assumptions: nfAssumptions(), dependencies: [...F.deps], medium: F.medium }], reassign: F.reassign };
}

// a crystallize (#155): no parent and no no_parent is the CLI's default, the item's one near node
function nfCrystallizeBody() {
  const F = nf.F;
  return {
    node_id: F.id.trim(), statement: F.statement, display_label: F.label.trim(), assumptions: nfAssumptions(), medium: F.medium,
    parent: F.parent || null, no_parent: !F.parent && F.noParent, reassign: !!F.parent && F.reassign,
  };
}

async function nfSubmit() {
  const F = nf.F;
  if (!F || F.busy) return;
  F.submitted = true;
  F.refusal = "";
  nfUpdate();
  if (nfValidate().length) return;
  F.busy = true;
  nfUpdate();
  const id = F.id.trim();
  try {
    if (!nfLocal() && F.newRef) {  // the citation first; it stays if the node is then refused (it is only a citation)
      const r = F.newRef;
      const made = await api("/api/references", {
        reference_id: r.id.trim(), title: r.title.trim(), year: r.year.trim(), authors: nfAuthors(r.authors),
        source_type: r.source_type, identifier: r.identifier.trim(), url: r.url.trim(),
      });
      nf.refs.references.push({ ...made, cited_by: [] });
      F.refId = made.id;
      F.newRef = null;
    }
    let page, done = `Created ${id}.`;
    if (F.fog) {  // the crystallize service, never a plain create: the item reads crystallized and names the Claim
      const made = await api(`/api/fog/${encodeURIComponent(F.fog.id)}/crystallize`, nfCrystallizeBody());
      page = made.page;
      done = `Crystallized ${F.fog.id} as ${id}.${made.reminder ? ` ${made.reminder}` : ""}`;
    } else {
      page = nfSplit()
        ? (await api(`/api/node/${encodeURIComponent(F.parent)}/split`, nfSplitBody())).next
        : (await api("/api/nodes", nfNodeBody())).page;
    }
    if (nf.ghost) { const saved = positions.load(); saved[id] = { x: nf.ghost.x, y: nf.ghost.y }; positions.save(saved); }  // where the ghost stood
    nfClose();
    say(done, "ok");
    try { await refresh(); } catch (error) { showError(error); }
    location.href = page || `#/node/${encodeURIComponent(id)}`;
  } catch (error) {
    F.busy = false;
    F.refusal = error.code ? `${error.code}: ${error.message}` : error.message;
    showError(error);
    nfUpdate();
  }
}

// -- building the popover -----------------------------------------------------------------------
function nfField(f, label, hint) {
  const box = el("div", null, { class: "nf-field", "data-f": f || "" });
  const head = el("span", label, { class: "nf-lbl" });
  if (hint) head.append(" ", el("span", hint, { class: "nf-opt" }));
  box.append(head);
  return box;
}

function nfInput(name, attrs = {}, multiline = false) {
  return el(multiline ? "textarea" : "input", null, { name, autocomplete: "off", spellcheck: "false", ...(multiline ? { rows: 3 } : { type: "text" }), ...attrs });
}

function nfSeg(name, values, labels) {
  const seg = el("div", null, { class: "nf-seg", role: "group", "data-seg": name });
  for (const value of values) seg.append(el("button", labels[value] || value, { type: "button", [`data-${name}`]: value, "aria-pressed": "false" }));
  return seg;
}

function nfBuild() {
  const ui = {};
  const pop = el("div", null, { class: "node-pop", id: "node-pop", role: "dialog", "aria-label": "New node" });
  pop.hidden = true;
  const head = el("div", null, { class: "nf-head" });
  ui.title = el("h2", "New node");
  ui.close = el("button", "×", { type: "button", class: "close", "aria-label": "Close" });
  head.append(ui.title, ui.close);
  const form = el("form", null, { class: "nf", novalidate: "", autocomplete: "off" });
  ui.err = {};
  const err = (f) => { ui.err[f] = el("p", null, { class: "nf-err" }); return ui.err[f]; };

  // a crystallize's fog item, for reference: its text is an idea, never copied into the statement (#155)
  ui.fog = el("div", null, { class: "nf-fog" });
  ui.fogHead = el("span", null, { class: "nf-lbl" });
  ui.fogText = el("p", null, { class: "fog-text" });
  ui.fog.append(ui.fogHead, ui.fogText, el("p", "For reference: write the Claim's statement below; the item's text is never copied.", { class: "hint" }));

  const idBox = nfField("id", "Node id", "its folder: proofs/<id>/");
  ui.id = nfInput("nf-id", { class: "mono", placeholder: "lem-chain" });
  idBox.append(ui.id, err("id"));
  const labelBox = nfField("", "Display label", "optional, on the card");
  ui.label = nfInput("nf-label", { placeholder: "Chaining lemma" });
  labelBox.append(ui.label);

  const kindBox = nfField("kind", "Kind");
  ui.kind = nfSeg("kind", NF_KINDS, KIND_LABEL);
  ui.kindHint = el("p", null, { class: "hint" });
  kindBox.append(ui.kind, ui.kindHint, err("kind"));

  const stBox = nfField("statement", "Statement", "LaTeX: $…$ inline, $$…$$ display · fixed once created");
  ui.statement = nfInput("nf-statement", { class: "tex", placeholder: "For every $u$ …" }, true);
  ui.statementPreview = el("div", null, { class: "nf-preview" });
  stBox.append(ui.statement, ui.statementPreview, err("statement"));

  const asBox = nfField("", "Assumptions", "each one a hypothesis; fixed once created");
  ui.assumptions = el("div", null, { class: "nf-assumptions" });
  ui.addAssumption = el("button", "+ Assumption", { type: "button", class: "small" });
  asBox.append(ui.assumptions, ui.addAssumption);

  ui.mediumBox = nfField("", "Medium", "what its candidate proof is made of; changeable later");
  ui.medium = nfSeg("medium", ["latex", "computation"], { latex: "LaTeX", computation: "Computation" });
  ui.mediumBox.append(ui.medium);

  ui.depsBox = nfField("deps", "Dependencies", "pinned at its first review request, not now");
  ui.depChips = el("div", null, { class: "nf-chips" });
  ui.depFind = nfInput("nf-deps-find", { type: "search", placeholder: "Search nodes by id, label or statement" });
  ui.depList = el("ul", null, { class: "nf-picklist" });
  ui.depsBox.append(ui.depChips, ui.depFind, ui.depList, err("deps"));

  const parentBox = nfField("parent", "Parent", "optional: the node it hangs under");
  ui.parent = el("select", null, { name: "nf-parent" });
  ui.parentMode = el("div", null, { class: "nf-radios" });
  const radio = (value, text) => {
    const label = el("label");
    const input = el("input", null, { type: "radio", name: "nf-parent-mode", value });
    label.append(input, el("span", text));
    ui.parentMode.append(label);
    return { label, input };
  };
  ui.modeSplit = radio("split", "A Split of the parent: a new Claim derived from it, which it rests on (node split)");
  ui.modeRests = radio("rests", "The parent rests on it: any kind, added to the parent's dependencies (node create --parent)");
  ui.reassignLabel = el("label", null, { class: "nf-reassign" });
  ui.reassign = el("input", null, { type: "checkbox", name: "nf-reassign" });
  ui.reassignText = el("span", "Take the claim over (--reassign)");
  ui.reassignLabel.append(ui.reassign, ui.reassignText);
  parentBox.append(ui.parent, ui.parentMode, ui.reassignLabel, err("parent"));

  // an imported result's source
  ui.source = el("fieldset", null, { class: "nf-source" });
  ui.source.append(el("legend", "Source"));
  const refBox = nfField("ref", "Citation", "a reference list entry; optional");
  ui.refSelected = el("div");
  ui.refFind = nfInput("nf-ref-find", { type: "search", placeholder: "Search title, author or identifier" });
  ui.refList = el("ul", null, { class: "nf-picklist" });
  ui.refNewButton = el("button", "+ New reference…", { type: "button", class: "small" });
  ui.refNew = el("div", null, { class: "nf-ref-new" });
  ui.refInputs = {};
  const refField = (key, text, attrs) => {
    const label = el("label", text);
    const input = key === "source_type" ? el("select", null, { name: "ref-source_type" }) : nfInput(`ref-${key}`, attrs);
    if (key === "source_type") for (const t of NF_SOURCE_TYPES) input.append(el("option", t, { value: t }));
    ui.refInputs[key] = input;
    label.append(input);
    return label;
  };
  const row3 = el("div", null, { class: "nf-row3" });
  row3.append(refField("id", "reference id", { class: "mono", placeholder: "rudin-1976" }), refField("year", "year", { inputmode: "numeric", placeholder: "1976" }), refField("source_type", "source type"));
  ui.refNewCancel = el("button", "Cancel", { type: "button", class: "small" });
  ui.refNew.append(row3, refField("title", "title", { placeholder: "Principles of Mathematical Analysis" }),
    refField("authors", "authors, ;-separated", { placeholder: "Walter Rudin" }),
    refField("identifier", "identifier (DOI, arXiv, ISBN…)", { class: "mono", placeholder: "doi:…" }),
    refField("url", "url", { class: "mono", placeholder: "https://…" }), ui.refNewCancel);
  ui.immutable = el("p", NF_IMMUTABLE, { class: "nf-immutable" });
  refBox.append(ui.refSelected, ui.refFind, ui.refList, ui.refNewButton, ui.refNew, err("ref"), ui.immutable);
  const locBox = nfField("locator", "source_locator", "where in the source: a theorem, a page");
  ui.locator = nfInput("nf-locator", { placeholder: "Thm 3.6" });
  locBox.append(ui.locator, err("locator"));
  const verBox = nfField("version", "source_version", "the edition or version cited");
  ui.version = nfInput("nf-version", { placeholder: "3rd ed., 1976" });
  verBox.append(ui.version, err("version"));
  ui.suggest = el("p", null, { class: "nf-suggest" });
  const trustBox = nfField("", "Trust level", "optional");
  ui.trust = el("select", null, { name: "nf-trust" });
  ui.trust.append(el("option", "(none)", { value: "" }), ...NF_TRUST_LEVELS.map((t) => el("option", t, { value: t })));
  trustBox.append(ui.trust, el("p", "Only recorded: whether it can be called is decided by its Reference review or a Trust rule, and a Trust rule never reads it (ADR-0014).", { class: "hint" }));
  ui.source.append(refBox, locBox, verBox, ui.suggest, trustBox);

  ui.refusal = el("p", null, { class: "nf-refusal", role: "status" });
  const cli = el("div", null, { class: "nf-cli-box" });
  const cliHead = el("div", null, { class: "nf-lbl nf-cli-head" });
  ui.copy = el("button", "Copy", { type: "button", class: "small" });
  cliHead.append(el("span", "Equivalent CLI"), ui.copy);
  ui.cliNote = el("p", null, { class: "hint nf-cli-note" });
  ui.cli = el("pre", null, { class: "nf-cli" });
  cli.append(cliHead, ui.cliNote, ui.cli);
  const foot = el("div", null, { class: "sheet-foot" });
  ui.cancel = el("button", "Cancel", { type: "button" });
  ui.submit = el("button", "Create", { type: "submit", class: "primary" });
  foot.append(ui.cancel, ui.submit);

  form.append(ui.fog, idBox, labelBox, kindBox, stBox, asBox, ui.mediumBox, ui.depsBox, parentBox, ui.source, ui.refusal, cli, foot);
  pop.append(head, form);
  ui.pop = pop;
  ui.form = form;
  nfWire(ui);
  return ui;
}

function nfWire(ui) {
  const F = () => nf.F;
  const bind = (input, key, field) => input.addEventListener("input", () => { F()[key] = input.value; F().touched.add(field || key); nfUpdate(); });
  bind(ui.id, "id"); bind(ui.label, "label"); bind(ui.statement, "statement"); bind(ui.locator, "locator"); bind(ui.version, "version");
  ui.trust.addEventListener("change", () => { F().trust = ui.trust.value; nfUpdate(); });
  ui.kind.addEventListener("click", (event) => {
    const button = event.target.closest ? event.target.closest("button") : null;
    if (!button || button.disabled) return;
    F().kind = button.getAttribute("data-kind");
    F().touched.add("kind");
    if (!nfLocal() && F().parentMode === "split") F().parentMode = "rests";  // an imported result is never a split child
    nfUpdate();
  });
  ui.medium.addEventListener("click", (event) => {
    const button = event.target.closest ? event.target.closest("button") : null;
    if (button) { F().medium = button.getAttribute("data-medium"); nfUpdate(); }
  });
  ui.addAssumption.addEventListener("click", () => { F().assumptions.push(""); nfAssumptionRows(true); nfUpdate(); });
  ui.depFind.addEventListener("input", () => { F().depFind = ui.depFind.value; nfDeps(); });
  ui.parent.addEventListener("change", () => {
    F().noParent = ui.parent.value === NF_NO_PARENT;
    F().parent = F().noParent ? "" : ui.parent.value;
    F().reassign = false;
    F().touched.add("parent");
    nfUpdate();
  });
  for (const { input } of [ui.modeSplit, ui.modeRests]) {
    input.addEventListener("change", () => { F().parentMode = input.value; if (nfSplit()) F().kind = "claim"; nfUpdate(); });
  }
  ui.reassign.addEventListener("change", () => { F().reassign = !!ui.reassign.checked; nfUpdate(); });
  ui.refFind.addEventListener("input", () => { F().refFind = ui.refFind.value; nfRefs(); });
  ui.refNewButton.addEventListener("click", () => {
    F().newRef = { id: "", year: "", title: F().refFind && !/^\d/.test(F().refFind) ? F().refFind : "", authors: "", source_type: "other", identifier: "", url: "" };
    F().refId = "";
    nfSyncNewRef();
    nfUpdate();
    setTimeout(() => ui.refInputs.id.focus(), 0);
  });
  ui.refNewCancel.addEventListener("click", () => { F().newRef = null; nfUpdate(); });
  for (const [key, input] of Object.entries(ui.refInputs)) {
    input.addEventListener(key === "source_type" ? "change" : "input", () => { if (F().newRef) { F().newRef[key] = input.value; F().touched.add("ref"); nfUpdate(); } });
  }
  ui.copy.addEventListener("click", async () => {
    const text = nfCliLines().join("\n");
    try { await navigator.clipboard.writeText(text); say("Copied the command.", "ok"); } catch { say("Select the command and copy it.", "error"); }
  });
  ui.close.addEventListener("click", () => nfClose());
  ui.cancel.addEventListener("click", () => nfClose());
  ui.form.addEventListener("submit", (event) => { event.preventDefault(); nfSubmit(); });
  ui.pop.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); nfClose(); }
    else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); nfSubmit(); }
    // Enter in a one-line field (a search box, say) never creates the node: Create, or ⌘/Ctrl+Enter, does
    else if (event.key === "Enter" && event.target && event.target.tagName === "INPUT") event.preventDefault();
    event.stopPropagation();  // the map's own keys (/ finds, F fits) never fire from inside the form
  });
}

// -- keeping it current ------------------------------------------------------------------------
function nfSyncInputs() {
  const F = nf.F, ui = nf.ui;
  ui.id.value = F.id; ui.label.value = F.label; ui.statement.value = F.statement; ui.locator.value = F.locator; ui.version.value = F.version;
  ui.trust.value = F.trust; ui.depFind.value = F.depFind; ui.refFind.value = F.refFind;
  nfAssumptionRows(false);
  nfSyncNewRef();
}

function nfSyncNewRef() {
  if (!nf.F.newRef) return;
  for (const [key, input] of Object.entries(nf.ui.refInputs)) input.value = nf.F.newRef[key] || "";
}

const nfPreview = (node, text) => { node.replaceChildren(); return withMath(node, text); };

function nfAssumptionRows(focusLast) {
  const F = nf.F, box = nf.ui.assumptions;
  box.replaceChildren();
  F.assumptions.forEach((text, i) => {
    const row = el("div", null, { class: "nf-assumption" });
    const input = nfInput(`nf-assumption-${i}`, { class: "mono", placeholder: "$u \\ge 0$" });
    input.value = text;
    const preview = el("div", null, { class: "nf-preview" });
    input.addEventListener("input", () => { F.assumptions[i] = input.value; nfPreview(preview, input.value); nfUpdate(); });
    const remove = el("button", "−", { type: "button", "aria-label": "Remove this assumption" });
    remove.addEventListener("click", () => { F.assumptions.splice(i, 1); nfAssumptionRows(false); nfUpdate(); });
    row.append(input, remove, preview);
    nfPreview(preview, text);
    box.append(row);
    if (focusLast && i === F.assumptions.length - 1) setTimeout(() => input.focus(), 0);
  });
}

// `text` with the first match of `query` marked, as text
function nfMarked(text, query) {
  const span = el("span");
  const q = query.trim().toLowerCase(), at = q ? String(text).toLowerCase().indexOf(q) : -1;
  if (at < 0) { span.textContent = String(text); return span; }
  span.append(String(text).slice(0, at), el("mark", String(text).slice(at, at + q.length)), String(text).slice(at + q.length));
  return span;
}

// a node's status as the server sends it with the map (webapp/node_status.py, issue #157), drawn with
// status.js's icons through app.js's statusChips: the same chips as the tree and the node page
const nfStatusChips = (n) => (n.status ? statusChips(n.status, n.frontier) : []);

function nfDeps() {
  const F = nf.F, ui = nf.ui;
  const q = F.depFind.trim().toLowerCase();
  const pool = nfNodes().filter((n) => !q || [n.id, n.display_label || "", n.statement || ""].some((t) => t.toLowerCase().includes(q)));
  ui.depList.replaceChildren(...pool.map((n) => {
    const li = el("li", null, { class: F.deps.includes(n.id) ? "on" : "", "data-dep": n.id });
    li.append(nfMarked(n.id, F.depFind), nfMarked(n.display_label || n.statement, F.depFind), ...nfStatusChips(n));
    li.children[0].setAttribute("class", "nf-pid");
    li.children[1].setAttribute("class", "nf-pst");
    li.addEventListener("click", () => nfToggleDep(n.id));
    return li;
  }));
  if (!pool.length) ui.depList.append(el("li", nfNodes().length ? "No node has that id, label or statement." : "The map is empty: nothing to depend on yet.", { class: "none" }));
  ui.depChips.replaceChildren(...F.deps.map((d) => {
    const chip = el("span", d, { class: "nf-dep-chip", "data-chip": d });
    const remove = el("button", "×", { type: "button", "aria-label": `Remove ${d}` });
    remove.addEventListener("click", () => nfToggleDep(d));
    chip.append(remove);
    return chip;
  }));
}

function nfToggleDep(id) {
  const F = nf.F;
  F.deps = F.deps.includes(id) ? F.deps.filter((d) => d !== id) : [...F.deps, id];
  F.touched.add("deps");
  nfUpdate();
}

const nfRefMatches = (r, q) => [r.title, (r.authors || []).join(" "), r.identifier || "", r.id].join(" ").toLowerCase().includes(q);

function nfRefs() {
  const F = nf.F, ui = nf.ui;
  const q = F.refFind.trim().toLowerCase();
  const pool = nf.refs.references.filter((r) => !q || nfRefMatches(r, q));
  ui.refList.replaceChildren(...pool.map((r) => {
    const li = el("li", null, { class: F.refId === r.id && !F.newRef ? "on" : "", "data-ref": r.id });
    const box = el("div", null, { class: "nf-ref" });
    const meta = el("span");
    meta.append(nfMarked((r.authors || []).join(", ") || "no authors listed", F.refFind), ` · ${r.year} · `, nfMarked(r.identifier || r.id, F.refFind));
    box.append(nfMarked(r.title, F.refFind), meta);
    box.children[0].setAttribute("class", "nf-ref-title");
    // the imported results that already cite it: its id, the version it cites, its Reference review state
    if ((r.cited_by || []).length) box.append(el("span", `cited by ${r.cited_by.map((c) => `${c.id} (${c.source_version}, ${c.acceptance_state})`).join(", ")}`));
    li.append(box, el("span", r.source_type, { class: "nf-pid" }));
    li.addEventListener("click", () => { F.refId = F.refId === r.id ? "" : r.id; F.newRef = null; F.touched.add("ref"); nfUpdate(); });
    return li;
  }));
  if (!pool.length) ui.refList.append(el("li", nf.refs.references.length ? `No reference matches “${F.refFind}”.` : "No reference yet: add one with + New reference….", { class: "none" }));
  // the chosen citation as the node's page will show it; never its legacy review fields (ADR-0012)
  const chosen = F.newRef ? { ...F.newRef, id: F.newRef.id.trim(), authors: nfAuthors(F.newRef.authors), year: F.newRef.year.trim() } : nf.refs.references.find((r) => r.id === F.refId);
  ui.refSelected.replaceChildren();
  if (chosen && (chosen.id || chosen.title)) {
    ui.refSelected.append(citationBlock({
      reference_id: chosen.id || "<reference-id>", missing: false, title: chosen.title || "(untitled)", authors: chosen.authors || [], year: chosen.year,
      identifier: chosen.identifier, url: chosen.url, locator: F.locator.trim() || "<locator>", version: F.version.trim() || "<version>",
    }));
    if (F.newRef) ui.refSelected.append(el("p", "New: imported first (proof reference import), then linked.", { class: "hint" }));
  }
  ui.refList.hidden = !!F.newRef; ui.refFind.hidden = !!F.newRef; ui.refNewButton.hidden = !!F.newRef; ui.refNew.hidden = !F.newRef;
  // a suggestion, never filled in for you: the locator names a place in the source, not the book
  const picked = !F.newRef ? nf.refs.references.find((r) => r.id === F.refId) : null;
  ui.suggest.replaceChildren();
  ui.suggest.hidden = !(picked && (!F.locator || !F.version));
  if (!ui.suggest.hidden) {
    ui.suggest.append(`From ${picked.id}:`);
    if (!F.locator) {
      const stem = `${(picked.authors || []).map((a) => a.split(" ").pop()).join("–") || picked.title} ${picked.year}, `;
      const b = el("button", `locator “${stem}…”`, { type: "button", class: "small", "data-suggest": "locator" });
      b.addEventListener("click", () => { F.locator = stem; nf.ui.locator.value = stem; nfUpdate(); nf.ui.locator.focus(); });
      ui.suggest.append(" ", b);
    }
    if (!F.version) {
      const b = el("button", `version “${picked.year}”`, { type: "button", class: "small", "data-suggest": "version" });
      b.addEventListener("click", () => { F.version = String(picked.year); nf.ui.version.value = F.version; nfUpdate(); });
      ui.suggest.append(" ", b);
    }
  }
}

function nfParent() {
  const F = nf.F, ui = nf.ui;
  const fog = nfFog();
  const nodes = nfNodes().map((n) => el("option", `${n.id} · ${KIND_LABEL[n.kind] || n.kind}${n.status ? `, ${n.status.text}` : ""}`, { value: n.id }));
  if (fog) {
    // near several nodes: unset until the researcher says which, or none (the CLI refuses to guess either)
    const unset = fog.near.length > 1 ? [el("option", `Choose: it is near ${fog.near.join(", ")}`, { value: "" })] : [];
    ui.parent.replaceChildren(...unset, el("option", "None: free-standing", { value: NF_NO_PARENT }), ...nodes);
    ui.parent.value = F.noParent ? NF_NO_PARENT : F.parent;
  } else {
    ui.parent.replaceChildren(el("option", "None: free-standing", { value: "" }), ...nodes);
    ui.parent.value = F.parent;
  }
  ui.parentMode.hidden = !F.parent || !!fog;  // a crystallize under a parent is always its single-child Split
  ui.modeSplit.input.checked = F.parentMode === "split";
  ui.modeRests.input.checked = F.parentMode === "rests";
  ui.modeSplit.input.disabled = !nfLocal();  // an imported result is never a split child
  ui.modeSplit.label.classList.toggle("off", !nfLocal());
  const parent = F.parent ? nfNode(F.parent) : null;
  ui.reassignLabel.hidden = !(parent && parent.assignee && parent.assignee !== nfMe());
  ui.reassign.checked = F.reassign;
  if (!ui.reassignLabel.hidden) ui.reassignText.textContent = `${parent.id} is claimed by ${parent.assignee}: take the claim over (--reassign)`;
}

const NF_KIND_HINTS = {
  theorem: "The map's one target result.",
  lemma: "A local result with standing of its own.",
  claim: "A local statement to prove; the usual unit of work.",
  imported_result: "Established elsewhere: no proof and no dependencies; it is relied on through its Reference review, and fixed once created.",
};

function nfUpdate() {
  const F = nf.F, ui = nf.ui;
  if (!F || !ui) return;
  const fog = nfFog();
  for (const b of ui.kind.querySelectorAll("button")) {
    const kind = b.getAttribute("data-kind");
    b.setAttribute("aria-pressed", String(kind === F.kind));
    b.disabled = (nfSplit() || !!fog) && kind !== "claim";  // a split child is a Claim, and so is a crystallize
  }
  for (const b of ui.medium.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.getAttribute("data-medium") === F.medium));
  ui.kindHint.textContent = fog ? "A crystallize states a Claim." : nfSplit() ? "A Split child is always a Claim." : NF_KIND_HINTS[F.kind];
  ui.mediumBox.hidden = !nfLocal();
  ui.depsBox.hidden = !!fog || (!nfLocal() && !F.deps.length);  // left over from a local kind: shown so they can be removed; a crystallize takes none
  ui.depFind.hidden = ui.depList.hidden = !nfLocal();
  ui.source.hidden = nfLocal();
  ui.pop.classList.toggle("wide", !nfLocal());
  ui.fog.hidden = !fog;
  if (fog) { ui.fogHead.textContent = `From ${fog.id}`; ui.fogText.textContent = fog.text; }
  ui.title.textContent = fog ? `Crystallize ${fog.id}` : nfSplit() ? `Split ${F.parent}` : F.kind === "imported_result" ? "New imported result" : "New node";
  nfPreview(ui.statementPreview, F.statement);
  nfDeps();
  nfParent();
  if (!nfLocal()) nfRefs();
  // the refusals, per field once touched (or after Create), and the first as the server would answer it
  const errs = nfValidate();
  const shown = errs.filter((e) => F.submitted || F.touched.has(e.f) || ["kind", "deps", "parent", "ref"].includes(e.f));
  for (const [f, box] of Object.entries(ui.err)) {
    const mine = shown.find((e) => e.f === f);
    box.textContent = mine ? `${mine.code}: ${mine.message}` : "";
  }
  ui.refusal.textContent = F.refusal || (shown.length ? `${shown[0].code}: ${shown[0].message}` : "");
  const lines = nfCliLines();
  ui.cli.textContent = lines.join("\n");
  ui.cliNote.textContent = lines.length > 1 ? `${lines.length} commands, run in order: not atomic from the CLI (a later one can fail after an earlier one wrote)` : "";
  ui.submit.textContent = fog ? (F.busy ? "Crystallizing…" : "Crystallize") : F.busy ? "Creating…" : nfSplit() ? "Split" : F.kind === "imported_result" ? "Create imported result" : `Create ${F.kind}`;
  ui.submit.disabled = F.busy;
  nfPlace();
  drawNodeFormGhost();
}

// -- the ghost: where the new card lands ------------------------------------------------------------
// Called by app.js's drawDag with the scene it just drew, and by the form as it changes.
function drawNodeFormGhost(scene) {
  scene = scene || $("dag-view");
  if (!scene) return;
  for (const old of scene.querySelectorAll("g.ghost")) old.remove();
  if (!nf.F || !nf.ghost || !nf.ui || nf.ui.pop.hidden) return;
  const g = svg("g", { class: "ghost", transform: `translate(${nf.ghost.x},${nf.ghost.y})`, "aria-hidden": "true" });
  g.append(svg("rect", { x: -BOX.w / 2, y: -BOX.h / 2, width: BOX.w, height: BOX.h, rx: BOX.radius }));
  const text = svg("text", { x: -BOX.w / 2 + 14, y: 5 });
  const id = nf.F.id.trim();
  text.textContent = id ? `${KIND_LABEL[nf.F.kind] || nf.F.kind} ${short(id, 18)}` : "The new node lands here";
  g.append(text);
  scene.append(g);
}

const nfToScene = (p) => ({ x: (p.x - view.tx) / view.k, y: (p.y - view.ty) / view.k });

// -- the menu, the popover, and closing them ----------------------------------------------------------
function nfStage() { return $("map-stage"); }

function nfMenu(point, node) {
  nfCloseMenu();
  nf.anchor = point;
  const menu = el("div", null, { class: "ctx-menu", role: "menu", id: "node-menu" });
  const item = (text, prefill, at) => {
    const b = el("button", text, { type: "button", role: "menuitem" });
    b.addEventListener("click", () => { nfCloseMenu(); nfOpen(prefill, at); });
    menu.append(b);
  };
  const scene = nfToScene(point);
  if (node) {
    const centre = (view.at && view.at.get(node.id)) || scene;
    const below = { x: centre.x, y: centre.y + BOX.h + BOX.gapY / 2 };  // a node its parent rests on sits below it
    const above = { x: centre.x, y: centre.y - BOX.h - BOX.gapY / 2 };
    menu.append(el("div", `${KIND_LABEL[node.kind] || node.kind} ${node.id}`, { class: "head" }));
    if (node.kind !== "imported_result") {
      item(`Split ${node.id} into a Claim…`, { parent: node.id, parentMode: "split", kind: "claim" }, below);
      item(`New node ${node.id} rests on…`, { parent: node.id, parentMode: "rests", kind: "lemma" }, below);
      item(`New imported result ${node.id} rests on…`, { parent: node.id, parentMode: "rests", kind: "imported_result" }, below);
      menu.append(el("div", null, { class: "sep" }));
    }
    item(`New node resting on ${node.id}…`, { deps: [node.id], kind: "lemma" }, above);
  } else {
    item("New node here…", {}, scene);
    item("New imported result here…", { kind: "imported_result" }, scene);
  }
  menu.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.preventDefault(); nfCloseMenu(); } event.stopPropagation(); });
  nfStage().append(menu);
  nf.menu = menu;
  const width = nfStage().clientWidth || 0, height = nfStage().clientHeight || 0;
  menu.style.left = `${Math.max(8, Math.min(point.x, width - 260))}px`;
  menu.style.top = `${Math.max(8, Math.min(point.y, height - (menu.offsetHeight || 0) - 8))}px`;
  const first = menu.querySelector("button");
  if (first) setTimeout(() => first.focus(), 0);
}

function nfCloseMenu() {
  if (nf.menu) { nf.menu.remove(); nf.menu = null; }
}

// The fog drawer's Crystallize… (#155): the form beside the item's near node on the canvas (its first one
// drawn there), the ghost below it where a Split child lands; with no near node, at the canvas centre.
// The parent is prefilled only when the item is near exactly one node; near none, it is none.
function nfCrystallize(item) {
  if (nf.ui && !nf.ui.pop.hidden && nfDirty()) { say("Finish or cancel the new node first: its form has unsaved input.", "error"); return; }
  nfCloseMenu();
  const near = item.near || [];
  const centre = mapView === "dag" && view.at ? near.map((id) => view.at.get(id)).find(Boolean) : null;
  const stage = nfStage();
  let ghost;
  if (centre) {
    nf.anchor = { x: centre.x * view.k + view.tx, y: centre.y * view.k + view.ty };
    ghost = { x: centre.x, y: centre.y + BOX.h + BOX.gapY / 2 };
  } else {
    nf.anchor = { x: (stage.clientWidth || 0) / 2, y: (stage.clientHeight || 0) / 2 };
    ghost = nfToScene(nf.anchor);
  }
  const prefill = { fog: { id: item.id, text: item.text, near: [...near] }, kind: "claim", parentMode: "split", parent: near.length === 1 ? near[0] : "", noParent: !near.length };
  return nfOpen(prefill, ghost);
}

async function nfOpen(prefill, at) {
  if (!nf.ui) { nf.ui = nfBuild(); nfStage().append(nf.ui.pop); }
  nf.F = Object.assign(nfBlank(), prefill || {});
  nf.initial = nfData(nf.F);
  nf.ghost = at || null;
  nf.ui.pop.hidden = false;
  nfSyncInputs();
  nfUpdate();
  setTimeout(() => nf.ui.id.focus(), 0);
  try {
    const refs = await api("/api/references");  // the citations, read afresh each time: another tab may have added one
    nf.refs = { references: refs.references || [], source_types: refs.source_types || NF_SOURCE_TYPES };
  } catch (error) { showError(error); }
  if (nf.F) nfUpdate();
}

function nfClose() {
  if (nf.ui) nf.ui.pop.hidden = true;
  nf.F = null;
  nf.ghost = null;
  drawNodeFormGhost();
}

// beside where it was asked for, flipped left near the right edge; a bottom sheet on a narrow window (CSS)
function nfPlace() {
  const pop = nf.ui.pop, stage = nfStage();
  if (pop.hidden || nfNarrow() || !nf.anchor) { pop.style.left = ""; pop.style.top = ""; return; }
  const width = nfLocal() ? 400 : 480, stageWidth = stage.clientWidth || 0, stageHeight = stage.clientHeight || 0;
  const left = nf.anchor.x + 16 + width > stageWidth - 12 ? Math.max(12, nf.anchor.x - width - 16) : nf.anchor.x + 16;
  const top = Math.max(12, Math.min(nf.anchor.y - 40, stageHeight - (pop.offsetHeight || 0) - 12));
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
}

const nfInside = (box, target) => !!box && !!target && (box === target || (typeof box.contains === "function" && box.contains(target)));

function nfWireCanvas() {
  const canvas = $("map-dag");
  if (!canvas || !nfStage()) return;
  const pointOf = (x, y) => { const r = nfStage().getBoundingClientRect(); return { x: x - r.left, y: y - r.top }; };
  const nodeAt = (target) => {
    const card = target && target.closest ? target.closest("[data-node-id]") : null;
    return card ? nfNode(card.getAttribute("data-node-id")) : null;
  };
  const ask = (target, x, y) => {
    if (mapView !== "dag") return;
    if (nf.ui && !nf.ui.pop.hidden && nfDirty()) { say("Finish or cancel the new node first: its form has unsaved input.", "error"); return; }
    nfClose();
    nfMenu(pointOf(x, y), nodeAt(target));
  };
  // a long press opened the menu just now: the browser's own context menu, or the lifted finger's click,
  // that may follow it is not another request (some touch browsers send one, some don't)
  const justPressed = () => !!nf.longPressAt && Date.now() - nf.longPressAt < 1200;
  canvas.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    if (justPressed()) return;
    ask(event.target, event.clientX, event.clientY);
  });
  // a long press on touch opens the same menu; moving the finger pans instead
  canvas.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
    const { target, clientX: x, clientY: y } = event;
    if (nf.press) clearTimeout(nf.press.timer);
    nf.press = { x, y, timer: setTimeout(() => { nf.press = null; nf.longPressAt = Date.now(); ask(target, x, y); }, NF_LONG_PRESS_MS) };
  }, true);
  const cancelPress = (event) => {
    const press = nf.press;
    if (!press) return;
    if (event.type === "pointermove" && Math.hypot(event.clientX - press.x, event.clientY - press.y) <= 8) return;
    clearTimeout(press.timer);
    nf.press = null;
  };
  for (const type of ["pointermove", "pointerup", "pointercancel"]) window.addEventListener(type, cancelPress);
  // the finger lifting after a long press is not a click that opens the card under it
  canvas.addEventListener("click", (event) => {
    if (justPressed()) { event.stopPropagation(); event.preventDefault(); nf.longPressAt = 0; }
  }, true);
  // a click outside closes the menu, and the popover unless it holds unsaved input
  document.addEventListener("pointerdown", (event) => {
    if (nf.menu && !nfInside(nf.menu, event.target)) nfCloseMenu();
    if (nf.ui && !nf.ui.pop.hidden && !nfInside(nf.ui.pop, event.target) && !nfDirty()) nfClose();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (nf.menu) { nfCloseMenu(); return; }
    if (nf.ui && !nf.ui.pop.hidden) nfClose();
  });
  window.addEventListener("resize", () => { if (nf.ui && !nf.ui.pop.hidden) nfPlace(); });
}

document.addEventListener("DOMContentLoaded", nfWireCanvas);
