/* The studio's centre: the Proof agent's run on this node, under the researcher's eye (spec #145, decided in
   #144 and #142). Reads /api/agent/run and /api/agent/log; renders the run card — status, role and step, the
   plan, the oversight actions — and the work log, in time order, with the roles' reports and what they did
   through `proof`. Nothing here drives the agent with a prompt: Start once, then Pause, Redirect, Resume,
   Stop and release, Review what it has. Everything from the project is inserted as text, never as HTML.
   Exposes globalThis.studioRun for the agent panel's "+" menu. Harnessed on its own (tests/js/run_pane_harness.js). */
"use strict";

(function runPane() {
  const pane = document.getElementById("run-pane");
  if (!pane) return;

  function h(tag, text, attrs) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
  }
  async function call(path, body) {
    const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Prism-Local": "1" }, body: JSON.stringify(body) };
    const response = await fetch(path.replace(/^\//, ""), options);   // relative: this node's /studio/<id>/
    let data = {};
    try { data = await response.json(); } catch { /* non-JSON */ }
    data._status = response.status;
    return data;
  }

  const ROLE_WORD = { prover: "Prover", typesetter: "Typesetter", numerics: "Numerics" };
  const state = { run: null, log: [], timer: null, note: "" };

  const note = h("p", "", { class: "run-note", role: "status" });
  function tell(text, bad) { note.textContent = text; note.setAttribute("class", bad ? "run-note bad" : "run-note"); }

  async function act(action, body) {
    const r = await call(`/api/agent/${action}`, body || {});
    if (r._status >= 400) { tell(`${r.error || "refused"}: ${r.message || ""}`.trim(), true); return r; }
    tell(action === "start" ? `Started as ${r.name || "the agent"}.` : action === "review-now" ? `Snapshot v${r.version} frozen: review it from the "+" menu.` : `${action}: ${r.status || "done"}.`);
    if (action === "review-now" && document.dispatchEvent) document.dispatchEvent(new (globalThis.CustomEvent || Event)("proof:node-changed"));
    await refresh();
    return r;
  }

  // the four actions, and Review what it has (which freezes a snapshot as the researcher)
  function controls(run) {
    const box = h("div", null, { class: "run-controls" });
    const button = (label, action, body, cls) => { const b = h("button", label, { type: "button", class: cls || "" }); b.onclick = () => act(action, body); return b; };
    const active = run && ["running", "pausing", "paused", "starting"].includes(run.status);
    if (!active) {
      box.append(button("Start agent", "start", {}, "primary"));
      const one = h("select", null, { class: "run-role", title: "Or one role alone, for one turn" });
      one.append(h("option", "all roles", { value: "" }), ...Object.entries(ROLE_WORD).map(([value, word]) => h("option", `${word} only`, { value })));
      const go = h("button", "Start", { type: "button", title: "Start the chosen role alone, for one turn" });
      go.onclick = () => act("start", one.value ? { roles: [one.value] } : {});
      box.append(one, go);
      return box;
    }
    if (run.status === "paused") box.append(button("Resume", "resume", {}, "primary"));
    else box.append(button("Pause", "pause", {}));
    const redirect = h("input", null, { type: "text", class: "run-redirect", placeholder: "Redirect: one line for its next turn", "aria-label": "Redirect the agent" });
    const to = h("select", null, { class: "run-redirect-role", title: "For the next turn of this role, or whoever is next" });
    to.append(h("option", "next turn", { value: "" }), ...Object.entries(ROLE_WORD).map(([value, word]) => h("option", word, { value })));
    const send = h("button", "Redirect", { type: "button" });
    send.onclick = () => { if (redirect.value.trim()) act("redirect", { text: redirect.value.trim(), role: to.value || null }); };
    box.append(redirect, to, send, button("Review what it has", "review-now", {}), button("Stop and release", "release", {}, "danger"));
    return box;
  }

  function runCard(run) {
    const card = h("section", null, { class: "run-card" });
    const active = run && ["running", "pausing", "paused", "starting"].includes(run.status);
    const line = h("div", null, { class: "run-line" });
    if (!run || run.status === "idle") {
      line.append(h("span", "No agent is working on this node.", { class: "run-status idle" }));
      card.append(line, h("p", "Start it once: it works the node on its own — the Prover finds the proof, the Typesetter writes it, Numerics computes — and stops when it requests review or needs you.", { class: "run-hint" }));
    } else {
      const where = `${ROLE_WORD[run.role] || run.role || "agent"}${run.step && run.steps ? ` · step ${run.step}/${run.steps}` : ""}`;
      line.append(h("span", run.status, { class: `run-status ${run.status}` }), h("span", where, { class: "run-where" }),
                  h("span", `${run.name || ""} · turn ${run.turns}/${run.turns_max}`, { class: "run-meta" }));
      if (run.reason && !active) line.append(h("span", run.reason, { class: "run-reason" }));
      card.append(line);
      if (run.redirect && run.redirect.text) card.append(h("p", `Redirect waiting: ${run.redirect.text}${run.redirect.role ? ` (for the ${ROLE_WORD[run.redirect.role]})` : ""}`, { class: "run-hint" }));
    }
    const plan = [...state.log].reverse().find((e) => e.kind === "plan");
    if (plan) {
      const steps = h("ol", null, { class: "run-plan" });
      const reports = state.log.filter((e) => e.kind === "step");
      plan.plan.forEach((text, i) => {
        const n = i + 1;
        const last = [...reports].reverse().find((e) => e.step === n);
        const status = last ? last.status : "";
        steps.append(h("li", text, { class: status, "data-step": n }));
      });
      card.append(steps);
    }
    card.append(controls(run), note);
    return card;
  }

  // one work-log entry as a line: time, role, what happened, and a link to what it produced
  function entry(e) {
    const li = h("li", null, { class: `log-${e.kind}`, "data-kind": e.kind });
    const when = String(e.at || "").slice(11, 16);
    li.append(h("span", when, { class: "log-time" }), h("span", e.role ? ROLE_WORD[e.role] || e.role : e.by || "", { class: `log-role ${e.role || ""}` }));
    const body = h("span", null, { class: "log-body" });
    if (e.kind === "plan") body.append(`plan: ${(e.plan || []).map((s, i) => `${i + 1}. ${s}`).join("  ")}`);
    else if (e.kind === "step") body.append(`step ${e.step} ${e.status}${e.note ? ` — ${e.note}` : ""}`);
    else if (e.kind === "handoff") body.append(`handed off to the ${ROLE_WORD[e.to] || e.to}${e.note ? `: ${e.note}` : ""}`);
    else if (e.kind === "split") body.append("split into ", ...(e.nodes || []).flatMap((id, i) => [i ? ", " : "", h("a", id, { href: `/studio/${encodeURIComponent(id)}/` })]));
    else if (e.kind === "review-requested") body.append(`requested review of snapshot v${e.version}`);
    else if (e.kind === "evidence") body.append(`Evidence check ${e.outcome}`);
    else if (e.kind === "fog") body.append(`fog ${e.fog_id}: ${e.text || ""}`);
    else if (e.kind === "experiment") body.append(`Experiment ${e.seq} on ${e.fog_id}: ${e.outcome}`);
    else if (e.kind === "dependencies") body.append(`dependency ${e.change}: ${e.dependency}`);
    else if (e.kind === "claimed") body.append(`took the node`);
    else body.append(String(e.kind));
    li.append(body);
    return li;
  }

  function render() {
    const log = h("ol", null, { class: "work-log" });
    for (const e of state.log) log.append(entry(e));
    if (!state.log.length) log.append(h("li", "Nothing yet: the work log fills as the agent reports its plan and its steps.", { class: "log-empty" }));
    pane.replaceChildren(runCard(state.run), h("h3", "Work log", { class: "run-head" }), log);
    const active = state.run && ["running", "pausing", "paused", "starting"].includes(state.run.status);
    if (state.timer) { clearTimeout(state.timer); state.timer = null; }
    if (active && globalThis.setTimeout) state.timer = setTimeout(refresh, 2000);
  }

  async function refresh() {
    const [run, log] = await Promise.all([call("/api/agent/run"), call("/api/agent/log")]);
    state.run = run._status === 200 ? run : null;
    state.log = log._status === 200 && Array.isArray(log.entries) ? log.entries : [];
    render();
  }

  globalThis.studioRun = {
    state: () => state.run,
    start: (roles, redirect) => act("start", { ...(roles && roles.length ? { roles } : {}), ...(redirect ? { redirect } : {}) }),
    pause: () => act("pause", {}), resume: () => act("resume", {}), release: () => act("release", {}),
    redirect: (text, role) => act("redirect", { text, role: role || null }),
    reviewNow: () => act("review-now", {}),
    refresh,
  };
  refresh();
})();
