"""Distance to upstream: the patches a pinned component carries that its
upstream does not have, each with a link to where it is reviewed."""
import json
import re
import subprocess
import urllib.parse
import urllib.request


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), check=True,
                          capture_output=True, text=True).stdout


def review_link(message, resolve=None):
    """The review a commit points at: a Link: trailer, else what
    resolve(change_id) makes of its Gerrit Change-Id, else None."""
    m = re.search(r"^Link: (https://\S+)", message, re.M)
    if m:
        return m.group(1)
    m = re.search(r"^Change-Id: (I[0-9a-f]{40})", message, re.M)
    return resolve(m.group(1)) if m and resolve else None


def carried(repo, upstream, pin, resolve=None):
    """Commits in pin that upstream lacks: not upstream by patch id
    (git cherry) and no upstream commit since the merge base with the same
    subject (a patch merged after review changes). resolve(change_id)
    turns a Gerrit Change-Id into a change URL (or None) when a commit has
    no Link: trailer."""
    base = git(repo, "merge-base", upstream, pin).strip()
    upstream_subjects = set(git(repo, "log", "--format=%s", "%s..%s" % (base, upstream)).splitlines())
    out = []
    for line in git(repo, "cherry", upstream, pin).splitlines():
        sign, sha = line.split()[:2]
        if sign != "+":
            continue
        subject = git(repo, "log", "-1", "--format=%s", sha).strip()
        if subject in upstream_subjects:
            continue
        out.append({"commit": sha, "subject": subject,
                    "review": review_link(git(repo, "log", "-1", "--format=%B", sha), resolve)})
    return {"base": base, "distance": len(out), "carried": out}


def resolve_gerrit(gerrit, project, change_id, fetch=None):
    """The change URL on Gerrit for a Change-Id, or None when Gerrit does
    not know it (a patch that was never uploaded)."""
    fetch = fetch or (lambda u: urllib.request.urlopen(u, timeout=30).read().decode())
    text = fetch("%s/changes/?q=%s" % (gerrit.rstrip("/"),
                                       urllib.parse.quote("change:" + change_id)))
    changes = json.loads(text.split("\n", 1)[1])  # drop Gerrit's )]}' prefix
    if not changes:
        return None
    return "%s/c/%s/+/%d" % (gerrit.rstrip("/"), project, changes[0]["_number"])
