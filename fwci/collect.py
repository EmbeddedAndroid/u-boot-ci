"""Turn one LAVA job (record, results, log) into a target of the run
schema. Pure functions over data already fetched, so they test offline."""
import json
import re

import yaml

from . import boot_verdict
from .lava_jobs import END_MARK

STATE = {"Submitted": "queued", "Scheduling": "queued", "Scheduled": "flashing",
         "Running": "testing", "Canceling": "testing", "Finished": "done"}


def log_entries(text):
    """get_job_logs output ('- {...}' lines) as (index, level, message).
    The index is the entry's position in the LAVA log, which is what a
    #L link counts, so an entry that does not parse still takes its place."""
    out = []
    for line in text.splitlines():
        if not line.startswith("- {"):
            continue
        d = _entry(line[2:])
        msg = d.get("msg", "")
        out.append((len(out), d.get("lvl", ""), msg if isinstance(msg, str) else json.dumps(msg)))
    return out


def _entry(text):
    # Most entries are JSON; LAVA writes the rest with YAML escapes
    # (console bytes such as \0 or \x01) or tags that JSON rejects.
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return {}


def console(entries):
    return [(i, m) for i, lvl, m in entries if lvl == "target"]


def window(lines, start, end):
    """Console lines from the first match of start to the first match of
    end after it (end excluded); empty when start never matched."""
    s = re.compile(start)
    e = re.compile(end)
    out = None
    for idx, text in lines:
        if out is None:
            if s.search(text):
                out = [(idx, text)]
        elif e.search(text):
            break
        else:
            out.append((idx, text))
    return out or []


def suite_of(result):
    m = re.search(r"^definition: (\S+)", result.get("metadata") or "", re.M)
    return re.sub(r"^\d+_", "", m.group(1)) if m else str(result.get("suite"))


NOT_REACHED = "not reached: the job ended before this check started"


def started_levels(entries):
    """The action levels the job started ("start: 6.1 lava-test-monitor")."""
    out = set()
    for _, lvl, m in entries:
        hit = re.match(r"start: (\d+(?:\.\d+)*) ", m) if lvl in ("debug", "info") else None
        if hit:
            out.add(hit.group(1))
    return out


def cases(results, job_url, started=None):
    """The job's cases. LAVA reports the expected cases of a test action
    that never started (the job ended earlier) as failed; with the levels
    the job started (started), such a case is a skip that says so, not a
    failure: a check that did not run did not fail."""
    out = []
    for r in results:
        suite = suite_of(r)
        if suite == "lava":
            continue
        c = {"suite": suite, "name": r["name"],
             "result": r["result"] if r["result"] in ("pass", "fail", "skip") else "unknown"}
        level = re.search(r"^level: '?([0-9.]+)'?$", r.get("metadata") or "", re.M)
        if started is not None and c["result"] == "fail" and level and level.group(1) not in started:
            c["result"], c["note"] = "skip", NOT_REACHED
        if r.get("start_log_line") is not None:
            c["url"] = "%s#L%d" % (job_url, r["start_log_line"])
        out.append(c)
    return out


NO_VERDICT = "no verdict: the check did not finish before LAVA timed out"
OUTPUT_MAX = 200


def shell_output(entries, suite, name):
    """What a shell check (lava_jobs.shell_checks) printed: (lines,
    finished), lines being (index, text) between the echo of its command
    line and its '@@ <name> pass|fail @@' verdict; None when the log has
    no such check."""
    res = None
    for i, lvl, m in entries:
        if lvl == "results" and m.startswith("{"):
            d = json.loads(m)
            if re.sub(r"^\d+_", "", str(d.get("definition"))) == suite and d.get("case") == name:
                res = i
                break
    waiting = "'@@ %s fail @@'" % name
    start = next((i for i, lvl, m in reversed(entries[:res or 0])
                  if lvl == "debug" and m.startswith("Waiting for") and waiting in m), None)
    if start is None:
        return None
    echo_end = 'echo "%s""@@"' % END_MARK[:-2]
    verdict = re.compile(r"^@@ %s (pass|fail) @@$" % re.escape(name))
    echo, out = "", None
    for i, text in console(entries[start:res]):
        if out is None:
            echo += text
            if echo_end in echo:
                out = []
        elif verdict.match(text.strip()):
            return out, True
        else:
            out.append((i, text))
    return out or [], False


