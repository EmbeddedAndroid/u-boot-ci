"""The on-target boot-time case: packing it (scripts/build-boottime-case.sh),
recording it with the target (ubci.run built), running it on the cold
boot only when the UKI carries it, and reading what it printed."""
import gzip
import json
import os
import shutil
import subprocess
import time

import pytest
import yaml

from fwci import schema
from fwci.lava_jobs import END_MARK
from ubci import config, jobs
from ubci import run as urun

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("automated/lib/sh-test-lib", "automated/linux/boot-time/boot-time.sh",
         "automated/linux/boot-time/cntvct-arm64")
PKG = {"url": "https://lava.example/a/pkg.tar.gz", "token": "lava-mcp-artifact-x", "path": "ubci-b"}
LINUX = {"tag": "next-20261023", "release": "7.3.0-next-20261023", "image_sha256": "5" * 64}


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def td(tmp_path):
    """A test-definitions repository with the case, and a copy of the
    script whose config pins that repository's commit."""
    src = tmp_path / "td"
    for f in FILES + ("automated/linux/boot-time/README.md",):
        p = src / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content of %s\n" % f)
    git("init", "-q", cwd=src)
    git("add", "-A", cwd=src)
    git("commit", "-q", "-m", "boot-time", cwd=src)
    commit = git("rev-parse", "HEAD", cwd=src)
    copy = tmp_path / "ci"
    (copy / "scripts").mkdir(parents=True)
    (copy / "config").mkdir()
    shutil.copy(os.path.join(REPO, "scripts", "build-boottime-case.sh"), copy / "scripts")

    def pin(pending=None, commit=commit):
        (copy / "config" / "project.yaml").write_text(yaml.safe_dump({"boottime_case": {
            "repo": "https://example.org/test-definitions.git", "commit": commit, "pending": pending}}))
    pin()
    return {"src": str(src), "commit": commit, "copy": copy, "pin": pin, "work": tmp_path}


def build(td, out, env_repo=True):
    env = dict(os.environ, UBCI_WORK=str(td["work"]))
    env.pop("UBCI_BOOTTIME_CASE_REPO", None)
    if env_repo:
        env["UBCI_BOOTTIME_CASE_REPO"] = td["src"]
    return subprocess.run([str(td["copy"] / "scripts" / "build-boottime-case.sh"), str(out)],
                          env=env, capture_output=True, text=True)


def cpio_list(path):
    data = gzip.decompress(open(path, "rb").read())
    return subprocess.run(["cpio", "-it", "--quiet", "-v"], input=data, capture_output=True, check=True).stdout


def test_packs_the_pinned_case(td, tmp_path):
    out = tmp_path / "initramfs"
    r = build(td, out)
    assert r.returncode == 0, r.stderr
    d = out / "boottime-case"
    meta = json.loads((d / "boottime-case.json").read_text())
    assert meta["commit"] == td["commit"] and meta["path"] == "/opt/test-definitions"
    # The pin's repository is recorded, not the local checkout it came from.
    assert meta["repo"] == "https://example.org/test-definitions.git"
    assert set(meta["files"]) == set(FILES)
    listing = cpio_list(d / "boottime-case.cpio.gz").decode()
    for f in FILES:
        line = next(ln for ln in listing.splitlines() if ln.endswith("opt/test-definitions/" + f))
        assert line.startswith("-rwxr-xr-x") and " root " in line
    assert "README.md" not in listing


