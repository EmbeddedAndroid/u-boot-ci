"""Pin watcher: compare a pin with what its upstream now names, verify
the new files, and keep one pull request per pin up to date. Used for the
downstream firmware pins; open-stack pins (TF-A, OP-TEE tips) plug in the same
way with their own `current`/`upstream` readers.

python3 -m fwci.pinwatch pr <branch> <title file> <body file> [--check]
    opens the PR for <branch>, or updates the open one (never a second one,
    never one a reviewer closed); --check only prints "declined" or "ok".
    Needs the gh CLI and GH_TOKEN. Standard library only, so it runs on the
    runner host next to git and gh.
"""
import hashlib
import json
import subprocess
import sys
import urllib.request


class PinError(Exception):
    pass


def diff(current, upstream):
    """{field: (current, upstream)} for every field that differs."""
    return {k: (current.get(k), v) for k, v in upstream.items() if current.get(k) != v}


def verify(files, fetch=None):
    """Download every (url, sha256) and check it; raises PinError on the
    first mismatch, so no pull request is opened for a pin that does not
    match its own upstream."""
    fetch = fetch or (lambda u: urllib.request.urlopen(u, timeout=600))
    for url, digest in files:
        h = hashlib.sha256()
        with fetch(url) as r:
            for block in iter(lambda: r.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != digest:
            raise PinError("%s: sha256 %s, upstream recipe says %s" % (url, h.hexdigest(), digest))


def gh(*args):
    return subprocess.run(["gh"] + list(args), check=True, capture_output=True, text=True).stdout


def prs(branch, run):
    return json.loads(run("pr", "list", "--head", branch, "--state", "all",
                          "--json", "number,title,body,state"))


def _pin(body):
    """The part of a PR body that names the pin (the source links after
    it change every day)."""
    return body.split("\nSource:")[0]


def _closed(found, title, body):
    return any(p["state"] == "CLOSED" and p["title"] == title and _pin(p["body"]) == _pin(body)
               for p in found)


def declined(branch, title, body, run=gh):
    """A reviewer closed this very bump without merging it."""
    return _closed(prs(branch, run), title, body)


def open_or_update_pr(branch, title, body, run=gh, base="main"):
    """One PR per pin branch: edit the open one when there is one, create
    it otherwise, and never reopen a bump a reviewer closed. Returns
    (action, number or url)."""
    found = prs(branch, run)
    if _closed(found, title, body):
        return "declined", None
    open_ = [p for p in found if p["state"] == "OPEN"]
    if open_:
        pr = open_[0]
        if pr.get("title") == title and pr.get("body") == body:
            return "unchanged", pr["number"]
        run("pr", "edit", str(pr["number"]), "--title", title, "--body", body)
        return "updated", pr["number"]
    url = run("pr", "create", "--head", branch, "--base", base, "--title", title, "--body", body).strip()
    return "created", url


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6) or sys.argv[1] != "pr":
        raise SystemExit(__doc__)
    title = open(sys.argv[3]).read().strip()
    if sys.argv[5:] == ["--check"]:
        print("declined" if declined(sys.argv[2], title, open(sys.argv[4]).read()) else "ok")
    else:
        print("%s %s" % open_or_update_pr(sys.argv[2], title, open(sys.argv[4]).read()))
