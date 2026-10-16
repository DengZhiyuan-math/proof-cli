// Execute the complete studio app against inert DOM/editor and HTTP boundaries.
const fs = require("fs"), vm = require("vm");
const scenario = JSON.parse(process.argv[3]);
class Element {
  constructor() { this.style = {}; this.dataset = {}; this.listeners = {}; this.value = ""; this.innerHTML = ""; this.children = []; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute() {}
  querySelector() { return new Element(); }
  get classList() { return { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
}
const elements = new Map();
const $ = (selector) => {
  if (selector === "#centre-tabs" && !scenario.proof_agent) return null;
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
};
const saved = new Map(Object.entries(scenario.cache || {}));
const requests = [];
const editor = { getWrapperElement: () => new Element(), on() {}, refresh() {}, setOption() {}, getOption: () => ({}) };
const CodeMirror = () => editor;
CodeMirror.commands = {};
const provider = { id: "claude", label: "Claude", available: true, usage_limits: true, ...scenario.provider };
const context = {
  $, CodeMirror,
  Date: class extends Date { static now() { return 2_000_000_000_000; } },
  store: { get: (key, fallback) => saved.has(key) ? saved.get(key) : fallback, set: (key, value) => saved.set(key, value) },
  api: async (url, body) => {
    requests.push({ url, body: body || null });
    if (url === "/api/agent/info") return { providers: [provider], default: "claude", proof_agent: scenario.proof_agent };
    if (url === "/api/agent/usage") return { rate: null };
    if (url.startsWith("/api/agent/account")) return { _status: 200, account: null };
    if (url === "/api/config") return { _status: 200 };
    if (url === "/api/tree") return { _status: 200, root: "fixture", files: [] };
    if (url === "/api/symbols") return { _status: 200, labels: [], outline: [], bibkeys: [], macros: [] };
    throw new Error("Unexpected request: " + url);
  },
  document: { querySelectorAll: () => [], addEventListener() {}, createElement: () => new Element() },
  window: { addEventListener() {} }, location: { hash: "" }, navigator: {},
  PV: { init() {} }, NODE: "fixture", pdfChannel: null,
  esc: (text) => String(text), icon: () => "", keys: (text) => text,
  setInterval() {}, setTimeout() {}, clearTimeout() {},
};
(async () => {
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
  for (let i = 0; i < 10; i++) await new Promise(setImmediate);
  const automatic = [...requests];
  if (scenario.manual) {
    const event = { target: { closest: (selector) => selector === "#quota-refresh" ? $("#quota-refresh") : null } };
    for (const listener of $("#quota").listeners.click) await listener(event);
  }
  console.log(JSON.stringify({ automatic, requests, quota: $("#quota").innerHTML, quotaHidden: $("#quota").hidden }));
})().catch((error) => { console.error(error); process.exit(1); });