def test_packing_is_reproducible(td, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert build(td, a).returncode == 0
    # A later checkout has later file times; the cpio must not carry them.
    time.sleep(1.1)
    assert build(td, b).returncode == 0
    assert (a / "boottime-case" / "boottime-case.cpio.gz").read_bytes() == \
        (b / "boottime-case" / "boottime-case.cpio.gz").read_bytes()


def test_same_pin_keeps_what_was_built(td, tmp_path):
    out = tmp_path / "initramfs"
    assert build(td, out).returncode == 0
    r = build(td, out)
    assert r.returncode == 0 and "already built" in r.stdout


def test_pending_pin_leaves_the_case_out(td, tmp_path):
    out = tmp_path / "initramfs"
    assert build(td, out).returncode == 0
    td["pin"](pending="not pushed yet")
    r = build(td, out, env_repo=False)
    assert r.returncode == 0 and "left out" in r.stdout
    # No stale case from an earlier pin is packed.
    assert not (out / "boottime-case").exists()


def test_commit_not_in_the_repository_fails(td, tmp_path):
    td["pin"](commit="0" * 40)
    r = build(td, tmp_path / "initramfs")
    assert r.returncode != 0
    assert not (tmp_path / "initramfs" / "boottime-case" / "boottime-case.cpio.gz").exists()


def cold_tail(job):
    names = [a["test"]["interactive"][0]["name"] for a in job["actions"]
             if "interactive" in a.get("test", {})]
    return names[names.index("poweroff") + 1:]


def test_case_runs_on_the_cold_boot_when_the_uki_carries_it():
    job = jobs.render("rb3gen2", "open", "ubci-9", PKG, LINUX, boottime_case=True)
    assert cold_tail(job) == [jobs.BOOTTIME_SUITE, "cold-poweroff"]
    step = [a for a in job["actions"] if "interactive" in a.get("test", {})
            and a["test"]["interactive"][0]["name"] == jobs.BOOTTIME_SUITE][0]["test"]["interactive"][0]
    assert step["script"][0]["name"] == jobs.BOOTTIME_CASE
    assert "cd /opt/test-definitions/automated/linux/boot-time && ./boot-time.sh" in step["script"][0]["command"]
    assert step["prompts"] == [END_MARK]


def test_no_case_step_without_the_case():
    assert cold_tail(jobs.render("rb3gen2", "open", "ubci-9", PKG, LINUX)) == ["cold-poweroff"]


@pytest.fixture
def doc(tmp_path):
    lj = tmp_path / "linux.json"
    lj.write_text(json.dumps({"tag": "next-20261023", "commit": "20a33c6b6cbe7e4805dfb6cd68816937443aa148",
                              "release": "7.3.0-next-20261023", "config": "arch/arm64/configs/defconfig",
                              "image_sha256": "5" * 64, "modules_sha256": "6" * 64}))
    p = str(tmp_path / "run.json")
    urun.main(["new", p, "--id", "ubci-1", "--commit", "ed869863c7e2aca50d57a05d843830dd843138c4",
               "--fingerprint", "ubci-1", "--linux", str(lj), "--targets", "rb3gen2:open,rb3gen2:stock"])
    return p


CASE = {"repo": "https://github.com/EmbeddedAndroid/test-definitions.git", "commit": "e" * 40,
        "path": "/opt/test-definitions", "files": {f: "a" * 64 for f in FILES}, "cpio_sha256": "c" * 64}


def test_built_records_the_case_and_render_follows_it(doc, tmp_path):
    for stack, case in (("open", CASE), ("stock", None)):
        d = tmp_path / "targets" / ("rb3gen2-" + stack)
        d.mkdir(parents=True)
        (d / "u-boot.json").write_text(json.dumps({"configs": "qcom_defconfig", "sha256": "a" * 64}))
        (d / "esp.json").write_text(json.dumps({"dtb_sha256": "b" * 64, "boottime_case": case}))
    urun.main(["built", doc, str(tmp_path / "targets")])
    r = json.load(open(doc))
    assert schema.errors(r) == []
    lx = {t["stack"]: next(c for c in t["components"] if c["name"] == "linux") for t in r["targets"]}
    assert lx["open"]["boottime_case"]["url"] == \
        "https://github.com/EmbeddedAndroid/test-definitions/commit/" + "e" * 40
    assert lx["stock"]["boottime_case"] is None
    assert urun.boottime_case(r["targets"][0]) and not urun.boottime_case(r["targets"][1])
    job = yaml.safe_load(urun.render_one(r, "rb3gen2", "open", PKG))
    assert jobs.BOOTTIME_SUITE in cold_tail(job)
    assert jobs.BOOTTIME_SUITE not in cold_tail(yaml.safe_load(urun.render_one(r, "rb3gen2", "stock", PKG)))


def line(t, lvl, msg):
    return "- " + json.dumps({"dt": "2026-11-01T00:%02d:%09.6f+00:00" % (t // 60, t % 60), "lvl": lvl, "msg": msg})


class CaseLava:
    """A finished job whose log has a cold boot and the case's output."""

    def __init__(self):
        cmd = 'if ( cd x && ./boot-time.sh ); then v=pass; else v=fail; fi; echo "@@ boot-time $v @@"; echo "%s""@@"' % \
            END_MARK[:-2]
        lines = []
        for t0, level in ((0, "3.1"), (60, "16.1")):
            lines += [line(t0, "debug", "start: %s pdu-reboot (timeout 00:01:00)" % level),
                      line(t0, "debug", "Calling: ['power']"),
                      line(t0 + 0.1, "debug", "end: %s pdu-reboot (duration 00:00:00)" % level),
                      line(t0 + 0.5, "target", "B -    1 - SBL1, Start"),
                      line(t0 + 2.5, "target", "U-Boot 2026.10-ubci-1-open-rb3gen2"),
                      line(t0 + 4.8, "target", "[    0.000000] Booting Linux on physical CPU 0x0")]
        lines += [line(90, "debug", "Waiting for '@@ boot-time pass @@', '@@ boot-time fail @@'"),
                  line(90, "target", cmd),
                  line(91, "target", "pre-kernel pass 6.120 s"),
                  line(91, "target", "INFO: kernel-to-init: no timestamped line"),
                  line(91, "target", "kernel-to-init skip"),
                  line(92, "target", "@@ boot-time pass @@"),
                  line(92, "results", {"definition": "19_boot-time", "case": "boot-time", "result": "pass"})]
        self.text = "\n".join(lines)

    def job(self, i):
        return {"id": i, "state": "Finished", "health": "Complete", "actual_device": "d1"}

    def results(self, i):
        return [{"name": "boot-time", "result": "pass", "suite": 1, "metadata": "definition: 19_boot-time\n"}]

    def log(self, i):
        return self.text

    def queue(self):
        return []


def test_collector_reads_the_case_on_the_cold_boot(doc):
    r = json.load(open(doc))
    t = r["targets"][0]
    t["lava"] = {"job_id": 5, "url": "https://lava.example/scheduler/job/5", "device": None, "health": None}
    r["targets"][1].update(state="skipped", state_detail="not in this test")
    urun.collect_once(r, CaseLava(), None)
    bt = t["boot_time"]
    assert [b["kind"] for b in bt["boots"]] == ["first", "cold"] and bt["headline"] == 1
    ot = bt["on_target"]
    assert ot["boot"] == 1 and ot["suite"] == jobs.BOOTTIME_SUITE
    assert ot["cases"] == [{"name": "kernel-to-init", "result": "skip", "note": "no timestamped line"},
                           {"name": "pre-kernel", "result": "pass", "value": 6.12, "units": "s"}]
    urun.save(doc, r)


def test_case_pin_is_configured():
    pin = config.project()["boottime_case"]
    assert len(pin["commit"]) == 40 and pin["repo"].startswith("https://")


def test_real_job_with_the_cold_boot_and_the_case():
    # LAVA 529181 (RB3 Gen 2, open stack), cut by mk-boottime-fixture.py.
    import pathlib

    from fwci import boottime, collect
    text = (pathlib.Path(__file__).resolve().parent / "data" / "boottime" / "rb3gen2-open-cold-boot.yaml").read_text()
    bt = boottime.measure(text, collect.log_entries(text), "https://lava.example/scheduler/job/529181",
                          (jobs.BOOTTIME_SUITE, jobs.BOOTTIME_CASE))
    assert [b["kind"] for b in bt["boots"]] == ["first", "warm-reset", "warm-reboot", "cold"]
    cold = bt["boots"][bt["headline"]]
    assert cold["kind"] == "cold" and cold["complete"]
    assert boottime.time_of(cold, "linux") == pytest.approx(6.246)
    assert cold["stages"]["loader"]["replayed"] and not cold["stages"]["bl31"]["replayed"]
    ot = bt["on_target"]
    assert ot["boot"] == bt["headline"] and ot["finished"]
    assert {c["name"]: c.get("value") for c in ot["cases"]} == {
        "pre-kernel": 3.982, "kernel-to-init": pytest.approx(1.10142), "kernel-to-login": 31.6}
