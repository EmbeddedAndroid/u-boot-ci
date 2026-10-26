"""ubci.config: per-stack downstream firmware, pending pins, the configs
a build used, and why a target cannot be built."""
import copy
import os
import subprocess

import pytest

from ubci import config
from ubci.dryrun import board_tree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_open_stack_on_its_own_downstream_firmware():
    b = copy.deepcopy(config.board("rb3gen2"))
    assert config.downstream(b, "open") is b["downstream"]
    b["downstream_open"] = {"release": "other"}
    assert config.downstream(b, "stock") is b["downstream"]
    assert config.downstream(b, "open") is b["downstream_open"]


def pending_board():
    b = copy.deepcopy(config.board("rb3gen2"))
    b["pins"]["optee"]["pending"] = "not pushed yet"
    return b


def test_pending_pin_names_the_component_and_why():
    b = pending_board()
    assert config.pending(b, "open") == "open-stack pin not public yet: optee %s (not pushed yet)" % (
        b["pins"]["optee"]["commit"][:12])
    assert config.pending(b, "stock") is None
    assert config.pending(config.board("rb3gen2"), "open") is None


def test_missing_board_before_pending_pin(tmp_path, monkeypatch):
    b = pending_board()
    monkeypatch.setattr(config, "board", lambda name: b)
    assert config.missing("rb3gen2", "open", str(tmp_path)).startswith("board not in this base: no qcom/")
    board_tree(str(tmp_path), ["rb3gen2"])
    assert config.missing("rb3gen2", "stock", str(tmp_path)) is None
    assert config.missing("rb3gen2", "open", str(tmp_path)).startswith("open-stack pin not public yet")
    os.remove(os.path.join(str(tmp_path), "configs", "qcm6490_defconfig"))
    assert config.missing("rb3gen2", "stock", str(tmp_path)) == "board not in this base: none of qcm6490_defconfig"


def test_fragments_flags_a_missing_board_fragment():
    entries = ["qcom_defconfig", "tfa-optee.config", "arduino-ventuno-q.config?"]
    got = config.fragments(entries, ["qcom_defconfig", "tfa-optee.config"])
    assert got == [{"name": "qcom_defconfig", "used": True, "optional": False},
                   {"name": "tfa-optee.config", "used": True, "optional": False},
                   {"name": "arduino-ventuno-q.config", "used": False, "optional": True}]
    both = config.fragments(["qcom_monaco_defconfig|qcom_qcs8300_defconfig"], ["qcom_qcs8300_defconfig"])
    assert both == [{"name": "qcom_qcs8300_defconfig", "used": True, "optional": False}]
    assert config.fragments(entries, entries[:2] + ["arduino-ventuno-q.config"])[2]["used"] is True


def cli(*args):
    return subprocess.run(["python3", "-m", "ubci.config"] + list(args), cwd=REPO, capture_output=True,
                          text=True, check=True).stdout.strip()


def test_bootimg_options_for_abl_chainload_only():
    assert cli("bootimg", "uno-q", "stock") == "--base 0x80000000 --pagesize 4096"
    assert cli("bootimg", "rb3gen2", "stock") == ""


@pytest.mark.parametrize("board", config.boards())
def test_every_board_is_complete(board):
    b = config.board(board)
    for stack in config.STACKS:
        if stack not in b["u-boot"]:
            assert stack == "spl" and stack not in b["boot_chain"]
            continue
        assert [s["origin"] for s in b["boot_chain"][stack]][-2:] == ["upstream", "upstream"]
        assert b["boot_chain"][stack][0] == {"stage": "XBL", "origin": "downstream"}
        assert b["u-boot"][stack]["image"]
        d = config.downstream(b, stack)
        assert d["source"] and set(d["source"]) <= set(d["upstream"]["layers"])
        assert all(len(c) == 40 for c in d["source"].values())
    assert "restore" not in b
    for name in ("tf-a", "optee", "bl2"):
        assert b["pins"][name]


def test_lemans_open_stack_takes_the_spl_xblconfig():
    # XBL takes the U-Boot SPL path only with this XBLConfig (LAVA 512763).
    b = config.board("lemans-evk")
    assert config.downstream(b, "open")["xbl_config"] == "xbl_config_spl.elf"
    assert config.downstream(b, "open")["bootbinaries"] == config.downstream(b, "stock")["bootbinaries"]
    assert config.downstream(b, "stock")["xbl_config"] == "xbl_config.elf"


def test_spl_stack_on_the_open_stack_firmware():
    b = config.board("lemans-evk")
    assert config.downstream(b, "spl") is b["downstream_open"]
    rb3 = config.board("rb3gen2")
    assert config.downstream(rb3, "spl") is rb3["downstream"]


