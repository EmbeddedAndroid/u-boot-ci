# Boot time

Every LAVA job of a run is measured for boot time, per stage, and the
result is stored with its target in the run document (`boot_time`,
[results-schema.md](results-schema.md)).

## Host side: from LAVA's own time stamps

The source of truth is the time LAVA stamps on each console line as it
receives it. No clock on the board is used. The parser is lava-boottime's,
vendored in `fwci/lava_boottime/` ([architecture.md](architecture.md));
`fwci/boottime.py` turns its result into the run document's form.

A job is split into boots at each reference instant:

| reference | boot kind |
|---|---|
| the power-on command of the job's first power-on (after the flash) | `first` |
| the power-on command of any later power-on | `cold` |
| U-Boot's `resetting ...` line (its `reset` command) | `warm-reset` |
| the kernel's `reboot: Restarting system` line | `warm-reboot` |

A stage is the arrival of the first console line that marks it, minus
the reference:

| stage | console line |
|---|---|
| `loader` | the first XBL line (log header or `B -` record) |
| `loader_end` | `SBL1, End` |
| `hyp` | `Hypervisor cold boot` (downstream firmware) |
| `uefi`, `ebs` | `UEFI Start`, `Start EBS` (downstream UEFI or ABL) |
| `spl`, `bl2`, `bl31`, `optee` | the U-Boot SPL, TF-A BL2, BL31 and OP-TEE banners |
| `uboot` | `U-Boot 20xx.` |
| `linux` | `Booting Linux on physical CPU` |
| `init` | `Run /init as init process` |
| `login` | LAVA's match of the login prompt |

A boot that stops (a hang, a failed boot, a job that times out) keeps the
stages it reached and names the last one; a board that starts over
without a power command (watchdog, firmware reset) has the time of that
restart in `reset`, and what follows is not counted.

**Replayed lines.** The dispatcher does not read the console while a
blocking power command runs, and the console server replays what it
buffered when reading resumes; LAVA logs that backlog in one burst. A
stage that arrived in such a burst is marked `replayed`: its time only
bounds the stage from above, so it is shown but never compared. On most
boards of the lab the first XBL lines of a power-on are replayed (the
power command takes about 2.3 s).

**Cold boot is the headline.** Warm resets and reboots skip the power-up
path, and the first power-on after a flash can retrain DDR (seconds), so
each kind is its own series and never compared with another. The target
is judged by its last `cold` boot (`boot_time.headline`), and the time to
`linux` ("Booting Linux") is the number the dashboard leads with: the
firmware is done there. `init` and `login` are shown but depend on the
image as much as on the firmware.

Each u-boot-ci job has one cold boot for this: after the U-Boot checks,
the Linux smoke checks, the warm reboot and the poweroff, the board is
powered on again, passes the fingerprint gate once more and boots to the
login prompt without being stopped (see [architecture.md](architecture.md)).
Jobs from before this cold boot was added have none: their `headline` is
null, and the dashboard shows their warm-reset boot, labelled as such.

## On target: from the kernel's own clock

Where the image carries it, the job also runs the test-definitions
`boot-time` case on that cold boot (after login). It reports, from the
kernel's own clock: `pre-kernel` (the Arm generic timer's count at a
kernel log line minus that line's time stamp: firmware plus the kernel's
early setup, skipped where a hypervisor may offset the counter, that is
on every downstream stack whose Linux runs at EL1), `kernel-to-init` and
`kernel-to-login`. These are stored apart, in `boot_time.on_target`, with
the boot they ran in, and are never mixed with the host-side numbers: the
zeros differ (counter reset against the power-on command).

The case is test-definitions' own, unchanged. `scripts/build-boottime-case.sh`
fetches the commit `config/project.yaml` pins (`boottime_case`: repository,
branch, commit) and packs `boot-time.sh`, its `cntvct-arm64` tool and
`sh-test-lib` into a small cpio, which `scripts/mk-esp.sh` adds to the UKI
as a third initrd; `esp.json` records it and the run document carries it
in the Linux component (`boottime_case`: repository, commit link, the
sha256 of every file). The job runs the case only when the target's UKI
carries it, as one shell check (suite and case `boot-time`), and the
collector reads the values the case printed. While the pin is `pending`
(its commit not public yet) nothing is packed and no job runs the case.
For a local run, `UBCI_BOOTTIME_CASE_REPO` fetches the pinned commit
from another repository, a local checkout for example; the commit, and so
the bytes, are the pin's.

## Against the baseline

