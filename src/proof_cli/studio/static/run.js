/* The studio's centre: the Proof agent's run on this node, under the researcher's eye (spec #145, decided in
   #144 and #142). Reads api/agent/run and api/agent/log; renders the run card — status, role and step, the
   plan, the oversight actions — and the work log, in time order, with the roles' reports, what they did
   through `proof`, and each turn's conversation folded under its step — read from what the project kept, so the
   turns of earlier Starts are there after a new Start or a restart. Nothing here drives the agent with a prompt:
   Start once, then Pause, Redirect, Resume, Stop and release, Review what it has. Everything from the project
   is inserted as text, never as HTML. Uses common.js's `api`; exposes globalThis.studioRun for the agent
   panel's "+" menu. Harnessed on its own (tests/js/run_pane_harness.js). */
"use strict";

const RUN_POLL_MS = 2000;    // while a run is on: how often the pane reads the run and the log again
const IDLE_POLL_MS = 10000;  // otherwise: a Start from the map or the node page shows up without a reload

(function runPane() {
  const pane = document.getElementById("run-pane");
  if (!pane) return;

  function h(tag, text, attrs) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
  }

  const ROLE_WORD = { prover: "Prover", typesetter: "Typesetter", numerics: "Numerics" };
  const state = { run: null, log: [], folder: "", open: null, read: false, timer: null, redirectBox: null, roleBox: null, shown: "", transcripts: {} };

  const note = h("p", "", { class: "run-note", role: "status" });
  function tell(text, bad) { note.textContent = text; note.setAttribute("class", bad ? "run-note bad" : "run-note"); }

  async function act(action, body) {
    const r = await api(`/api/agent/${action}`, body || {});
    if (r._status >= 400) { tell(`${r.error || "refused"}: ${r.message || ""}`.trim(), true); return r; }
    if (action === "start") tell(`Started as ${r.name || "the agent"}.`);
    else if (action === "review-now") {
      // a review request hands the node over (CONTEXT: a claim ends when its holder requests review): the run ends here,
      // the snapshot is yours to judge, and Start takes the node up again afterwards
      tell(`Snapshot v${r.version} frozen; the run has handed the node over. The review sheet is open.`);
      document.dispatchEvent(new CustomEvent("proof:node-changed", { detail: { review: true } }));
    } else tell(`${action}: ${r.status || "done"}.`);
    await refresh(true);
    return r;
  }

  // the oversight: Start (the whole run, or one role for one turn); then Pause / Resume, Redirect, Review what it has, Stop and release
  function controls(run) {
    const box = h("div", null, { class: "run-controls" });
    const button = (label, action, body, cls) => { const b = h("button", label, { type: "button", class: cls || "" }); b.onclick = () => act(action, body); return b; };
    if (!run || !run.active) {
      box.append(button("Start agent", "start", {}, "primary"));
      if (run && run.status === "release-failed") box.append(button("Stop and release", "release", {}, "danger"));  // try giving it back again
      const role = h("select", null, { class: "run-role", title: "Or one role alone, for one turn" });
      role.append(h("option", "all roles", { value: "" }), ...Object.entries(ROLE_WORD).map(([value, word]) => h("option", `${word} only`, { value })));
      const startRole = h("button", "Start", { type: "button", title: "Start the chosen role alone, for one turn" });
      startRole.onclick = () => act("start", role.value ? { roles: [role.value] } : {});
      box.append(role, startRole);
      return box;
    }
    if (run.status === "paused") box.append(button("Resume", "resume", {}, "primary"));
    else box.append(button("Pause", "pause", {}));
    const redirect = h("input", null, { type: "text", class: "run-redirect", placeholder: "Redirect: one line for its next turn", "aria-label": "Redirect the agent" });
    state.redirectBox = redirect;
    const forRole = h("select", null, { class: "run-redirect-role", title: "For the next turn of this role, or whoever is next" });
    forRole.append(h("option", "next turn", { value: "" }), ...Object.entries(ROLE_WORD).map(([value, word]) => h("option", word, { value })));
    state.roleBox = forRole;
    const send = h("button", "Redirect", { type: "button" });
    send.onclick = () => { if (redirect.value.trim()) act("redirect", { text: redirect.value.trim(), role: forRole.value || null }); };
    box.append(redirect, forRole, send,
               button("Review what it has", "review-now", {}),
               button("Stop and release", "release", {}, "danger"));
    return box;
  }

  function runCard(run) {
    const card = h("section", null, { class: "run-card" });
    const line = h("div", null, { class: "run-line" });
    if (!run || run.status === "idle") {
      line.append(h("span", "No agent is working on this node.", { class: "run-status idle" }));
      card.append(line, h("p", "Start it once: it works the node on its own — the Prover finds the proof, the Typesetter writes it, Numerics computes — and stops when it requests review or needs you.", { class: "run-hint" }));
    } else {
      const where = `${ROLE_WORD[run.role] || run.role || "agent"}${run.step && run.steps ? ` · step ${run.step}/${run.steps}` : ""}`;
      line.append(h("span", run.status, { class: `run-status ${run.status}` }), h("span", where, { class: "run-where" }),
                  h("span", `${run.name || ""} · turn ${run.turns}/${run.turns_max}`, { class: "run-meta" }));
      if (run.reason && !run.active) line.append(h("span", run.reason, { class: "run-reason" }));
      card.append(line);
      if (run.status === "needs-human" && run.decision) card.append(h("p", `Needs you: ${run.decision}`, { class: "run-decision" }));
      if (run.redirect && run.redirect.text) card.append(h("p", `Redirect waiting: ${run.redirect.text}${run.redirect.role ? ` (for the ${ROLE_WORD[run.redirect.role]})` : ""}`, { class: "run-hint" }));
    }
    const plan = [...state.log].reverse().find((e) => e.kind === "plan");
    if (plan) {
      const steps = h("ol", null, { class: "run-plan" });
      const marks = planMarks(plan, state.log.filter((e) => e.kind === "step"));
      plan.plan.forEach((text, i) => {
        const mark = marks[i];
        const li = h("li", text, { class: mark.status, "data-step": i + 1 });
        if (mark.label) li.append(" ", h("span", mark.label, { class: "plan-mark" }));
        steps.append(li);
      });
      card.append(steps);
    }
    card.append(controls(run), note);
    return card;
  }

  // The plan's steps in words, not only in a style (spec #145, story 36): each step's last report — done, stuck — and
  // which is the current step, with the role working it, and which comes next.
  function planMarks(plan, reports) {
    const last = plan.plan.map((_, i) => [...reports].reverse().find((e) => e.step === i + 1) || null);
    const latest = reports[reports.length - 1];
    const current = latest && latest.status === "started" && latest.step <= plan.plan.length ? latest.step : null;
    const after = current || Math.max(0, ...last.map((r, i) => (r && r.status === "done" ? i + 1 : 0)));
    const next = plan.plan.findIndex((_, i) => i + 1 > after && !(last[i] && last[i].status === "done")) + 1 || null;
    return last.map((report, i) => {
      const n = i + 1;
      if (n === current) return { status: "started", label: `current step · ${ROLE_WORD[latest.role] || latest.role || "agent"}` };
      if (report && report.status === "done") return { status: "done", label: "done" };
      if (report && report.status === "stuck") return { status: "stuck", label: "stuck" };
      if (report && report.status === "needs-human") return { status: "stuck", label: "needs you" };
      if (n === next) return { status: "next", label: "next" };
      return { status: "", label: "" };
    });
  }

  // A file the agent changed, opened where files are edited, at the line the turn changed (spec #145, stories 18–19):
  // through the vscode:// scheme, or — when the project names an `[studio] open_command` — by the studio's server running it.
  function fileLink(change) {
    const rel = change.path, line = change.line || 1;
    const how = state.open || { kind: "scheme", url: `vscode://file/${state.folder}` };
    if (how.kind === "command") {
      const link = h("a", rel, { href: "#", class: "log-file", title: `Open ${rel} at line ${line} with: ${how.command}` });
      link.onclick = async (event) => {
        if (event && event.preventDefault) event.preventDefault();
        const r = await api("/api/open", { file: rel, line });
        if (!r.ok) tell(r.error || `the open command failed (exit ${r.exit})`, true);
      };
      return link;
    }
    return h("a", rel, { href: `${how.url}/${rel}:${line}`, class: "log-file", title: `Open ${rel} at line ${line} in VS Code` });
  }

  // one work-log entry as a line: time, role, what happened, and a link to what it produced
  function entry(e) {
    const li = h("li", null, { class: `log-${e.kind}`, "data-kind": e.kind });
    const when = String(e.at || "").slice(11, 16);
    li.append(h("span", when, { class: "log-time" }), h("span", e.role ? ROLE_WORD[e.role] || e.role : e.by || "", { class: "log-role" }));
    const body = h("span", null, { class: "log-body" });
    if (e.kind === "plan") body.append(`plan: ${(e.plan || []).map((s, i) => `${i + 1}. ${s}`).join("  ")}`);
    else if (e.kind === "step") body.append(`step ${e.step} ${e.status === "needs-human" ? "needs you" : e.status}${e.note ? ` — ${e.note}` : ""}`);
    else if (e.kind === "turn") body.append(turnFold(e, false));
    else if (e.kind === "handoff") body.append(`handed off to the ${ROLE_WORD[e.to] || e.to}${e.note ? `: ${e.note}` : ""}`);
    else if (e.kind === "split") body.append("split into ", ...(e.nodes || []).flatMap((id, i) => [i ? ", " : "", h("a", id, { href: `/studio/${encodeURIComponent(id)}/` })]));
    else if (e.kind === "review-requested") body.append("requested review of ", h("a", `snapshot v${e.version}`, { href: `/#/node/${encodeURIComponent(NODE)}`, title: "The frozen files, on the node's page" }));
    else if (e.kind === "evidence") body.append("Evidence check ", h("a", e.outcome, { href: `/#/node/${encodeURIComponent(NODE)}`, title: "On the node's page" }));
    else if (e.kind === "fog") body.append("fog ", h("a", e.fog_id, { href: `/#/fog/${encodeURIComponent(e.fog_id)}`, title: "In the map's fog drawer" }), `: ${e.text || ""}`);
    else if (e.kind === "experiment") body.append(`Experiment ${e.seq} on `, h("a", e.fog_id, { href: `/#/fog/${encodeURIComponent(e.fog_id)}` }), `: ${e.outcome}`);
    else if (e.kind === "dependencies") body.append(`dependency ${e.change}: `, h("a", e.dependency, { href: `/studio/${encodeURIComponent(e.dependency)}/` }));
    else if (e.kind === "claimed") body.append("took the node");
    else body.append(String(e.kind));
    li.append(body);
    return li;
  }

  // A turn, folded under its step (spec #145, story 40): its role, its prompt, the files it changed, and its raw
  // conversation. A finished turn's is read from what the project kept (api/agent/turn), so an earlier Start's
  // turns read the same after a new Start or a restart; the turn running now is read from its job, again on every
  // open and every poll until it is over, so what is shown is never a stale fragment (reaudit R-P3).
  function turnFold(turn, running) {
    const details = h("details", null, { class: "log-turn", "data-turn": turn.turn });
    const where = turn.step ? `step ${turn.step} · ` : "";
    details.append(h("summary", `${where}${ROLE_WORD[turn.role] || turn.role || "agent"}'s turn${running ? " · running" : ""} — its conversation`));
    const body = h("div", null, { class: "turn-body" });
    const prompt = h("p", "", { class: "turn-prompt" });
    body.append(prompt);
    if (turn.changed && turn.changed.length) { const files = h("p", "changed: ", { class: "turn-files" }); turn.changed.forEach((change, i) => { if (i) files.append(", "); files.append(fileLink(change)); }); body.append(files); }
    const transcript = h("pre", "", { class: "turn-transcript" });
    body.append(transcript);
    const show = (known) => { transcript.textContent = known.text; prompt.textContent = known.prompt || ""; };
    if (state.transcripts[turn.turn]) show(state.transcripts[turn.turn]);
    details.loadTranscript = async () => {
      if (!details.open) return;
      const known = state.transcripts[turn.turn];
      if (known && known.final) return show(known);
      const r = running ? await api(`/api/agent/events?job=${turn.job}&after=0`) : await api(`/api/agent/turn?turn=${encodeURIComponent(turn.turn)}`);
      const said = (r.events || []).filter((ev) => ev.t === "text" || ev.t === "error").map((ev) => ev.text || ev.message || "").join("\n");
      const kept = { text: said || (running ? "(nothing said yet)" : r._status === 200 ? "(no text in this turn)" : "(this turn's conversation was not kept)"),
                     prompt: r.prompt || "", final: !running && r._status === 200 };
      state.transcripts[turn.turn] = kept;
      show(kept);
    };
    details.addEventListener("toggle", details.loadTranscript);
    details.append(body);
    return details;
  }

  // What the researcher has in hand across a rebuild: the redirect being typed (and its role, and the focus),
  // and the turns being read. A poll that finds nothing new rebuilds nothing at all (audit P3).
  function keep() {
    return {
      redirect: state.redirectBox ? state.redirectBox.value : "", role: state.roleBox ? state.roleBox.value : "",
      focused: !!(state.redirectBox && document.activeElement === state.redirectBox),
      open: Array.from(pane.querySelectorAll("details[open]")).map((d) => d.getAttribute("data-turn")),
    };
  }
  function restore(kept) {
    if (state.redirectBox && kept.redirect) state.redirectBox.value = kept.redirect;
    if (state.roleBox && kept.role) state.roleBox.value = kept.role;
    if (state.redirectBox && kept.focused) state.redirectBox.focus();
    for (const d of pane.querySelectorAll("details")) if (kept.open.includes(d.getAttribute("data-turn"))) { d.open = true; d.loadTranscript(); }
  }
  function followOpenTurns() {  // a poll with no news still reads on in the conversations that are open and not yet final
    for (const d of pane.querySelectorAll("details[open]")) d.loadTranscript();
  }

  function render(force) {
    const signature = JSON.stringify([state.run, state.log]);
    const changed = force || signature !== state.shown;
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(refresh, state.run && state.run.active ? RUN_POLL_MS : IDLE_POLL_MS);
    if (!changed) { followOpenTurns(); return; }
    const kept = keep();
    state.shown = signature;
    const log = h("ol", null, { class: "work-log" });
    for (const e of state.log) log.append(entry(e));
    const now = state.run;
    if (now && now.active && now.turn && now.job && !state.log.some((e) => e.kind === "turn" && e.turn === now.turn)) {
      // the turn running now: under the step it is on, read from its job until it is recorded
      const li = h("li", null, { class: "log-turn-running", "data-kind": "turn" });
      li.append(h("span", "now", { class: "log-time" }), h("span", ROLE_WORD[now.role] || now.role || "", { class: "log-role" }),
                h("span", null, { class: "log-body" }));
      li.children[li.children.length - 1].append(turnFold({ turn: now.turn, job: now.job, role: now.role, step: now.step }, true));
      log.append(li);
    }
    if (!log.children.length) log.append(h("li", "Nothing yet: the work log fills as the agent reports its plan and its steps.", { class: "log-empty" }));
    pane.replaceChildren(runCard(state.run), h("h3", "Work log", { class: "run-head" }), log);
    restore(kept);
  }

  async function refresh(force) {
    const [run, log] = await Promise.all([api("/api/agent/run"), api("/api/agent/log")]);
    state.run = run._status === 200 ? run : null;
    state.log = log._status === 200 && Array.isArray(log.entries) ? log.entries : [];
    state.folder = log.folder || state.folder;
    state.open = (log._status === 200 && log.open) || state.open;
    // A studio with no agent at work opens on "Start agent on this node", whatever Files tab was remembered
    // (spec #145, story 42); only a link to #files, or a run under way, leaves the remembered view
    if (!state.read && !(state.run && state.run.active) && location.hash !== "#files" && typeof showCentre === "function") showCentre("run", false);
    state.read = true;
    render(force === true);
  }

  globalThis.studioRun = {
    state: () => state.run,
    start: (roles, redirect) => act("start", { ...(roles && roles.length ? { roles } : {}), ...(redirect ? { redirect } : {}) }),
    pause: () => act("pause", {}), resume: () => act("resume", {}), release: () => act("release", {}),
    redirect: (text, role) => act("redirect", { text, role: role || null }),
    reviewNow: () => act("review-now", {}),
    focusRedirect: () => { if (state.redirectBox) state.redirectBox.focus(); },
    refresh,
  };
  refresh();
})();
