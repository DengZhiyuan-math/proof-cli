/* The node panel of a node's studio (ADR-0011, #70): what the node is, its state and who holds
   it. The agent-reachable actions of ADR-0006 (claim, split into Claims, request review, open a
   Challenge, record an Evidence check) are the proof agent's, asked of it from its panel (app.js).
   The node's Review decisions, when there are any, go to the proof map's own API (absolute URLs,
   same origin) as the page's git identity. Everything from the project is inserted as text, never as HTML. */
"use strict";

(function nodePanel() {
  const panel = document.getElementById("node-panel");
  if (!panel || !NODE) return;
  const base = `/api/node/${encodeURIComponent(NODE)}`;

  function h(tag, text, attrs) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
  }

  async function call(path, body) {
    const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const response = await fetch(path, options);
    const json = await response.json();
    if (!json.ok) throw Object.assign(new Error(json.error.message), { code: json.error.code });
    return json.data;
  }

  const note = h("p", "", { class: "node-note", role: "status" });
  function tell(text, bad) { note.textContent = text; note.classList.toggle("bad", !!bad); }

  // where a node opens: a theorem, lemma or claim in its studio, an imported result on its own page
  const pageOf = (id, kind) => (kind === "imported_result" ? `/#/node/${encodeURIComponent(id)}` : `/studio/${encodeURIComponent(id)}/`);
  const version = (v) => (v === null || v === undefined ? "—" : `v${v}`);

  // what each Human Review decision means, in the researcher's words
  const DECISIONS = {
    "acceptance:accept": "Accept this snapshot",
    "acceptance:revision-requested": "Request a revision",
    "acceptance:reject": "Reject (final)",
    "promote:promote": "Promote this Claim to a Lemma",
    "dependency_revalidation:reaffirmed": "Lightweight re-review: the proof still holds against the new version",
    "evidence_review:trusted": "Trust this Evidence check",
    "evidence_review:unusable": "Mark this Evidence check unusable",
    "challenge_resolution:dismissed": "Dismiss this Challenge (a false alarm)",
  };

  // Review in the studio (#71): the snapshot under review, every frozen file read-only, its
  // archived PDF apart from the working build, and the decisions this node offers — each sent
  // with the binding of what this page showed, so a change since is refused (STALE_VIEW).
  function reviewSection(view) {
    const box = h("div", null, { class: "node-review", id: "node-review" });
    box.append(h("h4", "Review"));
    const proof = view.candidate_proof;
    if (!proof) { box.append(h("p", "No snapshot has been requested for review yet.", { class: "node-hint" })); return box; }
    if (proof.unreadable || !proof.sha256) {
      // damaged or missing on disk: every decision on it has stopped counting (see the warnings)
      box.append(h("p", `Snapshot v${proof.version} can't be read: its files or manifest were changed or removed.`, { class: "node-note bad" }));
    } else {
      box.append(h("p", `Snapshot v${proof.version} · SHA-256 ${proof.sha256.slice(0, 12)}…`, { title: proof.sha256 }));
    }
    const files = h("p", null, { class: "node-files" });
    for (const [rel, text] of Object.entries(proof.files || {})) {
      const open = h("button", rel, { type: "button", title: "Open read-only" });
      open.onclick = () => (typeof openReadOnly === "function" ? openReadOnly(`v${proof.version} · ${rel}`, text) : null);
      files.append(open);
    }
    box.append(files);
    if (view.pdfs && view.pdfs.snapshot) box.append(h("a", "PDF archived with this snapshot", { href: `${base}/pdf/snapshot`, target: "_blank", rel: "noopener" }));
    else box.append(h("p", "No PDF was archived with this snapshot (the build wasn't current when review was requested).", { class: "node-hint" }));
    box.append(h("p", "The PDF pane shows the working build, which may be newer than this snapshot.", { class: "node-hint" }));
    for (const d of view.decisions || []) {
      const row = h("div", null, { class: "node-decision" });
      const label = DECISIONS[`${d.kind}:${d.decision}`] || `${d.kind}: ${d.decision}`;
      const why = h("input", null, { placeholder: "why" });
      const record = h("button", label, { type: "button" });
      record.onclick = async () => {
        const on = d.dependency_id ? `${d.target_id} (${d.dependency_id})` : d.target_id;
        if (!confirm(`${label} — on ${on}.\nIt is recorded in the node's reviews.jsonl and committed to git as your identity.`)) return;
        const binds = ["acceptance", "promote", "dependency_revalidation"].includes(d.kind);
        const item = { ...d, rationale: why.value, ...(binds ? { viewed_candidate_proof_sha256: proof.sha256 } : {}) };
        try {
          const outcome = await call("/api/decide", { decisions: [item] });
          const result = outcome.results[0];
          if (result.ok) tell(`Recorded: ${label}.`);
          else tell(`${result.error.code}: ${result.error.message}${result.error.code === "STALE_VIEW" ? " (the panel has been reloaded)" : ""}`, true);
        } catch (error) { tell(`${error.code || "error"}: ${error.message}`, true); }
        await render();
      };
      row.append(record, why);
      box.append(row);
    }
    if (!(view.decisions || []).length) box.append(h("p", "No decision to make on this node right now.", { class: "node-hint" }));
    return box;
  }

  // the node's three state axes, one chip each (never folded into one status), plus its claim
  // Each state as the proof map's icon for it and its word, in its colour (the map's seven states:
  // ready, in progress, blocked, awaiting review, accepted, rejected, needs attention).
  const VALUE_STATE = {
    claimed: "claimed", "review-needed": "review", "revision-requested": "review", blocked: "blocked",
    accepted: "accepted", reviewed: "accepted", rejected: "rejected", "no-longer-callable": "rejected",
    unverifiable: "attention", "potentially-stale": "attention", challenged: "attention",
  };
  const GLYPHS = {
    claimed: [["circle", { cx: 8, cy: 6.1, r: 1.9, class: "glyph-fill" }], ["path", { d: "M4.6 11.9a3.4 3.4 0 0 1 6.8 0z", class: "glyph-fill" }]],
    blocked: [["rect", { x: 5.2, y: 7.3, width: 5.6, height: 4.2, rx: 1, class: "glyph-fill" }], ["path", { d: "M6.4 7.3V6.1a1.6 1.6 0 0 1 3.2 0v1.2", class: "glyph" }]],
    review: [["path", { d: "M8 4.6V8l2.3 1.5", class: "glyph" }]],
    accepted: [["path", { d: "M4.9 8.3 7 10.4l4.2-4.6", class: "glyph" }]],
    rejected: [["path", { d: "M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8", class: "glyph" }]],
    attention: [["path", { d: "M8 5.6v3.9", class: "glyph" }], ["circle", { cx: 8, cy: 12, r: 1, class: "glyph-fill" }]],
    open: [],
  };
  const SVG_NS = "http://www.w3.org/2000/svg";
  function icon(kind) {
    if (!document.createElementNS) return null;  // no SVG here: the word alone says it
    const make = (tag, attrs) => { const e = document.createElementNS(SVG_NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
    const box = make("svg", { viewBox: "-1 -1 18 18", class: `status-icon ${kind}`, "aria-hidden": "true" });
    box.append(kind === "attention" ? make("path", { d: "M8 1.1c.5 0 .95.27 1.2.72l6.1 10.9c.52.93-.15 2.08-1.2 2.08H1.9c-1.05 0-1.72-1.15-1.2-2.08L6.8 1.82C7.05 1.37 7.5 1.1 8 1.1z", class: "disc" }) : make("circle", { cx: 8, cy: 8, r: 8, class: "disc" }));
    for (const [tag, attrs] of GLYPHS[kind] || []) box.append(make(tag, attrs));
    return box;
  }

  // the node's three state axes and who holds it, one chip each (never folded into one status)
  function axes(view, claimed) {
    const box = h("div", null, { class: "node-axes" });
    const chip = (value, text) => {
      const kind = VALUE_STATE[value] || "open";
      const span = h("span", null, { class: `state-${kind}`, title: text });
      const mark = icon(kind);
      if (mark) span.append(mark);
      span.append(text);
      box.append(span);
    };
    // who holds the node is a state only (the proof agent claims through `proof`): a claimed
    // node's workflow chip names its holder, and any other node says whether someone holds it
    if (view.workflow_state !== "claimed") chip(view.workflow_state, view.workflow_state);
    chip(view.acceptance_state, view.acceptance_state);
    chip(view.integrity_state, view.integrity_state);
    chip(view.claim ? "claimed" : "unclaimed", claimed);
    return box;
  }

  async function render() {
    let view;
    try { view = await call(base); } catch (error) { panel.replaceChildren(h("p", `${error.code || "error"}: ${error.message}`)); return; }
    const node = view.node;
    document.title = `${node.id} · proof studio`;
    const name = document.getElementById("projname");
    if (name) name.textContent = `${node.kind} · ${node.id}`;
    const deps = h("ul", null, { class: "node-deps" });
    for (const d of view.dependencies) {
      const li = h("li");
      li.append(h("a", d.node_id, { href: pageOf(d.node_id, d.kind) }));
      if (d.kind === "imported_result") li.append(" · imported result");
      else if (d.pin) li.append(` · pinned ${version(d.pin.pinned_version)} · accepted ${version(d.accepted_version)}${d.current === false ? " · interface changed" : ""}`);
      else li.append(" · not pinned yet");
      if (d.remedy) li.append(` — needs ${d.remedy === "new-candidate-proof" ? "a new Candidate proof" : "a Lightweight re-review"}`);
      deps.append(li);
    }
    if (!view.dependencies.length) deps.append(h("li", "no dependencies"));
    const claimed = view.claim ? `claimed by ${view.claim.claimant_id}` : "unclaimed";
    const proof = view.candidate_proof;
    panel.replaceChildren(
      h("p", node.statement, { class: "node-statement" }),
      ...node.assumptions.map((a) => h("p", `assuming ${a}`, { class: "node-assumption" })),
      axes(view, claimed),
      h("h4", "Depends on"), deps,
      reviewSection(view),
      note,
      h("p", null, { class: "node-links" }),
    );
    if (location.hash === "#review" && !render.scrolled) {
      render.scrolled = true;
      const review = panel.querySelector(".node-review");
      if (review && review.scrollIntoView) review.scrollIntoView();
    }
    const links = panel.querySelector(".node-links");
    links.append(h("a", "Review history and details", { href: `/#/node/${encodeURIComponent(node.id)}` }), " · ", h("a", "Proof map", { href: "/" }));
  }

  render();
})();
