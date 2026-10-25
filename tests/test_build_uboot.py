"""scripts/build-uboot.sh against a stand-in make: a tree without the
in-tree u-boot.mbn rule (master at v2026.07) gets its u-boot.elf signed
with qtestsign, as its board docs say; a tree with the rule does not."""
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
if grep -qs '^u-boot\.mbn:' "$src/board/qualcomm/config.mk"; then
	{ echo "in-tree mbn"; cat "$o/u-boot.elf"; } >"$o/u-boot.mbn"
fi
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

    def go(rule, board="rb3gen2", stack="stock"):
        src = tmp_path / "u-boot"
        (src / "configs").mkdir(parents=True, exist_ok=True)
        for c in ("qcm6490_defconfig", "qcom_defconfig", "tfa-optee.config"):
            (src / "configs" / c).write_text("\n")
        (src / "board" / "qualcomm").mkdir(parents=True, exist_ok=True)
        (src / "board" / "qualcomm" / "config.mk").write_text(
            "CMD_MKMBN = mkmbn.py\n" + (MBN_RULE if rule else ""))
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@e",
                        "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        out = tmp_path / "out"
        env = dict(os.environ, PATH="%s:%s" % (bin_, os.environ["PATH"]),
                   UBCI_WORK=str(tmp_path / "work"), UBCI_QTESTSIGN=str(qts))
        p = subprocess.run([os.path.join(REPO, "scripts", "build-uboot.sh"), str(src), board, stack,
                            "ubci-t-%s-%s" % (stack, board), str(out)],
                           env=env, capture_output=True, text=True)
        calls = (tmp_path / "qtestsign.py.calls")
        return p, out, calls.read_text().splitlines() if calls.exists() else []
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

