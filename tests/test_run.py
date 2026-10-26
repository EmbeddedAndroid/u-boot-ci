import json

import pytest

from fwci import schema
from fwci.lava_mcp import Rejected
from ubci import config
from ubci import run as urun

LINUX = {"tag": "next-20261023", "commit": "20a33c6b6cbe7e4805dfb6cd68816937443aa148",
         "release": "7.3.0-next-20261023", "config": "arch/arm64/configs/defconfig",
         "image_sha256": "5" * 64, "modules_sha256": "e" * 64}


@pytest.fixture
def doc(tmp_path):
    lj = tmp_path / "linux.json"
    lj.write_text(json.dumps(LINUX))
    p = str(tmp_path / "run.json")
    urun.main(["new", p, "--id", "ubci-1", "--commit", "ed869863c7e2aca50d57a05d843830dd843138c4",
               "--fingerprint", "ubci-1", "--linux", str(lj)])
    return p


def test_new_run_has_every_board_and_stack_with_distance(doc):
    r = json.load(open(doc))
    assert schema.errors(r) == []
    assert [(t["board"], t["stack"]) for t in r["targets"]] == [
        (b, s) for b in ("rb3gen2", "ventuno-q", "uno-q", "qcs615-ride", "lemans-evk", "shikra-iqs-evk")
        for s in ("stock", "open", "spl")]
    open_rb3 = target_of(r, "rb3gen2", "open")
    tfa = [c for c in open_rb3["components"] if c["name"] == "tf-a"][0]
    assert tfa["role"] == "pinned" and tfa["upstream"]["distance"] == len(tfa["upstream"]["carried"])
    optee = [c for c in open_rb3["components"] if c["name"] == "optee"][0]
    assert optee["upstream"]["distance"] == 0
    assert open_rb3["linux_boot"]["gaps"]
    for vq in (target_of(r, "ventuno-q", "stock"), target_of(r, "ventuno-q", "open")):
        assert vq["linux_boot"]["gaps"][0].startswith("upstream U-Boot does not support this board")
    assert r["targets"][0]["components"][1]["role"] == "stock"


def test_host_check_and_skip(doc):
    urun.main(["host", doc, "docs", "fail", "--summary", "3 warnings"])
    urun.main(["host", doc, "docs", "pass"])
    urun.main(["skip", doc, "LAVA_TOKEN is not set"])
    r = json.load(open(doc))
    assert r["host_checks"] == [{"name": "docs", "result": "pass"}]
    assert {t["state"] for t in r["targets"]} == {"skipped"}
    assert r["targets"][0]["state_detail"] == "LAVA_TOKEN is not set"
    assert r["state"] == "done"


def test_submit_needs_no_lab_restore_image(doc, tmp_path, monkeypatch):
    # Regression: a board without a STOCK_RESTORE_URL_* was skipped
    # ("no lab restore image configured") although its package was built.
    for k in list(__import__("os").environ):
        if k.startswith("STOCK_RESTORE_"):
            monkeypatch.delenv(k)
    make_pkg(tmp_path, "rb3gen2-stock")
    lava = SubmitLava()
    monkeypatch.setattr(urun, "Lava", lambda: lava)
    urun.main(["submit", doc, str(tmp_path)])
    r = json.load(open(doc))
    t = r["targets"][0]
    assert (t["board"], t["stack"], t["state"]) == ("rb3gen2", "stock", "queued") and t["lava"]["job_id"] == 7
    assert len(lava.submitted) == 1 and "restore" not in t
    assert "no lab restore image configured" not in json.dumps(r)


class Lab:
    """The LAVA calls submit makes besides upload and submit."""
    queued = []
    jobs_running = []
    devs = [{"hostname": "rb3g2-01", "state": "Idle", "health": "Good"},
            {"hostname": "ventunoq-01", "state": "Idle", "health": "Good"}]

    def queue(self):
        return self.queued

    def running(self, metadata):
        return self.jobs_running

    def devices(self, device_type):
        return self.devs


def make_pkg(directory, name, deferred=()):
    import io
    import tarfile
    top = "ubci-" + name
    with tarfile.open(directory / (name + ".qcomflash.tar.gz"), "w:gz") as t:
        blob = json.dumps({"deferred": list(deferred), "files": {}}).encode()
        info = tarfile.TarInfo(top + "/SOURCES.json")
        info.size = len(blob)
        t.addfile(info, io.BytesIO(blob))


