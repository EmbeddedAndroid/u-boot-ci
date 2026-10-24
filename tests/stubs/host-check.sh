#!/bin/bash
# Stand-in for scripts/host-check.sh in the tests and the dry run: same
# arguments and outputs, no U-Boot. Appends "check <name>" to
# $UBCI_STUB_CALLS. A name in $UBCI_STUB_FAIL gives result fail, one in
# $UBCI_STUB_CRASH exits 3 without a result.
check=$1 out=$3
mkdir -p "$out"
echo "check $check $*" >>"${UBCI_STUB_CALLS:-/dev/null}"
[[ " ${UBCI_STUB_CRASH:-} " == *" $check "* ]] && { echo "$check: crashed" >&2; exit 3; }
r=pass
[[ " ${UBCI_STUB_FAIL:-} " == *" $check "* ]] && r=fail
echo "stub $check: $r" >"$out/$check.log"
printf '{"result": "%s", "summary": "stub %s"}\n' "$r" "$r" >"$out/$check.json"
echo "$check: $r: stub"
