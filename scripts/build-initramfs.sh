#!/bin/bash
# build-initramfs.sh <output dir>
#
# Builds config/buildroot/initramfs_defconfig with the pinned Buildroot
# release into <output dir>/rootfs.cpio.gz (+ initramfs.json). The result
# depends only on the release and the defconfig, so CI caches it by the
# hash of both.
set -euo pipefail
[ $# -eq 1 ] || { sed -n '2p' "$0" >&2; exit 1; }
BR_VERSION=2026.08.1
BR_SHA256=34fb7bea8a213ffde39cc02e61703391560f26e0850f03138c722d0b09880f2b
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${UBCI_WORK:-$repo/work}/buildroot-$BR_VERSION
mkdir -p "$1" "$work"
out=$(cd "$1" && pwd)

tarball=$work.tar.xz
[ -f "$tarball" ] || curl -fsSL -o "$tarball" "https://buildroot.org/downloads/buildroot-$BR_VERSION.tar.xz"
echo "$BR_SHA256  $tarball" | sha256sum -c --quiet
[ -f "$work/Makefile" ] || tar -C "$work" --strip-components=1 -xJf "$tarball"

cp "$repo/config/buildroot/initramfs_defconfig" "$work/configs/ubci_initramfs_defconfig"
make -C "$work" -s O="$work/.out" ubci_initramfs_defconfig
# Buildroot refuses to run with a cross toolchain prefix in the environment.
env -u CROSS_COMPILE make -C "$work" O="$work/.out"
cp "$work/.out/images/rootfs.cpio.gz" "$out/rootfs.cpio.gz"
sha=$(sha256sum "$out/rootfs.cpio.gz" | cut -d' ' -f1)
printf '{\n  "buildroot": "%s",\n  "defconfig_sha256": "%s",\n  "rootfs_sha256": "%s"\n}\n' \
	"$BR_VERSION" "$(sha256sum "$repo/config/buildroot/initramfs_defconfig" | cut -d' ' -f1)" "$sha" \
	>"$out/initramfs.json"
cat "$out/initramfs.json"
