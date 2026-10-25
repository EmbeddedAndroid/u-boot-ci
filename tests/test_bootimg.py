"""ubci.bootimg: U-Boot as the Android boot image ABL chainloads."""
import hashlib
import os
import struct
import zlib

import pytest

from ubci import bootimg


def test_header_matches_skales_mkbootimg():
    kernel = b"k" * 5000
    img = bootimg.build(kernel, base=0x80000000, pagesize=4096)
    h = bootimg.parse(img)
    assert h["kernel_size"] == 5000 and h["kernel_addr"] == 0x80008000
    assert h["ramdisk_size"] == 0 and h["page_size"] == 4096 and h["header_version"] == 0
    assert h["cmdline"] == b"root=/dev/notreal"
    # An empty ramdisk and second stage get load address 0, as the
    # Arduino boot.img meta-qcom-arduino ships has them.
    f = struct.unpack_from("<8s10I", img)
    assert f[4] == 0 and f[6] == 0 and f[7] == 0x80000100
    sha = hashlib.sha1(kernel + struct.pack("<I", 5000) + struct.pack("<I", 0) * 2).digest()
    assert h["id"] == sha
    # Header page, then the kernel padded to whole pages.
    assert len(img) == 4096 + 8192 and img[4096:4096 + 5000] == kernel and set(img[9096:]) == {0}


def test_kernel_is_gzipped_u_boot_with_the_dtb_appended():
    k = bootimg.uboot_kernel(b"U-Boot 2026.10-ubci-1", b"\xd0\x0d\xfe\xeddtb")
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    assert d.decompress(k) == b"U-Boot 2026.10-ubci-1" and d.unused_data == b"\xd0\x0d\xfe\xeddtb"
    assert bootimg.uboot_kernel(b"x", b"y") == bootimg.uboot_kernel(b"x", b"y")


def test_cli_writes_the_image(tmp_path):
    (tmp_path / "nodtb").write_bytes(b"u" * 100)
    (tmp_path / "dtb").write_bytes(b"d" * 10)
    bootimg.main([str(tmp_path / "nodtb"), str(tmp_path / "dtb"), str(tmp_path / "boot.img"),
                  "--base", "0x40000000", "--pagesize", "2048"])
    h = bootimg.parse((tmp_path / "boot.img").read_bytes())
    assert h["kernel_addr"] == 0x40008000 and h["page_size"] == 2048


def test_bad_input_is_refused():
    with pytest.raises(ValueError, match="longer than 511"):
        bootimg.build(b"k", cmdline=b"x" * 512)
    with pytest.raises(ValueError, match="not an Android boot image"):
        bootimg.parse(b"\0" * 2048)


def test_header_is_the_one_the_uno_q_downstream_boot_img_has():
    # First page of boot.img in Arduino's unoq-bootloader-emmc-linux-251020
    # (sha256 c606e95d...), which meta-qcom-arduino's skales mkbootimg
    # made: base 0x80000000, 4 KiB pages, the default command line.
    shipped = open(os.path.join(os.path.dirname(__file__), "data", "bootimg",
                                "unoq-251020-boot.img.header"), "rb").read()
    h = bootimg.parse(shipped)
    ours = bootimg.build(b"\0" * h["kernel_size"])[:4096]
    # Everything but the id, which hashes the kernel, is the same.
    assert ours[:576] == shipped[:576] and ours[608:] == shipped[608:]
