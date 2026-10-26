# Qualcomm Shikra IQS EVK (IQ2)

LAVA device type `shikra-iqs-evk`, eMMC, debug UART `ttyMSM0`.

## Downstream boot path: U-Boot in the uefi slot

The downstream firmware is what meta-qcom pins for `shikra-evk`
([c853feb](https://github.com/qualcomm-linux/meta-qcom/commit/c853febcdeb149021fd043ac7a5eaae88f29f7b7):
`firmware-qcom-boot-shikra_00093.bb`): SHIKRA boot binaries 00093 with
qcom-ptool's `shikra-evk` eMMC layout. U-Boot replaces UEFI in
`uefi_a`/`uefi_b` as `u-boot.mbn`, as meta-qcom does for the machine
(`UBOOT_CONFIG[shikra-evk]`); XBL starts it at EL1 under Gunyah. Only the
user area is flashed: the CDT in the second boot partition stays as the
lab wrote it. U-Boot `main` has the IQS EVK device tree but not the
`qcom_shikra_iqs_defconfig` of the Shikra series (v4,
<20261021160916.3894471-1-aswin.murugan@oss.qualcomm.com>), so on a
nightly the downstream target is "board not in this base".

## Open stack

Not available as a FIP flow: TF-A `shikra_evk` builds BL31 only, so
there is no BL2 for XBL to load from `tz`. The Shikra open stack is the
U-Boot SPL one below.

## U-Boot SPL stack

U-Boot SPL replaces XBL on Shikra. The eMMC SPL series links it in
BOOT_IMEM, brings up DDR itself through QcLib with the pre-DDR blobs,
and signs it as SBL1 (`QCOM_SPL_FW_TYPE`), the image type the boot ROM
loads; the layout's `xbl_a`/`xbl_b` carry the SBL1 partition type GUID
(`DEA0BA2C-CBDD-4805-B4F9-F428251C3E98`), `tz_a`/`tz_b` the TZ one
(`A053AA7F-40B8-4B1C-BA08-2F68AC71A4F4`), which XBL loads only after DDR
is up. So the SPL goes to `xbl_a`/`xbl_b` (`spl.slot: xbl.elf`, `sign:
sbl1`), not to `tz_a` as meta-qcom PR 3420 installs it next to the
downstream XBL. This follows from the image type and the layout; no
Shikra SPL has been booted here. The SPL reads the FIT from `uefi_a`
(`QCOM_SPL_FIT_IMG_PARTITION` in `spl-shikra.c`).

The FIT (`ubci/fit.py`) carries a `pre-ddr` configuration of the boot
firmware blobs the SPL loads before DDR (PMIC Cocos and Wailua
configuration, the LP4 and LP5 DCBs, SHRM, QcLib, ECC from
`Shikra_LCP.bin`), all taken from the pinned boot binaries with their own
sha256 (`spl.pre_ddr`), at the addresses meta-qcom PR 3420 uses, and the
`post-ddr` one: BL31 at 0xA1300000 (TF-A `shikra_evk`), OP-TEE at
0xA1400000 (`qcom-shikra`), U-Boot at 0x87980000, from the public
`qcom/integration` of the EmbeddedAndroid forks.

What is missing upstream, and so what the SPL cell says: no posted Shikra
SPL enablement (no SPL defconfig, config fragment or Kconfig select: the
eMMC SPL v2 series dropped its defconfig), and no posted FIT template.
The SPL also embeds the XBL-sec image `qc_sec.mbn` (in the boot binaries)
from the source tree (`CONFIG_QCOM_XBL_SEC_ELF`), which the CI will have
to stage once there is a config. The series in flight are listed in the
board file (`spl.in_flight`): Shikra v4, HS200/HS400 v2, mkmbn ipq5210 v3,
IPQ5210 bringup v10, spl_qcom_phase v1, eMMC SPL v2, SD-card SPL v2, CDT
v2, DDR training v1 and the OP-TEE SPL link fix v1. On `main` 8649a54d3
HS200/HS400 v2 2/3 no longer applies (`msm_sdhci` moved to the dev_read
API).
