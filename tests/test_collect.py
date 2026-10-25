import json
import os

from fwci import collect

URL = "https://lava.example/scheduler/job/9"


def log(*entries):
    return "\n".join("- " + json.dumps({"dt": "t", "lvl": lvl, "msg": msg}) for lvl, msg in entries)


LOG = log(("info", "start: 0 validate"),
          ("target", "SBL1, End"),
          ("target", "U-Boot 2026.10-ubci-1"),
          ("target", "resetting ..."),
          ("target", "Booting: scsi 0"),
          ("target", "EFI stub: Booting Linux Kernel..."),
          ("target", "Booting Linux on physical CPU 0x0"),
          ("results", {"case": "x"}),
          ("target", "buildroot login:"),
          ("target", "reboot: Restarting system"),
          ("target", "Booting: scsi 0"))


def result(suite, name, res, line=None):
    return {"name": name, "result": res, "metadata": "definition: %s\ncase: %s\n" % (suite, name),
            "start_log_line": line, "suite": 1}


def test_log_entries_keep_lava_line_indexes():
    e = collect.log_entries(LOG + "\nnot an entry")
    assert e[0] == (0, "info", "start: 0 validate")
    assert e[7][0] == 7 and e[7][1] == "results" and json.loads(e[7][2]) == {"case": "x"}
    assert len(e) == 11


# Entries as LAVA 511932 logged them: YAML escapes for console bytes and a
# YAML tag, none of them valid JSON.
YAML_ONLY = [
    r'- {"dt": "t", "lvl": "results", "msg": {"case": "http-download", "extra": {"size": ! "44297776"}}}',
    r'- {"dt": "t", "lvl": "target", "msg": "\0\0S - \b\b\b\bFormat: Log Type"}',
    r'- {"dt": "t", "lvl": "target", "msg": "\uFFFD\v\uFFFD\x01"}',
]


def test_log_entries_parse_yaml_only_entries_in_place():
    text = "\n".join([YAML_ONLY[0], YAML_ONLY[1], YAML_ONLY[2], LOG])
    e = collect.log_entries(text)
    assert len(e) == 3 + 11
    assert e[0][1] == "results" and json.loads(e[0][2])["case"] == "http-download"
    assert e[1] == (1, "target", "\0\0S - \b\b\b\bFormat: Log Type")
    assert e[2] == (2, "target", "\ufffd\v\ufffd\x01")
    assert e[3] == (3, "info", "start: 0 validate")
    assert e[13] == (13, "target", "Booting: scsi 0")


def test_log_entries_keep_the_index_of_an_unparsable_entry():
    e = collect.log_entries("- {broken\n" + LOG)
    assert e[0] == (0, "", "")
    assert e[1] == (1, "info", "start: 0 validate")
    assert len(e) == 12


def test_window_is_first_boot_only():
    w = collect.window(collect.console(collect.log_entries(LOG)), r"resetting", r"reboot: Restarting")
    assert [i for i, _ in w] == [3, 4, 5, 6, 8]
    assert collect.window([(0, "x")], "never", "end") == []


def test_cases_drop_lava_suite_and_link_lines():
    c = collect.cases([result("lava", "job", "pass"), result("3_smoke", "usb", "fail", 42),
                       result("1_firmware-fingerprint", "u_boot_20", "pass", 7),
                       result("2_smoke", "odd", "weird")], URL)
    assert c == [{"suite": "smoke", "name": "usb", "result": "fail", "url": URL + "#L42"},
                 {"suite": "firmware-fingerprint", "name": "u_boot_20", "result": "pass", "url": URL + "#L7"},
                 {"suite": "smoke", "name": "odd", "result": "unknown"}]


def finished(health="Complete"):
    return {"id": 9, "state": "Finished", "health": health, "actual_device": "rb3g2-01"}


def test_target_done():
    res = [result("0_firmware-fingerprint", "u_boot_20", "pass"),
           result("5_stock-restore", "uefi_ver", "pass"), result("4_smoke", "usb", "fail")]
    t = collect.target({"board": "b", "stack": "stock"}, finished(), res,
                       collect.log_entries(LOG), URL, ["firmware-fingerprint"], "resetting")
    assert t["state"] == "done" and t["fingerprint_gate"] == "pass" and t["restore"] == "pass"
    assert t["linux_boot"]["verdict"] == "pass" and t["lava"]["device"] == "rb3g2-01"
    assert "state_detail" not in t


