"""The image tree source of the FIT U-Boot SPL loads from uefi_a/uefi_b
on an SPL boot chain: BL31 runs first, then OP-TEE and U-Boot proper with
its control DTB, at the load addresses of the TF-A pin
(pins.<board>.tf-a.fit).

The configuration is described as "post-ddr", the name the
mach-snapdragon SPL selects once DRAM is up (board_fit_config_name_match()
in board_spl.c); an SPL without that hook takes the default
configuration, which is the same one. A board whose SPL brings up DRAM
itself (spl.pre_ddr) gets a "pre-ddr" configuration too, of the boot
firmware blobs that SPL loads first (PMIC and DDR configuration, SHRM,
QcLib), each at its pinned address. U-Boot has no posted FIT template for
this; the layout is the one meta-qcom builds for the board.

python3 -m ubci.fit <board> <bl31.bin> <tee-raw.bin> <u-boot.bin> <u-boot.dtb> [<blob dir>]
    prints the .its for mkimage -f; the pre-ddr blobs are read from
    <blob dir> (ubci.package blobs)."""
import os
import sys

from . import config

HEAD = """/dts-v1/;

/ {
	description = "%(title)s: BL31, OP-TEE and U-Boot for U-Boot SPL";
	#address-cells = <1>;

	images {
"""

IMAGES = """		atf {
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
"""

BLOB = """		%(name)s {
			description = "%(description)s";
			data = /incbin/("%(path)s");
			type = "firmware";
			arch = "arm64";
			compression = "none";
			load = <%(load)s>;
			entry = <%(entry)s>;
		};
"""

CONFIGS = """	};

	configurations {
		default = "conf-1";
		conf-1 {
			description = "post-ddr";
			firmware = "atf";
			loadables = "uboot", "optee";
			fdt = "fdt-1";
		};
%(pre_ddr)s	};
};
"""

PRE_DDR = """		conf-pre-ddr {
			description = "pre-ddr";
			loadables = %s;
		};
"""


def _quoted(*paths):
    if any('"' in p for p in paths):
        raise SystemExit("a FIT input path holds a quote")


def its(board_name, bl31, tee, uboot_bin, dtb, blob_dir=None):
    b = config.board(board_name)
    addr = b["pins"]["tf-a"]["fit"]
    for k in ("atf", "optee", "uboot"):
        int(str(addr[k]), 0)
    _quoted(bl31, tee, uboot_bin, dtb)
    text = HEAD % dict(title=b["title"])
    text += IMAGES % dict(bl31=bl31, tee=tee, uboot_bin=uboot_bin, dtb=dtb,
                          atf=addr["atf"], optee=addr["optee"], uboot=addr["uboot"])
    blobs = (b.get("spl") or {}).get("pre_ddr", [])
    if blobs and not blob_dir:
        raise SystemExit("%s needs its pre-ddr blobs (no blob dir given)" % board_name)
    for blob in blobs:
        for k in ("load", "entry"):
            int(str(blob[k]), 0)
        path = os.path.join(blob_dir, blob["file"])
        _quoted(path)
        if not os.path.exists(path):
            raise SystemExit("pre-ddr blob %s missing from %s" % (blob["file"], blob_dir))
        text += BLOB % dict(blob, path=path)
    pre = PRE_DDR % ", ".join('"%s"' % blob["name"] for blob in blobs) if blobs else ""
    return text + CONFIGS % dict(pre_ddr=pre)


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7):
        raise SystemExit(__doc__)
    sys.stdout.write(its(*sys.argv[1:7]))
