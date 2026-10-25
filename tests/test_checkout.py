"""scripts/checkout.sh fetches a pinned commit from the pin's repository,
not from whichever repository the shared clone came from first."""
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args, cwd=None):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e"] + list(args), cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def repo_with_commit(path, msg):
    git("init", "-q", str(path))
    (path / "f").write_text(msg)
    git("add", "f", cwd=str(path))
    git("commit", "-q", "-m", msg, cwd=str(path))
    return git("rev-parse", "HEAD", cwd=str(path))


def test_a_commit_of_another_repository_is_fetched_from_it(tmp_path):
    upstream = tmp_path / "upstream"
    fork = tmp_path / "fork"
    a = repo_with_commit(upstream, "upstream")
    b = repo_with_commit(fork, "fork")
    env = dict(os.environ, UBCI_WORK=str(tmp_path / "work"))
    run = lambda url, sha: subprocess.run([os.path.join(REPO, "scripts", "checkout.sh"), "optee_os", url, sha],
                                          env=env, capture_output=True, text=True)
    p = run(str(upstream), a)
    assert p.returncode == 0, p.stderr
    p = run(str(fork), b)
    assert p.returncode == 0, p.stderr
    d = p.stdout.strip()
    assert git("rev-parse", "HEAD", cwd=d) == b and open(os.path.join(d, "f")).read() == "fork"
    p = run(str(upstream), "0" * 40)
    assert p.returncode != 0
