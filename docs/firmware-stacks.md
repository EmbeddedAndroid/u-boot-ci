# Firmware stacks

Each board is tested on three stacks; only U-Boot changes between runs.
The stack ids in run documents, fingerprints and the case history are
`stock`, `open` and `spl`; the dashboard and the job names say
"downstream firmware" for `stock` and "U-Boot SPL" for `spl`.

## Downstream firmware (`stock`)

The boot firmware the board's meta layer ships: the public boot binaries
and CDT its recipes pin (`downstream` in `config/boards/<board>.yaml`:
URL and sha256 of each archive and the meta layer commit the pin was read
at), with the partition layout qcom-ptool generates for the board. The
U-Boot under test goes where that firmware loads it, per board
([boards/](boards/) says which and why):

- in place of UEFI in `uefi_a`/`uefi_b` (RB3 Gen 2, VENTUNO Q, QCS615 Ride,
  Lemans EVK), as `u-boot.mbn` signed by U-Boot's own `mkmbn` (a tree
  without it, `master` at v2026.07, has `u-boot.elf` signed by the pinned
  `qtestsign -v6 aboot` as its board docs say);
- as the Android boot image ABL chainloads from `boot_a`/`boot_b` (UNO Q:
  `u-boot.stock.slot: boot.img`, built by `ubci.bootimg`).

Everything else, including the QTEE `tz.mbn` and the hypervisor, is the
release as published. The run document lists the release, every archive
with its download link and sha256, and the meta layer commit with a link.

## Open

The open-source stack: what XBL loads from `tz_a`/`tz_b` and from
`uefi_a`/`uefi_b`, every other boot image as in the downstream package
(or `downstream_open`, when the board's open stack needs other boot
firmware: UNO Q). By the TF-A pin's `image`:

- `fip.elf` (default): TF-A BL2 in `tz`, which loads a FIP from `uefi`
  holding TF-A BL31, OP-TEE (BL32) and U-Boot (BL33);
