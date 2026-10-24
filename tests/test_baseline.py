from fwci import baseline

from samples import case, run, target


def test_case_diff():
    base = run("n0", targets=[target(cases=[case("usb", "pass"), case("storage", "fail"),
                                            case("net", "fail")])])
    now = run("n1", targets=[target(cases=[case("usb", "fail"), case("storage", "fail"),
                                           case("net", "pass"), case("new", "fail")])])
    baseline.compare(now, base)
    d = now["targets"][0]["diff"]
    assert d == {"new_fail": ["smoke/new", "smoke/usb"], "new_pass": ["smoke/net"],
                 "still_fail": ["smoke/storage"]}
    assert now["run"]["baseline"] == "n0"


def test_series_that_stops_linux_booting_is_a_regression():
    base = run("n0", targets=[target(boot="pass", stage="login")])
    series = run("s1", kind="series", targets=[target(boot="fail", stage="early-panic")])
    baseline.compare(series, base)
    assert series["targets"][0]["linux_boot"]["versus_baseline"] == "regression"


def test_baseline_that_does_not_boot_either_is_an_upstream_gap():
    base = run("n0", targets=[target(boot="fail", stage="no-login")])
    series = run("s1", kind="series", targets=[target(boot="fail", stage="no-login")])
    baseline.compare(series, base)
    assert series["targets"][0]["linux_boot"]["versus_baseline"] == "upstream-gap"


def test_no_diff_when_a_fingerprint_gate_failed_or_no_baseline():
    base = run("n0")
    now = run("n1", targets=[target(gate="fail")])
    baseline.compare(now, base)
    assert "diff" not in now["targets"][0]
    # no regression banner for a build that the console never showed
    assert now["targets"][0]["linux_boot"]["versus_baseline"] == "unknown"
    other = run("n2", targets=[target(board="ventuno-q")])
    baseline.compare(other, base)
    assert other["targets"][0]["linux_boot"]["versus_baseline"] == "unknown"
    assert "diff" not in other["targets"][0]
    alone = run("n3")
    baseline.compare(alone, None)
    assert alone["run"]["baseline"] is None
