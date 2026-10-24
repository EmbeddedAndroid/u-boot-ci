"""Offline end-to-end dry run: render the LAVA job of every board and
stack, validate each with LAVA's validate_job when LAVA_TOKEN is set, and
build the dashboard site from sample results.

python3 -m ubci.dryrun <output dir>"""
import json
import os
import shutil
import sys

import yaml

from fwci import lava_jobs, schema, site

from . import config, jobs

LINUX = {"tag": "next-20261023", "release": "7.3.0-next-20261023", "image_sha256": "0" * 64}


def sample_runs():
    sys.path.insert(0, os.path.join(config.ROOT, "tests"))
    import samples
    rb3 = samples.target
    runs = [
        samples.run("ubci-sample-1", created="2026-10-22T01:20:00Z", targets=[
            rb3(), rb3(stack="open"), rb3(board="ventuno-q", boot="fail", stage="no-efi-stub"),
            rb3(board="ventuno-q", stack="open", boot="fail", stage="no-efi-stub")]),
        samples.run("ubci-sample-2", created="2026-10-23T01:20:00Z", targets=[
            rb3(), rb3(stack="open", boot="fail", stage="early-panic"),
            rb3(board="ventuno-q", boot="fail", stage="no-efi-stub"),
            dict(rb3(board="ventuno-q", stack="open"), state="testing",
                 linux_boot={"verdict": "not-run", "stage": "not-reached"}, cases=[])]),
    ]
    master = samples.run("ubci-sample-3", created="2026-10-23T01:25:00Z", targets=[rb3(), rb3(stack="open")])
    master["run"]["base"]["branch"] = "master"
    adhoc = samples.run("ubci-sample-4", kind="adhoc", created="2026-10-23T09:00:00Z", targets=[
        dict(rb3(board="ventuno-q"), diff={"new_fail": [], "new_pass": ["linux-version/linux_version"],
                                           "still_fail": ["smoke/network"]},
             linux_boot={"verdict": "pass", "stage": "login", "versus_baseline": "fixed"})])
    adhoc["run"].update(title="qcs8300 pinctrl/clocks v4 + VENTUNO Q v2", baseline="ubci-sample-2", stack=[
        {"message_id": "20261021-b4-monaco-v4-0-c90f0c01d312@oss.qualcomm.com", "version": 4, "patches": 5,
         "title": "qcom: qcs8300/monaco-evk: pinctrl and RPMH clock", "applied": True,
         "link": "https://lore.kernel.org/r/20261021-b4-monaco-v4-0-c90f0c01d312@oss.qualcomm.com"},
        {"message_id": "20260928-monaco-ventuno-q-v2-0-0e046c8242be@oss.qualcomm.com", "version": 2,
         "patches": 4, "title": "qcom: add support for the Arduino VENTUNO Q", "applied": True,
         "link": "https://lore.kernel.org/r/20260928-monaco-ventuno-q-v2-0-0e046c8242be@oss.qualcomm.com"}])
    return runs + [master, adhoc]


def main(out):
    os.makedirs(os.path.join(out, "jobs"), exist_ok=True)
    validate = None
    if os.environ.get("LAVA_TOKEN"):
        from fwci.lava_mcp import Lava
        lava = Lava()
        validate = lambda text: lava.call("validate_job", definition=text)
    pkg = {"url": "https://lava.example/mcp/artifacts/x/pkg.qcomflash.tar.gz",
           "token": "lava-mcp-artifact-x", "path": "ubci-pkg"}
    failed = 0
    for board in config.boards():
        restore = {"url": "https://lab.example/stock.tar.gz", "token": "STOCK_TOKEN",
                   "path": config.board(board)["restore"]["path"]}
        for stack in config.STACKS:
            text = lava_jobs.to_yaml(jobs.render(board, stack, "ubci-dry-run", pkg, LINUX, restore))
            yaml.safe_load(text)
            path = os.path.join(out, "jobs", "%s-%s.yaml" % (board, stack))
            open(path, "w").write(text)
            verdict = validate(text) if validate else "not validated (no LAVA_TOKEN)"
            ok = not validate or "valid" in json.dumps(verdict).lower() and "invalid" not in json.dumps(verdict).lower()
            failed += not ok
            print("%s: %s" % (os.path.basename(path), verdict))
    s = os.path.join(out, "site")
    shutil.rmtree(s, ignore_errors=True)
    os.makedirs(os.path.join(s, "runs"))
    for r in sample_runs():
        schema.check(r)
        json.dump(r, open(os.path.join(s, "runs", r["run"]["id"] + ".json"), "w"), indent=1)
    for f in os.listdir(os.path.join(config.ROOT, "dashboard")):
        shutil.copy(os.path.join(config.ROOT, "dashboard", f), s)
    idx = site.write(s)
    print("site: %s (%d matrix cells, latest %s)" % (s, len(idx["matrix"]), idx["latest_nightly"]))
    return failed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(1 if main(sys.argv[1]) else 0)
