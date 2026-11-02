// Boot time on the u-boot-ci dashboard: the line every matrix cell shows,
// the Boot time section (per board: stage bars of the latest boots and the
// history of time to Booting Linux) and the boot-time part of the detail
// view. Plain SVG built with the DOM: board and stage names are set as text.
// Uses el(), badge(), link() and stackLabel() from app.js.
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const BT_KINDS = {"cold": "cold boot", "warm-reset": "warm reset", "warm-reboot": "warm reboot",
                  "first": "first power-on after the flash"};
const BT_STAGE = {
  loader: "XBL starts", loader_end: "XBL ends (SBL1 End)", hyp: "hypervisor", uefi: "UEFI / ABL starts",
  ebs: "UEFI exits boot services", spl: "U-Boot SPL", bl2: "TF-A BL2", bl31: "TF-A BL31", optee: "OP-TEE",
  uboot: "U-Boot", linux: "Booting Linux", init: "init", login: "login prompt",
};
// Series: the stock reference, then the two stacks of the CI. Slots 1-3 of
// the validated categorical palette, in this fixed order (style.css).
const BT_SERIES = [
  {key: "stock-ref", label: "stock (health checks)", css: "--bt-s1"},
  {key: "stock", label: "downstream", css: "--bt-s2"},
  {key: "open", label: "open", css: "--bt-s3"},
  {key: "spl", label: "U-Boot SPL", css: "--bt-s4"},
];
// Phases of a bar, in boot order. Each starts where the one before ends:
// XBL to SBL1 End, then whatever runs before the bootloader (TF-A, OP-TEE,
// a hypervisor, an SPL), then UEFI / ABL / U-Boot up to Booting Linux.
const BT_PHASES = [
  {key: "xbl", label: "XBL", end: s => s.loader_end},
  {key: "secure", label: "TF-A, OP-TEE, hypervisor, SPL", end: s => s.uefi || s.uboot},
  {key: "boot", label: "UEFI, ABL, U-Boot", end: s => s.linux},
];
let btKind = null;

function svg(tag, attrs, ...kids) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
  return e;
}
function secs(t) { return t === null || t === undefined ? "-" : t.toFixed(t < 10 ? 2 : 1) + " s"; }
// A boot without a time (a job record without end_time) is listed, not drawn.
function when(t) { return Number.isFinite(t) ? new Date(t).toISOString().slice(0, 16).replace("T", " ") : "-"; }
function lineUrl(job, line) { return job && line !== undefined && line !== null ? job + "#L" + line : job; }
// A stage time that can be compared: reached and not in replayed backlog.
function timed(stages, k) { const s = (stages || {})[k]; return s && !s[2] ? s[0] : null; }
function seriesOf(stack) { return BT_SERIES.find(s => s.key === stack) || BT_SERIES[1]; }
function niceMax(v) {
  const steps = [1, 2, 2.5, 5, 10];
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(v, 0.1))));
  return steps.map(s => s * mag).find(s => s >= v) || 10 * mag;
}
function ticks(max) {
  const n = max / 5 >= 1 ? 5 : 4;
  return Array.from({length: n + 1}, (_, i) => +(max * i / n).toFixed(2));
}

// The boot verdict against the baseline: a status (icon and words, never
// color alone) for a regression or a stop, the delta otherwise.
const BT_VERDICT = {
  regression: ["fail", "▲ slower"], "stopped-earlier": ["fail", "■ stopped earlier"],
  improvement: ["pass", "▼ faster"], same: ["none", "same"], "no-history": ["none", "too little history"],
};
function verdictBadge(p) {
  if (!p || !p.verdict || p.verdict === "unknown") return null;
  const [cls, words] = BT_VERDICT[p.verdict] || ["none", p.verdict];
  const d = p.delta === null || p.delta === undefined ? "" : " " + (p.delta > 0 ? "+" : "") + p.delta.toFixed(2) + " s";
  const b = badge(cls, words + d);
  b.title = p.verdict === "no-history" ? "fewer than 5 earlier runs of this series: the difference is not judged"
    : p.threshold !== null && p.threshold !== undefined ? "threshold " + p.threshold.toFixed(3) + " s, from the noise of this series" : "";
  return b;
}

