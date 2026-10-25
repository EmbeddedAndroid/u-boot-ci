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
