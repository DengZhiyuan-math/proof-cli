/* The proof map's status icons (issue #157), defined once: the map page (its legend, the cards,
   the tree, an imported result's page) and the studio's node panel all draw them from here. The
   status itself, its word and its kind, is the server's (webapp/node_status.py): no page derives
   its own. SF Symbols' ".circle.fill" style: a filled disc and a white glyph on a 16 × 16 box; a
   warning is a triangle, like the system's. */
"use strict";

// each kind, in the legend's order: what the legend calls it, and its glyph
var STATUS_KINDS = {
  ready: { label: "Ready to start", glyph: [["path", { d: "M6.4 4.9v6.2L11.3 8z", class: "glyph-fill" }]] },
  claimed: { label: "In progress", glyph: [["path", { d: "M9.4 6.6 4.7 11.3", class: "glyph" }], ["rect", { x: 6.8, y: 5.3, width: 5.6, height: 2.5, rx: 0.6, transform: "rotate(45 9.6 6.55)", class: "glyph-fill" }]] },  // a hammer: work in progress
  blocked: { label: "Blocked", glyph: [["rect", { x: 5.2, y: 7.3, width: 5.6, height: 4.2, rx: 1, class: "glyph-fill" }], ["path", { d: "M6.4 7.3V6.1a1.6 1.6 0 0 1 3.2 0v1.2", class: "glyph" }]] },
  review: { label: "Awaiting review", glyph: [["path", { d: "M8 4.6V8l2.3 1.5", class: "glyph" }]] },
  accepted: { label: "Accepted", glyph: [["path", { d: "M4.9 8.3 7 10.4l4.2-4.6", class: "glyph" }]] },
  rejected: { label: "Rejected", glyph: [["path", { d: "M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8", class: "glyph" }]] },
  attention: { label: "Needs attention", glyph: [["path", { d: "M8 5.6v3.9", class: "glyph" }], ["circle", { cx: 8, cy: 12, r: 1, class: "glyph-fill" }]] },
  open: { label: "Open", glyph: [] },  // a plain grey disc
};

// an axis value (a workflow, acceptance or integrity state) as the kind its chip is drawn in.
// Revision requested is back to work, not awaiting review: a neutral chip (issue #157).
var STATUS_OF_VALUE = {
  frontier: "ready", claimed: "claimed", "review-needed": "review", blocked: "blocked",
  accepted: "accepted", reviewed: "accepted", "trusted-by-rule": "accepted", rejected: "rejected", "no-longer-callable": "rejected",
  unverifiable: "attention", "potentially-stale": "attention", challenged: "attention",
};

// the shapes of a kind's icon, as [tag, attributes]: its disc (or triangle), then its glyph
function statusShapes(kind) {
  const disc = kind === "attention"
    ? ["path", { d: "M8 1.1c.5 0 .95.27 1.2.72l6.1 10.9c.52.93-.15 2.08-1.2 2.08H1.9c-1.05 0-1.72-1.15-1.2-2.08L6.8 1.82C7.05 1.37 7.5 1.1 8 1.1z", class: "disc" }]
    : ["circle", { cx: 8, cy: 8, r: 8, class: "disc" }];
  return [disc, ...((STATUS_KINDS[kind] || STATUS_KINDS.open).glyph)];
}

// what a node's status shows: its own mark, and a frontier node's Ready mark beside a warning,
// never replaced by it (ADR-0008)
function statusMarks(status, frontier) {
  const marks = [{ kind: status.kind, text: status.text }];
  if (frontier && status.kind !== "ready") marks.push({ kind: "ready", text: "Ready" });
  return marks;
}
