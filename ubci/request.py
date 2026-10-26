"""An ad-hoc run request: series, base, boards and stacks, from the
workflow_dispatch inputs or an issue form, checked before anything runs.

python3 -m ubci.request inputs <series> <base> <boards> <stacks>
python3 -m ubci.request issue <issue body file>
    print GITHUB_OUTPUT lines (series, base, targets, title), or exit 1
    with the reason. Standard library only (runs on the runner host)."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fwci.series import message_id  # noqa: E402

BASES = ("main", "master")
STACKS = ("stock", "open", "spl")
# No stacks named: stock and open, and spl when the stack touches SPL
# code ("spl?", resolved by ubci.run new once the series are fetched).
DEFAULT_STACKS = ("stock", "open", "spl?")


def boards():
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "boards")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".yaml"))


def check(series, base, board_list, stack_list):
    ids = [message_id(s) for s in re.split(r"[\s,]+", series.strip()) if s]
    if not ids:
        raise ValueError("no series given")
    if base not in BASES:
        raise ValueError("base must be one of %s" % ", ".join(BASES))
    bl = [b for b in re.split(r"[\s,]+", board_list.strip()) if b] or boards()
    sl = [s for s in re.split(r"[\s,]+", stack_list.strip()) if s]
    for b in bl:
        if b not in boards():
            raise ValueError("unknown board %r" % b)
    for s in sl:
        if s not in STACKS:
            raise ValueError("unknown stack %r" % s)
    sl = sl or list(DEFAULT_STACKS)
    return {"series": " ".join(ids), "base": base,
            "targets": ",".join("%s:%s" % (b, s) for b in bl for s in sl)}


def from_issue(body):
    """The answers of .github/ISSUE_TEMPLATE/adhoc-run.yml ("### <label>"
    sections; "_No response_" when left empty)."""
    fields = {}
    for m in re.finditer(r"^### (.+?)\s*\n(.*?)(?=^### |\Z)", body, re.M | re.S):
        v = m.group(2).strip()
        fields[m.group(1).strip().lower()] = "" if v == "_No response_" else v
    return check(fields.get("series", ""), fields.get("base", "main") or "main",
                 fields.get("boards", ""), fields.get("stacks", ""))


if __name__ == "__main__":
    try:
        if len(sys.argv) == 6 and sys.argv[1] == "inputs":
            r = check(*sys.argv[2:6])
        elif len(sys.argv) == 3 and sys.argv[1] == "issue":
            r = from_issue(open(sys.argv[2]).read())
        else:
            raise SystemExit(__doc__)
    except ValueError as e:
        raise SystemExit("invalid request: %s" % e)
    for k, v in r.items():
        print("%s=%s" % (k, v))
    print("request=%s" % json.dumps(r))
