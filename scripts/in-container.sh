#!/bin/bash
# in-container.sh <command...>: run a repository command in the CI
# container (image u-boot-ci:1, built from docker/), as the calling user,
# with the checkout at /work. Passes through only the variables the
# commands use; the LAVA and restore ones are empty except in the submit job.
repo=$(cd "$(dirname "$0")/.." && pwd)
exec docker run --rm --network host -u "$(id -u):$(id -g)" -e UBCI_WORK=/work/work \
	-e LAVA_TOKEN -e STOCK_RESTORE_URL_RB3GEN2 -e STOCK_RESTORE_URL_VENTUNO_Q \
	-e STOCK_RESTORE_TOKEN -e STOCK_RESTORE_HEADER -v "$repo:/work" -w /work u-boot-ci:1 "$@"
