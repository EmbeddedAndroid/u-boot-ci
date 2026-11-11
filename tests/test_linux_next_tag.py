"""scripts/linux-next-tag.sh: the newest next-* tag, retried through a
failing or empty listing, and a failure (not an empty tag) when none comes."""
import os
import stat
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "linux-next-tag.sh")

LISTING = """\
1111111111111111111111111111111111111111\trefs/tags/next-20261109
2222222222222222222222222222222222222222\trefs/tags/next-20261110
3333333333333333333333333333333333333333\trefs/tags/next-20261110^{}
4444444444444444444444444444444444444444\trefs/tags/next-20261108
"""


def fake_git(tmp_path, answers):
    """A git on PATH that answers ls-remote with answers[n] on call n:
    a string is printed with exit 0, None exits 128 (as on an HTTP 502)."""
    d = tmp_path / "bin"
    d.mkdir()
    for n, a in enumerate(answers):
        f = tmp_path / ("answer%d" % n)
        if a is None:
            f.write_text("FAIL")
        else:
            f.write_text(a)
    git = d / "git"
    git.write_text("""#!/bin/bash
n=$(cat "%(t)s/calls" 2>/dev/null || echo 0)
echo $((n + 1)) > "%(t)s/calls"
f="%(t)s/answer$n"
[ -f "$f" ] || f="%(t)s/answer%(last)d"
if [ "$(cat "$f")" = FAIL ]; then
	echo "error: RPC failed; HTTP 502 curl 22 The requested URL returned error: 502" >&2
	exit 128
fi
cat "$f"
""" % {"t": tmp_path, "last": len(answers) - 1})
    git.chmod(git.stat().st_mode | stat.S_IEXEC)
    return str(d)


def run(tmp_path, answers, tries=3):
    env = dict(os.environ, PATH=fake_git(tmp_path, answers) + ":" + os.environ["PATH"],
               UBCI_LS_REMOTE_TRIES=str(tries), UBCI_LS_REMOTE_DELAY="0")
    p = subprocess.run([SCRIPT, "https://example.invalid/linux-next.git"], env=env,
                       capture_output=True, text=True)
    calls = int((tmp_path / "calls").read_text())
    return p, calls


def test_the_newest_tag_comes_back(tmp_path):
    p, calls = run(tmp_path, [LISTING])
    assert p.returncode == 0
    assert p.stdout == "next-20261110\n"
    assert calls == 1


def test_a_failed_listing_is_retried(tmp_path):
    p, calls = run(tmp_path, [None, None, LISTING])
    assert p.returncode == 0
    assert p.stdout == "next-20261110\n"
    assert calls == 3


def test_an_empty_listing_is_retried(tmp_path):
    p, calls = run(tmp_path, ["", LISTING])
    assert p.returncode == 0
    assert p.stdout == "next-20261110\n"
    assert calls == 2


def test_no_tag_after_every_try_fails_with_the_reason(tmp_path):
    p, calls = run(tmp_path, [None], tries=3)
    assert p.returncode != 0
    assert p.stdout == ""
    assert calls == 3
    assert "no linux-next tag" in p.stderr


def test_a_listing_without_next_tags_fails(tmp_path):
    p, calls = run(tmp_path, ["5555555555555555555555555555555555555555\trefs/tags/v6.18\n"], tries=2)
    assert p.returncode != 0
    assert p.stdout == ""
    assert calls == 2


def test_the_workflows_resolve_the_tag_with_the_script():
    for wf in ("run.yml", "pin-candidate.yml"):
        text = open(os.path.join(REPO, ".github", "workflows", wf)).read()
        assert "scripts/linux-next-tag.sh" in text, wf
        assert "ls-remote --tags" not in text, wf
