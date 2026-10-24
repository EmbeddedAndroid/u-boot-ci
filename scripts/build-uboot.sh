#!/bin/bash
# build-uboot.sh <u-boot source> <board> <stock|open> <fingerprint> <output dir>
#
# Builds the U-Boot under test for one board and firmware stack with the
# configs and device tree of config/boards/<board>.yaml, with the run's
# fingerprint as LOCALVERSION so the banner on the console names this
# build. Outputs the image the stack flashes (u-boot.mbn for stock,
# u-boot.bin for the FIP of the open stack), u-boot.elf and the .config.
set -euo pipefail
[ $# -eq 5 ] || { sed -n '2p' "$0" >&2; exit 1; }
src=$1 board=$2 stack=$3 fp=$4 out=$5
repo=$(cd "$(dirname "$0")/.." && pwd)
cfg() { (cd "$repo" && python3 -m ubci.config get "$board" "$1"); }
case $stack in stock|open) ;; *) echo "stack must be stock or open" >&2; exit 1 ;; esac
case $fp in *[!A-Za-z0-9._-]*|"") echo "bad fingerprint '$fp'" >&2; exit 1 ;; esac

configs=$(cd "$repo" && python3 -m ubci.config configs "$board" "$stack" "$(realpath "$src")")
dt=$(cfg "u-boot.$stack.device_tree")
image=$(cfg "u-boot.$stack.image")
commit=$(git -C "$src" rev-parse HEAD)
build=${UBCI_WORK:-$repo/work}/u-boot-build/$board-$stack
rm -rf "$build"
mkdir -p "$build" "$out"

make -C "$src" -s O="$build" $configs
make -C "$src" -s O="$build" -j"$(nproc)" LOCALVERSION="-$fp" DEVICE_TREE="$dt"
grep -aq -- "-$fp" "$build/$image" || { echo "$image lacks the fingerprint $fp" >&2; exit 1; }
cp "$build/$image" "$out/"
cp "$build/u-boot" "$out/u-boot.elf"
cp "$build/.config" "$out/u-boot.config"
printf '{"board": "%s", "stack": "%s", "fingerprint": "%s", "commit": "%s", "configs": "%s", "device_tree": "%s", "image": "%s", "sha256": "%s"}\n' \
	"$board" "$stack" "$fp" "$commit" "$configs" "$dt" "$image" \
	"$(sha256sum "$out/$image" | cut -d' ' -f1)" >"$out/u-boot.json"
cat "$out/u-boot.json"
