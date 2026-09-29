/* The node panel of a node's studio (ADR-0011, #70): what the node is, and the agent-reachable
   actions of ADR-0006 — claim or unassign, split into Claims, request review, open a Challenge,
   record an Evidence check. They go to the proof map's own API (absolute URLs, same origin), as
   the page's git identity, with the CLI's effects and refusals. Human Review decisions stay on
   the node's review page. Everything from the project is inserted as text, never as HTML. */
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

  // one action: a button, optional inputs, what to send, what to do with the answer, and
  // (`before`) what must succeed first, or the request isn't sent
  function action(label, path, fields, send, done, before) {
    const box = h("div", null, { class: "node-action" });
    const inputs = fields.map(([key, kind, placeholder, options]) => {
      let input;
      if (kind === "select") {
        input = h("select");
        for (const o of options) input.append(h("option", o, { value: o }));
        box.append(input);
      } else if (kind === "checkbox") {
        input = h("input", null, { type: "checkbox" });
        const label = h("label");
        label.append(input, ` ${placeholder}`);
        box.append(label);
      } else {
        input = h(kind === "textarea" ? "textarea" : "input", null, kind === "textarea" ? { placeholder, rows: 2 } : { placeholder });
        box.append(input);
      }
      input.dataset.key = key;
      return input;
    });
    const button = h("button", label, { type: "button" });
    button.onclick = async () => {
      const values = Object.fromEntries(inputs.map((i) => [i.dataset.key, i.type === "checkbox" ? i.checked : i.value]));
      button.disabled = true;
      try {
        if (before && !(await before())) return;
        const answer = await call(base + path, send(values));
        await done(answer);
      }
      catch (error) { tell(`${error.code || "error"}: ${error.message}`, true); }
      finally { button.disabled = false; }
    };
    box.prepend(button);
    return box;
  }

  // A snapshot is of the files on disk: the editor's unsaved edits are saved first, and if any
  // can't be (a conflict with the disk, an agent editing), nothing is requested (PR #76 audit).
  async function savedFirst() {
    if (typeof saveAll !== "function" || (await saveAll())) return true;
    tell("Some edits couldn't be saved (see the editor), so no review was requested.", true);
    return false;
  }

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

  // Review in the studio (ADR-0013, amending #71): the snapshot under review is read from its
  // key-ideas summary, and decided here — each decision sent with the binding of what this page
  // showed, so a change since is refused (STALE_VIEW). Its frozen LaTeX and archived PDF aren't
  // shown here: the node's page has them.
  function reviewSection(view) {
    const box = h("div", null, { class: "node-review", id: "node-review" });
    box.append(h("h4", "Review"));
    const proof = view.candidate_proof;
    if (!proof) { box.append(h("p", "No snapshot has been requested for review yet.", { class: "node-hint" })); return box; }
    const frozen = h("a", `v${proof.version} 的冻结源文件和 PDF · the frozen LaTeX and PDF, on the node's page`, { href: `/#/node/${encodeURIComponent(NODE)}`, class: "node-frozen" });
    if (proof.unreadable || !proof.sha256) {
      // damaged or missing on disk: every decision on it has stopped counting (see the warnings)
      box.append(h("p", `Snapshot v${proof.version} can't be read: its files or manifest were changed or removed.`, { class: "node-note bad" }));
    } else {
      box.append(h("p", `Snapshot v${proof.version} · SHA-256 ${proof.sha256.slice(0, 12)}…`, { title: proof.sha256 }));
      if (proof.key_ideas) box.append(keyIdeasBlock(proof.key_ideas));
      // an older snapshot, frozen before summaries: reviewed as before, from its files
      else box.append(h("p", "这个 snapshot 没有关键思路摘要 · this snapshot has no key-ideas summary: read its frozen files on the node's page.", { class: "node-note no-key-ideas" }));
    }
    const links = h("p", null, { class: "node-review-links" });
    links.append(frozen);
    box.append(links);
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

  const children = (text) => text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [id, ...rest] = line.split("=");
    return { id: id.trim(), statement: rest.join("=").trim() };
  });

  // the node's three state axes, one chip each (never folded into one status), plus its claim
  function axes(view, claimed) {
    const box = h("div", null, { class: "node-axes" });
    const chip = (text, tone) => box.append(h("span", text, { class: tone || "", title: text }));
    chip(view.workflow_state, ["review-needed", "revision-requested", "blocked"].includes(view.workflow_state) ? "warn" : "");
    chip(view.acceptance_state, ["rejected", "no-longer-callable"].includes(view.acceptance_state) ? "err" : view.acceptance_state === "unverifiable" ? "warn" : ["accepted", "reviewed"].includes(view.acceptance_state) ? "ok" : "");
    chip(view.integrity_state, view.integrity_state === "current" ? "" : "warn");
    chip(claimed, "");
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
    if (working && !working.exists) {
      summary.push(h("p", "No key-ideas.md yet: a review request needs one (核心思路, 主要步骤, 难点, 未覆盖).", { class: "node-hint" }));
      const draft = h("button", "Draft key ideas with the proof agent", { type: "button", title: "The proof agent writes key-ideas.md from proof.tex and the dependencies; you edit it, then request review" });
      draft.onclick = async () => {
        if (typeof draftKeyIdeas !== "function") { tell("The agent panel isn't available on this page.", true); return; }
        draft.disabled = true;
        try { await draftKeyIdeas(); tell("The proof agent drafted key-ideas.md: read and edit it, then request review to confirm it."); }
        catch (error) { tell(`${error.code || "error"}: ${error.message}`, true); }
        finally { draft.disabled = false; }
        await render();
      };
      const box = h("div", null, { class: "node-action" });
      box.append(draft);
      summary.push(box);
    } else if (working && working.missing.length) {
      summary.push(h("p", `key-ideas.md still leaves ${working.missing.join(" and ")} empty: fill it in before requesting review.`, { class: "node-hint" }));
    }
    panel.replaceChildren(
      h("p", node.statement, { class: "node-statement" }),
      ...node.assumptions.map((a) => h("p", `assuming ${a}`, { class: "node-assumption" })),
      axes(view, claimed),
      h("h4", "Depends on"), deps,
      h("h4", "Actions"),
      action("Claim", "/claim", [["reassign", "checkbox", "take it over"]], (v) => ({ reassign: v.reassign }), () => { tell("Claimed."); return render(); }),
      action("Unassign", "/unassign", [], () => ({}), () => { tell("Unassigned."); return render(); }),
      ...summary,
      action("Request review", "/request-review", [["rationale", "textarea", "why this node is scoped to prove directly"]], (v) => ({ rationale: v.rationale }),
        (snapshot) => { tell(`Snapshot v${snapshot.version} awaits review.` + (snapshot.resnapshot_after_loss == null ? "" :
          ` A re-snapshot after loss of v${snapshot.resnapshot_after_loss}: it needs its own review.`) +
          (snapshot.key_ideas_drafted_by && snapshot.key_ideas_drafted_by !== "author" ? ` Its key ideas: ${KEY_IDEAS_BY[snapshot.key_ideas_drafted_by] || snapshot.key_ideas_drafted_by}.` : "")); return render(); }, savedFirst),
      action("Split", "/split", [["children", "textarea", "one child per line: id = statement"], ["reassign", "checkbox", "take it over"]],
        (v) => ({ children: children(v.children), reassign: v.reassign }), (result) => { location.href = result.next; }),
      // one dependency edge at a time (#96): a Lemma the proof came to use, or a dependency handed down to a child
      action("Edit dependencies", "/depend",
        [["op", "select", "", ["add", "remove", "move"]], ["dependency", "input", "dependency id"], ["to", "input", "move onto (one of this node's dependencies)"], ["reassign", "checkbox", "take it over"]],
        (v) => ({ op: v.op, dependency: v.dependency.trim(), to: v.op === "move" ? v.to.trim() : "", reassign: v.reassign }),
        (edit) => { tell(`Dependencies of ${edit.node.id} edited (${edit.op} ${edit.dependency_id}); pins are taken at the next review request.`); return render(); }),
      action("Open a Challenge", "/challenge", [["rationale", "textarea", "what may no longer hold"]], (v) => ({ rationale: v.rationale }),
        () => { tell("Challenge opened."); return render(); }),
      // on the snapshot this page shows: the server records it there, even if a newer one has come since
      ...(proof ? [action(`Record an Evidence check on snapshot v${proof.version}`, "/evidence",
        [["outcome", "select", "", ["passed", "failed", "inconclusive", "error", "stale"]], ["run_by", "input", "which checker ran it"], ["notes", "textarea", "what it found"]],
        (v) => ({ candidate_proof_id: proof.id, outcome: v.outcome, run_by: v.run_by, notes: v.notes }),
        (check) => { tell(`Evidence check ${check.outcome} recorded on snapshot v${proof.version}.`); return render(); })]
        : [h("p", "No snapshot to run an Evidence check on yet.", { class: "node-hint" })]),
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
