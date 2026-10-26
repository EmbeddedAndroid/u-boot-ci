import hashlib
import os
import shutil
import zipfile

import pytest

from ubci import config, package


def test_unzip_top_flattens_release_directories(tmp_path):
    z = tmp_path / "bb.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("QCM6490_bootbinaries/xbl.elf", "x")
        f.writestr("QCM6490_bootbinaries/sail_nor/rawprogram0.xml", "nested")
        f.writestr("QCM6490_bootbinaries/", "")
    out = tmp_path / "out"
    out.mkdir()
    package.unzip_top(str(z), str(out))
    assert sorted(os.listdir(out)) == ["xbl.elf"]


def test_skip_missing_blanks_only_absent_images(tmp_path):
    (tmp_path / "xbl.elf").write_text("x")
    (tmp_path / "rawprogram0.xml").write_text(
        '<data>\n'
        '<program SECTOR_SIZE_IN_BYTES="4096" filename="xbl.elf" label="xbl_a" start_sector="6"/>\n'
        '<program SECTOR_SIZE_IN_BYTES="4096" filename="dtb.bin" label="dtb_a" start_sector="9"/>\n'
        '<program SECTOR_SIZE_IN_BYTES="4096" filename="" label="ddr_a" start_sector="12"/>\n'
        '</data>\n')
    assert package.skip_missing(str(tmp_path)) == ["dtb_a (dtb.bin)"]
    text = (tmp_path / "rawprogram0.xml").read_text()
    assert 'filename="xbl.elf"' in text and 'filename="dtb.bin"' not in text
    assert text.count('filename=""') == 2


@pytest.mark.skipif(not shutil.which("qcom-ptool"), reason="needs the CI container")
@pytest.mark.parametrize("board,stack", [(b, s) for b in config.boards() for s in config.STACKS
                                         if s in config.board(b)["u-boot"]])
def test_partition_layout_has_the_partitions_the_jobs_flash(board, stack, tmp_path):
    b = config.board(board)
    d = config.downstream(b, stack)
    package.partitions(d["partitions"], str(tmp_path))
    names = os.listdir(tmp_path)
    for lun in b["lava"]["luns"]:
        assert "rawprogram%d.xml" % lun in names and "patch%d.xml" % lun in names
    written = package.written_images(str(tmp_path))
    want = set(d.get("required", package.REQUIRED)) | {package.slot(b, stack), "efi.bin", "tz.mbn"}
    if stack == "spl":
        want.add(b["spl"]["slot"])
    assert want <= written, want - written
    if d.get("cdt"):
        assert "cdt.bin" in written


def fake_board(slot="boot.img"):
    """RB3 Gen 2 as if its downstream firmware ended in ABL (as UNO Q's)."""
    b = config.board("rb3gen2")
    b["u-boot"]["stock"]["slot"] = slot
    d = b["downstream"]
    d.update(bootbinaries=[{"url": "https://x/bb.zip", "sha256": "1" * 64}],
             required=["xbl.elf", "xbl_feature_config.elf", "tz.mbn", "abl.elf"], release="ABL firmware 1")
    del d["cdt"], d["xbl_config"]
    return b


LAYOUT = """<data>
<program filename="xbl.elf" label="xbl_a"/>
<program filename="tz.mbn" label="tz_a"/>
<program filename="abl.elf" label="abl_a"/>
<program filename="xbl_feature_config.elf" label="xbl_config_a"/>
<program filename="boot.img" label="boot_a"/>
<program filename="dtb.bin" label="dtb_a"/>
<program filename="efi.bin" label="efi"/>
</data>
"""


@pytest.fixture
def fake_build(tmp_path, monkeypatch):
    z = tmp_path / "bb.zip"
    with zipfile.ZipFile(z, "w") as f:
        for n in ("xbl.elf", "tz.mbn", "abl.elf", "xbl_feature_config.elf", "boot.img"):
            f.writestr("fw/" + n, "downstream " + n)
        for n in ("rawprogram0.xml", "rawprogram0.nouser.xml"):
            f.writestr("fw/" + n, "<data><program filename=\"../disk.img\" label=\"x\"/></data>")
        f.writestr("fw/gpt_main1.bin", "archive gpt")
    monkeypatch.setattr(package, "WORK", str(tmp_path))
    monkeypatch.setattr(package, "fetch", lambda url, sha, name=None: str(z))

    def go(board, layout=LAYOUT, stack="stock"):
        monkeypatch.setattr(config, "board", lambda name: board)
        monkeypatch.setattr(package, "partitions",
                            lambda lay, d: open(os.path.join(d, "rawprogram0.xml"), "w").write(layout))
        (tmp_path / "uboot.img").write_text("U-Boot under test")
        (tmp_path / "spl.mbn").write_text("U-Boot SPL under test")
        (tmp_path / "efi.bin").write_text("esp")
        out = str(tmp_path / "pkg.tar.gz")
        name, skipped = package.build("rb3gen2", stack, str(tmp_path / "uboot.img"), str(tmp_path / "efi.bin"), out)
        return name, skipped, package.sources(out), out
    return go


