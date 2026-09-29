// Runs the map page's real tree view (drawTree in src/proof_cli/webapp/static/app.js) against a minimal DOM.
// argv[2]: JSON {nodes: /api/map's nodes, root: node id}. Prints the drawn tree as nested
// {id, shared_by, children} objects, one per list item, in the order drawn.
const fs = require("fs"), path = require("path"), vm = require("vm");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.textContent = ""; this.value = ""; this.classList = { add() {}, toggle() {} }; }
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

const els = (x) => (typeof x === "object" ? x.children.filter((c) => typeof c === "object") : []);
// each item names its node in data-node-id, and a node with more than one parent carries
// data-shared-by="<N>"; its sub-list is a direct child <ul>
const read = (li) => {
  const list = els(li).find((c) => c.tag === "ul");
  return { id: li.attrs["data-node-id"] ?? null, shared_by: Number(li.attrs["data-shared-by"] ?? 0), children: list ? els(list).map(read) : [] };
};
console.log(JSON.stringify(els(els(elements["map-tree"])[0]).map(read)));
