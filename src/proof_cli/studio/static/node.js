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
  // what a decision did, under the review sheet
  const reviewNote = h("p", "", { class: "node-note", role: "status" });
  function tellReview(text, bad) { reviewNote.textContent = text; reviewNote.classList.toggle("bad", !!bad); }

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

  // The four fields of a key-ideas summary (ADR-0013), in order. Shown as text: `$…$` stays as written.
  const KEY_IDEAS = [["core_idea", "核心思路"], ["main_steps", "主要步骤"], ["difficulties", "难点"], ["not_covered", "未覆盖"]];

// who wrote a snapshot's key ideas, as its record says (ADR-0013): recorded by the studio, never read from the file
  const KEY_IDEAS_BY = {
    "agent (confirmed by author at request-review)": "由 agent 起草、作者确认 · drafted by the proof agent, confirmed by the author",
    "agent draft, edited by author": "由 agent 起草、作者修改 · the proof agent's draft, edited by the author",
    "author": "作者撰写 · written by the author",
  };

// a field's text with its $…$ and $$…$$ typeset (static/mathtext.js, KaTeX); plain text without it
  const withMath = (node, text) => {
    if (typeof renderMathText === "function") return renderMathText(node, text);
    node.textContent = String(text);
    return node;
  };

  function keyIdeasBlock(summary) {
    const block = h("div", null, { class: "key-ideas" });
    for (const [key, title] of KEY_IDEAS) {
      const text = (summary.fields || {})[key];
      if (!text) continue;
      block.append(h("h5", title), withMath(h("p", null, { class: `key-idea ${key}` }), text));
    }
    if (summary.drafted_by) block.append(h("p", KEY_IDEAS_BY[summary.drafted_by] || summary.drafted_by, { class: "node-hint drafted" }));
    return block;
  }

  // Review in the studio (ADR-0013, amending #71): a sheet over the agent panel, opened from its
  // "+" menu when a snapshot awaits review. The snapshot is read from its key-ideas summary; its
  // frozen LaTeX and archived PDF are a link away, on the node's page. The decisions on offer are
  // one choice, one rationale and one Record. The decision is the researcher's own (ADR-0010): it
  // goes straight to the proof map as this page's identity, never through the agent. Each is sent
  // with the binding of what this page showed, so a change since is refused (STALE_VIEW).
  function reviewSection(view, close) {
    const box = h("div", null, { class: "node-review", id: "node-review" });
    const proof = view.candidate_proof;
    if (!proof) return box;
    const head = h("div", null, { class: "review-head" });
    head.append(h("h4", `Review snapshot v${proof.version}`));
    const done = h("button", "Done", { type: "button", class: "review-done" });
    done.onclick = close;
    head.append(done);
    box.append(head);
    if (proof.unreadable || !proof.sha256) {
      // damaged or missing on disk: every decision on it has stopped counting (see the warnings)
      box.append(h("p", `Snapshot v${proof.version} can't be read: its files or manifest were changed or removed.`, { class: "node-note bad" }));
    } else {
      box.append(h("p", `Snapshot v${proof.version} · SHA-256 ${proof.sha256.slice(0, 12)}…`, { class: "review-snap", title: proof.sha256 }));
      if (proof.key_ideas) box.append(keyIdeasBlock(proof.key_ideas));
      // an older snapshot, frozen before summaries: reviewed as before, from its files
      else box.append(h("p", "这个 snapshot 没有关键思路摘要 · this snapshot has no key-ideas summary: read its frozen files on the node's page.", { class: "node-note no-key-ideas" }));
    }
    const links = h("p", null, { class: "node-review-links" });
    links.append(h("a", `v${proof.version} 的冻结源文件和 PDF · the frozen LaTeX and PDF, on the node's page`, { href: `/#/node/${encodeURIComponent(NODE)}`, class: "node-frozen" }));
    box.append(links);

    const offered = view.decisions || [];
    if (!offered.length) { box.append(h("p", "No decision to make on this node right now.", { class: "node-hint" })); return box; }
    let chosen = null;
    const choices = h("div", null, { class: "review-choices", role: "radiogroup" });
    const why = h("input", null, { class: "review-why", placeholder: "Why" });
    const record = h("button", "Record Decision", { type: "button", class: "primary review-record" });
    record.disabled = true;
    offered.forEach((d) => {
      const label = DECISIONS[`${d.kind}:${d.decision}`] || `${d.kind}: ${d.decision}`;
      const option = h("button", label, { type: "button", role: "radio", class: `review-choice ${d.decision}` });
      option.onclick = () => {
        chosen = { d, label };
        for (const other of choices.children) other.classList.toggle("on", other === option);
        record.disabled = false;
      };
      choices.append(option);
    });
    record.onclick = async () => {
      if (!chosen) return;
      const { d, label } = chosen;
      const on = d.dependency_id ? `${d.target_id} (${d.dependency_id})` : d.target_id;
      if (!confirm(`${label} — on ${on}.\nIt is recorded in the node's reviews.jsonl and committed to git as your identity, not by the agent.`)) return;
      const binds = ["acceptance", "promote", "dependency_revalidation"].includes(d.kind);
      const item = { ...d, rationale: why.value, ...(binds ? { viewed_candidate_proof_sha256: proof.sha256 } : {}) };
      try {
        const outcome = await call("/api/decide", { decisions: [item] });
        const result = outcome.results[0];
        if (result.ok) tellReview(`Recorded: ${label}.`);
        else tellReview(`${result.error.code}: ${result.error.message}${result.error.code === "STALE_VIEW" ? " (the panel has been reloaded)" : ""}`, true);
      } catch (error) { tellReview(`${error.code || "error"}: ${error.message}`, true); }
      await render();
    };
    const send = h("div", null, { class: "review-send" });
    send.append(why, record);
    box.append(choices, send);
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
    claimed: [["path", { d: "M9.4 6.6 4.7 11.3", class: "glyph" }], ["rect", { x: 6.8, y: 5.3, width: 5.6, height: 2.5, rx: 0.6, transform: "rotate(45 9.6 6.55)", class: "glyph-fill" }]],  // a hammer: work in progress
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
    // the working key-ideas.md a review request needs (ADR-0013): drafted by the proof agent when
    // there is none; the author edits it, and requesting review confirms it
    const working = view.key_ideas_working;
    const summary = [];
    const needsDraft = !!(working && !working.exists);
    if (needsDraft) {
      summary.push(h("p", "No key-ideas.md yet: a review request needs one (核心思路, 主要步骤, 难点, 未覆盖). Draft it with the proof agent from its \"+\" menu.", { class: "node-hint" }));
    } else if (working && working.missing.length) {
      summary.push(h("p", `key-ideas.md still leaves ${working.missing.join(" and ")} empty: fill it in before requesting review.`, { class: "node-hint" }));
    }
    panel.replaceChildren(
      h("p", node.statement, { class: "node-statement" }),
      ...node.assumptions.map((a) => h("p", `assuming ${a}`, { class: "node-assumption" })),
      axes(view, claimed),
      h("h4", "Depends on"), deps,
      // what the node needs before review (ADR-0013); drafting it is the proof agent's, from its "+" menu
      ...summary,
      note,
    );
    // the review is a sheet over the agent panel, opened from its "+" menu; the note under it
    // reports what a decision did. The "+" carries a dot while a snapshot awaits a decision.
    const card = document.getElementById("review-card");
    const reviewable = !!(proof && (view.decisions || []).length);
    if (card) {
      card.replaceChildren(reviewSection(view, () => { card.hidden = true; }), reviewNote);
      if (!proof) card.hidden = true;
    }
    const plus = document.getElementById("chat-plus");
    if (plus && plus.classList) plus.classList.toggle("has-review", reviewable);
    // the "+" menu offers the proof agent's draft of key-ideas.md while the node has none
    globalThis.studioKeyIdeas = () => (needsDraft ? {
      draft: async () => {
        if (typeof draftKeyIdeas !== "function") { tell("The agent panel isn't available on this page.", true); return; }
        try { await draftKeyIdeas(); tell("The proof agent drafted key-ideas.md: read and edit it, then request review to confirm it."); }
        catch (error) { tell(`${error.code || "error"}: ${error.message}`, true); }
        await render();
      },
    } : null);
    globalThis.studioReview = () => (reviewable ? {
      version: proof.version,
      check: `Check snapshot v${proof.version} of this node before I decide: read every frozen file, verify each step against the dependencies it cites, and report what does not hold. Change nothing.`,
      open: () => { if (card) card.hidden = false; },
    } : null);
    if (location.hash === "#review" && !render.scrolled) {
      render.scrolled = true;
      // arriving from the map's review list: show the agent panel with the review sheet open
      if (typeof chatHidden === "function") chatHidden(false);
      if (card && proof) card.hidden = false;
    }
  }

  render();
})();
