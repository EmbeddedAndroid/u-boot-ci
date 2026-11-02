"""Boot times of one LAVA job, for the run document (target.boot_time).

Host side: every boot in the job log measured by the vendored
lava-boottime parser, from LAVA's own console time stamps (power-on
command, U-Boot reset or kernel reboot to each stage). On target: the
values a boot-time test case printed on the board, from the kernel's own
clock. The two are kept apart: they have different zeros and never mix.
"""
import json
import os
import re

from . import collect
from .lava_boottime import parser

VERSION = 1
_VENDOR = json.load(open(os.path.join(os.path.dirname(__file__), "lava_boottime", "VENDOR.json")))
# The parser that measured, recorded with every measurement.
TOOL = "lava-boottime " + _VENDOR["commit"][:12]
# Every stage the parser knows, in boot order; the dashboard draws them in
# this order.
STAGES = list(parser.STAGE_ORDER)
# The stage the dashboard leads with: the firmware is done and Linux
# starts. Later stages depend on the image as much as on the firmware.
HEADLINE_STAGE = "linux"
WARM = {"reset": "warm-reset", "reboot": "warm-reboot"}
RESULT = re.compile(r"^([a-z0-9][a-z0-9_.-]*) (pass|fail|skip)(?: (-?\d+(?:\.\d+)?)(?: (\S+))?)?\s*$")
INFO = re.compile(r"^INFO: ([a-z0-9][a-z0-9_.-]*): (.+?)\s*$")


def _entry_index(text):
    """parser line number (position among all text lines) -> LAVA log
    entry index (position among '- {' lines, what a #L link counts)."""
    out, n = {}, 0
    for i, line in enumerate(text.splitlines()):
        if line.startswith("- {"):
            out[i] = n
            n += 1
    return out


def kind(boot, power_ons_before):
    """first: the first power-on of the job (after its flash, which can
    retrain DDR); cold: any later power-on; warm-reset: after U-Boot's
    reset command; warm-reboot: after the kernel's reboot."""
    if boot["ref_kind"] == "power-on":
        return "first" if power_ons_before == 0 else "cold"
    return WARM[boot["ref_kind"]]


def boots(text, job_url):
    """Every boot of the job log as a boot_time.boots entry."""
    idx = _entry_index(text)
    out, power_ons = [], 0
    for b in parser.parse(text):
        k = kind(b, power_ons)
        power_ons += b["ref_kind"] == "power-on"
        ref = idx.get(b["ref_line"], b["ref_line"])
        out.append({
            "kind": k,
            "ref_line": ref,
            "url": "%s#L%d" % (job_url, ref),
            "complete": b["complete"],
            "last_stage": b["last_stage"],
            "reset": b["reset"],
            "fastboot": b["fastboot"],
            "stages": {s: {"t": v["t"], "line": idx.get(v["line"], v["line"]),
                           "replayed": v["replayed"]}
                       for s, v in b["stages"].items()},
        })
    return out


def headline(boot_list):
    """Index of the boot the run is judged by: the last cold boot (a
    power-on after the first one), or None when the job had none."""
    cold = [i for i, b in enumerate(boot_list) if b["kind"] == "cold"]
    return cold[-1] if cold else None


def time_of(boot, stage):
    """A stage time that can be compared: reached and not replayed."""
    s = (boot or {}).get("stages", {}).get(stage)
    return None if s is None or s["replayed"] else s["t"]


def on_target(entries, suite, case, boot_list, job_url):
    """What the on-target boot-time case printed: its cases (name,
    result, value and units, or the reason of a skip) and the boot it ran
    in. None when the log has no such step."""
    got = collect.shell_output(entries, suite, case)
    if got is None:
        return None
    lines, finished = got
    cases, notes = {}, {}
    for _, text in lines:
        text = text.strip()
        m = RESULT.match(text)
        if m:
            c = {"name": m.group(1), "result": m.group(2)}
            if m.group(3) is not None:
                c["value"] = float(m.group(3))
                if m.group(4):
                    c["units"] = m.group(4)
            cases[c["name"]] = c
            continue
        m = INFO.match(text)
        if m:
            notes[m.group(1)] = m.group(2)
    for name, c in cases.items():
        if c["result"] != "pass" and name in notes:
            c["note"] = notes[name]
    first = lines[0][0] if lines else None
    boot = None
    if first is not None:
        before = [i for i, b in enumerate(boot_list) if b["ref_line"] < first]
        boot = before[-1] if before else None
    out = {"suite": suite, "case": case, "boot": boot, "finished": finished,
           "cases": [cases[k] for k in sorted(cases)]}
    if first is not None:
        out["url"] = "%s#L%d" % (job_url, first)
    return out


