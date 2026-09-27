// Proof review — the one surface that issues signed Human Review decisions (ADR-0009, #36).
// The server holds no authority: this page asks it what to sign, has the passkey sign it,
// and hands the signature back. Everything from the project is inserted as text, never HTML.
"use strict";

const $ = (id) => document.getElementById(id);

// -- base64url <-> bytes ---------------------------------------------------------
function b64urlToBytes(text) {
  const base64 = text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4);
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
}
function bytesToB64url(buffer) {
  let binary = "";
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// -- the server ------------------------------------------------------------------
async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const json = await response.json();
  if (!json.ok) throw Object.assign(new Error(json.error.message), { code: json.error.code, details: json.error });
  return json.data;
}

function say(text, kind) {
  const box = $("message");
  box.textContent = text;
  box.className = kind || "";
}

function el(tag, text, attrs) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  return node;
}

function row(cells) {
  const tr = document.createElement("tr");
  for (const cell of cells) {
    const td = document.createElement("td");
    if (cell instanceof Node) td.appendChild(cell); else td.textContent = cell === null || cell === undefined ? "—" : String(cell);
    tr.appendChild(td);
  }
  return tr;
}

// -- a minimal, safe Markdown view (headings, lists, emphasis, code); the exact text is shown too --
function renderMarkdown(text, into) {
  into.replaceChildren();
  const inline = (line, parent) => {
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
    let last = 0;
    for (const match of line.matchAll(pattern)) {
      parent.append(line.slice(last, match.index));
      const token = match[0];
      if (token.startsWith("`")) parent.append(el("code", token.slice(1, -1)));
      else if (token.startsWith("**")) parent.append(el("strong", token.slice(2, -2)));
      else parent.append(el("em", token.slice(1, -1)));
      last = match.index + token.length;
    }
    parent.append(line.slice(last));
  };
  const body = text.replace(/^---\n[\s\S]*?\n---\n/, ""); // the vault file's frontmatter isn't proof text
  let list = null, fence = null, paragraph = null;
  for (const line of body.split("\n")) {
    if (fence) { if (line.startsWith("```")) { into.append(fence); fence = null; } else fence.textContent += line + "\n"; continue; }
    if (line.startsWith("```")) { fence = el("pre"); list = paragraph = null; continue; }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (heading) { const h = el("h" + Math.min(6, heading[1].length + 3)); inline(heading[2], h); into.append(h); list = paragraph = null; }
    else if (item) { if (!list) { list = el("ul"); into.append(list); } const li = el("li"); inline(item[1], li); list.append(li); paragraph = null; }
    else if (!line.trim()) { list = paragraph = null; }
    else { if (!paragraph) { paragraph = el("p"); into.append(paragraph); } else paragraph.append(" "); inline(line, paragraph); list = null; }
  }
  if (fence) into.append(fence);
}

// -- WebAuthn ------------------------------------------------------------------------
async function assert(toSign) {
  const credential = await navigator.credentials.get({
    publicKey: {
      challenge: b64urlToBytes(toSign.challenge),
      rpId: toSign.rp_id,
      allowCredentials: toSign.allow_credentials.map((id) => ({ type: "public-key", id: b64urlToBytes(id) })),
      userVerification: "required",
      timeout: 120000,
    },
  });
  return {
    credential_id: bytesToB64url(credential.rawId),
    authenticator_data: bytesToB64url(credential.response.authenticatorData),
    client_data_json: bytesToB64url(credential.response.clientDataJSON),
    signature: bytesToB64url(credential.response.signature),
  };
}

// Show exactly what will be signed, then sign it with one tap.
function confirmAndSign(toSign) {
  return new Promise((resolve, reject) => {
    $("confirm-payloads").textContent = JSON.stringify(toSign.payloads, null, 2);
    for (const id of ["home", "node-page"]) $(id).hidden = true;
    $("confirm").hidden = false;
    const done = () => { $("confirm").hidden = true; route(); };
    $("confirm-cancel").onclick = () => { done(); reject(new Error("cancelled")); };
    $("confirm-sign").onclick = async () => {
      try { const assertion = await assert(toSign); done(); resolve(assertion); }
      catch (error) { done(); reject(error); }
    };
  });
}

