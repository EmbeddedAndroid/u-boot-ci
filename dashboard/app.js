// u-boot-ci dashboard: polls index.json (built by fwci.site) and renders it.
// Console lines and case names come from boards, so everything is set as
// text, never as HTML.
"use strict";

const POLL_MS = 60000;
const STAGE = {
  "login": "login prompt reached",
  "no-efi-stub": "bootloader handed off, no kernel output",
  "hang-before-console": "EFI stub ran, kernel console never came up",
  "early-panic": "kernel panic or oops before login",
  "no-login": "kernel ran, no login prompt",
  "not-reached": "Linux boot not reached",
};
const VERSUS = {
  "regression": ["fail", "Linux boot regression: the baseline booted"],
  "upstream-gap": ["warn", "upstream gap: the baseline does not boot either"],
  "fixed": ["pass", "fixed: the baseline did not boot"],
};
let index = null, selected = null, branch = null, runCache = {};

// The view of the selected base branch (main, master).
function view() { return (index.branches || {})[branch] || index; }

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k === "onclick") e.onclick = v; else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
  return e;
}
function badge(cls, text) { return el("span", {class: "badge " + cls}, text); }
function link(href, text) { return href ? el("a", {href: href, rel: "noopener"}, text) : text; }
function verdictClass(v) { return v === "pass" ? "pass" : v === "fail" ? "fail" : "none"; }
function stateBadge(c) {
  if (c.state === "done") return badge("none", "done");
  if (c.state === "skipped") return badge("warn", "skipped");
  if (c.state === "error") return badge("fail", "error");
  const q = c.queue_position !== null && c.queue_position !== undefined ? " #" + c.queue_position : "";
  return badge("info", c.state + q);
}

function renderAlerts() {
  const box = document.getElementById("alerts");
  box.replaceChildren();
  for (const c of view().matrix) {
    const v = VERSUS[c.versus];
    if (c.versus === "regression" || c.versus === "upstream-gap") {
      box.append(el("div", {class: "alert " + v[0]},
        el("b", {}, c.board + " / " + c.stack + ": " + v[1] + ". "),
        "Stopped at: " + (STAGE[c.boot_stage] || c.boot_stage) + ". ", link(c.boot_url, "console")));
    }
    if (c.gate === "fail") {
      box.append(el("div", {class: "alert fail"}, el("b", {}, c.board + " / " + c.stack + ": "),
        "fingerprint gate failed: the console did not show this build, its results are not counted. ",
        link(c.job_url, "LAVA job")));
    }
  }
}

function renderMatrix() {
  const t = document.getElementById("matrix");
  t.replaceChildren();
  const boards = [...new Set(view().matrix.map(c => c.board))];
  const stacks = [...new Set(view().matrix.map(c => c.stack))];
  t.append(el("tr", {}, el("th"), stacks.map(s => el("th", {}, s === "open" ? "open stack" : s + " firmware"))));
  for (const b of boards) {
    const row = el("tr", {}, el("th", {}, b));
    for (const s of stacks) {
      const c = view().matrix.find(x => x.board === b && x.stack === s);
      if (!c) { row.append(el("td")); continue; }
      const n = c.counts;
      const dist = Object.entries(c.distance || {}).map(([k, v]) => k + " +" + v).join(", ");
      const cell = el("td", {class: "cell" + (selected === b + "/" + s ? " sel" : ""),
                            onclick: () => { selected = b + "/" + s; renderMatrix(); renderDetail(); }},
        el("div", {class: "row"}, stateBadge(c), c.state_detail ? el("span", {class: "muted"}, c.state_detail) : null),
        el("div", {class: "row"}, el("span", {}, "fingerprint"), badge(verdictClass(c.gate), c.gate)),
        el("div", {class: "row boot"}, el("span", {}, "boots Linux"),
          badge(verdictClass(c.boot), c.boot === "pass" ? "yes" : c.boot === "fail" ? "no" : "not run")),
        c.boot === "fail" ? el("div", {class: "muted"}, STAGE[c.boot_stage] || c.boot_stage) : null,
        el("div", {class: "row"}, el("span", {}, "cases"),
          el("span", {}, badge("pass", n.pass), " ", badge(n.fail ? "fail" : "none", n.fail), " ",
             badge("none", n.skip + n.unknown), n.flaky ? badge("warn", n.flaky + " flaky") : null)),
        c.new_fail ? el("div", {class: "row"}, el("span", {}, "new failures"), badge("fail", c.new_fail)) : null,
        el("div", {class: "row"}, el("span", {}, "distance to upstream"),
          el("span", {class: "muted"}, dist || (s === "stock" ? "stock firmware" : "0"))));
      row.append(cell);
    }
    t.append(row);
  }
}

