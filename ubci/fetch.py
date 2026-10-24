"""Fetch a pinned file by URL into the cache and check its sha256.

python3 -m ubci.fetch <url> <sha256> [<name>]   prints the cached path.
A null URL means a file staged by hand in $UBCI_WORK/pins/<name> (a pin
not published yet); it is still checked against the sha256."""
import hashlib
import os
import shutil
import sys
import urllib.request

WORK = os.environ.get("UBCI_WORK", os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "work"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url, digest, name=None):
    if not digest:
        raise SystemExit("no sha256 pinned for %s" % (url or name))
    name = name or os.path.basename(url)
    if not url:
        path = os.path.join(WORK, "pins", name)
    else:
        path = os.path.join(WORK, "cache", digest[:16], name)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(tmp, path)
    if not os.path.exists(path):
        raise SystemExit("%s: not staged" % path)
    got = sha256(path)
    if got != digest:
        raise SystemExit("%s: sha256 %s, pinned %s" % (path, got, digest))
    return path


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    url = None if sys.argv[1] in ("", "None", "null") else sys.argv[1]
    print(fetch(url, sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else None))
