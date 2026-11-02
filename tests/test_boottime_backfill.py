"""ubci.run backfill: boot times for run documents written before they
were recorded, from public LAVA logs, touching nothing else."""
import copy
import io
import json
import pathlib
import urllib.parse

import pytest

from fwci import schema
from fwci.lava_rest import LavaRest
from ubci import run as urun

from samples import run, target

DATA = pathlib.Path(__file__).resolve().parent / "data" / "boottime"
URL = "https://lava.infra.foundries.io"
LOGS = {11: "rb3gen2-open", 12: "rb3gen2-open", 13: "qcs615-ride-stock-no-linux",
        90: "qcs615-ride-health-check"}


class Server:
    def __init__(self, logs=LOGS):
        self.logs, self.fetched = dict(logs), []

    def __call__(self, url):
        u = urllib.parse.urlparse(url)
        if u.path.endswith("/logs/"):
            job = int(u.path.rstrip("/").split("/")[-2])
            self.fetched.append(job)
            if job not in self.logs:
                raise OSError("HTTP 404")
            return io.BytesIO((DATA / (self.logs[job] + ".yaml")).read_bytes())
        q = dict(urllib.parse.parse_qsl(u.query))
        jobs = [{"id": 90, "requested_device_type": "qcs615-ride", "actual_device": "qcs615-01",
                 "health": "Complete", "state": "Finished", "health_check": True,
                 "end_time": "2026-10-20T00:00:00Z"}] if q["requested_device_type"] == "qcs615-ride" else []
        return io.BytesIO(json.dumps({"results": jobs}).encode())


def tgt(board, stack, job, state="done"):
    t = target(board=board, stack=stack, state=state)
    t["lava"] = dict(t["lava"], job_id=job, url="%s/scheduler/job/%d" % (URL, job))
    return t


def docs():
    old = run("n1", created="2026-10-25T01:00:00Z", targets=[tgt("rb3gen2", "open", 11),
                                                             tgt("qcs615-ride", "stock", 13)])
    new = run("n2", created="2026-10-26T01:00:00Z", targets=[tgt("rb3gen2", "open", 12),
                                                             tgt("qcs615-ride", "stock", 14),
                                                             tgt("rb3gen2", "stock", 15, state="testing")])
    new["run"]["baseline"] = "n1"
    return [new, old]


def strip(r):
    r = copy.deepcopy(r)
    r.pop("boot_time_reference", None)
    for t in r["targets"]:
        t.pop("boot_time", None)
    return r


def test_backfill_adds_boot_times_and_nothing_else(capsys):
    runs = docs()
    before = [strip(r) for r in runs]
    srv = Server()
    changed = urun.backfill_runs(runs, LavaRest(URL, opener=srv))
    assert changed == {"n1", "n2"}
    assert [strip(r) for r in runs] == before
    new, old = runs
    for r in runs:
        schema.check(r)
    bt = new["targets"][0]["boot_time"]
    assert [b["kind"] for b in bt["boots"]] == ["first", "warm-reset", "warm-reboot"]
    # Compared with n1, its baseline: same log, so no difference.
    assert bt["versus_baseline"]["baseline"] == "n1"
    assert bt["versus_baseline"]["kinds"]["warm-reset"]["delta"] == 0.0
    assert old["targets"][0]["boot_time"]["versus_baseline"]["kinds"]["warm-reset"]["verdict"] == "unknown"
    # A log that cannot be read leaves its target as it was; a running job is not read.
    assert "boot_time" not in new["targets"][1] and "job 14 not measured" in capsys.readouterr().err
    assert "boot_time" not in new["targets"][2] and 15 not in srv.fetched
    assert [b["job"] for b in old["boot_time_reference"]["boards"]["qcs615-ride"]["boots"]] == [90]


def test_backfill_again_changes_nothing():
    runs = docs()
    urun.backfill_runs(runs, LavaRest(URL, opener=Server()))
    srv = Server()
    assert urun.backfill_runs(runs, LavaRest(URL, opener=srv)) == set()
    assert srv.fetched == [14]


def test_force_measures_again():
    runs = docs()
    urun.backfill_runs(runs, LavaRest(URL, opener=Server()))
    runs[0]["targets"][0]["boot_time"]["boots"] = []
    urun.backfill_runs(runs, LavaRest(URL, opener=Server()), force=True)
    assert len(runs[0]["targets"][0]["boot_time"]["boots"]) == 3


def test_backfill_command_writes_valid_documents(tmp_path, monkeypatch):
    for r in docs():
        (tmp_path / (r["run"]["id"] + ".json")).write_text(json.dumps(r))
    monkeypatch.setattr(urun, "LavaRest", lambda url, cache=None: LavaRest(url, cache, opener=Server()))
    urun.main(["backfill", str(tmp_path)])
    for p in tmp_path.glob("*.json"):
        assert schema.errors(json.loads(p.read_text())) == []
    assert "boot_time" in json.loads((tmp_path / "n2.json").read_text())["targets"][0]