- `uefi.itb` (Lemans): U-Boot SPL in `tz`, which loads a FIT from `uefi`
  holding BL31, OP-TEE, U-Boot and its control DTB (`ubci/fit.py`, the
  load addresses in the pin's `fit`).

Pins (`config/pins.yaml`), per board:

- `tf-a`: repository, branch and commit, build flags, FIP load address
  or FIT addresses, the platform branch the commit integrates
  (`soc_branch`) where there is one. BL31 is built from it on every run,
  with the run fingerprint as the build string.
- `optee`: same, built on every run with the run fingerprint as its
  version and the pin's extra `make_args` (early TAs).
- `bl2`: the image XBL loads from `tz`, signed in advance (XBL only starts
  a signed tz image) and pinned by file name, sha256 and its own
  fingerprint: TF-A BL2 of the tf-a pin (RB3 Gen 2 with an OEM TEST
  signature from Qualcomm's public sectools, `scripts/sign-bl2-oem.sh`;
  the other boards with a QTI signature, pre-signed), or on Lemans a
  pre-built U-Boot SPL (`banner: U-Boot SPL`, `origin: downstream`: there
  is no Lemans SPL in U-Boot `main`). The binaries are not redistributable:
  CI gets them from the `PIN_BL2_<BOARD>` secrets of the LAVA
  environments, only in the submit job, and checks the sha256 before
  adding them to the package ([setup.md](setup.md)); the dashboard shows
  the sha256 only.
- `pending`: set while the pinned commit is not public yet (the new
  boards pin the hardware-gated `qcom/integration` snapshot until that
  branch is pushed). The open stack of that board is then skipped with
  "open-stack pin not public yet" instead of failing its build, and
  carries no distance to upstream.
- `qtestsign`: the tool that wraps the FIP in a signed ELF (and signs
  `u-boot.elf` for the downstream stack on a tree without `mkmbn`).

The FIP or FIT is rebuilt for every run with the U-Boot under test
(`scripts/build-open-stack.sh`).

## U-Boot SPL (`spl`)

The open stack with its first U-Boot stage built from the tree under test
too: U-Boot SPL and U-Boot proper come from the same tree and config
(`u-boot.spl` in the board file), carry the same fingerprint, and the SPL
replaces the image the board's SPL boot flow puts it in. On the other
stacks the image before BL31 is pinned (TF-A BL2, or the pre-built Lemans
SPL), so an SPL regression or an SPL series in review is invisible there.

Per board (`spl` in `config/boards/<board>.yaml`):

- `slot`: the package file the SPL replaces: `tz.mbn` when XBL stays the
  first stage and loads the SPL as its TZ image (Lemans), `xbl.elf` when
  the SPL is the first stage the boot ROM loads and brings up DRAM
  itself.
- `sign`: the `qtestsign -v6` image type, `tz` or `sbl1`, and `swiv`: the
  platform of the SWIV annotation XBL wants on a TZ image
  (`swiv_build_utility.py`, pinned as `swiv` in `config/pins.yaml`, the
  commit meta-qcom pins). `scripts/build-uboot.sh` annotates and signs
  `spl/u-boot-spl.elf` (`CONFIG_SPL_REMAKE_ELF`) into `spl.mbn` and checks
  the fingerprint is in it.
- `pre_ddr`: for an SPL that brings up DRAM, the boot firmware blobs it
  loads first (PMIC and DDR configuration, SHRM, QcLib, ECC), each with
  the file name in the downstream boot binaries, its sha256 and its load
  and entry address. `ubci.package blobs` takes them from the pinned
  archives and refuses a missing blob or another sha256; nothing is
  committed.
- `in_flight`: the series on the list that would add SPL support for
  the board (title, version, Message-ID), and `gaps`: what no posted
  series provides.

The FIT the SPL loads from `uefi_a` (`ubci/fit.py`) holds BL31, OP-TEE,
U-Boot and its control DTB at the TF-A pin's `fit` addresses, in a
configuration described `post-ddr`: the name the mach-snapdragon SPL
(`board_fit_config_name_match()`) selects once DRAM is up; an SPL without
that hook takes the default, which is the same configuration. A board
with `pre_ddr` blobs gets a `pre-ddr` configuration of them too. U-Boot
has no posted FIT template for this, so the recipe is the CI's own,
following the layout meta-qcom builds (`qcom-uboot-spl-fit.inc`).

TF-A and OP-TEE are the board's open-stack pins; the `bl2` pin is not
used. The job's fingerprint gate checks the SPL banner (`U-Boot SPL`),
BL31, OP-TEE and U-Boot proper, all with the target's one fingerprint, so
a pinned SPL can never pass it.

When the board's SPL defconfig (the first of `u-boot.spl.configs`) is
not in the tree the target is skipped, never failed and never hidden: "no
upstream SPL" on a nightly base, "no SPL in the tested tree" on an
ad-hoc stack. A board without `u-boot.spl` has no SPL config to look
for: "no SPL stack for this board". Each reason goes on with the gaps and
the series in flight, or "no SPL in flight for this board".

The gates start at XBL's end marker (`lava.xbl_marker`), as on the other
stacks: on Lemans XBL still runs before the SPL. A board whose SPL is the
first stage (Shikra) needs another start marker once it gets an SPL
config.

## The boot chain

`boot_chain` in each board file lists every stage per stack, each marked
`upstream`, `downstream` or `none` (a stage the chain does not have, such
as the hypervisor on the open stack), with the component it links to.
Every target of a run document carries it, and the dashboard shows it per
cell and in the detail view, so a reader sees at a glance what runs
downstream (XBL, QTEE, Gunyah, ABL, the Lemans SPL) and what upstream
(TF-A, OP-TEE, U-Boot, Linux) on every board.

## Distance to upstream

`config/carry.yaml` lists, for every pinned component, the commits it
carries that its upstream does not have, each with its review link (the
Gerrit change for TF-A, a `Link:` trailer otherwise; none when the patch was
never posted). It is generated by `python3 -m ubci.carry` (patch-id and
subject match against upstream) and checked in CI; the run document and
the dashboard show the count and the list per board and component. A
pending pin has none until its commit is public. The end state is zero
everywhere: then the open stack is plain upstream.

## Bumping a pin

See [pins.md](pins.md): downstream pins are bumped by the pin watcher's
pull requests, open-stack pins by hand, all reviewed by Tyler.
