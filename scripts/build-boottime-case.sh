#!/bin/bash
# build-boottime-case.sh <initramfs dir>
#
# Packs the on-target boot-time case of test-definitions, at the commit
# config/project.yaml pins (boottime_case), into
# <initramfs dir>/boottime-case/boottime-case.cpio.gz under
# /opt/test-definitions, with boottime-case.json (repo, commit, sha256 of
# each file). scripts/mk-esp.sh adds it to the UKI as a third initrd.
# Nothing is built while the pin is pending (its commit is not public),
# and the directory is removed so no stale case is packed. Run again with
# the same pin, it keeps what it built.
#
# UBCI_BOOTTIME_CASE_REPO fetches the pinned commit from another
# repository (a local checkout for a local run); the pin's commit is
# still the one packed and recorded, so the result is the same bytes.
set -euo pipefail
[ $# -eq 1 ] || { sed -n '2p' "$0" >&2; exit 1; }
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
out=$1/boottime-case
pin() { (cd "$repo_dir" && python3 -c "import sys, yaml; print(yaml.safe_load(open('config/project.yaml'))['boottime_case'].get(sys.argv[1]) or '')" "$1"); }
repo=$(pin repo) commit=$(pin commit) pending=$(pin pending)
src=${UBCI_BOOTTIME_CASE_REPO:-$repo}
if [ -n "$pending" ] && [ -z "${UBCI_BOOTTIME_CASE_REPO:-}" ]; then
	rm -rf "$out"
	echo "boot-time case left out: pin pending ($pending)"
	exit 0
fi
if [ -f "$out/boottime-case.json" ] && grep -q "\"commit\": \"$commit\"" "$out/boottime-case.json" &&
	[ -f "$out/boottime-case.cpio.gz" ]; then
	echo "boot-time case $commit already built"
	exit 0
fi
work=$(mktemp -d "${UBCI_WORK:-$repo_dir/work}/boottime-case.XXXXXX")
trap 'rm -rf "$work"' EXIT
git init -q "$work/td"
git -C "$work/td" fetch -q --depth 1 "$src" "$commit"
[ "$(git -C "$work/td" rev-parse FETCH_HEAD)" = "$commit" ] || { echo "fetched $(git -C "$work/td" rev-parse FETCH_HEAD), not $commit" >&2; exit 1; }
files=(automated/lib/sh-test-lib automated/linux/boot-time/boot-time.sh automated/linux/boot-time/cntvct-arm64)
root=$work/root/opt/test-definitions
for f in "${files[@]}"; do
	mkdir -p "$root/$(dirname "$f")"
	git -C "$work/td" show "FETCH_HEAD:$f" >"$root/$f"
	chmod 755 "$root/$f"
done
# Entries carry the commit's time, not the checkout's: same pin, same bytes.
find "$work/root" -mindepth 1 -exec touch -h -d "@$(git -C "$work/td" log -1 --format=%ct FETCH_HEAD)" {} +
mkdir -p "$out"
(cd "$work/root" && find . -mindepth 1 | LC_ALL=C sort |
	cpio -o -H newc --owner 0:0 --reproducible --quiet) | gzip -n -9 >"$out/boottime-case.cpio.gz"
python3 - "$out/boottime-case.json" "$repo" "$commit" "$root" "$out/boottime-case.cpio.gz" "${files[@]}" <<'PY'
import hashlib, json, os, sys
dest, repo, commit, root, cpio, files = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6:]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump({"repo": repo, "commit": commit, "path": "/opt/test-definitions",
           "files": {f: sha(os.path.join(root, f)) for f in files}, "cpio_sha256": sha(cpio)},
          open(dest, "w"), indent=2, sort_keys=True)
PY
cat "$out/boottime-case.json"
