"""Boot time in the dashboard data (fwci.site): the matrix cell line, the
per-branch history per board, stack and boot kind, and the stock series."""
import pytest

from fwci import schema, site

import boottime_samples


@pytest.fixture
def idx():
    runs = boottime_samples.runs()
    for r in runs:
        schema.check(r)
    return site.build(sorted(runs, key=lambda r: r["run"]["created"], reverse=True))


def test_cell_leads_with_the_cold_boot(idx):
    c = next(c for c in idx["matrix"] if c["board"] == "rb3gen2")
    assert c["boot_time"]["kind"] == "cold" and c["boot_time"]["linux"] == pytest.approx(5.248)
    assert c["boot_time"]["verdict"] == "regression" and c["boot_time"]["delta"] == 0.5


def test_cell_falls_back_to_the_warm_reset_and_says_where_it_stopped(idx):
    c = next(c for c in idx["matrix"] if c["board"] == "qcs615-ride")
    assert c["boot_time"]["kind"] == "warm-reset"
    assert c["boot_time"]["linux"] is None and c["boot_time"]["last_stage"] == "uboot"


def test_cell_without_boot_times():
    t = dict(boottime_samples.target(), state="skipped", state_detail="x")
    t.pop("boot_time", None)
    assert site.cell(boottime_samples.run(targets=[t]), t)["boot_time"] is None


def test_history_per_board_stack_and_kind(idx):
    h = idx["branches"]["main"]["boottime"]["history"]["rb3gen2"]["open"]
    assert [p["run"] for p in h["warm-reset"]] == ["n1", "n2"]
    assert [p["run"] for p in h["cold"]] == ["n2"]
    cold = h["cold"][0]
    assert cold["on_target"][0] == {"name": "pre-kernel", "result": "pass", "value": 3.982, "units": "s"}
    t, line, replayed = cold["stages"]["linux"]
    assert t == pytest.approx(5.248) and replayed == 0
    assert cold["stages"]["loader"][2] == 0 and h["warm-reset"][0]["job_url"].endswith("/job/1")
    assert "boottime" in idx and idx["boottime"]["headline_stage"] == "linux"


def test_stock_series_once_per_health_check(idx):
    st = idx["stock_boottime"]
    assert [b["job"] for b in st["history"]["qcs615-ride"]] == [50]
    assert st["history"]["rb3gen2"][0]["fastboot"] is True
    assert st["median"]["qcs615-ride"]["run"] == "n2" and st["median"]["qcs615-ride"]["jobs"] == [50]
    assert st["median"]["qcs615-ride"]["median"]["linux"] == pytest.approx(4.656)


def test_runs_without_boot_times_still_build():
    import samples
    idx = site.build([samples.run()])
    assert idx["stock_boottime"] == {"history": {}, "median": {}}
    assert idx["boottime"]["history"] == {} and idx["matrix"][0]["boot_time"] is None


def test_cell_says_when_the_linux_line_was_replayed():
    import copy
    runs = boottime_samples.runs()
    t = copy.deepcopy(runs[1]["targets"][0])
    cold = t["boot_time"]["boots"][t["boot_time"]["headline"]]
    cold["stages"]["linux"]["replayed"] = True
    c = site.boot_cell(runs[1], t)
    assert c["linux"] is None and c["linux_replayed"] is True
    assert site.boot_cell(runs[1], runs[1]["targets"][0])["linux_replayed"] is False