def add_output(case_list, entries, job_url):
    """A failed shell check carries the lines it printed (dmesg-errors:
    the kernel errors left), linked to the first; one that never printed
    its verdict says so, and keeps what it printed before it hung."""
    for c in case_list:
        if c["result"] != "fail":
            continue
        got = shell_output(entries, c["suite"], c["name"])
        if got is None:
            continue
        lines, finished = got
        if not finished:
            c["note"] = NO_VERDICT
        if lines:
            c["output"] = [t for _, t in lines[:OUTPUT_MAX]]
            if len(lines) > OUTPUT_MAX:
                c["output"].append("(%d more lines in the LAVA log)" % (len(lines) - OUTPUT_MAX))
            c["url"] = "%s#L%d" % (job_url, lines[0][0])
    return case_list


def suite_verdict(case_list, suite):
    got = [c["result"] for c in case_list if c["suite"] == suite and c.get("note") != NOT_REACHED]
    if not got:
        return "not-run"
    return "pass" if all(r == "pass" for r in got) else "fail"


def target(base, job, results, entries, job_url, gate_suites, boot_start,
           boot_end=r"reboot: Restarting system|reboot: Power down",
           restore_suite="stock-restore"):
    """base: the target as the submitter wrote it (board, stack,
    fingerprint, components, lava). job: the LAVA job record. Returns the
    target updated with state, cases, the fingerprint gate, the boot
    verdict and the restore."""
    t = dict(base)
    t["state"] = STATE.get(job.get("state"), "queued")
    t["lava"] = dict(base.get("lava") or {}, job_id=job["id"], url=job_url,
                     device=job.get("actual_device"), health=job.get("health"))
    cl = cases(results, job_url, started_levels(entries) if entries else None)
    t["cases"] = add_output(cl, entries or [], job_url)
    # The first gate must pass; a later one counts when it ran (a board
    # that hangs after the first boot never reaches the second).
    gates = [suite_verdict(cl, s) for s in gate_suites]
    t["fingerprint_gate"] = ("fail" if "fail" in gates
                             else "not-run" if not gates or gates[0] == "not-run"
                             else "pass")
    boot = boot_verdict.classify(window(console(entries), boot_start, boot_end), job_url)
    if t["state"] != "done" and boot["verdict"] != "pass":
        boot = {"verdict": "not-run", "stage": "not-reached"}
    t["linux_boot"] = boot
    t["restore"] = suite_verdict(cl, restore_suite)
    if t["state"] == "done" and job.get("health") != "Complete":
        t["state_detail"] = "LAVA job %s" % (job.get("health") or "unknown").lower()
    return t


def queue_position(queue, job_id, device_type):
    """1-based place of a job in the LAVA queue of its device type (higher
    priority first, then submit order), or None when it is not queued."""
    q = sorted((j for j in queue if j.get("requested_device_type") == device_type),
               key=lambda j: (-(j.get("priority") or 0), j.get("submit_time") or ""))
    for i, j in enumerate(q):
        if j["id"] == job_id:
            return i + 1
    return None


def apply_known_gaps(case_list, gaps):
    """A failed case the board is known not to support (gaps: case id ->
    reason, documented with the board) counts as skipped, with the reason."""
    for c in case_list:
        reason = gaps.get("%s/%s" % (c["suite"], c["name"]))
        if reason and c["result"] == "fail":
            c["result"] = "skip"
            c["note"] = "known gap: " + reason
    return case_list
