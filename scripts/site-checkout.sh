#!/bin/bash
# site-checkout.sh <dir>: check the GitHub Pages branch out as a worktree
# at <dir>, or start an empty gh-pages branch there when the remote has
# none yet.
#
# Run it through in-container.sh, like publish-site.sh that uses the
# worktree: git records the worktree by absolute path, so one created on
# the runner (checkout under /opt/actions-runner/...) is not a repository
# inside the container (checkout at /work), and the other way round.
set -euo pipefail
[ $# -eq 1 ] || { sed -n '2p' "$0" >&2; exit 1; }
site=$1
if git fetch -q origin +gh-pages:refs/remotes/origin/gh-pages 2>/dev/null; then
	git worktree add -q --detach "$site" origin/gh-pages
else
	git worktree add -q --orphan -b gh-pages "$site"
fi
