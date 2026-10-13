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

  const ROLE_WORD = { prover: "Prover", typesetter: "Typesetter", numerics: "Numerics", verifier: "Verifier", decomposer: "Decomposer" };
  const state = { run: null, log: [], folder: "", open: null, read: false, timer: null, redirectBox: null, roleBox: null, shown: "", transcripts: {}, following: null, followed: new Set(), liveStart: null, coordinator: null, node: null };
  // the Decomposer's offer (ADR-0019 point 20): a Theorem or Lemma not yet split and not yet reviewed — it proposes the
  // split into Claims and the run stops for the researcher to decide
  const decomposable = (node) => !!(node && node.node && ["theorem", "lemma"].includes(node.node.kind) && !(node.node.dependencies || []).length && node.acceptance_state === "unreviewed");
  // this node, from the page's URL (/studio/<id>/): the map's own API is two levels up
  const nodeId = () => decodeURIComponent((location.pathname.match(/\/studio\/([^/]+)\//) || [0, ""])[1]);

  const note = h("p", "", { class: "run-note", role: "status" });
  function tell(text, bad) { note.textContent = text; note.setAttribute("class", bad ? "run-note bad" : "run-note"); }

  // the provider the page has chosen (app.js's select, #chat-provider): a Start runs on it, not on the server's default (#170)
  function chosenProvider() {
    const select = document.getElementById("chat-provider");
    return select && select.value ? select.value : null;
  }

  async function act(action, body) {
    body = body || {};
    if (action === "start" && !body.provider && chosenProvider()) body = { ...body, provider: chosenProvider() };
    const r = await api(`/api/agent/${action}`, body);
    if (r._status >= 400) { tell(`${r.code || "refused"}: ${r.error || ""}`.trim(), true); return r; }
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

  // the Coordinator over this node's subtree (ADR-0019 points 18, 19): only on a node that rests on others; it starts
  // the children's runs on their frontier, the parent's once every child is Accepted, and holds no node itself
  async function coordinate(action, body) {
    body = body || {};
    if (action === "start" && chosenProvider()) body = { ...body, provider: chosenProvider() };
    const r = await api(`../../api/node/${encodeURIComponent(nodeId())}/coordinator/${action}`, body);
    if (r._status >= 400) { const err = r.error && typeof r.error === "object" ? r.error : { code: r.code, message: r.error }; tell(`${err.code || "refused"}: ${err.message || ""}`.trim(), true); return r; }
    tell(action === "start" ? "Pursue started: the agents work everything under this node to the end, and what they leave you is the review queue." : `subtree ${action}: ${(r.data || r).status || "done"}.`);
    await refresh(true);
    return r;
  }

  function coordinatorCard(c) {
    const card = h("section", null, { class: "coordinator-card" });
    const line = h("div", null, { class: "coordinator-line" });
    line.append(h("span", "Subtree", { class: "coordinator-head" }));
    const button = (label, action, cls, title) => { const b = h("button", label, { type: "button", class: cls || "", ...(title ? { title } : {}) }); b.onclick = () => coordinate(action, {}); return b; };
    if (c.status === "release-failed") {  // a Stop that could not give every node back: the way out is Stop again, not a new Start
      line.append(h("span", `release failed — ${c.reason || "a node is still assigned"}`, { class: "coordinator-status release-failed" }),
                  button("Stop subtree", "release", "danger", "Try again to release the run(s) the Coordinator started"));
    } else if (c.settling) {
      line.append(h("span", "finishing the previous Start — wait for its runs to settle", { class: "coordinator-meta" }));
    } else if (!c.active) {
      const sub = c.subtree || {};
      const said = c.status === "idle" ? `${sub.open || 0} open of ${sub.nodes || 0} node(s) under this one` : `${c.status}${c.reason ? ` — ${c.reason}` : ""}`;
      line.append(h("span", said, { class: `coordinator-status ${c.status}` }));
      if (c.can_release) {
        line.append(button("Stop subtree", "release", "danger", "Release the runs this Coordinator started before starting again"));
      } else {
        line.append(button("Pursue", "start", "primary", `Work everything under this node to the end, up to ${c.parallel || 2} runs at a time: split it first if it has no Claims; each node starts once what it rests on is Accepted or Provisional. Nothing waits for you`));
      }
    } else {
      const sub = c.subtree || {};
      const where = c.running && c.running.length ? `running: ${c.running.join(", ")}` : "no run on now";
      line.append(h("span", c.status, { class: `coordinator-status ${c.status}` }),
                  h("span", `${where} · ${(c.accepted || []).length} accepted of ${sub.nodes || 0} · turns ${c.turns}/${c.turns_max}`, { class: "coordinator-meta" }),
                  c.status === "paused" ? button("Resume subtree", "resume", "primary") : button("Pause subtree", "pause", "", "No new node run begins; the running ones hold after their turn"),
                  button("Stop subtree", "release", "danger", "Stop the Coordinator and release every run it started"));
    }
    // the nodes it parked (ADR-0021 point 9): where the agents could not go; the rest went on without them, and each
    // waits in the map's review queue with its attempts
    if ((c.parked || []).length) {
      line.append(h("span", c.parked.map((p) => `${p.node} parked — ${p.reason}`).join("; "), { class: "coordinator-meta coordinator-parked", title: "In the map's review queue, with its attempts" }));
    }
    // the nodes it left for the researcher: a run that ended needing them; the rest goes on without them
    if ((c.held || []).length) {
      line.append(h("span", c.held.map((x) => `${x.node} waits for you — ${x.reason}`).join("; "), { class: "coordinator-meta coordinator-held", title: "The Coordinator does not restart these; open the node to see why" }));
    }
    card.append(line);
    return card;
  }

  // the oversight: Start (the whole run, or one role for one turn); then Pause / Resume, Redirect, Review what it has, Stop and release
  function controls(run) {
    const box = h("div", null, { class: "run-controls" });
    const button = (label, action, body, cls) => { const b = h("button", label, { type: "button", class: cls || "" }); b.onclick = () => act(action, body); return b; };
    if (!run || !run.active) {
      box.append(button("Start agent", "start", {}, "primary"));
      if (decomposable(state.node)) {
        const propose = button("Propose a split", "start", { roles: ["decomposer"] });
        propose.title = "The Decomposer reads the library and the literature, splits this node into the Claims its proof needs, and stops for you to decide (ADR-0019)";
        box.append(propose);
      }
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

  const RECORD_SITE = { _close_note: "its closing note", _suggest: "its suggested redirect", _note_turn: "its turn record" };

  function runCard(run) {
    const card = h("section", null, { class: "run-card" });
    const line = h("div", null, { class: "run-line" });
    if (!run || run.status === "idle") {
      line.append(h("span", "No agent is working on this node.", { class: "run-status idle" }));
      card.append(line, h("p", "Start it once: it works the node on its own — the Prover finds the proof, the Typesetter writes it, Numerics computes, the Verifier reads it against them — and stops when it requests review or needs you.", { class: "run-hint" }));
      if (decomposable(state.node)) card.append(h("p", "Or have the Decomposer propose a split of this node into the Claims its proof needs; it stops for you to read them on the map and decide.", { class: "run-hint" }));
    } else {
      const where = `${ROLE_WORD[run.role] || run.role || "agent"}${run.step && run.steps ? ` · step ${run.step}/${run.steps}` : ""}`;
      line.append(h("span", run.status, { class: `run-status ${run.status}` }), h("span", where, { class: "run-where" }),
                  h("span", `${run.name || ""} · turn ${run.turns}/${run.turns_max}`, { class: "run-meta" }));
      // the Verifier's newest verdict on the working proof (ADR-0019 point 2): the gate the agent's review request waits on
      if (run.verdict) line.append(h("span", `verdict ${run.verdict}`, { class: `run-verdict ${run.verdict}`, title: run.verdict === "passed" ? "The Verifier passed the proof as it stands: the Prover may request review" : "The Verifier's objections are in the work log; the Prover answers them first" }));
      if (run.reason && !run.active) line.append(h("span", run.reason, { class: "run-reason" }));
      card.append(line);
      if (run.status === "needs-human" && run.decision) card.append(h("p", `Needs you: ${run.decision}`, { class: "run-decision" }));
      // the run's own work-log writes that failed this Start (proof-agents#16): held by the run, not in the work log
      const failed = Object.entries(run.record_failed && typeof run.record_failed === "object" ? run.record_failed : {});
      if (failed.length) {
        const list = h("ul", null, { class: "run-record-failed-list" });
        for (const [site, error] of failed) list.append(h("li", `${RECORD_SITE[site] || site} (${site}): ${error}`));
        card.append(h("p", "Not in the work log — the run could not write:", { class: "run-record-failed", title: "Held by this Start only, not saved: it is gone after a new Start or a restart" }), list);
      }
      if (run.redirect && run.redirect.text) card.append(h("p", `Redirect waiting: ${run.redirect.text}${run.redirect.role ? ` (for the ${ROLE_WORD[run.redirect.role]})` : ""}`, { class: "run-hint" }));
      // what the record repeats (ADR-0019 point 17): a suggested redirect for the researcher, who decides — it is sent only by them
      if (run.suggestion) {
        const suggestion = h("p", `The record suggests: ${run.suggestion} `, { class: "run-suggestion" });
        if (run.active) {
          const use = h("button", "Use as redirect", { type: "button", title: "Put it in the redirect box; edit it, then send it" });
          use.onclick = () => { if (state.redirectBox) { state.redirectBox.value = run.suggestion; state.redirectBox.focus(); } };
          suggestion.append(use);
        }
        card.append(suggestion);
      }
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
  // The link is built once, by the server (vscode_url, #147); the page posts to api/open only when a command is set.
  function fileLink(change) {
    const rel = change.path, line = change.line || 1;
    const how = state.open || { kind: "scheme" };
    if (how.kind === "command") {
      const link = h("a", rel, { href: "#", class: "log-file", title: `Open ${rel} at line ${line} with: ${how.command}` });
      link.onclick = async (event) => {
        if (event && event.preventDefault) event.preventDefault();
        const r = await api("/api/open", { file: rel, line });
        if (r._status !== 200) tell(`${r.code || "OPEN_FAILED"}: ${r.error || ""}`.trim(), true);
      };
      return link;
    }
    return change.url ? h("a", rel, { href: change.url, class: "log-file", title: `Open ${rel} at line ${line} in VS Code` }) : h("span", rel, { class: "log-file" });
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
    // ADR-0019: the Verifier's verdict (its objections numbered, in the note) and a role's abandoned attempt
    else if (e.kind === "verdict") body.append(h("span", `verdict ${e.outcome}`, { class: `log-verdict ${e.outcome}` }), e.note ? ` — ${e.note}` : "", e.inputs_sha256 ? h("span", ` · inputs ${String(e.inputs_sha256).slice(0, 8)}`, { class: "log-hash", title: `SHA-256 of the working inputs the Verifier read: ${e.inputs_sha256}` }) : "");
    else if (e.kind === "attempt") body.append(`attempt: ${e.goal || ""}${e.method ? ` (${e.method})` : ""} — failed on ${e.failed_on || "?"}`);
    else if (e.kind === "coordinator") body.append(`coordinator: ${e.note || ""}`);  // the subtree's Coordinator, on its root's log (ADR-0019 point 18)
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
  function transcriptText(events) {
    const lines = [];
    for (const ev of events) {
      if (ev.t === "text") lines.push(ev.text || "");
      else if (ev.t === "error") lines.push(`! ${ev.message || ""}`);
      else if (ev.t === "tool") lines.push(`▸ ${ev.name}${ev.summary ? " " + ev.summary : ""}`);
      else if (ev.t === "thinking_start") lines.push("… thinking");
      else if (ev.t === "build") lines.push(`▸ Compile: ${buildWord(ev.result || {})}`);
    }
    return lines.join("\n");
  }
  function buildWord(r) {
    const errors = (r.diagnostics || []).filter((d) => d.severity === "error").length;
    return r.cancelled ? "stopped" : r.timed_out ? "timed out" : r.exit === 0 && !errors ? "OK" : errors ? `${errors} error(s)` : `failed (exit ${r.exit})`;
  }

  // The running turn, watched live: its events are read as they come (the server holds the request until
  // there are some) and handed to the Files view (app.js studioLive), which shows the agent at work — the
  // lines it reads, the file as it writes it, the build it ran. One turn is followed at a time. The Files
  // view's marks (the lines each turn changed) stay through the Start's turns, a role's hand-off included,
  // and are cleared only when a new Start begins (the run's started_at changes).
  async function followLoop(job) {
    const live = globalThis.studioLive;
    const start = state.run ? state.run.started_at : undefined;
    if (live && start !== state.liveStart) { state.liveStart = start; live.reset(); }
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
    const now = state.run, job = now && now.active ? now.job : null;
    if (job && state.following !== job && !state.followed.has(job)) { state.following = job; followLoop(job); }
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
      const said = transcriptText(r.events || []);
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
    pane.replaceChildren(...(state.coordinator ? [coordinatorCard(state.coordinator)] : []), runCard(state.run), h("h3", "Work log", { class: "run-head" }), log);
    restore(kept);
  }

  async function refresh(force) {
    const [run, log, coordinator] = await Promise.all([api("/api/agent/run"), api("/api/agent/log"), api(`../../api/node/${encodeURIComponent(nodeId())}/coordinator`)]);
    state.run = run._status === 200 ? run : null;
    state.coordinator = coordinator._status === 200 && coordinator.data ? coordinator.data : null;  // a node that rests on nothing has none (404)
    if (!(state.run && state.run.active)) {  // what the node is (its kind, what it rests on, its review): whether the Decomposer is offered; not read while a run is on
      const node = await api(`../../api/node/${encodeURIComponent(nodeId())}`);
      state.node = node._status === 200 ? node.data : null;
    }
    state.log = log._status === 200 && Array.isArray(log.entries) ? log.entries : [];
    state.folder = log.folder || state.folder;
    state.open = (log._status === 200 && log.open) || state.open;
    // A studio with no agent at work opens on "Start agent on this node", whatever Files tab was remembered
    // (spec #145, story 42); only a link to #files, or a run under way, leaves the remembered view
    if (!state.read && !(state.run && state.run.active) && location.hash !== "#files" && typeof showCentre === "function") showCentre("run", false);
    state.read = true;
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
