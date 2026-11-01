# Qualcomm SM8750 MTP (Pakala, Wildcat)

LAVA device type `sm8750-mtp`, UFS, debug UART `ttyMSM0`.

## Firmware: the open stack only

The board boots XBL from what meta-qcom pins for `sm8750-mtp`
([af39508](https://github.com/qualcomm-linux/meta-qcom/commit/af39508715abfa06e0abd6e3d8e1228acf374f7d):
`firmware-qcom-boot-sm8750_00045.bb`): SM8750 boot binaries 00045 with qcom-ptool's `sm8750-mtp` UFS layout, LUNs 0, 1, 2 and 4
written; LUN 3 (CDT, DDR training) and LUN 5 stay as the lab wrote them.
The EDL programmer is `xbl_s_devprg_ns.melf`.

TF-A (PLAT=sm8750_mtp) and OP-TEE are built from the internal
`qcom/integration` (tag `qcom/integration-20261101`), gated on this
board, and pinned as images ([private-firmware.md](../private-firmware.md)):
BL2 in `tz_a`/`tz_b`, QTI-signed, fingerprint `QCDFP-261101-475` on BL2, BL31 and
OP-TEE; the FIP of BL31, OP-TEE and the U-Boot under test is built by
the submit job and wrapped at 0xa7000000 for `uefi_a`/`uefi_b` (qtestsign
v7, uefi). U-Boot: `qcom_defconfig` + `tfa-optee.config` (+ the board
fragment when the base has it), `DEVICE_TREE=qcom/sm8750-mtp`. Linux runs at
EL2 from the base DT (linux-next has no EL2 overlay for it).

There is no downstream (stock) stack: only the open stack is tested.

## Known gaps

- U-Boot `main` has no clock or pinctrl driver for this SoC; they are
  on the EmbeddedAndroid U-Boot fork's platform branch, not posted. The
  nightly cell shows how far `main` gets.
