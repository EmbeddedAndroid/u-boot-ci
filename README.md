# u-boot-ci

Open CI for upstream U-Boot on Qualcomm boards. Every night it takes
U-Boot `main`, runs the checks upstream U-Boot CI runs that matter for the
Qualcomm platforms, and tests it on real boards in a LAVA lab on two
firmware stacks, booting a pristine linux-next. The output is a public
dashboard on GitHub Pages; nothing is posted to the mailing list.

It runs nightly on `main` and on `master`, and on demand for series from
the list stacked onto either ([ad-hoc runs](docs/adhoc-runs.md)), on these
boards:

| board | SoC | LAVA device type | U-Boot on the stock firmware |
|---|---|---|---|
| Qualcomm RB3 Gen 2 | QCS6490 (Kodiak) | `qcs6490-rb3gen2` | replaces UEFI |
| Arduino VENTUNO Q | QCS8275 (Monaco) | `monaco-arduino-monza` | replaces UEFI |
| Arduino UNO Q | QRB2210 (Agatti) | `qrb2210-arduino-imola` | chainloaded by ABL |
| Qualcomm QCS615 Ride | QCS615 (Talos) | `qcs615-ride` | replaces UEFI |
| Qualcomm IQ-9075 EVK | QCS9075 (Lemans) | `lemans-evk` | replaces UEFI |

Automatic intake of every series from the list and U-Boot's own test.py
on the boards follow in later phases.

## Reading the dashboard

The page polls `index.json` once a minute, so a run is visible while it
moves through `queued`, `building`, `flashing`, `testing` and `done`
(or `cancelled` / `error` when its workflow was cancelled or failed).

**The matrix** has one cell per board and firmware stack for the latest
nightly of the branch selected above it (`main` or `master`):

- *state*: where the run is for that cell, with the LAVA queue position
  while it waits, or why it was skipped (for example, no `LAVA_TOKEN`).
- *fingerprint*: every build carries a fresh fingerprint
  (`ubci-<run id>-<attempt>-<stack>-<board>`) in its version string. The
  job passes this gate only when the board's console shows U-Boot (and, on
  the open stack, TF-A BL31 and OP-TEE) with this cell's fingerprint, and
  the pinned BL2 with its own, on the first boot and on the boot that
  starts Linux. A cell whose gate failed ran something else; its results
  are not counted and it raises no regression.
- *boots Linux*: the first-class verdict. Yes means the board reached a
  login prompt on the pristine linux-next payload. No comes with where it
  stopped (no kernel output after the bootloader handed off, kernel
  console never came up, an early panic, no login prompt), the last
  console lines and a link to that line in the LAVA log.
- *cases*: passed, failed and skipped test cases (U-Boot commands, Linux
  smoke checks, the fingerprint gates, the stock restore), flaky ones
  marked.
- *distance to upstream*: for the open stack, how many patches each pinned
  component carries on top of its upstream. The detail view lists each one
  with its review link. Zero everywhere is the goal.

A red banner above the matrix means a Linux boot regression (the baseline
booted, this run did not); an amber one means an upstream gap (the
baseline does not boot either). For a nightly the baseline is the previous
nightly of the same branch; for an ad-hoc run it is the latest nightly of
its base branch.

**Ad-hoc runs** list each requested stack (every series with its version
and patch count, or the patch that did not apply) and per cell the
difference against that baseline: new failures, new passes and the boot
verdict.

**Host checks** list the results of buildman (every snapdragon board,
warnings as errors), the defconfig and fragment combinations, checkpatch on
the day's new commits, the docs build with warnings as errors, test.py on
sandbox and QEMU, the image sizes, and a check that the pins' carried
lists are current.

**Detail** (click a cell) shows the components with their commits and
fingerprints, the boot verdict with the console tail, and every case with
its history over the recent nightlies (oldest left).

## Running it locally

Everything runs in the build container, the same one the CI runners use:

    docker compose -f docker/compose.yaml build
    docker compose -f docker/compose.yaml run --rm ci python3 -m pytest -q tests
    docker compose -f docker/compose.yaml run --rm ci scripts/dry-run.sh /build/dry-run

The dry run renders the LAVA job of every board and stack (validated by
LAVA when `LAVA_TOKEN` is set), builds the dashboard from sample
results into `../work/dry-run/site` (serve it with any static server), and
runs the CI job's script (`scripts/run-all.sh`) with stand-ins for the
checks and builds, once passing and once with a check and a build forced
to fail, to show that every step still runs and the job fails at the end.
Building a real run: see [docs/architecture.md](docs/architecture.md).

## Documentation

- [Architecture](docs/architecture.md): pipeline, jobs, the security
  split, the LAVA job flow and the boundary of the shared `fwci` package.
- [Boards](docs/boards/): per-board boot paths and known gaps.
- [Firmware stacks](docs/firmware-stacks.md): stock and open, pins,
  distance to upstream.
- [How pins are updated](docs/pins.md): the stock pin watcher and its
  validation, open-stack pins.
- [Linux payload](docs/linux-payload.md): what the boards boot.
- [Results schema](docs/results-schema.md): the run document.
- [Ad-hoc runs](docs/adhoc-runs.md): testing stacked series.
- [Flake policy](docs/flake-policy.md): flakes, allowlisted kernel
  errors, known gaps.
- [Adding a board](docs/adding-a-board.md).
- [GitHub and lab setup](docs/setup.md): environments, secrets,
  variables, permissions.
