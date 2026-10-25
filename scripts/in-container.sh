#!/bin/bash
# in-container.sh <command...>: run a repository command in the CI
# container (image $UBCI_IMAGE, default u-boot-ci:1, built from docker/;
# the prepare job uses u-boot-ci-control:1), as the calling user,
# with the checkout at /work. Passes through only the variables the
# commands use; the LAVA and BL2 ones are empty except in the submit
# jobs.
repo=$(cd "$(dirname "$0")/.." && pwd)
exec docker run --rm --network host -u "$(id -u):$(id -g)" -e UBCI_WORK=/work/work \
	-e LAVA_TOKEN \
	-e PIN_BL2_RB3GEN2 -e PIN_BL2_VENTUNO_Q -e PIN_BL2_UNO_Q -e PIN_BL2_QCS615_RIDE \
	-e PIN_BL2_LEMANS_EVK \
	-v "$repo:/work" -w /work "${UBCI_IMAGE:-u-boot-ci:1}" "$@"
