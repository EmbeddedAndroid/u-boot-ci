"""Compare a run with its baseline (for a series: the same-day nightly of
the base branch; for a nightly: the previous nightly), per board and
stack: new failures, new passes, failures in both, and the boot verdict."""
from . import boot_verdict


def key(t):
    return (t["board"], t["stack"])


def case_id(c):
    return "%s/%s" % (c["suite"], c["name"])


def results(t):
    return {case_id(c): c["result"] for c in t.get("cases", [])}


def compare(run, baseline):
    """Adds diff and linux_boot.versus_baseline to every target of run
    (in place) and returns run. Targets without a baseline target get
    versus_baseline 'unknown' and no diff."""
    base = {key(t): t for t in (baseline or {}).get("targets", [])}
    for t in run["targets"]:
        b = base.get(key(t))
        boot = t.setdefault("linux_boot", {"verdict": "not-run", "stage": "not-reached"})
        # Results of a run whose console did not show the build are not counted.
        if not b or t.get("fingerprint_gate") != "pass" or b.get("fingerprint_gate") != "pass":
            boot["versus_baseline"] = "unknown"
            t.pop("diff", None)
            continue
        boot["versus_baseline"] = boot_verdict.versus(boot["verdict"], b.get("linux_boot", {}).get("verdict"))
        now, then = results(t), results(b)
        t["diff"] = {
            "new_fail": sorted(c for c, r in now.items() if r == "fail" and then.get(c) != "fail"),
            "new_pass": sorted(c for c, r in now.items() if r == "pass" and then.get(c) == "fail"),
            "still_fail": sorted(c for c, r in now.items() if r == "fail" and then.get(c) == "fail"),
        }
    if baseline:
        run["run"]["baseline"] = baseline["run"]["id"]
    return run
