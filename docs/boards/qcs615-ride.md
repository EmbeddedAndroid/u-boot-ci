# Qualcomm QCS615 Ride (ADP Air, Talos)

LAVA device type `qcs615-ride`, UFS (LUNs 0 to 4), debug UART `ttyMSM0`.

## Downstream boot path: U-Boot in the uefi slot

The downstream firmware is what meta-qcom pins for `qcs615-ride`
([c853feb](https://github.com/qualcomm-linux/meta-qcom/commit/c853febcdeb149021fd043ac7a5eaae88f29f7b7):
`firmware-qcom-boot-qcs615_00142.bb`, `firmware-qcom-cdt-qcs615.bb`,
`QCOM_CDT_FILE = "cdt_adp_air_sa6155p"`): QCS615 boot binaries 00142, the
ADP Air CDT and qcom-ptool's `qcs615-ride/ufs` layout. U-Boot replaces UEFI
in `uefi_a`/`uefi_b` as `u-boot.mbn`: that is the install documented for
QCS615 in U-Boot (`doc/board/qualcomm/dragonwing.rst`) and what meta-qcom
builds for the machine (`UBOOT_CONFIG[qcs615-ride] = "qcom_qcs615_defconfig"`).
Built with `qcom_qcs615_defconfig` and `DEVICE_TREE=qcom/qcs615-ride`. XBL
starts it at EL1 under Gunyah.

## Open stack

TF-A `PLAT=qcs615_ride` (FIP at 0x9fc00000), BL2 QTI-signed and
pre-signed (fingerprint `QCDFP-261024-62`); OP-TEE `qcom-talos` with the
`trusted_keys` and `qcom_pas` early TAs. Both pin the hardware-gated
`qcom/integration` snapshot of 2026-10-24/25 (platform branches
`qcom/talos`), not public yet: the open stack is skipped with that
reason until the branch is pushed. U-Boot: `qcom_defconfig` +
`tfa-optee.config` + `qcs615-ride.config` when the base has it. Linux runs
at EL2 with the upstream `talos-el2.dtbo`.