def measure(text, entries, job_url, on_target_step=None, tool=TOOL):
    """target.boot_time for a finished job. on_target_step: (suite, case)
    of the on-target boot-time shell check, when the job runs one."""
    bl = boots(text, job_url)
    bt = {"version": VERSION, "tool": tool, "boots": bl, "headline": headline(bl)}
    if on_target_step:
        ot = on_target(entries, on_target_step[0], on_target_step[1], bl, job_url)
        if ot is not None:
            bt["on_target"] = ot
    return bt


# Regression threshold: a stage moved when the run and the baseline differ
# by more than 3 standard deviations of a difference of two boots
# (3 * sqrt(2) * sigma), sigma estimated robustly (1.4826 * median absolute
# deviation) from the same series' recent runs, never under the parser's
# resolution (the console is read in chunks of up to parser.CHUNK).
HISTORY_MAX = 10
HISTORY_MIN = 5
K = 3 * 2 ** 0.5
MAD_SIGMA = 1.4826
FLOOR = parser.CHUNK


def representative(bt, kind):
    """The boot of a kind a target is compared by: the headline for cold,
    else the last boot of that kind."""
    if not bt:
        return None
    if kind == "cold":
        return bt["boots"][bt["headline"]] if bt.get("headline") is not None else None
    of = [b for b in bt["boots"] if b["kind"] == kind]
    return of[-1] if of else None


def gated_stages():
    """Stages up to Booting Linux: the firmware's share, compared."""
    return STAGES[:STAGES.index(HEADLINE_STAGE) + 1]


