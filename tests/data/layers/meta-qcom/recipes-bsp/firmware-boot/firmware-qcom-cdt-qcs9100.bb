DESCRIPTION = "CDT (Configuration Data Table) Firmware for Qualcomm QCS9100 platform"

SRC_URI = " \
    https://${CDT_ARTIFACTORY}/QCS9100/cdt/ride-sx_v3.zip;downloadfilename=cdt-qcs9100-ride-sx-v3_${PV}.zip;name=qcs9100-ride-sx \
    https://${CDT_ARTIFACTORY}/QCS9100/cdt/rb8_core_kit.zip;downloadfilename=cdt-qcs9100-rb8-core-kit_${PV}.zip;name=qcs9100-rb8-ck \
    "
SRC_URI[qcs9100-ride-sx.sha256sum] = "377a8405899ac82199deaf70bca3648c15b924a3fcef8f109555e661ed70f4b9"
SRC_URI[qcs9100-rb8-ck.sha256sum] = "a252244f800d7c9e15883e12935af4113f9f2ecba6490e46cd9b943169f15bfa"

QCOM_CDT_SUBDIR = "qcs9100"

include firmware-qcom-cdt-common.inc
