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

  const children = (text) => text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [id, ...rest] = line.split("=");
    return { id: id.trim(), statement: rest.join("=").trim() };
  });

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
      h("p", `${view.workflow_state} · ${view.acceptance_state} · ${view.integrity_state} · ${claimed}`, { class: "node-axes" }),
      h("h4", "Depends on"), deps,
      h("h4", "Actions"),
      action("Claim", "/claim", [["reassign", "checkbox", "take it over"]], (v) => ({ reassign: v.reassign }), () => { tell("Claimed."); return render(); }),
      action("Unassign", "/unassign", [], () => ({}), () => { tell("Unassigned."); return render(); }),
      action("Request review", "/request-review", [["rationale", "textarea", "why this node is scoped to prove directly"]], (v) => ({ rationale: v.rationale }),
        (snapshot) => { tell(`Snapshot v${snapshot.version} awaits review.`); return render(); }, savedFirst),
      action("Split", "/split", [["children", "textarea", "one child per line: id = statement"], ["reassign", "checkbox", "take it over"]],
        (v) => ({ children: children(v.children), reassign: v.reassign }), (result) => { location.href = result.next; }),
      action("Open a Challenge", "/challenge", [["rationale", "textarea", "what may no longer hold"]], (v) => ({ rationale: v.rationale }),
        () => { tell("Challenge opened."); return render(); }),
      // on the snapshot this page shows: the server records it there, even if a newer one has come since
      ...(proof ? [action(`Record an Evidence check on snapshot v${proof.version}`, "/evidence",
        [["outcome", "select", "", ["passed", "failed", "inconclusive", "error", "stale"]], ["run_by", "input", "which checker ran it"], ["notes", "textarea", "what it found"]],
        (v) => ({ candidate_proof_id: proof.id, outcome: v.outcome, run_by: v.run_by, notes: v.notes }),
        (check) => { tell(`Evidence check ${check.outcome} recorded on snapshot v${proof.version}.`); return render(); })]
        : [h("p", "No snapshot to run an Evidence check on yet.", { class: "node-hint" })]),
      note,
      h("p", null, { class: "node-links" }),
    );
    const links = panel.querySelector(".node-links");
    links.append(h("a", "Review and decisions", { href: `/#/node/${encodeURIComponent(node.id)}` }), " · ", h("a", "Proof map", { href: "/" }));
  }

  render();
})();
