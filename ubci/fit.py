"""The image tree source of the FIT U-Boot SPL loads from uefi_a/uefi_b
on an SPL boot chain (Lemans): BL31 runs first, then OP-TEE and U-Boot
proper with its control DTB, at the load addresses of the TF-A pin
(pins.<board>.tf-a.fit).

python3 -m ubci.fit <board> <bl31.bin> <tee-raw.bin> <u-boot.bin> <u-boot.dtb>
    prints the .its for mkimage -f."""
import sys

from . import config

TEMPLATE = """/dts-v1/;

/ {
	description = "%(title)s: BL31, OP-TEE and U-Boot for U-Boot SPL";
	#address-cells = <1>;

	images {
		atf {
			description = "TF-A BL31";
			data = /incbin/("%(bl31)s");
			type = "firmware";
			arch = "arm64";
			os = "arm-trusted-firmware";
			compression = "none";
			load = <%(atf)s>;
			entry = <%(atf)s>;
			hash-1 { algo = "sha256"; };
		};
		optee {
			description = "OP-TEE (BL32)";
			data = /incbin/("%(tee)s");
			type = "tee";
			arch = "arm64";
			os = "tee";
			compression = "none";
			load = <%(optee)s>;
			entry = <%(optee)s>;
			hash-1 { algo = "sha256"; };
		};
		uboot {
			description = "U-Boot (BL33)";
			data = /incbin/("%(uboot_bin)s");
			type = "firmware";
			arch = "arm64";
			os = "u-boot";
			compression = "none";
			load = <%(uboot)s>;
			entry = <%(uboot)s>;
			hash-1 { algo = "sha256"; };
		};
		fdt-1 {
			description = "U-Boot control DTB";
			data = /incbin/("%(dtb)s");
			type = "flat_dt";
			arch = "arm64";
			compression = "none";
			hash-1 { algo = "sha256"; };
		};
	};

	configurations {
		default = "conf-1";
		conf-1 {
			description = "BL31, OP-TEE and U-Boot";
			firmware = "atf";
			loadables = "uboot", "optee";
			fdt = "fdt-1";
		};
	};
};
"""


def its(board_name, bl31, tee, uboot_bin, dtb):
    b = config.board(board_name)
    addr = b["pins"]["tf-a"]["fit"]
    for k in ("atf", "optee", "uboot"):
        int(str(addr[k]), 0)
    paths = (bl31, tee, uboot_bin, dtb)
    if any('"' in p for p in paths):
        raise SystemExit("a FIT input path holds a quote")
    return TEMPLATE % dict(title=b["title"], bl31=bl31, tee=tee, uboot_bin=uboot_bin, dtb=dtb,
                           atf=addr["atf"], optee=addr["optee"], uboot=addr["uboot"])


if __name__ == "__main__":
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    sys.stdout.write(its(*sys.argv[1:6]))