function renderHost() {
  const ul = document.getElementById("host");
  ul.replaceChildren(...(view().host_checks || []).map(h =>
    el("li", {}, el("span", {class: "name"}, h.name), badge(verdictClass(h.result === "skip" ? "" : h.result), h.result),
       el("span", {class: "muted"}, h.summary || ""), h.log ? link(h.log, "log") : null)));
}

async function run(id) {
  if (!runCache[id] || runCache[id].state !== "done") {
    const r = await fetch("runs/" + encodeURIComponent(id) + ".json", {cache: "no-store"});
    runCache[id] = await r.json();
  }
  return runCache[id];
}

async function renderDetail() {
  const box = document.getElementById("detail");
  if (!selected || !view().latest_nightly) return;
  const [b, s] = selected.split("/");
  document.getElementById("detail-title").textContent = selected;
  const r = await run(view().latest_nightly);
  const t = r.targets.find(x => x.board === b && x.stack === s);
  if (!t) return;
  const lb = t.linux_boot || {};
  const parts = [];
  parts.push(el("p", {}, "Fingerprint ", el("code", {}, t.fingerprint || ""), " · ",
    t.lava ? link(t.lava.url, "LAVA job " + t.lava.job_id) : "not submitted",
    t.lava && t.lava.device ? " on " + t.lava.device : "",
    " · stock restore: ", badge(verdictClass(t.restore === "recovery-job" ? "" : t.restore), t.restore || "not-run"),
    t.recovery ? [" ", link(t.recovery.url, "recovery job")] : null));
  parts.push(el("h3", {}, "Boots Linux: ", badge(verdictClass(lb.verdict), lb.verdict || "not-run"), " ",
    el("span", {class: "muted"}, STAGE[lb.stage] || lb.stage || "")));
  if (lb.versus_baseline && VERSUS[lb.versus_baseline])
    parts.push(el("p", {}, badge(VERSUS[lb.versus_baseline][0], VERSUS[lb.versus_baseline][1])));
  if ((lb.gaps || []).length)
    parts.push(el("p", {class: "muted"}, "Known upstream gaps for this stack: " + lb.gaps.join("; ")));
  if ((lb.last_lines || []).length)
    parts.push(el("p", {}, "Last console lines ", link(lb.url, "(at this line in LAVA)")),
               el("pre", {class: "console"}, lb.last_lines.join("\n")));
  parts.push(el("h3", {}, "Components"));
  for (const c of t.components || []) {
    const up = c.upstream;
    const line = el("div", {class: "comp"}, el("b", {}, c.name), " ", badge(c.role === "under-test" ? "info" : "none", c.role), " ",
      c.repo ? link(c.repo, c.branch || c.repo) : "", c.commit ? [" ", el("code", {}, c.commit.slice(0, 12))] : null,
      c.release ? " " + c.release : "", c.fingerprint ? [" ", el("code", {}, c.fingerprint)] : null,
      c.sha256 ? [" sha256 ", el("code", {}, c.sha256.slice(0, 16) + "…")] : null,
      up ? [" · distance to upstream ", badge(up.distance ? "warn" : "pass", up.distance)] : null);
    parts.push(line);
    if (up && up.carried && up.carried.length)
      parts.push(el("ul", {}, up.carried.map(p => el("li", {}, el("code", {}, p.commit.slice(0, 10)), " ",
        p.review ? link(p.review, p.subject) : p.subject + " (not posted)"))));
  }
  const d = t.diff || {};
  if (d.new_fail && d.new_fail.length) parts.push(el("p", {}, badge("fail", "new failures"), " " + d.new_fail.join(", ")));
  if (d.new_pass && d.new_pass.length) parts.push(el("p", {}, badge("pass", "new passes"), " " + d.new_pass.join(", ")));
  const hist = (view().case_history || {})[selected] || {runs: [], cases: {}};
  parts.push(el("h3", {}, "Cases ", el("span", {class: "muted"}, "(history: oldest left, newest right)")));
  const table = el("table", {class: "cases"}, el("tr", {}, el("th", {}, "suite / case"), el("th", {}, "result"), el("th", {}, "history")));
  for (const c of t.cases || []) {
    const id = c.suite + "/" + c.name;
    const h = hist.cases[id] || "";
    table.append(el("tr", {}, el("td", {}, link(c.url, id)),
      el("td", {}, badge(c.result === "pass" ? "pass" : c.result === "fail" ? "fail" : "none", c.result),
        c.flake ? [" ", badge("warn", "flake " + c.flake)] : null,
        c.note ? [" ", el("span", {class: "muted"}, c.note)] : null),
      el("td", {class: "hist"}, [...h].map(ch => el("span", {class: ch === "-" ? "x" : ch}, ch === "p" ? "●" : ch === "f" ? "✕" : "·")))));
  }
  parts.push(table);
  box.replaceChildren(...parts);
}

