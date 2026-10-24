#!/bin/bash
# build-open-stack.sh <board> <u-boot.bin> <fingerprint> <output dir>
#
# The open stack around a U-Boot under test: TF-A BL31 and OP-TEE built
# from the commits pinned in config/pins.yaml (with the run's fingerprint
# in their version strings), the FIP with U-Boot as BL33, wrapped in an
# ELF with a qtestsign test signature for uefi_a/uefi_b (fip.elf). The
# pinned, pre-signed BL2 (tz.mbn) comes from fetch-pins.sh.
set -euo pipefail
[ $# -eq 4 ] || { sed -n '2p' "$0" >&2; exit 1; }
board=$1 bl33=$(realpath "$2") fp=$3 out=$4
repo=$(cd "$(dirname "$0")/.." && pwd)
cfg() { (cd "$repo" && python3 -m ubci.config get "$board" "$1"); }
top() { (cd "$repo" && python3 -c "import sys,yaml; print(yaml.safe_load(open('config/pins.yaml'))$1)"); }
work=${UBCI_WORK:-$repo/work}
mkdir -p "$out"
out=$(realpath "$out")

# checkout <name> <repo> <commit>: a clean tree of that commit in $work/src
checkout() {
	local d=$work/src/$1
	[ -d "$d/.git" ] || git clone -q "$2" "$d"
	git -C "$d" cat-file -e "$3^{commit}" 2>/dev/null || git -C "$d" fetch -q origin "$3"
	git -C "$d" checkout -q --detach "$3"
	git -C "$d" clean -qfdx
	echo "$d"
}

optee=$(checkout "optee_os" "$(cfg pins.optee.repo)" "$(cfg pins.optee.commit)")
make -C "$optee" -s -j"$(nproc)" PLATFORM="$(cfg pins.optee.platform)" \
	CFG_ARM64_core=y CROSS_COMPILE64="$CROSS_COMPILE" CROSS_COMPILE_core="$CROSS_COMPILE" \
	CFG_TEE_CORE_LOG_LEVEL=2 TEE_IMPL_VERSION="$fp" O="$optee/out"
bl32=$optee/out/core/tee-raw.bin
grep -aq "$fp" "$bl32" || { echo "OP-TEE lacks $fp" >&2; exit 1; }

tfa=$(checkout "tf-a-$board" "$(cfg pins.tf-a.repo)" "$(cfg pins.tf-a.commit)")
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
printf '{"board": "%s", "fingerprint": "%s", "tf-a": "%s", "optee": "%s", "fip_elf_sha256": "%s"}\n' \
	"$board" "$fp" "$(cfg pins.tf-a.commit)" "$(cfg pins.optee.commit)" \
	"$(sha256sum "$out/fip.elf" | cut -d' ' -f1)" >"$out/open-stack.json"
cat "$out/open-stack.json"