`fwci.baseline` compares every target with the same board and stack of
the baseline run (the previous nightly of the branch, or the nightly an
ad-hoc run is based on), boot kind by boot kind, in
`boot_time.versus_baseline.kinds`. A kind is compared by its cold
headline boot, or by the last boot of that kind. Only targets whose
fingerprint gates both passed are compared, and only stages that were
timed (not replayed) in both.

The verdict is taken at "Booting Linux", or at the last stage before it
that both boots timed (a board that never reaches Linux is still compared
up to U-Boot):

| verdict | meaning |
|---|---|
| `regression` | later than the baseline by more than the threshold |
| `improvement` | earlier by more than the threshold |
| `same` | within the threshold |
| `stopped-earlier` | the baseline reached "Booting Linux", this run did not |
| `no-history` | fewer than 5 earlier runs of the series: the difference is shown, not judged |
| `unknown` | no baseline boot of that kind, or a fingerprint gate failed |

**The threshold comes from the data.** For each board, stack, boot kind
and stage, sigma is the robust spread of that series over the 10 newest
earlier nightlies of the same base branch whose gate passed (1.4826
times the median absolute deviation, which a few outlying runs do not
move), and the threshold is 3 standard deviations of the difference of
two boots, 3 * sqrt(2) * sigma, never under 20 ms (LAVA reads the
console in chunks of up to 20 ms, the parser's resolution). Over the
published history up to 2026-11-01 the spread of one series runs from 1
ms to 190 ms (median absolute deviation; RB3 Gen 2 warm reset to Linux:
110 ms), so a fixed threshold would be too loose for some boards and too
tight for others. Each comparison records the stage, both times, the
difference, sigma, the threshold and how many runs it came from, per
stage as well.

## Stock reference

Every board also gets a third series next to the downstream and open
stacks: its stock firmware booting the lab's own image, as the lab's
health checks do it (stock UEFI, or ABL on UNO Q, to Linux). Once per run,
before collecting, the submit job runs `ubci.run stockref`: for each board
of the run, the 5 newest completed health checks of its LAVA device type
that ended before the run was created (on devices
`lava.exclude_devices` does not leave out), each measured like a CI job,
read through LAVA's public REST API without a token. A health check
counts by its last power-on (the first one after its flash can retrain
DDR). The run document keeps the boots with their job links in
`boot_time_reference`, and per stage the median over those boots, only
where every one of them timed the stage (dropping the replayed ones would
keep only the slow, live boots).

Only the firmware stages are a fair comparison, up to "Booting Linux":
the health checks boot their own kernel and rootfs, not the pristine
linux-next of the CI, so their `init` and `login` say nothing about
U-Boot. RB3 Gen 2 health checks boot the kernel over fastboot: their
firmware stages all arrive in replayed backlog (untimed) and their Linux
time includes the download.

## On the dashboard

- **Every matrix cell** shows `boot → Linux`: the cold boot's time to
  "Booting Linux" (for a run from before cold boots were recorded, the
  warm reset's, labelled as such; for a boot that stopped earlier, where
  it stopped), and the verdict against the baseline when there is one:
  "▲ slower" or "■ stopped earlier" (red), "▼ faster" (green), with the
  difference; hovering it gives the threshold.
- **The Boot time section** (`dashboard/boottime.js`, data in
  `index.json`: `boottime` per branch, `stock_boottime`) has one card per
  board. The bars show the latest boot of each series to "Booting Linux",
  stock first, each split into three phases: XBL (to `SBL1, End`), what
  runs before the bootloader (TF-A BL2/BL31, OP-TEE, a hypervisor, an
  SPL) and the bootloader (UEFI, ABL, U-Boot) up to "Booting Linux". A
  phase boundary that was replayed merges its two phases into one gray
  span; a boot that stopped is drawn up to its last timed stage. The
  history plots the time to "Booting Linux" of every nightly of the
  branch and every stock health check; the crosshair lists every stage of
  the nearest boot and each point links to its line in the LAVA log. A
  table under each card lists every boot with links to each stage's line.
  The row above the cards selects the boot kind (cold boot, warm reset,
  warm reboot); a kind is never drawn next to another. Stock health checks
  are cold boots, so they show in the cold view only, and health checks
  that send the kernel over fastboot (RB3 Gen 2) are listed but not drawn:
  their Linux time includes a download that depends on the device's lab
  wiring (6 to 19 s across the RB3 Gen 2 devices).
- **The detail view** of a cell lists every boot of its job with each
  stage linked to its log line (replayed ones in parentheses), the
  verdict per boot kind, and the on-target view separately.

Series colors are slots 1 to 3 of a categorical palette validated for
color-vision deficiency in light and dark (stock blue, downstream orange,
open aqua; SPL takes slot 4); phases are steps of the series color.
Values and names are text set with `textContent`, never HTML.
