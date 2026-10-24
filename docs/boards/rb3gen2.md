# Qualcomm RB3 Gen 2 (QCS6490, Kodiak)

LAVA device type `qcs6490-rb3gen2`, UFS (LUNs 0 to 5), debug UART
`ttyMSM0`.

## Stock boot path

QCM6490 boot binaries 00142 with the rb3gen2-core-kit CDT (what
meta-qcom's rb3gen2-core-kit pins), default `xbl_config.elf`. U-Boot is
built with `qcm6490_defconfig` and `DEVICE_TREE=qcom/qcs6490-rb3gen2` and
replaces UEFI in `uefi_a`/`uefi_b`, as doc/board/qualcomm/rb3gen2.rst in
U-Boot describes: on this board U-Boot is meant to be the UEFI, so this is
the realistic path. XBL starts it at EL1 under the stock hypervisor; Linux
runs at EL1.

meta-qcom's kvm variant (`xbl_config_kvm.elf`) pairs the boot binaries
with a Gunyah-exit fragment that upstream U-Boot does not have, so it is
not used.

## Open stack

TF-A `PLAT=rb3gen2` from EmbeddedAndroid/arm-trusted-firmware
`kodiak-native-v4` (BL31 without QTISECLIB, Gerrit topic
qti-kodiak-native), BL2 OEM-TEST signed, upstream OP-TEE `qcom-kodiak`.
U-Boot: `qcom_defconfig` + `board/qualcomm/tfa-optee.config`, same DT.
Linux runs at EL2.

## Known gaps

- linux-next has no Kodiak EL2 overlay, so the open stack boots the base
  DT at EL2.
- USB (`smoke/usb`, reported `skip` with this note): the USB-A ports sit
  behind a Renesas uPD720201 xHCI that needs `renesas_usb_fw.mem`, which
  is not redistributable, and the Type-C port is a USB peripheral in the
  upstream DT, so a host-side device never appears.
- The minimal initramfs carries no firmware files, so the DSP, GPU, video,
  Wi-Fi, Bluetooth and Renesas xHCI drivers log missing-file errors; those
  lines are allowlisted (`config/known-errors.yaml`, E1 to E3).
