#!/bin/bash
# publish-site.sh <gh-pages checkout> <run.json>
#
# Puts a run document and the dashboard into the GitHub Pages branch
# checkout, rebuilds index.json and pushes. Nothing is committed when the
# run has not changed since the last publish (its "updated" stamp aside),
# so a live run makes a commit per state change, not per poll. When
# another workflow pushed first, the checkout is reset to the remote and
# the publish redone: the run file is the only input, the index is rebuilt.
set -euo pipefail
[ $# -eq 2 ] || { sed -n '2p' "$0" >&2; exit 1; }
site=$1 run=$2
repo=$(cd "$(dirname "$0")/.." && pwd)
dest=$site/runs/$(basename "$run")

same() {
	[ -f "$dest" ] && python3 - "$run" "$dest" <<'PY'
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
for d in (a, b):
    d["run"].pop("updated", None)
sys.exit(0 if a == b else 1)
PY
}

publish() {
	mkdir -p "$site/runs"
	cp "$run" "$dest"
	cp "$repo"/dashboard/* "$site/"
	touch "$site/.nojekyll"
	(cd "$repo" && python3 -m ubci.run site "$site")
	git -C "$site" add -A
	git -C "$site" -c user.name="u-boot-ci" -c user.email="u-boot-ci@users.noreply.github.com" \
		commit -q -m "results: $(basename "$run" .json)"
}

same && exit 0
publish
for i in 1 2 3; do
	git -C "$site" push -q origin HEAD:gh-pages && exit 0
	git -C "$site" fetch -q origin +gh-pages:refs/remotes/origin/gh-pages
	git -C "$site" reset -q --hard origin/gh-pages
	publish
done
exit 1
