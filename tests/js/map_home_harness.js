// Runs the proof map page's real home (src/proof_cli/webapp/static/app.js) against a small fake DOM.
// argv[2]: JSON {state, map, steps: [...]}. Each step acts on the page, then the page is read back;
// prints one reading per step. Steps: {view: "dag"|"tree"}, {root: node_id} (the tree's root),
// {tick: node_id, on: bool}, {choose: node_id, value}, {record: true} (presses Record, then confirms),
// {open: node_id} (follows the node's link to its own page, served from scenario.nodes[node_id]),
// {find: text} (types into the search box), {key: "Enter"|"Escape"|"/"|"f"} (a key pressed where the focus
// is: the focused element hears it first, then the document), {blur: true} (the focus goes back to the page).
const fs = require("fs"), path = require("path"), vm = require("vm");

const focus = { on: null, body: null };

// one compound selector: tag, .class and [attr=value] parts, e.g. input[type=checkbox] or span.chip
function matches(node, simple) {
  if (node.tagName === "#TEXT") return false;
  const tag = simple.match(/^[a-zA-Z]+/);
  if (tag && node.tagName !== tag[0].toUpperCase()) return false;
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
  get className() { return this.attributes.class || ""; }
  set className(v) { this.attributes.class = v; }
  get value() {
    if (this.tagName === "SELECT") {
      const options = this.children.filter((c) => c.tagName === "OPTION");
      const picked = options.find((o) => o.selected) || options[0];
      return picked ? picked.value : "";
    }
    if (this.tagName === "OPTION") return this.attributes.value ?? this.textContent;
    return this._value;
  }
  set value(v) {
    if (this.tagName === "SELECT") for (const o of this.children) o.selected = o.value === v;
    else this._value = v;
  }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = []; this._text = String(v); }
  _adopt(items) { return items.map((c) => { const n = typeof c === "string" ? Object.assign(new FakeElement("#text"), { _text: c }) : c; n.parent = this; return n; }); }
  append(...items) { this.children.push(...this._adopt(items)); }
  appendChild(item) { this.append(item); return item; }
  replaceChildren(...items) { this._text = ""; this.children = this._adopt(items); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); }
  get firstChild() { return this.children[0]; }
  focus() { focus.on = this; }
  blur() { if (focus.on === this) focus.on = focus.body; }
  select() {}
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { return Promise.all((this.listeners[type] || []).map((fn) => fn({ target: this, preventDefault() {}, stopPropagation() {}, ...event }))); }
  _all() { return this.children.flatMap((c) => [c, ...c._all()]); }
  // descendant selectors only ("tbody tr", "input[type=checkbox]", ".status"): all this page's script asks for
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
    "pending", "pending-count", "decide-batch", "warnings",
    "view-dag", "view-tree", "tree-root", "tree-root-label", "map-caption", "map-dag", "map-tree", "dag-svg",
    "zoom-in", "zoom-out", "zoom-fit", "zoom-tidy", "zoom-level", "map-find", "map-find-count",
    "node-title", "node-axes", "node-warnings", "node-statement", "node-assumptions", "node-claim", "node-folder", "node-source",
    "node-dependents", "node-pdfs", "node-deps", "node-challenges", "node-proof-meta", "node-proof-exact", "node-evidence",
    "node-decisions", "node-history"];
  const tags = { "tree-root": "select", "dag-svg": "svg", "decide-batch": "button", pending: "table", warnings: "ul", "map-find": "input",
    "node-deps": "table", "node-decisions": "table", "node-challenges": "ul", "node-evidence": "ul", "node-history": "ul" };
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(tags[id] || "div")]));
  Object.assign(elements["map-dag"], { clientWidth: 800, clientHeight: 600 });  // the canvas has a size, so it can be fitted and panned
  focus.body = focus.on = new FakeElement("body");
  // an element the page drew itself (the DAG's <g id="dag-view">) is found by its id too
  const byId = (id) => elements[id] || Object.values(elements).flatMap((e) => e._all()).find((n) => n.getAttribute("id") === id) || null;
  for (const table of ["pending", "node-deps", "node-decisions"]) elements[table].append(new FakeElement("thead"), new FakeElement("tbody"));
  elements.confirm.hidden = true;
  const listeners = {};
  const hear = (type, fn) => { (listeners[type] ||= []).push(fn); };
  const location = { hash: "", href: "" };
  const posted = [];
  const context = {
    console, location, setTimeout() {}, Node: FakeElement,
    document: {
      title: "", getElementById: byId,
      get activeElement() { return focus.on; }, get body() { return focus.body; },
      createElement: (tag) => new FakeElement(tag), createElementNS: (_, tag) => new FakeElement(tag),
      addEventListener: hear,
      querySelectorAll: () => [],
    },
    window: { addEventListener: (type, fn) => { listeners[`window:${type}`] = fn; }, removeEventListener() {} },
    fetch: async (url, init = {}) => {
      if (init.method === "POST") posted.push({ url, body: JSON.parse(init.body) });
      const node = url.startsWith("/api/node/") ? (scenario.nodes || {})[decodeURIComponent(url.slice("/api/node/".length))] : undefined;
      const data = url === "/api/state" ? scenario.state : url === "/api/map" ? scenario.map : node || { results: [] };
      return { json: async () => ({ ok: true, data }) };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/webapp/static/app.js"), "utf8"), context);
  listeners.DOMContentLoaded.forEach((fn) => fn());
  await new Promise((resolve) => setImmediate(resolve));

  const pendingRow = (id) => elements.pending.querySelectorAll("tbody tr").find((tr) => tr.dataset.target === id);
  const nodeIdOf = (g) => g.attributes["aria-label"].split(" ")[1].replace(/:$/, "");
  // a tree line, read the way PR #104's harness reads it: its attributes, its own chips, its children
  const treeLine = (li) => ({
    id: li.getAttribute("data-node-id"),
    dim: li.classList.contains("dim"),
    sharedBy: li.getAttribute("data-shared-by"),
    chips: li.children.filter((c) => c.tagName === "SPAN" && c.classList.contains("state-chip")).map((c) => c.textContent),
    children: li.children.filter((c) => c.tagName === "UL").flatMap((ul) => ul.children.filter((c) => c.tagName === "LI").map((c) => c.getAttribute("data-node-id"))),
  });
  const read = () => ({
    caption: elements["map-caption"].textContent,
    // each drawn DAG node: its classes, every text it shows (and each text's classes), its aria-label
    dag: Object.fromEntries(elements["dag-svg"].querySelectorAll("g.node").map((g) => [nodeIdOf(g), {
      classes: g.className.split(" "),
      texts: g.querySelectorAll("text").map((t) => t.textContent),
      tags: g.querySelectorAll("text.tag").map((t) => ({ text: t.textContent, classes: t.className.split(" ") })),
      label: g.attributes["aria-label"],
      title: (g.querySelector("title") || { textContent: null }).textContent,  // what hovering it shows
    }])),
    // each tree line in drawing order
    tree: elements["map-tree"].querySelectorAll("li").map(treeLine),
    // the search box: what it holds, its count, whether it has the focus
    find: { value: elements["map-find"].value, count: elements["map-find-count"].textContent, focused: focus.on === elements["map-find"] },
    // where the canvas looks: the scene's transform, and each node's centre on the scene
    scene: (byId("dag-view") || { getAttribute: () => null }).getAttribute("transform"),
    at: Object.fromEntries(elements["dag-svg"].querySelectorAll("g.node").map((g) => [nodeIdOf(g), g.getAttribute("transform")])),
    filtering: elements["dag-svg"].classList.contains("filtering"),
    href: location.href,
    pendingRows: elements.pending.querySelectorAll("tbody tr").map((tr) => tr.textContent),
    pendingCount: elements["pending-count"].textContent,
    warnings: elements.warnings.querySelectorAll("li").map((li) => li.textContent),
    message: elements.message.textContent,
    // the node's own page, once one is open: its source block, which carries the citation
    nodePageShown: !elements["node-page"].hidden,
    nodeSource: elements["node-source"].textContent,
    nodeSourceWarnings: elements["node-source"].querySelectorAll(".warning").map((w) => w.textContent),
    // each review card's citation line, and whether it is marked missing
    pendingCitations: elements.pending.querySelectorAll("tbody tr").map((tr) => tr.querySelectorAll(".citation").map((c) => c.textContent).join(" ")),
    pendingCitationMissing: elements.pending.querySelectorAll("tbody tr").map((tr) => tr.querySelectorAll(".citation.warning").length > 0),
    // each review card's key ideas (ADR-0013): the text of its .key-ideas block
    pendingKeyIdeas: elements.pending.querySelectorAll("tbody tr").map((tr) => tr.querySelectorAll(".key-ideas").map((k) => k.textContent).join(" ")),
    confirmShown: !elements.confirm.hidden,
    posted,
  });
  const readings = [read()];
  // a key pressed where the focus is: the focused element hears it first, then it bubbles to the document
  const press = async (key) => {
    const target = focus.on;
    const event = { key, target, metaKey: false, ctrlKey: false, altKey: false, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} };
    for (const fn of target.listeners.keydown || []) await fn(event);
    for (const fn of listeners.keydown || []) await fn(event);
  };
  for (const step of scenario.steps || []) {
    if (step.find !== undefined) { elements["map-find"].focus(); elements["map-find"].value = step.find; await elements["map-find"].dispatch("input"); }
    if (step.key) await press(step.key);
    if (step.blur) focus.on = focus.body;
    if (step.view) await elements[`view-${step.view}`].dispatch("click");
    if (step.root) { elements["tree-root"].value = step.root; await elements["tree-root"].dispatch("change"); }
    if (step.open) { location.hash = `#/node/${encodeURIComponent(step.open)}`; await listeners["window:hashchange"](); }
    if (step.tick) { pendingRow(step.tick).querySelector("input[type=checkbox]").checked = step.on !== false; }
    if (step.choose) { pendingRow(step.choose).querySelector("select").value = step.value; }
    if (step.record) {
      const pressed = elements["decide-batch"].dispatch("click");
      await new Promise((resolve) => setImmediate(resolve));
      if (!elements.confirm.hidden) elements["confirm-record"].onclick();
      await pressed;
    }
    readings.push(read());
  }
  console.log(JSON.stringify(readings));
})().catch((error) => { console.error(error); process.exit(1); });
