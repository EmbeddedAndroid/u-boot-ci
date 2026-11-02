# SPDX-License-Identifier: MIT
"""Per-stage boot times from a LAVA job log.

Times are host-side: the arrival time LAVA stamps on each console line,
relative to the instant the dispatcher ran the device's power-on command
(or, for a warm reboot, to the kernel's "reboot: Restarting system" line,
and for a reset from the U-Boot prompt, to U-Boot's "resetting ..." line).
Nothing here trusts a clock on the target.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import yaml

# Stages every chain prints the same way: upstream banners of U-Boot, TF-A,
# OP-TEE and Linux. Stage key -> pattern; a stage is the first console line
# matching its pattern after the start of the boot.
STAGES = {
    "spl": r"U-Boot SPL 20\d\d\.",
    "bl2": r"NOTICE:\s+BL2: v",
    "bl31": r"NOTICE:\s+BL31: v",
    "optee": r"OP-TEE version",
    "uboot": r"U-Boot 20\d\d\.",
    "linux": r"Booting Linux on physical CPU",
    "init": r"Run \S+ as init process",
    "login": r"(?<!Last )login:",
}
# Chains whose first stage prints nothing we know (a silent boot ROM) start
# the boot at the first of these.
ANCHORS = ("spl", "bl2")
PLATFORM_DIR = os.path.join(os.path.dirname(__file__), "platforms")
PLATFORM_KEYS = {"loaders", "stages", "stacks", "families"}


def load_platforms(paths=()):
    """Platform files: the ones shipped here, then each of paths (a file,
    or a directory of *.yaml files), in that order."""
    files = []
    for p in [PLATFORM_DIR, *paths]:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p)
                            if f.endswith(".yaml"))
        else:
            files.append(p)
    out = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        if not isinstance(d, dict):
            raise ValueError(f"{path}: not a mapping")
        stages = d.get("stages") or {}
        bad = d.keys() - PLATFORM_KEYS or stages.keys() & {"loader", *STAGES}
        if bad:
            raise ValueError(f"{path}: unknown or reserved keys {sorted(bad)}")
        bad = [k for k, ld in (d.get("loaders") or {}).items()
               if "first" not in (ld or {})]
        bad += [k for k, st in stages.items() if "pattern" not in (st or {})]
        if bad:
            raise ValueError(f"{path}: no first or pattern for {bad}")
        for x in [*(d.get("loaders") or {}).values(), *stages.values()]:
            for key in ("first", "build", "pattern"):
                try:
                    re.compile(x.get(key) or "")
                except re.error as e:
                    raise ValueError(f"{path}: {key}: {e}") from None
        d["name"] = path
        out.append(d)
    return out


def configure(paths=()):
    """Load the platform files; see load_platforms."""
    global PLATFORMS, LOADERS, STAGE_ORDER, STAGE_LABELS, FAMILIES
    PLATFORMS = load_platforms(paths)
    LOADERS, STAGE_LABELS, FAMILIES = {}, {}, {}
    order = []
    for p in PLATFORMS:
        for name, ld in (p.get("loaders") or {}).items():
            if name in LOADERS:
                raise ValueError(f"{p['name']}: loader {name} defined twice")
            LOADERS[name] = (p, ld)
        for key, st in (p.get("stages") or {}).items():
            if key not in order:
                order.append(key)
            STAGE_LABELS.setdefault(key, st.get("label", key))
        FAMILIES.update(p.get("families") or {})
    STAGE_ORDER = ["loader"] + order + list(STAGES)


configure(p for p in os.environ.get("BOOTTIME_PLATFORMS", "")
          .split(os.pathsep) if p)

# LAVA's own timing of the boot, from the "lava" suite results: login-action
# starts once the kernel start message ("Linux version") matched and lasts
# until the shell is logged in; kernel-messages starts with it and ends at
# the first prompt that is not a kernel error (the login prompt, or the shell
# prompt for a job without auto_login). Mark key -> (case, field) for the
# cross-check columns.
LOGIN_ACTION = "login-action"
LAVA_MARKS = {
    "lava_login_start": (LOGIN_ACTION, "start"),
    "lava_kernel_messages_end": ("kernel-messages", "end"),
    "lava_login_end": (LOGIN_ACTION, "end"),
}
LAVA_CASES = {case for case, _ in LAVA_MARKS.values()}
POWER_ACTIONS = ("pdu-reboot", "power-on")
FASTBOOT = "boot-fastboot"
REBOOT = re.compile(r"reboot: Restarting system")
# U-Boot's reset command (cmd/boot.c) prints this line, alone, just before
# it resets the system.
UBOOT_RESET = re.compile(r"^resetting \.\.\.$")
ATTACH = re.compile(r"^Connected to ")
LOGIN_MATCH = re.compile(r"Matched prompt #\d+: .*login:")
ACTION = re.compile(r"^(start|end): (\S+) (\S+)")
CALLING = re.compile(r"^Calling: \[(.*)\]")
# The dispatcher does not read the console while it runs a blocking action
# (the power command, a fastboot boot), and ser2net replays what it buffered
# when a client connects. That backlog is logged as one burst at the first
# console read after the reference, or after "Connected to": lines under
# BURST_GAP apart carrying more than twice what a 115200 baud UART delivers
# (bursts of 26 KB in 24 ms seen, against 11.5 bytes per ms live, read in
# chunks of up to CHUNK). Arrival times in such a burst, or within
# REPLAY_WINDOW of the power action ending, say nothing about when the line
# was printed.
BURST_GAP = 0.002
CHUNK = 0.02
UART_RATE = 11520
REPLAY_WINDOW = 0.1
JUNK = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x08\x0b-\x1f�]")
FINGERPRINT = re.compile(r"BL31: v[^:]*:(\S+)")
SAFE = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@dataclass
class Line:
    n: int
    t: float
    lvl: str
    msg: object


@dataclass
class Stage:
    t: float
    line: int
    text: str
    replayed: bool = False


@dataclass
class Boot:
    index: int
    ref_kind: str
    ref_line: int
    ref_t: float
    live: float = None
    loader: str = None
    loader_build: str = None
    loader_build_line: int = None
    fastboot: bool = False
    reset: float = None
    reset_line: int = None
    stages: dict = field(default_factory=dict)
    lava: dict = field(default_factory=dict)

    @property
    def stack(self):
        """The loader's stack label, else the first label of its platform
        whose stages the boot printed; None where there are no labels."""
        if self.loader is None:
            return None
        platform, loader = LOADERS[self.loader]
        stacks = platform.get("stacks") or {}
        if "stack" in loader:
            return loader["stack"]
        for label, keys in stacks.items():
            if self.stages.keys() & set(keys):
                return label
        return "unknown" if stacks else None

    @property
    def complete(self):
        return "login" in self.stages

    @property
    def last_stage(self):
        seen = [k for k in STAGE_ORDER if k in self.stages]
        return seen[-1] if seen else None

    @property
    def fingerprint(self):
        st = self.stages.get("bl31")
        m = FINGERPRINT.search(st.text) if st else None
        return m.group(1) if m else None

    def to_dict(self):
        return {
            "boot": self.index,
            "ref_kind": self.ref_kind,
            "ref_line": self.ref_line,
            "live": None if self.live is None else round(self.live, 3),
            "loader": self.loader,
            "loader_build": self.loader_build,
            "stack": self.stack,
            "fingerprint": self.fingerprint,
            "complete": self.complete,
            "fastboot": self.fastboot,
            "reset": None if self.reset is None else round(self.reset, 3),
            "last_stage": self.last_stage,
            "stages": {
                k: {"t": round(s.t, 3), "line": s.line,
                    "replayed": s.replayed}
                for k, s in sorted(self.stages.items(),
                                   key=lambda kv: kv[1].line)
            },
            "lava": self.lava,
        }


def _timestamp(dt):
    return datetime.fromisoformat(dt).timestamp()


def load(text):
    """Parse a LAVA log (YAML list of one flow mapping per line)."""
    lines = []
    for n, raw in enumerate(text.splitlines()):
        if not raw.startswith("- {"):
            continue
        try:
            e = json.loads(raw[2:])
        except ValueError:
            # YAML-only escapes such as \0 and \b in console lines.
            try:
                e = yaml.load(raw[2:], Loader=SAFE)
            except yaml.YAMLError:
                continue
        if not isinstance(e, dict) or not {"dt", "lvl", "msg"} <= e.keys():
            continue
        lines.append(Line(n, _timestamp(e["dt"]), e["lvl"], e["msg"]))
    return lines


def clean(msg):
    return JUNK.sub("", msg).strip()


def references(lines):
    """Yield (kind, start, live) for every boot trigger in the log.

    start indexes the reference line; live indexes the line from which the
    dispatcher reads the console again.
    """
    actions = []
    last_call = {}
    for i, ln in enumerate(lines):
        if not isinstance(ln.msg, str):
            continue
        if ln.lvl == "target":
            if REBOOT.search(ln.msg):
                yield "reboot", i, i
            elif UBOOT_RESET.match(clean(ln.msg)):
                yield "reset", i, i
            continue
        m = ACTION.match(ln.msg)
        if m:
            what, level, name = m.groups()
            if what == "start":
                actions.append((level, name))
            elif actions and actions[-1][0] == level:
                actions.pop()
                if name in POWER_ACTIONS and level in last_call:
                    yield "power-on", last_call.pop(level), i
            continue
        m = CALLING.match(ln.msg)
        if m and actions and actions[-1][1] in POWER_ACTIONS:
            if not m.group(1).startswith("'sleep'"):
                last_call[actions[-1][0]] = i


def _find(texts, patterns, start=0):
    """Index of the first of texts from start matching any of patterns, or
    len(texts)."""
    return next((i for i in range(start, len(texts))
                 if any(re.search(p, texts[i]) for p in patterns)),
                len(texts))


def _measure(lines, index, kind, start, live, end):
    ref_t = lines[start].t
    boot = Boot(index, kind, lines[start].n, ref_t, lines[live].t - ref_t)
    console = [clean(ln.msg) for ln in lines[start + 1:end]
               if ln.lvl == "target" and isinstance(ln.msg, str)]
    starts = {name: ld["first"] for name, (_, ld) in LOADERS.items()}
    # (pattern, stages): the pattern starts the boot over once a stage other
    # than these was seen. XBL repeats its own header before UEFI.
    restarts = [(p, {"loader", "loader_end"}) for p in starts.values()]
    # A boot without a loader starts at SPL or BL2; a loader line only after
    # the next stage is the board starting over, not the start of the boot.
    u = _find(console, [p for k, p in STAGES.items() if k not in ANCHORS],
              _find(console, [STAGES[k] for k in ANCHORS]))
    anchored = not any(re.search(p, text) for text in console[:u]
                       for p, _ in restarts)
    if anchored:
        starts = {k: STAGES[k] for k in ANCHORS}
        restarts = [(p, set(ANCHORS)) for p, _ in restarts]
        restarts.append((STAGES["bl2"], set(ANCHORS)))
        # TI K3 prints a second SPL banner (A53) after BL31 and OP-TEE.
        restarts.append((STAGES["spl"], {*ANCHORS, "bl31", "optee"}))
    first = None
    stages = STAGES
    arrivals = []
    login_start = {}
    for i in range(start + 1, end):
        ln = lines[i]
        r = ln.msg
        if (ln.lvl == "results" and isinstance(r, dict)
                and r.get("definition") == "lava" and "duration" in r
                and r.get("case") in LAVA_CASES
                and login_start.get(r.get("level")) is not None):
            t0 = login_start[r["level"]]
            boot.lava[r["case"]] = {
                "start": round(t0, 3),
                "end": round(t0 + float(r["duration"]), 3),
                "line": ln.n, "result": r.get("result")}
            continue
        if not isinstance(ln.msg, str):
            continue
        if ln.lvl != "target":
            m = ACTION.match(ln.msg)
            # The kernel is then sent over USB from the dispatcher: its stages
            # include the download, so they compare only with fastboot boots.
            if m and m.group(3) == FASTBOOT and "linux" not in boot.stages:
                boot.fastboot = True
            # kernel-messages runs inside login-action, at the same level. A
            # retry starts after the failed attempt, not at the kernel start
            # message: a retried login-action gives no timing.
            if m and m.group(1) == "start" and m.group(3) == LOGIN_ACTION:
                if m.group(2) in login_start:
                    login_start[m.group(2)] = None
                    boot.lava.clear()
                else:
                    login_start[m.group(2)] = ln.t - ref_t
            continue
        text = clean(ln.msg)
        attach = ATTACH.match(text)
        arrivals.append((ln.t - ref_t, len(ln.msg) + 1, attach))
        if attach:
            boot.live = max(boot.live, ln.t - ref_t)
            continue
        new = first is None
        if new:
            for name, pat in starts.items():
                if re.search(pat, text):
                    first = i
                    key = name if anchored else "loader"
                    boot.stages[key] = Stage(ln.t - ref_t, ln.n, text)
                    if not anchored:
                        boot.loader = name
                        platform, loader = LOADERS[name]
                        stages = {k: st["pattern"] for k, st in
                                  (platform.get("stages") or {}).items()}
                        stages.update(STAGES)
                    break
        # The build id belongs to the loader; later stages print their own.
        build = boot.loader and loader.get("build")
        if (build and boot.loader_build is None
                and not boot.stages.keys() & {"loader_end", "bl2", "spl"}):
            m = re.search(build, text)
            if m:
                boot.loader_build = m.group(1)
                boot.loader_build_line = ln.n
        if new:
            continue
        # The boot starting over after a later stage is a reset (watchdog,
        # firmware reset) without a power command: whatever follows belongs
        # to another boot.
        if any(boot.stages.keys() - seen and re.search(pat, text)
               for pat, seen in restarts):
            boot.reset, boot.reset_line = ln.t - ref_t, ln.n
            end = i
            break
        for key, pat in stages.items():
            if key not in boot.stages and re.search(pat, text):
                boot.stages[key] = Stage(ln.t - ref_t, ln.n, text)
    if first is None:
        return None
    # LAVA's prompt match is the moment the login prompt arrived; the
    # console line itself only completes once the username is echoed.
    for i in range(first, end):
        ln = lines[i]
        if (ln.lvl == "debug" and isinstance(ln.msg, str)
                and LOGIN_MATCH.search(ln.msg)):
            boot.stages["login"] = Stage(ln.t - ref_t, ln.n, clean(ln.msg))
            break
    spans = [(0.0, boot.live + REPLAY_WINDOW)]
    for s, (t0, _, attach) in enumerate(arrivals):
        if s and not attach:
            continue
        e, size = s, arrivals[s][1]
        while (e + 1 < len(arrivals)
               and arrivals[e + 1][0] - arrivals[e][0] < BURST_GAP):
            e += 1
            size += arrivals[e][1]
        t1 = arrivals[e][0]
        if size > 2 * UART_RATE * (t1 - t0 + CHUNK):
            spans.append((t0, t1))
    for st in boot.stages.values():
        st.replayed = any(a <= st.t <= z for a, z in spans)
    # login-action starts when LAVA reads "Linux version", so in a backlog
    # burst it starts when the burst was read (logged just after its end).
    for r in boot.lava.values():
        r["replayed"] = any(a <= r["start"] <= z + CHUNK for a, z in spans)
    return boot


def boots(lines):
    """Split a job log into boots and measure each one."""
    refs = sorted(references(lines), key=lambda r: r[1])
    out = []
    for n, (kind, start, live) in enumerate(refs):
        end = refs[n + 1][1] if n + 1 < len(refs) else len(lines)
        b = _measure(lines, len(out), kind, start, live, end)
        if b is not None:
            out.append(b)
    return out


def lava_mark(boot, key):
    """A LAVA_MARKS time of a boot record, if LAVA reported it as passed
    and, for a start, it was not set by console backlog."""
    case, what = LAVA_MARKS[key]
    r = boot.get("lava", {}).get(case)
    if (not r or r["result"] != "pass"
            or what == "start" and r.get("replayed")):
        return None
    return r[what]


def parse(text):
    return [b.to_dict() for b in boots(load(text))]
