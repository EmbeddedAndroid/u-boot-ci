#!/bin/bash
# sign-bl2-oem.sh <board> <fingerprint> <output dir>
#
# Prepares the pinned BL2 of a board whose XBL accepts an OEM TEST
# signature (RB3 Gen 2): TF-A BL2 built from the tf-a pin with
# <fingerprint> as its build string, signed as a TZ-TEE image with the
# OEM TEST key of Qualcomm's public sectools and the board's public
# security profile, then validated. Run when a pin changes, not per run;
# the result goes into config/pins.yaml (file, sha256, fingerprint).
# sectools is an x86_64 Linux binary.
set -euo pipefail
[ $# -eq 3 ] || { sed -n '2p' "$0" >&2; exit 1; }
board=$1 fp=$2 out=$3
repo=$(cd "$(dirname "$0")/.." && pwd)
cfg() { (cd "$repo" && python3 -m ubci.config get "$board" "$1"); }
work=${UBCI_WORK:-$repo/work}
mkdir -p "$out"
out=$(realpath "$out")
SECTOOLS_URL=https://softwarecenter.qualcomm.com/api/download/software/tools/Qualcomm_Security_Tools/All/1.50.0/1.50.zip
SECTOOLS_SHA256=8d6694f1d184e7c204d1e1ea50447a946d7f21838cfddb48b06f0c733d700cbe
PROFILE_URL=$(cfg pins.bl2.profile.url)
PROFILE_SHA256=$(cfg pins.bl2.profile.sha256)

zip=$(cd "$repo" && python3 -m ubci.fetch "$SECTOOLS_URL" "$SECTOOLS_SHA256" sectools-1.50.zip)
profile=$(cd "$repo" && python3 -m ubci.fetch "$PROFILE_URL" "$PROFILE_SHA256")
st=$work/sectools-1.50
[ -x "$st/1.50/Linux/sectools" ] || { mkdir -p "$st" && python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2], [n for n in zipfile.ZipFile(sys.argv[1]).namelist() if n.startswith('1.50/Linux/')])" "$zip" "$st" && chmod +x "$st/1.50/Linux/sectools"; }

tfa=$work/src/tf-a-$board-bl2
[ -d "$tfa/.git" ] || git clone -q "$(cfg pins.tf-a.repo)" "$tfa"
git -C "$tfa" fetch -q origin "$(cfg pins.tf-a.commit)"
git -C "$tfa" checkout -q --detach "$(cfg pins.tf-a.commit)"
git -C "$tfa" clean -qfdx
make -C "$tfa" -s -j"$(nproc)" $(cfg pins.tf-a.flags) DEBUG=0 BUILD_STRING="$fp" bl2
bl2=$(ls "$tfa"/build/*/release/bl2/bl2.elf)
"$st/1.50/Linux/sectools" secure-image "$bl2" --outfile "$out/$(cfg pins.bl2.file)" \
	--image-id TZ-TEE --security-profile "$profile" --sign --signing-mode TEST
"$st/1.50/Linux/sectools" secure-image "$out/$(cfg pins.bl2.file)" --validate \
	--image-id TZ-TEE --security-profile "$profile"
grep -aq "$fp" "$out/$(cfg pins.bl2.file)"
echo "file: $(cfg pins.bl2.file)  sha256: $(sha256sum "$out/$(cfg pins.bl2.file)" | cut -d' ' -f1)  fingerprint: $fp"
