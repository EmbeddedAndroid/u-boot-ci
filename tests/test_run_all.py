"""scripts/run-all.sh, the one job that runs patch code: every check and
build runs whatever the others do, the job fails at the end when any
failed, and nothing of a failed build is left for LAVA."""
import json
import os
import shutil
import subprocess

import pytest

from ubci import run as urun

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUBS = os.path.join(REPO, "tests", "stubs")
CHECKS = ["carry", "buildman", "fragments", "checkpatch", "docs", "sandbox", "qemu_arm64"]
TARGETS = ["rb3gen2-stock", "rb3gen2-open", "ventuno-q-stock", "ventuno-q-open"]


@pytest.fixture
def job(tmp_path):
    src = tmp_path / "u-boot"
    src.mkdir()
    for d, f in (("linux", "linux.json"), ("initramfs", "initramfs.json")):
        (tmp_path / d).mkdir()
        (tmp_path / d / f).write_text("{}")
    doc = str(tmp_path / "run.json")
    urun.main(["new", doc, "--id", "ubci-t", "--commit", "0" * 40, "--fingerprint", "ubci-t"])

    def go(fail="", crash="", stack=None, since="", linux="linux"):
        calls = tmp_path / "calls"
        calls.write_text("")
        env = dict(os.environ, UBCI_HOST_CHECK=os.path.join(STUBS, "host-check.sh"),
                   UBCI_BUILD_TARGET=os.path.join(STUBS, "build-target.sh"),
                   UBCI_STUB_CALLS=str(calls), UBCI_STUB_FAIL=fail, UBCI_STUB_CRASH=crash)
        args = [os.path.join(REPO, "scripts", "run-all.sh"), str(src), doc, "ubci-t", since,
                str(tmp_path / linux), str(tmp_path / "initramfs"), str(tmp_path / "out")]
        if stack:
            args.append(stack)
        p = subprocess.run(args, env=env, capture_output=True, text=True)
        steps = calls.read_text().splitlines()
        return p, [" ".join(s.split()[:2]) for s in steps], steps

    go.tmp = tmp_path
    go.doc = doc
    go.src = src
    return go


def every_step(targets=TARGETS):
    return ["check " + c for c in CHECKS] + ["build " + t for t in targets] + ["check size"]


def host(tmp_path, check):
    return json.load(open(tmp_path / "out" / "host" / (check + ".json")))["result"]


def packages(tmp_path):
    return sorted(f[:-len(".qcomflash.tar.gz")] for f in os.listdir(tmp_path / "out" / "targets")
                  if f.endswith(".qcomflash.tar.gz"))


def test_everything_runs_and_passes(job):
    p, steps, _ = job()
    assert p.returncode == 0, p.stdout + p.stderr
    assert steps == every_step()
    for c in CHECKS + ["size"]:
        assert host(job.tmp, c) == "pass"
    assert packages(job.tmp) == sorted(TARGETS)
    for t in TARGETS:
        assert (job.tmp / "out" / "host" / ("build-%s.log" % t)).exists()
    # size's own output dir is folded into host/.
    assert not (job.tmp / "out" / "targets" / "host").exists()


def test_a_failing_check_does_not_stop_the_others_and_fails_the_job(job):
    p, steps, _ = job(fail="sandbox")
    assert p.returncode == 1
    assert steps == every_step()
    assert host(job.tmp, "sandbox") == "fail"
    assert host(job.tmp, "qemu_arm64") == "pass"
    assert "sandbox (fail)" in p.stdout
    assert packages(job.tmp) == sorted(TARGETS)


def test_the_first_check_failing_still_runs_everything(job):
    p, steps, _ = job(fail="carry")
    assert p.returncode == 1 and steps == every_step()


def test_the_last_check_failing_fails_the_job(job):
    p, steps, _ = job(fail="size")
    assert p.returncode == 1 and steps == every_step()
    assert "size (fail)" in p.stdout


def test_a_check_that_could_not_run_is_a_failure_and_the_rest_runs(job):
    p, steps, _ = job(crash="docs")
    assert p.returncode == 1
    assert steps == every_step()
    assert "docs (could not run: exit 3)" in p.stdout
    assert not (job.tmp / "out" / "host" / "docs.json").exists()