async function signAndSend(decisions) {
  const toSign = await api("/api/prepare", { decisions });
  const assertion = await confirmAndSign(toSign);
  const outcome = await api("/api/decide", { payloads: toSign.payloads, batch: toSign.batch, assertion });
  const failed = outcome.results.filter((result) => !result.ok);
  if (failed.length) say(failed.map((f) => `${f.target_id}: ${f.error.code} — ${f.error.message}`).join("; "), "error");
  else say(`Signed ${outcome.results.length} decision(s).`, "ok");
  await refresh();
}

// -- enrollment: register the passkey, then sign its own (or an existing key signs its) enrollment --
async function enroll(displayName) {
  const begin = await api("/api/enroll/begin", { display_name: displayName });
  const options = begin.public_key;
  const created = await navigator.credentials.create({
    publicKey: {
      ...options,
      challenge: b64urlToBytes(options.challenge),
      user: { ...options.user, id: b64urlToBytes(options.user.id) },
      excludeCredentials: options.excludeCredentials.map((id) => ({ type: "public-key", id: b64urlToBytes(id) })),
    },
  });
  const registered = await api("/api/enroll/register", {
    token: begin.token,
    client_data_json: bytesToB64url(created.response.clientDataJSON),
    attestation_object: bytesToB64url(created.response.attestationObject),
  });
  say(`New key ${registered.fingerprint}. ${registered.first_key ? "Now confirm it with the same passkey." : "Now confirm it with a passkey that's already enrolled."}`);
  const assertion = await confirmAndSign(registered);
  const key = await api("/api/enroll/complete", { token: registered.token, assertion });
  say(`Enrolled ${key.display_name} — fingerprint ${key.fingerprint}. Check it matches this device.`, "ok");
  await refresh();
}

// -- pages -------------------------------------------------------------------------
let state = null;

function showBanner() {
  const banner = $("registry-banner");
  const registry = state.registry;
  const problems = state.warnings.filter((w) => /^(REVIEWER_|PIN_FILE|HISTORY_TRUNCATED|INVALID_REGISTRY)/.test(w.code));
  banner.replaceChildren();
  if (!registry.has_keys) {
    banner.append("No Reviewer passkey is enrolled for this project yet. Enroll one below before deciding anything.");
  } else if (!registry.trusted || problems.length) {
    banner.append("The Reviewer key registry doesn't verify — no decision counts until this is resolved: ");
    banner.append(problems.map((w) => w.code).join(", ") || "untrusted");
  } else if (!registry.acknowledged) {
    banner.append("The Reviewer keys changed since you last checked them. Look at the list below, then confirm with a tap.");
    const button = el("button", "These keys are mine");
    button.onclick = async () => {
      try { const toSign = await api("/api/acknowledge/prepare", {}); const assertion = await confirmAndSign(toSign); await api("/api/acknowledge", { payloads: toSign.payloads, batch: toSign.batch, assertion }); await refresh(); }
      catch (error) { say(error.message, "error"); }
    };
    banner.append(button);
  }
  banner.hidden = !banner.childNodes.length;
}

function showKeys() {
  const body = $("keys").querySelector("tbody");
  body.replaceChildren(...state.keys.map((key) => row([
    key.display_name,
    el("span", key.fingerprint, { class: "fp" }),
    key.enrolled_at,
    key.aaguid && !/^0+$/.test(key.aaguid) ? key.aaguid : "not disclosed",
    key.revoked_seq ? `revoked ${key.revoked_at}` : "active",
  ])));
}

function showWarnings(list, into) {
  into.replaceChildren(...list.map((w) => { const li = el("li", null, { class: "warning" }); li.append(el("code", w.code), " ", w.message); return li; }));
  if (!list.length) into.append(el("li", "None."));
}

