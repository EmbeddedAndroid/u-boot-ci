# Architecture

## Pipeline

A run is `.github/workflows/run.yml`, a reusable workflow with the base
branch (`main` or `master`), the kind (`nightly` or `adhoc`) and, for an
ad-hoc run, the series to stack on the base
([adhoc-runs.md](adhoc-runs.md)). `nightly.yml` calls it once per
branch every night; `adhoc.yml` (workflow_dispatch) and `adhoc-issue.yml`
(an issue form, started by the `adhoc-approved` label) call it for
ad-hoc runs.

A run is three jobs (four when it ends early, see `finalize`), one after
the other, each on its own self-hosted CIL runner
(`runs-on: [self-hosted, cil, [arm64,] <cpu>c-<ram>g-<disk>g]`):
one ephemeral VM per job, sized from the label; fork pull requests are
dropped before they reach a runner. Only `ci`, which does all the work on
the code under test, leases from the xeon pool (at most 32 CPUs, 32 GB,
750 GB per lease, one host). `prepare` and `submit`, and the request jobs
of the ad-hoc workflows, carry the `arm64` label and lease small VMs from
the arm64 pool (at most 4 CPUs, 8 GB, 200 GB per lease; one host, two
leases at a time), which keeps their load and power draw off the xeons.
Every job builds a container from `docker/` and runs the repository's
commands in it (`scripts/in-container.sh`), the same container used
locally: the CI image for `ci`, the control image (`--target control`:
git, curl, b4 and the Python of the run document and the LAVA client)
for `prepare`, `submit` and `finalize`. Both images build on x86_64 and
arm64.

| job | runner | runs U-Boot code | secrets | does |
|---|---|---|---|---|
| prepare | CIL arm64, `2c-4g-20g` | no | none (writes gh-pages) | resolves the branch commit, the newest linux-next tag and the latest nightly of that branch (the baseline); for an ad-hoc run fetches the series with b4 and applies them with `git am` (`ubci.stack`); creates the run document (`ubci.run new`) and publishes it, state `building` |
| ci | CIL xeon, `32c-32g-200g` | yes | none | builds pristine linux-next and the initramfs once per tag and config (Actions cache, [linux-payload.md](linux-payload.md)) and uploads them, then `scripts/run-all.sh`: applies the stack of an ad-hoc run, runs the host checks (`scripts/host-check.sh`: carry, buildman, fragments, checkpatch, docs, sandbox and QEMU test.py), builds every queued board and stack (`scripts/build-target.sh`: U-Boot with the run fingerprint, for the open stack TF-A BL31 + OP-TEE from the pins and the FIP, the ESP with the UKI, the qcomflash package) and sizes every build |
| submit | CIL arm64, `2c-4g-20g` | no | environment `lava-hw`: `LAVA_TOKEN`, restore URLs, BL2 pins (writes gh-pages) | records the Linux payload and the host checks, adds the BL2 to the open-stack packages, uploads each package to the LAVA artifact store, submits the jobs (device choice and cap below), collects results every 5 minutes and republishes the dashboard until the run is done |
| finalize | CIL arm64, `2c-4g-20g`, only when the run ended before `submit` did | no | none (writes gh-pages) | closes the published run document (`ubci.run close`): the run and its unfinished targets become `cancelled` after a cancel, `error` after a failure, with the reason |

`run-all.sh` runs every step whatever the earlier ones did: a failing check,
a check that could not run or a failed build is recorded and the next step
runs; the job fails at the end when any did. Each check leaves its
`<check>.json` (result and summary) and `<check>.log`, each build its
`build-<board>-<stack>.log`, all in the `<base>-host` artifact; the packages
are the `<base>-packages` artifact, and a failed build leaves no package.
A target without a package gets `<board>-<stack>.build.json` in that
artifact instead: `fail` with the last line of its build log (the submit
job marks it `error` with that reason), or `skip` when the tree does not
have the board at all, its device tree or a config missing
(`python3 -m ubci.config missing`; `master` before a board's DT was
imported): that target is `skipped` with "board not in this base: ..." and
does not fail the job.
When the stack of an ad-hoc run does not apply, only carry and size run.
`submit` starts when `ci` failed too (`!cancelled()`), so the host checks
and the boards that did build still reach the dashboard and LAVA; it does
not start after a cancel. `finalize` is the one job that does, and it
also starts when `submit` failed or never ran: without it the run
document stays `building` or `testing` on the dashboard for ever. A LAVA
job of a cancelled run is not cancelled; its target says it was not
collected.

The security split: list patches are untrusted code, so `ci`, the only job
that builds or executes it, holds no secret, declares no environment, gets
a read-only token and does not leave that token in the checkout
(`persist-credentials: false`). It saves the Linux payload to the Actions
cache and uploads it before the first patch is applied, so a series cannot
change the kernel later runs boot, or its own. `prepare` writes gh-pages;
it applies patches but runs nothing from them. Only the submit job declares an environment
([setup.md](setup.md)): `lava-hw`, which deploys from `main` only, for
the nightly and ad-hoc runs; `lava-pr`, which waits for a reviewer, for
the pin-candidate job that runs PR-branch code.
The submit job only moves the packages `ci` produced (opaque bytes)
to LAVA and reads results back; it never executes them. Console text that
comes back is data: the dashboard sets it as text, never as HTML. The
host-check results `ci` reports are data from untrusted code too: a
series can fake its own run's results, never another run's.

