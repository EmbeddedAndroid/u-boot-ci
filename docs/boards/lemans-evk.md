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
flashed: the board keeps the lab's (the restore writes it first).

## Open stack: an SPL boot chain

On Lemans XBL loads U-Boot SPL from `tz_a`/`tz_b`, and SPL loads a FIT
from `uefi_a`/`uefi_b` with TF-A BL31, OP-TEE and U-Boot proper (meta-qcom
`iq-9075-evk-open-fw-spl`). XBL takes that path only with the release's
SPL XBLConfig, `xbl_config_spl.elf` (meta-qcom `qcom-uboot-spl-fit.inc`),
so the open stack is built on the same release with that XBLConfig
(`downstream_open`); with the default one XBL loads `uefi` as an ELF and
stops at `Error code 82000035 at boot_elf_driver.c` (LAVA 512763). U-Boot
`main` has no Lemans SPL, so SPL is a
pinned, pre-built, test-signed binary (fingerprint
`LEMANSFP-261009-030954-lpb4`): the one stage of this chain that is not
built from a public commit, shown as downstream in the boot chain. The FIT
(`scripts/build-open-stack.sh`, image `uefi.itb`, `ubci/fit.py`) is built on
every run: BL31 at 0x1c200000, OP-TEE at 0x1c300000 (with the
`trusted_keys` and `qcom_pas` early TAs), U-Boot under test at 0xaf000000
with its control DTB. TF-A `PLAT=lemans_evk` and OP-TEE `qcom-lemans` pin
the hardware-gated `qcom/integration` snapshot of 2026-10-24/25 (platform
branches `qcom/lemans`), not public yet: the open stack is skipped with
that reason until the branch is pushed. U-Boot: `qcom_defconfig` +
`tfa-optee.config`, `DEVICE_TREE=qcom/lemans-evk`. Linux runs at EL2 with
the upstream `lemans-el2.dtbo`.
