"""Board, pin and project configuration (config/*.yaml).

python3 -m ubci.config get <board> <dotted.key>  prints one value (for the
shell scripts); lists print one item per line.
python3 -m ubci.config configs <board> <stack> <u-boot source>
    prints the U-Boot configs to build with, resolved against the tree.
python3 -m ubci.config missing <board> <stack> <u-boot source> [--adhoc]
    prints why the target cannot be built (its device tree or a config is
    not in the tree, the board has no SPL in it, or an open-stack pin is
    not public yet), nothing when it can; --adhoc when the tree is a base
    with series applied.
python3 -m ubci.config bootimg <board> <stack>
    prints the ubci.bootimg options of a stack that boots U-Boot as an
    Android boot image."""
import glob
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
STACKS = ("stock", "open", "spl")


def downstream(b, stack):
    """The downstream (vendor) firmware package a stack is built on: the
    board's downstream section, or downstream_open for the open and SPL
    stacks of a board whose open stack needs other boot firmware (UNO Q:
    the edk2-based release whose XBL loads TF-A BL2 and the FIP; Lemans:
    the XBLConfig that takes the SPL path)."""
    if stack in ("open", "spl") and b.get("downstream_open"):
        return b["downstream_open"]
    return b["downstream"]


def pending(b, stack):
    """Why a stack cannot be built yet although the base has the board:
    an open-stack pin whose commit is not published (pins.yaml pending),
    or None."""
    if stack == "stock":
        return None
    for name in ("tf-a", "optee", "bl2") if stack == "open" else ("tf-a", "optee"):
        pin = (b.get("pins") or {}).get(name) or {}
        if pin.get("pending"):
            return "open-stack pin not public yet: %s %s (%s)" % (
                name, pin.get("commit", "")[:12], pin["pending"])
    return None


def board(name):
    path = os.path.join(CONFIG, "boards", name + ".yaml")
    if not os.path.exists(path):
        raise SystemExit("unknown board %s" % name)
    b = yaml.safe_load(open(path))
    b["pins"] = pins().get(name)
    return b


def boards():
    return sorted(f[:-5] for f in os.listdir(os.path.join(CONFIG, "boards")) if f.endswith(".yaml"))


def pins():
    return yaml.safe_load(open(os.path.join(CONFIG, "pins.yaml")))["boards"]


def project():
    return yaml.safe_load(open(os.path.join(CONFIG, "project.yaml")))


def get(obj, dotted):
    for k in dotted.split("."):
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj


def _in_tree(src, name):
    return bool(glob.glob(os.path.join(src, "configs", name)) or
                glob.glob(os.path.join(src, "board", "*", name)) or
                glob.glob(os.path.join(src, "arch", "*", "configs", name)))


def resolve_configs(entries, src):
    """U-Boot configs for a tree. "a|b" takes the first that exists (a
    defconfig a series renames); "x?" is used only when the tree has it (a
    fragment a series adds). Anything else must exist."""
    out = []
    for e in entries:
        optional = e.endswith("?")
        names = e.rstrip("?").split("|")
        found = [n for n in names if _in_tree(src, n)]
        if found:
            out.append(found[0])
        elif not optional:
            raise SystemExit("none of %s in %s" % (" | ".join(names), src))
    return out


def _dt_in_tree(src, dt):
    name = dt + ".dts"
    return any(os.path.exists(os.path.join(src, d, n)) for d, n in (
        ("dts/upstream/src/arm64", name), ("arch/arm/dts", name),
        ("arch/arm/dts", os.path.basename(name))))


def series_line(s):
    return "%s v%d <%s>" % (s["title"], s.get("version", 1), s["message_id"])


def no_spl(b, adhoc, why=None):
    """Why a board's SPL stack has nothing to build: its SPL config is not
    in the tree (why: "no upstream SPL" on a base, "no SPL in the tested
    tree" with series applied), or the board has no SPL config to look
    for; then the gaps and the series in flight that would add it
    (spl.in_flight), or that none is in flight."""
    spl = b.get("spl") or {}
    if why is None:
        head = "no SPL stack for this board"
    else:
        head = "no SPL in the tested tree" if adhoc else "no upstream SPL"
    parts = [why] if why else []
    parts += spl.get("gaps", [])
    flight = spl.get("in_flight", [])
    parts.append("in flight: " + "; ".join(series_line(s) for s in flight) if flight
                 else "no SPL in flight for this board")
    return "%s: %s" % (head, "; ".join(parts))


def missing(name, stack, src, adhoc=False):
    """Why the target cannot be built from the tree at src, or None: the
    base predates the board (master before the board's DT was imported;
    "board not in this base: ..."), the tree has no SPL for the board
    (ubci.config.no_spl) or an open-stack pin is not public yet. Each
    skips the target instead of failing its build."""
    b = board(name)
    if stack == "spl" and "spl" not in b["u-boot"]:
        return no_spl(b, adhoc)
    u = b["u-boot"][stack]
    if not _dt_in_tree(src, u["device_tree"]):
        return "board not in this base: no %s device tree" % u["device_tree"]
    if stack == "spl":
        # Only the SPL defconfig decides "no SPL"; a missing fragment does not.
        try:
            resolve_configs(u["configs"][:1], src)
        except SystemExit as e:
            return no_spl(b, adhoc, str(e).replace(" in %s" % src, "").replace("none of ", "") + " not in the tree")
    try:
        resolve_configs(u["configs"], src)
    except SystemExit as e:
        return "board not in this base: " + str(e).replace(" in %s" % src, "")
    return pending(b, stack)


def fragments(entries, used):
    """The configs a build used and the optional ones ("x?") the base did
    not have: [{"name", "used"}] in the board's order, so a report shows
    a board fragment missing from the base instead of reading as a
    tested series."""
    out = []
    for e in entries:
        names = e.rstrip("?").split("|")
        hit = next((n for n in names if n in used), None)
        out.append({"name": hit or names[0], "used": bool(hit), "optional": e.endswith("?")})
    return out


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "get":
        v = get(board(sys.argv[2]), sys.argv[3])
        print("\n".join(str(x) for x in v) if isinstance(v, list) else v)
    elif len(sys.argv) == 5 and sys.argv[1] == "configs":
        print(" ".join(resolve_configs(get(board(sys.argv[2]), "u-boot.%s.configs" % sys.argv[3]),
                                       sys.argv[4])))
    elif len(sys.argv) == 4 and sys.argv[1] == "bootimg":
        bi = get(board(sys.argv[2]), "u-boot.%s" % sys.argv[3]).get("bootimg", {})
        print(" ".join("--%s %s" % (k, bi[k]) for k in ("base", "pagesize") if k in bi))
    elif len(sys.argv) in (5, 6) and sys.argv[1] == "missing" and sys.argv[5:] in ([], ["--adhoc"]):
        print(missing(sys.argv[2], sys.argv[3], sys.argv[4], adhoc=len(sys.argv) == 6) or "")
    else:
        raise SystemExit(__doc__)
