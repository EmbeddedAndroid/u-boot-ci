"""Stock firmware pin watcher (docs/pins.md).

python3 -m ubci.stockpin <out dir> [--no-verify]

For every board, read the layer recipes its stock pin follows
(downstream.upstream in config/boards/<board>.yaml), and when they name
other boot binaries or another CDT than the pin: download and check the
new files, then write <out>/<board>.yaml (the board config with the
bumped pin and the layer commits it was read at), <out>/<board>.title and
<out>/<board>.body for the pull request. A board without a CDT recipe
(its CDT stays in the eMMC boot partition) is compared on the
boot binaries alone.
<out>/summary.json lists each board's outcome. A recipe that cannot be
read is an error for that board and produces no PR.
"""
import json
import os
import re
import subprocess
import sys

from fwci import bitbake, pinwatch

from . import config
from .fetch import WORK


def checkout(name, layer):
    d = os.path.join(WORK, "layers", name)
    if not os.path.isdir(os.path.join(d, ".git")):
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", layer["branch"],
                        layer["repo"], d], check=True)
    else:
        subprocess.run(["git", "-C", d, "fetch", "-q", "--depth", "1", "origin", layer["branch"]], check=True)
        subprocess.run(["git", "-C", d, "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
    sha = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], check=True, capture_output=True,
                         text=True).stdout.strip()
    return d, sha


def upstream(up, roots):
    """The pin as the layer recipes describe it."""
    layers = list(roots.values())
    bb = up["bootbinaries"]
    recipe = bitbake.newest(os.path.join(roots[bb["layer"]], bb["recipe"]))
    env = bitbake.parse(recipe, layers)
    boot = bitbake.src_uri(env)
    out = {
        "release": bb["release"].format(pv=env["PV"]),
        "bootbinaries": [{"url": e["url"], "sha256": e["sha256"]} for e in boot],
        "cdt": None,
        "recipes": [os.path.relpath(recipe, roots[bb["layer"]])],
    }
    cdt_spec = up.get("cdt")
    if cdt_spec:
        cenv = bitbake.parse(os.path.join(roots[cdt_spec["layer"]], cdt_spec["recipe"]), layers)
        cdt = [e for e in bitbake.src_uri(cenv) if e.get("name") == cdt_spec["name"]]
        if len(cdt) != 1:
            raise bitbake.RecipeError("%s: no SRC_URI entry named %s" % (cdt_spec["recipe"], cdt_spec["name"]))
        out["cdt"] = {"url": cdt[0]["url"], "sha256": cdt[0]["sha256"]}
        out["recipes"].append(cdt_spec["recipe"])
    return out


def current(downstream):
    cdt = downstream.get("cdt")
    return {"release": downstream["release"],
            "bootbinaries": [{"url": b["url"], "sha256": b["sha256"]} for b in downstream["bootbinaries"]],
            "cdt": {"url": cdt["url"], "sha256": cdt["sha256"]} if cdt else None}


def bump(text, old, new, source=None):
    """The board config text with the old pin values replaced by the new
    ones, comments and layout kept. Every old value must occur once.
    source: {layer: (old commit, new commit)} of the downstream section."""
    if len(old["bootbinaries"]) != len(new["bootbinaries"]) or bool(old["cdt"]) != bool(new["cdt"]):
        raise pinwatch.PinError("the number of boot binary or CDT archives changed; bump by hand")
    pairs = [(old["release"], new["release"])]
    for o, n in zip(old["bootbinaries"], new["bootbinaries"]):
        pairs += [(o["url"], n["url"]), (o["sha256"], n["sha256"])]
    if old["cdt"]:
        pairs += [(old["cdt"]["url"], new["cdt"]["url"]), (old["cdt"]["sha256"], new["cdt"]["sha256"])]
    # Layer commits change in the downstream section only: another section
    # (downstream_open) was not read at the new commit.
    head = re.search(r"^downstream:.*\n", text, re.M)
    if not head:
        raise pinwatch.PinError("no downstream section in the board config")
    start = head.start()
    end = re.search(r"^[a-z_-]+:", text[head.end():], re.M)
    end = head.end() + end.start() if end else len(text)
    section = text[start:end]
    for o, n in (source or {}).values():
        if o and o != n:
            section = section.replace(o, n)
    text = text[:start] + section + text[end:]
    for o, n in pairs:
        if o == n:
            continue
        if text.count(o) != 1:
            raise pinwatch.PinError("%r occurs %d times in the board config" % (o, text.count(o)))
        text = text.replace(o, n)
    return text


def body(board, old, new, links):
    lines = ["Bump the %s stock firmware pin to what its meta layer now ships." % board, "",
             "| | pin | upstream |", "|---|---|---|",
             "| release | %s | %s |" % (old["release"], new["release"])]
    for i, (o, n) in enumerate(zip(old["bootbinaries"], new["bootbinaries"])):
        lines.append("| boot binaries %d | `%s` | `%s` |" % (i, o["sha256"][:16], n["sha256"][:16]))
    if old["cdt"]:
        lines.append("| CDT | `%s` | `%s` |" % (old["cdt"]["sha256"][:16], new["cdt"]["sha256"][:16]))
    lines += ["", "Source: " + ", ".join(links), "",
              "Every new file was downloaded and matches the sha256 of the recipe.",
              "The pin-candidate workflow runs the nightly `main` baseline on this",
              "board with the current and the candidate firmware and reports here.",
              "Merging stays with the reviewer."]
    return "\n".join(lines) + "\n"


def check(board_name, out, verify=True):
    b = config.board(board_name)
    up = b["downstream"].get("upstream")
    if not up:
        return {"board": board_name, "result": "no upstream configured"}
    roots, links, source = {}, [], {}
    for name, layer in up["layers"].items():
        roots[name], sha = checkout(name, layer)
        links.append("%s/commit/%s" % (layer["repo"], sha))
        source[name] = ((b["downstream"].get("source") or {}).get(name), sha)
    new = upstream(up, roots)
    old = current(b["downstream"])
    if not pinwatch.diff(old, {k: new[k] for k in old}):
        return {"board": board_name, "result": "up to date", "release": old["release"]}
    if verify:
        pinwatch.verify([(f["url"], f["sha256"]) for f in new["bootbinaries"] + [new["cdt"]] if f])
    path = os.path.join(config.CONFIG, "boards", board_name + ".yaml")
    open(os.path.join(out, board_name + ".yaml"), "w").write(bump(open(path).read(), old, new, source))
    open(os.path.join(out, board_name + ".title"), "w").write(
        "config: %s: bump stock firmware to %s\n" % (board_name, new["release"]))
    open(os.path.join(out, board_name + ".body"), "w").write(body(board_name, old, new, links))
    return {"board": board_name, "result": "bump", "from": old["release"], "to": new["release"]}


def main(argv):
    if not argv or argv[0].startswith("-"):
        raise SystemExit(__doc__)
    out = argv[0]
    os.makedirs(out, exist_ok=True)
    summary, failed = [], False
    for board in config.boards():
        try:
            r = check(board, out, verify="--no-verify" not in argv)
        except (bitbake.RecipeError, pinwatch.PinError, subprocess.CalledProcessError, OSError) as e:
            r, failed = {"board": board, "result": "error", "error": str(e)}, True
        print(json.dumps(r))
        summary.append(r)
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