function renderHistory() {
  const box = document.getElementById("history");
  const rows = Object.entries(view().history || {}).sort();
  box.replaceChildren(el("table", {class: "cases"},
    el("tr", {}, el("th", {}, "board / stack"), el("th", {}, "boots Linux, oldest to newest"), el("th", {}, "latest")),
    rows.map(([k, cells]) => {
      const last = cells[cells.length - 1];
      return el("tr", {}, el("td", {}, k),
        el("td", {class: "hist"}, cells.map(c => el("span", {class: c.boot === "pass" ? "p" : c.boot === "fail" ? "f" : "x",
          title: c.run + ": " + (STAGE[c.boot_stage] || c.boot_stage)}, c.boot === "pass" ? "●" : c.boot === "fail" ? "✕" : "·"))),
        el("td", {}, last.counts.pass + " pass, " + last.counts.fail + " fail"));
    })));
}

function renderCandidates() {
  const c = index.pin_candidates || {};
  document.getElementById("candidates-section").hidden = !Object.keys(c).length;
  document.getElementById("candidates").replaceChildren(...Object.entries(c).sort().map(([board, r]) =>
    el("div", {}, el("h3", {}, board + " ", el("span", {class: "muted"}, r.title || ""), " ",
                     badge(r.state === "done" ? "none" : "info", r.state), " ", r.ci_url ? link(r.ci_url, "workflow run") : null),
      el("table", {class: "cases"},
        el("tr", {}, el("th", {}, "stack"), el("th", {}, "firmware"), el("th", {}, "fingerprint"),
           el("th", {}, "boots Linux"), el("th", {}, "cases"), el("th", {}, "LAVA")),
        r.cells.map(x => el("tr", {}, el("td", {}, x.stack), el("td", {}, x.firmware), el("td", {}, badge(verdictClass(x.gate), x.gate)),
          el("td", {}, badge(verdictClass(x.boot), x.boot), " ", el("span", {class: "muted"}, x.boot === "fail" ? (STAGE[x.boot_stage] || x.boot_stage) : "")),
          el("td", {}, x.counts.pass + " pass, " + x.counts.fail + " fail"), el("td", {}, link(x.job_url, "job"))))))));
}

function renderBranches() {
  const names = Object.keys(index.branches || {}).sort((a, b) => a === "main" ? -1 : b === "main" ? 1 : a.localeCompare(b));
  if (!branch || !names.includes(branch)) branch = index.default_branch || names[0];
  document.getElementById("branches").replaceChildren(...names.map(n =>
    el("button", {class: "badge " + (n === branch ? "info" : "none"),
                  onclick: () => { branch = n; selected = null; refreshView(); }}, n)));
}