def test_abl_chainload_puts_u_boot_in_the_boot_image_slot(fake_build):
    import tarfile
    name, skipped, src, out = fake_build(fake_board())
    assert skipped == ["dtb_a (dtb.bin)"]
    with tarfile.open(out) as t:
        assert t.extractfile(name + "/boot.img").read() == b"U-Boot under test"
        rp = t.extractfile(name + "/rawprogram0.xml").read().decode()
        members = t.getnames()
    # The layout is qcom-ptool's, never the archive's own.
    assert "disk.img" not in rp and 'filename="boot.img"' in rp
    assert name + "/rawprogram0.nouser.xml" not in members and name + "/gpt_main1.bin" not in members
    assert src["components"] == {"downstream": "ABL firmware 1"}


def test_a_layout_that_does_not_write_the_slot_is_refused(fake_build):
    b = fake_board()
    with pytest.raises(SystemExit, match="writes no boot.img"):
        fake_build(b, layout=LAYOUT.replace("boot.img", "other.img"))
    with pytest.raises(SystemExit, match="writes no tz.mbn"):
        fake_build(b, layout=LAYOUT.replace('"tz.mbn"', '"other.mbn"'))


def test_a_package_without_a_required_image_is_refused(fake_build):
    b = fake_board()
    b["downstream"]["required"] = ["xbl.elf", "hyp.mbn"]
    with pytest.raises(SystemExit, match="package lacks hyp.mbn"):
        fake_build(b)


def spl_board(slot="tz.mbn"):
    b = fake_board(slot="uefi.elf")
    b["u-boot"]["spl"] = dict(b["u-boot"]["stock"])
    b["spl"] = {"slot": slot, "sign": "tz"}
    b["pins"]["bl2"]["pending"] = "never used by the spl stack"
    return b


SPL_LAYOUT = LAYOUT.replace("boot.img", "uefi.elf")


@pytest.mark.parametrize("slot", ["tz.mbn", "xbl.elf"])
def test_spl_stack_puts_the_spl_built_here_in_its_slot(fake_build, slot):
    import tarfile
    name, _, src, out = fake_build(spl_board(slot), layout=SPL_LAYOUT, stack="spl")
    with tarfile.open(out) as t:
        assert t.extractfile(name + "/" + slot).read() == b"U-Boot SPL under test"
        assert t.extractfile(name + "/uefi.elf").read() == b"U-Boot under test"
        other = "xbl.elf" if slot == "tz.mbn" else "tz.mbn"
        assert t.extractfile(name + "/" + other).read() == b"downstream " + other.encode()
    # Nothing is deferred: the SPL is not a secret pin.
    assert src["deferred"] == [] and src["components"]["spl"] == slot
    assert "bl2" not in src["components"]


def test_spl_stack_needs_a_layout_that_writes_its_slot(fake_build):
    with pytest.raises(SystemExit, match="writes no xbl.elf"):
        fake_build(spl_board("xbl.elf"), layout=SPL_LAYOUT.replace('"xbl.elf"', '"other.elf"'), stack="spl")


BLOBS = {"QcLib.elf": b"qclib", "shrm.elf": b"shrm"}


def blob_board(files=BLOBS):
    b = spl_board("xbl.elf")
    b["spl"]["pre_ddr"] = [{"name": n.split(".")[0].lower(), "file": n, "load": "0xc00000",
                            "entry": "0xc00000", "description": n,
                            "sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()]
    return b


@pytest.fixture
def blob_zip(tmp_path, monkeypatch):
    def go(files):
        z = tmp_path / "bb.zip"
        with zipfile.ZipFile(z, "w") as f:
            for n, d in files.items():
                f.writestr("fw/" + n, d)
        monkeypatch.setattr(package, "WORK", str(tmp_path))
        monkeypatch.setattr(package, "fetch", lambda url, sha, name=None: str(z))
        return str(tmp_path / "blobs")
    return go


def test_pre_ddr_blobs_come_from_the_downstream_archive_checked(blob_zip, monkeypatch):
    b = blob_board()
    monkeypatch.setattr(config, "board", lambda name: b)
    dest = blob_zip(dict(BLOBS, **{"xbl.elf": b"x"}))
    assert package.blobs("shikra", "spl", dest) == ["QcLib.elf", "shrm.elf"]
    assert sorted(os.listdir(dest)) == ["QcLib.elf", "shrm.elf"]


def test_a_missing_pre_ddr_blob_is_refused(blob_zip, monkeypatch):
    b = blob_board()
    monkeypatch.setattr(config, "board", lambda name: b)
    dest = blob_zip({"QcLib.elf": b"qclib"})
    with pytest.raises(SystemExit, match="lack the pre-ddr blob shrm.elf"):
        package.blobs("shikra", "spl", dest)


def test_a_pre_ddr_blob_with_another_sha256_is_refused(blob_zip, monkeypatch):
    b = blob_board()
    monkeypatch.setattr(config, "board", lambda name: b)
    dest = blob_zip({"QcLib.elf": b"qclib", "shrm.elf": b"other shrm"})
    with pytest.raises(SystemExit, match="pre-ddr blob shrm.elf: sha256"):
        package.blobs("shikra", "spl", dest)
