// Runs the map page's node form (src/proof_cli/webapp/static/nodeform.js, issue #154) with the page's real
// app.js against a small fake DOM, the way map_home_harness.js runs the home. argv[2]: JSON
// {state, map, references, narrow, refuse: {"<METHOD> <url>": {code, message}}, steps: [...]}.
// Each step acts on the page, then the page is read back; prints one reading per step. Steps:
// {contextmenu: {x, y}} on the empty canvas, or {contextmenu: {node: id}} on a card; {longpress: {x, y} | {node: id}}
// (a touch held still, then lifted); {dblclick: {x, y}}; {menu: text} (a menu item by its text);
// {fill: {name: value}} (an input by its name, then its input event); {kind: k}; {medium: m};
// {addAssumption: text}; {removeAssumption: i}; {depFind: text}; {pick: id} (a dependency row); {unpick: id} (its chip);
// {parent: id}; {mode: "split"|"rests"}; {reassign: bool}; {refFind: text}; {refPick: id}; {newRef: {...}} (opens and
// fills the new-reference fields); {suggest: "locator"|"version"}; {submit: true}; {cancel: true}; {close: true};
// {escape: true} (Escape inside the form); {key: k} (a key at the document, from the page body);
// {outside: true} (a pointer pressed on the canvas, outside the popover); {copy: true};
// {crystallize: fog_id} (the toolbar's Fog badge, then that row's Crystallize… in the drawer, issue #155),
// served from scenario.fog; {noParent: true} (the parent select's "None: free-standing").
const fs = require("fs"), path = require("path"), vm = require("vm");

const focus = { on: null, body: null };

