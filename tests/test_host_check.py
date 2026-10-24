"""scripts/host-check.sh with stand-ins for make and test.py: the
environment each check builds and tests with."""
import json
import os
import stat
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The CI image sets this for the board builds (docker/Dockerfile).
IMAGE_CROSS = "aarch64-linux-"

RECORD = """#!/bin/bash
echo "$(basename "$0") CROSS_COMPILE=${CROSS_COMPILE-<unset>} $*" >> "$UBCI_STUB_CALLS"
"""


def stub(path, extra=""):
    path.write_text(RECORD + extra)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def sandbox(tmp_path):
    src = tmp_path / "u-boot"
    (src / "test" / "py").mkdir(parents=True)
    stub(src / "test" / "py" / "test.py", 'echo "==== 3 passed in 1.00s ===="\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Like the nolibc toolchain on x86_64: no build with CROSS_COMPILE set.
    stub(bin_dir / "make", '[ -z "${CROSS_COMPILE:-}" ] || { echo "dirent.h: No such file" >&2; exit 2; }\n')
    calls = tmp_path / "calls"

    def go():
        calls.write_text("")
        env = dict(os.environ, PATH="%s:%s" % (bin_dir, os.environ["PATH"]),
                   CROSS_COMPILE=IMAGE_CROSS, UBCI_STUB_CALLS=str(calls))
        p = subprocess.run([os.path.join(REPO, "scripts", "host-check.sh"), "sandbox", str(src),
                            str(tmp_path / "out")], env=env, capture_output=True, text=True)
        res = json.load(open(tmp_path / "out" / "sandbox.json"))
        return p, res, calls.read_text().splitlines()
    return go


def test_sandbox_builds_and_tests_without_the_cross_compiler(sandbox):
    p, res, calls = sandbox()
    assert p.returncode == 0, p.stdout + p.stderr
    assert res == {"result": "pass", "summary": "3 passed in 1.00s"}
    assert [c.split()[0] for c in calls] == ["make", "make", "test.py"]
    assert all("CROSS_COMPILE=<unset>" in c for c in calls), calls


def test_sandbox_that_does_not_build_is_a_failure(sandbox, tmp_path):
    stub(tmp_path / "bin" / "make", "exit 2\n")
    p, res, calls = sandbox()
    assert p.returncode == 0
    assert res == {"result": "fail", "summary": "sandbox did not build"}
    assert [c.split()[0] for c in calls] == ["make"]
