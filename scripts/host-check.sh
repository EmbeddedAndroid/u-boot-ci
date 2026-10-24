#!/bin/bash
# host-check.sh <check> <u-boot source> <output dir> [base commit]
#
# One host-side check of the U-Boot under test, the way upstream U-Boot CI
# runs it (.gitlab-ci.yml), limited to what the Qualcomm boards need:
#   buildman   every snapdragon board, warnings as errors
#   fragments  the defconfig + fragment combinations of config/project.yaml
#   checkpatch every non-merge commit since <base commit> (else the last 24 h)
#   docs       make htmldocs with KDOC_WERROR=1 and Sphinx warnings as errors
#   sandbox    test.py on sandbox
#   qemu_arm64 test.py on QEMU with the upstream test hooks
#   carry      config/carry.yaml matches the pins (ubci.carry --check; this
#              repository, not the U-Boot source)
#   size       text/data/bss and image size of every hardware build in
#              <output dir>/../<board>-<stack>/
# Writes <output dir>/<check>.log and <output dir>/<check>.json
# ({"result", "summary"[, "data"]}); exits 0 when the check ran, whatever
# its result, and non-zero only when it could not run.
set -uo pipefail
[ $# -ge 3 ] || { sed -n '2p' "$0" >&2; exit 2; }
check=$1 src=$(realpath "$2") out=$3 base=${4:-}
repo=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$out"
out=$(realpath "$out")
log=$out/$check.log
: >"$log"
jobs=$(nproc)

result() { # <pass|fail> <summary> [data json]
	python3 - "$out/$check.json" "$@" <<'PY'
import json, sys
d = {"result": sys.argv[2], "summary": sys.argv[3]}
if len(sys.argv) > 4:
    d["data"] = json.loads(sys.argv[4])
json.dump(d, open(sys.argv[1], "w"))
PY
	echo "$check: $1: $2"
}

cd "$src"
case $check in
carry)
	if (cd "$repo" && python3 -m ubci.carry --check) >"$log" 2>&1; then r=pass; else r=fail; fi
	result $r "$(tail -1 "$log")" ;;
buildman)
	if tools/buildman/buildman -o "$out/buildman" -P -E -W -M -e -j "$jobs" snapdragon >"$log" 2>&1; then
		result pass "every snapdragon board built without warnings"
	else
		result fail "$(tools/buildman/buildman -o "$out/buildman" -s snapdragon 2>&1 | tail -2 | tr '\n' ' ')"
	fi ;;
fragments)
	fail=0 n=0
	while read -r combo; do
		n=$((n + 1))
		b=$out/fragments/$(echo "$combo" | tr ' ' '+')
		rm -rf "$b"
		{ make -s O="$b" $combo && make -s O="$b" -j"$jobs" KCFLAGS=-Werror; } >>"$log" 2>&1 || {
			fail=$((fail + 1)); echo "FAILED: $combo" >>"$log"; }
	done < <(cd "$repo" && python3 -c 'import yaml
for c in yaml.safe_load(open("config/project.yaml"))["host_checks"]["fragments"]: print(" ".join(c))')
	[ $fail = 0 ] && result pass "$n combinations built" || result fail "$fail of $n combinations failed"
	;;
checkpatch)
	if [ -n "$base" ] && git cat-file -e "$base^{commit}" 2>/dev/null; then
		commits=$(git rev-list --no-merges --reverse "$base..HEAD")
	else
		commits=$(git rev-list --no-merges --reverse --since="24 hours ago" HEAD)
	fi
	n=0 errs=0 warns=0
	for c in $commits; do
		n=$((n + 1))
		echo "=== $(git log -1 --format='%h %s' "$c")" >>"$log"
		report=$(scripts/checkpatch.pl -q --no-tree --git "$c" 2>&1) || true
		echo "$report" >>"$log"
		# checkpatch exits non-zero on warnings too; only errors fail the check.
		case $report in
		*"total: 0 errors, 0 warnings"*|"") ;;
		*"total: 0 errors"*) warns=$((warns + 1)) ;;
		*) errs=$((errs + 1)) ;;
		esac
	done
	[ $errs = 0 ] && r=pass || r=fail
	result $r "$n new commits: $errs with errors, $warns with warnings only"
	;;
docs)
	if make htmldocs KDOC_WERROR=1 SPHINXOPTS="-W --keep-going" O="$out/docs" >"$log" 2>&1; then
		result pass "htmldocs built without warnings"
	else
		result fail "$(grep -c -E 'WARNING|ERROR|error:' "$log") warnings or errors"
	fi ;;
sandbox|qemu_arm64)
	b=$out/build-$check
	rm -rf "$b"
	extra=()
	if [ "$check" = qemu_arm64 ]; then
		# The hooks resolve their config by host name, as upstream CI links it.
		hooks=$out/hooks
		rm -rf "$hooks" && cp -r /opt/u-boot-test-hooks "$hooks"
		ln -s travis-ci "$hooks/bin/$(hostname)"
		ln -s travis-ci "$hooks/py/$(hostname)"
		export PATH=$hooks/bin:$PATH PYTHONPATH=$hooks/py/$(hostname) UBOOT_TRAVIS_BUILD_DIR=$b
		tools/buildman/buildman -o "$b" -w -E -W -e --board qemu_arm64 -a CONFIG_SEMIHOSTING=y >"$log" 2>&1 ||
			{ result fail "qemu_arm64 did not build"; exit 0; }
		extra=(--id na -k "not sleep")
	else
		make -s O="$b" sandbox_defconfig >"$log" 2>&1 && make -s O="$b" -j"$jobs" >>"$log" 2>&1 ||
			{ result fail "sandbox did not build"; exit 0; }
		# binman (test_vboot) imports the pylibfdt of the build, as upstream CI sets it.
		export PYTHONPATH=$b/scripts/dtc/pylibfdt
		extra=(-k "not event_dump and not sleep")
	fi
	./test/py/test.py --bd "$check" --build-dir "$b" --result-dir "$out/result-$check" \
		--persistent-data-dir "$out/data-$check" "${extra[@]}" >>"$log" 2>&1
	rc=$?
	sumline=$(grep -E '^=+ .*(passed|failed|error).* =+$' "$log" | tail -1 | tr -d '=' | xargs)
	[ $rc = 0 ] && result pass "${sumline:-passed}" || result fail "${sumline:-test.py exited $rc}"
	;;
size)
	data=$(python3 - "$out/.." <<'PY'
import glob, json, os, subprocess, sys
d = {}
for elf in sorted(glob.glob(os.path.join(sys.argv[1], "*-*", "u-boot.elf"))):
    t = os.path.basename(os.path.dirname(elf))
    text, data, bss = subprocess.run(["aarch64-linux-size", elf], capture_output=True,
                                     text=True, check=True).stdout.splitlines()[1].split()[:3]
    img = [f for f in glob.glob(os.path.join(os.path.dirname(elf), "u-boot.[mb][bi][n]")) ]
    d[t] = {"text": int(text), "data": int(data), "bss": int(bss),
            "image": os.path.getsize(img[0]) if img else None}
print(json.dumps(d))
PY
	) || { result fail "size could not run"; exit 0; }
	echo "$data" >"$log"
	result pass "$(echo "$data" | python3 -c 'import json,sys; print(", ".join("%s %d B" % (k, v["image"] or 0) for k, v in json.load(sys.stdin).items()))')" "$data"
	;;
*)
	echo "unknown check $check" >&2; exit 2 ;;
esac
exit 0
