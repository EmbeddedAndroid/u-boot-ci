"""publish-site.sh against a real (local) gh-pages remote: skip when
nothing changed, and recover when another workflow pushed first."""
import json
import os
import shutil
import subprocess

import pytest

from samples import run

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout


def clone(remote, path):
    sh("git", "clone", "-q", "-b", "gh-pages", remote, str(path))
    return str(path)


@pytest.fixture
def remote(tmp_path):
    r = tmp_path / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "gh-pages", str(r))
    seed = tmp_path / "seed"
    sh("git", "init", "-q", "-b", "gh-pages", str(seed))
    (seed / "README").write_text("pages\n")
    sh("git", "add", "README", cwd=seed)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "-m", "seed", cwd=seed)
    sh("git", "push", "-q", str(r), "gh-pages", cwd=seed)
    return str(r)


def publish(site, doc):
    subprocess.run([os.path.join(REPO, "scripts", "publish-site.sh"), site, doc], check=True,
                   capture_output=True, text=True)


def commits(remote):
    return int(sh("git", "--git-dir", remote, "rev-list", "--count", "gh-pages"))


def test_publish_skips_unchanged_and_survives_a_concurrent_push(tmp_path, remote):
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    na, nb = tmp_path / "n1.json", tmp_path / "c1.json"
    na.write_text(json.dumps(run("n1")))
    nb.write_text(json.dumps(run("c1", kind="pin-candidate")))
    publish(a, str(na))
    publish(b, str(nb))  # b is behind: its first push is rejected
    assert commits(remote) == 3
    doc = run("n1")
    doc["run"]["updated"] = "2026-10-24T09:00:00Z"
    na.write_text(json.dumps(doc))
    publish(a, str(na))  # only the stamp changed
    assert commits(remote) == 3
    final = clone(remote, tmp_path / "final")
    idx = json.load(open(os.path.join(final, "index.json")))
    assert sorted(r["id"] for r in idx["runs"]) == ["c1", "n1"]
    assert os.path.exists(os.path.join(final, "app.js"))
