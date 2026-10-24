import pytest

from fwci import boot_verdict as bv

URL = "https://lava.example/scheduler/job/7"


def lines(*texts, start=100):
    return [(start + i, t) for i, t in enumerate(texts)]


HANDOFF = ("Booting: mmc 0", )
STUB = ("EFI stub: Booting Linux Kernel...", "EFI stub: Exiting boot services...")
KERNEL = ("[    0.000000] Booting Linux on physical CPU 0x0000000000",
          "[    0.000000] Linux version 7.3.0-next-20261023")


@pytest.mark.parametrize("text,stage,verdict", [
    (HANDOFF + STUB + KERNEL + ("Run /init as init process", "buildroot login:"), "login", "pass"),
    (HANDOFF + STUB + KERNEL + ("Unable to handle kernel paging request at 0",
                                 "Kernel panic - not syncing: Oops"), "early-panic", "fail"),
    (HANDOFF + STUB + KERNEL + ("Run /init as init process",), "no-login", "fail"),
    (HANDOFF + STUB, "hang-before-console", "fail"),
    (HANDOFF, "no-efi-stub", "fail"),
    (("U-Boot 2026.10", "=> "), "not-reached", "not-run"),
    ((), "not-reached", "not-run"),
])
def test_stage(text, stage, verdict):
    got = bv.classify(lines(*text), URL)
    assert (got["stage"], got["verdict"]) == (stage, verdict)


def test_failure_links_last_line_and_keeps_tail():
    got = bv.classify(lines(*(HANDOFF + STUB + KERNEL + ("probe of x failed",))), URL)
    assert got["url"] == URL + "#L105"
    assert got["last_lines"][-1] == "probe of x failed"


def test_panic_anchor_points_at_the_panic():
    text = HANDOFF + STUB + KERNEL + tuple("line %d" % i for i in range(40)) + (
        "Kernel panic - not syncing: VFS",) + tuple("after %d" % i for i in range(40))
    got = bv.classify(lines(*text), URL)
    panic_index = 100 + text.index("Kernel panic - not syncing: VFS")
    assert got["url"] == "%s#L%d" % (URL, panic_index)
    assert "Kernel panic - not syncing: VFS" in got["last_lines"]


@pytest.mark.parametrize("run,base,want", [
    ("fail", "pass", "regression"),
    ("fail", "fail", "upstream-gap"),
    ("pass", "fail", "fixed"),
    ("pass", "pass", "same"),
    ("fail", None, "unknown"),
    ("fail", "not-run", "unknown"),
    ("not-run", "pass", "unknown"),
])
def test_versus_baseline(run, base, want):
    assert bv.versus(run, base) == want
