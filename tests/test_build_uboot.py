"""scripts/build-uboot.sh against a stand-in make: a tree without the
in-tree u-boot.mbn rule (master at v2026.07) gets its u-boot.elf signed
with qtestsign, as its board docs say; a tree with the rule does not."""
import hashlib
import json
import os
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MBN_RULE = "u-boot.mbn: u-boot.bin FORCE\n\t$(call if_changed,mkmbn)\n"

MAKE = r"""#!/bin/bash
src= o= lv=
while [ $# -gt 0 ]; do
	case $1 in -C) src=$2; shift ;; O=*) o=${1#O=} ;; LOCALVERSION=*) lv=${1#LOCALVERSION=} ;; esac
	shift
done
if [ -z "$lv" ]; then echo "CONFIG_ARM=y" >"$o/.config"; exit 0; fi
for f in u-boot u-boot.elf u-boot.bin u-boot-nodtb.bin; do echo "U-Boot 2026.07$lv" >"$o/$f"; done
echo "control dtb" >"$o/u-boot.dtb"
if [ -n "${STUB_NODTB_WITHOUT_FP:-}" ]; then echo "U-Boot 2026.07" >"$o/u-boot-nodtb.bin"; fi
if [ -z "${STUB_NO_SPL:-}" ]; then
	mkdir -p "$o/spl"
	echo "U-Boot SPL 2026.07${STUB_SPL_LV-$lv}" >"$o/spl/u-boot-spl.elf"
fi
if grep -qs '^u-boot\.mbn:' "$src/board/qualcomm/config.mk"; then
	{ echo "in-tree mbn"; cat "$o/u-boot.elf"; } >"$o/u-boot.mbn"
fi
"""

SWIV = r"""import sys
open(sys.argv[0] + ".calls", "a").write(" ".join(sys.argv[1:]) + "\n")
open(sys.argv[1], "w").write("swiv " + sys.argv[3] + "\n" + open(sys.argv[2]).read())
"""

QTESTSIGN = r"""import sys
open(sys.argv[0] + ".calls", "a").write(" ".join(sys.argv[1:]) + "\n")
out = sys.argv[sys.argv.index("-o") + 1]
open(out, "w").write("qtestsign\n" + open(sys.argv[-1]).read())
"""


@pytest.fixture
def build(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "make").write_text(MAKE)
    (bin_ / "make").chmod(0o755)
    qts = tmp_path / "qtestsign.py"
    qts.write_text(QTESTSIGN)
    swiv = tmp_path / "swiv.py"
    swiv.write_text(SWIV)

    def go(rule, board="rb3gen2", stack="stock", env_extra=None):
        src = tmp_path / "u-boot"
        (src / "configs").mkdir(parents=True, exist_ok=True)
        for c in ("qcm6490_defconfig", "qcom_defconfig", "tfa-optee.config", "qcom_lemans_spl_defconfig"):
            (src / "configs" / c).write_text("\n")
        (src / "board" / "qualcomm").mkdir(parents=True, exist_ok=True)
        (src / "board" / "qualcomm" / "config.mk").write_text(
            "CMD_MKMBN = mkmbn.py\n" + (MBN_RULE if rule else ""))
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@e",
                        "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        out = tmp_path / "out"
        env = dict(os.environ, PATH="%s:%s" % (bin_, os.environ["PATH"]),
                   UBCI_WORK=str(tmp_path / "work"), UBCI_QTESTSIGN=str(qts), UBCI_SWIV=str(swiv),
                   **(env_extra or {}))
        p = subprocess.run([os.path.join(REPO, "scripts", "build-uboot.sh"), str(src), board, stack,
                            "ubci-t-%s-%s" % (stack, board), str(out)],
                           env=env, capture_output=True, text=True)
        calls = [c for f in ("swiv.py.calls", "qtestsign.py.calls") if (tmp_path / f).exists()
                 for c in (tmp_path / f).read_text().splitlines()]
        return p, out, calls
    go.tmp = tmp_path
    return go


