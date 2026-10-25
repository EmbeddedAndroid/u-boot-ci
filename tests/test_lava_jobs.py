import re

import pytest
import yaml

from fwci import lava_jobs as lj


def test_case_name_matches_lava_normalisation():
    assert lj.case_name("OP-TEE version") == "op_tee_version"
    assert lj.case_name("U-Boot 20") == "u_boot_20"
    assert lj.case_name("BL2: v") == "bl2_v"


def gate():
    return lj.fingerprint_gate("fp", "SBL1, End", "DRAM:",
                               {"BL31: v": "run-1", "U-Boot 20": "run-1", "BL2: v": "pin-7"})["test"]["monitors"][0]


def match(m, line):
    r = re.search(m["pattern"], line)
    return (lj.case_name(r.group("test_case_id")), m["fixupdict"].get(r.group("result"))) if r else None


def test_gate_passes_banner_with_its_fingerprint():
    m = gate()
    assert match(m, "NOTICE:  BL31: v2.13.0(release):run-1") == ("bl31_v", "pass")
    assert match(m, "U-Boot 2026.10-00012-gabc-run-1 (Oct 24 2026)") == ("u_boot_20", "pass")
    assert match(m, "NOTICE:  BL2: v2.13.0(release):pin-7") == ("bl2_v", "pass")
    assert m["expected"] == ["bl31_v", "u_boot_20", "bl2_v"]
    assert (m["start"], m["end"]) == ("SBL1, End", "DRAM:")


def test_gate_rejects_stale_or_crossed_fingerprints():
    m = gate()
    assert match(m, "U-Boot 2026.10-00012-gabc-run-0 (Oct 23 2026)") is None
    # BL2 must carry the pinned fingerprint, not the run's
    assert match(m, "NOTICE:  BL2: v2.13.0(release):run-1") is None
    assert match(m, "NOTICE:  BL31: v2.13.0(release):pin-7") is None


def test_gate_rejects_a_longer_fingerprint():
    m = gate()
    assert match(m, "NOTICE:  BL31: v2.13.0(release):run-10") is None
    assert match(m, "U-Boot 2026.10-run-12-00634-gabc (Oct 24 2026)") is None
    # U-Boot appends -<commits>-g<sha> after its LOCALVERSION
    assert match(m, "U-Boot 2026.10-run-1-00634-gabc (Oct 24 2026)") == ("u_boot_20", "pass")


def test_shell_check_echo_never_matches_its_own_verdict():
    step = lj.shell_checks("smoke", [("usb", "ls /sys/bus/usb/devices | grep -q usb1")])
    block = step["test"]["interactive"][0]
    s = block["script"][0]
    ok, bad = s["successes"][0]["message"], s["failures"][0]["message"]
    assert not re.search(ok, s["command"]) and not re.search(bad, s["command"])
    # the steps never wait for a shell prompt, only for the end marker
    assert block["prompts"] == [lj.END_MARK] and lj.END_MARK not in s["command"]
    assert not re.search(block["prompts"][0], "pci 0000:00:00.0: PME# supported from D0 # ")
    assert re.search(ok, "@@ usb pass @@") and re.search(bad, "@@ usb fail @@")
    assert not re.search(ok, "@@ usb fail @@")


def test_shell_check_refuses_a_line_the_shell_would_cut():
    """LAVA 512816 #L3016: BusyBox echoed 1022 of the 1131 characters of
    the dmesg-errors line and waited in an open quote until the job timed
    out; such a line must fail at render time."""
    wrap = len(lj.shell_checks("s", [("c", "")])["test"]["interactive"][0]["script"][0]["command"])
    fits = "x" * (lj.SHELL_LINE_MAX - wrap)
    assert lj.shell_checks("s", [("c", fits)])
    with pytest.raises(ValueError, match="shell check c: 1023 characters"):
        lj.shell_checks("s", [("c", fits + "x")])


def test_deploy_uses_token_name_header_and_yaml_round_trip():
    d = lj.deploy_qdl("https://x/a.tar.gz", "lava-mcp-artifact-1")
    assert d["deploy"]["qcomflash"]["headers"] == {"Authorization": "lava-mcp-artifact-1"}
    job = lj.job("dt", "n" * 300, [d, lj.power_on()], {"k": "v"})
    assert len(job["job_name"]) == 200 and job["priority"] == "low" and job["visibility"] == "public"
    assert yaml.safe_load(lj.to_yaml(job)) == job


def test_interactive_wait_step_sends_nothing():
    s = lj.interactive("u", ["=> "], [{"name": "wait", "command": None}])
    assert s["test"]["interactive"][0]["script"][0]["command"] is None
    assert "successes" not in s["test"]["interactive"][0]["script"][0]
