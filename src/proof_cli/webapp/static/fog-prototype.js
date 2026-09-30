// PROTOTYPE (issue #127): three variants of the Proof fog view, switchable via ?variant=A|B|C, on
// the existing map page. Throwaway: branch prototype/fog-view, never master. Read-only against the
// project: the fog items are a stub built from whichever nodes the loaded project has, mutations
// change the stub in memory and say what `proof fog …` command they stand for.
//   A  a Fog page in the sidebar, like Review and Warnings
//   B  a drawer over the map canvas, grouped by the node each item is near; hovering lights the node up
//   C  fog notes drawn on the canvas beside their node, unattached ones in a bank at the corner
"use strict";
(() => {
  const VARIANTS = { A: "Fog page in the sidebar", B: "Drawer over the map", C: "Notes on the canvas" };
  const KEYS = Object.keys(VARIANTS);
  const variant = new URLSearchParams(location.search).get("variant");
  if (!variant || !VARIANTS[variant]) return;

  // ---- the stub -------------------------------------------------------------------------
  let fog = null;
  let seq = 0;
  const now = () => new Date().toISOString().slice(0, 16).replace("T", " ");
  const item = (text, near, extra) => ({ id: `fog-${++seq}`, text, notes: "", near, status: "open", created_by: "human", created_at: "2026-09-28 10:12", experiments: [], ...extra });
  const exp = (outcome, summary, run_by, path) => ({ outcome, summary, run_by, at: "2026-09-29 21:40", path });
  function stubFog(nodes) {
    const rejected = (n) => ["rejected", "no-longer-callable"].includes(n.acceptance_state);
    const pick = (test) => (nodes.find(test) || {}).id;
    const T = pick((n) => n.kind === "theorem"), L = pick((n) => n.kind === "lemma");
    const claims = nodes.filter((n) => n.kind === "claim" && !rejected(n)).map((n) => n.id);
    const C1 = claims[0], C2 = claims[1] || claims[0];
    const R = pick((n) => n.kind === "claim" && rejected(n)), I = pick((n) => n.kind === "imported_result");
    const near = (...ids) => ids.filter(Boolean);
    seq = 0;
    return [
      item(`${L || "引理"} 里的常数 C 大概能取到最优，但还说不清「最优」该怎么陈述`, near(L), { experiments: [
        exp("supports", "n ≤ 10⁶ 逐一验证，比值单调趋于 1", "agent_a", `proofs/${L || "L1"}/scratch/constant.py`),
        exp("inconclusive", "换成 p 进制情形，数值不稳定", "human", `proofs/fog/fog-1/padic.ipynb`) ] }),
      item(`${C1 || "C1"} 也许对更一般的群成立，至少对可解群`, near(C1), { created_by: "agent_a" }),
      item(`能不能绕开 ${I || "引用的结果"}，直接从 ${C2 || "C2"} 的构造得到 ${C1 || "C1"}？`, near(C1, I), { experiments: [
        exp("inconclusive", "小阶情形能绕开，一般情形没算出来", "agent_a", `proofs/${C1 || "C1"}/scratch/bypass.sage`) ] }),
      item(`${R || "被否决的那条路"} 失败可能只是缺一个紧性假设`, near(R), { experiments: [
        exp("refutes", "加上紧性后反例仍然成立（n = 7）", "human", "proofs/fog/fog-4/counterexample.py") ] }),
      item("整个问题有没有一个变分刻画？", near(), { notes: "如果有，主定理应该是某个泛函的临界点条件。", experiments: [
        exp("error", "SageMath 内存不足，没跑完", "agent_a", "proofs/fog/fog-5/variational.sage") ] }),
      item("用生成函数硬算", near(L), { status: "dropped", reason: "系数增长太快，估计不出来", dropped_by: "human", dropped_at: "2026-09-29 09:03" }),
      item("主定理里 ε 的依赖也许是多项式的", near(T), { status: "crystallized", node_id: "eps-poly" }),
    ];
  }
  const ensureFog = () => { if (!fog && typeof mapData !== "undefined" && mapData) fog = stubFog(mapData.nodes); return fog || []; };
  const open = () => ensureFog().filter((f) => f.status === "open");
  const latest = (f) => f.experiments[f.experiments.length - 1] || null;
  const nodeById = (id) => (mapData ? mapData.nodes.find((n) => n.id === id) : null);
  const nodeHref = (id) => { const n = nodeById(id); return n ? pageOf(n) : "#/"; };

  // ---- what the stub's mutations stand for -------------------------------------------------
  const cmd = (text) => say(`PROTOTYPE · would run: ${text}`, "ok");
  function addFog(text, nearId) {
    if (!text.trim()) return;
    ensureFog().push(item(text.trim(), nearId ? [nearId] : [], { created_at: now() }));
    cmd(`proof fog add "${text.trim()}"${nearId ? ` --near ${nearId}` : ""}`);
    rerender();
  }
  function dropFog(f) {
    const reason = prompt(`Drop ${f.id}: why? (required)`);
    if (!reason) return;
    Object.assign(f, { status: "dropped", reason, dropped_by: "human", dropped_at: now() });
    cmd(`proof fog drop ${f.id} --reason "${reason}"`);
    rerender();
  }
  function reopenFog(f) { Object.assign(f, { status: "open", reason: undefined, dropped_by: undefined, dropped_at: undefined }); cmd(`proof fog reopen ${f.id}`); rerender(); }
  function recordExperiment(f) {
    const outcome = prompt(`Experiment on ${f.id}: outcome? supports / refutes / inconclusive / error`, "supports");
    if (!["supports", "refutes", "inconclusive", "error"].includes(outcome || "")) return;
    const summary = prompt("One or two lines: what was computed, what it showed") || "";
    f.experiments.push({ outcome, summary, run_by: "human", at: now(), path: `proofs/fog/${f.id}/` });
    cmd(`proof fog experiment record ${f.id} ${outcome} --summary "${summary}" --run-by human`);
    rerender();
  }

  // the crystallize sheet, shared by the variants (#126: statement written fresh, parent defaults to the one near node)
  function crystallize(f) {
    let overlay = $("fog-overlay");
    if (!overlay) {
      overlay = el("section", null, { id: "fog-overlay", class: "fog-overlay" });
      document.body.append(overlay);
    }
    const sheet = el("div", null, { class: "sheet" });
    const from = el("p", null, { class: "from" });
    from.append(`Crystallize ${f.id} — `, el("span", f.text, { class: "fog-text" }));
    const idField = el("input", null, { type: "text", placeholder: "node id (a folder name under proofs/)", value: "" });
    const stmt = el("textarea", null, { rows: 3, placeholder: "The precise statement. The fog's text stays on the fog item; it is never copied here." });
    const parent = el("select");
    parent.append(el("option", "— no parent (a free-standing Claim) —", { value: "" }));
    for (const n of mapData.nodes.filter((n) => n.kind !== "imported_result")) parent.append(el("option", `${n.id} · ${KIND_LABEL[n.kind]}`, { value: n.id }));
    if (f.near.length === 1) parent.value = f.near[0];
    const warn = el("p", f.near.length > 1 ? `This item is near ${f.near.length} nodes: choose the parent (the CLI refuses with FOG_PARENT_AMBIGUOUS).` : "", { class: "hint" });
    const foot = el("div", null, { class: "sheet-foot" });
    const cancel = el("button", "Cancel", { type: "button" });
    const go = el("button", "Crystallize", { type: "button", class: "primary" });
    cancel.onclick = () => { overlay.hidden = true; };
    go.onclick = () => {
      if (!idField.value.trim() || !stmt.value.trim()) return say("A node id and a statement are required.", "error");
      Object.assign(f, { status: "crystallized", node_id: idField.value.trim() });
      overlay.hidden = true;
      cmd(`proof fog crystallize ${f.id} ${idField.value.trim()} "${stmt.value.trim()}"${parent.value ? ` --parent ${parent.value}` : f.near.length ? " --no-parent" : ""}  (the new Claim would now appear on the map)`);
      rerender();
    };
    foot.append(cancel, go);
    const lab = (text, field) => { const l = el("label", text); l.append(field); return l; };
    sheet.append(el("h2", "Crystallize into a Claim"), from, lab("Node id", idField), lab("Statement", stmt), lab("Parent (becomes a single-child Split of it)", parent), warn, foot);
    overlay.replaceChildren(sheet);
    overlay.hidden = false;
    idField.focus();
  }

  // ---- shared pieces -------------------------------------------------------------------
  function expChip(f) {
    const e = latest(f);
    if (!e) return el("span", "no experiment yet", { class: "exp none" });
    return el("span", `${e.outcome} · ${short(e.summary, 40)}`, { class: `exp ${e.outcome}`, title: `${e.summary} — ${e.run_by}, ${e.at}${e.path ? ` · ${e.path}` : ""}` });
  }
  function nearChips(f) {
    const box = el("span", null, { class: "fog-near" });
    if (!f.near.length) box.append(el("span", "not near any node", { class: "fog-id" }));
    for (const id of f.near) box.append(el("a", id, { href: nodeHref(id), title: `near ${id} — an informal pointer, not a dependency` }));
    return box;
  }
  function expList(f) {
    const ul = el("ul", null, { class: "exp-list" });
    for (const e of [...f.experiments].reverse()) {
      const li = el("li");
      const right = el("span");
      right.append(e.summary, " ", el("span", `— ${e.run_by}, ${e.at}`, { class: "who" }));
      if (e.path) right.append(" ", el("code", e.path));
      li.append(el("span", e.outcome, { class: `exp ${e.outcome}` }), right);
      ul.append(li);
    }
    if (!f.experiments.length) ul.append(el("li", "No experiment recorded.", { class: "fog-id" }));
    return ul;
  }
  function actions(f) {
    const box = el("div", null, { class: "fog-actions" });
    const btn = (text, fn, primary) => { const b = el("button", text, { type: "button", class: primary ? "primary" : "" }); b.onclick = (ev) => { ev.stopPropagation(); fn(f); }; return b; };
    if (f.status === "open") box.append(btn("Crystallize…", crystallize, true), btn("Record experiment…", recordExperiment), btn("Drop…", dropFog));
    else if (f.status === "dropped") box.append(btn("Reopen", reopenFog));
    else box.append(el("a", `Open ${f.node_id}`, { href: `/studio/${encodeURIComponent(f.node_id)}/`, class: "review-link" }));
    return box;
  }
  function statusLine(f) {
    if (f.status === "dropped") return el("span", `dropped · ${f.dropped_by}, ${f.dropped_at} — ${f.reason}`, { class: "fog-status" });
    if (f.status === "crystallized") return el("span", `crystallized as ${f.node_id}`, { class: "fog-status" });
    return null;
  }
  function nearSelect() {
    const s = el("select", null, { title: "near which node (optional)" });
    s.append(el("option", "near: none", { value: "" }));
    for (const n of mapData.nodes) s.append(el("option", `near: ${n.id}`, { value: n.id }));
    return s;
  }
  function composer(compact) {
    const box = el("div", null, { class: "fog-composer" });
    const input = el("input", null, { type: "text", placeholder: "A difficulty you can't state precisely yet…" });
    const near = nearSelect();
    const add = el("button", "Add", { type: "button", class: "primary" });
    const submit = () => { addFog(input.value, near.value); input.value = ""; };
    add.onclick = submit;
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") submit(); });
    if (compact) { const row2 = el("div", null, { class: "row2" }); row2.append(near, add); box.append(input, row2); }
    else box.append(input, near, add);
    return box;
  }

  // ---- variant A: a page in the sidebar --------------------------------------------------
  let showGone = false;
  function mountA() {
    const rail = document.querySelector(".rail");
    const link = el("a", null, { href: "#/fog", "data-nav": "fog" });
    link.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 18.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.1 9.6 4.5 4.5 0 0 0 7 18.5z"/></svg>';
    link.append(el("span", "Fog"), el("span", "", { class: "n", id: "rail-fog" }));
    rail.append(link);
    const page = el("section", null, { id: "fog-page", class: "page", hidden: "" });
    const title = el("h1", "Proof fog ", { class: "page-title" });
    title.append(el("span", "", { class: "n", id: "fog-count" }));
    const toggle = el("label", null, { class: "fog-toggle" });
    const cb = el("input", null, { type: "checkbox" });
    cb.onchange = () => { showGone = cb.checked; renderA(); };
    toggle.append(cb, "show dropped and crystallized");
    title.append(toggle);
    const compose = el("div", null, { class: "card" });
    compose.append(composer(false));
    const list = el("div", null, { class: "card" });
    list.append(el("ul", null, { id: "fog-list", class: "fog-list" }));
    page.append(title, el("p", "Difficulties not yet precise enough to be a Claim. They live outside the map: a fog item is never a node, never a dependency, and never changes a node's state. When one can be stated, crystallize it into a Claim.", { class: "hint" }), compose, list);
    $("home").after(page);
  }
  function renderA() {
    const items = ensureFog().filter((f) => showGone || f.status === "open");
    const ul = $("fog-list");
    ul.replaceChildren(...items.map((f) => {
      const li = el("li", null, { class: f.status === "open" ? "" : "gone" });
      const colId = el("div", null, { class: "col-id" });
      colId.append(el("span", f.id, { class: "fog-id" }), el("span", `${f.created_by}`, { class: "fog-id" }));
      const main = el("div", null, { class: "col-main" });
      main.append(el("p", f.text, { class: "fog-text", style: "margin:0" }));
      if (f.notes) main.append(el("p", f.notes, { class: "hint", style: "margin:0" }));
      const meta = el("div", null, { class: "meta" });
      meta.append(nearChips(f), expChip(f));
      const st = statusLine(f); if (st) meta.append(st);
      main.append(meta);
      if (f.experiments.length) { const d = el("details"); d.append(el("summary", `${f.experiments.length} experiment${f.experiments.length > 1 ? "s" : ""}`), expList(f)); main.append(d); }
      const side = el("div", null, { class: "col-side" });
      side.append(actions(f));
      li.append(colId, main, side);
      return li;
    }));
    if (!items.length) ul.append(el("li", "No fog: everything you know about is stated as a node.", { class: "fog-id" }));
    const n = open().length;
    $("fog-count").textContent = n ? String(n) : "";
    $("rail-fog").textContent = n ? String(n) : "";
  }

  // ---- variant B: a drawer over the canvas ----------------------------------------------
  let drawerOpen = true, expanded = null;
  function mountB() {
    const badge = el("a", null, { class: "badge fog on", href: "#/", id: "fog-badge", title: "Proof fog: what you can't state yet" });
    badge.append(el("b", "–", { id: "stat-fog" }), " Fog");
    badge.onclick = (ev) => { ev.preventDefault(); drawerOpen = !drawerOpen; renderB(); };
    document.querySelector(".badges").append(badge);
    const drawer = el("aside", null, { id: "fog-drawer", class: "fog-drawer", "aria-label": "Proof fog" });
    const head = el("div", null, { class: "fog-drawer-head" });
    head.append(el("h2", "Proof fog"), el("span", "", { class: "n", id: "fog-drawer-n" }));
    const close = el("button", "×", { type: "button", class: "close", title: "Hide (the Fog badge brings it back)" });
    close.onclick = () => { drawerOpen = false; renderB(); };
    head.append(close);
    drawer.append(head, composer(true), el("div", null, { class: "fog-drawer-body", id: "fog-drawer-body" }));
    document.querySelector(".stage").append(drawer);
  }
  function focusNodes(ids, on) {
    const svgBox = $("dag-svg");
    svgBox.classList.toggle("fog-focus", on && ids.length > 0);
    for (const g of svgBox.querySelectorAll("g.node")) g.classList.toggle("fog-near", on && ids.includes(g.getAttribute("data-node-id")));
  }
  function renderB() {
    const items = open();
    $("stat-fog").textContent = String(items.length);
    $("fog-badge").classList.toggle("on", drawerOpen);
    const drawer = $("fog-drawer");
    drawer.hidden = !drawerOpen;
    $("fog-drawer-n").textContent = String(items.length);
    const body = $("fog-drawer-body");
    body.replaceChildren();
    const groups = new Map();
    for (const f of items) { const key = f.near[0] || ""; (groups.get(key) || groups.set(key, []).get(key)).push(f); }
    const order = [...groups.keys()].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
    for (const key of order) {
      const head = el("div", null, { class: "fog-group-head" });
      if (key) { const n = nodeById(key); head.append("near ", el("a", key, { href: nodeHref(key) }), el("span", n ? KIND_LABEL[n.kind] : "")); }
      else head.append("not near any node");
      body.append(head);
      for (const f of groups.get(key)) {
        const it = el("div", null, { class: `fog-drawer-item${expanded === f.id ? " open" : ""}` });
        const line = el("div", null, { class: "line" });
        line.append(el("span", f.id, { class: "fog-id" }), expChip(f));
        it.append(line, el("p", f.text, { class: "fog-text", style: "margin:0" }));
        const more = el("div", null, { class: "more" });
        more.append(nearChips(f), expList(f), actions(f));
        it.append(more);
        it.onclick = () => { expanded = expanded === f.id ? null : f.id; renderB(); };
        it.onmouseenter = () => focusNodes(f.near, true);
        it.onmouseleave = () => focusNodes([], false);
        body.append(it);
      }
    }
    if (!items.length) body.append(el("p", "No fog.", { class: "hint", style: "margin:8px" }));
  }

  // ---- variant C: notes on the canvas ---------------------------------------------------
  const NOTE = { w: 184, h: 54, gap: 26, step: 64 };
  let notesOn = true;
  function mountC() {
    const bank = el("div", null, { class: "fog-bank", id: "fog-bank" });
    document.querySelector(".stage").append(bank);
    const pop = el("div", null, { class: "fog-pop", id: "fog-pop", hidden: "" });
    document.querySelector(".stage").append(pop);
    const sw = el("label", null, { class: "fog-switch", title: "Show or hide the fog notes" });
    const cb = el("input", null, { type: "checkbox", checked: "" });
    cb.onchange = () => { notesOn = cb.checked; drawNotes(); };
    sw.append(cb, "Fog");
    const zoom = document.querySelector(".zoom");
    zoom.insertBefore(el("span", null, { class: "sep" }), zoom.firstChild);
    zoom.insertBefore(sw, zoom.firstChild);
    $("map-dag").addEventListener("pointerdown", (ev) => { if (!ev.target.closest(".fog-note, .fog-pop")) $("fog-pop").hidden = true; });
  }
  function popover(f, clientX, clientY) {
    const pop = $("fog-pop"), stage = document.querySelector(".stage").getBoundingClientRect();
    pop.replaceChildren();
    const close = el("button", "×", { type: "button", class: "close" }); close.onclick = () => { pop.hidden = true; };
    const line = el("div", null, { class: "line" }); line.append(el("span", f.id, { class: "fog-id" }), el("span", `· ${f.created_by}, ${f.created_at}`, { class: "fog-id" }));
    pop.append(close, line, el("p", f.text, { class: "fog-text", style: "margin:0" }));
    if (f.notes) pop.append(el("p", f.notes, { class: "hint", style: "margin:0" }));
    pop.append(nearChips(f), expList(f), actions(f));
    pop.hidden = false;
    const x = Math.min(clientX - stage.left + 12, stage.width - 336), y = Math.min(clientY - stage.top + 12, stage.height - 260);
    pop.style.left = `${Math.max(8, x)}px`; pop.style.top = `${Math.max(8, y)}px`;
  }
  function drawNotes() {
    const scene = $("dag-view");
    if (!scene) return;
    for (const old of scene.querySelectorAll(".fog-note, .fog-tie")) old.remove();
    const items = open();
    const bank = $("fog-bank");
    const loose = items.filter((f) => !f.near.some((id) => view.at && view.at.has(id)));
    bank.replaceChildren();
    const h = el("h3", "Fog not near any node "); h.append(el("span", String(loose.length), { class: "n" }));
    bank.append(h);
    for (const f of loose) {
      const it = el("div", null, { class: "item" });
      const line = el("div", null, { class: "line", style: "display:flex;gap:8px;align-items:baseline" }); line.append(el("span", f.id, { class: "fog-id" }), expChip(f));
      it.append(el("p", f.text, { class: "fog-text", style: "margin:0" }), line);
      it.onclick = (ev) => popover(f, ev.clientX, ev.clientY);
      bank.append(it);
    }
    const add = el("div", null, { class: "add" });
    const input = el("input", null, { type: "text", placeholder: "Add fog…" });
    const btn = el("button", "Add", { type: "button" });
    btn.onclick = () => { addFog(input.value, ""); input.value = ""; };
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") btn.click(); });
    add.append(input, btn); bank.append(add);
    if (!notesOn || !view.at) return;
    const slot = new Map();
    for (const f of items) {
      const anchor = f.near.find((id) => view.at.has(id));
      if (!anchor) continue;
      const p = view.at.get(anchor), i = slot.get(anchor) || 0; slot.set(anchor, i + 1);
      const x = p.x + BOX.w / 2 + NOTE.gap, y = p.y - BOX.h / 2 + i * NOTE.step;
      for (const id of f.near) {
        const q = view.at.get(id); if (!q) continue;
        const from = id === anchor ? { x: q.x + BOX.w / 2, y: q.y } : { x: q.x, y: q.y + BOX.h / 2 };
        const to = id === anchor ? { x, y: y + NOTE.h / 2 } : { x: x + NOTE.w / 2, y: y + NOTE.h };
        scene.append(svg("path", { class: "fog-tie", d: `M${from.x},${from.y} C${from.x + 20},${from.y} ${to.x - 20},${to.y} ${to.x},${to.y}` }));
      }
      const g = svg("g", { class: "fog-note", transform: `translate(${x},${y})`, "data-fog-id": f.id, role: "button", tabindex: 0, "aria-label": `fog ${f.id}: ${f.text}` });
      g.append(svg("rect", { class: "paper", x: 0, y: 0, width: NOTE.w, height: NOTE.h, rx: 10 }));
      const fid = svg("text", { class: "fid", x: 10, y: 15 }); fid.textContent = f.id;
      const t1 = svg("text", { x: 10, y: 33 }); t1.textContent = short(f.text, 20);
      const t2 = svg("text", { x: 10, y: 47 }); t2.textContent = f.text.length > 20 ? short(f.text.slice(19), 20) : "";
      g.append(fid, t1, t2);
      const e = latest(f);
      if (e) g.append(svg("circle", { class: `dot ${e.outcome}`, cx: NOTE.w - 12, cy: 12, r: 4.5 }));
      g.addEventListener("click", (ev) => { ev.stopPropagation(); popover(f, ev.clientX, ev.clientY); });
      scene.append(g);
    }
  }

  // ---- wiring: hook the page's own functions --------------------------------------------
  function rerender() {
    if (variant === "A") renderA();
    if (variant === "B") renderB();
    if (variant === "C") drawNotes();
  }
  const _showMap = showMap;
  showMap = function () { ensureFog(); _showMap(); rerender(); };
  const _drawDag = drawDag;
  drawDag = function (nodes) { _drawDag(nodes); if (variant === "C") drawNotes(); };
  const _route = route;
  route = async function () {
    await _route();
    if (variant !== "A") return;
    const onFog = location.hash === "#/fog";
    if (onFog) { $("home").hidden = true; document.body.dataset.page = "fog"; }
    $("fog-page").hidden = !onFog;
    if (onFog) for (const link of document.querySelectorAll(".rail a[data-nav]")) link.classList.toggle("on", link.dataset.nav === "fog");
    if (onFog) renderA();
  };

  // the switcher
  function switcher() {
    const bar = el("div", null, { class: "proto-bar", role: "group", "aria-label": "Prototype variant" });
    const go = (delta) => { const next = KEYS[(KEYS.indexOf(variant) + delta + KEYS.length) % KEYS.length]; const u = new URL(location); u.searchParams.set("variant", next); if (next !== "A" && u.hash === "#/fog") u.hash = "#/"; location.href = u; };
    const prev = el("button", "‹", { type: "button", title: "Previous variant (←)" }); prev.onclick = () => go(-1);
    const next = el("button", "›", { type: "button", title: "Next variant (→)" }); next.onclick = () => go(1);
    const lbl = el("span", null, { class: "lbl" }); lbl.append(el("b", variant), VARIANTS[variant], el("span", `?variant=${variant}`, { class: "q" }));
    bar.append(prev, lbl, next);
    document.body.append(bar);
    document.addEventListener("keydown", (ev) => {
      const a = document.activeElement;
      if (a && (["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName) || a.isContentEditable)) return;
      if (ev.key === "ArrowLeft") go(-1); else if (ev.key === "ArrowRight") go(1);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (variant === "A") mountA();
    if (variant === "B") mountB();
    if (variant === "C") mountC();
    switcher();
  });
})();