function seriesLine(s) {
  const state = s.applied === true ? badge("pass", "applied") : s.applied === false ? badge("fail", "does not apply") :
    badge("none", "not tried");
  return el("li", {}, link(s.link, s.title), " ", el("span", {class: "muted"}, "v" + s.version + ", " + s.patches + " patches"), " ", state,
    s.added_as_prerequisite_of ? el("span", {class: "muted"}, " (prerequisite)") : null,
    s.failed_patch ? el("div", {class: "muted"}, "fails at patch " + s.failed_patch.number + ": " + s.failed_patch.subject) : null,
    (s.unresolved_prerequisites || []).length ? el("div", {class: "muted"},
      (s.unresolved_prerequisites.length) + " declared prerequisite patch(es) not in the stack (they may be in the base)") : null);
}

function renderAdhoc() {
  const runs = index.adhoc || [];
  document.getElementById("adhoc-section").hidden = !runs.length;
  document.getElementById("adhoc").replaceChildren(...runs.map(r =>
    el("div", {}, el("h3", {}, el("code", {}, r.run), " ", r.title || "", " ", badge(r.state === "done" ? "none" : "info", r.state)),
      el("p", {class: "muted"}, "on " + r.base.branch + " " + r.base.commit.slice(0, 12) +
         (r.baseline ? " · compared with " + r.baseline : " · no baseline"), r.ci_url ? [" · ", link(r.ci_url, "workflow run")] : null),
      el("ol", {}, r.stack.map(seriesLine)),
      el("table", {class: "cases"},
        el("tr", {}, ["board / stack", "state", "fingerprint", "boots Linux", "vs baseline", "new failures", "new passes", "LAVA"].map(h => el("th", {}, h))),
        r.cells.map(c => el("tr", {}, el("td", {}, c.board + " / " + c.stack),
          el("td", {}, stateBadge(c), c.state_detail ? el("div", {class: "muted"}, c.state_detail) : null),
          el("td", {}, badge(verdictClass(c.gate), c.gate)),
          el("td", {}, badge(verdictClass(c.boot), c.boot), " ", el("span", {class: "muted"}, c.boot === "fail" ? (STAGE[c.boot_stage] || c.boot_stage) : "")),
          el("td", {}, VERSUS[c.versus] ? badge(VERSUS[c.versus][0], c.versus) : el("span", {class: "muted"}, c.versus)),
          el("td", {}, (c.diff.new_fail || []).join(", ")), el("td", {}, (c.diff.new_pass || []).join(", ")),
          el("td", {}, link(c.job_url, "job"))))))));
}

function renderRuns() {
  document.getElementById("runs").replaceChildren(...(index.runs || []).map(r =>
    el("li", {}, el("code", {}, r.id), badge(r.state === "done" ? "none" : "info", r.state), r.kind,
       el("span", {class: "muted"}, r.created.replace("T", " ").replace("Z", " UTC")),
       el("code", {}, r.base.commit.slice(0, 12)), el("span", {}, r.title || ""))));
}

async function refresh() {
  try {
    const r = await fetch("index.json", {cache: "no-store"});
    index = await r.json();
  } catch (e) {
    document.getElementById("updated").textContent = " (could not load index.json)";
    return;
  }
  document.getElementById("updated").textContent = " Updated " + index.updated.replace("T", " ").replace("Z", " UTC") + ".";
  renderBranches();
  refreshView();
  renderCandidates(); renderAdhoc(); renderRuns();
}

function refreshView() {
  renderBranches();
  const latest = (index.runs || []).find(r => r.id === view().latest_nightly);
  document.getElementById("run-title").textContent = latest ? latest.id : "(none yet)";
  const lx = view().linux;
  document.getElementById("run-meta").replaceChildren(el("span", {},
    latest ? ["U-Boot ", el("code", {}, latest.base.branch + " " + latest.base.commit.slice(0, 12)), " · "] : null,
    lx ? ["Linux ", el("code", {}, lx.tag), " (" + lx.release + ", defconfig, kernel sha256 ",
          el("code", {}, lx.image_sha256.slice(0, 16)), "…)"] : null));
  if (!selected && view().matrix.length) selected = view().matrix[0].board + "/" + view().matrix[0].stack;
  renderAlerts(); renderMatrix(); renderHost(); renderHistory();
  renderDetail();
}

refresh();
setInterval(refresh, POLL_MS);
