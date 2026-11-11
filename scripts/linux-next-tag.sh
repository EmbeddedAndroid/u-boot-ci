#!/bin/bash
# linux-next-tag.sh [repo]: print the newest next-YYYYMMDD tag of linux-next.
#
# git.kernel.org answers the tag listing with an HTTP 5xx now and then; an
# empty answer used to become an empty LINUX_TAG and every board cell then
# failed with "no Linux payload". Retry, and fail with the reason when no tag
# comes back, so the run stops in prepare instead.
set -euo pipefail

repo=${1:-${LINUX_NEXT:?LINUX_NEXT is not set}}
tries=${UBCI_LS_REMOTE_TRIES:-5}
delay=${UBCI_LS_REMOTE_DELAY:-20}

for i in $(seq 1 "$tries"); do
	if out=$(git ls-remote --tags "$repo" 'refs/tags/next-*'); then
		tag=$(printf '%s\n' "$out" | sed -n 's|.*refs/tags/\(next-[0-9]\{8\}\)$|\1|p' | sort | tail -1)
		if [ -n "$tag" ]; then
			echo "$tag"
			exit 0
		fi
		echo "linux-next-tag: attempt $i/$tries: no next-* tag in the listing" >&2
	else
		echo "linux-next-tag: attempt $i/$tries: git ls-remote failed" >&2
	fi
	[ "$i" -lt "$tries" ] && sleep "$delay"
done
echo "linux-next-tag: no linux-next tag from $repo after $tries attempts" >&2
exit 1
