import os
import shutil
import zipfile

import pytest

from ubci import package


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
@pytest.mark.parametrize("board", ["rb3gen2", "ventuno-q"])
def test_partition_layout_has_the_partitions_the_jobs_flash(board, tmp_path):
    from ubci import config
    b = config.board(board)
    package.partitions(b["stock"]["partitions"], str(tmp_path))
    names = os.listdir(tmp_path)
    for lun in b["lava"]["luns"]:
        assert "rawprogram%d.xml" % lun in names and "patch%d.xml" % lun in names
    text = "".join(open(tmp_path / f).read() for f in names if f.startswith("rawprogram") and "_" not in f)
    for f in ("uefi.elf", "tz.mbn", "xbl.elf", "efi.bin", "cdt.bin"):
        assert 'filename="%s"' % f in text
