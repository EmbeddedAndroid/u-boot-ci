#!/bin/bash
# build-open-stack.sh <board> <u-boot.bin> <fingerprint> <output dir>
#
# The open stack around a U-Boot under test: TF-A BL31 and OP-TEE built
# from the commits pinned in config/pins.yaml (with the run's fingerprint
# in their version strings, OP-TEE with the pin's make_args), and the
# image XBL loads from uefi_a/uefi_b, by the TF-A pin's image:
#   fip.elf    the FIP with U-Boot as BL33, wrapped in an ELF with a
#              qtestsign test signature (TF-A BL2 loads it);
#   uefi.itb   a FIT of BL31, OP-TEE, U-Boot and its control DTB at the
#              pin's load addresses (U-Boot SPL loads it; Lemans).
# The pinned, pre-signed tz image (BL2 or SPL) is added by ubci.package.
# open-stack.json names the image.
set -euo pipefail
[ $# -eq 4 ] || { sed -n '2p' "$0" >&2; exit 1; }
board=$1 bl33=$(realpath "$2") fp=$3 out=$4
repo=$(cd "$(dirname "$0")/.." && pwd)
cfg() { (cd "$repo" && python3 -m ubci.config get "$board" "$1"); }
top() { (cd "$repo" && python3 -c "import sys,yaml; print(yaml.safe_load(open('config/pins.yaml'))$1)"); }
work=${UBCI_WORK:-$repo/work}
mkdir -p "$out"
out=$(realpath "$out")

checkout() { "$repo/scripts/checkout.sh" "$@"; }

opt() { (cd "$repo" && python3 -m ubci.config get "$board" "$1" 2>/dev/null) || true; }

optee=$(checkout "optee_os" "$(cfg pins.optee.repo)" "$(cfg pins.optee.commit)")
mapfile -t optee_args < <(opt pins.optee.make_args)
make -C "$optee" -s -j"$(nproc)" PLATFORM="$(cfg pins.optee.platform)" \
	CFG_ARM64_core=y CROSS_COMPILE64="$CROSS_COMPILE" CROSS_COMPILE_core="$CROSS_COMPILE" \
	CROSS_COMPILE_ta_arm64="$CROSS_COMPILE" CFG_TEE_CORE_LOG_LEVEL=2 TEE_IMPL_VERSION="$fp" \
	"${optee_args[@]}" O="$optee/out"
bl32=$optee/out/core/tee-raw.bin
grep -aq "$fp" "$bl32" || { echo "OP-TEE lacks $fp" >&2; exit 1; }

tfa=$(checkout "tf-a-$board" "$(cfg pins.tf-a.repo)" "$(cfg pins.tf-a.commit)")
image=$(opt pins.tf-a.image)
image=${image:-fip.elf}
case $image in
fip.elf)
	make -C "$tfa" -s -j"$(nproc)" $(cfg pins.tf-a.flags) DEBUG=0 BUILD_STRING="$fp" \
		BL32="$bl32" BL33="$bl33" bl31 fip
	fip=$(ls "$tfa"/build/*/release/fip.bin)
	[ "$(grep -ac "$fp" "$fip")" -ge 2 ] || { echo "FIP lacks $fp in BL31 or OP-TEE" >&2; exit 1; }
	qts=$(checkout qtestsign "$(top "['qtestsign']['repo']")" "$(top "['qtestsign']['commit']")")
	wrap=$work/fip-elf-$board
	rm -rf "$wrap" && mkdir -p "$wrap" && ln -s "$qts" "$wrap/qtestsign"
	(cd "$wrap" && "$tfa/tools/qti/generate_fip_elf.sh" "$fip" "$(cfg pins.tf-a.fip_load_addr)")
	mv "$wrap/fip.elf" "$out/fip.elf"
	cp "$fip" "$out/fip.bin"
	;;
uefi.itb)
	make -C "$tfa" -s -j"$(nproc)" $(cfg pins.tf-a.flags) DEBUG=0 BUILD_STRING="$fp" bl31
	bl31=$(ls "$tfa"/build/*/release/bl31.bin)
	grep -aq "$fp" "$bl31" || { echo "BL31 lacks $fp" >&2; exit 1; }
	dir=$(dirname "$bl33")
	[ -x "$dir/mkimage" ] && [ -f "$dir/u-boot.dtb" ] || { echo "no mkimage or u-boot.dtb next to $bl33" >&2; exit 1; }
	(cd "$repo" && python3 -m ubci.fit "$board" "$bl31" "$bl32" "$bl33" "$dir/u-boot.dtb") >"$out/uefi.its"
	"$dir/mkimage" -q -f "$out/uefi.its" "$out/uefi.itb"
	[ "$(grep -ac "$fp" "$out/uefi.itb")" -ge 3 ] || { echo "FIT lacks $fp in BL31, OP-TEE or U-Boot" >&2; exit 1; }
	;;
*) echo "unknown open-stack image $image" >&2; exit 1 ;;
esac
printf '{"board": "%s", "fingerprint": "%s", "tf-a": "%s", "optee": "%s", "image": "%s", "image_sha256": "%s"}\n' \
	"$board" "$fp" "$(cfg pins.tf-a.commit)" "$(cfg pins.optee.commit)" "$image" \
	"$(sha256sum "$out/$image" | cut -d' ' -f1)" >"$out/open-stack.json"
cat "$out/open-stack.json"
