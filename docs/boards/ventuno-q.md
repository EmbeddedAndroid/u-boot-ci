# Arduino VENTUNO Q (QCS8275, Monaco)

LAVA device type `monaco-arduino-monza`, eMMC (user area and boot area),
debug UART `ttyMSM0`.

## Stock boot path

QCS8300 boot binaries 00142 with the Monza CDT and the qcs8275-monza eMMC
layout (what meta-qcom-arduino's ventuno-q pins), default
`xbl_config.elf`. U-Boot replaces UEFI in `uefi_a`/`uefi_b`, as
meta-qcom-arduino installs it. U-Boot `main` has no VENTUNO Q config, so it
is built with `qcom_monaco_defconfig` when the tree has it (the QCS8300
series renames it) and `qcom_qcs8300_defconfig` otherwise, and
`DEVICE_TREE=qcom/monaco-arduino-monza` (mkmbn takes the `qcom,qcs8300`
load address). XBL starts it at EL1 under Gunyah.

## Open stack

TF-A `PLAT=monza` from EmbeddedAndroid/arm-trusted-firmware `ventuno-q-v3`
(topic qti-monaco follow-ups), BL2 QTI-signed and pre-signed
(fingerprint MONZAFP-261008-154802-pr2-fs), upstream OP-TEE `qcom-monaco`.
U-Boot: `qcom_defconfig` + `board/qualcomm/tfa-optee.config` with the
board DT. Linux runs at EL2 with the upstream `monaco-el2.dtbo`.

## Known gaps (U-Boot main, 2026-10-24)

The VENTUNO Q U-Boot series (QCS8300 pinctrl and interconnect, full GCC
clocks, boot CPU selection, the board config) is on the list, not in
`main`. Without it U-Boot cannot set the SDCC clocks or pins, the eMMC
does not probe, so there is no ESP to boot and the board does not reach
Linux on either stack: the boot verdict is `nothing-booted` (U-Boot back at
its prompt after autoboot) and the `uboot-storage` and `uboot-efi-media`
checks fail. The dashboard shows it as a failure, with this gap
(`linux.gaps` in `config/boards/ventuno-q.yaml`) next to it, until the
series lands.
