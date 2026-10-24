"""LAVA job building blocks shared by the firmware CIs.

A job is a firmware stack (pinned components plus one component under
test) flashed with qdl, a fingerprint gate on the console, interactive
checks at a bootloader prompt and a Linux shell, and a restore of the
lab's stock image at the end. Each function returns plain dicts; job()
assembles them and to_yaml() renders the definition.
"""
import re

import yaml

# LAVA turns a monitor's test_case_id into a case name this way
# (lava_dispatcher.actions.test.monitor), so expected lists must match it.
_CASE_RE = re.compile(r"[^a-z0-9]+")


def case_name(text):
    return _CASE_RE.sub("_", text.lower()).strip("_")


def job(device_type, name, actions, metadata, priority="low", job_minutes=120,
        visibility="public"):
    return {
        "device_type": device_type,
        "job_name": name[:200],
        "priority": priority,
        "visibility": visibility,
        "metadata": metadata,
        "timeouts": {"job": {"minutes": job_minutes},
                     "action": {"minutes": 10},
                     "connection": {"minutes": 3}},
        "context": {"test_character_delay": 10},
        "actions": actions,
    }


def deploy_qdl(url, token_name, header="Authorization", minutes=30):
    """Download a qcomflash tarball; token_name is a LAVA remote artifact
    token name (LAVA swaps in the secret), never the secret itself."""
    return {"deploy": {"to": "qdl",
                       "qcomflash": {"url": url, "headers": {header: token_name}},
                       "timeout": {"minutes": minutes}}}


def boot_qdl(path, storage, luns, firehose="prog_firehose_ddr.elf", minutes=15):
    return {"boot": {"method": "qdl",
                     "firehose_program": firehose,
                     "rawprogram": " ".join("rawprogram%d.xml" % n for n in luns),
                     "patch": " ".join("patch%d.xml" % n for n in luns),
                     "path": path,
                     "storage": storage,
                     "timeout": {"minutes": minutes}}}


def power_on():
    return {"boot": {"method": "minimal", "timeout": {"minutes": 1}}}


def fingerprint_gate(name, start, end, expect, minutes=5):
    """Monitor from start to end that passes one case per banner prefix
    whose line carries the expected fingerprint.

    expect maps a banner prefix (e.g. "U-Boot 20") to its fingerprint. The
    case names are the prefixes as LAVA normalizes them; a banner that is
    missing or carries another fingerprint leaves its case failed."""
    # A fingerprint must not be followed by more of a name, so ubci-1-1
    # does not pass on a console that shows ubci-1-10.
    nb = "(?![A-Za-z0-9_])"
    alts = "|".join("%s(?=[^\\r\\n]*?%s%s)" % (re.escape(p), re.escape(fp), nb)
                    for p, fp in expect.items())
    fps = sorted(set(expect.values()))
    return {"test": {
        "monitors": [{
            "name": name,
            "start": start,
            "end": end,
            "pattern": "(?P<test_case_id>%s)[^\\r\\n]*?(?P<result>%s)%s"
                       % (alts, "|".join(re.escape(f) for f in fps), nb),
            "fixupdict": {f: "pass" for f in fps},
            "expected": [case_name(p) for p in expect],
        }],
        "timeout": {"minutes": minutes}}}


def interactive(name, prompts, steps, minutes=10):
    """steps: dicts with name, command (None waits without sending),
    optional success / failure messages (regex) and wait_for_prompt
    (False: a matched success or failure ends the step, without waiting
    for a prompt)."""
    script = []
    for s in steps:
        item = {"name": s["name"], "command": s.get("command")}
        if s.get("success"):
            item["successes"] = [{"message": s["success"]}]
        if s.get("failure"):
            item["failures"] = [{"message": s["failure"]}]
        if s.get("wait_for_prompt") is False:
            item["wait_for_prompt"] = False
        script.append(item)
    return {"test": {
        "interactive": [{"name": name, "prompts": prompts, "echo": "discard",
                         "script": script}],
        "timeout": {"minutes": minutes}}}


END_MARK = "@@ end@@"


def shell_checks(name, checks, minutes=10):
    """Interactive shell cases: each check is (case, shell command) and
    passes when the command exits 0. Each step echoes '@@ <case> pass|fail
    @@' and then an end marker, both built at run time so the echo of the
    command line never matches, and the steps wait for those markers only:
    a shell prompt or kernel text such as "PME# supported" can come at any
    time and must not count as a prompt."""
    steps = [{"name": case,
              "command": 'if ( %s ); then v=pass; else v=fail; fi; echo "@@ %s $v @@"; echo "%s""@@"'
                         % (cmd, case, END_MARK[:-2]),
              "success": "@@ %s pass @@" % case,
              "failure": "@@ %s fail @@" % case}
             for case, cmd in checks]
    return interactive(name, [END_MARK], steps, minutes)


def monitor(name, start, end, pattern, fixupdict=None, expected=None, minutes=5):
    m = {"name": name, "start": start, "end": end, "pattern": pattern}
    if fixupdict:
        m["fixupdict"] = fixupdict
    if expected:
        m["expected"] = expected
    return {"test": {"monitors": [m], "timeout": {"minutes": minutes}}}


def login(login_prompt, prompt, username="root", minutes=6, commands=("dmesg -n 1",)):
    """Log in on the running system. The kernel start was already matched
    by an earlier monitor, so LAVA must not wait for it again; the default
    login command keeps kernel messages off the console so they do not
    interleave with the shell checks."""
    return {"boot": {"method": "minimal", "reset": False,
                     "parameters": {"kernel-start-message": ""},
                     "auto_login": {"login_prompt": login_prompt, "username": username,
                                    "login_commands": list(commands)},
                     "prompts": [prompt],
                     "timeout": {"minutes": minutes}}}


def to_yaml(definition):
    return yaml.safe_dump(definition, sort_keys=False, width=1000)
