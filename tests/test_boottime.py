"""Boot times per target (fwci.boottime): real u-boot-ci job logs cut down
by scripts/mk-boottime-fixture.py, and synthetic logs for the paths the
lab has not shown yet."""
import json
import pathlib

import pytest

from fwci import boottime, collect, schema
from fwci.lava_jobs import END_MARK

DATA = pathlib.Path(__file__).resolve().parent / "data" / "boottime"
URL = "https://lava.example.org/scheduler/job/1"


def fixture(name):
    return (DATA / (name + ".yaml")).read_text()


def measure(text, step=None):
    return boottime.measure(text, collect.log_entries(text), URL, step)


def line(t, lvl, msg):
    return "- " + json.dumps({"dt": "2026-11-01T00:%02d:%09.6f+00:00" % (t // 60, t % 60),
                              "lvl": lvl, "msg": msg})


def power_on(t, level="3.1"):
    return [line(t, "debug", "start: %s pdu-reboot (timeout 00:01:00)" % level),
            line(t, "debug", "Calling: ['power']"),
            line(t + 0.1, "debug", "end: %s pdu-reboot (duration 00:00:00)" % level)]


def boot_lines(t, linux=True):
    out = [line(t + 0.4, "target", "B -    1 - SBL1, Start"),
           line(t + 1.5, "target", "B -  900 - SBL1, End"),
           line(t + 2.5, "target", "U-Boot 2026.10-rc1-ubci-1-1-stock-rb3gen2 (Nov 01 2026)")]
    if linux:
        out.append(line(t + 4.8, "target", "[    0.000000] Booting Linux on physical CPU 0x0"))
    return out


def test_real_job_kinds_and_stages():
    bt = measure(fixture("rb3gen2-open"))
    assert [b["kind"] for b in bt["boots"]] == ["first", "warm-reset", "warm-reboot"]
    # This job has no power-on after the first: nothing to lead with.
    assert bt["headline"] is None
    first, reset, reboot = bt["boots"]
    assert first["stages"]["loader"]["replayed"]
    assert boottime.time_of(first, "loader") is None
    assert first["last_stage"] == "uboot" and not first["complete"]
    assert boottime.time_of(reset, "linux") == pytest.approx(4.748)
    assert reset["complete"] and reboot["complete"]
    for k in ("bl2", "bl31", "optee", "uboot"):
        assert k in reset["stages"]
    assert reset["url"] == "%s#L%d" % (URL, reset["ref_line"])
    assert bt["version"] == 1 and bt["tool"].startswith("lava-boottime ")


def test_links_point_at_the_stage_line():
    text = fixture("rb3gen2-open")
    entries = collect.log_entries(text)
    bt = measure(text)
    st = bt["boots"][1]["stages"]["linux"]
    assert "Booting Linux on physical CPU" in entries[st["line"]][2]
    assert "resetting ..." in entries[bt["boots"][1]["ref_line"]][2]


def test_downstream_chain_through_abl():
    reset = measure(fixture("uno-q-stock"))["boots"][1]
    assert list(reset["stages"])[:5] == ["loader", "loader_end", "uefi", "ebs", "uboot"]
    assert boottime.time_of(reset, "linux") == pytest.approx(10.002)


def test_reset_that_never_boots_again():
    # VENTUNO Q open stack: U-Boot's reset hangs, nothing follows it.
    bt = measure(fixture("ventuno-q-open-reset-hang"))
    assert [b["kind"] for b in bt["boots"]] == ["first"]
    assert bt["boots"][0]["last_stage"] == "uboot"
    assert bt["boots"][0]["reset"] is None


def test_boot_that_stops_before_linux():
    # QCS615: U-Boot cannot read UFS, so no stage after U-Boot.
    reset = measure(fixture("qcs615-ride-stock-no-linux"))["boots"][1]
    assert reset["kind"] == "warm-reset" and reset["last_stage"] == "uboot"
    assert boottime.time_of(reset, "linux") is None and not reset["complete"]


def test_truncated_log():
    text = fixture("rb3gen2-open").splitlines()
    cut = [i for i, ln in enumerate(text) if "U-Boot 20" in ln][1]
    bt = measure("\n".join(text[:cut + 1]))
    assert [b["kind"] for b in bt["boots"]] == ["first", "warm-reset"]
    assert bt["boots"][1]["last_stage"] == "uboot"


def test_cold_boot_after_the_first_is_the_headline():
    log = power_on(0) + boot_lines(0, linux=False) + power_on(60, "13.1") + boot_lines(60)
    bt = measure("\n".join(log))
    assert [b["kind"] for b in bt["boots"]] == ["first", "cold"]
    assert bt["headline"] == 1
    assert boottime.time_of(bt["boots"][1], "linux") == pytest.approx(4.8)


def test_replayed_burst_is_never_compared():
    # The console comes back after a blocking power command and LAVA logs
    # its backlog in one burst: those lines only bound the stages.
    burst = [line(5.0 + i * 0.0005, "target", "x" * 120) for i in range(40)]
    log = power_on(0) + [line(5.0, "target", "B -    1 - SBL1, Start")] + burst + [
        line(5.02, "target", "U-Boot 2026.10 (Nov 01 2026)"),
        line(9.0, "target", "[    0.000000] Booting Linux on physical CPU 0x0")]
    (b,) = measure("\n".join(log))["boots"]
    assert b["stages"]["uboot"]["replayed"] and boottime.time_of(b, "uboot") is None
    assert boottime.time_of(b, "linux") == pytest.approx(9.0)


def test_no_boot_in_the_log():
    assert measure("") == {"version": 1, "tool": boottime.TOOL, "boots": [], "headline": None}
    assert measure("\n".join(power_on(0)))["boots"] == []


def shell_check(t, suite, case, output, verdict="pass"):
    cmd = 'if ( ./boot-time.sh ); then v=pass; else v=fail; fi; echo "@@ %s $v @@"; echo "%s""@@"' % (
        case, END_MARK[:-2])
    out = [line(t, "debug", "Waiting for '@@ %s pass @@', '@@ %s fail @@'" % (case, case)),
           line(t, "target", cmd)]
    out += [line(t + 0.1 * (i + 1), "target", o) for i, o in enumerate(output)]
    if verdict:
        out.append(line(t + 2, "target", "@@ %s %s @@" % (case, verdict)))
        out.append(line(t + 2, "results", {"definition": "0_" + suite, "case": case, "result": verdict}))
    return out


CASE_OUTPUT = [
    "INFO: log time, CNTVCT_EL0, CNTFRQ_EL0, CLOCK_BOOTTIME(ns): 12.5 362880000 19200000 12400000000",
    "pre-kernel pass 6.400 s",
    "kernel-to-init pass 3.152 s",
    "INFO: kernel-to-login: no process of this session was started by init",
    "kernel-to-login skip",
]


def test_on_target_case_is_parsed_and_tied_to_its_boot():
    log = power_on(0) + boot_lines(0, linux=False) + power_on(60, "13.1") + boot_lines(60) + \
        shell_check(90, "boot-time", "boot-time", CASE_OUTPUT)
    bt = measure("\n".join(log), ("boot-time", "boot-time"))
    ot = bt["on_target"]
    assert ot["boot"] == 1 and ot["finished"]
    got = {c["name"]: c for c in ot["cases"]}
    assert got["pre-kernel"] == {"name": "pre-kernel", "result": "pass", "value": 6.4, "units": "s"}
    assert got["kernel-to-init"]["value"] == pytest.approx(3.152)
    assert got["kernel-to-login"] == {"name": "kernel-to-login", "result": "skip",
                                      "note": "no process of this session was started by init"}
    assert ot["url"].startswith(URL + "#L")


def test_on_target_case_that_never_finished():
    log = power_on(0) + boot_lines(0) + shell_check(30, "boot-time", "boot-time", CASE_OUTPUT[:2], verdict=None)
    ot = measure("\n".join(log), ("boot-time", "boot-time")).get("on_target")
    # Without its result LAVA never reported the check: nothing to show.
    assert ot is None


def test_on_target_case_absent():
    log = power_on(0) + boot_lines(0)
    assert "on_target" not in measure("\n".join(log), ("boot-time", "boot-time"))


def base_target():
    return {"board": "rb3gen2", "stack": "open", "state": "testing", "fingerprint": "ubci-1-1-open-rb3gen2",
            "lava": {"job_id": 1, "url": URL}, "cases": []}


def test_collector_records_boot_times_of_a_finished_job():
    text = fixture("rb3gen2-open")
    job = {"id": 1, "state": "Finished", "health": "Complete", "actual_device": "rb3g2-01"}
    t = collect.target(base_target(), job, [], collect.log_entries(text), URL, ["firmware-fingerprint"],
                       r"resetting \.\.\.", log=text)
    assert [b["kind"] for b in t["boot_time"]["boots"]] == ["first", "warm-reset", "warm-reboot"]
    run = {"schema": "fwci-run/1", "project": "u-boot", "state": "done", "host_checks": [], "targets": [t],
           "run": {"id": "r1", "kind": "nightly", "created": "2026-11-01T00:00:00Z",
                   "updated": "2026-11-01T00:00:00Z", "base": {"repo": "r", "branch": "main", "commit": "0123456789ab"}}}
    schema.check(run)


def test_collector_does_not_measure_a_running_job():
    text = fixture("rb3gen2-open")
    job = {"id": 1, "state": "Running", "health": "Unknown", "actual_device": "rb3g2-01"}
    t = collect.target(base_target(), job, [], collect.log_entries(text), URL, ["firmware-fingerprint"],
                       r"resetting \.\.\.", log=text)
    assert "boot_time" not in t


def test_schema_rejects_an_unknown_boot_kind():
    bt = measure(fixture("rb3gen2-open"))
    bt["boots"][0]["kind"] = "lukewarm"
    t = dict(base_target(), state="done", boot_time=bt)
    run = {"schema": "fwci-run/1", "project": "u-boot", "state": "done", "host_checks": [], "targets": [t],
           "run": {"id": "r1", "kind": "nightly", "created": "2026-11-01T00:00:00Z",
                   "updated": "2026-11-01T00:00:00Z", "base": {"repo": "r", "branch": "main", "commit": "0123456789ab"}}}
    assert any("lukewarm" in e for e in schema.errors(run))


def test_malformed_values_from_the_board_are_not_values():
    out = CASE_OUTPUT[:1] + ["pre-kernel pass .", "kernel-to-init pass 1.2.3 s", "kernel-to-login pass 2 s"]
    log = power_on(0) + boot_lines(0) + shell_check(30, "boot-time", "boot-time", out)
    got = {c["name"]: c for c in measure("\n".join(log), ("boot-time", "boot-time"))["on_target"]["cases"]}
    assert set(got) == {"kernel-to-login"} and got["kernel-to-login"]["value"] == 2.0


def test_a_measurement_error_does_not_stop_collection(monkeypatch, capsys):
    def boom(*a, **k):
        raise ValueError("bad")
    monkeypatch.setattr(boottime, "measure", boom)
    text = fixture("rb3gen2-open")
    job = {"id": 1, "state": "Finished", "health": "Complete", "actual_device": "rb3g2-01"}
    t = collect.target(base_target(), job, [], collect.log_entries(text), URL, ["firmware-fingerprint"],
                       r"resetting \.\.\.", log=text)
    assert t["state"] == "done" and "boot_time" not in t and "linux_boot" in t
    assert "boot time not measured: ValueError: bad" in capsys.readouterr().err
