"""Stacked series for an ad-hoc run (docs/adhoc-runs.md).

python3 -m ubci.stack fetch <dir> <Message-ID or lore link>...
    b4-fetches each series, in order, into <dir> (s01.mbx, s01.cover, ...),
    adds a series a cover letter names as prerequisite-message-id in front
    of it when the stack lacks it, and writes <dir>/stack.json.
python3 -m ubci.stack apply <u-boot source> <dir>
    applies the stack onto the checkout with git am and writes the result
    (which series applied, the patch that did not) back to stack.json.
    Exits 0 either way; "applies" in stack.json says which.
"""
import json
import os
import subprocess
import sys

from fwci import series


def b4_am(outdir, name, msgid):
    subprocess.run(["b4", "--no-stdin", "am", "-o", outdir, "-n", name, msgid], check=True,
                   capture_output=True, text=True)
    return os.path.join(outdir, name + ".mbx"), os.path.join(outdir, name + ".cover")


def fetch(outdir, wanted, am=b4_am):
    os.makedirs(outdir, exist_ok=True)
    stack, seen = [], set()

    def add(msgid, added_for=None):
        if msgid in seen:
            return
        seen.add(msgid)
        name = "s%02d" % (len(seen))
        mbx, cover = am(outdir, name, msgid)
        s = dict(series.describe(mbx, cover), message_id=msgid, mbx=mbx,
                 link="https://lore.kernel.org/r/" + msgid)
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
