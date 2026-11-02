"""Boot time against the baseline (fwci.boottime.compare via
fwci.baseline.compare): the threshold comes from the series' own
history."""
import pytest

from fwci import baseline, boottime


def boot(kind, linux=4.8, uboot=2.5, replayed=(), last=None):
    stages = {"loader": {"t": 0.3, "line": 1, "replayed": "loader" in replayed},
              "uboot": {"t": uboot, "line": 2, "replayed": "uboot" in replayed}}
    if linux is not None:
        stages["linux"] = {"t": linux, "line": 3, "replayed": "linux" in replayed}
    return {"kind": kind, "ref_line": 0, "url": "u#L0", "complete": linux is not None,
            "last_stage": last or ("linux" if linux is not None else "uboot"), "reset": None,
            "fastboot": False, "stages": stages}


def target(boots, gate="pass", board="rb3gen2", stack="open"):
    head = max((i for i, b in enumerate(boots) if b["kind"] == "cold"), default=None)
    return {"board": board, "stack": stack, "state": "done", "fingerprint_gate": gate,
            "linux_boot": {"verdict": "pass", "stage": "login"},
            "boot_time": {"version": 1, "tool": "t", "boots": boots, "headline": head}}


def run(rid, created, targets, kind="nightly", branch="main"):
    return {"run": {"id": rid, "created": created, "kind": kind, "base": {"branch": branch}}, "targets": targets}


def history(values, kind="cold", gate="pass"):
    return [run("h%d" % i, "2026-10-%02dT00:00:00Z" % (i + 1), [target([boot("first", None), boot(kind, v)], gate)])
            for i, v in enumerate(values)]


HIST = [4.80, 4.81, 4.79, 4.82, 4.80, 4.78, 4.81]  # MAD 0.01


def compare(now, then, hist):
    r = run("now", "2026-11-01T00:00:00Z", [now])
    baseline.compare(r, run("base", "2026-10-31T00:00:00Z", [then]), hist)
    return r["targets"][0]["boot_time"]["versus_baseline"]["kinds"]


def cold(linux, **kw):
    return target([boot("first", None), boot("cold", linux, **kw)])


@pytest.mark.parametrize("linux, verdict", [(5.2, "regression"), (4.83, "same"), (4.4, "improvement")])
def test_verdict_from_the_series_noise(linux, verdict):
    c = compare(cold(linux), cold(4.80), history(HIST))["cold"]
    assert c["verdict"] == verdict and c["stage"] == "linux"
    assert c["history"] == len(HIST)
    # 3 * sqrt(2) * 1.4826 * MAD(0.01)
    assert c["threshold"] == pytest.approx(0.063, abs=0.001)
    assert c["delta"] == pytest.approx(linux - 4.80, abs=0.001)


def test_too_little_history_gives_no_flag():
    c = compare(cold(9.0), cold(4.8), history(HIST[:4]))["cold"]
    assert c["verdict"] == "no-history" and c["threshold"] is None
    assert c["delta"] == pytest.approx(4.2)


def test_threshold_never_under_the_parser_resolution():
    flat = [4.8] * 6
    assert compare(cold(4.815), cold(4.8), history(flat))["cold"]["verdict"] == "same"
    c = compare(cold(4.83), cold(4.8), history(flat))["cold"]
    assert c["verdict"] == "regression" and c["threshold"] == pytest.approx(boottime.FLOOR)


def test_stopped_before_linux_when_the_baseline_did_not():
    c = compare(cold(None), cold(4.8), history(HIST))["cold"]
    assert c["verdict"] == "stopped-earlier" and c["then"] == 4.8


def test_neither_reaches_linux_compares_the_last_common_stage():
    hist = [run("h%d" % i, "2026-10-%02dT00:00:00Z" % (i + 1), [cold(None, uboot=2.5 + i * 0.001)])
            for i in range(6)]
    c = compare(cold(None, uboot=3.5), cold(None, uboot=2.5), hist)["cold"]
    assert c["stage"] == "uboot" and c["verdict"] == "regression"


def test_replayed_stage_is_not_compared():
    c = compare(cold(5.5, replayed=("linux",)), cold(4.8), history(HIST))["cold"]
    assert c["stage"] == "uboot" and "linux" not in c["stages"]


def test_failed_gate_compares_nothing():
    c = compare(target([boot("cold", 9.0)], gate="fail"), cold(4.8), history(HIST))["cold"]
    assert c == {"verdict": "unknown"}


def test_kind_missing_in_the_baseline():
    then = target([boot("first", None), boot("warm-reset", 4.9)])
    kinds = compare(cold(4.8), then, history(HIST))
    assert kinds["cold"] == {"verdict": "unknown"}
    assert kinds["first"]["verdict"] in ("same", "no-history", "unknown")


def test_kinds_are_separate_series():
    # Warm resets only in the history: a cold boot has no history.
    c = compare(cold(5.5), cold(4.8), history(HIST, kind="warm-reset"))["cold"]
    assert c["verdict"] == "no-history"


def test_history_leaves_out_failed_gates_and_the_run_itself():
    hist = history(HIST, gate="fail") + [run("now", "2026-10-30T00:00:00Z", [cold(4.8)])]
    assert compare(cold(5.5), cold(4.8), hist)["cold"]["verdict"] == "no-history"


def test_history_is_earlier_nightlies_of_the_same_branch():
    other = history(HIST)
    for r in other:
        r["run"]["base"]["branch"] = "master"
    pins = history(HIST)
    for r in pins:
        r["run"]["kind"] = "pin-candidate"
    later = history(HIST)
    for r in later:
        r["run"]["created"] = r["run"]["created"].replace("2026-10-", "2026-12-")
    assert compare(cold(5.5), cold(4.8), other + pins + later)["cold"]["verdict"] == "no-history"
    assert compare(cold(5.5), cold(4.8), other + history(HIST))["cold"]["verdict"] == "regression"


def test_history_is_the_newest_runs():
    old = history([1.0, 9.0, 1.0, 9.0, 1.0, 9.0])
    for i, r in enumerate(old):
        r["run"]["created"] = "2026-09-%02dT00:00:00Z" % (i + 1)
    c = compare(cold(5.2), cold(4.8), old + history(HIST))["cold"]
    assert c["history"] == boottime.HISTORY_MAX
    assert c["verdict"] == "regression"


def test_no_baseline_target():
    r = run("now", "2026-11-01T00:00:00Z", [cold(4.8)])
    baseline.compare(r, None, history(HIST))
    vs = r["targets"][0]["boot_time"]["versus_baseline"]
    assert vs["baseline"] is None and vs["kinds"]["cold"] == {"verdict": "unknown"}


def test_target_without_boot_time_is_left_alone():
    t = {"board": "b", "stack": "s", "state": "skipped", "state_detail": "x"}
    r = run("now", "2026-11-01T00:00:00Z", [t])
    baseline.compare(r, None)
    assert "boot_time" not in r["targets"][0]


def test_collect_reads_the_history_from_the_site(tmp_path):
    import json

    import samples
    from ubci import run as urun
    good = samples.run("n1")
    (tmp_path / "n1.json").write_text(json.dumps(good))
    (tmp_path / "bad.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("x")
    assert [r["run"]["id"] for r in urun.load_history(str(tmp_path))] == ["n1"]
    assert urun.load_history(str(tmp_path / "missing")) == []
    assert urun.load_history(None) == []
