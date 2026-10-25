// u-boot-ci dashboard: polls index.json (built by fwci.site) and renders it.
// Console lines and case names come from boards, so everything is set as
// text, never as HTML.
"use strict";

const POLL_MS = 60000;
const STAGE = {
  "login": "login prompt reached",
  "nothing-booted": "bootloader found nothing to boot, back at its prompt",
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
// Run documents keep the stack ids they were written with ("stock" for
// the downstream firmware stack); this is what a reader sees.
const STACK = {"stock": "downstream firmware", "open": "open stack", "stock-candidate": "downstream candidate"};
const KIND = {"nightly": "nightly", "adhoc": "ad-hoc", "series": "series", "pin-candidate": "pin candidate"};
const FRAGMENT = "board fragment not on this base";
let index = null, selected = null, branch = null, runCache = {};

function stackLabel(s) { return STACK[s] || s; }
// The view of the selected base branch (main, master).
function view() { return (index.branches || {})[branch] || index; }

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k === "onclick") e.onclick = v; else e.setAttribute(k, v);
  }
  for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
  return e;
}
function badge(cls, text) { return el("span", {class: "badge " + cls}, text); }
function link(href, text) { return href ? el("a", {href: href, rel: "noopener"}, text) : text; }
function short(sha) { return (sha || "").slice(0, 12); }
function verdictClass(v) { return v === "pass" ? "pass" : v === "fail" ? "fail" : "none"; }
// A run or target in one of these states is over (fwci-run/1).
const CLOSED = {done: "none", cancelled: "warn", error: "fail"};
function runBadge(state) { return badge(CLOSED[state] || "info", state); }
function stateBadge(c) {
  if (c.state in CLOSED) return runBadge(c.state);
  if (c.state === "skipped") return badge("warn", "skipped");
  const q = c.queue_position !== null && c.queue_position !== undefined ? " #" + c.queue_position : "";
  return badge("info", c.state + q);
}
function originClass(o) { return o === "upstream" ? "up" : o === "downstream" ? "down" : "none"; }

// The boot chain, each stage marked upstream or downstream.
function chain(stages, compact) {
  return el("div", {class: "chain" + (compact ? " compact" : "")}, (stages || []).map((s, i) => [
    i ? el("span", {class: "arrow", "aria-hidden": "true"}, "›") : null,
    el("span", {class: "stage " + originClass(s.origin),
                title: s.stage + ": " + (s.origin === "none" ? "not in this chain" : s.origin) + (s.detail ? " (" + s.detail + ")" : "")},
       s.stage, compact ? null : el("small", {}, s.origin === "none" ? " none" : " " + s.origin))]));
}

function renderAlerts() {
  const box = document.getElementById("alerts");
  box.replaceChildren();
  for (const c of view().matrix) {
    const v = VERSUS[c.versus];
    const who = c.board + " / " + stackLabel(c.stack) + ": ";
    if (c.versus === "regression" || c.versus === "upstream-gap") {
      box.append(el("div", {class: "alert " + v[0]}, el("b", {}, who + v[1] + ". "),
        "Stopped at: " + (STAGE[c.boot_stage] || c.boot_stage) + ". ", link(c.boot_url, "console")));
    }
    if (c.gate === "fail") {
      box.append(el("div", {class: "alert fail"}, el("b", {}, who),
        "fingerprint gate failed: the console did not show this build, its results are not counted. ",
        link(c.job_url, "LAVA job")));
    }
  }
}

function select(run, board, stack) {
  selected = {run: run, board: board, stack: stack};
  renderMatrix(); renderDetail();
}
function isSelected(run, b, s) { return selected && selected.run === run && selected.board === b && selected.stack === s; }

