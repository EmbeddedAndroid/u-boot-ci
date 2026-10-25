import json

import pytest

from fwci import schema
from fwci.lava_mcp import Rejected
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
        ("rb3gen2", "stock"), ("rb3gen2", "open"), ("ventuno-q", "stock"), ("ventuno-q", "open")]
    open_rb3 = r["targets"][1]
    tfa = [c for c in open_rb3["components"] if c["name"] == "tf-a"][0]
    assert tfa["role"] == "pinned" and tfa["upstream"]["distance"] == len(tfa["upstream"]["carried"])
    optee = [c for c in open_rb3["components"] if c["name"] == "optee"][0]
    assert optee["upstream"]["distance"] == 0
    assert open_rb3["linux_boot"]["gaps"]
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


def test_submit_skips_boards_without_a_stock_restore(doc, tmp_path, monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("STOCK_RESTORE_"):
            monkeypatch.delenv(k)
    monkeypatch.setattr(urun, "Lava", lambda: object())
    urun.main(["submit", doc, str(tmp_path)])
    r = json.load(open(doc))
    assert {t["state_detail"] for t in r["targets"]} == {"no stock restore image configured"}


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


class FakeLava(Lab):
    def __init__(self, log, restore_ok=True):
        self._log = log
        self.submitted = []
        self.restore_ok = restore_ok

    def submit(self, definition):
        self.submitted.append(definition)
        return 900 + len(self.submitted)

    def job(self, i):
        return {"id": i, "state": "Finished", "health": "Complete", "actual_device": "d1"}

    def results(self, i):
        if i >= 900:
            return [{"name": "uefi_ver", "result": "pass" if self.restore_ok else "fail", "suite": 3,
                     "metadata": "definition: 0_stock-restore\n"}]
        return [{"name": "u_boot_20", "result": "pass", "suite": 1, "start_log_line": 2,
                 "metadata": "definition: 0_firmware-fingerprint\n"},
                {"name": "u_boot_20", "result": "pass", "suite": 1, "start_log_line": 3,
                 "metadata": "definition: 2_firmware-fingerprint-reset\n"},
                {"name": "uefi_ver", "result": "pass", "suite": 2, "start_log_line": 9,
                 "metadata": "definition: 9_stock-restore\n"}]

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
    assert t["state"] == "done" and t["fingerprint_gate"] == "pass" and t["restore"] == "pass"
    assert t["linux_boot"]["stage"] == "early-panic" and t["linux_boot"]["versus_baseline"] == "unknown"
    assert t["linux_boot"]["url"].endswith("#L6") and t["linux_boot"]["gaps"]
    assert r["state"] == "done"


def test_job_that_stopped_early_gets_a_recovery_job(doc, monkeypatch):
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
    monkeypatch.setenv("STOCK_RESTORE_TOKEN", "LAB_TOKEN")
    r = json.load(open(doc))
    t = r["targets"][0]
    t["lava"] = {"job_id": 100, "url": "https://lava.example/scheduler/job/100", "device": None, "health": None}
    lava = FakeLava("- " + json.dumps({"lvl": "target", "msg": "hang"}))
    lava.results = lambda i: [{"name": "u_boot_20", "result": "pass", "suite": 1,
                               "metadata": "definition: 0_firmware-fingerprint\n"}] if i < 900 else \
        [{"name": "uefi_ver", "result": "pass", "suite": 3, "metadata": "definition: 0_stock-restore\n"}]
    urun.collect_once(r, lava, None)
    assert t["restore"] == "recovery-job" and t["recovery"]["job_id"] == 901
    assert "device: d1" in lava.submitted[0] and "LAB_TOKEN" in lava.submitted[0]
    urun.collect_once(r, lava, None)
    assert t["restore"] == "pass" and t["recovery"]["health"] == "Complete" and len(lava.submitted) == 1
    urun.save(doc, r)


def test_no_recovery_possible_is_a_failed_restore(doc, monkeypatch):
    monkeypatch.delenv("STOCK_RESTORE_URL_RB3GEN2", raising=False)
    r = json.load(open(doc))
    t = r["targets"][0]
    t["lava"] = {"job_id": 100, "url": "u", "device": None, "health": None}
    lava = FakeLava("")
    lava.results = lambda i: []
    urun.collect_once(r, lava, None)
    assert t["restore"] == "fail" and "no recovery job" in t["state_detail"] and not lava.submitted


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
    assert "| rb3gen2 | stock-candidate | QCM6490 boot binaries 00150 |" in out


def test_candidate_job_is_the_stock_job():
    from ubci import jobs
    pkg = {"url": "u", "token": "t", "path": "p"}
    restore = {"url": "r", "token": "t", "path": "s"}
    linux = {"tag": "next-20261023", "image_sha256": "0" * 64}
    a = jobs.render("rb3gen2", "stock", "f", pkg, linux, restore)
    b = jobs.render("rb3gen2", "stock-candidate", "f", pkg, linux, restore)
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
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
    monkeypatch.setenv("STOCK_RESTORE_URL_VENTUNO_Q", "https://lab.example/vq.tar.gz")
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
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")

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
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
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


def test_finished_waits_for_recovery(doc):
    r = json.load(open(doc))
    for t in r["targets"]:
        t["state"] = "done"
    r["targets"][0]["restore"] = "recovery-job"
    urun.save(doc, r)
    with pytest.raises(SystemExit) as e:
        urun.main(["finished", doc])
    assert e.value.code == 1
    r["targets"][0]["restore"] = "pass"
    urun.save(doc, r)
    with pytest.raises(SystemExit) as e:
        urun.main(["finished", doc])
    assert e.value.code == 0


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
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")

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
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
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
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
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
    r["targets"][2]["state"] = "skipped"
    json.dump(r, open(doc, "w"))
    urun.main(["close", doc, "cancelled"])
    r = json.load(open(doc))
    assert schema.errors(r) == []
    assert r["state"] == "cancelled" and r["note"] == "workflow cancelled"
    assert [t["state"] for t in r["targets"]] == ["cancelled", "cancelled", "skipped", "cancelled"]
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
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
    monkeypatch.setenv("STOCK_RESTORE_URL_VENTUNO_Q", "https://lab.example/vq.tar.gz")
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
    assert r["targets"][2]["lava"]["job_id"] > 800


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
    assert r["targets"][2]["lava"]["job_id"] > 800


def test_a_rejected_job_is_an_error_with_lavas_message(doc, tmp_path, monkeypatch):
    pk = tmp_path / "pk"
    pk.mkdir()
    make_pkg(pk, "rb3gen2-stock")
    monkeypatch.setenv("STOCK_RESTORE_URL_RB3GEN2", "https://lab.example/rb3.tar.gz")
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

