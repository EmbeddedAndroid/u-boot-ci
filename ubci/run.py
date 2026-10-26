"""Run documents (fwci-run/1) for u-boot-ci, from creation to the site.

python3 -m ubci.run new <run.json> --id ID --kind nightly --commit SHA
        --fingerprint FP [--linux linux.json] [--ci-url URL] [--note TEXT]
python3 -m ubci.run linux <run.json> <linux.json>
python3 -m ubci.run built <run.json> <targets dir>
python3 -m ubci.run host <run.json> <check> <pass|fail|skip|running> [--summary S] [--log URL]
python3 -m ubci.run render <run.json> <board> <stack> <package url> <token name>
        <package path>
python3 -m ubci.run submit <run.json> <packages dir>   (holds LAVA_TOKEN)
python3 -m ubci.run skip <run.json> <reason>
python3 -m ubci.run close <run.json> <cancelled|failure>
python3 -m ubci.run collect <run.json> [--baseline base.json] [--wait [--packages DIR]]
python3 -m ubci.run site <site dir>
"""
import argparse
import datetime
import fnmatch
import json
import os
import re
import sys
import tarfile
import time

import yaml

from fwci import baseline as fbaseline
from fwci import collect as fcollect
from fwci import flakes as fflakes
from fwci import lava_jobs, links, schema, site
from fwci.lava_mcp import Lava, Rejected

from . import config, jobs
from . import package as upackage

# The first boot and the boot that starts Linux must both show this build.
GATE_SUITES = [jobs.GATE_SUITE, jobs.GATE_SUITE + "-reset"]
BOOT_START = r"resetting \.\.\."
# LAVA's refusal of a job pinned to a device this user may not submit to.
DENIED = re.compile(r"permission to submit jobs to device '([^']+)'")


# A run in one of these states is over; nothing changes it any more.
CLOSED = ("done", "error", "cancelled")
UNFINISHED = ("queued", "building", "flashing", "testing")


def load(path):
    return json.load(open(path))