@pytest.mark.parametrize("board", config.boards())
def test_spl_section_is_complete(board):
    b = config.board(board)
    if "spl" not in b["u-boot"]:
        return
    spl = b["spl"]
    assert spl["slot"] in ("tz.mbn", "xbl.elf") and spl["sign"] in ("tz", "sbl1")
    assert b["boot_chain"]["spl"][1]["stage"] == "U-Boot SPL"
    assert b["boot_chain"]["spl"][1]["origin"] == "upstream"
    assert b["pins"]["tf-a"]["fit"]
    for s in spl.get("in_flight", []):
        assert s["title"] and "@" in s["message_id"]


@pytest.mark.parametrize("board", [b for b in config.boards() if config.board(b).get("spl")])
def test_spl_is_signed_as_the_image_its_slot_takes(board):
    # XBL takes a TZ image from tz_a; the boot ROM takes an SBL1 image from xbl_a.
    spl = config.board(board)["spl"]
    assert (spl["slot"], spl["sign"]) in (("tz.mbn", "tz"), ("xbl.elf", "sbl1"))


def spl_tree(tmp_path, monkeypatch, pending=False):
    b = copy.deepcopy(config.board("lemans-evk"))
    for name in ("tf-a", "optee"):
        b["pins"][name].pop("pending", None)
    if pending:
        b["pins"]["optee"]["pending"] = "not pushed yet"
    monkeypatch.setattr(config, "board", lambda name: b)
    board_tree(str(tmp_path), ["lemans-evk"])
    return b


def test_no_upstream_spl_names_the_series_in_flight(tmp_path, monkeypatch):
    b = spl_tree(tmp_path, monkeypatch)
    assert config.missing("lemans-evk", "spl", str(tmp_path)) is None
    os.remove(os.path.join(str(tmp_path), "configs", "qcom_lemans_spl_defconfig"))
    why = config.missing("lemans-evk", "spl", str(tmp_path))
    assert why.startswith("no upstream SPL: qcom_lemans_spl_defconfig not in the tree; in flight: ")
    assert "Enable U-Boot SPL support for Lemans EVK v4 <20260928-spl-lemans-v4-0-007635cc4667@" in why
    assert config.missing("lemans-evk", "spl", str(tmp_path), adhoc=True).startswith(
        "no SPL in the tested tree: qcom_lemans_spl_defconfig not in the tree")
    # The other stacks of the board do not care.
    assert config.missing("lemans-evk", "stock", str(tmp_path)) is None
    assert b["spl"]["in_flight"]


def test_a_missing_fragment_is_not_a_missing_spl(tmp_path, monkeypatch):
    spl_tree(tmp_path, monkeypatch)
    os.remove(os.path.join(str(tmp_path), "configs", "tfa-optee.config"))
    assert config.missing("lemans-evk", "spl", str(tmp_path)) == "board not in this base: none of tfa-optee.config"


def test_board_without_spl_support_says_none_is_in_flight(tmp_path):
    board_tree(str(tmp_path), ["rb3gen2"])
    # Nothing was looked for in the tree: it says so, base or stack.
    assert config.missing("rb3gen2", "spl", str(tmp_path)) == (
        "no SPL stack for this board: no SPL in flight for this board")
    assert cli("missing", "rb3gen2", "spl", str(tmp_path), "--adhoc") == (
        "no SPL stack for this board: no SPL in flight for this board")


def test_spl_gaps_are_part_of_the_reason(tmp_path, monkeypatch):
    b = copy.deepcopy(config.board("rb3gen2"))
    b["spl"] = {"gaps": ["no posted SPL enablement"], "in_flight": [
        {"title": "SPL", "version": 2, "message_id": "a@b"}]}
    monkeypatch.setattr(config, "board", lambda name: b)
    assert config.missing("rb3gen2", "spl", str(tmp_path)) == (
        "no SPL stack for this board: no posted SPL enablement; in flight: SPL v2 <a@b>")


def test_spl_stack_waits_for_public_tf_a_and_optee_pins_not_bl2(tmp_path, monkeypatch):
    b = spl_tree(tmp_path, monkeypatch, pending=True)
    assert config.missing("lemans-evk", "spl", str(tmp_path)).startswith("open-stack pin not public yet: optee")
    b["pins"]["optee"].pop("pending")
    b["pins"]["bl2"]["pending"] = "the pinned SPL is not the one under test"
    assert config.missing("lemans-evk", "spl", str(tmp_path)) is None
    assert config.missing("lemans-evk", "open", str(tmp_path)).startswith("open-stack pin not public yet: bl2")


def test_missing_refuses_unknown_flags(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        cli("missing", "rb3gen2", "spl", str(tmp_path), "--nightly")

