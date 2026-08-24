"""The console page.

One file, no build step, no dependencies to install: a console that needs a
toolchain before it can show you what your machine is doing is a console that
stops working the day the toolchain does.

Priorities in order: what is waiting for you, what has permission, what
happened, and how to stop it (PRD 12.1).
"""

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pressure Harness</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #fbfbfc; --panel: #fff; --line: #e3e4e8; --text: #16181d; --dim: #6a6f7a;
  --accent: #2f6fd0; --danger: #c02626; --ok: #1c7c46; --warn: #a86a00;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#15171b; --panel:#1c1f24; --line:#2c3038; --text:#e8eaee; --dim:#9aa1ad;
          --accent:#6aa6f5; --danger:#f07171; --ok:#63c78e; --warn:#e0a53f; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; display:flex; min-height:100vh; }
nav { width:190px; flex:none; border-right:1px solid var(--line); padding:1rem .6rem;
      position:sticky; top:0; height:100vh; overflow:auto; }
nav h1 { font-size:.95rem; margin:.2rem .6rem 1rem; letter-spacing:.02em; }
nav h1 small { display:block; font-weight:400; color:var(--dim); font-size:.75rem; }
nav button { display:flex; justify-content:space-between; align-items:center; width:100%;
  text-align:left; background:none; border:0; color:inherit; font:inherit; padding:.45rem .6rem;
  border-radius:.4rem; cursor:pointer; }
nav button:hover { background:rgba(127,127,127,.12); }
nav button[aria-current="true"] { background:rgba(127,127,127,.18); font-weight:600; }
nav .count { background:var(--accent); color:#fff; border-radius:1rem; padding:0 .45rem;
  font-size:.72rem; font-weight:600; }
nav .stop { margin-top:1.2rem; border:1px solid var(--danger); color:var(--danger);
  justify-content:center; }
main { flex:1; padding:1.4rem 1.6rem 4rem; max-width:1000px; }
h2 { font-size:1.15rem; margin:0 0 .2rem; }
.sub { color:var(--dim); margin:0 0 1.2rem; }
section { display:none; } section.on { display:block; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:.6rem;
        padding:.9rem 1rem; margin-bottom:.8rem; }
.row { display:flex; gap:1rem; align-items:baseline; justify-content:space-between; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:.6rem;
         margin-bottom:1rem; }
.tile { background:var(--panel); border:1px solid var(--line); border-radius:.6rem; padding:.7rem .9rem; }
.tile b { display:block; font-size:1.5rem; font-weight:650; line-height:1.2; }
.tile span { color:var(--dim); font-size:.8rem; }
pre { font-family:var(--mono); font-size:.82rem; white-space:pre-wrap; word-break:break-word;
      background:rgba(127,127,127,.09); padding:.6rem .7rem; border-radius:.4rem; margin:.5rem 0 0;
      max-height:16rem; overflow:auto; }
code { font-family:var(--mono); font-size:.85em; }
button.act { font:inherit; padding:.35rem .7rem; border-radius:.35rem; border:1px solid var(--line);
  background:var(--panel); color:inherit; cursor:pointer; }
button.act:hover { border-color:var(--accent); }
button.primary { border-color:var(--accent); color:var(--accent); font-weight:600; }
button.danger { border-color:var(--danger); color:var(--danger); }
.actions { display:flex; gap:.4rem; flex-wrap:wrap; margin-top:.7rem; }
table { width:100%; border-collapse:collapse; font-size:.85rem; }
th { text-align:left; color:var(--dim); font-weight:600; padding:.3rem .5rem; }
td { padding:.3rem .5rem; border-top:1px solid var(--line); vertical-align:top; }
.pill { font-size:.72rem; padding:.05rem .4rem; border-radius:.3rem; border:1px solid var(--line);
        color:var(--dim); white-space:nowrap; }
.deny { color:var(--danger); } .ask { color:var(--warn); } .allow { color:var(--ok); }
.warn-box { border-left:3px solid var(--warn); }
.empty { color:var(--dim); padding:.6rem 0; }
.count-down { font-variant-numeric:tabular-nums; color:var(--warn); font-weight:600; }
label.inline { color:var(--dim); font-size:.85rem; margin-right:.4rem; }
select, input[type=text] { font:inherit; padding:.3rem .4rem; border-radius:.35rem;
  border:1px solid var(--line); background:var(--panel); color:inherit; }
