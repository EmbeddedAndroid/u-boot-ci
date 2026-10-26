#!/bin/bash
# build-uboot.sh <u-boot source> <board> <stock|open|spl> <fingerprint> <output dir>
#
# Builds the U-Boot under test for one board and firmware stack with the
# configs and device tree of config/boards/<board>.yaml, with the run's
# fingerprint as LOCALVERSION so the banner on the console names this
# build. Outputs the image the stack flashes (u-boot.<stack>.image:
# u-boot.mbn for the uefi slot, boot.img when ABL chainloads U-Boot as an
# Android boot image, u-boot.bin for the open stack's FIP or the SPL
# FIT), u-boot.elf, the control DTB and the .config. The spl stack also
# builds U-Boot SPL, from the same tree and config, and signs it for the
# slot it replaces as spl.mbn: SWIV-annotated when the board names a
# platform (spl.swiv), then test-signed as spl.sign (tz when XBL loads
# it, sbl1 when the boot ROM does).
# UBCI_QTESTSIGN and UBCI_SWIV replace the pinned qtestsign.py and
# swiv_build_utility.py (tests).
set -euo pipefail
[ $# -eq 5 ] || { sed -n '2p' "$0" >&2; exit 1; }
src=$1 board=$2 stack=$3 fp=$4 out=$5
repo=$(cd "$(dirname "$0")/.." && pwd)
cfg() { (cd "$repo" && python3 -m ubci.config get "$board" "$1"); }
top() { (cd "$repo" && python3 -c "import sys,yaml; print(yaml.safe_load(open('config/pins.yaml'))[sys.argv[1]][sys.argv[2]])" "$1" "$2"); }
case $stack in stock|open|spl) ;; *) echo "stack must be stock, open or spl" >&2; exit 1 ;; esac
case $fp in *[!A-Za-z0-9._-]*|"") echo "bad fingerprint '$fp'" >&2; exit 1 ;; esac

configs=$(cd "$repo" && python3 -m ubci.config configs "$board" "$stack" "$(realpath "$src")")
dt=$(cfg "u-boot.$stack.device_tree")
image=$(cfg "u-boot.$stack.image")
commit=$(git -C "$src" rev-parse HEAD)
build=${UBCI_WORK:-$repo/work}/u-boot-build/$board-$stack
rm -rf "$build"
mkdir -p "$build" "$out"

qtestsign() {
	local qts=${UBCI_QTESTSIGN:-}
	[ -n "$qts" ] || qts=$("$repo/scripts/checkout.sh" qtestsign "$(top qtestsign repo)" "$(top qtestsign commit)")/qtestsign.py
	python3 "$qts" "$@"
}

make -C "$src" -s O="$build" $configs
make -C "$src" -s O="$build" -j"$(nproc)" LOCALVERSION="-$fp" DEVICE_TREE="$dt"
# A tree without the u-boot.mbn rule (board/qualcomm/config.mk; master at
# v2026.07) builds u-boot.elf, and its board docs sign that with qtestsign.
if [ "$image" = u-boot.mbn ] && ! grep -qs '^u-boot\.mbn:' "$src/board/qualcomm/config.mk"; then
	qtestsign -v6 aboot -o "$build/u-boot.mbn" "$build/u-boot.elf"
fi
if [ "$image" = boot.img ]; then
	grep -aq -- "-$fp" "$build/u-boot-nodtb.bin" || { echo "u-boot-nodtb.bin lacks the fingerprint $fp" >&2; exit 1; }
	(cd "$repo" && python3 -m ubci.bootimg "$build/u-boot-nodtb.bin" "$build/u-boot.dtb" "$build/boot.img" \
		$(python3 -m ubci.config bootimg "$board" "$stack"))
else
	grep -aq -- "-$fp" "$build/$image" || { echo "$image lacks the fingerprint $fp" >&2; exit 1; }
fi
if [ "$stack" = spl ]; then
	# CONFIG_SPL_REMAKE_ELF: the SPL as the loadable ELF the boot chain takes.
	elf=$build/spl/u-boot-spl.elf
	[ -f "$elf" ] || { echo "no spl/u-boot-spl.elf: the config builds no SPL ELF (CONFIG_SPL_REMAKE_ELF)" >&2; exit 1; }
	grep -aq -- "-$fp" "$elf" || { echo "spl/u-boot-spl.elf lacks the fingerprint $fp" >&2; exit 1; }
	swiv=$( (cd "$repo" && python3 -m ubci.config get "$board" spl.swiv 2>/dev/null) || true)
	if [ -n "$swiv" ]; then
		sw=${UBCI_SWIV:-}
		[ -n "$sw" ] || sw=$("$repo/scripts/checkout.sh" boot-firmware-ci "$(top swiv repo)" "$(top swiv commit)")/tools/swiv_build_utility.py
		python3 "$sw" "$build/u-boot-spl-swiv.elf" "$elf" "$swiv"
		elf=$build/u-boot-spl-swiv.elf
	fi
	qtestsign -v6 "$(cfg spl.sign)" -o "$out/spl.mbn" "$elf"
fi
cp "$build/$image" "$out/"
cp "$build/u-boot.dtb" "$out/u-boot.dtb"
# The FIT of an SPL boot chain is made with the mkimage of this tree.
if [ "$stack" != stock ] && [ -x "$build/tools/mkimage" ]; then
	cp "$build/tools/mkimage" "$out/mkimage"
fi
cp "$build/u-boot" "$out/u-boot.elf"
cp "$build/.config" "$out/u-boot.config"
spl_sha=null
[ "$stack" != spl ] || spl_sha="\"$(sha256sum "$out/spl.mbn" | cut -d' ' -f1)\""
printf '{"board": "%s", "stack": "%s", "fingerprint": "%s", "commit": "%s", "configs": "%s", "device_tree": "%s", "image": "%s", "sha256": "%s", "spl_sha256": %s}\n' \
	"$board" "$stack" "$fp" "$commit" "$configs" "$dt" "$image" \
	"$(sha256sum "$out/$image" | cut -d' ' -f1)" "$spl_sha" >"$out/u-boot.json"
cat "$out/u-boot.json"
