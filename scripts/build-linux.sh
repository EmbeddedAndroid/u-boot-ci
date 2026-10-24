#!/bin/bash
# build-linux.sh <linux-next tag> <output dir>
#
# The Linux every board boots: a pristine linux-next tag built with the
# upstream arm64 defconfig, no fragments and no patches. Outputs:
#   Image            the kernel (EFI stub)
#   dtbs/            every qcom DTB and overlay of the tree, built with
#                    DTC_FLAGS=-@ so upstream overlays (e.g. monaco-el2.dtbo)
#                    can be applied to boards that have no composite target
#   modules.cpio.zst lib/modules of the same build (stripped), an initramfs
#                    part: defconfig builds UFS, QMP PHYs and more as modules
#   linux.json       tag, commit, kernel release, sha256 of every output
set -euo pipefail
[ $# -eq 2 ] || { sed -n '2p' "$0" >&2; exit 1; }
tag=$1 out=$2
case $tag in next-[0-9]*) ;; *) echo "not a linux-next tag: $tag" >&2; exit 1 ;; esac
LINUX_NEXT=${LINUX_NEXT:-https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git}
src=${UBCI_WORK:-$PWD/work}/linux-next-$tag
mkdir -p "$out"
out=$(cd "$out" && pwd)

if [ ! -d "$src/.git" ]; then
	git clone -q --depth 1 --branch "$tag" "$LINUX_NEXT" "$src"
fi
[ -z "$(git -C "$src" status --porcelain)" ] || { echo "$src is not pristine" >&2; exit 1; }
commit=$(git -C "$src" rev-parse HEAD)

mk() { make -C "$src" O="$src/.out" ARCH=arm64 CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-}" "$@"; }
mk -s defconfig
mk -s -j"$(nproc)" Image modules dtbs DTC_FLAGS=-@
release=$(mk -s kernelrelease)
case $release in *"${tag#next}") ;; *) echo "release $release does not carry $tag" >&2; exit 1 ;; esac

rm -rf "$out/dtbs" "$src/.mod"
cp "$src/.out/arch/arm64/boot/Image" "$out/Image"
mkdir -p "$out/dtbs/qcom"
cp "$src/.out/arch/arm64/boot/dts/qcom/"*.dtb "$src/.out/arch/arm64/boot/dts/qcom/"*.dtbo "$out/dtbs/qcom/"
mk -s modules_install INSTALL_MOD_PATH="$src/.mod" INSTALL_MOD_STRIP=1
rm -f "$src/.mod/lib/modules/$release/build" "$src/.mod/lib/modules/$release/source"
(cd "$src/.mod" && find lib | LC_ALL=C sort | cpio -o -H newc --reproducible -R 0:0 --quiet) |
	zstd -q -19 -T0 -o "$out/modules.cpio.zst" -f

sum() { sha256sum "$1" | cut -d' ' -f1; }
python3 - "$out/linux.json" <<PY
import json, sys
json.dump({"tag": "$tag", "commit": "$commit", "release": "$release",
           "config": "arch/arm64/configs/defconfig",
           "image_sha256": "$(sum "$out/Image")",
           "modules_sha256": "$(sum "$out/modules.cpio.zst")"},
          open(sys.argv[1], "w"), indent=2)
PY
cat "$out/linux.json"
