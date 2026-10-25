#!/bin/bash
# checkout.sh <name> <repo> <commit>
#
# A clean tree of <commit> in $UBCI_WORK/src/<name> (cloned on first use);
# prints its path.
set -euo pipefail
[ $# -eq 3 ] || { sed -n '2p' "$0" >&2; exit 1; }
repo=$(cd "$(dirname "$0")/.." && pwd)
d=${UBCI_WORK:-$repo/work}/src/$1
[ -d "$d/.git" ] || git clone -q "$2" "$d"
# From <repo>, not origin: boards may pin one name (optee_os) from
# different repositories (upstream and a fork).
git -C "$d" cat-file -e "$3^{commit}" 2>/dev/null || git -C "$d" fetch -q "$2" "$3"
git -C "$d" checkout -q --detach "$3"
git -C "$d" clean -qfdx
echo "$d"
