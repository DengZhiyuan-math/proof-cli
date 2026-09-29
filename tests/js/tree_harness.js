// Runs the map page's real tree view (drawTree in src/proof_cli/webapp/static/app.js) against a minimal DOM.
// argv[2]: JSON {nodes: /api/map's nodes, root: node id}. Prints the drawn tree as nested
// {id, shared, children} objects, one per list item, in the order drawn.
const fs = require("fs"), path = require("path"), vm = require("vm");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.textContent = ""; this.value = ""; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...xs) { this.children.push(...xs); }
  replaceChildren(...xs) { this.children = xs; }
  addEventListener() {}
}

const scenario = JSON.parse(process.argv[2]);
const elements = {};
const context = {
  document: { getElementById: (id) => (elements[id] ||= new El("div")), createElement: (tag) => new El(tag), addEventListener() {} },
  window: { addEventListener() {} },
  location: { href: "" },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/webapp/static/app.js"), "utf8"), context);
context.document.getElementById("tree-root").value = scenario.root;
context.drawTree(scenario.nodes);

const kids = (x) => (typeof x === "object" ? x.children : []);
const read = (li) => {
  const link = li.children.find((x) => typeof x === "object" && x.tag === "a");
  const shared = li.children.some((x) => typeof x === "object" && (x.attrs.class || "").includes("shared-chip"));
  const list = li.children.find((x) => typeof x === "object" && x.tag === "ul");
  return { id: link ? link.textContent : null, shared, children: list ? kids(list).map(read) : [] };
};
console.log(JSON.stringify(kids(kids(elements["map-tree"])[0]).map(read)));
