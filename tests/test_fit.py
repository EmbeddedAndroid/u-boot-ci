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


def test_the_configuration_is_the_one_the_qcom_spl_selects(board):
    # mach-snapdragon board_fit_config_name_match() takes "post-ddr" once
    # DRAM is up; the default is the same configuration for other SPLs.
    text = fit.its("x", "a", "t", "u", "d")
    conf = re.search(r"conf-1 \{(.*?)\};", text, re.S).group(1)
    assert 'description = "post-ddr";' in conf
    assert 'default = "conf-1";' in text and "pre-ddr" not in text


BLOBS = [{"name": "shrm", "file": "shrm.elf", "description": "SHRM", "load": "0xC00000", "entry": "0xC00000",
          "sha256": "0" * 64},
         {"name": "qclib", "file": "QcLib.elf", "description": "QcLib", "load": "0x0C2C3800",
          "entry": "0x0C2C5270", "sha256": "1" * 64}]


def test_a_board_whose_spl_trains_ddr_gets_a_pre_ddr_configuration(board, tmp_path):
    board["spl"] = {"pre_ddr": BLOBS}
    for b in BLOBS:
        (tmp_path / b["file"]).write_text(b["name"])
    text = fit.its("x", "a", "t", "u", "d", str(tmp_path))
    pre = re.search(r"conf-pre-ddr \{(.*?)\};", text, re.S).group(1)
    assert 'description = "pre-ddr";' in pre and 'loadables = "shrm", "qclib";' in pre
    q = re.search(r"qclib \{(.*?)\};", text, re.S).group(1)
    assert "load = <0x0C2C3800>;" in q and "entry = <0x0C2C5270>;" in q
    assert '/incbin/("%s")' % (tmp_path / "QcLib.elf") in q
    # The post-ddr configuration stays the default, BL31 first.
    assert re.search(r'conf-1 \{\s*description = "post-ddr";\s*firmware = "atf";', text)


def test_pre_ddr_blobs_must_be_given_and_present(board, tmp_path):
    board["spl"] = {"pre_ddr": BLOBS}
    with pytest.raises(SystemExit, match="needs its pre-ddr blobs"):
        fit.its("x", "a", "t", "u", "d")
    (tmp_path / "shrm.elf").write_text("shrm")
    with pytest.raises(SystemExit, match="pre-ddr blob QcLib.elf missing"):
        fit.its("x", "a", "t", "u", "d", str(tmp_path))
