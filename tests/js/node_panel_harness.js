// Runs the studio's real node panel (src/proof_cli/studio/static/node.js) against a minimal DOM.
// argv[2]: JSON {view, saveAll: true|false|null, click: {label, values}, press: button label,
// answer, confirm}. Prints what happened: the events, the review section's text, links and buttons.
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
    confirm: () => { events.push("confirm"); return scenario.confirm !== false; },
    openReadOnly: (name, text) => { events.push({ openReadOnly: name, text }); },
    draftKeyIdeas: async () => { events.push("draftKeyIdeas"); },
    fetch: async (url, options = {}) => {
      if (options.method === "POST") events.push({ post: url, body: JSON.parse(options.body) });
      return { json: async () => ({ ok: true, data: options.method === "POST" ? (scenario.answer || { version: 2 }) : scenario.view }) };
    },
  };
  if (scenario.saveAll !== null) context.saveAll = async () => { events.push("saveAll"); return scenario.saveAll; };
  // the studio page's KaTeX and mathtext.js (ADR-0013), unless the scenario leaves KaTeX out
  const katexCalls = [];
  if (scenario.katex !== false) context.katex = require("./katex_stub.js")(katexCalls);
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/studio/static/mathtext.js"), "utf8"), context);
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
  if (scenario.press) {  // any button, by its label: a review file, a decision
    const button = panel.all().find((x) => x.tag === "button" && x.textContent === scenario.press);
    if (!button) throw new Error(`no button ${scenario.press}`);
    const row = panel.all().find((x) => x.children && x.children.includes(button));
    const why = row && row.children.find((x) => x.tag === "input");
    if (why && scenario.rationale) why.value = scenario.rationale;
    await button.onclick();
    out.note = panel.querySelector(".node-note").textContent;
  }
  const review = panel.querySelector(".node-review") || { text: () => "", all: () => [] };
  out.review = review.text();
  out.reviewLinks = review.all().filter((x) => x.tag === "a").map((x) => x.attrs.href);
  out.reviewButtons = review.all().filter((x) => x.tag === "button").map((x) => x.textContent);
  out.buttons = panel.all().filter((x) => x.tag === "button").map((x) => x.textContent);
  out.text = panel.text();
  out.katex = katexCalls;
  // every maths span in the review section: its class and its text
  out.math = review.all().filter((x) => x.tag === "span" && String(x.attrs.class || "").startsWith("math")).map((x) => ({ class: x.attrs.class, text: x.textContent, title: x.attrs.title || null }));
  console.log(JSON.stringify(out));
})();