function showHome() {
  const body = $("pending").querySelector("tbody");
  body.replaceChildren(...state.pending.map((item) => {
    const box = el("input", null, { type: "checkbox" });
    const choice = el("select");
    for (const decision of item.decisions) choice.append(el("option", decision));
    const rationale = el("input", null, { placeholder: "why" });
    const link = el("a", item.node_id, { href: `#/node/${encodeURIComponent(item.node_id)}` });
    const statement = el("div", item.statement);
    if (item.candidate_proof && item.candidate_proof.id) {
      const proof = el("details");
      proof.append(el("summary", `proof ${item.candidate_proof.id} · SHA-256 ${item.candidate_proof.sha256.slice(0, 16)}…`), el("pre", item.candidate_proof.text));
      statement.append(proof);
    }
    const tr = row([box, link, statement, choice, rationale]);
    tr.dataset.kind = item.kind; tr.dataset.target = item.node_id;
    if (item.candidate_proof && item.candidate_proof.sha256) tr.dataset.viewed = item.candidate_proof.sha256;
    return tr;
  }));
  if (!state.pending.length) body.append(row(["", "Nothing is awaiting review.", "", "", ""]));
  showWarnings(state.warnings, $("warnings"));
}

async function showLegacy() {
  const items = await api("/api/legacy");
  $("legacy-section").hidden = !items.length;
  $("legacy").replaceChildren(...items.map((item) => {
    const box = el("details", null, { class: "legacy-item" });
    const summary = el("summary");
    const pick = el("select");
    pick.append(el("option", "leave for now", { value: "" }));
    if (item.resignable) pick.append(el("option", `re-sign: ${item.decision}`, { value: "resign" }));
    // a legacy Reject or dismissal keeps its node/Challenge closed: it can only be re-signed
    const closes = item.kind === "challenge_resolution" || (item.kind === "acceptance" && item.decision === "reject");
    if (!closes) pick.append(el("option", "decline", { value: "decline" }));
    pick.dataset.item = JSON.stringify(item);
    summary.append(pick, " ", el("strong", `${item.kind} · ${item.decision}`), ` on ${item.target_id} — by ${item.original_reviewer}, ${item.original_time}`);
    box.append(summary);
    if (!item.resignable) box.append(el("p", `Can only be declined: ${item.why_not}`, { class: "warning" }));
    if (item.original_rationale) box.append(el("p", `Original rationale: ${item.original_rationale}`));
    if (item.node) box.append(el("p", `Statement: ${item.node.statement}`), el("p", `Assumptions: ${item.node.assumptions.join("; ") || "none"}`));
    if (item.pins.length) box.append(el("p", "Pins: " + item.pins.map((p) => `${p.target_node_id} v${p.pinned_version ?? "—"}`).join(", ")));
    const challenge = item.context && item.context.challenge;
    if (challenge) box.append(el("p", `Challenge ${challenge.id} on ${challenge.target_node_id}: "${challenge.rationale}" (opened by ${challenge.opened_by})`));
    const check = item.context && item.context.evidence_check;
    if (check) box.append(el("p", `Evidence check ${check.id}: ${check.outcome} — ${check.notes || "no notes"} (run by ${check.run_by})`));
    if (item.candidate_proof) {
      box.append(el("p", `Candidate proof ${item.candidate_proof.id} (version ${item.candidate_proof.version}, SHA-256 ${item.candidate_proof.sha256}) — the exact text that will be signed:`));
      box.append(el("pre", item.candidate_proof.text));
    }
    return box;
  }));
}

