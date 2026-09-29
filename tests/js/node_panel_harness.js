// Runs the studio's real node panel (src/proof_cli/studio/static/node.js) against a minimal DOM.
// argv[2]: JSON {view, saveAll: true|false|null, press: a button label or a list of them,
// rationale, answer, confirm}. Prints what happened.
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
  const panel = new El("div"), card = new El("section"), name = new El("span"), events = [];
  const everything = () => [...panel.all(), ...card.all()];  // the node panel and the review card in the agent panel
  const context = {
    NODE: scenario.view.node.id,
    document: { getElementById: (id) => (id === "node-panel" ? panel : id === "review-card" ? card : name), createElement: (tag) => new El(tag) },
    location: {},
    confirm: () => { events.push("confirm"); return scenario.confirm !== false; },
    openReadOnly: (name, text) => { events.push({ openReadOnly: name, text }); },
    fetch: async (url, options = {}) => {
      if (options.method === "POST") events.push({ post: url, body: JSON.parse(options.body) });
      return { json: async () => ({ ok: true, data: options.method === "POST" ? (scenario.answer || { version: 2 }) : scenario.view }) };
    },
  };
  if (scenario.saveAll !== null) context.saveAll = async () => { events.push("saveAll"); return scenario.saveAll; };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/studio/static/node.js"), "utf8"), context);
  await new Promise(setImmediate);
  const out = { events, deps: null, links: [], note: "", panel: panel.text() };
  const deps = panel.querySelector(".node-deps");
  if (deps) { out.deps = deps.text(); out.links = deps.all().filter((x) => x.tag === "a").map((x) => x.attrs.href); }
  if (scenario.press) {  // buttons by their labels, in order: a review file; a decision, then Record
    const note = () => (card.querySelector(".node-note") || panel.querySelector(".node-note") || { textContent: "" }).textContent;
    const why = everything().find((x) => x.attrs.class === "review-why");
    if (why && scenario.rationale) why.value = scenario.rationale;
    for (const label of [].concat(scenario.press)) {
      const button = everything().find((x) => x.tag === "button" && x.textContent === label);
      if (!button) throw new Error(`no button ${label}`);
      await button.onclick();
    }
    out.note = note();
  }
  out.review = (card.querySelector(".node-review") || { text: () => "" }).text();
  console.log(JSON.stringify(out));
})();
