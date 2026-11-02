#!/usr/bin/env python3
"""mk-boottime-fixture.py <job log> <output.yaml> [<suite>/<case>]

Cuts a public LAVA job log down to a test fixture for fwci.boottime: the
dispatcher lines the boot-time parser reads (actions, power commands,
login prompt matches), the console lines it measures and, with
<suite>/<case>, every line of that shell check (the on-target boot-time
case). Power command arguments (board serials) and addresses are
dropped. Fails unless the cut log measures exactly like the full one.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fwci.lava_boottime import parser  # noqa: E402

SCRUB = [
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"), "192.0.2.1"),
    (re.compile(r"\bip-\d+-\d+-\d+-\d+\b"), "ip-host"),
]


def dt_of(raw):
    return re.search(r'"dt": "([^"]+)"', raw).group(1)


def measured(text):
    out = []
    for b in parser.parse(text):
        for st in b["stages"].values():
            st.pop("line")
        for st in b["lava"].values():
            st.pop("line")
        b.pop("ref_line")
        out.append(b)
    return out


def step_lines(lines, suite, case):
    """Parser line numbers of a shell check: from LAVA waiting for its
    verdict to its result."""
    start = next((ln.n for ln in lines if ln.lvl == "debug" and isinstance(ln.msg, str)
                  and ln.msg.startswith("Waiting for") and "'@@ %s fail @@'" % case in ln.msg), None)
    if start is None:
        sys.exit("no shell check %s/%s in the log" % (suite, case))
    end = next((ln.n for ln in lines if ln.n > start and ln.lvl == "results"
                and isinstance(ln.msg, dict) and ln.msg.get("case") == case), None)
    return set(range(start, (end if end is not None else lines[-1].n) + 1))


def main(raw_path, out_path, step=None):
    text = open(raw_path, encoding="utf-8").read()
    raw = text.splitlines()
    lines = parser.load(text)
    full = parser.boots(lines)
    keep = {b.ref_line for b in full}
    keep |= {s.line for b in full for s in b.stages.values()}
    keep |= {b.loader_build_line for b in full}
    keep |= {b.reset_line for b in full}
    if step:
        keep |= step_lines(lines, *step.split("/", 1))
    # The lines around the moment the console goes live set the extent of
    # a backlog burst: their timing is kept, not their text.
    timing = [(b.ref_t + b.live, b.ref_t + b.live + 1.0) for b in full]
    out = []
    for ln in lines:
        msg = ln.msg if isinstance(ln.msg, str) else ""
        if ln.n in keep and not parser.CALLING.match(msg):
            line = raw[ln.n]
        elif ln.lvl == "target":
            if parser.ATTACH.match(parser.clean(msg)) or parser.REBOOT.search(msg) or \
                    parser.UBOOT_RESET.match(parser.clean(msg)):
                line = raw[ln.n]
            elif any(a <= ln.t <= z for a, z in timing):
                line = "- " + json.dumps({"dt": dt_of(raw[ln.n]), "lvl": "target", "msg": "."})
            else:
                continue
        elif parser.ACTION.match(msg) or parser.LOGIN_MATCH.search(msg):
            line = raw[ln.n]
        elif ln.lvl == "results" and isinstance(ln.msg, dict) and ln.msg.get("case") in parser.LAVA_CASES:
            # Only LAVA's timing: "extra" carries kernel messages.
            line = "- " + json.dumps({"dt": dt_of(raw[ln.n]), "lvl": "results", "msg": {
                k: ln.msg[k] for k in ("definition", "case", "level", "duration", "result") if k in ln.msg}})
        elif parser.CALLING.match(msg):
            word = "sleep" if parser.CALLING.match(msg).group(1).startswith("'sleep'") else "power"
            line = "- " + json.dumps({"dt": dt_of(raw[ln.n]), "lvl": ln.lvl, "msg": "Calling: ['%s']" % word})
        else:
            continue
        # Action levels ("start: 1.3.2.1 ...") look like addresses.
        if not parser.ACTION.match(msg):
            for pat, rep in SCRUB:
                line = pat.sub(rep, line)
        out.append(line)
    cut = "\n".join(out) + "\n"
    if measured(cut) != measured(text):
        sys.exit("%s: the cut log does not measure like the full log" % raw_path)
    with open(out_path, "w") as f:
        f.write(cut)
    print("%s: %d -> %d lines, %d boots" % (out_path, len(raw), len(out), len(full)))


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    main(*sys.argv[1:])
