"""Dashboard data: index.json built from the run documents of a site
directory (runs/<id>.json). The static page polls index.json and loads
run documents on demand."""
import json
import os

from . import schema

HISTORY = 30
RESULT_CHAR = {"pass": "p", "fail": "f", "skip": "s", "unknown": "u"}


def load_runs(runs_dir):
    runs = []
    for name in sorted(os.listdir(runs_dir)):
        if name.endswith(".json"):
            runs.append(schema.check(json.load(open(os.path.join(runs_dir, name)))))
    return sorted(runs, key=lambda r: r["run"]["created"], reverse=True)


def counts(t):
    c = {"pass": 0, "fail": 0, "skip": 0, "unknown": 0}
    for case in t.get("cases", []):
        c[case["result"]] += 1
    c["flaky"] = sum(1 for case in t.get("cases", []) if case.get("flake"))
    return c


def distance(t):
    d = [c for c in t.get("components", []) if c.get("upstream")]
    return {c["name"]: c["upstream"]["distance"] for c in d}


def cell(run, t):
    boot = t.get("linux_boot", {})
    return {
        "run": run["run"]["id"],
        "board": t["board"], "stack": t["stack"],
        "state": t["state"], "state_detail": t.get("state_detail", ""),
        "queue_position": t.get("queue_position"),
        "fingerprint": t.get("fingerprint", ""),
        "gate": t.get("fingerprint_gate", "not-run"),
        "boot": boot.get("verdict", "not-run"),
        "boot_stage": boot.get("stage", "not-reached"),
        "versus": boot.get("versus_baseline", "unknown"),
        "boot_url": boot.get("url", ""),
        "counts": counts(t),
        "new_fail": len(t.get("diff", {}).get("new_fail", [])),
        "distance": distance(t),
        "job_url": (t.get("lava") or {}).get("url", ""),
    }


def nightly(nightlies):
    """The view of one base branch: its latest nightly, the history and
    the per-case history of its recent nightlies."""
    latest = nightlies[0] if nightlies else None
    history, case_history = {}, {}
    for r in reversed(nightlies[:HISTORY]):
        for t in r["targets"]:
            k = "%s/%s" % (t["board"], t["stack"])
            history.setdefault(k, []).append(cell(r, t))
            ch = case_history.setdefault(k, {"runs": [], "cases": {}})
            n = len(ch["runs"])
            ch["runs"].append(r["run"]["id"])
            # One character per run, even when LAVA reports a case twice.
            now = {"%s/%s" % (c["suite"], c["name"]): RESULT_CHAR[c["result"]] for c in t.get("cases", [])}
            for cid in set(ch["cases"]) | set(now):
                ch["cases"][cid] = ch["cases"].get(cid, "-" * n) + now.get(cid, "-")
    return {
        "latest_nightly": latest["run"]["id"] if latest else None,
        "matrix": [cell(latest, t) for t in latest["targets"]] if latest else [],
        "host_checks": latest["host_checks"] if latest else [],
        "linux": latest.get("linux") if latest else None,
        "history": history,
        "case_history": case_history,
    }


def diffed_cell(r, t):
    c = cell(r, t)
    c["diff"] = t.get("diff", {})
    return c


def build(runs, default_branch="main"):
    by_branch = {}
    for r in runs:
        if r["run"]["kind"] == "nightly":
            by_branch.setdefault(r["run"]["base"].get("branch", default_branch), []).append(r)
    branches = {b: nightly(rs) for b, rs in by_branch.items()}
    candidates = {}
    for r in runs:
        if r["run"]["kind"] == "pin-candidate":
            for t in r["targets"]:
                candidates.setdefault(t["board"], {"run": r["run"]["id"], "title": r["run"].get("title", ""),
                                                   "ci_url": r["run"].get("ci_url"), "state": r["state"],
                                                   "cells": []})
                if candidates[t["board"]]["run"] == r["run"]["id"]:
                    c = cell(r, t)
                    c["firmware"] = next((x.get("release", "") for x in t.get("components", [])
                                          if x["role"] == "stock"), "")
                    candidates[t["board"]]["cells"].append(c)
    adhoc = [{"run": r["run"]["id"], "title": r["run"].get("title", ""), "created": r["run"]["created"],
              "ci_url": r["run"].get("ci_url"), "state": r["state"], "base": r["run"]["base"],
              "baseline": r["run"].get("baseline"), "stack": r["run"].get("stack", []),
              "cells": [diffed_cell(r, t) for t in r["targets"]]}
             for r in runs if r["run"]["kind"] == "adhoc"][:HISTORY]
    default = default_branch if default_branch in branches else next(iter(sorted(branches)), None)
    idx = {
        "updated": schema.now(),
        "default_branch": default,
        "branches": branches,
        "pin_candidates": candidates,
        "adhoc": adhoc,
        "runs": [{"id": r["run"]["id"], "kind": r["run"]["kind"],
                  "title": r["run"].get("title", ""), "created": r["run"]["created"],
                  "state": r["state"], "base": r["run"]["base"]} for r in runs[:100]],
    }
    # The default branch's view at the top level too.
    idx.update(branches.get(default) or nightly([]))
    return idx


def write(site_dir):
    idx = build(load_runs(os.path.join(site_dir, "runs")))
    tmp = os.path.join(site_dir, "index.json.tmp")
    with open(tmp, "w") as f:
        json.dump(idx, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(site_dir, "index.json"))
    return idx
