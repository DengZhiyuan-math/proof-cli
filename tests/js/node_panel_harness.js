// Runs the studio's real node panel (src/proof_cli/studio/static/node.js) against a minimal DOM.
// argv[2]: JSON {view, saveAll: true|false|null, press: a button label or a list of them,
// rationale, draft: true (the "+" menu's "Draft key ideas"), katex: false, answer, confirm}.
// Prints what happened: the events, the review sheet's text, links and buttons, the panel's.
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
  const out = { events, deps: null, links: [], note: "", panel: panel.text() };
  const deps = panel.querySelector(".node-deps");
  if (deps) { out.deps = deps.text(); out.links = deps.all().filter((x) => x.tag === "a").map((x) => x.attrs.href); }
  // what the last action said: the review sheet's note, else the node panel's
  const note = () => [card, panel].map((where) => (where.querySelector(".node-note") || { textContent: "" }).textContent).find(Boolean) || "";
  if (scenario.draft) {  // the "+" menu's "Draft key ideas", offered only while the node has none
    const offer = context.studioKeyIdeas && context.studioKeyIdeas();
    out.draftOffered = !!offer;
    if (offer) await offer.draft();
    out.note = note();
  }
  if (scenario.press) {  // buttons by their labels, in order: a decision, then Record
    const why = everything().find((x) => x.attrs.class === "review-why");
    if (why && scenario.rationale) why.value = scenario.rationale;
    for (const label of [].concat(scenario.press)) {
      const button = everything().find((x) => x.tag === "button" && x.textContent === label);
      if (!button) throw new Error(`no button ${label}`);
      await button.onclick();
    }
    out.note = note();
  }
  // the review is a sheet in the agent panel (#review-card); the rest is the node panel
  const review = card.querySelector(".node-review") || { text: () => "", all: () => [] };
  out.review = review.text();
  out.reviewLinks = review.all().filter((x) => x.tag === "a").map((x) => x.attrs.href);
  out.reviewButtons = review.all().filter((x) => x.tag === "button").map((x) => x.textContent);
  out.buttons = panel.all().filter((x) => x.tag === "button").map((x) => x.textContent);
  out.text = panel.text();
  out.katex = katexCalls;
  // every maths span in the review sheet: its class and its text
  out.math = review.all().filter((x) => x.tag === "span" && String(x.attrs.class || "").startsWith("math")).map((x) => ({ class: x.attrs.class, text: x.textContent, title: x.attrs.title || null }));
  console.log(JSON.stringify(out));
})();
