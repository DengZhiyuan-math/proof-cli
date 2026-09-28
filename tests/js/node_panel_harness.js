// Runs the studio's real node panel (src/proof_cli/studio/static/node.js) against a minimal DOM.
// argv[2]: JSON {view, saveAll: true|false|null, click: {label, values}}. Prints what happened.
const fs = require("fs"), path = require("path"), vm = require("vm");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.textContent = ""; this.value = ""; this.checked = false; this.classList = { toggle() {} }; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "type") this.type = v; }
  append(...xs) { this.children.push(...xs); }
  prepend(...xs) { this.children.unshift(...xs); }
  replaceChildren(...xs) { this.children = xs; }
  querySelector(s) { return this.all().find((x) => x.attrs.class === s.slice(1)); }
  all() { return this.children.flatMap((x) => (typeof x === "object" ? [x, ...x.all()] : [])); }
  text() { return [this.textContent, ...this.children.map((x) => (typeof x === "object" ? x.text() : String(x)))].join(" "); }
}

(async () => {
  const scenario = JSON.parse(process.argv[2]);
  const panel = new El("div"), name = new El("span"), events = [];
  const context = {
    NODE: scenario.view.node.id,
    document: { getElementById: (id) => (id === "node-panel" ? panel : name), createElement: (tag) => new El(tag) },
    location: {},
    fetch: async (url, options = {}) => {
      if (options.method === "POST") events.push({ post: url, body: JSON.parse(options.body) });
      return { json: async () => ({ ok: true, data: options.method === "POST" ? (scenario.answer || { version: 2 }) : scenario.view }) };
    },
  };
  if (scenario.saveAll !== null) context.saveAll = async () => { events.push("saveAll"); return scenario.saveAll; };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/studio/static/node.js"), "utf8"), context);
  await new Promise(setImmediate);
  const out = { events, deps: null, links: [], note: "" };
  const deps = panel.querySelector(".node-deps");
  if (deps) { out.deps = deps.text(); out.links = deps.all().filter((x) => x.tag === "a").map((x) => x.attrs.href); }
  if (scenario.click) {
    const box = panel.all().find((x) => x.tag === "div" && x.attrs.class === "node-action" && x.children[0].textContent === scenario.click.label);
    for (const [key, value] of Object.entries(scenario.click.values || {})) {
      const input = box.all().find((x) => x.dataset.key === key);
      if (input.type === "checkbox") input.checked = value; else input.value = value;
    }
    await box.children[0].onclick();
    out.note = panel.querySelector(".node-note").textContent;
  }
  console.log(JSON.stringify(out));
})();
