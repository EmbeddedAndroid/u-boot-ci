"""Board, pin and project configuration (config/*.yaml).

python3 -m ubci.config get <board> <dotted.key>  prints one value (for the
shell scripts); lists print one item per line.
python3 -m ubci.config configs <board> <stack> <u-boot source>
    prints the U-Boot configs to build with, resolved against the tree."""
import glob
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
STACKS = ("stock", "open")


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


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "get":
        v = get(board(sys.argv[2]), sys.argv[3])
        print("\n".join(str(x) for x in v) if isinstance(v, list) else v)
    elif len(sys.argv) == 5 and sys.argv[1] == "configs":
        print(" ".join(resolve_configs(get(board(sys.argv[2]), "u-boot.%s.configs" % sys.argv[3]),
                                       sys.argv[4])))
    else:
        raise SystemExit(__doc__)
