import os
import re

import pytest
import yaml

from fwci import lava_jobs
from ubci import config, jobs

PKG = {"url": "https://lava.example/a/pkg.tar.gz", "token": "lava-mcp-artifact-x", "path": "ubci-b"}
LINUX = {"tag": "next-20261023", "release": "7.3.0-next-20261023", "image_sha256": "5" * 64}


def monitors(job):
    return {m["name"]: m for a in job["actions"] if "test" in a for m in a["test"].get("monitors", [])}


@pytest.mark.parametrize("board", [b for b in config.boards() if "open" in config.board(b)["u-boot"]])
def test_open_stack_gate_checks_every_component(board):
    job = jobs.render(board, "open", "ubci-9", PKG, LINUX)
    gate = monitors(job)[jobs.GATE_SUITE]
    pin = config.board(board)["pins"]["bl2"]
    tz = "u_boot_spl" if pin.get("banner") == "U-Boot SPL" else "bl2_v"
    assert gate["expected"] == [tz, "bl31_v", "op_tee_version", "u_boot_20"]
    bl2 = pin["fingerprint"]
    assert bl2 in gate["fixupdict"] and "ubci-9" in gate["fixupdict"]
    assert job["device_type"] == config.board(board)["lava"]["device_type"]
    assert job["priority"] == "low" and job["visibility"] == "public"


@pytest.mark.parametrize("board", config.boards())
def test_stock_gate_checks_u_boot_only(board):
    job = jobs.render(board, "stock", "ubci-9", PKG, LINUX)
    assert monitors(job)[jobs.GATE_SUITE]["expected"] == ["u_boot_20"]


def test_spl_gate_starts_at_the_first_stage_and_checks_the_spl_built_here():
    job = jobs.render("lemans-evk", "spl", "ubci-9", PKG, LINUX)
    for name in (jobs.GATE_SUITE, jobs.GATE_SUITE + "-reset", jobs.GATE_SUITE + "-reboot"):
        gate = monitors(job)[name]
        assert gate["start"] == "SBL1, End"
        assert gate["expected"] == ["u_boot_spl", "bl31_v", "op_tee_version", "u_boot_20"]
        # One fingerprint for every stage: the pinned SPL's never passes.
        assert gate["fixupdict"] == {"ubci-9": "pass"}
    line = "U-Boot SPL 2026.10-ubci-9 (Oct 26 2026 - 00:20:28 +0000)"
    m = re.search(gate["pattern"], line)
    assert m and m.group("test_case_id") == "U-Boot SPL" and m.group("result") == "ubci-9"
    assert not re.search(gate["pattern"], line.replace("ubci-9", "LEMANSFP-261009-030954-lpb4"))
    # "U-Boot 20" is U-Boot proper, never the SPL banner.
    assert all(m.group("test_case_id") == "U-Boot SPL" for m in re.finditer(gate["pattern"], line))


def test_a_board_without_spl_has_no_spl_job():
    with pytest.raises(SystemExit, match="rb3gen2 has no spl stack"):
        jobs.render("rb3gen2", "spl", "ubci-9", PKG, LINUX)


def test_linux_version_gate_names_the_tag():
    m = monitors(jobs.render("rb3gen2", "stock", "ubci-9", PKG, LINUX))[jobs.LINUX_SUITE]
    r = re.search(m["pattern"], "[    0.000000] Linux version 7.3.0-next-20261023 (gcc 14)")
    assert r and m["fixupdict"][r.group("result")] == "pass"
    assert not re.search(m["pattern"], "Linux version 7.3.0-next-20261022 (gcc 14)")


@pytest.mark.parametrize("stack", config.STACKS + ("stock-candidate",))
@pytest.mark.parametrize("board", config.boards())
def test_job_ends_at_poweroff_with_no_restore(board, stack):
    # Every job flashes its whole package, so none restores the lab image.
    if stack not in config.board(board)["u-boot"]:
        return
    job = jobs.render(board, stack, "ubci-9", PKG, LINUX)
    deploys = [a["deploy"] for a in job["actions"] if "deploy" in a]
    assert deploys == [job["actions"][0]["deploy"]] and deploys[0]["qcomflash"]["url"] == PKG["url"]
    qdl = [a["boot"]["path"] for a in job["actions"] if "boot" in a and a["boot"]["method"] == "qdl"]
    assert qdl == [PKG["path"]]
    last = job["actions"][-1]["test"]["interactive"][0]
    assert last["name"] == "poweroff" and last["prompts"] == ["reboot: Power down"]
    names = {m["name"] for m in monitors(job).values()}
    assert not any("restore" in n for n in names)
    text = lava_jobs.to_yaml(job)
    assert "uefi_ver" not in text and "restore" not in text.lower()
    assert yaml.safe_load(text) == job
    # header values are token names LAVA resolves, never secrets
    assert re.findall(r"(?m)^\s+Authorization: (\S+)$", text) == ["lava-mcp-artifact-x"]


def test_uboot_checks_come_from_the_board():
    job = jobs.render("rb3gen2", "stock", "ubci-9", PKG, LINUX)
    steps = [a for a in job["actions"] if "test" in a and "interactive" in a["test"]][0]
    names = [s["name"] for s in steps["test"]["interactive"][0]["script"]]
    assert names[:4] == ["autoboot", "u-boot-prompt", "u-boot-sync", "uboot-version"] and names[-1] == "uboot-reset"
    assert "uboot-storage" in names


