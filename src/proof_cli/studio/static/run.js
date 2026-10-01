/* The studio's centre: the Proof agent's run on this node, under the researcher's eye (spec #145, decided in
   #144 and #142). Reads api/agent/run and api/agent/log; renders the run card — status, role and step, the
   plan, the oversight actions — and the work log, in time order, with the roles' reports, what they did
   through `proof`, and each turn's conversation folded under it. Nothing here drives the agent with a prompt:
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
  const state = { run: null, log: [], turns: [], folder: "", timer: null, redirectBox: null, roleBox: null, shown: "", transcripts: {}, following: null, followed: new Set() };

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
      if (run.redirect && run.redirect.text) card.append(h("p", `Redirect waiting: ${run.redirect.text}${run.redirect.role ? ` (for the ${ROLE_WORD[run.redirect.role]})` : ""}`, { class: "run-hint" }));
    }
    const plan = [...state.log].reverse().find((e) => e.kind === "plan");
    if (plan) {
      const steps = h("ol", null, { class: "run-plan" });
      const reports = state.log.filter((e) => e.kind === "step");
      plan.plan.forEach((text, i) => {
        const n = i + 1;
        const last = [...reports].reverse().find((e) => e.step === n);
        steps.append(h("li", text, { class: last ? last.status : "", "data-step": n }));
      });
      card.append(steps);
    }
    card.append(controls(run), note);
    return card;
  }

  // a file the agent changed, opened where files are edited: in VS Code, at its line when one is known
  const fileLink = (rel) => h("a", rel, { href: `vscode://file/${state.folder}/${rel}`, class: "log-file", title: `Open ${rel} in VS Code` });

  // one work-log entry as a line: time, role, what happened, and a link to what it produced
  function entry(e) {
    const li = h("li", null, { class: `log-${e.kind}`, "data-kind": e.kind });
    const when = String(e.at || "").slice(11, 16);
    li.append(h("span", when, { class: "log-time" }), h("span", e.role ? ROLE_WORD[e.role] || e.role : e.by || "", { class: "log-role" }));
    const body = h("span", null, { class: "log-body" });
    if (e.kind === "plan") body.append(`plan: ${(e.plan || []).map((s, i) => `${i + 1}. ${s}`).join("  ")}`);
    else if (e.kind === "step") body.append(`step ${e.step} ${e.status}${e.note ? ` — ${e.note}` : ""}`);
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

  // A turn's conversation as text: what it said, and each step it took — the tool and where (a file, a command),
  // a compile and how it went — so the researcher reads what the agent did, not only what it wrote.
  function transcriptText(events, done) {
    const lines = [];
    for (const ev of events) {
      if (ev.t === "text") lines.push(ev.text || "");
      else if (ev.t === "error") lines.push(`! ${ev.message || ""}`);
      else if (ev.t === "tool") lines.push(`▸ ${ev.name}${ev.summary ? " " + ev.summary : ""}`);
      else if (ev.t === "thinking_start") lines.push("… thinking");
      else if (ev.t === "build") lines.push(`▸ Compile: ${buildWord(ev.result || {})}`);
    }
    return lines.join("\n") || (done ? "(no text in this turn)" : "(nothing said yet)");
  }
  function buildWord(r) {
    const errors = (r.diagnostics || []).filter((d) => d.severity === "error").length;
    return r.cancelled ? "stopped" : r.timed_out ? "timed out" : r.exit === 0 && !errors ? "OK" : errors ? `${errors} error(s)` : `failed (exit ${r.exit})`;
  }

  // The running turn, watched live: its events are read as they come (the server holds the request until
  // there are some) and handed to the Files view (app.js studioLive), which shows the agent at work — the
  // lines it reads, the file as it writes it, the build it ran. One turn is followed at a time.
  async function followLoop(job) {
    const live = globalThis.studioLive;
    if (live) live.reset();
    let after = 0;
    while (state.following === job) {
      let r;
      try { r = await api(`/api/agent/events?job=${job}&after=${after}`); } catch (e) { break; }
      const events = r.events || [];
      after += events.length;
      if (live && events.length) live.feed(events);
      if (r.done || r._status !== 200) break;
    }
    state.followed.add(job);  // once: a turn that ended between two polls is not replayed from its first event
    if (state.following === job) state.following = null;
  }
  function follow() {
    const turn = state.turns.find((t) => !t.done);
    if (turn && state.following !== turn.job && !state.followed.has(turn.job)) { state.following = turn.job; followLoop(turn.job); }
  }

  // a turn of this Start, folded: its role and prompt, the files it changed, and its conversation (the job's events)
  function turnEntry(turn, index) {
    const details = h("details", null, { class: "log-turn", "data-turn": index + 1 });
    const summary = h("summary", `turn ${index + 1} · ${ROLE_WORD[turn.role] || turn.role}${turn.done ? "" : " · running"}`);
    details.append(summary);
    const body = h("div", null, { class: "turn-body" });
    body.append(h("p", turn.prompt, { class: "turn-prompt" }));
    if (turn.changed && turn.changed.length) { const files = h("p", "changed: ", { class: "turn-files" }); turn.changed.forEach((rel, i) => { if (i) files.append(", "); files.append(fileLink(rel)); }); body.append(files); }
    const transcript = h("pre", "", { class: "turn-transcript" });
    body.append(transcript);
    // The conversation is read when the turn is opened. Only a finished turn's is final: a running turn's is read
    // again on every open and every poll until the turn is done, so what is shown is never a stale fragment (reaudit R-P3).
    const cached = state.transcripts[turn.job];
    if (cached) transcript.textContent = cached.text;
    details.loadTranscript = async () => {
      if (!details.open) return;
      const known = state.transcripts[turn.job];
      if (known && known.final) return;
      const r = await api(`/api/agent/events?job=${turn.job}&after=0`);
      const text = transcriptText(r.events || [], turn.done);
      state.transcripts[turn.job] = { text, final: !!turn.done };
      transcript.textContent = text;
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
    const signature = JSON.stringify([state.run, state.log, state.turns]);
    const changed = force || signature !== state.shown;
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(refresh, state.run && state.run.active ? RUN_POLL_MS : IDLE_POLL_MS);
    if (!changed) { followOpenTurns(); return; }
    const kept = keep();
    state.shown = signature;
    const log = h("ol", null, { class: "work-log" });
    for (const e of state.log) log.append(entry(e));
    if (!state.log.length) log.append(h("li", "Nothing yet: the work log fills as the agent reports its plan and its steps.", { class: "log-empty" }));
    const turns = h("div", null, { class: "turns" });
    state.turns.forEach((turn, i) => turns.append(turnEntry(turn, i)));
    pane.replaceChildren(runCard(state.run), h("h3", "Work log", { class: "run-head" }), log,
                         ...(state.turns.length ? [h("h3", "This Start's turns", { class: "run-head" }), turns] : []));
    restore(kept);
  }

  async function refresh(force) {
    const [run, log] = await Promise.all([api("/api/agent/run"), api("/api/agent/log")]);
    state.run = run._status === 200 ? run : null;
    state.log = log._status === 200 && Array.isArray(log.entries) ? log.entries : [];
    state.turns = log._status === 200 && Array.isArray(log.turns) ? log.turns : [];
    state.folder = log.folder || state.folder;
    render(force === true);
    follow();
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
