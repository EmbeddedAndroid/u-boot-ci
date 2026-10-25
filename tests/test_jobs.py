import os
import re

import pytest
import yaml

from fwci import lava_jobs
from ubci import config, jobs

PKG = {"url": "https://lava.example/a/pkg.tar.gz", "token": "lava-mcp-artifact-x", "path": "ubci-b"}
LINUX = {"tag": "next-20261023", "release": "7.3.0-next-20261023", "image_sha256": "5" * 64}
RESTORE = {"url": "https://lab.example/stock.tar.gz", "token": "LAB_TOKEN", "header": "LabAuth",
           "path": "stock"}


def monitors(job):
    return {m["name"]: m for a in job["actions"] if "test" in a for m in a["test"].get("monitors", [])}


@pytest.mark.parametrize("board", config.boards())
def test_open_stack_gate_checks_every_component(board):
    job = jobs.render(board, "open", "ubci-9", PKG, LINUX, RESTORE)
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
    job = jobs.render(board, "stock", "ubci-9", PKG, LINUX, RESTORE)
    assert monitors(job)[jobs.GATE_SUITE]["expected"] == ["u_boot_20"]


def test_linux_version_gate_names_the_tag():
    m = monitors(jobs.render("rb3gen2", "stock", "ubci-9", PKG, LINUX, RESTORE))[jobs.LINUX_SUITE]
    r = re.search(m["pattern"], "[    0.000000] Linux version 7.3.0-next-20261023 (gcc 14)")
    assert r and m["fixupdict"][r.group("result")] == "pass"
    assert not re.search(m["pattern"], "Linux version 7.3.0-next-20261022 (gcc 14)")


def test_job_ends_with_the_stock_restore_and_no_secrets():
    job = jobs.render("ventuno-q", "open", "ubci-9", PKG, LINUX, RESTORE)
    tail = job["actions"][-4:]
    assert tail[0]["deploy"]["qcomflash"] == {"url": RESTORE["url"], "headers": {"LabAuth": "LAB_TOKEN"}}
    assert tail[1]["boot"]["path"] == "stock" and "stock-restore" in monitors({"actions": tail})
    text = lava_jobs.to_yaml(job)
    assert yaml.safe_load(text) == job
    # header values are token names LAVA resolves, never secrets
    assert re.findall(r"(?m)^\s+(?:Authorization|LabAuth): (\S+)$", text) == ["lava-mcp-artifact-x", "LAB_TOKEN"]


def test_uboot_checks_come_from_the_board():
    job = jobs.render("rb3gen2", "stock", "ubci-9", PKG, LINUX, RESTORE)
    steps = [a for a in job["actions"] if "test" in a and "interactive" in a["test"]][0]
    names = [s["name"] for s in steps["test"]["interactive"][0]["script"]]
    assert names[:4] == ["autoboot", "u-boot-prompt", "u-boot-sync", "uboot-version"] and names[-1] == "uboot-reset"
    assert "uboot-storage" in names


def test_unknown_board_is_refused():
    with pytest.raises(SystemExit):
        jobs.render("nope", "stock", "f", PKG, LINUX, RESTORE)


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


def restore_tail(board, stack="stock"):
    job = jobs.render(board, stack, "ubci-9", PKG, LINUX, RESTORE)
    i = max(n for n, a in enumerate(job["actions"]) if "deploy" in a)
    return job["actions"][i:]


@pytest.mark.parametrize("board", ["uno-q", "qcs615-ride", "lemans-evk"])
def test_restore_checks_the_exact_lab_uefi_build(board):
    r = config.board(board)["restore"]
    m = monitors({"actions": restore_tail(board)})[jobs.RESTORE_SUITE]
    assert m["end"] == "UEFI Total" and m["expected"] == ["uefi_ver"]
    line = "UEFI Ver    : " + r["uefi_ver"]
    hit = re.search(m["pattern"], line)
    assert hit and m["fixupdict"][hit.group("result")] == "pass"
    # Any other build, ours or a newer lab image, does not pass.
    other = re.sub(r"\d(?=[^\d]*$)", lambda d: str((int(d.group()) + 1) % 10), r["uefi_ver"])
    assert not re.search(m["pattern"], "UEFI Ver    : " + other)


def test_restore_flashes_the_lab_images_listed_for_the_board(monkeypatch):
    import copy
    b = copy.deepcopy(config.board("rb3gen2"))
    b["restore"].update(pre=[{"subdir": "sail_nor", "storage": "spinor", "luns": [0]}], luns=[0, 1],
                        deploy_minutes=20, qdl_minutes=20, uefi_ver="6.0.1.X-1", end="UEFI Total")
    monkeypatch.setattr(config, "board", lambda name: b)
    tail = restore_tail("rb3gen2")
    boots = [a["boot"] for a in tail if "boot" in a and a["boot"]["method"] == "qdl"]
    assert [(x["path"], x["storage"]) for x in boots] == [("stock/sail_nor", "spinor"), ("stock", "ufs")]
    assert boots[0]["rawprogram"] == "rawprogram0.xml"
    assert boots[1]["rawprogram"].split() == ["rawprogram0.xml", "rawprogram1.xml"]
    assert boots[1]["timeout"] == {"minutes": 20} and tail[0]["deploy"]["timeout"] == {"minutes": 20}
    m = monitors({"actions": tail})[jobs.RESTORE_SUITE]
    assert m["end"] == "UEFI Total" and m["fixupdict"] == {"6.0.1.X-1": "pass"}
    assert re.search(m["pattern"], "UEFI Ver   : 6.0.1.X-1") and not re.search(m["pattern"], "UEFI Ver : 6.0.1.X-2")


def test_a_board_without_an_anchor_keeps_the_uefi_6_check():
    m = monitors({"actions": restore_tail("rb3gen2")})[jobs.RESTORE_SUITE]
    assert m["end"] == "Boot Device" and m["fixupdict"] == {"6.0": "pass"}


def test_job_names_say_downstream_firmware():
    assert jobs.render("uno-q", "stock", "ubci-9", PKG, LINUX, RESTORE)["job_name"] == \
        "u-boot-ci uno-q downstream ubci-9"
    assert jobs.render("uno-q", "stock-candidate", "f", PKG, LINUX, RESTORE)["job_name"].startswith(
        "u-boot-ci uno-q downstream-candidate ")
    assert jobs.stack_label("open") == "open"


def test_lemans_restore_writes_the_sail_nor_before_ufs():
    boots = [a["boot"] for a in restore_tail("lemans-evk") if "boot" in a and a["boot"]["method"] == "qdl"]
    assert [(b["path"], b["storage"]) for b in boots] == [("stock/sail_nor", "spinor"), ("stock", "ufs")]
    assert boots[1]["rawprogram"].split() == ["rawprogram%d.xml" % n for n in range(6)]