def save(path, run):
    run["run"]["updated"] = schema.now()
    states = {t["state"] for t in run["targets"]}
    if run["state"] not in CLOSED:
        run["state"] = ("done" if states <= {"done", "skipped", "error"} and
                        all(h["result"] not in ("queued", "running") for h in run["host_checks"])
                        else "testing" if states & {"flashing", "testing", "done"}
                        else run["state"])
    schema.check(run)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(run, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


LINUX_NEXT = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"


def downstream_component(b, stack):
    """The downstream firmware a stack is built on, exactly: its release,
    every archive with its download link and sha256, and the meta layer
    commits the pin was read at, with links."""
    d = config.downstream(b, stack)
    files = [{"name": os.path.basename(f["url"]), "url": f["url"], "sha256": f["sha256"]}
             for f in d["bootbinaries"] + ([d["cdt"]] if d.get("cdt") else [])]
    up = d.get("upstream") or {}
    layers = []
    for name, commit in sorted((d.get("source") or {}).items()):
        repo = up.get("layers", {}).get(name, {}).get("repo")
        recipe = (up.get("bootbinaries") or {}).get("recipe") if (up.get("bootbinaries") or {}).get(
            "layer") == name else None
        layers.append({"name": name, "repo": repo, "commit": commit, "url": links.commit_url(repo, commit),
                       "recipes": links.file_url(repo, commit, os.path.dirname(recipe)) if recipe else None})
    return {"name": "downstream firmware", "role": "stock", "origin": "downstream",
            "release": d["release"], "files": files, "layers": layers, "upstream": None}


def uboot_configs(b, stack):
    """The configs the board builds with, before a build says which the
    base had (ubci.run built)."""
    return [dict(c, used=None) for c in config.fragments(b["u-boot"][stack]["configs"], [])]


def components(board, stack, commit, fp, branch=None):
    stack = jobs.base_stack(stack)
    p = config.project()["under_test"]
    b = config.board(board)
    u = b["u-boot"].get(stack)
    out = [{"name": "u-boot", "role": "under-test", "origin": "upstream", "repo": p["repo"],
            "branch": branch or p["branch"], "commit": commit, "url": links.commit_url(p["repo"], commit),
            "fingerprint": fp}]
    if u is None:
        # A stack the board does not have: nothing is built.
        return out
    out[0].update(configs=uboot_configs(b, stack), device_tree=u["device_tree"])
    out.append(downstream_component(b, stack))
    if stack == "stock":
        return out
    carry = yaml.safe_load(open(os.path.join(config.CONFIG, "carry.yaml"))).get(board, {})
    for name in ("tf-a", "optee"):
        pin = b["pins"][name]
        c = carry.get(name)
        comp = {"name": name, "role": "pinned", "origin": "upstream", "repo": pin["repo"],
                "branch": pin["branch"], "commit": pin["commit"],
                "url": links.commit_url(pin["repo"], pin["commit"]), "fingerprint": fp,
                "upstream": {"repo": c["repo"], "base": c["base"], "distance": c["distance"],
                             "carried": c["carried"]} if c else None}
        if pin.get("soc_branch"):
            comp["soc_branch"] = dict(pin["soc_branch"], url=links.commit_url(pin["repo"], pin["soc_branch"]["commit"]))
        if pin.get("pending"):
            comp["pending"] = pin["pending"]
        out.append(comp)
    if stack == "spl":
        # The SPL is built from the tree under test with U-Boot proper.
        out.append({"name": "u-boot spl", "role": "under-test", "origin": "upstream",
                    "repo": p["repo"], "branch": branch or p["branch"], "commit": commit,
                    "url": links.commit_url(p["repo"], commit), "fingerprint": fp})
        return out
    bl2 = b["pins"]["bl2"]
    tz = {"name": bl2.get("name", "tf-a bl2"), "role": "pinned", "origin": bl2.get("origin", "upstream"),
          "fingerprint": bl2["fingerprint"], "sha256": bl2["sha256"], "upstream": None}
    if tz["origin"] == "upstream":
        # BL2 is built from the tf-a pin: its carried patches are counted there.
        tf = b["pins"]["tf-a"]
        tz.update(repo=tf["repo"], commit=tf["commit"], url=links.commit_url(tf["repo"], tf["commit"]))
    out.append(tz)
    return out


def linux_component(b, stack, linux):
    """The Linux payload of a target: the linux-next tag and commit, the
    config and the DTB with its overlays, each linked at that commit."""
    stack = jobs.base_stack(stack)
    dts = lambda f: "arch/arm64/boot/dts/" + f.rsplit(".", 1)[0] + (".dtso" if f.endswith(".dtbo") else ".dts")
    dtbs = [b["linux"]["dtb"]] + list(b["linux"]["overlays"].get(stack, []))
    return {"name": "linux", "role": "payload", "origin": "upstream", "repo": LINUX_NEXT,
            "branch": linux["tag"], "commit": linux["commit"], "url": links.commit_url(LINUX_NEXT, linux["commit"]),
            "release": linux["release"], "sha256": linux["image_sha256"],
            "config": {"name": linux.get("config", "arch/arm64/configs/defconfig"),
                       "url": links.file_url(LINUX_NEXT, linux["commit"],
                                             linux.get("config", "arch/arm64/configs/defconfig"))},
            "dtbs": [{"name": f, "url": links.file_url(LINUX_NEXT, linux["commit"], dts(f))} for f in dtbs]}


def set_target_linux(t, linux):
    t["components"] = [c for c in t.get("components", []) if c["name"] != "linux"]
    if linux:
        t["components"].append(linux_component(config.board(t["board"]), t["stack"], linux))


def spl_info(b):
    """What an SPL-stack target shows whatever its result: the series in
    flight that add SPL support for the board, and the known gaps."""
    spl = b.get("spl") or {}
    return {"in_flight": [dict(s, link="https://lore.kernel.org/r/" + s["message_id"])
                          for s in spl.get("in_flight", [])],
            "gaps": list(spl.get("gaps", []))}


def new(args):
    p = config.project()
    linux = linux_of(args.linux) if args.linux else None
    now = schema.now()
    branch = args.branch or p["under_test"]["branch"]
    stack_doc = json.load(open(args.stack)) if args.stack else None
    targets = []
    pairs = ([tuple(x.split(":")) for x in args.targets.split(",")] if args.targets
             else [(b, s) for b in p["boards"] for s in p["stacks"]])
    # "<board>:spl?" (an ad-hoc request that named no stacks): the SPL
    # stack only when a series of the stack touches SPL code.
    touches = any(s.get("touches_spl") for s in stack_doc or [])
    pairs = [(b, s.rstrip("?")) for b, s in pairs if not s.endswith("?") or touches]
    for board, stack in pairs:
        b = config.board(board)
        targets.append({
            "board": board, "stack": stack, "state": "queued",
            "fingerprint": jobs.target_fingerprint(args.fingerprint, board, stack),
            "components": components(board, stack, args.commit,
                                     jobs.target_fingerprint(args.fingerprint, board, stack), branch),
            "fingerprint_gate": "not-run",
            "boot_chain": b["boot_chain"].get(jobs.base_stack(stack), []),
            "linux_boot": {"verdict": "not-run", "stage": "not-reached",
                           "gaps": b["linux"]["gaps"].get(jobs.base_stack(stack), [])},
            "cases": []})
        if jobs.base_stack(stack) == "spl":
            targets[-1]["spl"] = spl_info(b)
        set_target_linux(targets[-1], linux)
    for spec in args.stock_release or []:
        stack, release = spec.split("=", 1)
        for t in targets:
            for c in t["components"]:
                if t["stack"] == stack and c["role"] == "stock":
                    c["release"] = release
    stack = None
    if args.stack:
        keep = ("message_id", "link", "title", "version", "patches", "applied",
                "added_as_prerequisite_of", "failed_patch", "unresolved_prerequisites")
        stack = [{k: s[k] for k in keep if k in s} for s in stack_doc]
        bad = next((s for s in stack if s["applied"] is False), None)
        if bad:
            fp = bad.get("failed_patch") or {}
            for t in targets:
                t["state"] = "skipped"
                t["state_detail"] = "does not apply: %s v%d, patch %s/%d: %s" % (
                    bad["title"], bad["version"], fp.get("number"), bad["patches"], fp.get("subject", ""))
    run = {"schema": "fwci-run/1", "project": p["project"],
           "run": {"id": args.id, "kind": args.kind, "title": args.title or "%s %s" % (
                   branch, args.commit[:12]),
                   "created": now, "updated": now, "ci_url": args.ci_url,
                   "base": {"repo": p["under_test"]["repo"], "branch": branch,
                            "commit": args.commit},
                   "series": None, "baseline": None},
           "state": "building", "linux": linux, "host_checks": [], "targets": targets}
    if stack is not None:
        run["run"]["stack"] = stack
    if args.note:
        run["note"] = args.note
    save(args.run, run)


def linux_of(path):
    lj = load(path)
    out = {k: lj[k] for k in ("tag", "commit", "release", "config", "image_sha256", "modules_sha256")}
    out["url"] = links.commit_url(LINUX_NEXT, out["commit"])
    out["tag_url"] = links.tag_url(LINUX_NEXT, out["tag"])
    return out


def built(args):
    """Record what each target's build used, from the files the ci job
    leaves next to its packages (<board>-<stack>/u-boot.json, esp.json):
    the U-Boot configs the base had (a missing optional board fragment
    shows as not used), the U-Boot image sha256 and the sha256 of the DTB
    the UKI carries."""
    run = load(args.run)
    for t in run["targets"]:
        d = os.path.join(args.targets, "%s-%s" % (t["board"], t["stack"]))
        try:
            ub = json.load(open(os.path.join(d, "u-boot.json")))
        except (OSError, ValueError):
            continue
        b = config.board(t["board"])
        st = jobs.base_stack(t["stack"])
        for c in t.get("components", []):
            if c["name"] == "u-boot":
                c["configs"] = config.fragments(b["u-boot"][st]["configs"], ub["configs"].split())
                c["sha256"] = ub["sha256"]
        try:
            esp = json.load(open(os.path.join(d, "esp.json")))
            for c in t["components"]:
                if c["name"] == "linux":
                    c["dtb_sha256"] = esp["dtb_sha256"]
        except (OSError, ValueError):
            pass
    save(args.run, run)


def set_linux(args):
    """Record the Linux payload once its build is known (CI builds it after
    the run document exists)."""
    run = load(args.run)
    run["linux"] = linux_of(args.linux)
    for t in run["targets"]:
        set_target_linux(t, run["linux"])
    save(args.run, run)


def host(args):
    run = load(args.run)
    run["host_checks"] = [h for h in run["host_checks"] if h["name"] != args.check]
    h = {"name": args.check, "result": args.result}
    if args.summary:
        h["summary"] = args.summary
    if args.log:
        h["log"] = args.log
    run["host_checks"].append(h)
    run["host_checks"].sort(key=lambda h: h["name"])
    save(args.run, run)


def target(run, board, stack):
    for t in run["targets"]:
        if t["board"] == board and t["stack"] == stack:
            return t
    raise SystemExit("no target %s/%s" % (board, stack))


def render_one(run, board, stack, package, device=None):
    t = target(run, board, stack)
    meta = {"run": run["run"]["id"], "u-boot": run["run"]["base"]["commit"]}
    if run["run"].get("ci_url"):
        meta["ci"] = run["run"]["ci_url"]
    return lava_jobs.to_yaml(jobs.render(board, stack, t["fingerprint"], package,
                                         run["linux"], meta, device))


def choose_device(lava, device_type, denied=()):
    """A healthy device of the type that is not excluded
    (project.yaml lava.exclude_devices: production boards of other teams)
    and has not refused this LAVA user (denied), an idle one first. None
    when there is none."""
    exclude = config.project()["lava"].get("exclude_devices", [])
    ok = sorted((d for d in lava.devices(device_type) if d["health"] == "Good" and
                 d["hostname"] not in denied and
                 not any(fnmatch.fnmatch(d["hostname"], p) for p in exclude)),
                key=lambda d: (d["state"] != "Idle", d["hostname"]))
    return ok[0]["hostname"] if ok else None


def lab_in_flight(lava, device_type):
    """Jobs of this project queued or running on the device type, from
    every run (a nightly per branch and ad-hoc runs share the cap)."""
    queued = [j for j in lava.queue() if j.get("requested_device_type") == device_type and
              (j.get("description") or "").startswith("u-boot-ci ")]
    running = [j for j in lava.running({"project": "u-boot-ci"})
               if j.get("requested_device_type") == device_type]
    return len(queued) + len(running)


def render(args):
    run = load(args.run)
    sys.stdout.write(render_one(run, args.board, args.stack,
                                {"url": args.url, "token": args.token, "path": args.path}))


def package_dir(path):
    """The top directory of a qcomflash tarball (what the qdl boot reads)."""
    with tarfile.open(path) as t:
        return t.next().name.split("/")[0]


def in_flight(run, device_type):
    n = 0
    for t in run["targets"]:
        if t.get("lava") and t["state"] in ("queued", "flashing", "testing") and \
                config.board(t["board"])["lava"]["device_type"] == device_type:
            n += 1
    return n


def submit(args):
    """Upload and submit every queued target that has a free slot: at most
    max_in_flight_per_device_type jobs of this run per device type. One
    pass, called again on every collect pass until every target is
    submitted; each job is recorded as soon as it is submitted."""
    submit_pass(args.run, load(args.run), Lava(), args.packages)


def no_package(t, pkg):
    """(state, detail) of a target that cannot be submitted: why from the
    build status the ci job leaves next to the packages (run-all.sh): a
    board the base does not have is skipped, a failed build is an error."""
    try:
        st = json.load(open(pkg[:-len(".qcomflash.tar.gz")] + ".build.json"))
    except (OSError, ValueError):
        return "error", "no package and no build result from the ci job"
    return ("skipped" if st.get("result") == "skip" else "error"), st.get("reason") or "build failed"


def refused(t, device_type, devices):
    t["state"] = "error"
    t["state_detail"] = ("no healthy %s device takes jobs from this LAVA user (refused by %s)"
                         % (device_type, ", ".join(sorted(devices))))


def submit_pass(path, run, lava, packages):
    cap = config.project()["lava"]["max_in_flight_per_device_type"]
    denied = {}
    for t in run["targets"]:
        if t["state"] != "queued" or t.get("lava"):
            continue
        b = config.board(t["board"])
        pkg = os.path.join(packages, "%s-%s.qcomflash.tar.gz" % (t["board"], t["stack"]))
        if not os.path.exists(pkg):
            t["state"], t["state_detail"] = no_package(t, pkg)
            save(path, run)
            continue
        dt = b["lava"]["device_type"]
        if max(in_flight(run, dt), lab_in_flight(lava, dt)) >= cap:
            continue
        device = choose_device(lava, dt, denied.get(dt, ()))
        if device is None:
            if dt in denied:
                refused(t, dt, denied[dt])
                save(path, run)
            continue
        if "tz.mbn" in upackage.sources(pkg).get("deferred", []):
            try:
                upackage.insert_bl2(pkg, t["board"])
            except SystemExit as e:
                t["state"] = "skipped"
                t["state_detail"] = "BL2 pin not available: %s" % e
                save(path, run)
                continue
        url, token = lava.upload(pkg)
        package = {"url": url, "token": token, "path": package_dir(pkg)}
        job_id = None
        while device is not None:
            try:
                job = render_one(run, t["board"], t["stack"], package, device)
            except ValueError as e:
                t["state"] = "error"
                t["state_detail"] = "job does not render: %s" % e
                break
            try:
                job_id = lava.submit(job)
                break
            except Rejected as e:
                # Refused: no job exists. The device list does not say
                # which devices this user may submit to; LAVA does here.
                m = DENIED.search(e.message)
                if m and m.group(1) == device:
                    denied.setdefault(dt, set()).add(device)
                    device = choose_device(lava, dt, denied[dt])
                    continue
                t["state"] = "error"
                t["state_detail"] = "LAVA rejected the job: %s" % e.message
                break
            except Exception as e:
                # LAVA may have taken the job: never submit this target again.
                t["state"] = "error"
                t["state_detail"] = "submit outcome unknown: %s" % str(e)[:1000]
                save(path, run)
                raise
        if job_id is None:
            if device is None:
                refused(t, dt, denied[dt])
            save(path, run)
            continue
        t["lava"] = {"job_id": job_id, "url": "%s/scheduler/job/%d" % (
            config.project()["lava"]["url"], job_id), "device": None, "health": None}
        save(path, run)


def collect_once(run, lava, base):
    queue = None
    for t in run["targets"]:
        if not t.get("lava") or t["state"] in ("done", "skipped", "error"):
            continue
        job = lava.job(t["lava"]["job_id"])
        results = lava.results(job["id"]) if job["state"] == "Finished" else []
        entries = fcollect.log_entries(lava.log(job["id"])) if job["state"] in (
            "Running", "Finished") else []
        gaps = t.get("linux_boot", {}).get("gaps", [])
        t.update(fcollect.target(t, job, results, entries, t["lava"]["url"], GATE_SUITES, BOOT_START))
        if gaps:
            t["linux_boot"]["gaps"] = gaps
        fcollect.apply_known_gaps(t["cases"], config.board(t["board"]).get("known_gaps", {}))
        t["queue_position"] = None
        if job["state"] == "Submitted":
            queue = lava.queue() if queue is None else queue
            t["queue_position"] = fcollect.queue_position(
                queue, job["id"], config.board(t["board"])["lava"]["device_type"])
    fbaseline.compare(run, base)
    fflakes.mark(run, (yaml.safe_load(open(os.path.join(config.CONFIG, "flakes.yaml")))
                       or {}).get("flakes", []), datetime.date.today())


def summary(args):
    """Markdown summary of a run, per board and stack (the PR comment of a
    pin candidate)."""
    run = load(args.run)
    lines = ["Results of %s (%s):" % (run["run"]["id"], run["state"]), "",
             "| board | stack | firmware | fingerprint | boots Linux | pass | fail | LAVA |",
             "|---|---|---|---|---|---|---|---|"]
    for t in run["targets"]:
        fw = next((c.get("release", "") for c in t.get("components", []) if c["role"] == "stock"), "")
        boot = t.get("linux_boot", {})
        n = site.counts(t)
        lava = t.get("lava") or {}
        lines.append("| %s | %s | %s | %s | %s (%s) | %d | %d | %s |" % (
            t["board"], jobs.stack_label(t["stack"]), fw, t.get("fingerprint_gate"), boot.get("verdict"),
            boot.get("stage"), n["pass"], n["fail"],
            "[%s](%s)" % (lava["job_id"], lava["url"]) if lava else t.get("state_detail", "")))
    sys.stdout.write("\n".join(lines) + "\n")


def finished(args):
    """Exit 0 when the run is done."""
    sys.exit(0 if load(args.run)["state"] == "done" else 1)


def skip(args):
    """Mark every target not yet submitted as skipped, with the reason the
    dashboard shows (e.g. no LAVA_TOKEN configured)."""
    run = load(args.run)
    for t in run["targets"]:
        if not t.get("lava") and t["state"] not in ("done", "error"):
            t["state"] = "skipped"
            t["state_detail"] = args.reason
    save(args.run, run)


def close(args):
    """The workflow ended before the run did (a cancel, or a job that
    failed before submit finished): close the run so the dashboard does
    not show it in progress for ever. Targets and host checks that did not
    finish say why; a run that is already over is left as it is."""
    run = load(args.run)
    if run["state"] in CLOSED:
        print("%s: already %s" % (run["run"]["id"], run["state"]))
        return
    cancelled = args.conclusion == "cancelled"
    why = "workflow %s" % ("cancelled" if cancelled else "failed")
    for t in run["targets"]:
        if t["state"] in UNFINISHED:
            job = (t.get("lava") or {}).get("job_id")
            t["state"] = "cancelled" if cancelled else "error"
            t["state_detail"] = why + " before this target finished" + (
                "; LAVA job %d was not collected" % job if job else "")
    for h in run["host_checks"]:
        if h["result"] in ("queued", "running"):
            h["result"] = "skip"
            h["summary"] = "did not finish: " + why
    run["state"] = "cancelled" if cancelled else "error"
    run["note"] = "; ".join(x for x in (run.get("note"), why) if x)
    save(args.run, run)
    print("%s: %s" % (run["run"]["id"], run["state"]))


def collect(args):
    run = load(args.run)
    base = load(args.baseline) if args.baseline else None
    lava = Lava()
    while True:
        if args.packages:
            submit_pass(args.run, run, lava, args.packages)
        collect_once(run, lava, base)
        save(args.run, run)
        if not args.wait or run["state"] == "done":
            break
        time.sleep(120)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ubci.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("new")
    a.add_argument("run")
    a.add_argument("--id", required=True)
    a.add_argument("--kind", default="nightly", choices=["nightly", "series", "pin-candidate", "adhoc"])
    a.add_argument("--branch", help="the base branch (default: project.yaml under_test.branch)")
    a.add_argument("--stack", help="stack.json of ubci.stack: the series applied onto the base")
    a.add_argument("--targets", help="board:stack,... (default: every board and stack)")
    a.add_argument("--stock-release", action="append", metavar="STACK=RELEASE",
                   help="the downstream firmware release a target runs, when it is not the one in config")
    a.add_argument("--commit", required=True)
    a.add_argument("--fingerprint", required=True)
    a.add_argument("--linux")
    a.add_argument("--ci-url")
    a.add_argument("--title")
    a.add_argument("--note")
    a = sub.add_parser("linux")
    a.add_argument("run")
    a.add_argument("linux")
    a = sub.add_parser("built")
    a.add_argument("run")
    a.add_argument("targets", help="the ci job's targets directory")
    a = sub.add_parser("host")
    a.add_argument("run")
    a.add_argument("check")
    a.add_argument("result", choices=["pass", "fail", "skip", "queued", "running"])
    a.add_argument("--summary")
    a.add_argument("--log")
    a = sub.add_parser("render")
    for n in ("run", "board", "stack", "url", "token", "path"):
        a.add_argument(n)
    a = sub.add_parser("submit")
    a.add_argument("run")
    a.add_argument("packages")
    a = sub.add_parser("summary")
    a.add_argument("run")
    a = sub.add_parser("finished")
    a.add_argument("run")
    a = sub.add_parser("skip")
    a.add_argument("run")
    a.add_argument("reason")
    a = sub.add_parser("close")
    a.add_argument("run")
    a.add_argument("conclusion", choices=["cancelled", "failure"])
    a = sub.add_parser("collect")
    a.add_argument("run")
    a.add_argument("--baseline")
    a.add_argument("--wait", action="store_true")
    a.add_argument("--packages", help="also submit queued targets from this directory on every pass")
    a = sub.add_parser("site")
    a.add_argument("site_dir")
    args = ap.parse_args(argv)
    if args.cmd == "site":
        site.write(args.site_dir)
    else:
        {"new": new, "host": host, "render": render, "submit": submit, "skip": skip, "summary": summary, "finished": finished, "linux": set_linux,
         "collect": collect, "close": close, "built": built}[args.cmd](args)


if __name__ == "__main__":
    main()
