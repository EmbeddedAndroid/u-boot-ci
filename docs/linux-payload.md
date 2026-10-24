# Linux payload

Every board, on both firmware stacks, boots the same kind of payload, built
from upstream only, so the dashboard shows the real upstream state.

## What is in it

| part | source |
|---|---|
| kernel `Image` | the newest `next-YYYYMMDD` tag of linux-next, `make defconfig` (arch/arm64/configs/defconfig), no fragments, no patches, GCC 14.2.0 (kernel.org) |
| device tree | the board's DTB from that same build (`DTC_FLAGS=-@`, so overlays apply); on the open stack the upstream EL2 overlay of the SoC applied with `fdtoverlay` where linux-next has one (`config/boards/<board>.yaml`, `linux.overlays`) |
| initramfs, part 1 | Buildroot 2026.08.1 with `config/buildroot/initramfs_defconfig`: BusyBox, eudev, kmod, a root login on `ttyMSM0` |
| initramfs, part 2 | `/lib/modules` of the same kernel build (stripped), so the drivers defconfig builds as modules (UFS, QMP PHYs, ...) load at coldplug |
| command line | `console=ttyMSM0,115200n8` |

`scripts/build-linux.sh` builds the kernel, DTBs and modules once per tag
(CI caches them by tag) and records the tag, commit, kernel release and
sha256 of the Image and modules (`linux.json`, copied into the run
document). `scripts/build-initramfs.sh` builds the userspace once per
Buildroot release and defconfig. `scripts/mk-esp.sh` packs them with
`ukify` and the systemd-boot stub into a UKI, written to a FAT ESP as
`EFI/BOOT/BOOTAA64.EFI`, the removable-media path U-Boot's EFI boot
manager falls back to. `esp.json` next to it lists every input hash.

## Checks

- The job's Linux gate requires the version banner to carry the tag
  (`Linux version 7.3.0-next-20261023 ...`).
- "Boots Linux" passes when the Buildroot login prompt appears.
- After login the smoke checks run (see [architecture.md](architecture.md)).

## Gaps

Where linux-next lacks something a board needs to reach the smoke test,
nothing is patched: the case fails and the dashboard shows it, with the
missing piece named when it is known (`linux.gaps` in the board config,
shown in the cell's detail). Example: linux-next has no Kodiak EL2 overlay,
so the RB3 Gen 2 open stack boots the base DT at EL2.
