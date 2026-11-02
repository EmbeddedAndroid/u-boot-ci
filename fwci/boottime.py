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
