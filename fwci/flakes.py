"""The known-flake list. The bar to get in is high, so a failure is
explained, never hidden: a case that failed on the base branch with no
code change at least 3 times in 14 days, on at least 2 boards (or 3 runs
of a single-board device type), with a linked issue and a named suspected
cause. Entries expire 30 days after their last confirmation.

The known kernel-error allowlist (an entry names a `pattern` instead of a
`case`) is held to the same bar."""
import datetime

WINDOW_DAYS = 14
EXPIRE_DAYS = 30
REQUIRED = ("id", "issue", "suspected_cause", "confirmed", "failures")


def _date(s):
    return datetime.date.fromisoformat(str(s))


def densest(failures):
    """The most failures that fit in one WINDOW_DAYS span."""
    fs = sorted(failures, key=lambda f: _date(f["date"]))
    best = []
    for i, f in enumerate(fs):
        span = [g for g in fs[i:]
                if _date(g["date"]) - _date(f["date"]) < datetime.timedelta(days=WINDOW_DAYS)]
        if len(span) > len(best):
            best = span
    return best


def problems(entry, today, key="case"):
    """Why an entry does not (or no longer) meet the bar; empty when it does."""
    out = ["missing %s" % k for k in (key,) + REQUIRED if not entry.get(k)]
    if out:
        return out
    if not str(entry["issue"]).startswith("https://"):
        out.append("issue must be a link")
    if today - _date(entry["confirmed"]) > datetime.timedelta(days=EXPIRE_DAYS):
        out.append("expired: last confirmed %s" % entry["confirmed"])
    recent = densest(entry["failures"])
    boards = {f["board"] for f in recent}
    if len(recent) < 3:
        out.append("%d failures within %d days, need 3" % (len(recent), WINDOW_DAYS))
    elif len(boards) < 2 and not entry.get("single_board_type"):
        out.append("failed on %d board, need 2 (or single_board_type)" % len(boards))
    for f in entry["failures"]:
        if not str(f.get("run", "")).strip() or f.get("code_change", False):
            out.append("failure %s is not a base-branch run without code change" % f.get("run"))
    return out


def active(entries, today, key="case"):
    return [e for e in entries if not problems(e, today, key)]


def mark(run, entries, today):
    """Tag failed cases that match an active flake (case id, optionally
    limited to boards and stacks) with the entry id."""
    live = active(entries, today)
    for t in run["targets"]:
        for c in t.get("cases", []):
            if c["result"] != "fail":
                continue
            cid = "%s/%s" % (c["suite"], c["name"])
            for e in live:
                if e["case"] == cid and t["board"] in e.get("boards", [t["board"]]) \
                        and t["stack"] in e.get("stacks", [t["stack"]]):
                    c["flake"] = e["id"]
    return run