def test_unknown_board_is_refused():
    with pytest.raises(SystemExit):
        jobs.render("nope", "stock", "f", PKG, LINUX)


def test_known_errors_are_filtered_and_others_still_fail():
    import datetime
    import subprocess
    pats = jobs.known_errors("rb3gen2", datetime.date(2026, 10, 25))
    assert pats and jobs.known_errors("ventuno-q", datetime.date(2026, 10, 25)) == []
    assert jobs.known_errors("rb3gen2", datetime.date(2026, 12, 1)) == []  # expired
    cmd = jobs.errors_command(pats).replace("dmesg -r", "cat /dev/stdin")
    known = "<3>[ 3.1] geni_spi 98c000.spi: spi master firmware load failed ret: -517\n"
    other = "<3>[ 3.2] qcom-ice 1d88000.crypto: probe with driver qcom-ice failed with error -95\n"
    run = lambda text: subprocess.run(["sh", "-c", cmd.replace("cat /dev/stdin", "printf %s '" + text + "'")],
                                      capture_output=True, text=True).returncode
    assert run(known) == 0 and run(known + other) != 0
    with pytest.raises(ValueError):
        jobs.errors_command(["it's"])


@pytest.mark.parametrize("bad", [["a(", "b)"], [r"(x)\1"]])
def test_known_error_patterns_must_stand_alone(bad):
    """Joined as a|b, "a(" and "b)" would make the valid "a(|b)" and drop
    every line with an "a"; a back-reference would point into another
    entry. Both are refused."""
    with pytest.raises(ValueError, match="known-error pattern"):
        jobs.errors_command(bad)


def run_errors(cmd, dmesg):
    """Run an errors_command with dmesg -r replaced by the given text."""
    import subprocess
    return subprocess.run(["sh", "-c", cmd.replace("dmesg -r", "cat " + str(dmesg))],
                          capture_output=True, text=True)


# What is left of those lines once the known errors are gone: genuine
# kernel errors, one entry per distinct message with its count.
REAL_ERRORS = {
    "stock": [("qcom-smem smem: Found an unknown type of DRAM info struct", 1),
              ("ufshcd-qcom 1d84000.ufshc: ufshcd_is_wb_buf_lifetime_available", 1),
              ("qcom_pmic_glink pmic-glink: Failed to create device link", 3),
              ("Bluetooth: hci0: unexpected event for opcode 0xfc48", 1)],
    "open": [("qcom_scm firmware:scm: qseecom: scm call failed with error -5", 1),
             ("qcom-smem smem: Found an unknown type of DRAM info struct", 1),
             ("qcomtee: QTEE returned with -22.", 1),
             ("probe with driver qcom-ice failed with error -95", 2),
             ("qcom_pmic_glink pmic-glink: Failed to create device link", 3),
             ("lt9611uxc 0-002b: wait for EDID timeout", 4),
             ("Bluetooth: hci0: command 0xfc00 tx timeout", 1),
             ("Bluetooth: hci0: Reading QCA version information failed (-110)", 1)],
}


@pytest.mark.parametrize("stack", ["stock", "open"])
def test_known_errors_on_real_rb3gen2_lines(stack):
    """The level 0-3 lines of linux-next next-20261023 on the RB3 Gen 2
    (LAVA 509892 #L3137-3186 stock, 509899 #L2920-2969 open): the known
    missing-firmware lines go, every other line is printed and fails."""
    import datetime
    data = os.path.join(os.path.dirname(__file__), "data", "dmesg", "rb3gen2-next-20261023-%s.txt" % stack)
    cmd = jobs.errors_command(jobs.known_errors("rb3gen2", datetime.date(2026, 10, 25)))
    r = run_errors(cmd, data)
    out = r.stdout.splitlines()
    assert r.returncode != 0
    assert len(out) == sum(n for _, n in REAL_ERRORS[stack])
    for msg, n in REAL_ERRORS[stack]:
        assert sum(msg in line for line in out) == n, msg
    assert run_errors(cmd, "/dev/null").returncode == 0


def test_a_known_error_grep_cannot_parse_fails_the_check():
    """Python accepts "[[:digits:]]"; grep exits 2 on it and prints
    nothing, which must not read as "no errors left"."""
    data = os.path.join(os.path.dirname(__file__), "data", "dmesg", "rb3gen2-next-20261023-stock.txt")
    assert run_errors(jobs.errors_command(["[[:digits:]]"]), data).returncode != 0


def test_smoke_lines_fit_the_shell_with_every_known_error():
    """LAVA 512816 #L3016: with the three known-error entries the
    dmesg-errors line was 1131 characters and BusyBox cut it at 1022."""
    import datetime
    b = config.board("rb3gen2")
    step = lava_jobs.shell_checks("smoke", jobs.smoke_checks(b, "next-20261023", datetime.date(2026, 10, 25)))
    cmds = {s["name"]: s["command"] for s in step["test"]["interactive"][0]["script"]}
    assert cmds["dmesg-errors"].count("dmesg -r") == 1
    assert max(len(c) for c in cmds.values()) <= lava_jobs.SHELL_LINE_MAX


def test_job_names_say_downstream_firmware():
    assert jobs.render("uno-q", "stock", "ubci-9", PKG, LINUX)["job_name"] == \
        "u-boot-ci uno-q downstream ubci-9"
    assert jobs.render("uno-q", "stock-candidate", "f", PKG, LINUX)["job_name"].startswith(
        "u-boot-ci uno-q downstream-candidate ")
    assert jobs.stack_label("open") == "open"
