"""The U-Boot step of the hardware job against a model of the board's
console, driven the way LAVA's lava-test-interactive drives it
(lava_dispatcher/actions/test/interactive.py: sendline, read one line
when echo is "discard", expect prompts + failures + successes, then the
prompts again after a success or failure unless wait_for_prompt is
false; pexpect takes the earliest match). Job 511644 (VENTUNO Q, run
ubci-40132771629-1-main) had line noise executed as a command at the
first prompt: every check matched the prompt of the one before and the
reset was typed while U-Boot was still printing."""
import re

import pytest

from ubci import jobs

FP = "ubci-9-1-main-stock-ventuno-q"
JUNK = "$�\x0c�\x0b"
OUTPUT = {
    "version": "U-Boot 2026.10-%s-01063-gecd14b59ae66 (Oct 24 2026)\r\n\r\naarch64-linux-gcc (GCC) 14.2.0\r\n" % FP,
    "bdinfo": "boot_params = 0x0000000000000000\r\n",
    "dm tree": " root          0  [ + ]   root_driver           root_driver\r\n",
    "clk dump": " Rate               Usecnt      Name\r\n",
    "mmc info": "Device: mmc@87c4000\r\nUser Capacity: 59.3 GiB WRREL\r\n",
    "usb tree": "USB device tree:\r\n  1  Hub (5 Gb/s, 0mA)\r\n",
    "efidebug dh": "0000000f7f5fafc0 (mmc@87c4000.blk)\r\n  Block IO\r\n",
    "bootflow scan -l": "Seq  Method       State   Uclass    Part  Name\r\n  0  efi_mgr      ready   (none)       0  <NULL>\r\n",
}


class Board:
    """U-Boot's console: autoboot countdown, the line editor, hush ';'
    lists, echo with adjacent quoted strings joined, reset."""

    def __init__(self, noise=""):
        self.out = "U-Boot 2026.10-%s\r\nHit any key to stop autoboot: 1" % FP
        self.line = noise
        self.state = "countdown"

    def run(self, cmd):
        cmd = cmd.strip()
        m = re.fullmatch(r'echo (.*)', cmd)
        if m:
            return re.sub(r'"([^"]*)"', r"\1", m.group(1)) + "\r\n"
        if cmd in OUTPUT:
            return OUTPUT[cmd]
        if cmd == "reset":
            self.state = "reset"
            return "resetting ...\r\n"
        return "Unknown command '%s' - try 'help'\r\n" % cmd if cmd else ""

    def type(self, text):
        typed, self.line = self.line + text, ""
        if self.state == "countdown":
            # Any key stops autoboot and is consumed; the rest is a line.
            self.out += "\x1b[2K\rHit any key to stop autoboot: 0\r\n=> "
            self.state = "prompt"
            typed = typed[1:]
            if not typed:
                return
        self.out += typed + "\r\n"
        for part in typed.split(";"):
            self.out += self.run(part)
            if self.state == "reset":
                return
        self.out += "=> "


class Lava:
    def __init__(self, board):
        self.board, self.pos = board, 0
        self.typed_with_unread_output = []

    def sendline(self, text):
        # Typing into the countdown is the point; at the prompt it is not.
        if self.board.state == "prompt" and self.board.out[self.pos:].rstrip(" =>"):
            self.typed_with_unread_output.append(text)
        self.board.type(text + "\n")

    def readline(self):
        i = self.board.out.find("\n", self.pos)
        self.pos = len(self.board.out) if i < 0 else i + 1

    def expect(self, patterns):
        found = [(m.start(), i, m.end()) for i, p in enumerate(patterns)
                 for m in [re.compile(p).search(self.board.out, self.pos)] if m]
        if not found:
            raise TimeoutError(patterns)
        start, i, end = min(found)
        self.pos = end
        return i


def interactive(job):
    return [a["test"]["interactive"][0] for a in job["actions"]
            if "test" in a and "interactive" in a["test"] and a["test"]["interactive"][0]["name"] == "u-boot"][0]


def drive(script, lava):
    """lava-test-interactive's run_script: case -> pass/fail."""
    prompts, results = script["prompts"], {}
    for cmd in script["script"]:
        if cmd["command"] is not None:
            lava.sendline(cmd["command"])
            if script.get("echo") == "discard":
                lava.readline()
        failures = [f["message"] for f in cmd.get("failures", [])]
        successes = [s["message"] for s in cmd.get("successes", [])]
        try:
            i = lava.expect(prompts + failures + successes)
        except TimeoutError:
            results[cmd["name"]] = "timeout"
            break
        if i < len(prompts):
            results[cmd["name"]] = "fail" if successes else "pass"
        else:
            results[cmd["name"]] = "fail" if i < len(prompts) + len(failures) else "pass"
            if cmd.get("wait_for_prompt", True):
                lava.expect(prompts)
    return results


def render(board="ventuno-q"):
    return jobs.render(board, "stock", FP, {"url": "u", "token": "t", "path": "p"},
                       {"tag": "next-20261023", "release": "7.3.0", "image_sha256": "0" * 64},
                       {"url": "r", "token": "T", "path": "rp"})


@pytest.mark.parametrize("noise", ["", JUNK], ids=["clean", "line-noise"])
def test_every_check_reads_its_own_output(noise):
    lava = Lava(Board(noise))
    results = drive(interactive(render()), lava)
    assert set(results.values()) == {"pass"}, results
    assert lava.board.state == "reset"
    assert "uboot-storage" in results and list(results)[-1] == "uboot-reset"
    # No command typed while U-Boot still had output on the way, but for
    # the sync, which is there to take up whatever the noise printed.
    sync = [jobs.uboot_command()] if noise else []
    assert lava.typed_with_unread_output == sync, lava.typed_with_unread_output


def test_a_failing_check_fails_alone(monkeypatch):
    monkeypatch.delitem(OUTPUT, "mmc info")
    lava = Lava(Board(JUNK))
    results = drive(interactive(render()), lava)
    assert results["uboot-storage"] == "fail"
    assert {k for k, v in results.items() if v != "pass"} == {"uboot-storage"}
    assert lava.board.state == "reset"


def test_a_check_without_its_success_text_fails(monkeypatch):
    monkeypatch.setitem(OUTPUT, "usb tree", "starting USB...\r\n")
    results = drive(interactive(render()), Lava(Board()))
    assert results["uboot-usb"] == "fail"
    assert {k for k, v in results.items() if v != "pass"} == {"uboot-usb"}


def test_the_echoed_command_line_never_ends_a_step():
    for s in interactive(render())["script"]:
        if s["command"]:
            assert jobs.UBOOT_END not in s["command"], s