def test_target_gate_failure_and_incomplete_job():
    res = [result("0_firmware-fingerprint", "u_boot_20", "fail")]
    t = collect.target({"board": "b", "stack": "stock"}, finished("Incomplete"), res, [], URL,
                       ["firmware-fingerprint"], "resetting")
    assert t["fingerprint_gate"] == "fail" and t["restore"] == "not-run"
    assert t["linux_boot"] == {"verdict": "not-run", "stage": "not-reached"} or \
        t["linux_boot"]["stage"] == "not-reached"
    assert t["state_detail"] == "LAVA job incomplete"


def test_target_running_has_no_boot_verdict_yet():
    job = {"id": 9, "state": "Running", "health": "Unknown", "actual_device": "d"}
    t = collect.target({"board": "b", "stack": "open"}, job, [], collect.log_entries(LOG)[:5], URL,
                       ["firmware-fingerprint"], "resetting")
    assert t["state"] == "testing" and t["fingerprint_gate"] == "not-run"
    assert t["linux_boot"]["verdict"] == "not-run"


def test_queue_position_by_priority_then_submit_time():
    q = [{"id": 1, "requested_device_type": "a", "priority": 50, "submit_time": "2026-10-24T01:00:00Z"},
         {"id": 2, "requested_device_type": "a", "priority": 10, "submit_time": "2026-10-24T00:00:00Z"},
         {"id": 3, "requested_device_type": "b", "priority": 50, "submit_time": "2026-10-23T00:00:00Z"},
         {"id": 4, "requested_device_type": "a", "priority": 50, "submit_time": "2026-10-24T02:00:00Z"}]
    assert [collect.queue_position(q, i, "a") for i in (1, 4, 2)] == [1, 2, 3]
    assert collect.queue_position(q, 3, "a") is None


def test_gate_fails_when_the_linux_boot_did_not_show_the_build():
    res = [result("0_firmware-fingerprint", "u_boot_20", "pass"),
           result("2_firmware-fingerprint-reset", "u_boot_20", "fail")]
    t = collect.target({"board": "b", "stack": "stock"}, finished(), res, [], URL,
                       ["firmware-fingerprint", "firmware-fingerprint-reset"], "resetting")
    assert t["fingerprint_gate"] == "fail"


def test_known_gap_turns_a_failure_into_a_skip_with_the_reason():
    cl = [{"suite": "smoke", "name": "usb", "result": "fail"}, {"suite": "smoke", "name": "net", "result": "fail"},
          {"suite": "smoke", "name": "usb2", "result": "pass"}]
    collect.apply_known_gaps(cl, {"smoke/usb": "needs non-free firmware", "smoke/usb2": "x"})
    assert cl[0] == {"suite": "smoke", "name": "usb", "result": "skip", "note": "known gap: needs non-free firmware"}
    assert cl[1]["result"] == "fail" and "note" not in cl[2]


def test_a_gate_the_job_never_reached_is_not_a_failed_gate():
    # LAVA 512760: the first gate passed, U-Boot stopped after "DRAM:" on
    # XPU errors and the job ended, and LAVA reported the cases of the
    # gates that never started as failed.
    def lvl(suite, name, res, level):
        r = result(suite, name, res)
        r["metadata"] += "level: '%s'\n" % level
        return r
    res = [lvl("firmware-fingerprint", "u_boot_20", "pass", "4.1"),
           lvl("firmware-fingerprint-reset", "u_boot_20", "fail", "6.1"),
           lvl("smoke", "usb", "fail", "9.1"), lvl("u-boot", "uboot-bdinfo", "fail", "5.1")]
    entries = collect.log_entries(log(("debug", "start: 4.1 lava-test-monitor (timeout 00:05:00) [common]"),
                                      ("debug", "start: 5.1 lava-test-interactive (timeout 00:10:00) [common]"),
                                      ("target", "DRAM:  2 GiB"), ("target", "ERROR:   XPU ERROR: non secure")))
    t = collect.target({"board": "b", "stack": "open"}, finished("Incomplete"), res, entries, URL,
                       ["firmware-fingerprint", "firmware-fingerprint-reset"], "resetting")
    assert t["fingerprint_gate"] == "pass"
    by = {(c["suite"], c["name"]): c for c in t["cases"]}
    assert by[("firmware-fingerprint-reset", "u_boot_20")] == {
        "suite": "firmware-fingerprint-reset", "name": "u_boot_20", "result": "skip", "note": collect.NOT_REACHED}
    assert by[("smoke", "usb")]["result"] == "skip"
    # A check that started and failed stays a failure.
    assert by[("u-boot", "uboot-bdinfo")]["result"] == "fail"
    # A second gate that ran and did not show the build still fails it.
    res[1] = lvl("firmware-fingerprint-reset", "u_boot_20", "fail", "5.1")
    t = collect.target({"board": "b", "stack": "open"}, finished("Incomplete"), res, entries, URL,
                       ["firmware-fingerprint", "firmware-fingerprint-reset"], "resetting")
    assert t["fingerprint_gate"] == "fail"


