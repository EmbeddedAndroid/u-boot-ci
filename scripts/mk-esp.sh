#!/bin/bash
# mk-esp.sh <board> <stock|open> <linux dir> <initramfs dir> <output dir>
#
# The EFI payload the board boots: a UKI (systemd-boot stub) holding the
# pristine linux-next Image, the board DTB from the same build with the
# upstream overlays config/boards/<board>.yaml lists for the stack, the
# command line, and an initramfs of the Buildroot userspace followed by
# the kernel's own modules; on a FAT ESP as EFI/BOOT/BOOTAA64.EFI, the
# removable-media path U-Boot's EFI boot manager boots. Nothing in the
# kernel or DT is changed.
set -euo pipefail
[ $# -eq 5 ] || { sed -n '2p' "$0" >&2; exit 1; }
board=$1 stack=$2 linux=$(realpath "$3") initramfs=$(realpath "$4") out=$5
repo=$(cd "$(dirname "$0")/.." && pwd)
cfg() { (cd "$repo" && python3 -m ubci.config get "$board" "$1"); }
mkdir -p "$out"
out=$(realpath "$out")
work=$(mktemp -d "${UBCI_WORK:-$repo/work}/esp.XXXXXX")
trap 'rm -rf "$work"' EXIT

dtb=$linux/dtbs/$(cfg linux.dtb)
overlays=$(cfg "linux.overlays.$stack" | sed "/^$/d; s|^|$linux/dtbs/|")
if [ -n "$overlays" ]; then
	fdtoverlay -i "$dtb" -o "$work/board.dtb" $overlays
else
	cp "$dtb" "$work/board.dtb"
fi
cmdline=$(cfg linux.cmdline)

ukify build --linux="$linux/Image" \
	--initrd="$initramfs/rootfs.cpio.gz" --initrd="$linux/modules.cpio.zst" \
	--devicetree="$work/board.dtb" --cmdline="$cmdline" --efi-arch=aa64 \
	--stub=/usr/lib/systemd/boot/efi/linuxaa64.efi.stub --output="$work/uki.efi" >/dev/null

case $(cfg lava.storage) in ufs) sector=4096 ;; *) sector=512 ;; esac
size=$((256 * 1024 * 1024))
[ "$(stat -c %s "$work/uki.efi")" -lt $((size - 16 * 1024 * 1024)) ] || { echo "UKI too large for the ESP" >&2; exit 1; }
truncate -s $size "$out/efi.bin"
mkfs.fat -F 32 -S $sector "$out/efi.bin" >/dev/null
mmd -i "$out/efi.bin" ::/EFI ::/EFI/BOOT
mcopy -i "$out/efi.bin" "$work/uki.efi" ::/EFI/BOOT/BOOTAA64.EFI
python3 - "$out/esp.json" "$linux/linux.json" "$initramfs/initramfs.json" <<PY
import hashlib, json, sys
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump({"board": "$board", "stack": "$stack",
           "linux": json.load(open(sys.argv[2])),
           "initramfs": json.load(open(sys.argv[3])),
           "dtb": "$(cfg linux.dtb)", "overlays": "$(cfg "linux.overlays.$stack" | tr '\n' ' ')".split(),
           "dtb_sha256": sha("$work/board.dtb"), "cmdline": "$cmdline",
           "uki_sha256": sha("$work/uki.efi")}, open(sys.argv[1], "w"), indent=2)
PY
echo "$out/efi.bin"