def test_a_tree_without_the_mbn_rule_signs_the_elf_with_qtestsign(build):
    p, out, calls = build(rule=False)
    assert p.returncode == 0, p.stderr
    elf = build.tmp / "work" / "u-boot-build" / "rb3gen2-stock" / "u-boot.elf"
    mbn = build.tmp / "work" / "u-boot-build" / "rb3gen2-stock" / "u-boot.mbn"
    assert calls == ["-v6 aboot -o %s %s" % (mbn, elf)]
    assert (out / "u-boot.mbn").read_text() == "qtestsign\nU-Boot 2026.07-ubci-t-stock-rb3gen2\n"


def test_a_tree_with_the_mbn_rule_uses_its_own(build):
    p, out, calls = build(rule=True)
    assert p.returncode == 0, p.stderr
    assert calls == []
    assert (out / "u-boot.mbn").read_text().startswith("in-tree mbn\n")


def test_the_open_stack_never_signs_u_boot(build):
    p, out, calls = build(rule=False, stack="open")
    assert p.returncode == 0, p.stderr
    assert calls == [] and (out / "u-boot.bin").exists()


def test_abl_chainload_builds_an_android_boot_image(build):
    import zlib
    from ubci import bootimg
    p, out, calls = build(rule=False, board="uno-q")
    assert p.returncode == 0, p.stderr
    assert calls == [] and not (out / "u-boot.mbn").exists()
    img = (out / "boot.img").read_bytes()
    h = bootimg.parse(img)
    assert h["kernel_addr"] == 0x80008000 and h["page_size"] == 4096
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    assert d.decompress(img[4096:4096 + h["kernel_size"]]) == b"U-Boot 2026.07-ubci-t-stock-uno-q\n"
    assert d.unused_data == (out / "u-boot.dtb").read_bytes() == b"control dtb\n"


def test_a_boot_image_without_the_fingerprint_fails(build):
    p, out, calls = build(rule=False, board="uno-q", env_extra={"STUB_NODTB_WITHOUT_FP": "1"})
    assert p.returncode != 0 and "u-boot-nodtb.bin lacks the fingerprint" in p.stderr
    assert not (out / "boot.img").exists()


def test_spl_stack_signs_the_swiv_annotated_spl_for_its_slot(build):
    p, out, calls = build(rule=True, board="lemans-evk", stack="spl")
    assert p.returncode == 0, p.stderr
    b = build.tmp / "work" / "u-boot-build" / "lemans-evk-spl"
    swiv = b / "u-boot-spl-swiv.elf"
    assert calls == ["%s %s lemans" % (swiv, b / "spl" / "u-boot-spl.elf"),
                     "-v6 tz -o %s %s" % (out / "spl.mbn", swiv)]
    assert (out / "spl.mbn").read_text() == "qtestsign\nswiv lemans\nU-Boot SPL 2026.07-ubci-t-spl-lemans-evk\n"
    assert (out / "u-boot.bin").exists()
    meta = json.loads((out / "u-boot.json").read_text())
    assert meta["configs"] == "qcom_lemans_spl_defconfig tfa-optee.config"
    assert meta["spl_sha256"] == hashlib.sha256((out / "spl.mbn").read_bytes()).hexdigest()


def test_other_stacks_record_no_spl(build):
    p, out, _ = build(rule=True)
    assert p.returncode == 0, p.stderr
    assert json.loads((out / "u-boot.json").read_text())["spl_sha256"] is None
    assert not (out / "spl.mbn").exists()


def test_a_config_that_builds_no_spl_elf_fails(build):
    p, out, calls = build(rule=True, board="lemans-evk", stack="spl", env_extra={"STUB_NO_SPL": "1"})
    assert p.returncode != 0 and "no spl/u-boot-spl.elf" in p.stderr
    assert calls == [] and not (out / "spl.mbn").exists()


def test_an_spl_without_the_fingerprint_fails(build):
    p, out, calls = build(rule=True, board="lemans-evk", stack="spl", env_extra={"STUB_SPL_LV": "-other"})
    assert p.returncode != 0 and "spl/u-boot-spl.elf lacks the fingerprint ubci-t-spl-lemans-evk" in p.stderr
    assert calls == [] and not (out / "spl.mbn").exists()


def test_a_board_without_spl_cannot_build_the_spl_stack(build):
    p, out, _ = build(rule=True, stack="spl")
    assert p.returncode != 0 and not (out / "spl.mbn").exists()