// The row a matrix cell shows.
function bootRow(c) {
  const b = c.boot_time;
  if (!b) return null;
  const kind = b.kind === "cold" ? "cold" : "warm reset";
  const value = b.linux !== null ? secs(b.linux)
    : b.linux_replayed ? "Linux line not timed"
    : "stopped at " + (BT_STAGE[b.last_stage] || b.last_stage || "?");
  return el("div", {class: "row", title: "time to Booting Linux, host side, " + BT_KINDS[b.kind]},
    el("span", {}, "boot → Linux"),
    el("span", {class: "bt-cell"}, el("b", {class: "num"}, value), " ", el("span", {class: "muted"}, kind),
      " ", verdictBadge(b)));
}

// Bars: one per series, split into phases with a 2px surface gap.
function phaseSegments(stages) {
  const segs = [];
  let start = 0, pending = [];
  for (const ph of BT_PHASES) {
    const v = ph.end(stages);
    pending.push(ph);
    if (v === null || v === undefined) continue;
    segs.push({from: start, to: v, phases: pending});
    start = v; pending = [];
  }
  return segs;
}
function timedStages(stages) {
  // name -> time, for the stages that were timed (for the bars' phases)
  const out = {};
  for (const k of Object.keys(stages || {})) { const t = timed(stages, k); if (t !== null) out[k] = t; }
  return out;
}

function barChart(board, rows, tip, W) {
  // Narrow: each label on its own line above its bar.
  const narrow = W < 460;
  const rowH = narrow ? 42 : 30, barH = 14, left = narrow ? 18 : 150, right = narrow ? 120 : 54, top = 6;
  const H = top + rows.length * rowH + 26;
  // A boot that never reached Linux is drawn up to the last stage it timed.
  for (const r of rows) {
    if (r.linux) continue;
    const ts = Object.entries(timedStages(r.stages)).sort((a, b) => a[1] - b[1]);
    if (ts.length) { r.reached = ts[ts.length - 1][1]; r.reachedStage = ts[ts.length - 1][0]; }
  }
  const max = niceMax(Math.max(...rows.filter(r => !r.blocked).map(r => r.linux || r.reached || 0), 1));
  const x = t => left + (W - left - right) * t / max;
  const g = svg("svg", {viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "bt-bars", role: "img",
                        "aria-label": board + ": time to Booting Linux per phase"});
  for (const t of ticks(max)) {
    g.append(svg("line", {x1: x(t), x2: x(t), y1: top, y2: H - 22, class: "grid"}),
             svg("text", {x: x(t), y: H - 6, class: "tick", "text-anchor": "middle"}, t + " s"));
  }
  rows.forEach((r, i) => {
    const y = top + i * rowH + (narrow ? rowH - barH - 4 : (rowH - barH) / 2);
    const series = seriesOf(r.series);
    const ly = narrow ? y - 6 : y + barH / 2 + 4;
    g.append(svg("circle", {cx: 8, cy: ly - 4, r: 4, style: "fill: var(" + series.css + ")"}),
             svg("text", {x: 18, y: ly, class: "label"}, r.label));
    const end = r.linux || r.reached;
    if (!end || r.blocked) {
      g.append(svg("text", {x: left, y: y + barH / 2 + 4, class: "note"}, r.note || "no boot to Linux"));
      return;
    }
    const stages = timedStages(r.stages);
    if (!r.linux) stages.linux = r.reached;
    const segs = phaseSegments(stages);
    segs.forEach((s, j) => {
      const known = s.phases.length === 1;
      const step = known ? BT_PHASES.indexOf(s.phases[0]) : -1;
      const w = Math.max(x(s.to) - x(s.from) - (j < segs.length - 1 ? 2 : 0), 1);
      const last = j === segs.length - 1;
      // Square at the baseline, a 4px rounded data end.
      const d = last
        ? "M" + x(s.from) + "," + y + "h" + Math.max(w - 4, 0) + "a4,4 0 0 1 4,4v" + (barH - 8) + "a4,4 0 0 1 -4,4h" + (-Math.max(w - 4, 0)) + "z"
        : "M" + x(s.from) + "," + y + "h" + w + "v" + barH + "h" + (-w) + "z";
      const seg = svg("path", {d: d, class: "seg " + (known ? "p" + step : "untimed"), tabindex: "0",
                               style: known ? "fill: var(" + series.css + ")" : ""});
      const text = () => [r.label + " (" + r.run + "): " + s.phases.map(p => p.label).join(" + "),
        secs(s.from) + " → " + secs(s.to) + " (" + secs(s.to - s.from) + ")",
        known ? null : "the boundary between these phases was not timed (replayed console)",
        ...stagesIn(r.stages, s.from, s.to)];
      seg.addEventListener("pointermove", ev => tip.show(ev, text()));
      seg.addEventListener("focus", ev => tip.showAt(seg, text()));
      seg.addEventListener("pointerleave", () => tip.hide());
      seg.addEventListener("blur", () => tip.hide());
      g.append(seg);
    });
    g.append(svg("text", {x: x(end) + 6, y: y + barH / 2 + 4, class: "value"},
      r.linux ? secs(r.linux) : "stopped at " + (BT_STAGE[r.reachedStage] || r.reachedStage) + ", " + secs(end)));
  });
  return g;
}
function stagesIn(stages, from, to) {
  return Object.entries(stages || {}).filter(([, v]) => v[0] >= from - 1e-9 && v[0] <= to + 1e-9)
    .sort((a, b) => a[1][0] - b[1][0])
    .map(([k, v]) => (BT_STAGE[k] || k) + "  " + secs(v[0]) + (v[2] ? " (replayed, not timed)" : ""));
}

