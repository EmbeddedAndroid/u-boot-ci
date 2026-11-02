"""Run documents with boot times, from the cut-down LAVA logs in
data/boottime: for the site tests and the dashboard browser test."""
import copy
import pathlib

from fwci import boottime, collect

from samples import run, target

DATA = pathlib.Path(__file__).resolve().parent / "data" / "boottime"
JOB = "https://lava.example/scheduler/job/%d"
# Set as text by the page, never as HTML: a board name that would run
# script if it were.
HOSTILE = "<img src=x onerror=window.__pwned=1>"


def measured(name, job):
    text = (DATA / (name + ".yaml")).read_text()
    return boottime.measure(text, collect.log_entries(text), JOB % job, ("boot-time", "boot-time"))


def with_cold(bt, job, linux_shift=0.0):
    """A copy of bt, as job `job`, whose warm-reset boot is also recorded as
    the job's cold boot (the fixtures predate the cold boot), shifted in
    time."""
    bt = copy.deepcopy(bt)
    for b in bt["boots"]:
        b["url"] = JOB % job + "#L%d" % b["ref_line"]
    reset = next(b for b in bt["boots"] if b["kind"] == "warm-reset")
    cold = copy.deepcopy(reset)
    cold["kind"] = "cold"
    for st in cold["stages"].values():
        st["t"] = round(st["t"] + linux_shift, 3)
    bt["boots"].append(cold)
    bt["headline"] = len(bt["boots"]) - 1
    bt["on_target"] = {"suite": "boot-time", "case": "boot-time", "boot": bt["headline"], "finished": True,
                       "url": JOB % 3 + "#L10",
                       "cases": [{"name": "pre-kernel", "result": "pass", "value": 3.982, "units": "s"},
                                 {"name": "kernel-to-init", "result": "skip", "note": "no timestamped line"}]}
    return bt


def reference(name, job, end_time):
    text = (DATA / (name + ".yaml")).read_text()
    b = boottime.reference_boot(text, JOB % job)
    return dict(b, job=job, job_url=JOB % job, device="dev-%d" % job, end_time=end_time)


def runs():
    rb3 = measured("rb3gen2-open", 1)
    qcs = measured("qcs615-ride-stock-no-linux", 2)
    hc_qcs = reference("qcs615-ride-health-check", 50, "2026-10-29T12:00:00Z")
    hc_rb3 = reference("rb3gen2-health-check-fastboot", 51, "2026-10-29T13:00:00Z")

    def ref(*boards):
        out = {}
        for board, dt, boots in boards:
            out[board] = {"device_type": dt, "boots": boots, "median": boottime.reference_median(boots)}
        return {"version": 1, "tool": boottime.TOOL, "source": "health checks", "before": None, "boards": out}

    def t(board, stack, bt, job, gate="pass"):
        x = target(board=board, stack=stack, gate=gate)
        x["lava"] = {"job_id": job, "url": JOB % job, "device": "dev-%d" % job, "health": "Complete"}
        x["boot_time"] = bt
        return x

    n1 = run("n1", created="2026-10-30T01:00:00Z", targets=[
        t("rb3gen2", "open", rb3, 1), t("qcs615-ride", "stock", qcs, 2)])
    n1["boot_time_reference"] = ref(("qcs615-ride", "qcs615-ride", [hc_qcs]),
                                    ("rb3gen2", "qcs6490-rb3gen2", [hc_rb3]))
    bt2 = with_cold(rb3, 3, 0.5)
    bt2["versus_baseline"] = {"baseline": "n1", "kinds": {
        "cold": {"verdict": "regression", "stage": "linux", "now": 5.248, "then": 4.748, "delta": 0.5,
                 "threshold": 0.12, "noise": 0.02, "history": 6, "stages": {}},
        "warm-reset": {"verdict": "same", "stage": "linux", "now": 4.748, "then": 4.748, "delta": 0.0,
                       "threshold": 0.12, "noise": 0.02, "history": 6, "stages": {}}}}
    n2 = run("n2", created="2026-11-01T01:00:00Z", targets=[
        t("rb3gen2", "open", bt2, 3), t("qcs615-ride", "stock", qcs, 4),
        t(HOSTILE, "stock", measured("uno-q-stock", 5), 5)])
    n2["run"]["baseline"] = "n1"
    n2["boot_time_reference"] = ref(("qcs615-ride", "qcs615-ride", [hc_qcs]),
                                    ("rb3gen2", "qcs6490-rb3gen2", [hc_rb3]))
    return [n1, n2]