class SubmitLava(Lab):
    def __init__(self):
        self.submitted = []

    def upload(self, path):
        return "https://lava.example/a/p.tar.gz", "lava-mcp-artifact-x"

    def submit(self, definition):
        self.submitted.append(definition)
        return 7


class FakeLava(Lab):
    def __init__(self, log):
        self._log = log
        self.submitted = []

    def submit(self, definition):
        self.submitted.append(definition)
        return 900 + len(self.submitted)

    def job(self, i):
        return {"id": i, "state": "Finished", "health": "Complete", "actual_device": "d1"}

    def results(self, i):
        return [{"name": "u_boot_20", "result": "pass", "suite": 1, "start_log_line": 2,
                 "metadata": "definition: 0_firmware-fingerprint\n"},
                {"name": "u_boot_20", "result": "pass", "suite": 1, "start_log_line": 3,
                 "metadata": "definition: 2_firmware-fingerprint-reset\n"}]

    def log(self, i):
        return self._log

    def queue(self):
        return []


def test_collect_once_fills_targets(doc):
    r = json.load(open(doc))
    for i, t in enumerate(r["targets"]):
        t["lava"] = {"job_id": 100 + i, "url": "https://lava.example/scheduler/job/%d" % (100 + i),
                     "device": None, "health": None}
    log = "\n".join("- " + json.dumps({"lvl": "target", "msg": m}) for m in (
        "SBL1, End", "U-Boot 2026.10-ubci-1", "resetting ...", "Booting: scsi 0",
        "EFI stub: Booting Linux Kernel...", "Booting Linux on physical CPU 0x0",
        "Kernel panic - not syncing: no init", "end"))
    urun.collect_once(r, FakeLava(log), None)
    urun.save(doc, r)
    r = json.load(open(doc))
    t = r["targets"][1]
    assert t["state"] == "done" and t["fingerprint_gate"] == "pass" and "restore" not in t
    assert t["linux_boot"]["stage"] == "early-panic" and t["linux_boot"]["versus_baseline"] == "unknown"
    assert t["linux_boot"]["url"].endswith("#L6") and t["linux_boot"]["gaps"]
    assert r["state"] == "done"


@pytest.mark.parametrize("health", ["Incomplete", "Canceled"])
def test_job_that_stopped_early_gets_no_recovery_job(doc, monkeypatch, health):
    # The next job flashes its whole package: a hung or Incomplete job
    # simply ends, nothing is submitted after it.
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
    monkeypatch.setenv("STOCK_RESTORE_TOKEN", "LAB_TOKEN")
    r = json.load(open(doc))
    t = r["targets"][0]
    t["lava"] = {"job_id": 100, "url": "https://lava.example/scheduler/job/100", "device": None, "health": None}
    lava = FakeLava("- " + json.dumps({"lvl": "target", "msg": "hang"}))
    lava.job = lambda i: {"id": i, "state": "Finished", "health": health, "actual_device": "d1"}
    lava.results = lambda i: [{"name": "u_boot_20", "result": "pass", "suite": 1,
                               "metadata": "definition: 0_firmware-fingerprint\n"}]
    for _ in range(2):
        urun.collect_once(r, lava, None)
    assert not lava.submitted
    assert t["state"] == "done" and t["state_detail"] == "LAVA job " + health.lower()
    assert "restore" not in t and "recovery" not in t
    for o in r["targets"][1:]:
        o["state"] = "skipped"
        o["state_detail"] = "not in this test"
    urun.save(doc, r)
    with pytest.raises(SystemExit) as e:
        urun.main(["finished", doc])
    assert e.value.code == 0


def test_pin_candidate_run(tmp_path, capsys):
    lj = tmp_path / "linux.json"
    lj.write_text(json.dumps(LINUX))
    p = str(tmp_path / "cand.json")
    urun.main(["new", p, "--id", "ubci-2", "--kind", "pin-candidate", "--commit", "ed869863c7e2",
               "--fingerprint", "ubci-2", "--linux", str(lj), "--targets", "rb3gen2:stock,rb3gen2:stock-candidate",
               "--stock-release", "stock=QCM6490 boot binaries 00142",
               "--stock-release", "stock-candidate=QCM6490 boot binaries 00150"])
    r = json.load(open(p))
    assert [(t["board"], t["stack"]) for t in r["targets"]] == [("rb3gen2", "stock"), ("rb3gen2", "stock-candidate")]
    assert [t["components"][1]["release"] for t in r["targets"]] == [
        "QCM6490 boot binaries 00142", "QCM6490 boot binaries 00150"]
    urun.main(["summary", p])
    out = capsys.readouterr().out
    assert "| rb3gen2 | downstream-candidate | QCM6490 boot binaries 00150 |" in out