function renderMatrix() {
  const t = document.getElementById("matrix");
  t.replaceChildren();
  const boards = [...new Set(view().matrix.map(c => c.board))];
  const stacks = [...new Set(view().matrix.map(c => c.stack))];
  t.append(el("tr", {}, el("th"), stacks.map(s => el("th", {}, stackLabel(s)))));
  for (const b of boards) {
    const row = el("tr", {}, el("th", {}, b));
    for (const s of stacks) {
      const c = view().matrix.find(x => x.board === b && x.stack === s);
      if (!c) { row.append(el("td")); continue; }
      const n = c.counts;
      const dist = Object.entries(c.distance || {}).map(([k, v]) => k + " +" + v).join(", ");
      const cell = el("td", {class: "cell" + (isSelected(c.run, b, s) ? " sel" : ""), tabindex: "0",
                            onclick: () => select(c.run, b, s)},
        el("div", {class: "row"}, stateBadge(c), c.state_detail ? el("span", {class: "muted detail"}, c.state_detail) : null),
        (c.fragments_missing || []).length ? el("div", {class: "row"},
          badge("warn", FRAGMENT), el("span", {class: "muted"}, c.fragments_missing.join(", "))) : null,
        el("div", {class: "row"}, el("span", {}, "fingerprint"), badge(verdictClass(c.gate), c.gate)),
        el("div", {class: "row boot"}, el("span", {}, "boots Linux"),
          badge(verdictClass(c.boot), c.boot === "pass" ? "yes" : c.boot === "fail" ? "no" : "not run")),
        c.boot === "fail" ? el("div", {class: "muted"}, STAGE[c.boot_stage] || c.boot_stage) : null,
        el("div", {class: "row"}, el("span", {}, "cases"),
          el("span", {}, badge("pass", n.pass), " ", badge(n.fail ? "fail" : "none", n.fail), " ",
             badge("none", n.skip + n.unknown), n.flaky ? badge("warn", n.flaky + " flaky") : null)),
        c.new_fail ? el("div", {class: "row"}, el("span", {}, "new failures"), badge("fail", c.new_fail)) : null,
        chain(c.boot_chain, true),
        el("div", {class: "row"}, el("span", {}, "distance to upstream"),
          el("span", {class: "muted"}, dist || (s.startsWith("stock") ? "n/a" : "0"))));
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
  if (!runCache[id] || !(runCache[id].state in CLOSED)) {
    const r = await fetch("runs/" + encodeURIComponent(id) + ".json", {cache: "no-store"});
    runCache[id] = await r.json();
  }
  return runCache[id];
}

function commitLink(c) {
  return c.commit ? link(c.url, el("code", {}, short(c.commit))) : null;
}

// One component, exactly: where it comes from and how to get the same bits.
function component(c, r) {
  const head = el("div", {class: "comp-head"}, el("b", {}, c.name), " ",
    c.origin ? badge(originClass(c.origin), c.origin) : null, " ",
    c.role === "under-test" ? badge("info", "under test") : null,
    c.repo ? [" ", link(c.repo, c.repo.replace(/^https:\/\//, ""))] : null,
    c.branch ? [" ", el("code", {}, c.branch)] : null, c.commit ? " " : null, commitLink(c),
    c.release && c.name !== "linux" ? " " + c.release : "",
    c.fingerprint ? [" · fingerprint ", el("code", {}, c.fingerprint)] : null,
    c.sha256 ? [" · sha256 ", el("code", {class: "sha"}, c.sha256)] : null);
  const body = [];
  if (c.pending) body.push(el("div", {class: "warnline"}, badge("warn", "not public yet"), " " + c.pending +
    ": the open stack is skipped until the pinned commit is published"));
  if (c.soc_branch) body.push(el("div", {class: "muted"}, "platform branch ", el("code", {}, c.soc_branch.name), " ",
    link(c.soc_branch.url, el("code", {}, short(c.soc_branch.commit)))));
  if (c.name === "u-boot" && r && (r.run.stack || []).length)
    body.push(el("div", {}, "with the series applied, in order:", el("ol", {}, r.run.stack.map(s =>
      el("li", {}, link(s.link, s.title), el("span", {class: "muted"}, " v" + s.version + ", " + s.patches + " patches"))))));
  if (c.name === "u-boot" && c.role === "under-test" && r && !(r.run.stack || []).length)
    body.push(el("div", {class: "muted"}, "no series applied: plain " + (c.branch || "base")));
  if ((c.configs || []).length)
    body.push(el("div", {}, "configs ", c.configs.map(x => [
      el("code", {class: x.used === false ? "missing" : ""}, x.name), x.used === false && x.optional ? [" ", badge("warn", FRAGMENT)] : null,
      x.used === null ? el("span", {class: "muted"}, " (not built)") : null, " "]),
      c.device_tree ? [" · device tree ", el("code", {}, c.device_tree)] : null));
  if ((c.files || []).length)
    body.push(el("ul", {class: "files"}, c.files.map(f => el("li", {}, link(f.url, f.name), " sha256 ", el("code", {class: "sha"}, f.sha256)))));
  if ((c.layers || []).length)
    body.push(el("div", {}, "pinned from ", c.layers.map(l => [el("code", {}, l.name), " ", link(l.url, el("code", {}, short(l.commit))),
      l.recipes ? [" (", link(l.recipes, "recipes"), ")"] : null, " "])));
  if (c.name === "linux") {
    body.push(el("div", {}, "kernel ", el("code", {}, c.release || ""),
      c.config ? [" · config ", link(c.config.url, el("code", {}, c.config.name))] : null,
      " · DTB ", (c.dtbs || []).map((d, i) => [i ? " + " : "", link(d.url, el("code", {}, d.name))])));
  }
  const up = c.upstream;
  if (up) {
    body.push(el("div", {}, "distance to upstream ", badge(up.distance ? "warn" : "pass", up.distance)));
    if ((up.carried || []).length)
      body.push(el("ul", {}, up.carried.map(p => el("li", {}, el("code", {}, p.commit.slice(0, 10)), " ",
        p.review ? link(p.review, p.subject) : p.subject + " (not posted)"))));
  }
  return el("div", {class: "comp"}, head, body);
}

async function renderDetail() {
  const box = document.getElementById("detail");
  if (!selected) return;
  const r = await run(selected.run);
  const t = r.targets.find(x => x.board === selected.board && x.stack === selected.stack);
  document.getElementById("detail-title").textContent =
    selected.board + " / " + stackLabel(selected.stack) + " · " + (KIND[r.run.kind] || r.run.kind) + " " + r.run.id;
  if (!t) { box.replaceChildren(el("p", {class: "muted"}, "No such target in this run.")); return; }
  const lb = t.linux_boot || {};
  const parts = [];
  parts.push(el("p", {}, "Fingerprint ", el("code", {}, t.fingerprint || ""), " · ",
    t.lava ? link(t.lava.url, "LAVA job " + t.lava.job_id) : "not submitted",
    t.lava && t.lava.device ? " on " + t.lava.device : "",
    " · lab firmware restore: ", badge(verdictClass(t.restore === "recovery-job" ? "" : t.restore), t.restore || "not-run"),
    t.recovery ? [" ", link(t.recovery.url, "recovery job")] : null,
    " · ", link("runs/" + encodeURIComponent(r.run.id) + ".json", "run document")));
  if (t.state_detail) parts.push(el("p", {class: "muted"}, t.state + ": " + t.state_detail));
  // Run documents from before the boot chain was recorded have none.
  if ((t.boot_chain || []).length) parts.push(el("h3", {}, "Boot chain"), chain(t.boot_chain, false));
  parts.push(el("h3", {}, "Boots Linux: ", badge(verdictClass(lb.verdict), lb.verdict || "not-run"), " ",
    el("span", {class: "muted"}, STAGE[lb.stage] || lb.stage || "")));
  if (lb.versus_baseline && VERSUS[lb.versus_baseline])
    parts.push(el("p", {}, badge(VERSUS[lb.versus_baseline][0], VERSUS[lb.versus_baseline][1])));
  if ((lb.gaps || []).length)
    parts.push(el("p", {class: "muted"}, "Known upstream gaps for this stack: " + lb.gaps.join("; ")));
  if ((lb.last_lines || []).length)
    parts.push(el("p", {}, "Last console lines ", link(lb.url, "(at this line in LAVA)")),
               el("pre", {class: "console"}, lb.last_lines.join("\n")));
  parts.push(el("h3", {}, "Tested software"));
  for (const c of t.components || []) parts.push(component(c, r));
  const d = t.diff || {};
  if (d.new_fail && d.new_fail.length) parts.push(el("p", {}, badge("fail", "new failures"), " " + d.new_fail.join(", ")));
  if (d.new_pass && d.new_pass.length) parts.push(el("p", {}, badge("pass", "new passes"), " " + d.new_pass.join(", ")));
  const key = selected.board + "/" + selected.stack;
  const nightly = r.run.kind === "nightly" ? ((index.branches || {})[r.run.base.branch] || {}) : {};
  const hist = (nightly.case_history || {})[key] || {runs: [], cases: {}};
  parts.push(el("h3", {}, "Cases ", r.run.kind === "nightly" ? el("span", {class: "muted"}, "(history: oldest left, newest right)") : null));
  const table = el("table", {class: "cases"}, el("tr", {}, el("th", {}, "suite / case"), el("th", {}, "result"),
    r.run.kind === "nightly" ? el("th", {}, "history") : null));
  for (const c of t.cases || []) {
    const id = c.suite + "/" + c.name;
    const h = hist.cases[id] || "";
    table.append(el("tr", {}, el("td", {}, link(c.url, id)),
      el("td", {}, badge(c.result === "pass" ? "pass" : c.result === "fail" ? "fail" : "none", c.result),
        c.flake ? [" ", badge("warn", "flake " + c.flake)] : null,
        c.note ? [" ", el("span", {class: "muted"}, c.note)] : null),
      r.run.kind === "nightly" ? el("td", {class: "hist"}, [...h].map(ch => el("span", {class: ch === "-" ? "x" : ch}, ch === "p" ? "●" : ch === "f" ? "✕" : "·"))) : null));
    if ((c.output || []).length)
      table.append(el("tr", {}, el("td", {colspan: r.run.kind === "nightly" ? 3 : 2},
        el("pre", {class: "console"}, c.output.join("\n")))));
  }
  parts.push(el("div", {class: "table-wrap"}, table));
  box.replaceChildren(...parts);
}

function historyTable(name, hist) {
  const rows = Object.entries(hist || {}).sort();
  if (!rows.length) return null;
  return el("div", {}, el("h4", {}, name),
    el("div", {class: "table-wrap"}, el("table", {class: "cases"},
      el("tr", {}, el("th", {}, "board / stack"), el("th", {}, "boots Linux, oldest to newest"), el("th", {}, "latest")),
      rows.map(([k, cells]) => {
        const last = cells[cells.length - 1];
        const [b, s] = k.split("/");
        return el("tr", {}, el("td", {}, b + " / " + stackLabel(s)),
          el("td", {class: "hist"}, cells.map(c => el("span", {class: c.boot === "pass" ? "p" : c.boot === "fail" ? "f" : "x",
            title: c.run + ": " + (STAGE[c.boot_stage] || c.boot_stage)}, c.boot === "pass" ? "●" : c.boot === "fail" ? "✕" : "·"))),
          el("td", {}, last.counts.pass + " pass, " + last.counts.fail + " fail",
            (last.fragments_missing || []).length ? [" ", badge("warn", FRAGMENT)] : null));
      }))));
}

function renderHistory() {
  const names = branchNames();
  document.getElementById("history").replaceChildren(...names.map(n => historyTable(n, index.branches[n].history))
    .filter(x => x));
}

function renderCandidates() {
  const c = index.pin_candidates || {};
  if (!Object.keys(c).length) return;
  document.getElementById("candidates").replaceChildren(...Object.entries(c).sort().map(([board, r]) =>
    el("div", {}, el("h3", {}, board + " ", el("span", {class: "muted"}, r.title || ""), " ",
                     runBadge(r.state), " ", r.ci_url ? link(r.ci_url, "workflow run") : null),
      el("div", {class: "table-wrap"}, el("table", {class: "cases"},
        el("tr", {}, el("th", {}, "stack"), el("th", {}, "firmware"), el("th", {}, "fingerprint"),
           el("th", {}, "boots Linux"), el("th", {}, "cases"), el("th", {}, "LAVA")),
        r.cells.map(x => el("tr", {class: "click", onclick: () => select(r.run, x.board, x.stack)},
          el("td", {}, stackLabel(x.stack)), el("td", {}, x.firmware), el("td", {}, badge(verdictClass(x.gate), x.gate)),
          el("td", {}, badge(verdictClass(x.boot), x.boot), " ", el("span", {class: "muted"}, x.boot === "fail" ? (STAGE[x.boot_stage] || x.boot_stage) : "")),
          el("td", {}, x.counts.pass + " pass, " + x.counts.fail + " fail"), el("td", {}, link(x.job_url, "job")))))))));
}

function branchNames() {
  return Object.keys(index.branches || {}).sort((a, b) => a === "main" ? -1 : b === "main" ? 1 : a.localeCompare(b));
}

function renderBranches() {
  const names = branchNames();
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
  if (!runs.length) return;
  document.getElementById("adhoc").replaceChildren(...runs.map(r =>
    el("div", {class: "adhoc"}, el("h3", {}, el("code", {}, r.run), " ", r.title || "", " ", runBadge(r.state)),
      el("p", {class: "muted"}, "on ", link(r.base.url, r.base.branch + " " + short(r.base.commit)),
         r.baseline ? " · compared with nightly " + r.baseline : " · no baseline", r.ci_url ? [" · ", link(r.ci_url, "workflow run")] : null),
      el("ol", {}, r.stack.map(seriesLine)),
      el("div", {class: "table-wrap"}, el("table", {class: "cases"},
        el("tr", {}, ["board / stack", "state", "fingerprint", "boots Linux", "vs baseline", "new failures", "new passes", "LAVA"].map(h => el("th", {}, h))),
        r.cells.map(c => el("tr", {class: "click" + (isSelected(r.run, c.board, c.stack) ? " sel" : ""),
                                   onclick: () => select(r.run, c.board, c.stack)},
          el("td", {}, c.board + " / " + stackLabel(c.stack)),
          el("td", {}, stateBadge(c), c.state_detail ? el("div", {class: "muted"}, c.state_detail) : null,
            (c.fragments_missing || []).length ? el("div", {}, badge("warn", FRAGMENT)) : null),
          el("td", {}, badge(verdictClass(c.gate), c.gate)),
          el("td", {}, badge(verdictClass(c.boot), c.boot), " ", el("span", {class: "muted"}, c.boot === "fail" ? (STAGE[c.boot_stage] || c.boot_stage) : "")),
          el("td", {}, VERSUS[c.versus] ? badge(VERSUS[c.versus][0], c.versus) : el("span", {class: "muted"}, c.versus)),
          el("td", {}, (c.diff.new_fail || []).join(", ")), el("td", {}, (c.diff.new_pass || []).join(", ")),
          el("td", {}, link(c.job_url, "job")))))))));
}

function renderRuns() {
  const groups = {};
  for (const r of index.runs || []) (groups[r.kind] = groups[r.kind] || []).push(r);
  document.getElementById("runs").replaceChildren(...["nightly", "adhoc", "series", "pin-candidate"].filter(k => groups[k]).map(k =>
    el("div", {}, el("h3", {}, KIND[k]), el("ul", {class: "runs"}, groups[k].map(r =>
      el("li", {}, el("code", {}, r.id), runBadge(r.state),
        el("span", {class: "muted"}, r.created.replace("T", " ").replace("Z", " UTC")),
        link(r.base.url, el("code", {}, r.base.branch + " " + short(r.base.commit))), el("span", {}, r.title || "")))))));
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
  refreshView();
  renderCandidates(); renderAdhoc(); renderRuns();
}

function refreshView() {
  renderBranches();
  const latest = (index.runs || []).find(r => r.id === view().latest_nightly);
  document.getElementById("run-title").textContent = latest ? latest.id : "(none yet)";
  const lx = view().linux;
  document.getElementById("run-meta").replaceChildren(el("span", {},
    latest ? ["U-Boot ", link(latest.base.url, el("code", {}, latest.base.branch + " " + short(latest.base.commit))), " · "] : null,
    lx ? ["Linux ", link(lx.tag_url, el("code", {}, lx.tag)), " ", link(lx.url, el("code", {}, short(lx.commit))),
          " (" + lx.release + ", defconfig, kernel sha256 ", el("code", {}, lx.image_sha256.slice(0, 16)), "…)"] : null));
  if (!selected && view().matrix.length) selected = {run: view().matrix[0].run, board: view().matrix[0].board, stack: view().matrix[0].stack};
  renderAlerts(); renderMatrix(); renderHost(); renderHistory();
  renderDetail();
}

refresh();
setInterval(refresh, POLL_MS);
