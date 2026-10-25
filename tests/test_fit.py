"""ubci.fit: the FIT U-Boot SPL loads on an SPL boot chain."""
import copy
import re

import pytest

from ubci import config, fit

ADDR = {"atf": "0x1c200000", "optee": "0x1c300000", "uboot": "0xaf000000"}


@pytest.fixture
def board(monkeypatch):
    b = copy.deepcopy(config.board("rb3gen2"))
    b["pins"]["tf-a"]["fit"] = dict(ADDR)
    monkeypatch.setattr(config, "board", lambda name: b)
    return b


def test_its_uses_the_pinned_load_addresses(board):
    text = fit.its("x", "/b/bl31.bin", "/b/tee-raw.bin", "/b/u-boot.bin", "/b/u-boot.dtb")
    atf = re.search(r"atf \{.*?load = <([^>]+)>", text, re.S).group(1)
    tee = re.search(r"optee \{.*?load = <([^>]+)>", text, re.S).group(1)
    ub = re.search(r"uboot \{.*?load = <([^>]+)>", text, re.S).group(1)
    assert (atf, tee, ub) == (ADDR["atf"], ADDR["optee"], ADDR["uboot"])
    assert '/incbin/("/b/bl31.bin")' in text and '/incbin/("/b/u-boot.dtb")' in text
    assert 'firmware = "atf";' in text and 'loadables = "uboot", "optee";' in text


def test_bad_inputs_are_refused(board):
    with pytest.raises(SystemExit, match="quote"):
        fit.its("x", 'a"b', "t", "u", "d")
    board["pins"]["tf-a"]["fit"]["atf"] = "0xzz"
    with pytest.raises(ValueError):
        fit.its("x", "a", "t", "u", "d")


def test_a_board_without_a_fit_pin_has_no_its():
    with pytest.raises(KeyError):
        fit.its("rb3gen2", "a", "t", "u", "d")
