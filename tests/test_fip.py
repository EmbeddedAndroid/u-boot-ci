"""ubci.fip: the FIP and fip.elf the submit job builds for a private open
stack. Checked against fiptool's layout here; byte-identical to the
fiptool + ld + qtestsign output of a gated build (docs/private-firmware.md)."""
import os
import struct

import pytest

from ubci import fip

IMAGES = {"bl31": b"B" * 5, "bl32": b"T" * 7, "bl33": b"U" * 3}


def test_build_writes_fiptools_toc_without_alignment():
    f = fip.build(IMAGES)
    assert struct.unpack_from("<IIQ", f, 0) == (0xAA640001, 0x12345678, 0)
    head = 16 + 40 * 4
    entries = [struct.unpack_from("<16sQQQ", f, 16 + 40 * i) for i in range(4)]
    assert [e[0] for e in entries] == [fip.UUIDS["bl31"], fip.UUIDS["bl32"], fip.UUIDS["bl33"], bytes(16)]
    assert [(e[1], e[2]) for e in entries] == [(head, 5), (head + 5, 7), (head + 12, 3), (head + 15, 0)]
    assert f[head:] == b"B" * 5 + b"T" * 7 + b"U" * 3


def test_parse_round_trips_and_refuses_what_is_not_a_fip():
    assert fip.parse(fip.build(IMAGES)) == IMAGES
    with pytest.raises(ValueError, match="not a FIP"):
        fip.parse(b"\0" * 64)
    broken = bytearray(fip.build(IMAGES))
    struct.pack_into("<Q", broken, 16 + 24, 1 << 20)
    with pytest.raises(ValueError, match="beyond the end"):
        fip.parse(bytes(broken))


def test_build_refuses_an_image_it_has_no_uuid_for():
    with pytest.raises(ValueError, match="unknown FIP images"):
        fip.build(dict(IMAGES, bl2=b"x"))


def test_elf_is_one_load_segment_at_the_address():
    payload = b"P" * 100
    e = fip.elf(payload, 0xC6800000)
    assert e[:4] == b"\x7fELF" and e[4] == 2
    etype, machine, _, entry, phoff = struct.unpack_from("<HHIQQ", e, 16)
    assert (etype, machine, entry, phoff) == (2, 183, 0xC6800000, 64)
    assert struct.unpack_from("<H", e, 56)[0] == 1
    ptype, flags, off, va, pa, fsz, msz, align = struct.unpack_from("<IIQQQQQQ", e, 64)
    assert (ptype, off, va, pa, fsz, msz, align) == (1, 0x10000, 0xC6800000, 0xC6800000, 100, 100, 0x10000)
    assert e[off:] == payload


def test_build_matches_fiptool():
    # tests/data/fip/fiptool.bin: TF-A 5fe94c0a7356's fiptool create
    # --soc-fw --tos-fw --nt-fw of these three images.
    golden = open(os.path.join(os.path.dirname(__file__), "data", "fip", "fiptool.bin"), "rb").read()
    assert fip.build(GOLDEN) == golden


# The images of tests/data/fip/fiptool.bin.
GOLDEN = {"bl31": b"B" * 37, "bl32": b"T" * 53, "bl33": b"U" * 29}
# sha256 of qtestsign -v7 uefi over generate_fip_elf.sh's ld output for
# that FIP at 0xa7000000 (TF-A 5fe94c0a7356, qtestsign 0eef3b552b1a).
GOLDEN_SIGNED = "f945962e716fdaeb287485cc1d953f77063f49f52a0a0a0e1b3f383f28df4d04"