function matches(node, simple) {
  if (node.tagName === "#TEXT") return false;
  const tag = simple.match(/^[a-zA-Z][a-zA-Z0-9]*/);
  if (tag && node.tagName !== tag[0].toUpperCase()) return false;
  for (const [, id] of simple.matchAll(/#([\w-]+)/g)) if (node.getAttribute("id") !== id) return false;
  for (const [, cls] of simple.matchAll(/\.([\w-]+)/g)) if (!node.classList.contains(cls)) return false;
  for (const [, key, value] of simple.matchAll(/\[([\w-]+)(?:=([^\]]+))?\]/g)) {
    const have = node.getAttribute(key);
    if (have === null || (value !== undefined && have !== value.replace(/^["']|["']$/g, ""))) return false;
  }
  return true;
}

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.attributes = {}; this.children = []; this.parent = null; this.listeners = {};
    this.dataset = {}; this.hidden = false; this.disabled = false; this.checked = false; this._value = ""; this._text = ""; this.style = {};
    const self = this;
    this.classList = {
      _set() { return new Set((self.attributes.class || "").split(/\s+/).filter(Boolean)); },
      contains(c) { return this._set().has(c); },
      add(...cs) { const s = this._set(); cs.forEach((c) => s.add(c)); self.attributes.class = [...s].join(" "); },
      remove(...cs) { const s = this._set(); cs.forEach((c) => s.delete(c)); self.attributes.class = [...s].join(" "); },
      toggle(c, on) { if (on === undefined ? !this.contains(c) : on) this.add(c); else this.remove(c); },
    };
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
  removeAttribute(k) { delete this.attributes[k]; }
  get className() { return this.attributes.class || ""; }
  set className(v) { this.attributes.class = v; }
  get value() {
    if (this.tagName === "SELECT") {
      const options = this.children.filter((c) => c.tagName === "OPTION");
      const picked = options.find((o) => o.selected) || options[0];
      return picked ? picked.value : "";
    }
    if (this.tagName === "OPTION") return this.attributes.value ?? this.textContent;
    if (this.tagName === "INPUT" && this._value === "" && this.attributes.value !== undefined) return this.attributes.value;
    return this._value;
  }
  set value(v) {
    if (this.tagName === "SELECT") for (const o of this.children) o.selected = o.value === v;
    else this._value = v;
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = []; this._text = String(v); }
  _adopt(items) { return items.map((c) => { const n = typeof c === "string" ? Object.assign(new FakeElement("#text"), { _text: c }) : c; if (n.parent && n.parent !== this) n.remove(); n.parent = this; return n; }); }
  append(...items) { this.children.push(...this._adopt(items)); }
  appendChild(item) { this.append(item); return item; }
  replaceChildren(...items) { this._text = ""; this.children = this._adopt(items); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  get firstChild() { return this.children[0]; }
  focus() { focus.on = this; }
  blur() { if (focus.on === this) focus.on = focus.body; }
  select() {}
  closest(selector) { for (let n = this; n; n = n.parent) if (matches(n, selector)) return n; return null; }
  contains(other) { for (let n = other; n; n = n.parent) if (n === this) return true; return false; }
  getBoundingClientRect() { return { left: 0, top: 0, width: this.clientWidth || 0, height: this.clientHeight || 0 }; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { return Promise.all((this.listeners[type] || []).map((fn) => fn({ target: this, preventDefault() {}, stopPropagation() {}, ...event }))); }
  _all() { return this.children.flatMap((c) => [c, ...c._all()]); }
  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+/);
    const last = parts.pop();
    return this._all().filter((n) => {
      if (!matches(n, last)) return false;
      let i = parts.length - 1;
      for (let up = n.parent; i >= 0 && up; up = up === this ? null : up.parent) if (matches(up, parts[i])) i--;
      return i < 0;
    });
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

(async () => {
  const scenario = JSON.parse(process.argv[2]);
  const ids = ["message", "project", "reviewer", "reviewer-initial", "stat-frontier", "stat-review", "rail-review", "rail-warnings",
    "home", "node-page", "confirm", "confirm-decisions", "confirm-record", "confirm-cancel",
    "sidebar-toggle", "review-page", "warnings-page", "attention-nodes", "attention-count", "records-count",
    "pending", "pending-count", "decide-batch", "warnings",
    "view-dag", "view-tree", "tree-root", "tree-root-label", "map-caption", "map-stage", "map-dag", "map-tree", "dag-svg",
    "zoom-in", "zoom-out", "zoom-fit", "zoom-tidy", "zoom-level", "map-find", "map-find-count",
    "trusted", "trusted-count", "manage-rules", "rules-sheet", "rule-form", "rule-new", "rule-cancel", "rule-record",
    "cond-reviewed", "cond-doi", "cond-arxiv", "cond-types", "rule-name",
    "fog-badge", "stat-fog", "fog-drawer", "fog-drawer-n", "fog-list", "fog-close", "fog-add-text", "fog-add-near", "fog-add", "fog-show-all", "fog-composer", "map-legend"];
  const tags = { "tree-root": "select", "dag-svg": "svg", "map-find": "input", pending: "table", trusted: "table", "fog-add-near": "select", "fog-show-all": "input", "fog-add-text": "input" };
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(tags[id] || "div")]));
  for (const [id, element] of Object.entries(elements)) element.setAttribute("id", id);
  elements["map-stage"].append(elements["map-dag"]);
  elements["map-dag"].append(elements["dag-svg"]);
  for (const stage of ["map-stage", "map-dag"]) Object.assign(elements[stage], { clientWidth: scenario.width || 800, clientHeight: 600 });
  focus.body = focus.on = new FakeElement("body");
  const byId = (id) => elements[id] || Object.values(elements).flatMap((e) => e._all()).find((n) => n.getAttribute("id") === id) || null;
  for (const table of ["pending", "trusted"]) elements[table].append(new FakeElement("thead"), new FakeElement("tbody"));
  elements.confirm.hidden = elements["rules-sheet"].hidden = elements["fog-drawer"].hidden = true;
  const listeners = {}, windowListeners = {};
  const hear = (type, fn) => { (listeners[type] ||= []).push(fn); };
  const location = { hash: "", href: "" };
  const posted = [];
  const timers = [];
  const storage = {};
  const copied = [];
  let map = scenario.map;
  const context = {
    console, location, Node: FakeElement,
    setTimeout(fn, ms) { timers.push({ fn, ms: ms || 0 }); return timers.length; },
    clearTimeout(id) { if (timers[id - 1]) timers[id - 1].fn = null; },
    matchMedia: (query) => ({ matches: !!scenario.narrow && query.includes("760px") }),
    localStorage: { getItem: (k) => storage[k] ?? null, setItem: (k, v) => { storage[k] = String(v); }, removeItem: (k) => { delete storage[k]; } },
    navigator: { clipboard: { writeText: async (text) => { copied.push(text); } } },
    document: {
      title: "", getElementById: byId,
      get activeElement() { return focus.on; }, get body() { return focus.body; },
      createElement: (tag) => new FakeElement(tag), createElementNS: (_, tag) => new FakeElement(tag),
      addEventListener: hear,
      querySelectorAll: () => [],
    },
    window: { addEventListener: (type, fn) => { (windowListeners[type] ||= []).push(fn); }, removeEventListener() {} },
    fetch: async (url, init = {}) => {
      const method = init.method || "GET";
      const body = init.body ? JSON.parse(init.body) : null;
      if (method === "POST") posted.push({ url, body });
      const refused = (scenario.refuse || {})[`${method} ${url}`];
      if (refused) return { json: async () => ({ ok: false, error: refused }) };
      let data;
      if (url === "/api/state") data = scenario.state;
      else if (url === "/api/map") data = map;
      else if (url.endsWith("/crystallize") && method === "POST") {
        // the crystallize as the server answers it (webapp/server.py fog_action): the node, its fog item, the page to open
        data = { id: body.node_id, kind: "claim", fog: { id: url.split("/")[3], status: "crystallized", node_id: body.node_id }, reminder: scenario.reminder || "", page: `/studio/${body.node_id}/` };
        map = { nodes: [...map.nodes, { id: body.node_id, kind: "claim", statement: body.statement, display_label: body.display_label, dependencies: [],
          acceptance_state: "unreviewed", workflow_state: "open", integrity_state: "current", assignee: null, frontier: false, status: { text: "Open", kind: "open" } }] };
      }
      else if (url.startsWith("/api/fog")) data = scenario.fog || { items: [] };
      else if (url === "/api/references" && method === "GET") data = scenario.references || { references: [], source_types: [] };
      else if (url === "/api/references") data = { id: body.reference_id, title: body.title, authors: body.authors, year: Number(body.year), source_type: body.source_type, identifier: body.identifier, url: body.url, bibliographic_source: "" };
      else if (url === "/api/nodes") {
        data = { id: body.node_id, kind: body.kind, page: body.kind === "imported_result" ? `/#/node/${body.node_id}` : `/studio/${body.node_id}/` };
        // the map as the server then sends it: the new node with the status the server derived (scenario.createdStatus)
        map = { nodes: [...map.nodes, { id: body.node_id, kind: body.kind, statement: body.statement, display_label: body.display_label, dependencies: body.dependencies,
          acceptance_state: "unreviewed", workflow_state: "open", integrity_state: "current", assignee: null, frontier: false,
          status: scenario.createdStatus || { text: "Open", kind: "open" } }] };
      } else if (url.endsWith("/split")) data = { children: body.children, next: `/studio/${body.children[0].id}/` };
      else data = {};
      return { json: async () => ({ ok: true, data }) };
    },
  };
  const katexCalls = [];
  context.katex = require("./katex_stub.js")(katexCalls);
  vm.createContext(context);
  for (const file of ["studio/static/mathtext.js", "studio/static/status.js", "webapp/static/app.js", "webapp/static/nodeform.js"]) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli", file), "utf8"), context);
  }
  listeners.DOMContentLoaded.forEach((fn) => fn());
  const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((resolve) => setImmediate(resolve)); };
  const flush = async () => { while (timers.some((t) => t.fn)) { for (const t of timers) if (t.fn) { const fn = t.fn; t.fn = null; await fn(); } } await settle(); };
  await settle();

  const pop = () => byId("node-pop");
  const menu = () => byId("node-menu");
  const inPop = (name) => pop()._all().find((n) => n.getAttribute("name") === name);
  const card = (id) => elements["dag-svg"].querySelectorAll("g.node").find((g) => g.getAttribute("data-node-id") === id);
  // a click where it lands: the element's own listeners, then each parent's, as it bubbles
  const click = async (target) => { for (let n = target; n; n = n.parent) await n.dispatch("click", { target }); await settle(); };
  const errorsOf = () => Object.fromEntries(pop()._all().filter((n) => n.getAttribute("data-f")).map((box) => [box.getAttribute("data-f"),
    (box.children.find((c) => c.classList.contains("nf-err")) || { textContent: "" }).textContent]).filter(([f, text]) => f && text));
  const read = () => {
    const p = pop();
    const shown = !!p && !p.hidden;
    const ghost = elements["dag-svg"].querySelector("g.ghost");
    const reading = {
      menu: menu() ? menu().querySelectorAll("button").map((b) => b.textContent) : null,
      menuHead: menu() ? menu().querySelectorAll("div.head").map((d) => d.textContent) : null,
      popover: shown,
      ghost: ghost ? { transform: ghost.getAttribute("transform"), text: ghost.querySelector("text").textContent } : null,
      empty: (elements["dag-svg"].querySelector("text.empty") || { textContent: null }).textContent,
      scene: (byId("dag-view") || { getAttribute: () => null }).getAttribute("transform"),
      posted: [...posted], href: location.href, message: elements.message.textContent, katex: [...katexCalls], copied: [...copied],
      positions: JSON.parse(storage["proof.map.positions:p"] || "{}"),
      focused: focus.on ? focus.on.getAttribute("name") : null,
      findFocused: focus.on === elements["map-find"],
      // what Create would post now, its own checks aside: for comparing them with the server's
      cliCommands: vm.runInContext("nf.F ? nfCliLines() : null", context),
      // each card's centre on the scene, and the scene's pan and zoom: where a crystallize's popover should stand
      centres: vm.runInContext("view.at ? Object.fromEntries(view.at) : null", context),
      zoom: vm.runInContext("({ k: view.k, tx: view.tx, ty: view.ty })", context),
      anchor: vm.runInContext("nf.F && nf.anchor ? { ...nf.anchor } : null", context),
      wouldPost: vm.runInContext("nf.F ? (nf.F.fog ? { url: `/api/fog/${nf.F.fog.id}/crystallize`, body: nfCrystallizeBody() } : nfSplit() ? { url: `/api/node/${nf.F.parent}/split`, body: nfSplitBody() } : { url: '/api/nodes', body: nfNodeBody() }) : null", context),
    };
    if (!p) return reading;
    const q = (sel) => p.querySelector(sel);
    return Object.assign(reading, {
      title: q("h2").textContent, fogShown: !q(".nf-fog").hidden, fogText: q(".nf-fog").textContent, classes: p.className.split(" "), style: { ...p.style },
      kinds: q("[data-seg=kind]").querySelectorAll("button").map((b) => ({ kind: b.getAttribute("data-kind"), pressed: b.getAttribute("aria-pressed") === "true", disabled: b.disabled })),
      mediumShown: !q("[data-seg=medium]").parent.hidden, medium: q("[data-seg=medium]").querySelectorAll("button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.getAttribute("data-medium"))[0],
      depsShown: !q("[data-f=deps]").hidden, sourceShown: !q("fieldset").hidden,
      statementPreview: q("[data-f=statement]").querySelector(".nf-preview").textContent,
      statementMath: q("[data-f=statement]").querySelectorAll("span.math").map((m) => ({ class: m.className, text: m.textContent })),
      assumptionPreviews: p.querySelectorAll(".nf-assumption .nf-preview").map((n) => n.textContent),
      depRows: q("[data-f=deps]").querySelectorAll("li").map((li) => ({ id: li.getAttribute("data-dep"), text: li.textContent, on: li.classList.contains("on"),
        marks: li.querySelectorAll("mark").map((m) => m.textContent), chips: li.querySelectorAll("span.chip").map((c) => ({ text: c.textContent, class: c.className, icon: (c.querySelector("g.status-icon") || { className: null }).className })) })),
      depChips: q("[data-f=deps]").querySelectorAll(".nf-dep-chip").map((c) => c.getAttribute("data-chip")),
      parentOptions: inPop("nf-parent").querySelectorAll("option").map((o) => o.value), parentLabels: inPop("nf-parent").querySelectorAll("option").map((o) => o.textContent), parent: inPop("nf-parent").value,
      modesShown: !q(".nf-radios").hidden, mode: p.querySelectorAll("input[type=radio]").filter((r) => r.checked).map((r) => r.value)[0] || null,
      splitDisabled: p.querySelectorAll("input[type=radio]").find((r) => r.value === "split").disabled,
      reassignShown: !q(".nf-reassign").hidden, reassignText: q(".nf-reassign").textContent,
      refRows: q("[data-f=ref]").querySelectorAll("ul li").map((li) => ({ id: li.getAttribute("data-ref"), text: li.textContent, on: li.classList.contains("on"), marks: li.querySelectorAll("mark").map((m) => m.textContent) })),
      refListShown: !q("[data-f=ref]").querySelector("ul").hidden,
      refSelected: q("[data-f=ref]").children[1].textContent, refSelectedBlock: !!q("[data-f=ref]").querySelector(".citation-block"),
      immutable: (q(".nf-immutable") || { textContent: null }).textContent,
      suggest: p.querySelectorAll("[data-suggest]").map((b) => b.getAttribute("data-suggest")),
      errors: errorsOf(), refusal: q(".nf-refusal").textContent,
      cli: q("pre.nf-cli").textContent, cliNote: q(".nf-cli-note").textContent,
      submit: { text: q("button.primary").textContent, disabled: q("button.primary").disabled },
      kindHint: q("[data-f=kind]").querySelector(".hint").textContent,
    });
  };
  const readings = [read()];
  for (const step of scenario.steps || []) {
    const canvas = elements["map-dag"];
    const pointer = (spec) => spec.node ? { target: card(spec.node), clientX: 300, clientY: 200 } : { target: canvas, clientX: spec.x, clientY: spec.y };
    if (step.contextmenu) {
      const at = pointer(step.contextmenu);
      for (const fn of listeners.pointerdown || []) await fn({ ...at, button: 2, pointerType: "mouse" });
      await canvas.dispatch("contextmenu", at); await flush();
    }
    if (step.longpress) {
      const at = pointer(step.longpress);
      for (const fn of listeners.pointerdown || []) await fn({ ...at, button: 0, pointerType: "touch" });
      await canvas.dispatch("pointerdown", { ...at, button: 0, pointerType: "touch" });
      await flush();  // held long enough
      for (const fn of windowListeners.pointerup || []) await fn({ type: "pointerup", ...at });
      // the lift's click: the canvas hears it first (capture), then the card it lands on
      const clickEvent = { ...at, stopped: false, stopPropagation() { this.stopped = true; }, preventDefault() {} };
      for (const fn of canvas.listeners.click || []) await fn(clickEvent);
      if (!clickEvent.stopped && step.longpress.node) await card(step.longpress.node).dispatch("click");
      await settle();
    }
    if (step.dblclick) { await canvas.dispatch("dblclick", { target: canvas, clientX: step.dblclick.x, clientY: step.dblclick.y }); await settle(); }
    if (step.menu) { await click(menu().querySelectorAll("button").find((b) => b.textContent === step.menu)); await flush(); }
    if (step.fill) for (const [name, value] of Object.entries(step.fill)) { const input = inPop(name); input.value = value; await input.dispatch("input"); await input.dispatch("change"); await settle(); }
    if (step.kind) { await click(pop().querySelector("[data-seg=kind]").querySelectorAll("button").find((b) => b.getAttribute("data-kind") === step.kind)); }
    if (step.medium) { await click(pop().querySelector("[data-seg=medium]").querySelectorAll("button").find((b) => b.getAttribute("data-medium") === step.medium)); }
    if (step.addAssumption !== undefined) {
      await click(pop().querySelectorAll("button").find((b) => b.textContent === "+ Assumption")); await flush();
      const inputs = pop().querySelectorAll(".nf-assumption input");
      const input = inputs[inputs.length - 1]; input.value = step.addAssumption; await input.dispatch("input"); await settle();
    }
    if (step.removeAssumption !== undefined) { await click(pop().querySelectorAll(".nf-assumption button")[step.removeAssumption]); }
    if (step.depFind !== undefined) { const input = inPop("nf-deps-find"); input.value = step.depFind; await input.dispatch("input"); await settle(); }
    if (step.pick) { await click(pop().querySelector("[data-f=deps]").querySelectorAll("li").find((li) => li.getAttribute("data-dep") === step.pick)); }
    if (step.unpick) { await click(pop().querySelector("[data-f=deps]").querySelectorAll(".nf-dep-chip").find((c) => c.getAttribute("data-chip") === step.unpick).querySelector("button")); }
    if (step.crystallize) {
      await elements["fog-badge"].dispatch("click"); await settle();
      const row = elements["fog-list"].querySelectorAll("li").find((li) => li.getAttribute("data-fog") === step.crystallize);
      const button = row.querySelectorAll("button").find((b) => b.textContent === "Crystallize…");
      for (const fn of listeners.pointerdown || []) await fn({ target: button, button: 0, pointerType: "mouse" });
      await button.dispatch("click"); await flush();
    }
    if (step.noParent) { const select = inPop("nf-parent"); select.value = ":none"; await select.dispatch("change"); await settle(); }
    if (step.parent !== undefined) { const select = inPop("nf-parent"); select.value = step.parent; await select.dispatch("change"); await settle(); }
    if (step.mode) { const radio = pop().querySelectorAll("input[type=radio]").find((r) => r.value === step.mode); radio.checked = true; await radio.dispatch("change"); await settle(); }
    if (step.reassign !== undefined) { const box = inPop("nf-reassign"); box.checked = step.reassign; await box.dispatch("change"); await settle(); }
    if (step.refFind !== undefined) { const input = inPop("nf-ref-find"); input.value = step.refFind; await input.dispatch("input"); await settle(); }
    if (step.refPick) { await click(pop().querySelector("[data-f=ref]").querySelectorAll("li").find((li) => li.getAttribute("data-ref") === step.refPick)); }
    if (step.newRef) {
      await click(pop().querySelectorAll("button").find((b) => b.textContent === "+ New reference…")); await flush();
      for (const [key, value] of Object.entries(step.newRef)) { const input = inPop(`ref-${key}`); input.value = value; await input.dispatch(key === "source_type" ? "change" : "input"); await settle(); }
    }
    if (step.suggest) { await click(pop().querySelector(`[data-suggest=${step.suggest}]`)); }
    if (step.submit) { await pop().querySelector("form").dispatch("submit"); await flush(); }
    if (step.cancel) { await click(pop().querySelectorAll("button").find((b) => b.textContent === "Cancel" && !b.parent.classList.contains("nf-ref-new"))); }
    if (step.close) { await click(pop().querySelector("button.close")); }
    if (step.copy) { await click(pop().querySelectorAll("button").find((b) => b.textContent === "Copy")); }
    if (step.escape) {
      let stopped = false;
      const event = { key: "Escape", target: inPop("nf-id"), preventDefault() {}, stopPropagation() { stopped = true; } };
      await pop().dispatch("keydown", event);
      if (!stopped) for (const fn of listeners.keydown || []) await fn(event);
      await settle();
    }
    if (step.keyInForm) {  // a key typed while the focus is on one of the form's buttons: the map's keys must not hear it
      let stopped = false;
      const event = { key: step.keyInForm, target: pop().querySelector("button.close"), metaKey: false, ctrlKey: false, altKey: false, preventDefault() {}, stopPropagation() { stopped = true; } };
      focus.on = event.target;
      await pop().dispatch("keydown", event);
      if (!stopped) for (const fn of listeners.keydown || []) await fn(event);
      await settle();
    }
    if (step.enterIn) {  // Enter in a one-line field: the browser submits the form unless the keydown was prevented
      let prevented = false;
      const event = { key: "Enter", target: inPop(step.enterIn), metaKey: false, ctrlKey: false, preventDefault() { prevented = true; }, stopPropagation() {} };
      await pop().dispatch("keydown", event);
      if (!prevented) await pop().querySelector("form").dispatch("submit");
      await flush();
    }
    if (step.outside) { for (const fn of listeners.pointerdown || []) await fn({ target: canvas, button: 0, pointerType: "mouse" }); await settle(); }
    readings.push(read());
  }
  console.log(JSON.stringify(readings));
})().catch((error) => { console.error(error); process.exit(1); });
