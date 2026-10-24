"""The LAVA job for one board and firmware stack of a run.

Flow (docs/architecture.md): flash the package, power on, fingerprint
gate up to U-Boot's DRAM line, stop autoboot and run the U-Boot checks,
reset; on that boot the gate again and U-Boot autoboots the linux-next
UKI from the ESP; Linux version gate, login, smoke checks, reboot (gate
and login once more), poweroff; then flash the lab's stock image back.
A job that stops on the way (a hang or a timeout ends a LAVA job) does
not reach its restore; the collector then submits a recovery job
(ubci/restore.py) to the same device.
"""
import datetime
import os

import yaml

from fwci import flakes
from fwci import lava_jobs as lj

from . import config

UBOOT_PROMPT = "=> "
# A newline before the root prompt: kernel lines such as "PME# supported"
# carry "# " too.
SHELL_PROMPT = "\n# "
LOGIN_PROMPT = "buildroot login:"
AUTOBOOT = "Hit any key to stop autoboot"
UBOOT_FAILURE = r"Unknown command|Error|ERROR|error:|failed|FAILED"
GATE_SUITE = "firmware-fingerprint"
# The stock UEFI of the lab image reports "UEFI Ver    : 6.0.<date>...".
STOCK_UEFI = {"6.0": "pass"}
LINUX_SUITE = "linux-version"


def target_fingerprint(fp, board, stack):
    """The fingerprint of one target's builds (scripts/build-target.sh)."""
    return "%s-%s-%s" % (fp, stack, board)


def base_stack(stack):
    """The firmware stack a target builds: a pin candidate ("stock-candidate")
    is the stock stack with the candidate firmware."""
    return "stock" if stack.startswith("stock") else stack


def gate_expect(board, stack, fp):
    """Banner prefix -> fingerprint the console must show for this stack."""
    expect = {}
    if base_stack(stack) == "open":
        expect["BL2: v"] = board["pins"]["bl2"]["fingerprint"]
        expect["BL31: v"] = fp
        expect["OP-TEE version"] = fp
    expect["U-Boot 20"] = fp
    return expect


def known_errors(board_name, today=None):
    """The kernel-error patterns of config/known-errors.yaml that meet the
    bar today and apply to this board."""
    entries = (yaml.safe_load(open(os.path.join(config.CONFIG, "known-errors.yaml")))
               or {}).get("errors", [])
    return [e["pattern"] for e in flakes.active(entries, today or datetime.date.today(), key="pattern")
            if board_name in e.get("boards", [board_name])]


def errors_command(patterns):
    """Kernel errors (levels 0-3), less the known ones; fails when any is left."""
    for p in patterns:
        if "'" in p:
            raise ValueError("known-error pattern with a single quote: %s" % p)
    keep = "grep -E '^<[0-3]>'" + "".join(" | grep -v -E '%s'" % p for p in patterns)
    return "dmesg -r | %s | head -50; [ -z \"$(dmesg -r | %s)\" ]" % (keep, keep)


def smoke_checks(board, tag, today=None):
    s = board["smoke"]
    return [
        ("linux-next-tag", 'grep -q "%s" /proc/version' % tag),
        ("cpus-online", '[ "$(grep -c ^processor /proc/cpuinfo)" = %d ]' % s["cpus"]),
        ("modules-loaded", 'grep -q . /proc/modules'),
        ("dmesg-errors", errors_command(known_errors(board["name"], today))),
        ("storage", s["storage"]),
        ("usb", s["usb"]),
        ("network", s["network"]),
    ]


def render(board_name, stack, fp, package, linux, restore, metadata=None, device=None):
    """package: {url, token, path}; linux: {tag, release, image_sha256};
    restore: {url, header, token, path} of the lab stock image, or the
    stock firmware package of this board."""
    b = config.board(board_name)
    lava = b["lava"]
    xbl = lava["xbl_marker"]
    expect = gate_expect(b, stack, fp)
    checks = [{"name": "uboot-%s" % n, "command": cmd, "success": ok, "failure": UBOOT_FAILURE}
              for n, cmd, ok in b["uboot_checks"]]
    actions = [
        lj.deploy_qdl(package["url"], package["token"]),
        lj.boot_qdl(package["path"], lava["storage"], lava["luns"], lava["firehose"]),
        lj.power_on(),
        lj.fingerprint_gate(GATE_SUITE, xbl, "DRAM:", expect),
        lj.interactive("u-boot", [UBOOT_PROMPT, AUTOBOOT, r"resetting \.\.\."], [
            {"name": "autoboot", "command": None},
            {"name": "u-boot-prompt", "command": ""},
            {"name": "uboot-version", "command": "version", "success": fp},
        ] + checks + [
            {"name": "uboot-reset", "command": "reset"},
        ]),
        lj.fingerprint_gate(GATE_SUITE + "-reset", xbl, AUTOBOOT, expect),
        lj.monitor(LINUX_SUITE, "Booting Linux on physical CPU",
                   "Run /init as init process|Kernel panic",
                   r"(?P<test_case_id>Linux version) \S*(?P<result>%s)" % linux["tag"],
                   fixupdict={linux["tag"]: "pass"}, expected=["linux_version"]),
        lj.login(LOGIN_PROMPT, SHELL_PROMPT),
        lj.shell_checks("smoke", smoke_checks(b, linux["tag"])),
        lj.interactive("reboot", ["reboot: Restarting system"],
                       [{"name": "reboot", "command": "reboot"}], minutes=3),
        lj.fingerprint_gate(GATE_SUITE + "-reboot", xbl, AUTOBOOT, expect),
        lj.login(LOGIN_PROMPT, SHELL_PROMPT),
        lj.shell_checks("smoke-after-reboot",
                        [("linux-next-tag", 'grep -q "%s" /proc/version' % linux["tag"])]),
        lj.interactive("poweroff", ["reboot: Power down"],
                       [{"name": "poweroff", "command": "poweroff"}], minutes=3),
    ] + restore_actions(b, restore)
    meta = {"project": "u-boot-ci", "board": board_name, "stack": stack,
            "fingerprint": fp, "linux": linux["tag"], "linux-sha256": linux["image_sha256"]}
    meta.update(metadata or {})
    job = lj.job(lava["device_type"], "u-boot-ci %s %s %s" % (board_name, stack, fp),
                 actions, meta)
    if device:
        job["device"] = device
    return job


def restore_actions(board, restore):
    """Flash the lab's stock image back and check that its UEFI starts."""
    lava = board["lava"]
    return [
        lj.deploy_qdl(restore["url"], restore["token"], restore.get("header", "Authorization")),
        lj.boot_qdl(restore["path"], lava["storage"], restore.get("luns", lava["luns"]), lava["firehose"]),
        lj.power_on(),
        lj.monitor("stock-restore", lava["xbl_marker"], "Boot Device",
                   r"(?P<test_case_id>UEFI Ver)\s*:\s*(?P<result>\d+\.\d+)\.",
                   fixupdict=STOCK_UEFI, expected=["uefi_ver"]),
    ]
