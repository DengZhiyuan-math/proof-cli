// Runs the studio's real run pane (src/proof_cli/studio/static/run.js) against a minimal DOM.
// argv[2]: JSON {run, log, press: a button label or a list, redirect: text, role: a select value, answer}.
// Prints what the pane shows and what it posted.
const fs = require("fs"), path = require("path"), vm = require("vm");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.textContent = ""; this.value = ""; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  append(...xs) { this.children.push(...xs); }
  replaceChildren(...xs) { this.children = xs; }
  all() { return this.children.flatMap((x) => (typeof x === "object" ? [x, ...x.all()] : [])); }
  text() { return [this.textContent, ...this.children.map((x) => (typeof x === "object" ? x.text() : String(x)))].filter(Boolean).join(" "); }
  cls() { return String(this.attrs.class || ""); }
}

(async () => {
  const scenario = JSON.parse(process.argv[2]);
  const pane = new El("section"), posted = [], dispatched = [];
  let run = scenario.run, log = scenario.log || [];
  const context = {
    document: { getElementById: (id) => (id === "run-pane" ? pane : null), createElement: (tag) => new El(tag), dispatchEvent: (ev) => { dispatched.push(ev.type); } },
    Event: class { constructor(type) { this.type = type; } },
    setTimeout: () => 0, clearTimeout: () => {},
    fetch: async (url, options = {}) => {
      if (options.method === "POST") {
        posted.push({ url, body: JSON.parse(options.body) });
        const answer = scenario.answer || { status: "running", name: "claude-code", version: 2 };
        if (scenario.after) run = scenario.after;  // what the next read of the run says
        return { status: scenario.refuse ? 409 : 200, json: async () => (scenario.refuse ? { error: "RUN_ACTIVE", message: "already working" } : answer) };
      }
      if (url === "api/agent/run") return { status: 200, json: async () => run };
      if (url === "api/agent/log") return { status: 200, json: async () => ({ entries: log }) };
      return { status: 404, json: async () => ({}) };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/studio/static/run.js"), "utf8"), context);
  for (let i = 0; i < 4; i++) await new Promise(setImmediate);
  const read = () => ({
    text: pane.text(),
    buttons: pane.all().filter((x) => x.tag === "button").map((x) => x.textContent),
    status: (pane.all().find((x) => x.cls().startsWith("run-status")) || { textContent: "" }).textContent,
    where: (pane.all().find((x) => x.cls() === "run-where") || { textContent: "" }).textContent,
    plan: pane.all().filter((x) => x.tag === "li" && x.attrs["data-step"]).map((x) => ({ step: x.attrs["data-step"], text: x.textContent, status: x.cls() })),
    log: pane.all().filter((x) => x.tag === "li" && x.attrs["data-kind"]).map((x) => ({ kind: x.attrs["data-kind"], text: x.text() })),
    links: pane.all().filter((x) => x.tag === "a").map((x) => x.attrs.href),
    note: (pane.all().find((x) => x.cls().startsWith("run-note")) || { textContent: "" }).textContent,
    posted: [...posted], dispatched: [...dispatched],
  });
  const readings = [read()];
  for (const label of [].concat(scenario.press || [])) {
    if (scenario.redirect !== undefined) { const box = pane.all().find((x) => x.cls() === "run-redirect"); if (box) box.value = scenario.redirect; }
    if (scenario.role !== undefined) { for (const sel of pane.all().filter((x) => x.tag === "select")) sel.value = scenario.role; }
    const button = pane.all().find((x) => x.tag === "button" && x.textContent === label);
    if (!button) throw new Error(`no button ${label}: ${JSON.stringify(read().buttons)}`);
    await button.onclick();
    for (let i = 0; i < 4; i++) await new Promise(setImmediate);
    readings.push(read());
  }
  console.log(JSON.stringify(readings));
})().catch((error) => { console.error(error); process.exit(1); });