def test_a_result_left_from_an_earlier_run_is_not_taken(job):
    (job.tmp / "out" / "host").mkdir(parents=True)
    (job.tmp / "out" / "host" / "docs.json").write_text('{"result": "pass", "summary": "old"}')
    (job.tmp / "out" / "host" / "sandbox.json").write_text('{"result": "pass", "summary": "old"}')
    p, _, _ = job(crash="docs")
    assert p.returncode == 1
    assert not (job.tmp / "out" / "host" / "docs.json").exists()


def test_a_failed_build_leaves_no_package_and_the_other_targets_build(job):
    p, steps, _ = job(fail="rb3gen2-open")
    assert p.returncode == 1
    assert steps == every_step()
    assert packages(job.tmp) == sorted(t for t in TARGETS if t != "rb3gen2-open")
    assert not (job.tmp / "out" / "targets" / "rb3gen2-open").exists()
    assert "build rb3gen2/open (exit 1)" in p.stdout


def test_no_linux_payload_fails_every_build_but_the_checks_run(job):
    p, steps, _ = job(linux="missing")
    assert p.returncode == 1
    assert steps == ["check " + c for c in CHECKS] + ["check size"]
    assert p.stdout.count("(no Linux payload)") == len(TARGETS)
    assert packages(job.tmp) == []


def test_only_queued_targets_are_built(job):
    run = json.load(open(job.doc))
    for t in run["targets"]:
        if t["board"] == "ventuno-q":
            t["state"] = "skipped"
    json.dump(run, open(job.doc, "w"))
    p, steps, _ = job()
    assert p.returncode == 0
    assert steps == every_step(["rb3gen2-stock", "rb3gen2-open"])


def test_checkpatch_gets_the_base_commit_and_builds_the_fingerprint(job):
    _, _, raw = job(since="abc123")
    cp = next(s for s in raw if s.startswith("check checkpatch "))
    assert cp.split()[-1] == "abc123"
    assert all(s.split()[-1] == "ubci-t" for s in raw if s.startswith("build "))


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_a_stack_that_does_not_apply_runs_only_carry_and_size(job):
    git(job.src, "init", "-q")
    (job.src / "README").write_text("base\n")
    git(job.src, "add", "README")
    git(job.src, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "base")
    stack = job.tmp / "stack"
    stack.mkdir()
    (stack / "s01.mbx").write_text(
        "From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n"
        "From: A <a@example.com>\nSubject: [PATCH 1/1] touch a missing file\n\n---\n"
        "--- a/missing\n+++ b/missing\n@@ -1 +1 @@\n-x\n+y\n")
    json.dump([{"mbx": "s01.mbx", "message_id": "m@x", "title": "t", "version": 1, "patches": 1,
                "prerequisites": {"patch_ids": [], "message_ids": []}}], open(stack / "stack.json", "w"))
    p, steps, _ = job(stack=str(stack))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "stack: does not apply" in p.stdout
    assert steps == ["check carry", "check size"]
    assert json.load(open(stack / "stack.json"))[0]["applied"] is False


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_a_stack_that_applies_runs_everything(job):
    git(job.src, "init", "-q")
    (job.src / "README").write_text("base\n")
    git(job.src, "add", "README")
    git(job.src, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "base")
    stack = job.tmp / "stack"
    stack.mkdir()
    json.dump([], open(stack / "stack.json", "w"))
    p, steps, _ = job(stack=str(stack))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "stack: applies" in p.stdout
    assert steps == every_step()


def test_bad_usage_exits_2():
    p = subprocess.run([os.path.join(REPO, "scripts", "run-all.sh"), "only", "three", "args"],
                       capture_output=True, text=True)
    assert p.returncode == 2


def test_host_check_knows_every_check_the_job_runs():
    text = open(os.path.join(REPO, "scripts", "host-check.sh")).read()
    for c in CHECKS + ["size"]:
        assert "\n%s)" % c in text or "\n%s|" % c in text or "|%s)" % c in text, c
