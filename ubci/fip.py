"""A TF-A FIP and its fip.elf wrapper without the TF-A tree or a
toolchain, for the submit job (Python only): fiptool's TOC layout with
no alignment, and the single-segment ELF tools/qti/generate_fip_elf.sh
links, before qtestsign signs it.

python3 -m ubci.fip unpack <fip.bin> <dir>
    writes bl31.bin, tee.bin, bl33.bin (the images the open stack uses)"""
import os
import struct
import sys

TOC_NAME = 0xAA640001
TOC_SERIAL = 0x12345678
# fiptool's UUIDs, as the bytes it writes.
UUIDS = {
    "bl31": bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00"),
    "bl32": bytes.fromhex("05d0e18953dc13478d2b500a4b7a3e38"),
    "bl33": bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4"),
}
ORDER = ("bl31", "bl32", "bl33")
ENTRY = struct.Struct("<16sQQQ")


def build(images):
    """images: {"bl31": bytes, "bl32": bytes, "bl33": bytes} -> fip.bin."""
    names = [n for n in ORDER if n in images]
    if set(images) - set(names):
        raise ValueError("unknown FIP images %s" % sorted(set(images) - set(names)))
    off = 16 + ENTRY.size * (len(names) + 1)
    toc, data = [struct.pack("<IIQ", TOC_NAME, TOC_SERIAL, 0)], []
    for n in names:
        toc.append(ENTRY.pack(UUIDS[n], off, len(images[n]), 0))
        data.append(images[n])
        off += len(images[n])
    toc.append(ENTRY.pack(bytes(16), off, 0, 0))
    return b"".join(toc + data)


def parse(fip):
    name, serial, _ = struct.unpack_from("<IIQ", fip, 0)
    if (name, serial) != (TOC_NAME, TOC_SERIAL):
        raise ValueError("not a FIP")
    by_uuid = {v: k for k, v in UUIDS.items()}
    out, o = {}, 16
    while True:
        u, off, size, _ = ENTRY.unpack_from(fip, o)
        o += ENTRY.size
        if u == bytes(16):
            return out
        if off + size > len(fip):
            raise ValueError("FIP entry beyond the end")
        out[by_uuid.get(u, u.hex())] = fip[off:off + size]


def elf(payload, addr, align=0x10000):
    """An ELF64 AArch64 executable of one PT_LOAD at addr, entry addr."""
    ehsize, phsize = 64, 56
    hdr = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(8)
    hdr += struct.pack("<HHIQQQIHHHHHH", 2, 183, 1, addr, ehsize, 0, 0,
                       ehsize, phsize, 1, 64, 0, 0)
    ph = struct.pack("<IIQQQQQQ", 1, 6, align, addr, addr, len(payload), len(payload), align)
    head = hdr + ph
    return head + bytes(align - len(head)) + payload


if __name__ == "__main__":
    if sys.argv[1:2] != ["unpack"] or len(sys.argv) != 4:
        raise SystemExit(__doc__)
    imgs = parse(open(sys.argv[2], "rb").read())
    os.makedirs(sys.argv[3], exist_ok=True)
    for n, f in (("bl31", "bl31.bin"), ("bl32", "tee.bin"), ("bl33", "bl33.bin")):
        if n in imgs:
            open(os.path.join(sys.argv[3], f), "wb").write(imgs[n])
