"""Workflow rules that only show on a real run: which CIL pool each job
leases from and how big, which jobs see secrets, the order of the steps that keep a
series from touching what other runs use, and that a job never starts
after the run is cancelled."""
import glob
import os
import re

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(REPO, ".github", "workflows")

# The largest lease of each CIL pool, GET /api/v1/pools (2026-10-24):
# cpu, RAM GB, disk GB. A xeon host gives 38 CPUs and 56 GB, so the xeon
# limit fits one host; the arm64 pool is one host (the VENTUNO Q,
# max_concurrent 2). The bridge sends a job with the `arm64` label there.
POOLS = {"xeon": (32, 32, 750), "arm64": (4, 8, 200)}
# cil-gha-bridge generic profile: a lease lives 6 h.
LEASE_TTL_MIN = 360

# The pool of every job, per workflow; a job not listed calls run.yml.
# Light jobs go to arm64 to keep load and power draw off the xeons.
LEASED = {
    "run.yml": {"prepare": "arm64", "ci": "xeon", "submit": "arm64", "finalize": "arm64"},
    "adhoc.yml": {"request": "arm64"},
    "adhoc-issue.yml": {"request": "arm64"},
    "nightly.yml": {},
    "tests.yml": {"tests": "xeon"},
    "pin-watch.yml": {"stock": "xeon"},
    "pin-candidate.yml": {"build": "xeon", "submit": "xeon"},
}
# What runs U-Boot or patch code.
PATCH_CODE = re.compile(r"scripts/(run-all|host-check|build-target|build-uboot|build-open-stack)\.sh")


def load(name):
    return yaml.safe_load(open(os.path.join(WORKFLOWS, name)))


def jobs(name):
    return load(name)["jobs"]


def run_text(job):
    return "\n".join(s.get("run", "") for s in job.get("steps", []))


def lease(job):
    """(pool, (cpu, ram GB, disk GB)) of a CIL job, as the bridge reads
    its labels; None for a job that is not on a CIL runner."""
    labels = job.get("runs-on")
    if not isinstance(labels, list) or "self-hosted" not in labels:
        return None
    assert "cil" in labels, labels
    m = [re.fullmatch(r"(\d+)c-(\d+)g(?:-(\d+)g)?", lb) for lb in labels]
    m = [x for x in m if x]
    assert len(m) == 1, labels
    cpu, ram, disk = m[0].groups()
    return ("arm64" if "arm64" in labels else "xeon"), (int(cpu), int(ram), int(disk or 30))


def job_conditions():
    for wf in glob.glob(os.path.join(WORKFLOWS, "*.yml")):
        for n, line in enumerate(open(wf), 1):
            # Job-level keys sit at four spaces; step keys are deeper.
            m = re.match(r"^    if: (.*)$", line.rstrip("\n"))
            if m:
                yield f"{os.path.basename(wf)}:{n}", m.group(1)


# The only job that may start after a cancel: it closes the run document.
AFTER_CANCEL = {"run.yml": {"finalize"}}


def test_no_job_runs_after_a_cancel():
    bad = [f"{where}: {cond}" for where, cond in job_conditions() if "always()" in cond]
    assert not bad, bad
    for wf in LEASED:
        late = {n for n, j in jobs(wf).items() if re.search(r"\bcancelled\(\)", str(j.get("if", "")))
                and "!cancelled()" not in str(j.get("if", "")).replace(" ", "")}
        assert late == AFTER_CANCEL.get(wf, set()), (wf, late)


def test_finalize_closes_runs_that_ended_before_submit():
    js = jobs("run.yml")
    fin = js["finalize"]
    assert set(fin["needs"]) == {"prepare", "ci", "submit"}
    assert fin["if"] == "${{ cancelled() || (failure() && needs.submit.result != 'success') }}"
    assert fin["permissions"] == {"contents": "write"} and "environment" not in fin
    assert fin["env"]["UBCI_IMAGE"] == "u-boot-ci-control:1"
    assert "contains(needs.*.result, 'cancelled')" in fin["env"]["CONCLUSION"]
    text = run_text(fin)
    assert not PATCH_CODE.search(text)
    # The published document (submit may have moved it on), not prepare's artifact.
    assert 'doc="site/runs/$FINGERPRINT.json"' in text
    assert re.search(r'ubci\.run close "work/\$FINGERPRINT\.json" "\$CONCLUSION"', text)
    assert text.index("ubci.run close") < text.index("scripts/publish-site.sh")


def test_submit_runs_after_a_failed_check_but_not_after_a_cancel():
    sub = jobs("run.yml")["submit"]
    assert "!cancelled()" in sub["if"]
    assert "needs.prepare.result == 'success'" in sub["if"]
    assert set(sub["needs"]) == {"prepare", "ci"}


def test_every_workflow_is_listed():
    assert set(os.listdir(WORKFLOWS)) == set(LEASED)


@pytest.mark.parametrize("wf", sorted(LEASED))
def test_every_job_leases_from_its_pool(wf):
    pools = {n: lease(j)[0] for n, j in jobs(wf).items() if lease(j)}
    assert pools == LEASED[wf]
    for n, j in jobs(wf).items():
        assert n in pools or "uses" in j, (wf, n)


def test_a_run_is_one_xeon_lease_and_two_arm64_leases():
    js = jobs("run.yml")
    assert set(js) == {"prepare", "ci", "submit", "finalize"}
    # finalize only leases when the run ended early.
    pools = sorted(lease(j)[0] for n, j in js.items() if n != "finalize")
    assert pools == ["arm64", "arm64", "xeon"]


