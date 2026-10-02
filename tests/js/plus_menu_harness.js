// Runs the studio's real "+" menu (src/proof_cli/studio/static/menu.js) against a minimal DOM.
// argv[2]: JSON {run: the run's view, or null for a page with no run; review: {version} or null; press: a label}.
// Prints the menu's rows (heads, items with their disabled state) and what pressing an item called.
const fs = require("fs"), path = require("path"), vm = require("vm");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.className = ""; this.textContent = ""; this.hidden = true; this.disabled = false; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(type, fn) { (this.listeners ||= {})[type] = fn; }
  replaceChildren(...xs) { this.children = xs; }
}

const scenario = JSON.parse(process.argv[2]);
const calls = [];
const els = { "#plus-menu": new El("div"), "#chat-plus": new El("button"), "#review-card": new El("section") };
const context = {
  $: (selector) => els[selector],
  document: { createElement: (tag) => new El(tag), addEventListener() {} },
  showCentre: (which) => calls.push(["showCentre", which]),
  askAgent: (request) => calls.push(["askAgent", request]),
};
if (scenario.run !== null) {
  context.studioRun = {
    state: () => scenario.run,
    start: (roles, task) => calls.push(["start", roles || null, task || null]),
    pause: () => calls.push(["pause"]), resume: () => calls.push(["resume"]), release: () => calls.push(["release"]),
    reviewNow: () => calls.push(["reviewNow"]), focusRedirect: () => calls.push(["focusRedirect"]),
  };
}
if (scenario.review) context.studioReview = () => ({ version: scenario.review.version, check: "Check it.", open: () => calls.push(["openReview"]) });
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/studio/static/menu.js"), "utf8"), context);
context.plusMenu(true);
const menu = els["#plus-menu"];
const rows = menu.children.map((x) => (x.tag === "hr" ? { sep: true } : x.className === "menu-head" ? { head: x.textContent } : { item: x.textContent, disabled: !!x.disabled, title: x.title || "" }));
const out = { open: !menu.hidden, rows };
if (scenario.press) {
  const button = menu.children.find((x) => x.tag === "button" && x.textContent === scenario.press);
  if (!button) throw new Error(`no item ${scenario.press}: ${JSON.stringify(rows)}`);
  button.onclick();
  out.closed = menu.hidden;
}
out.calls = calls;
console.log(JSON.stringify(out));
