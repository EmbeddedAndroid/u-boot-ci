# Qualcomm IQ-9075 EVK (QCS9075, Lemans)

LAVA device type `lemans-evk`, UFS (LUNs 0 to 5) and a SAIL NOR flash,
debug UART `ttyMSM0`.

## Downstream boot path: U-Boot in the uefi slot

The downstream firmware is what meta-qcom pins for `iq-9075-evk`
([c853feb](https://github.com/qualcomm-linux/meta-qcom/commit/c853febcdeb149021fd043ac7a5eaae88f29f7b7):
`firmware-qcom-boot-qcs9100_00142.bb`, `firmware-qcom-cdt-qcs9100.bb`,
`QCOM_CDT_FILE = "cdt_rb8_core_kit"`): QCS9100 boot binaries 00142 with
the RB8 core kit CDT and qcom-ptool's `iq-9075-evk` layout. U-Boot replaces
UEFI in `uefi_a`/`uefi_b` as `u-boot.mbn`, as meta-qcom does for this
machine (`UBOOT_CONFIG[iq-9075-evk]`) and `doc/board/qualcomm/dragonwing.rst`
documents for IQ9. meta-qcom builds `qcom_lemans_defconfig` from its U-Boot
tree; U-Boot `main` has `qcom_qcs9100_defconfig` instead, so the CI takes
the first that exists with `DEVICE_TREE=qcom/lemans-evk` (the board DT
also carries `qcom,qcs9100`, which gives mkmbn its load address). XBL
starts it at EL1 under Gunyah. The SAIL NOR image of the release is not
flashed and no job restores it: the board runs the SAIL NOR image the
lab last wrote (its health-check image writes it).

## Open stack: TF-A BL2 and a FIP

The TF-A boot flow of `docs/plat/qti/lemans_evk.rst`, as on RB3 Gen 2:
XBL loads TF-A BL2 from `tz_a`/`tz_b`, and BL2 takes the FIP XBL loaded
from `uefi_a`/`uefi_b` (`fip.elf` at 0xaf000000) with BL31, OP-TEE and
U-Boot under test as BL33, on the downstream release with its default
XBLConfig. BL2 is built from the tf-a pin, SWIV-annotated for `lemans`
(the pinned boot-firmware-ci `swiv_build_utility.py`, segment at
0x1c042000, past BL2's image) and test-signed as `tz` with the pinned
qtestsign (`qtestsign -v6 tz`), the treatment the SPL stack gives its
SPL; the image is pinned by sha256 and fingerprint like every BL2.
BL31 and OP-TEE (with the `trusted_keys` and `qcom_pas` early TAs) are
built on every run. TF-A `PLAT=lemans_evk` and OP-TEE `qcom-lemans` pin
the pushed `qcom/integration` of the EmbeddedAndroid forks (platform
branches `qcom/lemans` recorded as `soc_branch`). U-Boot: `qcom_defconfig` +
`tfa-optee.config`, `DEVICE_TREE=qcom/lemans-evk`. Linux runs at EL2 with
the upstream `lemans-el2.dtbo`.

No integration branch carries a Lemans U-Boot SPL; the SPL boot chain runs
only on the U-Boot SPL stack below, from the tree under test.

## U-Boot SPL stack

The Lemans SPL boot flow keeps XBL first: PBL loads XBL, XBL trains DDR
and loads U-Boot SPL from `tz_a`/`tz_b` as its TZ image, and the SPL
loads the FIT from `uefi_a` (the Lemans SPL v4 cover letter: "PBL -> XBL
-> U-Boot SPL"; meta-qcom `qcom-uboot-spl-fit.inc` and
`iq-9075-evk-open-fw-spl`). So the SPL replaces `tz.mbn`, SWIV-annotated
for `lemans` and test-signed as `tz` (`qtestsign -v6 tz`), on the same
release with the SPL XBLConfig `xbl_config_spl.elf` (`downstream_spl`;
meta-qcom `qcom-uboot-spl-fit.inc`: with the default one XBL loads `uefi`
as an ELF and stops at `Error code 82000035 at boot_elf_driver.c`, LAVA
512763), and the FIT (`uefi.itb`, `ubci/fit.py`: BL31 at 0x1c200000,
OP-TEE at 0x1c300000, U-Boot at 0xaf000000 with its control DTB) built
around it on every run. The gates start
at XBL's "SBL1, End". U-Boot: `qcom_lemans_spl_defconfig` +
`tfa-optee.config`, `DEVICE_TREE=qcom/lemans-evk`, SPL and U-Boot proper
from the one build.

U-Boot `main` has no Lemans SPL: the nightly cell is "no upstream SPL"
with the series that would add it. The Lemans SPL v4 series
(<20260928-spl-lemans-v4-0-007635cc4667@oss.qualcomm.com>) needs the
mach-snapdragon SPL of the IPQ5210 bringup v10, the SPL UFS loader
(spl_ufs v4), the SPL builds of the GENI, serial, pinctrl and SMEM
drivers (spl_qcom_phase v1, which builds on the SDAM v5 series), and,
with `tfa-optee.config`, the OP-TEE SPL link fix v1; its cover letter
declares only the IPQ5210 series.
