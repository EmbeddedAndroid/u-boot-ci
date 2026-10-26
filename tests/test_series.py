import json
import os
import shutil
import subprocess

import pytest

from fwci import series
from ubci import stack

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True).stdout


def write(repo, name, text):
    (repo / name).write_text(text)


@pytest.fixture
def tree(tmp_path):
    """A base tree and two series (each a format-patch mbox), the second
    built on the first and naming one of its patches as prerequisite."""
    repo = tmp_path / "src"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "next")
    sh(repo, "config", "user.email", "t@example.com")
    sh(repo, "config", "user.name", "T")
    write(repo, "clk.c", "base\n")
    write(repo, "board.c", "base\n")
    sh(repo, "add", ".")
    sh(repo, "commit", "-q", "-m", "base")
    base = sh(repo, "rev-parse", "HEAD").strip()
    write(repo, "clk.c", "base\nsdcc clocks\n")
    sh(repo, "commit", "-q", "-am", "clk: add the SDCC clocks")
    write(repo, "pinctrl.c", "tlmm\n")
    sh(repo, "add", "pinctrl.c")
    sh(repo, "commit", "-q", "-m", "pinctrl: add the TLMM driver")
    s1 = sh(repo, "rev-parse", "HEAD").strip()
    pid = subprocess.run(["git", "patch-id", "--stable"], input=sh(repo, "show", "HEAD~1"),
                         capture_output=True, text=True, cwd=repo).stdout.split()[0]
    write(repo, "board.c", "base\nventuno q\n")
    sh(repo, "commit", "-q", "-am", "board: add the VENTUNO Q")
    out = tmp_path / "mail"
    out.mkdir()

    def mbox(rev, name, version, extra=""):
        text = sh(repo, "format-patch", "--stdout", "--cover-letter", "-v%d" % version, rev)
        cover, rest = text.split("\nFrom ", 1)
        open(out / (name + ".cover"), "w").write(cover.replace("*** SUBJECT HERE ***", name + " series") + extra)
        open(out / (name + ".mbx"), "w").write("From " + rest)
    mbox("%s..%s" % (base, s1), "s01", 4)
    mbox("%s..HEAD" % s1, "s02", 2, "\nprerequisite-patch-id: %s\n" % pid)
    sh(repo, "reset", "-q", "--hard", base)
    return repo, out, base


def am_from(mail):
    def am(outdir, name, msgid):
        src = {"clk@example.com": "s01", "board@example.com": "s02"}[msgid]
        for ext in ("mbx", "cover"):
            shutil.copy(mail / ("%s.%s" % (src, ext)), os.path.join(outdir, "%s.%s" % (name, ext)))
        return os.path.join(outdir, name + ".mbx"), os.path.join(outdir, name + ".cover")
    return am


def test_message_id_forms():
    for t in ("abc@example.com", "<abc@example.com>", "https://lore.kernel.org/u-boot/abc@example.com/",
              "https://lore.kernel.org/r/abc@example.com", "https://patch.msgid.link/abc@example.com",
              "https://lore.kernel.org/u-boot/abc@example.com/T/#u"):
        assert series.message_id(t) == "abc@example.com", t
    with pytest.raises(ValueError):
        series.message_id("next")


def test_two_series_stack_applies_in_order(tree, tmp_path):
    repo, mail, base = tree
    d = tmp_path / "stack"
    got = stack.fetch(str(d), ["https://lore.kernel.org/u-boot/clk@example.com/", "board@example.com"],
                      am=am_from(mail))
    assert [(s["message_id"], s["version"], s["patches"]) for s in got] == [
        ("clk@example.com", 4, 2), ("board@example.com", 2, 1)]
    assert got[1]["title"] == "s02 series"
    assert stack.apply(str(repo), str(d))
    st = json.load(open(d / "stack.json"))
    assert [s["applied"] for s in st] == [True, True]
    assert st[1]["unresolved_prerequisites"] == []
    assert sh(repo, "log", "--format=%s", "%s..HEAD" % base).splitlines() == [
        "board: add the VENTUNO Q", "pinctrl: add the TLMM driver", "clk: add the SDCC clocks"]


