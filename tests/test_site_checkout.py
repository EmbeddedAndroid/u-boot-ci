"""site-checkout.sh: the gh-pages worktree publish-site.sh writes to, and
the rule that both run in the CI container (a worktree made on the runner
is not a repository at the container's /work)."""
import glob
import json
import os
import re
import shutil
import subprocess

import pytest

from samples import run

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout


def script(name, *args, cwd):
    return subprocess.run([os.path.join(REPO, "scripts", name), *args], cwd=cwd,
                          capture_output=True, text=True)


def bare(tmp_path, with_pages):
    r = tmp_path / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(r))
    seed = tmp_path / "seed"
    sh("git", "init", "-q", "-b", "main", str(seed))
    (seed / "README").write_text("ci\n")
    sh("git", "add", "README", cwd=seed)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "main", cwd=seed)
    sh("git", "push", "-q", str(r), "main", cwd=seed)
    if with_pages:
        sh("git", "switch", "-q", "--orphan", "gh-pages", cwd=seed)
        (seed / "index.json").write_text('{"runs": []}\n')
        sh("git", "add", "index.json", cwd=seed)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "pages", cwd=seed)
        sh("git", "push", "-q", str(r), "gh-pages", cwd=seed)
    # Like actions/checkout: only main is fetched, no gh-pages tracking ref.
    work = tmp_path / "work"
    sh("git", "clone", "-q", "--single-branch", "-b", "main", str(r), str(work))
    return str(r), str(work)


def test_checks_out_the_existing_pages_branch_and_publishes(tmp_path):
    remote, work = bare(tmp_path, with_pages=True)
    p = script("site-checkout.sh", "site", cwd=work)
    assert p.returncode == 0, p.stderr
    assert os.path.exists(os.path.join(work, "site", "index.json"))
    doc = tmp_path / "n1.json"
    doc.write_text(json.dumps(run("n1")))
    p = script("publish-site.sh", os.path.join(work, "site"), str(doc), cwd=work)
    assert p.returncode == 0, p.stderr
    pages = sh("git", "--git-dir", remote, "ls-tree", "-r", "--name-only", "gh-pages").split()
    assert "runs/n1.json" in pages


def test_starts_an_empty_pages_branch_when_the_remote_has_none(tmp_path):
    remote, work = bare(tmp_path, with_pages=False)
    p = script("site-checkout.sh", "site", cwd=work)
    assert p.returncode == 0, p.stderr
    assert sh("git", "-C", os.path.join(work, "site"), "ls-files") == ""
    doc = tmp_path / "n1.json"
    doc.write_text(json.dumps(run("n1")))
    p = script("publish-site.sh", os.path.join(work, "site"), str(doc), cwd=work)
    assert p.returncode == 0, p.stderr
    assert "runs/n1.json" in sh("git", "--git-dir", remote, "ls-tree", "-r", "--name-only",
                                "gh-pages").split()


def test_publish_recovers_against_a_stale_tracking_ref(tmp_path):
    """The retry path resets to origin/gh-pages; it must fetch into it."""
    remote, work = bare(tmp_path, with_pages=True)
    assert script("site-checkout.sh", "site", cwd=work).returncode == 0
    other = tmp_path / "other"
    sh("git", "clone", "-q", "-b", "gh-pages", remote, str(other))
    (other / "x").write_text("x\n")
    sh("git", "add", "x", cwd=other)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "x", cwd=other)
    sh("git", "push", "-q", "origin", "gh-pages", cwd=other)
    doc = tmp_path / "n1.json"
    doc.write_text(json.dumps(run("n1")))
    p = script("publish-site.sh", os.path.join(work, "site"), str(doc), cwd=work)
    assert p.returncode == 0, p.stderr
    pages = sh("git", "--git-dir", remote, "ls-tree", "-r", "--name-only", "gh-pages").split()
    assert {"x", "runs/n1.json"} <= set(pages)


def test_workflows_touch_the_site_worktree_only_in_the_container():
    bad = []
    for wf in glob.glob(os.path.join(REPO, ".github", "workflows", "*.yml")):
        for n, line in enumerate(open(wf), 1):
            s = line.strip()
            if re.search(r"\bgit\b.*\bworktree\b", s) or re.search(
                    r"(site-checkout|publish-site)\.sh", s) and not re.match(
                    r"(\$CI_RUN|ci) scripts/", s):
                bad.append(f"{os.path.basename(wf)}:{n}: {s}")
    assert not bad, bad
    uses = sum(open(wf).read().count("scripts/site-checkout.sh site")
               for wf in glob.glob(os.path.join(REPO, ".github", "workflows", "*.yml")))
    assert uses == 3
