// Runs the map page's real home (src/proof_cli/webapp/static/app.js) against a small fake DOM.
// argv[2]: JSON {state, map, steps: [...]}. Each step acts on the page, then the page is read back;
// prints one reading per step. Steps: {filter: "text"}, {key: "Enter"|"Escape"}, {view: "dag"|"tree"},
// {tick: node_id, on: bool}, {choose: node_id, value}, {record: true} (presses Record, then confirms).
const fs = require("fs"), path = require("path"), vm = require("vm");

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.attributes = {}; this.children = []; this.parent = null; this.listeners = {};
    this.dataset = {}; this.hidden = false; this.disabled = false; this.checked = false; this._value = ""; this._text = "";
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
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { return Promise.all((this.listeners[type] || []).map((fn) => fn({ target: this, preventDefault() {}, ...event }))); }
  _all() { return this.children.flatMap((c) => [c, ...c._all()]); }
  querySelectorAll(selector) {
    const cls = selector.startsWith(".") ? selector.slice(1) : null;
    return this._all().filter((n) => (cls ? n.classList.contains(cls) : n.tagName === selector.toUpperCase()));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

(async () => {
  const scenario = JSON.parse(process.argv[2]);
  const ids = ["toasts", "project", "reviewer", "home", "node-page", "confirm", "confirm-decisions", "confirm-reviewer", "confirm-record", "confirm-cancel",
    "review", "pending", "pending-count", "selected-count", "decide-batch", "warnings", "warnings-block",
    "view-dag", "view-tree", "tree-root", "map-filter", "map-caption", "map-dag", "map-tree", "dag-svg", "new-node", "new-kind", "new-dependencies"];
  const tags = { "tree-root": "select", "new-kind": "select", "new-dependencies": "select", "map-filter": "input", "dag-svg": "svg", "decide-batch": "button" };
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(tags[id] || "div")]));
  const listeners = {};
  const location = { hash: "", href: "" };
  const posted = [];
  const context = {
    console, location, setTimeout() {}, Node: FakeElement,
    document: {
      title: "", getElementById: (id) => elements[id] || null,
      createElement: (tag) => new FakeElement(tag), createElementNS: (_, tag) => new FakeElement(tag),
      addEventListener: (type, fn) => { listeners[type] = fn; },
    },
    window: { addEventListener() {} },
    fetch: async (url, init = {}) => {
      if (init.method === "POST") posted.push({ url, body: JSON.parse(init.body) });
      const data = url === "/api/state" ? scenario.state : url === "/api/map" ? scenario.map : { results: [] };
      return { json: async () => ({ ok: true, data }) };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/webapp/static/app.js"), "utf8"), context);
  listeners.DOMContentLoaded();
  await new Promise((resolve) => setImmediate(resolve));

  const card = (id) => [...elements.pending.querySelectorAll(".pending")].find((c) => c.dataset.target === id);
  const read = () => ({
    caption: elements["map-caption"].textContent,
    filtering: elements["dag-svg"].classList.contains("filtering"),
    matched: elements["dag-svg"].querySelectorAll("g").filter((g) => g.classList.contains("match")).map((g) => g.attributes["aria-label"].split(" ")[1].replace(":", "")),
    dimmed: elements["map-tree"].querySelectorAll("li").filter((li) => li.classList.contains("dim")).map((li) => li.querySelector(".muted").textContent),
    // each drawn DAG node: its classes and every text it shows
    dag: Object.fromEntries(elements["dag-svg"].querySelectorAll("g").map((g) => [
      g.attributes["aria-label"].split(" ")[1].replace(":", ""),
      { classes: g.className.split(" "), texts: g.querySelectorAll("text").map((t) => t.textContent), label: g.attributes["aria-label"] },
    ])),
    // each tree line, by its node id: the status chips it shows
    tree: Object.fromEntries(elements["map-tree"].querySelectorAll("li").filter((li) => li.attributes["data-node-id"]).map((li) => [
      li.attributes["data-node-id"], li.querySelector(".line").querySelectorAll(".status").map((s) => s.textContent),
    ])),
    href: location.href,
    reviewHidden: elements.review.hidden, warningsHidden: elements["warnings-block"].hidden,
    pendingCount: elements["pending-count"].textContent,
    batchDisabled: elements["decide-batch"].disabled, selected: elements["selected-count"].textContent,
    posted,
  });
  const readings = [read()];
  for (const step of scenario.steps || []) {
    if ("filter" in step) { elements["map-filter"].value = step.filter; await elements["map-filter"].dispatch("input"); }
    if (step.key) await elements["map-filter"].dispatch("keydown", { key: step.key });
    if (step.view) await elements[`view-${step.view}`].dispatch("click");
    if (step.tick) { const box = card(step.tick).querySelector(".pick"); box.checked = step.on !== false; await box.dispatch("change"); }
    if (step.choose) { const choice = card(step.choose).querySelector(".choice"); choice.value = step.value; await choice.dispatch("change"); }
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