</style></head>
<body>
<nav>
  <h1>Pressure Harness<small id="platform">…</small></h1>
  <div id="nav"></div>
  <button class="stop" onclick="emergencyStop()">Stop everything</button>
</nav>
<main>
  <section id="overview" class="on"></section>
  <section id="approvals"></section>
  <section id="projects"></section>
  <section id="activity"></section>
  <section id="changes"></section>
  <section id="processes"></section>
  <section id="connection"></section>
  <section id="doctor"></section>
</main>
<script>
const TOKEN = "__TOKEN__";
const TABS = [
  ["overview","Overview"], ["approvals","Approvals"], ["projects","Projects"],
  ["activity","Activity"], ["changes","Changes"], ["processes","Processes"],
  ["connection","Connection"], ["doctor","Doctor"],
];
let current = "overview";
let pendingCount = 0;

// Single quotes as well as double: some of these values land inside inline
// handlers, where a lone apostrophe would end the string early. Every value
// there is generated or validated today, but escaping both closes the class
// rather than the instance.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => (
  {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function get(path, params={}) {
  const url = new URL(path, location.origin);
  Object.entries(params).forEach(([k,v]) => v != null && url.searchParams.set(k, v));
  const res = await fetch(url, {headers: {"x-pharness-token": TOKEN}});
  if (!res.ok) throw new Error((await res.json()).error || res.statusText);
  return res.json();
}
async function post(path, body={}) {
  const res = await fetch(path, {method:"POST",
    headers:{"x-pharness-token":TOKEN,"content-type":"application/json"},
    body: JSON.stringify(body)});
  return res.json();
}

function drawNav() {
  document.getElementById("nav").innerHTML = TABS.map(([id,label]) =>
    `<button onclick="show('${id}')" aria-current="${id===current}">${label}` +
    (id==="approvals" && pendingCount ? `<span class="count">${pendingCount}</span>` : "") +
    `</button>`).join("");
}
function show(id) {
  current = id;
  document.querySelectorAll("section").forEach(s => s.classList.toggle("on", s.id===id));
  drawNav(); refresh();
}
function heading(title, sub) { return `<h2>${title}</h2><p class="sub">${sub}</p>`; }
// Colour by what happened, not by what was decided: a call that was allowed and
// then failed is not a green row.
function outcomeClass(r) {
  if (r.disposition === "failed" || r.disposition === "error") return "ask";
  return esc(r.decision);
}

async function drawOverview() {
  const s = await get("/api/status");
  document.getElementById("platform").textContent =
    s.platform + (s.supported ? "" : " · unsupported");
  const elevated = s.elevated.map(e =>
    `<div class="card warn-box"><b>${esc(e.alias)}</b> has full access for
     <span class="count-down">${Math.ceil(e.expires_in_sec/60)} min</span>
     <div class="actions"><button class="act danger"
       onclick="post('/api/revoke-elevation',{alias:'${esc(e.alias)}'}).then(refresh)">
       End it now</button></div></div>`).join("");
  document.getElementById("overview").innerHTML =
    heading("Overview", "What is happening on this machine right now.") +
    `<div class="tiles">
      <div class="tile"><b>${s.today.calls}</b><span>tool calls today</span></div>
      <div class="tile"><b class="${s.pending?'ask':''}">${s.pending}</b><span>waiting for you</span></div>
      <div class="tile"><b class="${s.today.denied?'deny':''}">${s.today.denied}</b><span>refused today</span></div>
      <div class="tile"><b>${s.processes}</b><span>running processes</span></div>
     </div>` + elevated +
    `<div class="card"><div class="row"><span>Approval prompts</span>
       <span class="pill">${esc(s.notifier)}${s.can_prompt ? "" : " · cannot ask"}</span></div>
       ${s.can_prompt ? "" : `<p class="sub" style="margin:.5rem 0 0">
         Nothing here can ask you a question, so anything needing approval is refused.</p>`}</div>
     <div class="card"><div class="row"><span>Audit log</span>
       <span class="pill ${s.audit_intact?'allow':'deny'}">${esc(s.audit)}</span></div></div>` +
    (s.warnings.length ? `<div class="card warn-box"><b>Worth narrowing</b>
       <ul>${s.warnings.map(w=>`<li>${esc(w)}</li>`).join("")}</ul></div>` : "");
}

async function drawApprovals() {
  const [pending, history, rules] = await Promise.all(
    [get("/api/pending"), get("/api/approvals/history"), get("/api/rules")]);
  const queue = pending.length ? pending.map(p => `
    <div class="card">
      <div class="row"><b>${esc(p.tool)}${p.op?"."+esc(p.op):""} · ${esc(p.workspace)}</b>
        <span class="count-down">${p.seconds_left}s</span></div>
      <div class="sub" style="margin:.2rem 0 0">${esc(p.tier)} — ${esc(p.reason)}</div>
      <pre>${esc(p.payload)}</pre>
      <div class="actions">
        <button class="act danger" onclick="answer('${p.id}','deny')">Deny</button>
        <button class="act primary" onclick="answer('${p.id}','once')">Allow once</button>
        <button class="act" onclick="answer('${p.id}','session')">This conversation</button>
        <button class="act" onclick="answer('${p.id}','remember')">Remember this</button>
      </div>
    </div>`).join("") : `<p class="empty">Nothing is waiting.</p>`;

  const ruleRows = rules.length ? `<table><tr><th>Action</th><th>Scope</th><th>Why</th><th></th></tr>` +
    rules.map(r => `<tr>
      <td class="${r.action==='deny'?'deny':'allow'}">${esc(r.action)}</td>
      <td>${esc(r.tool||"any tool")} · ${esc(r.workspace||"any project")}
        ${r.exact_payload?`<br><span class="pill">payload ${esc(r.exact_payload)}…</span>`:""}
        ${r.session_only?`<span class="pill">one conversation</span>`:""}</td>
      <td>${esc(r.reason||"")}</td>
      <td><button class="act danger" onclick="post('/api/forget-rule',{index:${r.index}}).then(refresh)">
        Remove</button></td></tr>`).join("") + `</table>`
    : `<p class="empty">You have not remembered any permissions.</p>`;

  const past = history.length ? `<table><tr><th>When</th><th>What</th><th>Outcome</th></tr>` +
    history.map(h => `<tr><td>${esc((h.at||"").slice(11,19))}</td>
      <td>${esc(h.tool)} · ${esc(h.workspace)} <span class="pill">${esc(h.tier)}</span></td>
      <td class="${h.outcome==='deny'||h.outcome==='timed_out'?'deny':'allow'}">${esc(h.outcome)}</td>
      </tr>`).join("") + `</table>` : `<p class="empty">Nothing yet.</p>`;

  document.getElementById("approvals").innerHTML =
    heading("Approvals", "You approve the exact request, not a description of it.") +
    queue + `<h2 style="margin-top:1.6rem">Remembered permissions</h2>
    <p class="sub">Anything you allowed for longer than once. Remove what you no longer want.</p>
    <div class="card">${ruleRows}</div>
    <h2 style="margin-top:1.6rem">Recently answered</h2><div class="card">${past}</div>`;
}
async function answer(id, outcome) {
  const res = await post("/api/answer", {request_id:id, outcome});
  if (!res.ok) alert(res.error || "it is no longer waiting");
  refresh();
}

async function drawProjects() {
  const list = await get("/api/workspaces");
  document.getElementById("projects").innerHTML =
    heading("Projects", "Only these directories are reachable. Adding one is done on this machine.") +
    (list.length ? list.map(w => `
      <div class="card ${w.scope_warning?'warn-box':''}">
        <div class="row"><b>${esc(w.alias)}</b>
          <span class="pill ${w.mode==='full-access'?'ask':''}">${esc(w.mode)}</span></div>
        <div class="sub" style="margin:.2rem 0 0"><code>${esc(w.path)}</code>
          ${w.exists?"":' <span class="pill deny">missing</span>'}</div>
        ${w.scope_warning?`<p class="sub" style="margin:.4rem 0 0">This is ${esc(w.scope_warning)} —
          narrower is safer.</p>`:""}
        <div class="sub" style="margin:.4rem 0 0">
          ${w.branch?`branch <code>${esc(w.branch)}</code> · `:""}
          ${w.checkpoints} checkpoint(s) · push ${w.git_push?"allowed":"off"}</div>
        ${w.allow_commands.length?`<div class="sub" style="margin:.3rem 0 0">runs without asking:
          ${w.allow_commands.map(c=>`<code>${esc(c)}</code>`).join(", ")}</div>`:""}
        <div class="actions">
          <button class="act" onclick="post('/api/elevate',{alias:'${esc(w.alias)}',minutes:120}).then(refresh)">
            Full access for 2 hours</button>
          ${w.mode==='full-access'?`<button class="act danger"
            onclick="post('/api/revoke-elevation',{alias:'${esc(w.alias)}'}).then(refresh)">End it</button>`:""}
        </div>
      </div>`).join("") : `<p class="empty">Nothing is authorised yet. Run
        <code>ph workspace add &lt;path&gt;</code> on this machine.</p>`);
}

async function drawActivity() {
  const filter = document.getElementById("act-filter")?.value || "";
  const rows = await get("/api/activity", {limit:120, decision: filter || null});
  document.getElementById("activity").innerHTML =
    heading("Activity", "Every tool call, including the refusals — those are the interesting ones.") +
    `<div class="card"><label class="inline" for="act-filter">Show</label>
      <select id="act-filter" onchange="drawActivity()">
        <option value="">everything</option>
        <option value="deny" ${filter==='deny'?'selected':''}>refused only</option>
        <option value="ask" ${filter==='ask'?'selected':''}>asked only</option>
        <option value="allow" ${filter==='allow'?'selected':''}>allowed only</option>
      </select></div>
    <div class="card">${rows.length?`<table>
      <tr><th>When</th><th>Tool</th><th>Tier</th><th>Outcome</th><th>Why</th></tr>` +
      rows.map(r => `<tr>
        <td>${esc((r.ts||"").slice(11,19))}</td>
        <td>${esc(r.tool)}${r.op?"."+esc(r.op):""}<br><span class="pill">${esc(r.workspace||"")}</span></td>
        <td>${esc(r.tier||"")}</td>
        <td class="${outcomeClass(r)}">${esc(r.disposition||r.decision)}</td>
        <td>${esc(r.reason||"")}${r.redacted?`<br><span class="pill">secrets removed</span>`:""}</td>
      </tr>`).join("") + `</table>` : `<p class="empty">Nothing recorded yet.</p>`}</div>`;
}

async function drawChanges() {
  const list = await get("/api/workspaces");
  if (!list.length) {
    document.getElementById("changes").innerHTML =
      heading("Changes", "Every edit is recorded so it can be put back.") +
      `<p class="empty">No projects yet.</p>`;
    return;
  }
  const alias = document.getElementById("cp-project")?.value || list[0].alias;
  const points = await get("/api/checkpoints", {alias});
  document.getElementById("changes").innerHTML =
    heading("Changes", "Every edit is recorded so it can be put back. Undo is undoable too.") +
    `<div class="card"><label class="inline" for="cp-project">Project</label>
      <select id="cp-project" onchange="drawChanges()">
        ${list.map(w=>`<option ${w.alias===alias?'selected':''}>${esc(w.alias)}</option>`).join("")}
      </select></div>` +
    (points.length ? points.map(c => `
      <div class="card"><div class="row"><b>${esc(c.label)}</b>
        <span class="pill">${esc(c.id)} · ${esc((c.ts||"").slice(0,16).replace("T"," "))}</span></div>
        <div class="sub" style="margin:.3rem 0 0">${c.changes.map(ch =>
          `${esc(ch.action)} <code>${esc(ch.path)}</code>`).join("<br>")}</div>
        <div class="actions"><button class="act"
          onclick="undo('${esc(alias)}','${esc(c.id)}')">Put this back</button></div>
      </div>`).join("") : `<p class="empty">Nothing has been changed yet.</p>`);
}
async function undo(alias, id) {
  const res = await post("/api/undo", {alias, checkpoint:id});
  alert(res.ok ? res.summary : (res.error || "could not undo"));
  drawChanges();
}

async function drawProcesses() {
  const list = await get("/api/processes");
  document.getElementById("processes").innerHTML =
    heading("Processes", "Anything started here, including what has already exited.") +
    (list.length ? list.map(p => `
      <div class="card"><div class="row">
        <b>${esc(p.id)} <span class="pill">${p.running?"running":"exited "+p.exit_code}</span></b>
        <span class="pill">pid ${p.pid} · ${p.uptime_sec}s</span></div>
        <div class="sub" style="margin:.2rem 0 0"><code>${esc(p.argv.join(" "))}</code></div>
        <div class="actions">
          <button class="act" onclick="logs('${esc(p.id)}')">Output</button>
          ${p.running?`<button class="act danger"
            onclick="post('/api/stop-process',{process_id:'${esc(p.id)}'}).then(refresh)">Stop</button>`:""}
        </div><pre id="log-${esc(p.id)}" style="display:none"></pre>
      </div>`).join("") : `<p class="empty">Nothing has been started.</p>`);
}
async function logs(id) {
  const box = document.getElementById("log-"+id);
  const res = await get("/api/process-logs", {process_id:id, lines:200});
  box.textContent = res.text || "(no output)";
  box.style.display = "block";
}

async function drawConnection() {
  const c = await get("/api/connection");
  const tunnel = c.tunnel ? `<div class="card"><div class="row"><span>Tunnel</span>
      <span class="pill ${c.tunnel.running?'allow':''}">${esc(c.tunnel.summary)}</span></div></div>` : "";
  const pairing = c.pairing_code ? `
    <div class="card"><div class="row"><span>Pairing code</span>
      <b style="font-family:var(--mono);letter-spacing:.15em">${esc(c.pairing_code)}</b></div>
      <p class="sub" style="margin:.4rem 0 0">Type this on the approval page when a new client
        connects. Anyone can reach that page; only someone looking at this screen has the code.</p>
      <div class="actions"><button class="act"
        onclick="post('/api/rotate-pairing-code').then(refresh)">Issue a new code</button></div></div>` : "";
  const clients = (c.clients||[]).length ? `<div class="card"><b>Authorised clients</b>
    <table>${c.clients.map(cl=>`<tr><td>${esc(cl.name)}<br><span class="pill">${esc(cl.id)}</span></td>
      <td><button class="act danger"
        onclick="post('/api/revoke-client',{client_id:'${esc(cl.id)}'}).then(refresh)">Revoke</button>
      </td></tr>`).join("")}</table></div>`
    : `<div class="card"><p class="empty">Nothing has been authorised to connect.</p></div>`;

  document.getElementById("connection").innerHTML =
    heading("Connection", "How clients reach this machine, and who may.") +
    `<div class="card"><div class="row"><span>On this machine</span>
       <code>${esc(c.stdio_command)}</code></div></div>` + tunnel + pairing + clients;
}

async function drawDoctor() {
  const checks = await get("/api/doctor");
  document.getElementById("doctor").innerHTML =
    heading("Doctor", "What is set up, and what is worth fixing.") +
    `<div class="card"><table>${checks.map(c=>`<tr>
      <td class="${c.ok?'allow':(c.level==='error'?'deny':'ask')}">${c.ok?"ok":(c.level==='error'?"fail":"warn")}</td>
      <td>${esc(c.label)}${c.detail?`<br><span class="pill">${esc(c.detail)}</span>`:""}</td>
      </tr>`).join("")}</table></div>`;
}

async function emergencyStop() {
  if (!confirm("Refuse everything waiting and stop every process started here?")) return;
  const res = await post("/api/emergency-stop");
  alert(`Refused ${res.refused} request(s), stopped ${res.stopped} process(es).`);
  refresh();
}

const DRAW = {overview:drawOverview, approvals:drawApprovals, projects:drawProjects,
  activity:drawActivity, changes:drawChanges, processes:drawProcesses,
  connection:drawConnection, doctor:drawDoctor};

async function refresh() {
  try {
    const s = await get("/api/status");
    pendingCount = s.pending;
    drawNav();
    await DRAW[current]();
  } catch (err) {
    document.querySelector("section.on").innerHTML =
      `<h2>Cannot reach the console</h2><p class="sub">${esc(err.message)}</p>`;
  }
}
drawNav(); refresh();
// Pending approvals are time-limited, so the queue has to move on its own.
setInterval(() => { if (current === "approvals" || pendingCount) refresh(); }, 2000);
setInterval(refresh, 10000);
</script>
</body></html>
"""
