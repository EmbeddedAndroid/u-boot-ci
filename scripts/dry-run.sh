#!/bin/bash
# dry-run.sh <output dir>: render and validate every LAVA job and build the
# dashboard from sample results, without building or flashing anything.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m ubci.dryrun "${1:-work/dry-run}"
