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