def test_stack_applies_from_paths_relative_to_the_caller(tree, tmp_path, monkeypatch):
    # The prepare job runs "ubci.stack apply work/u-boot work/stack" from the
    # checkout root: both paths are relative to the caller, not the tree.
    repo, mail, base = tree
    monkeypatch.chdir(tmp_path)
    stack.fetch("stack", ["clk@example.com", "board@example.com"], am=am_from(mail))
    assert json.load(open("stack/stack.json"))[0]["mbx"] == os.path.join("stack", "s01.mbx")
    assert stack.apply("src", "stack")
    assert [s["applied"] for s in json.load(open("stack/stack.json"))] == [True, True]
    assert len(sh(repo, "log", "--format=%s", "%s..HEAD" % base).splitlines()) == 3


def test_missing_prerequisite_is_reported(tree, tmp_path):
    repo, mail, base = tree
    d = tmp_path / "stack"
    # the second series alone: its prerequisite patch is missing, and the
    # board file applies on the base anyway
    stack.fetch(str(d), ["board@example.com"], am=am_from(mail))
    assert stack.apply(str(repo), str(d))
    assert len(json.load(open(d / "stack.json"))[0]["unresolved_prerequisites"]) == 1


def test_conflict_is_recorded_with_the_failing_patch(tree, tmp_path):
    repo, mail, base = tree
    write(repo, "clk.c", "base\nsomething else\n")
    sh(repo, "commit", "-q", "-am", "clk: conflicting change")
    d = tmp_path / "stack"
    stack.fetch(str(d), ["clk@example.com", "board@example.com"], am=am_from(mail))
    assert not stack.apply(str(repo), str(d))
    st = json.load(open(d / "stack.json"))
    assert st[0]["applied"] is False and st[1]["applied"] is None
    assert st[0]["failed_patch"]["number"] == 1
    assert st[0]["failed_patch"]["subject"].endswith("clk: add the SDCC clocks")
    # the checkout is left clean, on the base
    assert sh(repo, "status", "--porcelain") == ""
    assert sh(repo, "log", "-1", "--format=%s") == "clk: conflicting change\n"


def test_prerequisite_message_id_is_fetched_first(tree, tmp_path):
    repo, mail, base = tree
    with open(mail / "s02.cover", "a") as f:
        f.write("prerequisite-message-id: <clk@example.com>\n")
    got = stack.fetch(str(tmp_path / "stack"), ["board@example.com"], am=am_from(mail))
    assert [s["message_id"] for s in got] == ["clk@example.com", "board@example.com"]
    assert got[0]["added_as_prerequisite_of"] == "board@example.com"


def test_a_failed_series_is_aborted_without_a_git_identity(tree, tmp_path, monkeypatch):
    # The CI container has no git identity; git am --abort needs one.
    repo, mail, base = tree
    write(repo, "clk.c", "base\nsomething else\n")
    sh(repo, "commit", "-q", "-am", "clk: conflicting change")
    sh(repo, "config", "--unset", "user.email")
    sh(repo, "config", "--unset", "user.name")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("HOME", str(tmp_path))
    # An empty GIT_COMMITTER_EMAIL is an identity to git: unset, not empty.
    for v in ("EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"):
        monkeypatch.delenv(v, raising=False)
    d = tmp_path / "stack"
    stack.fetch(str(d), ["clk@example.com"], am=am_from(mail))
    assert not stack.apply(str(repo), str(d))
    fp = json.load(open(d / "stack.json"))[0]["failed_patch"]
    assert fp["number"] == 1 and fp["error"].startswith("Patch failed at 0001 clk: add the SDCC clocks")
    assert fp["subject"].endswith("clk: add the SDCC clocks")
    assert not os.path.exists(repo / ".git" / "rebase-apply")


def test_a_failed_series_in_a_worktree_names_its_patch(tree, tmp_path):
    repo, mail, base = tree
    write(repo, "clk.c", "base\nsomething else\n")
    sh(repo, "commit", "-q", "-am", "clk: conflicting change")
    wt = tmp_path / "wt"
    sh(repo, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
    d = tmp_path / "stack"
    stack.fetch(str(d), ["clk@example.com"], am=am_from(mail))
    assert not stack.apply(str(wt), str(d))
    assert json.load(open(d / "stack.json"))[0]["failed_patch"]["number"] == 1
    assert sh(wt, "status", "--porcelain") == ""


def test_a_series_git_cannot_read_is_recorded_not_raised(tree, tmp_path):
    repo, mail, base = tree
    d = tmp_path / "stack"
    stack.fetch(str(d), ["clk@example.com"], am=am_from(mail))
    (d / "s01.mbx").write_text("not a patch\n")
    assert not stack.apply(str(repo), str(d))
    assert json.load(open(d / "stack.json"))[0]["applied"] is False
