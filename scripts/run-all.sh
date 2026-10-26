#!/bin/bash
# run-all.sh <u-boot source> <run.json> <fingerprint> <checkpatch base> <linux dir> <initramfs dir> <output dir> [<stack dir>]
#
# Everything a run does with the U-Boot under test, in the one job that
# runs patch code (docs/architecture.md): applies the stack of an ad-hoc
# run (<stack dir>, ubci.stack), runs the host checks carry, buildman,
# fragments, checkpatch (from <checkpatch base>), docs, sandbox and
# qemu_arm64 (scripts/host-check.sh), builds every queued target of the
# run document (scripts/build-target.sh) and runs the size check over
# those builds. One step failing does not stop the ones after it.
#
# Writes <output dir>/host/<check>.{json,log} as host-check.sh does,
# <output dir>/host/build-<board>-<stack>.log, and the packages and
# per-target files in <output dir>/targets/. A target without a package
# gets <output dir>/targets/<board>-<stack>.build.json saying why: "skip"
# when the tree does not have the board or its SPL, or an open-stack pin
# is not public yet (ubci.config missing), "fail"
# when its build failed. When the stack does not
# apply there is no tree to check or build: only carry and size run (the
# run document already marks every target skipped).
# Exits 0 when every step ran and passed, 1 when any did not.
set -uo pipefail
[ $# -ge 7 ] && [ $# -le 8 ] || { sed -n '2p' "$0" >&2; exit 2; }
src=$1 run=$2 fp=$3 since=$4 linux=$5 initramfs=$6 out=$7 stack=${8:-}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
# The dry run (scripts/dry-run.sh) and the tests replace the two workers.
host_check=${UBCI_HOST_CHECK:-$here/host-check.sh}
build_target=${UBCI_BUILD_TARGET:-$here/build-target.sh}
mkdir -p "$out/host" "$out/targets"
out=$(realpath "$out")
failed=()

result() { # <check json>: its result, or "none"
	python3 -c 'import json, sys
try:
    print(json.load(open(sys.argv[1]))["result"])
except Exception:
    print("none")' "$1"
}

# check <name> <source> <output dir> [base]: one host-check.sh check; its
# JSON ends up in $out/host whatever output dir the check needs.
check() {
	local c=$1 dir=$3 rc r
	echo "== check $c"
	rm -f "$out/host/$c.json"
	"$host_check" "$@"
	rc=$?
	if [ "$dir" != "$out/host" ]; then
		mv -f "$dir/$c".* "$out/host/" 2>/dev/null
		rmdir "$dir" 2>/dev/null
	fi
	r=$(result "$out/host/$c.json")
	case $rc/$r in
	0/pass) ;;
	0/none) failed+=("$c (no result)") ;;
	0/*) failed+=("$c ($r)") ;;
	*) failed+=("$c (could not run: exit $rc)") ;;
	esac
}

# status <board> <stack> <skip|fail> <reason>: why a target has no
# package, for the submit job (<board>-<stack>.build.json next to the
# packages).
status() {
	python3 -c 'import json, sys
json.dump({"result": sys.argv[2], "reason": sys.argv[3]}, open(sys.argv[1], "w"))' \
		"$out/targets/$1-$2.build.json" "$3" "$4"
}

applies=yes
if [ -n "$stack" ]; then
	a=$(cd "$repo" && python3 -m ubci.stack apply "$src" "$stack")
	rc=$?
	echo "stack: $a"
	if [ $rc != 0 ]; then
		failed+=("stack (could not apply: exit $rc)")
		applies=no
	elif [ "$a" != applies ]; then
		applies=no
	fi
fi

check carry . "$out/host"

if [ $applies = yes ]; then
	for c in buildman fragments checkpatch docs sandbox qemu_arm64; do
		check $c "$src" "$out/host" "$since"
	done

	targets=$(python3 -c 'import json, sys
for t in json.load(open(sys.argv[1]))["targets"]:
    if t["state"] == "queued":
        print(t["board"], t["stack"])' "$run") || { failed+=("run document (unreadable)"); targets=; }
	while read -r board st; do
		[ -n "$board" ] || continue
		echo "== build $board/$st"
		log=$out/host/build-$board-$st.log
		why=$(cd "$repo" && python3 -m ubci.config missing "$board" "${st%-candidate}" "$src" ${stack:+--adhoc})
		if [ -n "$why" ]; then
			echo "$why" >"$log"
			status "$board" "$st" skip "$why"
			echo "build $board/$st: skipped: $why"
			continue
		fi
		if [ ! -f "$linux/linux.json" ] || [ ! -f "$initramfs/initramfs.json" ]; then
			echo "no Linux payload in $linux and $initramfs" >"$log"
			failed+=("build $board/$st (no Linux payload)")
		elif "$build_target" "$src" "$board" "$st" "$fp" "$linux" "$initramfs" "$out/targets" >"$log" 2>&1; then
			echo "build $board/$st: pass"
			continue
		else
			failed+=("build $board/$st (exit $?)")
		fi
		# Nothing of a failed build may reach LAVA or the size check.
		rm -rf "$out/targets/$board-$st.qcomflash.tar.gz" "$out/targets/$board-$st"
		status "$board" "$st" fail "build failed: $(grep -v '^[[:space:]]*$' "$log" | tail -1)"
		echo "build $board/$st: fail"
		tail -20 "$log"
	done <<<"$targets"
fi

# size reads the builds next to its output dir (<targets>/<board>-<stack>/).
check size . "$out/targets/host"

if [ ${#failed[@]} = 0 ]; then
	echo "every step passed"
	exit 0
fi
echo "failed: ${#failed[@]}"
printf '  %s\n' "${failed[@]}"
exit 1