async function showNode(nodeId) {
  const view = await api(`/api/node/${encodeURIComponent(nodeId)}`);
  const node = view.node;
  $("node-title").textContent = `${node.id} — ${node.kind}`;
  $("node-axes").textContent = `workflow: ${view.workflow_state} · acceptance: ${view.acceptance_state} · integrity: ${view.integrity_state}`;
  const nodeWarnings = el("ul");
  showWarnings(view.warnings, nodeWarnings);
  $("node-warnings").replaceChildren(el("h3", "Warnings for this node"), nodeWarnings);
  $("node-statement").textContent = node.statement;
  $("node-assumptions").replaceChildren(...(node.assumptions.length ? [el("h3", "Assumptions"), ...node.assumptions.map((a) => el("p", a))] : []));
  $("node-deps").querySelector("tbody").replaceChildren(...view.dependencies.map((d) => row([
    d.node_id, d.pin ? d.pin.pinned_version : null, d.pin ? el("span", d.pin.pinned_fingerprint || "—", { class: "fp" }) : null, d.current === null ? null : d.current ? "yes" : "NO — stale",
  ])));
  $("node-challenges").replaceChildren(...view.challenges.filter((c) => c.status === "open").map((c) => el("li", `${c.id}: ${c.rationale} (opened by ${c.opened_by})`)));
  const proof = view.candidate_proof;
  if (proof) {
    $("node-proof-meta").textContent = `version ${proof.version} · ${proof.id} · SHA-256 ${proof.sha256}`;
    renderMarkdown(proof.text, $("node-proof-rendered"));
    $("node-proof-exact").textContent = proof.text;
  } else {
    $("node-proof-meta").textContent = "No Candidate proof submitted.";
    $("node-proof-rendered").replaceChildren();
    $("node-proof-exact").textContent = "";
  }
  $("node-evidence").replaceChildren(...view.evidence_checks.map((c) => el("li", `${c.outcome} — ${c.notes || "no notes"} (run by ${c.run_by})`)));
  const choice = $("decide-choice");
  const decisions = node.kind === "imported_result" ? ["reference-review"] : ["accept", "revision-requested", "reject"];
  choice.replaceChildren(...decisions.map((d) => el("option", d)));
  $("decide-form").onsubmit = async (event) => {
    event.preventDefault();
    try {
      await signAndSend([{
        kind: node.kind === "imported_result" ? "reference_review" : "acceptance", target_id: node.id, decision: choice.value,
        rationale: $("decide-rationale").value,
        ...(proof ? { viewed_candidate_proof_sha256: proof.sha256 } : {}),
      }]);
    } catch (error) { say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }
  };
  $("node-history").replaceChildren(...view.history.filter((r) => r.kind).map((r) => el("li", `${r.updated_at} · ${r.kind} · ${r.decision} · ${r.reviewer_id}${r.signed ? "" : " · UNSIGNED"}`)));
}

async function route() {
  const match = location.hash.match(/^#\/node\/(.+)$/);
  $("home").hidden = !!match;
  $("node-page").hidden = !match;
  if (match) {
    try { await showNode(decodeURIComponent(match[1])); } catch (error) { say(error.message, "error"); }
  }
}

async function refresh() {
  state = await api("/api/state");
  $("project").textContent = `· ${state.project_id} · ${state.origin}`;
  showBanner();
  showKeys();
  showHome();
  await showLegacy();
  await route();
}

document.addEventListener("DOMContentLoaded", () => {
  $("enroll-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await enroll($("enroll-name").value.trim()); } catch (error) { say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }
  });
  $("sign-batch").addEventListener("click", async () => {
    const decisions = [...$("pending").querySelectorAll("tbody tr")]
      .filter((tr) => tr.querySelector("input[type=checkbox]")?.checked)
      .map((tr) => ({
        kind: tr.dataset.kind, target_id: tr.dataset.target, decision: tr.querySelector("select").value,
        rationale: tr.querySelectorAll("input")[1].value,
        // the proof text shown in this row: the server refuses to sign if it changed since
        ...(tr.dataset.viewed ? { viewed_candidate_proof_sha256: tr.dataset.viewed } : {}),
      }));
    if (!decisions.length) return say("Tick at least one decision.", "error");
    try { await signAndSend(decisions); } catch (error) { say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }
  });
  $("sign-legacy").addEventListener("click", async () => {
    const decisions = [...$("legacy").querySelectorAll("select")].filter((pick) => pick.value).map((pick) => {
      const item = JSON.parse(pick.dataset.item);
      return pick.value === "resign"
        ? { kind: item.kind, target_id: item.target_id, decision: item.decision, resigns: item.item_id,
            ...(item.candidate_proof ? { viewed_candidate_proof_sha256: item.candidate_proof.sha256 } : {}) }
        : { kind: "legacy_decline", target_id: item.item_id, decision: "decline" };
    });
    if (!decisions.length) return say("Choose re-sign or decline for at least one item.", "error");
    try { await signAndSend(decisions); } catch (error) { say(error.code ? `${error.code}: ${error.message}` : error.message, "error"); }
  });
  window.addEventListener("hashchange", route);
  refresh().catch((error) => say(error.message, "error"));
});
