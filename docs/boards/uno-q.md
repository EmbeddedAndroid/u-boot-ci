# Arduino UNO Q (QRB2210, Agatti)

LAVA device type `qrb2210-arduino-imola`, eMMC (user area, LUN 0), debug
UART `ttyMSM0`.

## Downstream boot path: ABL chainloads U-Boot

The downstream firmware is what meta-qcom-arduino pins for `uno-q`
([66170f2](https://github.com/qualcomm-linux/meta-qcom-arduino/commit/66170f27dea1c40781b871b6482ef886a7663232),
`recipes-bsp/firmware-boot/firmware-qcom-boot-qrb2210-arduino-imola_251020.bb`):
Arduino's boot firmware 251020 (XBL, TZ, the QTI hypervisor, ABL) on the
`qrb2210-unoq-abl-arduino` eMMC layout of qcom-ptool. On this firmware ABL
loads the kernel from `boot_a`/`boot_b` as an Android boot image, and
meta-qcom-arduino puts U-Boot there (`recipes-bsp/u-boot/u-boot-arduino_git.bb`:
`qcom_defconfig`, gzipped `u-boot-nodtb.bin` with the board DTB appended,
`mkbootimg --base 0x80000000 --pagesize 4096`), which is also how
`doc/board/qualcomm/board.rst` in U-Boot describes booting a board whose
firmware ends in ABL. So the CI does the same: U-Boot under test is built
with `qcom_defconfig` and `DEVICE_TREE=qcom/qrb2210-arduino-imola`, packed
by `ubci.bootimg` (header version 0, byte for byte what that recipe's
`mkbootimg` writes) and written to `boot_a`/`boot_b`. UEFI is not replaced:
it is part of XBL on this firmware. The lab's own image boots the same
chain (XBL, UEFI, ABL, U-Boot, Linux; LAVA job 511188).

The board's CDT lives in the eMMC boot partition and is not rewritten.

meta-qcom-arduino moved uno-q to the edk2-based QRB2210 release in
September and back to this ABL firmware in
[36740ca](https://github.com/qualcomm-linux/meta-qcom-arduino/commit/36740ca1aeef956305a4f1403a3fca8dcb477faf)
(boot hangs on the edk2 firmware); the pin watcher follows the recipe.

## Open stack

TF-A BL2 in `tz_a`/`tz_b` loads the FIP (BL31, OP-TEE, U-Boot) from
`uefi_a`/`uefi_b`. The ABL firmware's XBL does not do that, so the open
stack is built on the edk2-based release meta-qcom pins
(`firmware-qcom-boot-qrb2210_00021.bb`, QRB2210 boot binaries 00021) with
the `qrb2210-unoq-arduino` layout: `downstream_open` in
`config/boards/uno-q.yaml`, pinned by hand.

TF-A `PLAT=uno_q`, the FIP wrapped at 0x5f800000; BL2 is QTI-signed and
pre-signed (fingerprint `QCDFP-261024-68`); OP-TEE `qcom-agatti`. Both pin
the hardware-gated `qcom/integration` snapshot of 2026-10-24/25 on the
EmbeddedAndroid forks (platform branches `qcom/agatti`). Those commits
are not public yet, so the open stack is skipped with that reason until
the branch is pushed; the pins then move to its head. U-Boot:
`qcom_defconfig` + `tfa-optee.config` + the board fragment
`arduino-uno-q.config` when the base has it (the UNO Q series adds it;
the dashboard flags it when it is missing).

## Known gaps

- linux-next has no Agatti EL2 overlay, so the open stack boots the base
  DT at EL2.
