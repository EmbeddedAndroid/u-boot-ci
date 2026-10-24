"""Just enough of BitBake's recipe syntax to read a firmware pin: plain
assignments, require/include, ${VAR} expansion, SRC_URI entries and their
sha256sum flags. Anything it cannot expand is an error, never a guess."""
import glob
import os
import re

ASSIGN = re.compile(r'^([A-Za-z0-9_\-]+)(\[[^\]]+\])?\s*(\?\?=|\?=|:=|\+=|=\+|=)\s*"(.*)"\s*$')
INCLUDE = re.compile(r'^(require|include)\s+(\S+)\s*$')
VAR = re.compile(r"\$\{([A-Za-z0-9_\-]+)\}")


class RecipeError(Exception):
    pass


def _lines(text):
    """Logical lines: comments dropped, backslash continuations joined."""
    out, cur = [], ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not cur and line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            cur += line[:-1] + " "
            continue
        out.append((cur + line).strip())
        cur = ""
    if cur:
        out.append(cur.strip())
    return [l for l in out if l]


def _find(name, here, layers):
    for base in [here] + list(layers):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return None


def parse(path, layers=(), env=None, depth=0):
    """Variables (and flags as 'VAR[flag]') a recipe sets, following
    require/include through the recipe's directory and the layer roots."""
    if depth > 10:
        raise RecipeError("include depth exceeded at %s" % path)
    env = env if env is not None else {}
    if depth == 0:
        # BitBake takes PN and PV from <pn>_<pv>.bb; PV defaults to 1.0.
        m = re.match(r"^(.+?)(?:_([^_/]+))?\.bb$", os.path.basename(path))
        if m:
            env.setdefault("PN", m.group(1))
            env.setdefault("PV", m.group(2) or "1.0")
    for line in _lines(open(path).read()):
        inc = INCLUDE.match(line)
        if inc:
            target = _find(VAR.sub(lambda v: env.get(v.group(1), v.group(0)), inc.group(2)),
                           os.path.dirname(path), layers)
            if target is None:
                if inc.group(1) == "require":
                    raise RecipeError("%s: required file %s not found" % (path, inc.group(2)))
                continue
            parse(target, layers, env, depth + 1)
            continue
        a = ASSIGN.match(line)
        if not a:
            # A pin must never be read from half a recipe.
            if re.match(r"(SRC_URI|PV)\b", line):
                raise RecipeError("%s: cannot read %r" % (path, line))
            continue
        name = a.group(1) + (a.group(2) or "")
        op, value = a.group(3), a.group(4)
        if op in ("?=", "??=") and name in env:
            continue
        if op == "+=":
            value = (env.get(name, "") + " " + value).strip()
        elif op == "=+":
            value = (value + " " + env.get(name, "")).strip()
        env[name] = value
    return env


def expand(env, value, seen=()):
    def one(m):
        name = m.group(1)
        if name in seen or name not in env:
            raise RecipeError("cannot expand ${%s}" % name)
        return expand(env, env[name], seen + (name,))
    return VAR.sub(one, value)


def src_uri(env):
    """SRC_URI entries as dicts: url plus their ;key=value parameters, and
    the sha256sum flag of each named entry."""
    if "SRC_URI" not in env:
        raise RecipeError("no SRC_URI")
    out = []
    for item in expand(env, env["SRC_URI"]).split():
        url, *params = item.split(";")
        e = {"url": url}
        e.update(p.split("=", 1) for p in params if "=" in p)
        name = e.get("name")
        sha = env.get("SRC_URI[%s.sha256sum]" % name) if name else env.get("SRC_URI[sha256sum]")
        if not sha or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise RecipeError("%s: no sha256sum" % (name or url))
        e["sha256"] = sha
        out.append(e)
    return out


def newest(pattern):
    """The recipe matching the glob with the highest version (PV)."""
    files = glob.glob(pattern)
    if not files:
        raise RecipeError("no recipe matches %s" % pattern)

    def key(p):
        pv = re.match(r"^.+?_([^_/]+)\.bb$", os.path.basename(p))
        return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", pv.group(1) if pv else "")]
    return max(files, key=key)
