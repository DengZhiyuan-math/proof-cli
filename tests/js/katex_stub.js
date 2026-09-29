// The pages' KaTeX for the fake-DOM harnesses (ADR-0013): the vendored katex.min.js parses each
// formula for real, so a malformed one throws exactly as it would in the browser; instead of
// building KaTeX's DOM (which the fake DOM can't hold) it writes a marker the tests can read.
const path = require("path");

const real = require(path.join(__dirname, "../../src/proof_cli/studio/static/vendor/katex.min.js"));

module.exports = function katexStub(calls) {
  return {
    version: real.version,
    render(tex, node, options) {
      calls.push({ tex, displayMode: !!options.displayMode });
      real.renderToString(tex, options);  // throws a ParseError on a malformed formula
      node.textContent = `[katex${options.displayMode ? " display" : ""}: ${tex}]`;
    },
  };
};
