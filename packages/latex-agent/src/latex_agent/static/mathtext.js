/* Text with maths (ADR-0013): a key-ideas field's text, with inline `$…$` and display `$$…$$`
   typeset by the vendored KaTeX (static/vendor/katex.min.js) and everything else inserted as
   text, never as HTML. KaTeX builds DOM nodes and sets their styles through the CSSOM, which
   the pages' Content-Security-Policy allows. A formula KaTeX can't parse, or a page without
   KaTeX, shows as the literal text it was written as: rendering never throws. */
"use strict";

// $$…$$ first, then $…$; `\$` is a dollar sign, not a delimiter
const MATH_SEGMENTS = /\$\$([\s\S]+?)\$\$|\$((?:\\\$|[^$\n])+?)\$/g;

function renderMathText(target, text) {
  const source = String(text == null ? "" : text);
  const tex = typeof katex !== "undefined" && katex && typeof katex.render === "function" ? katex : null;
  let last = 0;
  for (const match of source.matchAll(MATH_SEGMENTS)) {
    if (match.index > last) target.append(source.slice(last, match.index));
    const display = match[1] !== undefined;
    const formula = display ? match[1] : match[2];
    const span = document.createElement("span");
    span.setAttribute("class", display ? "math display" : "math");
    try {
      if (!tex) throw new Error("KaTeX isn't loaded");
      tex.render(formula, span, { displayMode: display, throwOnError: true, strict: "ignore", trust: false, output: "htmlAndMathml" });
    } catch (error) {
      // shown exactly as written, and marked, so a reader can see the formula didn't render
      span.textContent = match[0];  // drops anything KaTeX built before it failed
      span.setAttribute("class", "math unrendered");
      span.setAttribute("title", error && error.message ? String(error.message) : "not rendered");
    }
    target.append(span);
    last = match.index + match[0].length;
  }
  if (last < source.length) target.append(source.slice(last));
  return target;
}
