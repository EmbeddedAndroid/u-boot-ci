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
    assert gate["expected"] == ["bl2_v", "bl31_v", "op_tee_version", "u_boot_20"]
    bl2 = config.board(board)["pins"]["bl2"]["fingerprint"]
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
