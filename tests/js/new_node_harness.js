// Runs the map page's real New node form (src/proof_cli/webapp/static/app.js) against stub elements.
// argv[2]: JSON {kind, dependencies: [selected ids], switchTo: kind|null}. Prints the POST body sent.
const fs = require("fs"), path = require("path"), vm = require("vm");

(async () => {
  const scenario = JSON.parse(process.argv[2]);
  const options = scenario.dependencies.map((value) => ({ value, selected: true }));
  const field = (value) => ({
    value, hidden: false, disabled: false, textContent: "", className: "", children: [],
    replaceChildren() {}, reset() {}, setAttribute() {}, append() {}, remove() {},
  });
  const elements = {
    "new-kind": field(scenario.kind), "new-id": field("n1"), "new-statement": field("S"), "new-assumptions": field(""),
    "new-locator": field("doi:x"), "new-version": field("v1"), "new-trust": field(""), "new-source": field(""),
    "new-node": field(""), toasts: field(""),
    "new-dependencies": { ...field(""), get selectedOptions() { return options.filter((o) => o.selected); }, options },
  };
  const sent = [];
  const context = {
    console, location: { href: "" }, setTimeout() {},
    document: { getElementById: (id) => elements[id] || field(""), addEventListener() {}, createElement: () => field("") },
    window: { addEventListener() {} },
    fetch: async (url, init = {}) => {
      if (init.method === "POST") sent.push(JSON.parse(init.body));
      return { json: async () => ({ ok: true, data: { kind: scenario.kind, id: "n1", page: "/studio/n1/" } }) };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../src/proof_cli/webapp/static/app.js"), "utf8"), context);
  if (scenario.switchTo) { elements["new-kind"].value = scenario.switchTo; vm.runInContext("showNewNodeKind()", context); }
  await vm.runInContext("createNode({ preventDefault() {} })", context);
  console.log(JSON.stringify({ sent, selectedAfter: options.filter((o) => o.selected).map((o) => o.value) }));
})();
