// The Home (ADR-0017): the researcher's proof projects, each a card, each opening in its own proof map page.
// Everything from a project is inserted as text, never HTML; a theorem's $…$ is typeset with KaTeX.
"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const json = await response.json();
  if (!json.ok) throw Object.assign(new Error(json.error.message), { code: json.error.code });
  return json.data;
}

function say(text, kind) {
  const box = $("message");
  box.textContent = text;
  box.className = kind || "";
}
const showError = (error) => say(error.code ? `${error.code}: ${error.message}` : error.message, "error");

function el(tag, text, attrs) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  return node;
}

// a field's text with its $…$ typeset (static/mathtext.js, KaTeX); plain text without it
function withMath(node, text) {
  if (typeof renderMathText === "function") return renderMathText(node, text);
  node.textContent = text;
  return node;
}

function ago(iso) {
  if (!iso) return "never opened";
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (seconds < 90) return "opened just now";
  if (seconds < 3600) return `opened ${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `opened ${Math.round(seconds / 3600)} h ago`;
  return `opened ${Math.round(seconds / 86400)} d ago`;
}

let data = { projects: [] };

async function refresh() {
  data = await api("/api/projects");
  render();
}

// Open: the Home serves the project's page (starting it if need be), then the browser moves there.
async function openProject(project) {
  say(`Opening ${project.name}…`);
  try {
    const { url } = await api("/api/projects/open", { path: project.path });
    location.href = url;
  } catch (error) { showError(error); }
}

function stat(count, word, cls) {
  const li = el("li", null, cls ? { class: cls } : {});
  li.append(el("b", count), ` ${word}`);
  return li;
}

function card(project) {
  const box = el("article", null, { class: `project-card${project.error ? " broken" : ""}`, "data-path": project.path });
  const head = el("header");
  const title = el("a", project.name, { href: project.url || "#", class: "name" });
  title.addEventListener("click", (event) => { event.preventDefault(); if (!project.error) openProject(project); });
  head.append(title);
  if (project.project_id) head.append(el("span", project.project_id, { class: "pid mono" }));
  if (project.running) head.append(el("span", "running", { class: "live", title: "Its page is being served right now" }));
  box.append(head);
  if (project.error) {
    box.append(el("p", project.error, { class: "warning" }));
  } else {
    const theorem = el("p", null, { class: "theorem" });
    if (project.theorem) withMath(theorem, project.theorem); else { theorem.textContent = "No theorem yet"; theorem.classList.add("none"); }
    box.append(theorem);
  }
  box.append(el("p", project.path, { class: "path mono", title: project.path }));
  if (project.counts) {
    const c = project.counts;
    const stats = el("ul", null, { class: "stats" });
    stats.append(stat(c.nodes, c.nodes === 1 ? "node" : "nodes"), stat(c.frontier, "on the frontier", "frontier"), stat(c.awaiting, "awaiting you", c.awaiting ? "review" : ""), stat(c.accepted, "accepted", "accepted"));
    if (c.fog) stats.append(stat(c.fog, "fog"));
    box.append(stats);
  }
  const foot = el("footer");
  foot.append(el("span", ago(project.opened_at), { class: "hint" }), el("span", null, { class: "spacer" }));
  const forget = el("button", "Forget", { type: "button", title: "Drop it from this list; the folder is untouched" });
  forget.addEventListener("click", () => askForget(project));
  foot.append(forget);
  if (project.exists && !project.project) {
    const create = el("button", "Start a project here", { type: "button", class: "primary" });
    create.addEventListener("click", () => createProject(project.path, "").catch(showError));
    foot.append(create);
  } else if (!project.error) {
    const open = el("button", "Open", { type: "button", class: "primary" });
    open.addEventListener("click", () => openProject(project));
    foot.append(open);
  }
  box.append(foot);
  return box;
}

function render() {
  const projects = data.projects;
  $("projects").replaceChildren(...projects.map(card));
  $("empty").hidden = projects.length > 0;
  const running = projects.filter((p) => p.running).length;
  $("map-caption").textContent = projects.length ? `${projects.length} ${projects.length === 1 ? "project" : "projects"}${running ? ` · ${running} running` : ""}` : "";
}

// -- the sheets --------------------------------------------------------------------
function showSheet(id, focusId) {
  for (const sheet of document.querySelectorAll(".overlay")) sheet.hidden = sheet.id !== id;
  if (focusId) { const field = $(focusId); field.value = field.value || ""; field.focus(); }
}
function hideSheets() { for (const sheet of document.querySelectorAll(".overlay")) sheet.hidden = true; }

async function addProject(path) {
  const project = await api("/api/projects/add", { path });
  hideSheets();
  say(`Added ${project.name}.`, "ok");
  await refresh();
}

async function createProject(path, projectId) {
  const body = projectId ? { path, project_id: projectId } : { path };
  const project = await api("/api/projects/create", body);
  hideSheets();
  say(`Started ${project.name}.`, "ok");
  await refresh();
  await openProject(project);
}

let forgetting = null;
function askForget(project) {
  forgetting = project;
  $("forget-what").textContent = `${project.name} — ${project.path}`;
  showSheet("forget-sheet");
}

document.addEventListener("DOMContentLoaded", () => {
  for (const id of ["add-project", "empty-add"]) $(id).addEventListener("click", () => showSheet("add-sheet", "add-path"));
  for (const id of ["new-project", "empty-new"]) $(id).addEventListener("click", () => showSheet("new-sheet", "new-path"));
  for (const button of document.querySelectorAll(".overlay .cancel")) button.addEventListener("click", hideSheets);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") hideSheets(); });
  $("add-form").addEventListener("submit", (event) => { event.preventDefault(); addProject($("add-path").value.trim()).catch(showError); });
  $("new-form").addEventListener("submit", (event) => { event.preventDefault(); createProject($("new-path").value.trim(), $("new-id").value.trim()).catch(showError); });
  $("forget-confirm").addEventListener("click", async () => {
    if (!forgetting) return;
    try { await api("/api/projects/forget", { path: forgetting.path }); hideSheets(); say(`Forgot ${forgetting.name}.`, "ok"); forgetting = null; await refresh(); } catch (error) { showError(error); }
  });
  // back from a project's tab: which pages are running, what awaits, may have changed
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh().catch(showError); });
  refresh().catch(showError);
});
