"""The stock reference series: lab health checks of each board's device
type, measured like the CI jobs (fwci.boottime.reference,
ubci.run stockref), read through the public REST API (fwci.lava_rest)."""
import io
import json
import pathlib
import urllib.parse

import pytest

from fwci import boottime, schema
from fwci.lava_rest import LavaRest
from ubci import run as urun

DATA = pathlib.Path(__file__).resolve().parent / "data" / "boottime"
URL = "https://lava.example.org"


class Server:
    """Answers LAVA REST URLs from job records and fixture logs."""

    def __init__(self, jobs, logs):
        self.jobs, self.logs, self.queries = jobs, logs, []

    def __call__(self, url):
        u = urllib.parse.urlparse(url)
        if u.path.endswith("/logs/"):
            job = int(u.path.rstrip("/").split("/")[-2])
            if job not in self.logs:
                raise OSError("HTTP 404")
            return io.BytesIO(self.logs[job].encode())
        q = dict(urllib.parse.parse_qsl(u.query))
        self.queries.append(q)
        hits = [j for j in self.jobs if j["requested_device_type"] == q["requested_device_type"]]
        if "end_time__lt" in q:
            hits = [j for j in hits if j["end_time"] < q["end_time__lt"]]
        return io.BytesIO(json.dumps({"results": hits[:int(q["limit"])]}).encode())


def hc(job, dt, device, end, health="Complete"):
    return {"id": job, "requested_device_type": dt, "actual_device": device, "health": health,
            "state": "Finished", "health_check": True, "end_time": end, "description": "health check",
            "definition": "secret: do not keep"}


QCS615 = (DATA / "qcs615-ride-health-check.yaml").read_text()
RB3 = (DATA / "rb3gen2-health-check-fastboot.yaml").read_text()


def server():
    jobs = [hc(10, "qcs615-ride", "qcs615-03", "2026-11-01T15:00:00Z"),
            hc(9, "qcs615-ride", "qcs615-02", "2026-11-01T12:00:00Z", health="Incomplete"),
            hc(8, "qcs615-ride", "qcs615-production-01", "2026-11-01T10:00:00Z"),
            hc(7, "qcs615-ride", "qcs615-01", "2026-11-01T09:00:00Z"),
            hc(6, "qcs615-ride", "qcs615-01", "2026-10-30T09:00:00Z"),
            hc(5, "qcs6490-rb3gen2", "rb3-01", "2026-11-01T15:00:00Z")]
    return Server(jobs, {10: QCS615, 9: QCS615, 8: QCS615, 7: "- {broken", 6: QCS615, 5: RB3})


def test_last_power_on_of_a_health_check():
    b = boottime.reference_boot(QCS615, URL + "/scheduler/job/1")
    # Two power-ons in this health check: the second one counts.
    assert b["kind"] == "cold" and b["complete"]
    assert boottime.time_of(b, "linux") == pytest.approx(4.656)
    assert "uefi" in b["stages"] and "uboot" not in b["stages"]


def test_reference_skips_incomplete_excluded_and_bootless_jobs():
    lava = LavaRest(URL, opener=server())
    ref = boottime.reference(lava, "qcs615-ride", None, 2, lambda d: "-production-" in d)
    assert [r["job"] for r in ref] == [10, 6]
    assert ref[0]["device"] == "qcs615-03" and ref[0]["job_url"] == URL + "/scheduler/job/10"
    assert ref[0]["url"].startswith(URL + "/scheduler/job/10#L")
    assert "definition" not in json.dumps(ref)


def test_reference_ends_before_the_run():
    srv = server()
    ref = boottime.reference(LavaRest(URL, opener=srv), "qcs615-ride", "2026-11-01T00:00:00Z", 5)
    assert [r["job"] for r in ref] == [6]
    assert srv.queries[0]["health_check"] == "true" and srv.queries[0]["end_time__lt"] == "2026-11-01T00:00:00Z"


def test_fastboot_health_check_has_no_timed_firmware():
    (b,) = boottime.reference(LavaRest(URL, opener=server()), "qcs6490-rb3gen2", None, 5)
    assert b["fastboot"]
    for st in ("loader", "loader_end", "hyp", "uefi", "ebs"):
        assert b["stages"][st]["replayed"], st
    med = boottime.reference_median([b])
    assert "uefi" not in med and med["linux"] == pytest.approx(16.613)


def test_boots_from_storage_come_before_fastboot_boots():
    srv = server()
    srv.jobs = [hc(5, "qcs6490-rb3gen2", "rb3-01", "2026-11-01T15:00:00Z"),
                hc(4, "qcs6490-rb3gen2", "rb3-02", "2026-11-01T14:00:00Z")]
    srv.logs = {5: RB3, 4: QCS615}
    ref = boottime.reference(LavaRest(URL, opener=srv), "qcs6490-rb3gen2", None, 5)
    assert [r["job"] for r in ref] == [4] and not ref[0]["fastboot"]


def test_median_only_where_every_boot_timed_the_stage():
    def boot(linux, uefi_replayed=False):
        return {"stages": {"uefi": {"t": 2.0, "line": 1, "replayed": uefi_replayed},
                           "linux": {"t": linux, "line": 2, "replayed": False}}}
    med = boottime.reference_median([boot(4.0), boot(5.0), boot(4.5, uefi_replayed=True)])
    assert med == {"linux": 4.5}
    assert boottime.reference_median([boot(4.0), boot(5.0)])["linux"] == pytest.approx(4.5)
    assert boottime.reference_median([]) == {}


def run_doc(tmp_path):
    p = str(tmp_path / "run.json")
    urun.main(["new", p, "--id", "ubci-1", "--commit", "ed869863c7e2aca50d57a05d843830dd843138c4",
               "--fingerprint", "ubci-1", "--targets", "qcs615-ride:stock,rb3gen2:stock,rb3gen2:open"])
    return p


def test_stock_reference_in_the_run_document(tmp_path, monkeypatch):
    p = run_doc(tmp_path)
    r = json.load(open(p))
    r["run"]["created"] = "2026-11-02T00:00:00Z"
    srv = server()
    urun.stock_reference(r, LavaRest(URL, opener=srv), 3)
    ref = r["boot_time_reference"]
    assert ref["version"] == 1 and ref["before"] == "2026-11-02T00:00:00Z"
    assert sorted(ref["boards"]) == ["qcs615-ride", "rb3gen2"]
    q = ref["boards"]["qcs615-ride"]
    # project.yaml leaves out the production boards (job 8).
    assert q["device_type"] == "qcs615-ride" and [b["job"] for b in q["boots"]] == [10, 6]
    assert q["median"]["linux"] == pytest.approx(4.656)
    assert schema.errors(r) == []


def test_board_whose_health_checks_cannot_be_read_is_left_out(tmp_path, capsys):
    p = run_doc(tmp_path)
    r = json.load(open(p))
    srv = server()
    srv.logs = {}
    urun.stock_reference(r, LavaRest(URL, opener=srv), 3)
    assert r["boot_time_reference"]["boards"] == {}
    assert "HTTP 404" in capsys.readouterr().err
    assert schema.errors(r) == []


def test_rest_client_keeps_logs_and_drops_definitions(tmp_path):
    srv = server()
    lava = LavaRest(URL + "/", cache=str(tmp_path / "cache"), opener=srv)
    assert all("definition" not in j for j in lava.jobs(requested_device_type="qcs615-ride"))
    assert lava.log(10) == QCS615
    srv.logs = {}
    assert lava.log(10) == QCS615
    assert lava.job_url(3) == URL + "/scheduler/job/3"