def noise(values):
    """(sigma, threshold) from a series' recent values, or (None, None)
    with fewer than HISTORY_MIN of them."""
    if len(values) < HISTORY_MIN:
        return None, None
    s = sorted(values)
    med = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
    dev = sorted(abs(v - med) for v in values)
    mad = dev[len(dev) // 2] if len(dev) % 2 else (dev[len(dev) // 2 - 1] + dev[len(dev) // 2]) / 2
    sigma = MAD_SIGMA * mad
    return sigma, max(K * sigma, FLOOR)


def comparable_history(run, history):
    """The earlier runs a run's boot-time noise comes from: the nightlies of
    its base branch (another branch builds other code), never the run
    itself."""
    branch = run["run"].get("base", {}).get("branch")
    return [r for r in history or [] if r["run"]["id"] != run["run"]["id"] and r["run"].get("kind") == "nightly"
            and r["run"].get("base", {}).get("branch") == branch and r["run"]["created"] < run["run"]["created"]]


def series(history, board, stack, kind, stage):
    """The stage's times in the history runs (newest first, at most
    HISTORY_MAX) for this board, stack and boot kind: targets whose
    fingerprint gate passed, stages that were timed."""
    out = []
    for r in sorted(history or [], key=lambda r: r["run"]["created"], reverse=True):
        for t in r["targets"]:
            if t["board"] != board or t["stack"] != stack or t.get("fingerprint_gate") != "pass":
                continue
            v = time_of(representative(t.get("boot_time"), kind), stage)
            if v is not None:
                out.append(v)
        if len(out) >= HISTORY_MAX:
            break
    return out[:HISTORY_MAX]


def _verdict(delta, threshold):
    if threshold is None:
        return "no-history"
    return "regression" if delta > threshold else "improvement" if delta < -threshold else "same"


def compare_kind(now, then, board, stack, kind, history):
    """One boot kind of a target against the baseline target."""
    a, b = representative(now, kind), representative(then, kind)
    if a is None or b is None:
        return {"verdict": "unknown"}
    gated = gated_stages()
    stages = {}
    for st in gated:
        x, y = time_of(a, st), time_of(b, st)
        if x is None or y is None:
            continue
        sigma, thr = noise(series(history, board, stack, kind, st))
        d = round(x - y, 3)
        stages[st] = {"now": x, "then": y, "delta": d, "threshold": None if thr is None else round(thr, 3),
                      "verdict": _verdict(d, thr)}
    # The baseline reached Linux and this run did not: slower by any
    # measure, whatever the times of the stages before.
    if HEADLINE_STAGE in b["stages"] and HEADLINE_STAGE not in a["stages"]:
        return {"verdict": "stopped-earlier", "stage": HEADLINE_STAGE, "now": None,
                "then": time_of(b, HEADLINE_STAGE), "delta": None, "threshold": None, "noise": None,
                "history": 0, "stages": stages}
    # Booting Linux when both have it, else the last stage both timed.
    st = next((s for s in reversed(gated) if s in stages), None)
    if st is None:
        return {"verdict": "unknown", "stages": stages}
    vals = series(history, board, stack, kind, st)
    sigma, thr = noise(vals)
    c = stages[st]
    return {"verdict": c["verdict"], "stage": st, "now": c["now"], "then": c["then"], "delta": c["delta"],
            "threshold": c["threshold"], "noise": None if sigma is None else round(sigma, 4),
            "history": len(vals), "stages": stages}


def compare(t, b, baseline_id, history):
    """boot_time.versus_baseline of target t against baseline target b
    (same board and stack): per boot kind both have."""
    now, then = t.get("boot_time"), (b or {}).get("boot_time")
    if not now:
        return None
    kinds = {}
    for kind in ("cold", "first", "warm-reset", "warm-reboot"):
        if representative(now, kind) is None:
            continue
        if not then or t.get("fingerprint_gate") != "pass" or b.get("fingerprint_gate") != "pass":
            kinds[kind] = {"verdict": "unknown"}
        else:
            kinds[kind] = compare_kind(now, then, t["board"], t["stack"], kind, history)
    return {"baseline": baseline_id, "kinds": kinds}


# The stock reference: the board's downstream (vendor) firmware booting its
# own image, from the lab's health checks: a power-on to the login prompt.
REFERENCE_JOBS = 5


def reference_boot(text, job_url):
    """The boot a health check is measured by: its last power-on (the first
    one after a flash can retrain DDR), or None."""
    on = [b for b in boots(text, job_url) if b["kind"] in ("first", "cold")]
    return on[-1] if on else None


def reference(lava, device_type, before=None, limit=REFERENCE_JOBS, exclude=lambda device: False):
    """The newest `limit` health checks of a device type that ended before
    `before` (ISO time, None for now), completed and booted, on devices
    not excluded: one boot each, with its job. Boots from storage only,
    or fastboot boots only where the type has no other."""
    direct, fastboot = [], []
    for j in lava.jobs(limit=limit * 4, requested_device_type=device_type, health_check="true",
                       health="Complete", end_time__lt=before):
        if j.get("health") != "Complete" or exclude(j.get("actual_device") or ""):
            continue
        url = lava.job_url(j["id"])
        b = reference_boot(lava.log(j["id"]), url)
        if b is None:
            continue
        # A kernel sent over fastboot puts the download into Booting Linux:
        # such boots compare only with each other, so boots from storage
        # are taken first.
        (fastboot if b["fastboot"] else direct).append(
            dict(b, job=j["id"], job_url=url, device=j.get("actual_device"), end_time=j.get("end_time")))
        if len(direct) == limit:
            break
    return direct or fastboot[:limit]


def reference_median(ref_boots):
    """Per stage, the median time over the reference boots, only where
    every boot timed the stage: dropping the replayed ones would keep the
    slow, live boots only and bias it."""
    out = {}
    for st in STAGES:
        vals = [time_of(b, st) for b in ref_boots]
        if ref_boots and all(v is not None for v in vals):
            s = sorted(vals)
            n = len(s)
            out[st] = round(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2, 3)
    return out