def real_log(name):
    return collect.log_entries(open(os.path.join(os.path.dirname(__file__), "data", "lava", name)).read())


def test_failed_shell_check_shows_the_lines_it_printed():
    """LAVA 509892 #L3130-3193 (excerpt starts at index 0 here): the 50
    kernel error lines between the echo of the command and the verdict."""
    entries = real_log("509892-dmesg-errors.log")
    cl = collect.add_output([{"suite": "smoke", "name": "dmesg-errors", "result": "fail"},
                             {"suite": "smoke", "name": "storage", "result": "fail"}], entries, URL)
    c = cl[0]
    assert len(c["output"]) == 50 and c["url"] == URL + "#L7"
    assert c["output"][0].startswith("<3>[    0.364596] qcom-smem smem: Found an unknown type of DRAM info")
    assert c["output"][-1].endswith("spi master firmware load failed ret: -517")
    assert not any("@@" in line for line in c["output"]) and "note" not in c
    # storage ran after the excerpt ends: nothing to show, nothing invented
    assert "output" not in cl[1] and "note" not in cl[1]


def test_shell_check_that_never_printed_its_verdict_says_so():
    """LAVA 512816 #L3013-3034: the line was cut by the shell, the echo
    stops and LAVA times out; the case has no output and says why."""
    t = collect.target({"board": "rb3gen2", "stack": "stock"}, finished("Incomplete"),
                       [result("9_smoke", "dmesg-errors", "fail")], real_log("512816-dmesg-errors.log"),
                       URL, ["firmware-fingerprint"], "resetting")
    c = t["cases"][0]
    assert c["note"] == collect.NO_VERDICT and "output" not in c


def test_shell_output_is_capped_and_says_how_much_is_left():
    lines = [("target", "<3>[ %d.0] err" % n) for n in range(collect.OUTPUT_MAX + 5)]
    entries = collect.log_entries(log(
        ("debug", "Waiting for '@@ end@@', '@@ e fail @@', '@@ e pass @@'"),
        ("target", '# if ( x ); then v=pass; else v=fail; fi; echo "@@ e $v @@"; echo "@@ end""@@"'),
        *lines, ("target", "@@ e fail @@"),
        ("results", {"definition": "0_smoke", "case": "e", "result": "fail"})))
    c = collect.add_output([{"suite": "smoke", "name": "e", "result": "fail"},
                            {"suite": "smoke", "name": "e", "result": "pass"}], entries, URL)
    assert len(c[0]["output"]) == collect.OUTPUT_MAX + 1 and c[0]["output"][-1] == "(5 more lines in the LAVA log)"
    assert "output" not in c[1]


def test_a_hung_shell_check_keeps_what_it_printed():
    entries = collect.log_entries(log(
        ("debug", "Waiting for '@@ end@@', '@@ storage fail @@', '@@ storage pass @@'"),
        ("target", '# if ( dd if=/dev/sda ); then v=pass; else v=fail; fi; echo "@@ storage $v @@"; echo "@@ end""@@"'),
        ("target", "dd: error reading '/dev/sda': Input/output error"),
        ("results", {"definition": "0_smoke", "case": "storage", "result": "fail"})))
    c = collect.add_output([{"suite": "smoke", "name": "storage", "result": "fail"}], entries, URL)[0]
    assert c["note"] == collect.NO_VERDICT and c["url"] == URL + "#L2"
    assert c["output"] == ["dd: error reading '/dev/sda': Input/output error"]
