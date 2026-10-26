"""Stacked series for an ad-hoc run (docs/adhoc-runs.md).

python3 -m ubci.stack fetch <dir> <Message-ID or lore link>...
    b4-fetches each series, in order, into <dir> (s01.mbx, s01.cover, ...),
    adds a series a cover letter names as prerequisite-message-id in front
    of it when the stack lacks it (by Message-ID, or by its patches: a
    RESEND under another Message-ID is the same series and is recorded as
    "also_posted_as" instead of being applied twice), and writes
    <dir>/stack.json, where
    "touches_spl" says whether a series changes SPL code (an ad-hoc run
    that named no stacks then runs the SPL stack too).
python3 -m ubci.stack apply <u-boot source> <dir>
    applies the stack onto the checkout with git am and writes the result
    (which series applied, the patch that did not) back to stack.json.
    Exits 0 either way; "applies" in stack.json says which.
"""
import json
import mailbox
import os
import re
import subprocess
import sys

from fwci import series


def b4_am(outdir, name, msgid):
    subprocess.run(["b4", "--no-stdin", "am", "-o", outdir, "-n", name, msgid], check=True,
                   capture_output=True, text=True)
    return os.path.join(outdir, name + ".mbx"), os.path.join(outdir, name + ".cover")


# A patch about SPL: "SPL" in its subject, a file of the SPL build
# (common/spl/, board_spl.c, *_spl_defconfig, spl-<board>.c, include/spl.h,
# ...) or a new SPL_ Kconfig symbol.
SPL_SUBJECT = re.compile(r"\bSPL\b")
SPL_PATH = re.compile(r"^\+\+\+ b/(?:\S*/)?\S*(?<![a-z])spl(?![a-z])", re.M | re.I)
SPL_SYMBOL = re.compile(r"^\+\s*(?:menu)?config\s+SPL_", re.M)


def touches_spl(mbx):
    for m in mailbox.mbox(mbx):
        text = m.as_bytes().decode("utf-8", "replace")
        if SPL_SUBJECT.search(series.subject(m)) or SPL_PATH.search(text) or SPL_SYMBOL.search(text):
            return True
    return False


def patch_ids(mbx):
    """The stable patch ids of the patches of an mbox."""
    out = subprocess.run(["git", "patch-id", "--stable"], stdin=open(mbx, "rb"), check=True,
                         capture_output=True).stdout.decode()
    return frozenset(line.split()[0] for line in out.splitlines())


def fetch(outdir, wanted, am=b4_am):
    os.makedirs(outdir, exist_ok=True)
    stack, seen, ids = [], set(), {}

    def add(msgid, added_for=None):
        if msgid in seen:
            return
        seen.add(msgid)
        name = "s%02d" % (len(seen))
        mbx, cover = am(outdir, name, msgid)
        pids = patch_ids(mbx)
        same = next((s for s in stack if ids[s["message_id"]] == pids), None)
        if same:
            same.setdefault("also_posted_as", []).append(msgid)
            os.remove(mbx)
            return
        ids[msgid] = pids
        s = dict(series.describe(mbx, cover), message_id=msgid, mbx=mbx,
                 link="https://lore.kernel.org/r/" + msgid, touches_spl=touches_spl(mbx))
        if added_for:
            s["added_as_prerequisite_of"] = added_for
        for p in s["prerequisites"]["message_ids"]:
            add(series.message_id(p), msgid)
        stack.append(s)

    for w in wanted:
        add(series.message_id(w))
    json.dump(stack, open(os.path.join(outdir, "stack.json"), "w"), indent=1)
    return stack


def apply(src, outdir):
    path = os.path.join(outdir, "stack.json")
    stack = json.load(open(path))
    for s in stack:
        s["mbx"] = os.path.join(outdir, os.path.basename(s["mbx"]))
    series.apply(src, stack)
    json.dump(stack, open(path, "w"), indent=1)
    return all(s["applied"] for s in stack)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "fetch":
        for s in fetch(sys.argv[2], sys.argv[3:]):
            print("%s v%d, %d patches: %s" % (s["message_id"], s["version"], s["patches"], s["title"]))
    elif len(sys.argv) == 4 and sys.argv[1] == "apply":
        print("applies" if apply(sys.argv[2], sys.argv[3]) else "does not apply")
    else:
        raise SystemExit(__doc__)
