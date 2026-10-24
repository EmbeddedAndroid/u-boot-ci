import hashlib

import pytest

from ubci import fetch


def test_staged_pin_is_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "WORK", str(tmp_path))
    (tmp_path / "pins").mkdir()
    (tmp_path / "pins" / "tz.mbn").write_bytes(b"bl2")
    good = hashlib.sha256(b"bl2").hexdigest()
    assert fetch.fetch(None, good, "tz.mbn").endswith("pins/tz.mbn")
    with pytest.raises(SystemExit, match="pinned"):
        fetch.fetch(None, "0" * 64, "tz.mbn")
    with pytest.raises(SystemExit, match="no sha256"):
        fetch.fetch(None, None, "tz.mbn")
    with pytest.raises(SystemExit, match="not staged"):
        fetch.fetch(None, good, "other.mbn")


def test_resolve_configs(tmp_path):
    from ubci import config
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "qcom_qcs8300_defconfig").write_text("")
    (tmp_path / "board" / "qualcomm").mkdir(parents=True)
    (tmp_path / "board" / "qualcomm" / "tfa-optee.config").write_text("")
    assert config.resolve_configs(["qcom_monaco_defconfig|qcom_qcs8300_defconfig", "tfa-optee.config",
                                   "arduino-ventuno-q.config?"], str(tmp_path)) == \
        ["qcom_qcs8300_defconfig", "tfa-optee.config"]
    (tmp_path / "configs" / "qcom_monaco_defconfig").write_text("")
    assert config.resolve_configs(["qcom_monaco_defconfig|qcom_qcs8300_defconfig"], str(tmp_path)) == \
        ["qcom_monaco_defconfig"]
    with pytest.raises(SystemExit):
        config.resolve_configs(["missing_defconfig"], str(tmp_path))
