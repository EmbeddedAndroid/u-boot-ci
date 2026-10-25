"""ubci.config: per-stack downstream firmware, pending pins, and why a
target cannot be built."""
import copy
import os

from ubci import config
from ubci.dryrun import board_tree


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