// History: time to Booting Linux per series, a crosshair snapping to the
// nearest boot, every point a link to its log line.
function historyChart(board, series, tip, W) {
  const H = 200, left = 40, right = 64, top = 10, bottom = 26;
  series = series.map(s => Object.assign({}, s, {points: s.points.filter(p => Number.isFinite(p.time))}));
  const pts = series.flatMap(s => s.points.map(p => Object.assign({s: s}, p)));
  if (!pts.length) return el("p", {class: "muted"}, "No boot of this kind reached Booting Linux; the table lists where each stopped.");
  const t0 = Math.min(...pts.map(p => p.time)), t1 = Math.max(...pts.map(p => p.time));
  const span = Math.max(t1 - t0, 86400000);
  const max = niceMax(Math.max(...pts.map(p => p.linux)) * 1.05);
  const x = t => left + (W - left - right) * (t - t0) / span;
  const y = v => top + (H - top - bottom) * (1 - v / max);
  const g = svg("svg", {viewBox: "0 0 " + W + " " + H, width: W, height: H, class: "bt-history", role: "img",
                        "aria-label": board + ": time to Booting Linux over time"});
  for (const v of ticks(max)) {
    g.append(svg("line", {x1: left, x2: W - right, y1: y(v), y2: y(v), class: v ? "grid" : "axis"}),
             svg("text", {x: left - 6, y: y(v) + 4, class: "tick", "text-anchor": "end"}, v + " s"));
  }
  const days = Math.max(1, Math.round(span / 86400000));
  const every = Math.ceil(days / Math.max(2, Math.floor((W - left - right) / 70)));
  for (let d = 0; d <= days; d += every) {
    const t = t0 + d * 86400000;
    g.append(svg("text", {x: x(t), y: H - 8, class: "tick", "text-anchor": "middle"},
                 new Date(t).toISOString().slice(5, 10)));
  }
  const ends = [];
  for (const s of series) {
    if (!s.points.length) continue;
    const css = "var(" + s.series.css + ")";
    if (s.points.length > 1)
      g.append(svg("polyline", {class: "line", style: "stroke: " + css,
        points: s.points.map(p => x(p.time) + "," + y(p.linux)).join(" ")}));
    for (const p of s.points) {
      const a = svg("a", {href: p.url, target: "_blank", rel: "noopener", "aria-label":
        s.series.label + " " + when(p.time) + " " + secs(p.linux)},
        svg("circle", {cx: x(p.time), cy: y(p.linux), r: 4, class: "dot", style: "fill: " + css}));
      a.addEventListener("focus", () => tip.showAt(a, pointText(s, p)));
      a.addEventListener("blur", () => tip.hide());
      g.append(a);
    }
    const last = s.points[s.points.length - 1];
    ends.push({y: y(last.linux), x: x(last.time), text: secs(last.linux)});
  }
  // Direct end labels only where they do not collide; the legend carries the rest.
  ends.sort((a, b) => a.y - b.y);
  let prev = -1e9;
  for (const e of ends) {
    if (e.y - prev >= 13) g.append(svg("text", {x: W - right + 8, y: e.y + 4, class: "value"}, e.text));
    prev = e.y;
  }
  const cross = svg("line", {class: "cross", y1: top, y2: H - bottom, x1: left, x2: left, visibility: "hidden"});
  const hit = svg("rect", {x: left, y: top, width: W - left - right, height: H - top - bottom, class: "hit"});
  g.append(cross, hit);
  const near = ev => {
    const r = g.getBoundingClientRect();
    const px = (ev.clientX - r.left) * W / r.width;
    let best = null;
    for (const p of pts) if (!best || Math.abs(x(p.time) - px) < Math.abs(x(best.time) - px)) best = p;
    return best;
  };
  hit.addEventListener("pointermove", ev => {
    const p = near(ev);
    cross.setAttribute("x1", x(p.time)); cross.setAttribute("x2", x(p.time)); cross.setAttribute("visibility", "visible");
    // Every series at that moment: its boot nearest in time, within a day.
    const lines = [];
    for (const s of series) {
      const q = s.points.reduce((b, c) => !b || Math.abs(c.time - p.time) < Math.abs(b.time - p.time) ? c : b, null);
      if (q && Math.abs(q.time - p.time) <= 86400000) lines.push({series: s.series, value: secs(q.linux), sub: q.title});
    }
    tip.show(ev, pointText(p.s, p), lines);
  });
  hit.addEventListener("pointerleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); });
  hit.addEventListener("click", ev => { const p = near(ev); if (p && p.url) window.open(p.url, "_blank", "noopener"); });
  return g;
}
function pointText(s, p) {
  return [s.series.label + ": " + secs(p.linux) + " to Booting Linux", p.title,
          ...Object.entries(p.stages || {}).sort((a, b) => a[1][0] - b[1][0])
            .map(([k, v]) => (BT_STAGE[k] || k) + "  " + secs(v[0]) + (v[2] ? " (replayed)" : "")),
          "click: the LAVA log at Booting Linux"];
}

// One tooltip for the section: values lead, labels follow, line keys.
function makeTip(host) {
  const box = el("div", {class: "bt-tip", role: "tooltip"});
  box.hidden = true;
  host.append(box);
  const fill = (lines, rows) => {
    box.replaceChildren();
    if (rows && rows.length) box.append(el("div", {class: "rows"}, rows.map(r =>
      el("div", {}, el("span", {class: "key", style: "background: var(" + r.series.css + ")"}),
         el("b", {}, r.value), " ", el("span", {class: "muted"}, r.series.label)))));
    lines.filter(l => l).forEach((l, i) => box.append(el("div", {class: i ? "muted" : "head"}, l)));
    box.hidden = false;
  };
  const place = (cx, cy, node) => {
    const hr = host.getBoundingClientRect();
    // Stay over the card the pointer is in: flip left in its right half.
    const card = (node && node.closest && node.closest(".bt-board") || host).getBoundingClientRect();
    let left = cx - hr.left + 14, top = cy - hr.top + 14;
    if (cx > card.left + card.width / 2 || left + box.offsetWidth > hr.width)
      left = Math.max(card.left - hr.left, cx - hr.left - box.offsetWidth - 14);
    box.style.left = left + "px"; box.style.top = top + "px";
  };
  return {
    show(ev, lines, rows) { fill(lines, rows); place(ev.clientX, ev.clientY, ev.target); },
    showAt(node, lines) { fill(lines); const r = node.getBoundingClientRect(); place(r.right, r.top, node); },
    hide() { box.hidden = true; },
  };
}

function legend(items) {
  return el("div", {class: "bt-legend"}, items.map(s =>
    el("span", {}, el("span", {class: "key", style: "background: var(" + s.css + ")"}), s.label)));
}
function phaseLegend() {
  return el("div", {class: "bt-legend phases"}, "bar segments, left to right: ",
    BT_PHASES.map((p, i) => el("span", {}, el("span", {class: "key p" + i}), p.label)),
    el("span", {}, el("span", {class: "key untimed"}), "phases whose boundary was not timed"));
}

function btTable(rows) {
  const cols = ["", "date", "run / job", "device", "Booting Linux", "stopped at", "vs baseline", "stages (s after the reference)"];
  return el("details", {class: "bt-table"}, el("summary", {}, "Table"),
    el("div", {class: "table-wrap"}, el("table", {class: "cases"},
      el("tr", {}, cols.map(c => el("th", {}, c))),
      rows.map(r => el("tr", {},
        el("td", {}, el("span", {class: "key", style: "background: var(" + r.series.css + ")"}), " ", r.series.label),
        el("td", {class: "num"}, when(r.time)),
        el("td", {}, link(r.url, r.title)), el("td", {}, r.device || ""),
        el("td", {class: "num"}, r.linux === null ? "-" : secs(r.linux)),
        el("td", {}, r.linux !== null ? "" : (r.stages || {}).linux ? "Linux line not timed (replayed)"
          : (BT_STAGE[r.last_stage] || r.last_stage || "")),
        el("td", {}, verdictBadge(r) || (r.gate && r.gate !== "pass" ? badge("warn", "gate " + r.gate) : "")),
        el("td", {class: "stages"}, Object.entries(r.stages || {}).sort((a, b) => a[1][0] - b[1][0]).map(([k, v], i) =>
          [i ? " · " : "", link(lineUrl(r.job_url, v[1]), k), " " + (v[2] ? "(" + v[0] + ")" : v[0])])))))));
}

// The data of one board for the selected kind.
function boardSeries(view, stock, board, kind) {
  const out = [];
  if (kind === "cold") {
    const hs = (stock.history || {})[board] || [];
    const all = hs.map(p => ({
      time: Date.parse(p.end_time), linux: p.linux, stages: p.stages, url: lineUrl(p.job_url, (p.stages.linux || [])[1] ?? p.ref_line),
      title: "health check " + p.job + (p.fastboot ? " (kernel over fastboot)" : ""), device: p.device,
      job_url: p.job_url, last_stage: p.last_stage, fastboot: p.fastboot, job: p.job}));
    // A kernel sent over fastboot puts the download, which depends on the
    // device's lab wiring, into Booting Linux: such boots are not drawn,
    // only listed in the table.
    out.push({series: BT_SERIES[0], points: all.filter(p => p.linux !== null && !p.fastboot), all: all,
              fastboot: all.length > 0 && all.every(p => p.fastboot)});
  }
  const hist = ((view.boottime || {}).history || {})[board] || {};
  for (const stack of Object.keys(hist).sort((a, b) => BT_SERIES.findIndex(s => s.key === a) - BT_SERIES.findIndex(s => s.key === b))) {
    const ps = (hist[stack][kind] || []).map(p => ({time: Date.parse(p.created), linux: p.linux, stages: p.stages,
      url: lineUrl(p.job_url, (p.stages.linux || [])[1] ?? p.ref_line), title: p.run, device: p.device,
      job_url: p.job_url, last_stage: p.last_stage, gate: p.gate, verdict: p.verdict, delta: p.delta,
      threshold: p.threshold, on_target: p.on_target}));
    if (!ps.length) continue;
    const series = Object.assign({}, seriesOf(stack), {label: stackLabel(stack)});
    // A cell whose gate failed ran another build: kept in the table only.
    out.push({series: series, points: ps.filter(p => p.linux !== null && p.gate === "pass"), all: ps});
  }
  return out;
}

function barRows(series, stock, board, kind) {
  const rows = [];
  for (const s of series) {
    if (s.series.key === "stock-ref") {
      const m = (stock.median || {})[board];
      if (!m) continue;
      const med = Object.fromEntries(Object.entries(m.median).map(([k, v]) => [k, [v, null, 0]]));
      const fast = s.all.filter(p => m.jobs.includes(p.job)).some(p => p.fastboot);
      rows.push({series: "stock-ref", label: "stock", run: "median of " + m.jobs.length + " health checks",
                 linux: m.median.linux ?? null, stages: med, blocked: fast,
                 note: fast ? "health checks boot the kernel over fastboot: no fair reference" : null});
      continue;
    }
    const last = s.all[s.all.length - 1];
    rows.push({series: s.series.key, label: s.series.label, run: last.title,
               linux: last.gate === "pass" ? last.linux : null, stages: last.stages, blocked: last.gate !== "pass",
               note: last.gate !== "pass" ? "fingerprint gate " + last.gate + ": not this build" : null});
  }
  return rows;
}

function renderBoottime(view, index) {
  const box = document.getElementById("boottime");
  const stock = index.stock_boottime || {history: {}, median: {}};
  const hist = (view.boottime || {}).history || {};
  const boards = [...new Set([...Object.keys(hist), ...Object.keys(stock.median || {})])]
    .filter(b => hist[b] || ((stock.history || {})[b] || []).length).sort();
  if (!boards.length) {
    document.getElementById("bt-filters").replaceChildren();
    box.replaceChildren(el("p", {class: "muted"}, "No boot times yet."));
    return;
  }
  // Cold first; until cold boots have history, the warm resets that do.
  const counts = k => boards.reduce((n, b) => n + Object.values(hist[b] || {}).reduce((m, s) => m + (s[k] || []).length, 0), 0);
  if (!btKind) btKind = counts("cold") >= 3 * Math.max(1, boards.length) ? "cold" : "warm-reset";
  document.getElementById("bt-filters").replaceChildren(...["cold", "warm-reset", "warm-reboot"].map(k =>
    el("button", {class: "badge " + (k === btKind ? "info" : "none"), "aria-pressed": String(k === btKind),
                  onclick: () => { btKind = k; renderBoottime(view, index); }}, BT_KINDS[k] + " (" + counts(k) + ")")),
    el("span", {class: "muted"}, btKind === "cold" ? "" : " stock health checks have no warm boots: no stock series here"));
  const tipHost = el("div", {class: "bt-host"});
  const grid = el("div", {class: "bt-grid"});
  const tip = makeTip(tipHost);
  const width = box.clientWidth || 720;
  const cols = width >= 1000 ? 2 : 1;
  // The SVG's own units are CSS pixels: text keeps its size at any width.
  const W = Math.max(280, Math.floor((width - 16 * (cols - 1)) / cols) - 30);
  const empty = [];
  for (const b of boards) {
    const series = boardSeries(view, stock, b, btKind);
    const m = (stock.median || {})[b];
    if (!series.some(s => s.all.length)) { empty.push(b); continue; }
    grid.append(el("div", {class: "bt-board"},
      el("h3", {}, b, " ", el("span", {class: "muted"}, m ? m.device_type : "")),
      legend(series.map(s => s.series)),
      el("h4", {}, "Latest " + BT_KINDS[btKind] + " to Booting Linux"),
      barChart(b, barRows(series, stock, b, btKind), tip, W), phaseLegend(),
      el("h4", {}, "History, time to Booting Linux"),
      historyChart(b, series.filter(s => s.points.length), tip, W),
      btTable(series.flatMap(s => s.all.map(p => Object.assign({series: s.series}, p))).sort((x, y) => y.time - x.time))));
  }
  tipHost.append(grid);
  if (empty.length) tipHost.append(el("p", {class: "muted"}, "No " + BT_KINDS[btKind] + " measured yet: " + empty.join(", ") + "."));
  box.replaceChildren(tipHost);
  btLast = [view, index];
}
let btLast = null, btResize = null;
window.addEventListener("resize", () => {
  clearTimeout(btResize);
  btResize = setTimeout(() => { if (btLast) renderBoottime(...btLast); }, 150);
});

// The detail view: every boot of the target, the on-target view apart.
function bootDetail(t) {
  const bt = t.boot_time;
  if (!bt) return [];
  const job = (t.lava || {}).url;
  const out = [el("h3", {}, "Boot time ", el("span", {class: "muted"}, "(host side, s after the reference; " + bt.tool + ")"))];
  const vs = (bt.versus_baseline || {}).kinds || {};
  // The boot each kind is compared by: the headline for cold, else the
  // last boot of the kind (fwci.boottime.representative).
  const compared = {};
  bt.boots.forEach((b, i) => { if (b.kind !== "cold") compared[b.kind] = i; });
  if (bt.headline !== null && bt.headline !== undefined) compared.cold = bt.headline;
  const gate = t.fingerprint_gate;
  const stages = [...new Set(bt.boots.flatMap(b => Object.keys(b.stages)))]
    .sort((a, b) => BOOT_ORDER.indexOf(a) - BOOT_ORDER.indexOf(b));
  out.push(el("div", {class: "table-wrap"}, el("table", {class: "cases"},
    el("tr", {}, el("th", {}, "boot"), stages.map(s => el("th", {class: "num"}, BT_STAGE[s] || s)), el("th", {}, "vs baseline")),
    bt.boots.map((b, i) => el("tr", {class: i === bt.headline ? "sel" : ""},
      el("td", {}, link(b.url, BT_KINDS[b.kind] || b.kind), i === bt.headline ? [" ", badge("info", "headline")] : null,
        b.reset !== null && b.reset !== undefined ? el("div", {class: "muted"}, "board reset at " + secs(b.reset)) : null),
      stages.map(s => { const v = b.stages[s]; return el("td", {class: "num"}, v ? link(lineUrl(job, v.line),
        v.replayed ? "(" + v.t.toFixed(3) + ")" : v.t.toFixed(3)) : "-"); }),
      el("td", {}, compared[b.kind] !== i ? null : verdictBadge(vs[b.kind]) || el("span", {class: "muted"},
        (vs[b.kind] || {}).verdict !== "unknown" ? ""
          : gate !== "pass" ? "not compared: fingerprint gate " + gate : "no baseline boot of this kind")))))));
  out.push(el("p", {class: "legend"}, "(…) = arrived in replayed console backlog: only bounds the stage, never compared."));
  const ot = bt.on_target;
  if (ot) {
    out.push(el("h4", {}, "On target, from the kernel's own clock ", el("span", {class: "muted"},
      "(a separate view: its zero is not the power-on command)")),
      el("ul", {class: "checks"}, ot.cases.map(c => el("li", {}, el("span", {class: "name"}, c.name),
        c.result === "pass" && c.value !== undefined ? el("b", {class: "num"}, c.value + " " + (c.units || ""))
          : badge(c.result === "pass" ? "pass" : "none", c.result),
        c.note ? el("span", {class: "muted"}, c.note) : null))),
      el("p", {class: "muted"}, "ran in the ", BT_KINDS[(bt.boots[ot.boot] || {}).kind] || "boot", " · ", link(ot.url, "output in the LAVA log")));
  }
  return out;
}
const BOOT_ORDER = ["loader", "loader_end", "hyp", "uefi", "ebs", "spl", "bl2", "bl31", "optee", "uboot", "linux", "init", "login"];
