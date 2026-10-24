"""Workflow rules that only show on a real run: a job must not start after
the run is cancelled, since every job leases a CIL VM."""
import glob
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def job_conditions():
    for wf in glob.glob(os.path.join(REPO, ".github", "workflows", "*.yml")):
        for n, line in enumerate(open(wf), 1):
            # Job-level keys sit at four spaces; step keys are deeper.
            m = re.match(r"^    if: (.*)$", line.rstrip("\n"))
            if m:
                yield f"{os.path.basename(wf)}:{n}", m.group(1)


def test_no_job_runs_after_a_cancel():
    bad = [f"{where}: {cond}" for where, cond in job_conditions() if "always()" in cond]
    assert not bad, bad


def test_the_jobs_that_ran_on_always_now_skip_on_cancel():
    conds = dict(job_conditions())
    skips = [c for c in conds.values() if "!cancelled()" in c]
    assert len(skips) >= 2, conds
