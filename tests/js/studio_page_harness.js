// Runs pieces of the studio page's real code against a minimal DOM. argv[2]: JSON {case, ...}.
//  - "agent-edit": app.js's tabs, its live marks (AH), the agent's view (AV) and studioLive, sliced from the
//    file as it is. The researcher has `active` open; the agent's turn edits `edited`; then the researcher
//    clicks that file's tab (or, with then: "reset", a new Start begins). Prints what the editor showed.
//  - "pdf-links": pdfview.js's PV.links over a page whose annotations are `annots`. Prints the links drawn.
const fs = require("fs"), path = require("path"), vm = require("vm");
const STATIC = path.join(__dirname, "../../src/proof_cli/studio/static");
const scenario = JSON.parse(process.argv[2]);

class El {
  constructor(tag) { this.tag = tag || "div"; this.children = []; this.dataset = {}; this.style = {}; this.hidden = false; this.innerHTML = ""; this.textContent = ""; this.listeners = {}; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  appendChild(x) { this.children.push(x); return x; }
  get classList() { return { add() {}, remove() {}, toggle() {} }; }
  setAttribute() {}
}

// A CodeMirror document over plain text: what the sliced code asks of one.
class Doc {
  constructor(text) { this.text = text; this.classes = []; this.gen = 0; }
  getValue() { return this.text; }
  setValue(t) { this.text = t; }
  lineCount() { return this.text.split("\n").length; }
  posFromIndex(i) { const before = this.text.slice(0, Math.max(0, i)).split("\n"); return { line: before.length - 1, ch: before[before.length - 1].length }; }
  addLineClass(line, where, cls) { this.classes.push([line, cls]); return line; }
  removeLineClass(line, where, cls) { this.classes = this.classes.filter(([l, c]) => !(l === line && c === cls)); }
  changeGeneration() { return this.gen; }
  isClean() { return true; }
  markText() { return { clear() {} }; }
  replaceRange(t, pos) { this.text += t; }
  setOption() {} refresh() {} scrollIntoView() {}
  getScrollInfo() { return { clientHeight: 300 }; }
}

async function agentEdit() {
  const files = scenario.files;  // path -> text on disk
  const els = {};
  const $ = (sel) => (els[sel] ||= new El());
  const editor = { doc: null, swapDoc(d) { this.doc = d; }, setOption() {}, getWrapperElement: () => ({ style: {} }), focus() {}, refresh() {},
                   lineCount() { return this.doc.lineCount(); }, setCursor(p) { this.cursor = p; }, charCoords: () => ({ top: 0 }), scrollTo() {},
                   getScrollInfo: () => ({ clientHeight: 300 }), addLineClass() {}, removeLineClass() {} };
  const CodeMirror = (where, opts) => new Doc("");
  CodeMirror.Doc = (text) => new Doc(text);
  const views = [];
  const context = {
    $, cm: editor, CodeMirror, S: { files: Object.keys(files).map((p) => ({ path: p })), tabs: [], active: null, diagnostics: [] },
    api: async (url) => { const p = decodeURIComponent(url.split("path=")[1] || ""); return p in files ? { _status: 200, content: files[p], mtime: 1 } : { _status: 404 }; },
    poll: async () => {}, showCentre: (v) => views.push(v), applyDiagnostics() {}, renderTree() {}, showBanner() {}, toast() {}, showBuild() {},
    store: { get: () => null, set() {} }, esc: (s) => String(s), CSS: { escape: (s) => s },
    document: { querySelectorAll: () => [] }, setTimeout: (fn) => setImmediate(fn), clearTimeout() {}, confirm: () => true,
    saveTab: async () => true, scheduleSave() {},
  };
  const app = fs.readFileSync(path.join(STATIC, "app.js"), "utf8");
  const slice = (from, to) => {
    const i = app.indexOf(from), j = app.indexOf(to, i);
    if (i < 0 || j < 0) throw new Error(`app.js no longer has ${from} … ${to}`);
    return app.slice(i, j);
  };
  vm.createContext(context);
  vm.runInContext([
    slice("function modeFor(path)", "/* ------------------------------------------------------------------ save & external changes */"),
    slice("const AH = {", "async function chatSend()"),
    slice("const liveNames = new Map();", "\n};") + "\n};",
    "globalThis.AH = AH; globalThis.AV = AV;",
  ].join("\n"), context);
  const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(setImmediate); };
  const seen = () => ({
    active: context.S.active, shown: editor.doc && editor.doc.getValue(), tabs: context.S.tabs.map((t) => t.path),
    tabbar: $("#tabs").innerHTML.replace(/\s+/g, " "), views: [...views], cursor: editor.cursor || null,
  });

  await context.openFile(scenario.active, undefined, false);  // the researcher's file, in the editor
  views.length = 0;
  context.studioLive.feed([
    { t: "tool_start", id: "e1", name: "Edit" },
    { t: "tool_live", id: "e1", path: scenario.edited, old: scenario.old, old_done: true, text: scenario.new },
  ]);
  await settle();
  files[scenario.edited] = scenario.after;  // what the agent's edit leaves on disk
  context.studioLive.feed([{ t: "tool_result", id: "e1", error: false }]);
  await settle();
  const afterEdit = seen();
  if (scenario.then === "reset") context.studioLive.reset();  // a new Start begins
  else await context.openFile(scenario.edited);  // the researcher clicks the offered tab
  return [afterEdit, seen()];
}

async function pdfLinks() {
  const context = { URL, pdfjsLib: { GlobalWorkerOptions: {} }, document: { createElement: (tag) => new El(tag) }, window: {}, $: () => new El() };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(STATIC, "pdfview.js"), "utf8") + "\nglobalThis.PV = PV;", context);
  const div = new El();
  const pv = { div, vp: { convertToViewportRectangle: (r) => r }, page: { getAnnotations: async () => scenario.annots } };
  await context.PV.links(pv);
  return div.children.map((a) => ({ href: a.href || null, dest: a.dataset.dest || null, target: a.target || null }));
}

(async () => {
  const out = scenario.case === "agent-edit" ? await agentEdit() : await pdfLinks();
  console.log(JSON.stringify(out));
})().catch((error) => { console.error(error); process.exit(1); });
