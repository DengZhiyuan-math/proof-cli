/* Shared by the editor (app.js) and the pop-out PDF viewer (viewer.js). */
"use strict";

const $ = (s) => document.querySelector(s);
/* The node this studio page belongs to: the page lives at /studio/<node-id>/ (ADR-0011). Its
   URLs are relative, so it only ever reaches its own node, and everything it keeps in the
   browser is keyed by node, so two nodes never share open tabs, chat or an agent session.
   Only the theme is shared: a preference, not a node's state. */
const NODE = decodeURIComponent((location.pathname.match(/\/studio\/([^/]+)\//) || [])[1] || "");
// [node, key] as JSON: unambiguous whatever the node id holds (node "A" key "chat.session"
// and node "A.chat" key "session" must not meet)
const storeKey = (k) => k === "theme" ? "proof.studio.theme" : "proof.studio:" + JSON.stringify([NODE, k]);
const store = {
  get(k, d) { try { const v = localStorage.getItem(storeKey(k)); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(storeKey(k), JSON.stringify(v)); } catch { /* ignore */ } },
};

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Prism-Local": "1" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path.replace(/^\//, ""), opts);   // relative: this node's /studio/<id>/
  let data = {};
  try { data = await r.json(); } catch { /* non-JSON */ }
  data._status = r.status;
  return data;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* theme */
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const dark = t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  if (dark) document.documentElement.dataset.dark = ""; else delete document.documentElement.dataset.dark;
}
applyTheme(store.get("theme", null));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(store.get("theme", null)));

/* Icons: one line-icon set drawn on a 24px grid, so every icon has the same size, stroke
   and centre (text glyphs such as ☰ ⌂ ◐ differ in size and sit at different heights).
   <button data-icon="home"> puts the icon before the label, data-icon-end after it. */
const ICONS = {
  menu: '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
  home: '<path d="M4 10.5 12 4l8 6.5"/><path d="M6 9v10.5h4.5V14h3v5.5H18V9"/>',
  theme: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" stroke="none"/>',
  settings: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  minus: '<path d="M6 12h12"/>',
  plus: '<path d="M12 6v12M6 12h12"/>',
  more: '<circle cx="6" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="18" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  down: '<path d="m7 10 5 5 5-5"/>',
  up: '<path d="m7 14 5-5 5 5"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor" stroke-width="1.2"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5" fill="currentColor" stroke="none"/>',
  popout: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L19.5 9"/><path d="M19.5 4.5V9H15"/>',
  arrow: '<path d="M5 12h14M13.5 6.5 19 12l-5.5 5.5"/>',
  list: '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><circle cx="4.8" cy="6.5" r="1.1" fill="currentColor" stroke="none"/><circle cx="4.8" cy="12" r="1.1" fill="currentColor" stroke="none"/><circle cx="4.8" cy="17.5" r="1.1" fill="currentColor" stroke="none"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5"/>',
  download: '<path d="M12 4v11M7 10.5l5 5 5-5"/><path d="M5 19.5h14"/>',
  spark: '<path d="M12 4l1.7 5.3L19 11l-5.3 1.7L12 18l-1.7-5.3L5 11l5.3-1.7z" fill="currentColor" stroke-width="1"/>',
  gauge: '<path d="M4.2 16.5a8 8 0 1 1 15.6 0"/><path d="m12 15.5 3.6-4.6"/><circle cx="12" cy="15.8" r="1.2" fill="currentColor" stroke="none"/>',
  star: '<path d="m12 4.5 2.3 4.7 5.2.8-3.8 3.6.9 5.1L12 16.3l-4.6 2.4.9-5.1-3.8-3.6 5.2-.8z"/>',
};
function icon(name, cls = "") {
  return `<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name] || ""}</svg>`;
}
for (const el of document.querySelectorAll("[data-icon]")) el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon));
for (const el of document.querySelectorAll("[data-icon-end]")) el.insertAdjacentHTML("beforeend", icon(el.dataset.iconEnd, "end"));

/* Key hints are written for macOS (⌘); on Windows and Linux the same keys use Ctrl. */
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const keys = (s) => (IS_MAC ? s : String(s).replace(/⌘/g, "Ctrl+"));
if (!IS_MAC) for (const el of document.querySelectorAll("[title*='⌘'], [placeholder*='⌘']")) {
  if (el.title) el.title = keys(el.title);
  if (el.placeholder) el.placeholder = keys(el.placeholder);
}

// Editor tab <-> pop-out PDF tab. Messages:
//   viewer -> editor: {type:"alive"} (heartbeat), {type:"bye"}, {type:"inverse", id, page, x, y}
//   editor -> viewer: {type:"forward", r} (SyncTeX box), {type:"pdf", mtime},
//                     {type:"jumped", id, name, ok, file, line | msg} (answers "inverse")
const pdfChannel = "BroadcastChannel" in window ? new BroadcastChannel("proof-studio-pdf:" + NODE) : null;

/* prism-local's page presence (heartbeat, idle exit) is not part of proof-cli: the server's
   lifecycle is proof-cli's own (ADR-0011). */
