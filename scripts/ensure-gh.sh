#!/bin/bash
# ensure-gh.sh: make the GitHub CLI available to the rest of the job.
#
# The CIL runners do not ship `gh`, and the pin workflows need it to list,
# open and comment on PRs and to dispatch pin-candidate. A pinned release is
# fetched, checked against its published SHA-256 and put on GITHUB_PATH, so
# later steps find it without any change to the runner image.
set -euo pipefail

if command -v gh >/dev/null 2>&1; then
	exit 0
fi

ver=2.62.0
case "$(uname -m)" in
x86_64)
	arch=amd64
	sum=41c8b0698ad3003cb5c44bde672a1ffd5f818595abd80162fbf8cc999418446a
	;;
aarch64)
	arch=arm64
	sum=a165413209aab98bfb1db9629b97bc9c59778d38bb7378a33a0363cf822e7965
	;;
*)
	echo "ensure-gh: no pinned gh for $(uname -m)" >&2
	exit 1
	;;
esac

dir="${RUNNER_TEMP:-/tmp}/gh-$ver"
tarball="gh_${ver}_linux_${arch}.tar.gz"
mkdir -p "$dir"
curl -fsSL -o "$dir/$tarball" "https://github.com/cli/cli/releases/download/v$ver/$tarball"
echo "$sum  $dir/$tarball" | sha256sum -c --quiet -
tar -xzf "$dir/$tarball" -C "$dir"
bin="$dir/gh_${ver}_linux_${arch}/bin"
"$bin/gh" --version | head -1
if [ -n "${GITHUB_PATH:-}" ]; then
	echo "$bin" >> "$GITHUB_PATH"
fi
