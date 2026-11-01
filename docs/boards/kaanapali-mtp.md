# Qualcomm Kaanapali MTP (SM8850, Wildcat)

LAVA device type `kaanapali-mtp`, UFS, debug UART `ttyMSM0`.

## Firmware: the open stack only

The board boots XBL from what meta-qcom pins for `kaanapali-mtp`
([af39508](https://github.com/qualcomm-linux/meta-qcom/commit/af39508715abfa06e0abd6e3d8e1228acf374f7d):
`firmware-qcom-boot-kaanapali_00036.bb`): Kaanapali boot binaries 00036 with qcom-ptool's `kaanapali-mtp` UFS layout, LUNs 0, 1, 2 and 4
written; LUN 3 (CDT, DDR training) and LUN 5 stay as the lab wrote them.
The EDL programmer is `qsahara_device_programmer.xml`.

TF-A (PLAT=kaanapali_mtp) and OP-TEE are built from the internal
`qcom/integration` (tag `qcom/integration-20261101`), gated on this
board, and pinned as images ([private-firmware.md](../private-firmware.md)):
BL2 in `tz_a`/`tz_b`, QTI-signed, fingerprint `QCDFP-261101-474` on BL2, BL31 and
OP-TEE; the FIP of BL31, OP-TEE and the U-Boot under test is built by
the submit job and wrapped at 0xc6800000 for `uefi_a`/`uefi_b` (qtestsign
v7, uefi). U-Boot: `qcom_defconfig` + `tfa-optee.config` (+ the board
fragment when the base has it), `DEVICE_TREE=qcom/kaanapali-mtp`. Linux runs at
EL2 from the base DT (linux-next has no EL2 overlay for it).

There is no downstream (stock) stack: only the open stack is tested.

## Known gaps

- U-Boot `main` has no clock or pinctrl driver for this SoC; they are
  on the EmbeddedAndroid U-Boot fork's platform branch, not posted. The
  nightly cell shows how far `main` gets.
