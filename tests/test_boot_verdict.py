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
    # The size query as LAVA logged it in job 511932.
    (("7[r[999;999H[6n8\x00",), "no-efi-stub", "fail"),
    (("U-Boot 2026.10", "=> "), "not-reached", "not-run"),
    # A prompt before the handoff is the one the U-Boot checks used.
    (("=> ",) + HANDOFF, "no-efi-stub", "fail"),
    # VENTUNO Q on plain main, LAVA 512231: no eMMC, autoboot found nothing
    # and U-Boot was back at its prompt (flushed at teardown).
    (("Hit any key to stop autoboot: 0", "7[r[999;999H[6n8Power domain id (0) not supported",
      "msm_sdc mmc@87c4000: pinctrl_select_state_full: uclass_get_device_by_phandle_id: err=-19",
      "Cannot persist EFI variables without system partition", "=> \x00"),
     "nothing-booted", "fail"),
    ((), "not-reached", "not-run"),
])
def test_stage(text, stage, verdict):
    got = bv.classify(lines(*text), URL)
    assert (got["stage"], got["verdict"]) == (stage, verdict)


def test_nothing_booted_links_the_prompt():
    got = bv.classify(lines(*(HANDOFF + ("Cannot persist EFI variables", "=> ", "line noise"))), URL)
    assert got["stage"] == "nothing-booted" and got["url"] == URL + "#L102"


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
