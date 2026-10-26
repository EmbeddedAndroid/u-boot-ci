"""Patch series from a mailing list: what a series is (version, patches,
the prerequisites its cover letter declares) and stacking several of them
onto a base with git am, recording where one does not apply. Fetching is
the caller's job (b4 am writes the mbox and the cover letter)."""
import email
import mailbox
import os
import re
import subprocess

SUBJECT = re.compile(r"^\[([^\]]*PATCH[^\]]*)\]\s*(.*)$")


def message_id(text):
    """A Message-ID from a bare id, <id>, or a lore / patch.msgid.link URL."""
    t = text.strip().strip("<>")
    m = re.match(r"^https?://[^/]+/(?:[^/]+/)?([^/]+@[^/]+?)/?(?:[Tt]/?.*)?$", t)
    if m:
        t = m.group(1)
    if not re.fullmatch(r"[^\s<>/]+@[^\s<>/]+", t):
        raise ValueError("not a Message-ID or lore link: %r" % text)
    return t


def subject(msg):
    return " ".join(str(email.header.make_header(email.header.decode_header(msg["Subject"] or ""))).split())


def describe(mbx, cover=None):
    """Version, patch count, title and declared prerequisites of a series."""
    patches = [subject(m) for m in mailbox.mbox(mbx)]
    if not patches:
        raise ValueError("%s holds no patch" % mbx)
    m = SUBJECT.match(patches[0])
    v = re.search(r"\bv(\d+)\b", m.group(1)) if m else None
    version = int(v.group(1)) if v else 1
    title = patches[0]
    prereq = {"message_ids": [], "patch_ids": [], "change_ids": []}
    if cover and os.path.exists(cover):
        text = open(cover, errors="replace").read()
        first = re.search(r"^Subject: (.*)$", text, re.M)
        if first:
            cm = SUBJECT.match(first.group(1).strip())
            title = cm.group(2) if cm else first.group(1).strip()
        for key, field in (("prerequisite-message-id", "message_ids"),
                           ("prerequisite-patch-id", "patch_ids"),
                           ("prerequisite-change-id", "change_ids")):
            prereq[field] = re.findall(r"^%s: <?([^\s>]+)>?\s*$" % key, text, re.M)
    elif m:
        title = m.group(2)
    return {"version": version, "patches": len(patches), "title": title,
            "prerequisites": prereq}


def git(src, *args, check=True):
    return subprocess.run(["git", "-C", src] + list(args), check=check, capture_output=True, text=True)


def patch_ids(src, base):
    """Stable patch ids of the commits on top of base."""
    out = set()
    for sha in git(src, "rev-list", "%s..HEAD" % base).stdout.split():
        show = subprocess.run(["git", "-C", src, "show", sha], capture_output=True, text=True, check=True)
        pid = subprocess.run(["git", "-C", src, "patch-id", "--stable"], input=show.stdout,
                             capture_output=True, text=True, check=True).stdout.split()
        if pid:
            out.add(pid[0])
    return out


def apply(src, stack, ident=("u-boot-ci", "u-boot-ci@users.noreply.github.com")):
    """git am each series of the stack, in order, onto the checkout. A
    series that does not apply is aborted and recorded with the patch that
    failed; the ones after it are not tried. Returns the stack with
    "applied" (True, False, None for not tried) and, at the end, every
    declared prerequisite patch id the stack does not carry."""
    base = git(src, "rev-parse", "HEAD").stdout.strip()
    env = ["-c", "user.name=%s" % ident[0], "-c", "user.email=%s" % ident[1]]
    failed = False
    for s in stack:
        if failed:
            s["applied"] = None
            continue
        # git -C resolves a relative mbox against the checkout, not the caller.
        r = git(src, *env, "am", "--3way", os.path.abspath(s["mbx"]), check=False)
        if r.returncode == 0:
            s["applied"] = True
            continue
        failed = True
        s["applied"] = False
        nxt = os.path.join(src, git(src, "rev-parse", "--git-path", "rebase-apply/next").stdout.strip())
        cur = git(src, *env, "am", "--show-current-patch=raw", check=False).stdout
        sub = re.search(r"^Subject: (.*(?:\n[ \t]+.*)*)", cur, re.M)
        # The "Patch failed at" line, else git's last word before its hints.
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not l.startswith("hint:")]
        lines = [l for l in lines if l.startswith("Patch failed at")] or lines
        s["failed_patch"] = {
            "number": int(open(nxt).read()) if os.path.exists(nxt) else None,
            "subject": " ".join(sub.group(1).split()) if sub else "",
            "error": lines[-1][:200] if lines else "",
        }
        # Without an identity git 2.43 refuses --show-current-patch and --abort.
        git(src, *env, "am", "--abort", check=False)
    have = patch_ids(src, base) if not failed else set()
    for s in stack:
        s["unresolved_prerequisites"] = [p for p in s["prerequisites"]["patch_ids"] if p not in have] \
            if not failed else []
    return stack
