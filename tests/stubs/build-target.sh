#!/bin/bash
# Stand-in for scripts/build-target.sh in the tests and the dry run: same
# arguments, writes the package and the target directory with stub
# contents. Appends "build <board>-<stack>" to $UBCI_STUB_CALLS. A
# <board>-<stack> in $UBCI_STUB_FAIL leaves a partial package and fails.
board=$2 stack=$3 fp=$4 out=$7
t=$board-$stack
echo "build $t $fp" >>"${UBCI_STUB_CALLS:-/dev/null}"
mkdir -p "$out/$t"
echo "partial" >"$out/$t.qcomflash.tar.gz"
[[ " ${UBCI_STUB_FAIL:-} " == *" $t "* ]] && { echo "$t: build failed" >&2; exit 1; }
printf '{"board": "%s", "stack": "%s", "fingerprint": "%s-%s-%s"}\n' "$board" "$stack" "$fp" "$stack" "$board" >"$out/$t/u-boot.json"
echo "package" >"$out/$t.qcomflash.tar.gz"
echo "$out/$t.qcomflash.tar.gz"
