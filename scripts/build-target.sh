#!/bin/bash
# build-target.sh <u-boot source> <board> <stock|open> <fingerprint> <linux dir> <initramfs dir> <output dir>
#
# Everything one board and firmware stack of a run flashes, end to end:
# U-Boot, for the open stack the FIP around it, the ESP with the
# linux-next UKI, and the qcomflash package
# <output dir>/<board>-<stack>.qcomflash.tar.gz. Each target gets its own
# fingerprint, <run fingerprint>-<stack>-<board> (ubci.jobs.target_fingerprint),
# so a console can only pass the gate of the package built for it. A
# stack "stock-candidate" builds the stock stack from the board config in
# the tree (a pin candidate).
set -euo pipefail
[ $# -eq 7 ] || { sed -n '2p' "$0" >&2; exit 1; }
src=$1 board=$2 stack=$3 fp=$4-$3-$2 linux=$5 initramfs=$6 out=$7
here=$(cd "$(dirname "$0")" && pwd)
t=$out/$board-$stack
base=${stack%-candidate}
"$here/build-uboot.sh" "$src" "$board" "$base" "$fp" "$t"
if [ "$base" = open ]; then
	"$here/build-open-stack.sh" "$board" "$t/u-boot.bin" "$fp" "$t"
	uefi=$t/fip.elf
else
	uefi=$t/$(cd "$here/.." && python3 -m ubci.config get "$board" "u-boot.$base.image")
fi
"$here/mk-esp.sh" "$board" "$base" "$linux" "$initramfs" "$t"
(cd "$here/.." && python3 -m ubci.package "$board" "$base" "$uefi" "$t/efi.bin" \
	"$out/$board-$stack.qcomflash.tar.gz")
rm "$t/efi.bin"