Each job is pinned to a device: the submit job picks a board of the
device type in Good health, idle ones first, leaving out the devices
`config/project.yaml` `lava.exclude_devices` names (the production
boards, `*-production-*`). The in-flight cap (`lava.max_in_flight` per
device type) counts the whole lab's u-boot-ci jobs, queued and running,
so the `main` and `master` nightlies and ad-hoc runs together never hold
more boards than that. The device list does not say which devices the
LAVA user may submit to; LAVA refuses a job pinned to one it may not
("You do not have permission to submit jobs to device ..."), creating no
job, and the submit job then picks the next device. A target whose every
healthy device refused is `error` with the devices named. Any other refusal
(an HTTP 4xx answer, no job created) is `error` with LAVA's message. A
submit that fails without an answer marks the target `error` ("submit
outcome unknown") and is never resubmitted, so a job is never duplicated.

When `LAVA_TOKEN` is not set the submit job marks every hardware cell
`skipped` with the reason and publishes the host checks alone. A board
with no lab restore image configured is skipped the same way, because
every job must end on the lab's downstream firmware.

## Hardware tests

Per board and firmware stack, one LAVA job (`ubci/jobs.py`), public, at
low priority:

1. Flash the package with qdl (full layout, as the lab's own images do).
2. Power on; **fingerprint gate** from XBL's `SBL1, End` to U-Boot's
   `DRAM:` line: U-Boot (downstream firmware stack), or BL2 or SPL (pinned fingerprint), BL31,
   OP-TEE and U-Boot (open) must each print their fingerprint.
3. Stop autoboot and run the **U-Boot checks** of the board config
   (`version`, `bdinfo`, `dm tree`, `clk dump`, storage, `usb tree`,
   `efidebug dh`, `bootflow scan -l`), then `reset`. Each command line
   ends with an `echo` of an end marker and its step waits for that
   marker, not for the `=> ` prompt, after one sync step that does
   nothing else: a stray prompt (line noise run as a command at the first
   prompt) cannot shift the checks onto each other's output, and no
   command is typed while U-Boot is still printing.
4. The gate again on that boot (the fingerprint gate passes only when
   both boots show the build), then U-Boot autoboots (its default
   `bootefi bootmgr`) the UKI from the ESP.
5. **Linux**: the version banner must name the linux-next tag; login at
   the Buildroot prompt (the "boots Linux" verdict); smoke checks: the
   tag in `/proc/version`, all CPUs online, modules loaded, no kernel
   errors (`dmesg` level 0-3, less the allowlisted firmware-file lines of
   `config/known-errors.yaml`, [flake-policy.md](flake-policy.md)), the
   board's storage readable, USB, a network interface. A case the board
   config lists under `known_gaps` (RB3 Gen 2 USB) is reported `skip`
   with the gap as its note, not as a failure.
6. `reboot`: the gate a third time and a second login (warm reset path).
7. `poweroff`, then flash the lab's image back and check its UEFI
   starts.

The Linux the boards boot is a pristine linux-next (latest tag, upstream
arm64 defconfig, no patches, DTB and upstream overlays from the same tree).
Where linux-next lacks something a board needs, the case fails and the
dashboard says so; nothing is patched.

A hang or a timeout ends a LAVA job before its own restore. The collector
then submits a recovery job (`ubci/restore.py`) pinned to the same device
at medium priority and records its result as the cell's restore.

U-Boot's own test.py on the boards (LAVA board sessions as the hooks) is
phase 3.

## Results

One run document per run, schema `fwci-run/1`
([results-schema.md](results-schema.md)). The collector
(`fwci.collect`) turns each LAVA job (record, results, log) into a target:
state, cases with links to their log lines, the fingerprint gate, the boot
verdict (`fwci.boot_verdict`) and the restore. `fwci.baseline` compares the
run with its baseline per board and stack (new failures, new passes, still
failing, the boot verdict against the baseline's) and `fwci.flakes` marks
known flakes. `fwci.site` builds `index.json` from the run documents, and
`scripts/publish-site.sh` pushes them with the dashboard to the gh-pages
branch.

## Generic and U-Boot-specific code

`tf-a-ci` and `optee-ci` will reuse the framework, so it is split:

- `fwci/` holds nothing U-Boot specific and imports nothing from `ubci/`:
  the results schema (`schema.py`, `schema/run.schema.json`), LAVA job
  building blocks for "pinned components + one component under test"
  (`lava_jobs.py`: qdl flash, fingerprint gate over any banner prefixes,
  interactive bootloader and shell checks, login, a restore), the
  collector, the boot verdict, the baseline diff, the flake list, the
  distance to upstream (`carry.py`), the LAVA MCP client and the
  dashboard data (`site.py`). The dashboard page (`dashboard/`) only reads
  `index.json` and run documents.
- `ubci/` and `scripts/` are the U-Boot project: which boards and stacks,
  how a target is built and packaged, the job flow with U-Boot's prompt and
  checks, the run command line.
- `config/` is data: boards, pins, carried patches, flakes, project.

A sibling CI copies or vendors `fwci/` and `dashboard/` and writes its own
equivalent of `ubci/` (the component it swaps, its banner prefixes, its
checks). Intake helpers (lore watcher, Gerrit and GitHub PR polling) come
in phase 2 and go to `fwci/` when they are generic.

## Local runs

The same steps run from a laptop: `scripts/build-target.sh` in the
container builds a target; `python3 -m ubci.run new|submit|collect|site`
drives a run with `LAVA_TOKEN`, the `STOCK_RESTORE_*` and `PIN_BL2_*`
values in the environment. The phase-1 validation runs were submitted this way.