def test_candidate_job_is_the_stock_job():
    from ubci import jobs
    pkg = {"url": "u", "token": "t", "path": "p"}
    linux = {"tag": "next-20261023", "image_sha256": "0" * 64}
    a = jobs.render("rb3gen2", "stock", "f", pkg, linux)
    b = jobs.render("rb3gen2", "stock-candidate", "f", pkg, linux)
    assert a["actions"] == b["actions"]


def test_package_dir_reads_the_tarball(tmp_path):
    import tarfile
    d = tmp_path / "ubci-rb3gen2-stock"
    d.mkdir()
    (d / "x").write_text("1")
    with tarfile.open(tmp_path / "p.tar.gz", "w:gz") as t:
        t.add(d, arcname=d.name)
    assert urun.package_dir(str(tmp_path / "p.tar.gz")) == "ubci-rb3gen2-stock"


def test_a_failed_upload_keeps_the_jobs_already_submitted(doc, tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    for name in ("rb3gen2-stock", "rb3gen2-open"):
        make_pkg(pk, name)

    class Lava(Lab):
        n = 0

        def upload(self, path):
            Lava.n += 1
            if Lava.n == 2:
                raise OSError("network")
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            return 555

    monkeypatch.setattr(urun, "Lava", Lava)
    project = urun.config.project()
    project["lava"]["max_in_flight_per_device_type"] = 4
    monkeypatch.setattr(urun.config, "project", lambda: project)
    with pytest.raises(OSError):
        urun.main(["submit", doc, str(pk)])
    r = json.load(open(doc))
    assert r["targets"][0]["lava"]["job_id"] == 555
    assert "lava" not in r["targets"][1] and r["targets"][1]["state"] == "queued"
    assert schema.errors(r) == []
    # the next pass submits the target whose upload failed
    urun.main(["submit", doc, str(pk)])
    r = json.load(open(doc))
    assert r["targets"][1]["lava"]["job_id"] == 555


def test_cap_holds_a_board_until_its_job_is_done(doc, tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    for name in ("rb3gen2-stock", "rb3gen2-open"):
        make_pkg(pk, name)

    class Lava(Lab):
        def upload(self, path):
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            return 700

    monkeypatch.setattr(urun, "Lava", Lava)
    urun.main(["submit", doc, str(pk)])
    r = json.load(open(doc))
    assert r["targets"][0]["lava"]["job_id"] == 700 and "lava" not in r["targets"][1]
    r["targets"][0]["state"] = "done"
    urun.save(doc, r)
    urun.main(["submit", doc, str(pk)])
    assert json.load(open(doc))["targets"][1]["lava"]["job_id"] == 700


def test_a_failed_submit_is_never_retried(doc, tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    make_pkg(pk, "rb3gen2-stock")
    calls = []

    class Lava(Lab):
        def upload(self, path):
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            calls.append(1)
            raise TimeoutError("read timed out")

    monkeypatch.setattr(urun, "Lava", Lava)
    with pytest.raises(TimeoutError):
        urun.main(["submit", doc, str(pk)])
    urun.main(["submit", doc, str(pk)])
    t = json.load(open(doc))["targets"][0]
    assert len(calls) == 1 and t["state"] == "error" and t["state_detail"].startswith("submit outcome unknown")


def test_a_job_that_does_not_render_is_an_error_not_a_lost_submit(doc, tmp_path, monkeypatch):
    """A shell check longer than the board shell keeps (LAVA 512816: the
    dmesg-errors line) fails at render time: nothing reaches LAVA, the
    target says why, and the pass goes on."""
    from fwci import lava_jobs
    pk = tmp_path / "pk"
    pk.mkdir()
    make_pkg(pk, "rb3gen2-stock")
    monkeypatch.setattr(lava_jobs, "SHELL_LINE_MAX", 100)
    calls = []

    class Lava(Lab):
        def upload(self, path):
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            calls.append(1)
            return 700

    monkeypatch.setattr(urun, "Lava", Lava)
    urun.main(["submit", doc, str(pk)])
    t = json.load(open(doc))["targets"][0]
    assert calls == [] and t["state"] == "error" and "lava" not in t
    assert t["state_detail"].startswith("job does not render: shell check linux-next-tag:")


def test_finished_ignores_a_legacy_recovery_job(doc):
    # A document from before 2026-10-25 that was waiting on a recovery
    # job: nothing updates that field any more, so it must not hold the
    # submit loop open.
    r = json.load(open(doc))
    for t in r["targets"]:
        t["state"] = "done"
    r["targets"][0]["restore"] = "recovery-job"
    r["targets"][0]["recovery"] = {"job_id": 901, "url": "https://lava.example/scheduler/job/901", "health": None}
    urun.save(doc, r)
    with pytest.raises(SystemExit) as e:
        urun.main(["finished", doc])
    assert e.value.code == 0
    r["targets"][1]["state"] = "testing"
    r["state"] = "testing"
    urun.save(doc, r)
    with pytest.raises(SystemExit) as e:
        urun.main(["finished", doc])
    assert e.value.code == 1


def test_choose_device_skips_production_boards_and_prefers_idle(monkeypatch):
    class L(Lab):
        devs = [{"hostname": "rb3g2-matthart-production-01", "state": "Idle", "health": "Good"},
                {"hostname": "rb3g2-01", "state": "Running", "health": "Good"},
                {"hostname": "rb3g2-02", "state": "Idle", "health": "Bad"},
                {"hostname": "rb3g2-03", "state": "Idle", "health": "Good"}]
    assert urun.choose_device(L(), "qcs6490-rb3gen2") == "rb3g2-03"
    L.devs = L.devs[:3]
    assert urun.choose_device(L(), "qcs6490-rb3gen2") == "rb3g2-01"
    L.devs = L.devs[:1]
    assert urun.choose_device(L(), "qcs6490-rb3gen2") is None


def test_lab_wide_cap_counts_other_runs(doc, tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    make_pkg(pk, "rb3gen2-stock")

    class L(Lab):
        queued = [{"id": 1, "requested_device_type": "qcs6490-rb3gen2", "description": "u-boot-ci rb3gen2 stock x"}]

        def upload(self, path):
            raise AssertionError("must wait for the other run's job")

    monkeypatch.setattr(urun, "Lava", L)
    urun.main(["submit", doc, str(pk)])
    assert json.load(open(doc))["targets"][0]["state"] == "queued"


def test_submitted_job_is_pinned_to_the_chosen_device(doc, tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    make_pkg(pk, "rb3gen2-stock")
    sent = []

    class L(Lab):
        def upload(self, path):
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            sent.append(definition)
            return 9

    monkeypatch.setattr(urun, "Lava", L)
    urun.main(["submit", doc, str(pk)])
    assert "device: rb3g2-01" in sent[0]


def test_deferred_bl2_comes_from_its_secret(doc, tmp_path, monkeypatch):
    import base64
    import gzip
    import hashlib
    import tarfile
    from ubci import config, package
    pk = tmp_path / "pk"
    pk.mkdir()
    make_pkg(pk, "rb3gen2-open", deferred=["tz.mbn"])
    data = b"signed bl2"
    pins = config.pins()
    pins["rb3gen2"]["bl2"]["sha256"] = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(config, "pins", lambda: pins)

    class L(Lab):
        def upload(self, path):
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            return 11

    monkeypatch.setattr(urun, "Lava", L)
    # no secret: the cell is skipped, nothing is sent
    urun.main(["submit", doc, str(pk)])
    t = json.load(open(doc))["targets"][1]
    assert t["state"] == "skipped" and "PIN_BL2_RB3GEN2" in t["state_detail"]
    # wrong file: refused
    with pytest.raises(SystemExit, match="sha256"):
        package.insert_bl2(str(pk / "rb3gen2-open.qcomflash.tar.gz"), "rb3gen2",
                           {"PIN_BL2_RB3GEN2": base64.b64encode(gzip.compress(b"other")).decode()})
    package.insert_bl2(str(pk / "rb3gen2-open.qcomflash.tar.gz"), "rb3gen2",
                       {"PIN_BL2_RB3GEN2": base64.b64encode(gzip.compress(data)).decode()})
    with tarfile.open(pk / "rb3gen2-open.qcomflash.tar.gz") as t:
        assert t.extractfile("ubci-rb3gen2-open/tz.mbn").read() == data
    assert package.sources(str(pk / "rb3gen2-open.qcomflash.tar.gz"))["deferred"] == []


def stack_file(tmp_path, applied):
    s = [{"message_id": "clk@example.com", "title": "qcs8300 pinctrl and clocks", "version": 4, "patches": 5,
          "applied": applied[0], "mbx": "/x/s01.mbx", "prerequisites": {"patch_ids": []},
          "unresolved_prerequisites": []},
         {"message_id": "board@example.com", "title": "ventuno q", "version": 2, "patches": 4,
          "applied": applied[1], "mbx": "/x/s02.mbx", "prerequisites": {"patch_ids": []},
          "unresolved_prerequisites": []}]
    if applied[0] is False:
        s[0]["failed_patch"] = {"number": 3, "subject": "[PATCH v4 3/5] pinctrl: qcom: Add QCS8300", "error": "x"}
    p = tmp_path / "stack.json"
    p.write_text(json.dumps(s))
    return str(p)


def test_adhoc_run_records_the_stack(tmp_path):
    p = str(tmp_path / "a.json")
    urun.main(["new", p, "--id", "ubci-3", "--kind", "adhoc", "--branch", "master", "--commit", "ece349ade2",
               "--fingerprint", "ubci-3", "--targets", "ventuno-q:stock,ventuno-q:open",
               "--stack", stack_file(tmp_path, [True, True])])
    r = json.load(open(p))
    assert r["run"]["kind"] == "adhoc" and r["run"]["base"]["branch"] == "master"
    assert [(s["message_id"], s["version"], s["patches"], s["applied"]) for s in r["run"]["stack"]] == [
        ("clk@example.com", 4, 5, True), ("board@example.com", 2, 4, True)]
    assert "mbx" not in r["run"]["stack"][0] and {t["state"] for t in r["targets"]} == {"queued"}
    assert schema.errors(r) == []


def test_a_stack_that_does_not_apply_skips_every_target(tmp_path):
    p = str(tmp_path / "a.json")
    urun.main(["new", p, "--id", "ubci-4", "--kind", "adhoc", "--commit", "ed869863c7",
               "--fingerprint", "ubci-4", "--stack", stack_file(tmp_path, [False, None])])
    r = json.load(open(p))
    assert {t["state"] for t in r["targets"]} == {"skipped"}
    assert r["targets"][0]["state_detail"] == \
        "does not apply: qcs8300 pinctrl and clocks v4, patch 3/5: [PATCH v4 3/5] pinctrl: qcom: Add QCS8300"
    assert r["state"] == "done"


def test_close_cancelled_run_left_building(doc, capsys):
    # ubci-40121088154-1-main: cancelled during the host checks, published
    # by prepare as "building" with every target queued, never touched again.
    urun.main(["host", doc, "docs", "running"])
    r = json.load(open(doc))
    r["targets"][1]["state"] = "testing"
    r["targets"][1]["lava"] = {"job_id": 511644, "url": "u", "device": "d", "health": None}
    r["targets"][2].update(state="skipped", state_detail="board not in this base: no x device tree")
    json.dump(r, open(doc, "w"))
    urun.main(["close", doc, "cancelled"])
    r = json.load(open(doc))
    assert schema.errors(r) == []
    assert r["state"] == "cancelled" and r["note"] == "workflow cancelled"
    assert [t["state"] for t in r["targets"]] == ["cancelled", "cancelled", "skipped"] + ["cancelled"] * 15
    assert r["targets"][0]["state_detail"] == "workflow cancelled before this target finished"
    assert r["targets"][1]["state_detail"].endswith("; LAVA job 511644 was not collected")
    assert r["host_checks"] == [{"name": "docs", "result": "skip",
                                 "summary": "did not finish: workflow cancelled"}]
    assert "ubci-1: cancelled" in capsys.readouterr().out
    # Closed for good: a later save does not reopen it.
    urun.save(doc, r)
    assert json.load(open(doc))["state"] == "cancelled"


def test_close_failed_run_is_an_error(doc):
    urun.main(["close", doc, "failure"])
    r = json.load(open(doc))
    assert r["state"] == "error" and {t["state"] for t in r["targets"]} == {"error"}
    assert r["targets"][0]["state_detail"] == "workflow failed before this target finished"


def test_close_leaves_a_finished_run_alone(doc, capsys):
    urun.main(["skip", doc, "no LAVA_TOKEN"])
    before = json.load(open(doc))
    assert before["state"] == "done"
    urun.main(["close", doc, "cancelled"])
    assert json.load(open(doc)) == before
    assert "already done" in capsys.readouterr().out


def test_close_takes_only_a_workflow_conclusion(doc):
    with pytest.raises(SystemExit):
        urun.main(["close", doc, "success"])


def test_a_cancelled_run_stays_cancelled_when_every_target_was_over(doc):
    urun.main(["host", doc, "docs", "running"])
    urun.main(["skip", doc, "no LAVA_TOKEN"])
    assert json.load(open(doc))["state"] != "done"  # docs still running
    urun.main(["close", doc, "cancelled"])
    r = json.load(open(doc))
    urun.save(doc, r)
    assert json.load(open(doc))["state"] == "cancelled"


# The refusal LAVA gave nightly 40152748187 for both RB3 Gen 2 targets.
REFUSED = ("Problem with submitted job data: You do not have permission to submit "
           "jobs to device 'rb3g2-02'.")


def refusing_lab(sent, refuse):
    class L(Lab):
        devs = [{"hostname": "rb3g2-02", "state": "Idle", "health": "Good"},
                {"hostname": "rb3g2-05", "state": "Idle", "health": "Good"},
                {"hostname": "ventunoq-01", "state": "Idle", "health": "Good"}]

        def devices(self, device_type):
            prefix = "rb3g2-" if device_type == "qcs6490-rb3gen2" else "ventunoq-"
            return [d for d in self.devs if d["hostname"].startswith(prefix)]

        def upload(self, path):
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            sent.append(definition)
            for d in refuse:
                if "device: %s\n" % d in definition:
                    raise Rejected("submit_job", 400, REFUSED.replace("rb3g2-02", d))
            return 800 + len(sent)
    return L


def four_packages(tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    for name in ("rb3gen2-stock", "rb3gen2-open", "ventuno-q-stock"):
        make_pkg(pk, name)
    project = urun.config.project()
    project["lava"]["max_in_flight_per_device_type"] = 4
    monkeypatch.setattr(urun.config, "project", lambda: project)
    return pk


def test_a_device_that_refuses_the_user_is_passed_over(doc, tmp_path, monkeypatch):
    pk = four_packages(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(urun, "Lava", refusing_lab(sent, ["rb3g2-02"]))
    urun.main(["submit", doc, str(pk)])
    r = json.load(open(doc))
    assert schema.errors(r) == []
    rb3 = r["targets"][:2]
    assert [t["state"] for t in rb3] == ["queued", "queued"]
    assert all(t["lava"]["job_id"] > 800 for t in rb3)
    # rb3g2-02 is asked once per pass, not once per target
    assert sum("device: rb3g2-02\n" in d for d in sent) == 1
    assert sum("device: rb3g2-05\n" in d for d in sent) == 2
    assert target_of(r, "ventuno-q", "stock")["lava"]["job_id"] > 800


def test_no_device_takes_the_job_is_an_error_with_the_reason(doc, tmp_path, monkeypatch):
    pk = four_packages(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(urun, "Lava", refusing_lab(sent, ["rb3g2-02", "rb3g2-05"]))
    urun.main(["submit", doc, str(pk)])
    r = json.load(open(doc))
    assert schema.errors(r) == []
    for t in r["targets"][:2]:
        assert t["state"] == "error" and "lava" not in t
        assert t["state_detail"] == ("no healthy qcs6490-rb3gen2 device takes jobs from this "
                                     "LAVA user (refused by rb3g2-02, rb3g2-05)")
    # the refusal did not end the pass: the VENTUNO Q target went in
    assert target_of(r, "ventuno-q", "stock")["lava"]["job_id"] > 800


def test_a_rejected_job_is_an_error_with_lavas_message(doc, tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    make_pkg(pk, "rb3gen2-stock")
    calls = []
    msg = "Problem with submitted job data: " + "x" * 300 + " missing key 'timeouts'"

    class L(Lab):
        def upload(self, path):
            return "https://lava.example/a/x", "tok"

        def submit(self, definition):
            calls.append(1)
            raise Rejected("submit_job", 400, msg)

    monkeypatch.setattr(urun, "Lava", L)
    urun.main(["submit", doc, str(pk)])
    urun.main(["submit", doc, str(pk)])
    t = json.load(open(doc))["targets"][0]
    assert len(calls) == 1
    assert t["state"] == "error" and t["state_detail"] == "LAVA rejected the job: " + msg


@pytest.mark.parametrize("status, state, detail", [
    ({"result": "skip", "reason": "board not in this base: no qcom/monaco-arduino-monza device tree"},
     "skipped", "board not in this base: no qcom/monaco-arduino-monza device tree"),
    ({"result": "fail", "reason": "build failed: u-boot.mbn lacks the fingerprint x"},
     "error", "build failed: u-boot.mbn lacks the fingerprint x"),
    (None, "error", "no package and no build result from the ci job"),
])
def test_a_target_without_a_package_says_why(doc, tmp_path, monkeypatch, status, state, detail):
    pk = tmp_path / "pk"
    pk.mkdir()
    if status:
        (pk / "rb3gen2-stock.build.json").write_text(json.dumps(status))
    monkeypatch.setattr(urun, "Lava", Lab)
    urun.main(["submit", doc, str(pk)])
    r = json.load(open(doc))
    assert schema.errors(r) == []
    assert (r["targets"][0]["state"], r["targets"][0]["state_detail"]) == (state, detail)


def comp(t, name):
    return next(c for c in t["components"] if c["name"] == name)


def target_of(r, board, stack):
    return next(t for t in r["targets"] if t["board"] == board and t["stack"] == stack)


def test_every_target_names_its_exact_software(doc):
    r = json.load(open(doc))
    for t in r["targets"]:
        ub = comp(t, "u-boot")
        assert ub["url"] == "https://git.u-boot-project.org/u-boot/u-boot/-/commit/" + ub["commit"]
        if t["stack"] not in config.board(t["board"])["u-boot"]:
            # Nothing to build: no firmware is named, only why.
            assert [c["name"] for c in t["components"]] == ["u-boot", "linux"] and t["boot_chain"] == []
            if t["stack"] == "spl":
                assert t["spl"] == urun.spl_info(config.board(t["board"]))
            continue
        ds = comp(t, "downstream firmware")
        assert ds["origin"] == "downstream" and ds["files"] and all(len(f["sha256"]) == 64 for f in ds["files"])
        assert all(f["url"].startswith("https://") for f in ds["files"])
        assert ds["layers"] and all(l["url"].endswith("/commit/" + l["commit"]) for l in ds["layers"])
        lx = comp(t, "linux")
        assert lx["url"].endswith("/commit/?id=" + LINUX["commit"]) and lx["branch"] == "next-20261023"
        assert lx["config"]["url"].endswith("arch/arm64/configs/defconfig?id=" + LINUX["commit"])
        assert t["boot_chain"][0]["stage"] == "XBL" and t["boot_chain"][-1]["component"] == "linux"
    # UNO Q: the open stack sits on other boot firmware than ABL chainload.
    assert comp(target_of(r, "uno-q", "stock"), "downstream firmware")["release"] != \
        comp(target_of(r, "uno-q", "open"), "downstream firmware")["release"]
    dtbs = [d["name"] for d in comp(target_of(r, "lemans-evk", "open"), "linux")["dtbs"]]
    assert dtbs == ["qcom/lemans-evk.dtb", "qcom/lemans-el2.dtbo"]
    assert comp(target_of(r, "lemans-evk", "open"), "linux")["dtbs"][1]["url"].split("?")[0].endswith(
        "arch/arm64/boot/dts/qcom/lemans-el2.dtso")


def test_open_stack_pins_link_their_commits_and_say_when_not_public(doc):
    r = json.load(open(doc))
    tfa = comp(target_of(r, "qcs615-ride", "open"), "tf-a")
    assert tfa["url"] == "https://github.com/EmbeddedAndroid/arm-trusted-firmware/commit/" + tfa["commit"]
    assert tfa["pending"] and tfa["soc_branch"]["name"] == "qcom/talos" and tfa["upstream"] is None
    assert "pending" not in comp(target_of(r, "rb3gen2", "open"), "tf-a")
    spl = comp(target_of(r, "lemans-evk", "open"), "u-boot spl")
    assert spl["origin"] == "downstream" and "commit" not in spl and spl["fingerprint"].startswith("LEMANSFP-")
    bl2 = comp(target_of(r, "uno-q", "open"), "tf-a bl2")
    assert bl2["origin"] == "upstream" and bl2["commit"] == comp(target_of(r, "uno-q", "open"), "tf-a")["commit"]


def test_built_records_the_configs_the_base_had(doc, tmp_path):
    d = tmp_path / "targets" / "ventuno-q-open"
    d.mkdir(parents=True)
    (d / "u-boot.json").write_text(json.dumps({"configs": "qcom_defconfig tfa-optee.config",
                                               "sha256": "a" * 64}))
    (d / "esp.json").write_text(json.dumps({"dtb_sha256": "b" * 64}))
    r = json.load(open(doc))
    before = comp(target_of(r, "ventuno-q", "open"), "u-boot")["configs"]
    assert {c["used"] for c in before} == {None}
    urun.main(["built", doc, str(tmp_path / "targets")])
    r = json.load(open(doc))
    assert schema.errors(r) == []
    t = target_of(r, "ventuno-q", "open")
    assert comp(t, "u-boot")["configs"] == [
        {"name": "qcom_defconfig", "used": True, "optional": False},
        {"name": "tfa-optee.config", "used": True, "optional": False},
        {"name": "arduino-ventuno-q.config", "used": False, "optional": True}]
    assert comp(t, "u-boot")["sha256"] == "a" * 64 and comp(t, "linux")["dtb_sha256"] == "b" * 64
    # A target without a build keeps the configs it declares, not built.
    assert {c["used"] for c in comp(target_of(r, "rb3gen2", "open"), "u-boot")["configs"]} == {None}


def test_linux_recorded_later_reaches_every_target(tmp_path):
    p = str(tmp_path / "run.json")
    urun.main(["new", p, "--id", "ubci-2", "--commit", "ed869863c7e2", "--fingerprint", "ubci-2",
               "--targets", "rb3gen2:stock"])
    assert not [c for c in json.load(open(p))["targets"][0]["components"] if c["name"] == "linux"]
    lj = tmp_path / "linux.json"
    lj.write_text(json.dumps(LINUX))
    urun.main(["linux", p, str(lj)])
    r = json.load(open(p))
    assert comp(r["targets"][0], "linux")["commit"] == LINUX["commit"]
    assert r["linux"]["tag_url"].endswith("/tag/?h=next-20261023")


def test_spl_target_names_the_spl_built_here_and_the_series_in_flight(doc):
    r = json.load(open(doc))
    t = target_of(r, "lemans-evk", "spl")
    spl = comp(t, "u-boot spl")
    assert spl["origin"] == "upstream" and spl["commit"] == comp(t, "u-boot")["commit"]
    assert spl["fingerprint"] == t["fingerprint"] == "ubci-1-spl-lemans-evk"
    assert [c["name"] for c in t["components"]][:5] == ["u-boot", "downstream firmware", "tf-a", "optee",
                                                        "u-boot spl"]
    assert not any(c["name"] in ("tf-a bl2", "u-boot spl") and c["origin"] == "downstream"
                   for c in t["components"])
    assert [c["name"] for c in comp(t, "u-boot")["configs"]] == ["qcom_lemans_spl_defconfig", "tfa-optee.config"]
    assert t["boot_chain"][1] == {"stage": "U-Boot SPL", "origin": "upstream", "component": "u-boot spl",
                                  "detail": "from the tree under test, in place of tz"}
    flight = t["spl"]["in_flight"]
    assert flight[0]["link"] == "https://lore.kernel.org/r/20260928-spl-lemans-v4-0-007635cc4667@oss.qualcomm.com"
    assert "spl" not in target_of(r, "lemans-evk", "open")


def stack_doc(tmp_path, touches):
    p = tmp_path / "stack.json"
    p.write_text(json.dumps([{"message_id": "a@b", "link": "https://lore.kernel.org/r/a@b", "title": "t",
                              "version": 1, "patches": 1, "applied": True, "touches_spl": touches}]))
    return str(p)


@pytest.mark.parametrize("touches, want", [(True, ["stock", "spl"]), (False, ["stock"])])
def test_spl_runs_on_an_adhoc_stack_only_when_it_touches_spl(tmp_path, touches, want):
    p = str(tmp_path / "run.json")
    urun.main(["new", p, "--id", "ubci-a", "--commit", "0" * 40, "--fingerprint", "ubci-a", "--kind", "adhoc",
               "--stack", stack_doc(tmp_path, touches), "--targets", "lemans-evk:stock,lemans-evk:spl?"])
    r = json.load(open(p))
    assert [t["stack"] for t in r["targets"]] == want
    assert "touches_spl" not in r["run"]["stack"][0]


def test_an_spl_target_asked_for_runs_whatever_the_stack(tmp_path):
    p = str(tmp_path / "run.json")
    urun.main(["new", p, "--id", "ubci-a", "--commit", "0" * 40, "--fingerprint", "ubci-a", "--kind", "adhoc",
               "--stack", stack_doc(tmp_path, False), "--targets", "lemans-evk:spl"])
    assert [t["stack"] for t in json.load(open(p))["targets"]] == ["spl"]