@pytest.mark.parametrize("wf", sorted(LEASED))
def test_every_lease_fits_its_pool(wf):
    for n, j in jobs(wf).items():
        if lease(j):
            pool, size = lease(j)
            assert all(a <= b for a, b in zip(size, POOLS[pool])), (wf, n, pool, size)


@pytest.mark.parametrize("wf", sorted(LEASED))
def test_arm64_jobs_use_only_the_control_image_and_no_gh(wf):
    # The CI image (toolchains, QEMU, Sphinx) is for the xeon job; the
    # runner image has curl, jq and docker but no gh.
    for n, j in jobs(wf).items():
        if lease(j) and lease(j)[0] == "arm64":
            text = run_text(j)
            for line in text.splitlines():
                if "docker build" in line:
                    assert "--target control" in line, (wf, n, line)
            assert not re.search(r"(^|[\s;|&(])gh ", text, re.M), (wf, n)


def test_the_patch_code_job_holds_no_secret():
    ci = jobs("run.yml")["ci"]
    assert "environment" not in ci
    assert ci["permissions"] == {"contents": "read"}
    text = yaml.safe_dump(ci)
    assert "secrets." not in text and "vars." not in text and "github.token" not in text
    checkout = [s for s in ci["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout and all(s.get("with", {}).get("persist-credentials") is False for s in checkout)


def test_patch_code_runs_only_in_the_ci_job():
    js = jobs("run.yml")
    assert {n for n, j in js.items() if PATCH_CODE.search(run_text(j))} == {"ci"}
    assert "scripts/run-all.sh" in run_text(js["ci"])


def test_only_the_control_jobs_write_and_only_submit_has_the_environment():
    js = jobs("run.yml")
    assert {n for n, j in js.items() if (j.get("permissions") or {}).get("contents") == "write"} == \
        {"prepare", "submit", "finalize"}
    assert {n for n, j in js.items() if "environment" in j} == {"submit"}
    sub = js["submit"]
    assert sub["environment"] == "lava-hw"
    assert sub["env"]["LAVA_TOKEN"] == "${{ secrets.LAVA_TOKEN }}"


def step_index(steps, pred):
    return [i for i, s in enumerate(steps) if pred(s)]


def test_the_linux_payload_is_cached_and_uploaded_before_patch_code_runs():
    steps = jobs("run.yml")["ci"]["steps"]
    patch = step_index(steps, lambda s: PATCH_CODE.search(s.get("run", "")))
    saves = step_index(steps, lambda s: s.get("uses", "").startswith("actions/cache/save@"))
    linux = step_index(steps, lambda s: s.get("uses", "").startswith("actions/upload-artifact@") and
                       s["with"]["name"].endswith("-linux"))
    assert patch and len(saves) == 2 and len(linux) == 1
    assert max(saves + linux) < min(patch)
    # actions/cache saves in its post step, after patch code has run.
    assert not step_index(steps, lambda s: re.match(r"actions/cache@", s.get("uses", "")))


def test_a_failed_linux_payload_does_not_stop_the_checks():
    steps = jobs("run.yml")["ci"]["steps"]
    build = [s for s in steps if "scripts/build-linux.sh" in s.get("run", "")]
    assert len(build) == 1 and build[0]["continue-on-error"] is True


def test_logs_and_packages_upload_when_a_check_failed():
    steps = jobs("run.yml")["ci"]["steps"]
    last = max(step_index(steps, lambda s: "scripts/run-all.sh" in s.get("run", "")))
    ups = [s for s in steps[last + 1:] if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert {u["with"]["name"].split("-", 1)[1] for u in ups} == {"host", "packages"}
    for u in ups:
        assert "!cancelled()" in u["if"] and "always()" not in u["if"].replace("!cancelled()", "")


def test_submit_reads_what_prepare_and_ci_upload():
    js = jobs("run.yml")
    uploaded = {s["with"]["name"].replace("${{ inputs.base }}", "$BASE")
                for n in ("prepare", "ci") for s in js[n]["steps"]
                if s.get("uses", "").startswith("actions/upload-artifact@")}
    assert uploaded == {"$BASE-run", "$BASE-linux", "$BASE-host", "$BASE-packages"}
    sub = run_text(js["submit"])
    for name in uploaded:
        assert "work/artifacts/%s/" % name in sub, name


def test_submit_records_every_check_run_all_runs():
    loop = re.search(r"for c in ([a-z_0-9 ]+); do", run_text(jobs("run.yml")["submit"])).group(1).split()
    text = open(os.path.join(REPO, "scripts", "run-all.sh")).read()
    ran = set(re.findall(r"^check (\w+) ", text, re.M))
    ran |= set(re.search(r"for c in ([a-z_0-9 ]+); do", text).group(1).split())
    assert set(loop) == ran == {"carry", "buildman", "fragments", "checkpatch", "docs", "sandbox",
                                "qemu_arm64", "size"}


def test_the_ci_job_ends_before_its_lease():
    assert jobs("run.yml")["ci"]["timeout-minutes"] < LEASE_TTL_MIN


@pytest.mark.parametrize("wf,job", [("nightly.yml", "main"), ("nightly.yml", "master"),
                                    ("adhoc.yml", "run"), ("adhoc-issue.yml", "run")])
def test_callers_hand_run_the_inputs_and_secrets(wf, job):
    j = jobs(wf)[job]
    assert j["uses"] == "./.github/workflows/run.yml"
    assert {"kind", "base"} <= set(j["with"])
    assert j["secrets"] == "inherit"
