"""U-Boot as an Android boot image (header version 0), the way a board
whose downstream firmware ends in ABL chainloads it: the gzipped
u-boot-nodtb.bin with the board DTB appended as the kernel and an empty
ramdisk (doc/board/qualcomm/board.rst, meta-qcom-arduino
u-boot-arduino_git.bb).

python3 -m ubci.bootimg <u-boot-nodtb.bin> <dtb> <out> [--base B] [--pagesize P] [--cmdline C]
"""
import argparse
import gzip
import hashlib
import struct

MAGIC = b"ANDROID!"
KERNEL_OFFSET = 0x00008000
RAMDISK_OFFSET = 0x01000000
TAGS_OFFSET = 0x00000100


def _pad(data, page):
    return data + b"\0" * (-len(data) % page)


def build(kernel, base=0x80000000, pagesize=4096, cmdline=b"root=/dev/notreal", ramdisk=b""):
    """The image bytes, as skales mkbootimg writes them: an empty section
    gets load address 0, and the id is the SHA-1 over each section
    followed by its size."""
    if len(cmdline) >= 512:
        raise ValueError("command line longer than 511 bytes")
    sha = hashlib.sha1()
    for part in (kernel, ramdisk, b""):
        sha.update(part)
        sha.update(struct.pack("<I", len(part)))
    header = struct.pack("<8s10I16s512s32s1024s", MAGIC,
                         len(kernel), base + KERNEL_OFFSET,
                         len(ramdisk), base + RAMDISK_OFFSET if ramdisk else 0,
                         0, 0,
                         base + TAGS_OFFSET, pagesize, 0, 0,
                         b"", cmdline, sha.digest(), b"")
    return _pad(header, pagesize) + _pad(kernel, pagesize) + (_pad(ramdisk, pagesize) if ramdisk else b"")


def uboot_kernel(nodtb, dtb):
    """gzip(u-boot-nodtb.bin) + DTB, the kernel ABL loads and hands the
    appended DTB to. mtime 0 keeps the image reproducible."""
    return gzip.compress(nodtb, mtime=0) + dtb


def parse(image):
    """Header fields of an image (for checks and tests)."""
    f = struct.unpack_from("<8s10I16s512s32s", image)
    if f[0] != MAGIC:
        raise ValueError("not an Android boot image")
    return {"kernel_size": f[1], "kernel_addr": f[2], "ramdisk_size": f[3], "page_size": f[8],
            "header_version": f[9], "cmdline": f[12].rstrip(b"\0"), "id": f[13][:20]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ubci.bootimg")
    ap.add_argument("nodtb")
    ap.add_argument("dtb")
    ap.add_argument("out")
    ap.add_argument("--base", type=lambda x: int(x, 0), default=0x80000000)
    ap.add_argument("--pagesize", type=int, default=4096)
    ap.add_argument("--cmdline", default="root=/dev/notreal")
    a = ap.parse_args(argv)
    kernel = uboot_kernel(open(a.nodtb, "rb").read(), open(a.dtb, "rb").read())
    open(a.out, "wb").write(build(kernel, a.base, a.pagesize, a.cmdline.encode()))


if __name__ == "__main__":
    main()
