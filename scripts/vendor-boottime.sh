#!/bin/bash
# vendor-boottime.sh <lava-boottime repository> <commit>
#
# Copies the boot-time parser of lava-boottime (its parser module and the
# platform files) at <commit> into fwci/lava_boottime, byte for byte, and
# writes VENDOR.json: the commit and the sha256 of every file copied.
# tests/test_boottime_vendor.py checks the copy against it, so a change
# made here instead of in lava-boottime fails the tests.
set -euo pipefail
[ $# -eq 2 ] || { sed -n '2p' "$0" >&2; exit 1; }
src=$1 commit=$(git -C "$1" rev-parse --verify "$2^{commit}")
dest=$(cd "$(dirname "$0")/.." && pwd)/fwci/lava_boottime
files=(lava_boottime/parser.py $(git -C "$src" ls-tree --name-only "$commit" lava_boottime/platforms/ | grep '\.yaml$'))
rm -rf "$dest"
mkdir -p "$dest/platforms"
: >"$dest/__init__.py"
for f in "${files[@]}"; do
	git -C "$src" show "$commit:$f" >"$dest/${f#lava_boottime/}"
done
python3 - "$dest" "$commit" "${files[@]#lava_boottime/}" <<'PY'
import hashlib, json, os, sys
dest, commit, files = sys.argv[1], sys.argv[2], sys.argv[3:]
sha = lambda f: hashlib.sha256(open(os.path.join(dest, f), "rb").read()).hexdigest()
json.dump({"name": "lava-boottime", "commit": commit,
           "files": {f: sha(f) for f in sorted(files)}},
          open(os.path.join(dest, "VENDOR.json"), "w"), indent=1, sort_keys=True)
PY
echo "vendored lava-boottime $commit into $dest"
