import json

from fwci import site

from samples import case, run, target


def write(d, r):
    (d / "runs").mkdir(exist_ok=True)
    (d / "runs" / (r["run"]["id"] + ".json")).write_text(json.dumps(r))


def test_index_from_runs(tmp_path):
    write(tmp_path, run("n1", created="2026-10-23T01:00:00Z",
                        targets=[target(cases=[case("usb", "pass")]), target(stack="open", boot="fail",
                                                                             stage="no-login")]))
    write(tmp_path, run("n2", created="2026-10-24T01:00:00Z",
                        targets=[target(cases=[case("usb", "fail"), case("new", "pass")])]))
    write(tmp_path, run("s1", kind="series", created="2026-10-24T05:00:00Z"))
    idx = site.write(str(tmp_path))
    assert json.loads((tmp_path / "index.json").read_text()) == idx
    assert idx["latest_nightly"] == "n2"
    assert [r["id"] for r in idx["runs"]] == ["s1", "n2", "n1"]
    m = idx["matrix"]
    assert len(m) == 1 and m[0]["board"] == "rb3gen2" and m[0]["counts"]["fail"] == 1
    assert m[0]["distance"] == {"tf-a": 2}
    ch = idx["case_history"]["rb3gen2/stock"]
    assert ch["runs"] == ["n1", "n2"]
    assert ch["cases"] == {"smoke/usb": "pf", "smoke/new": "-p"}
    assert [c["run"] for c in idx["history"]["rb3gen2/open"]] == ["n1"]
    assert idx["history"]["rb3gen2/open"][0]["boot_stage"] == "no-login"


def test_invalid_run_document_stops_the_build(tmp_path):
    bad = run("n1")
    bad["targets"][0]["state"] = "nope"
    write(tmp_path, bad)
    try:
        site.write(str(tmp_path))
    except ValueError as e:
        assert "targets/0/state" in str(e)
    else:
        raise AssertionError("invalid run accepted")
    assert not (tmp_path / "index.json").exists()


def test_empty_site(tmp_path):
    (tmp_path / "runs").mkdir()
    idx = site.write(str(tmp_path))
    assert idx["matrix"] == [] and idx["latest_nightly"] is None


def test_pin_candidates_view(tmp_path):
    write(tmp_path, run("n1", created="2026-10-23T01:00:00Z"))
    old = run("c1", kind="pin-candidate", created="2026-10-24T03:00:00Z",
              targets=[target(), target(stack="stock-candidate", boot="fail", stage="no-login")])
    for t, rel in zip(old["targets"], ("QCM6490 boot binaries 00142", "QCM6490 boot binaries 00150")):
        t["components"].append({"name": "boot firmware", "role": "stock", "release": rel})
    write(tmp_path, old)
    idx = site.write(str(tmp_path))
    c = idx["pin_candidates"]["rb3gen2"]
    assert c["run"] == "c1" and [x["firmware"] for x in c["cells"]] == [
        "QCM6490 boot binaries 00142", "QCM6490 boot binaries 00150"]
    assert idx["latest_nightly"] == "n1" and [m["run"] for m in idx["matrix"]] == ["n1"]


def test_case_reported_twice_counts_once(tmp_path):
    write(tmp_path, run("n1", created="2026-10-23T01:00:00Z", targets=[target(cases=[case("usb", "pass"), case("usb", "pass")])]))
    write(tmp_path, run("n2", created="2026-10-24T01:00:00Z", targets=[target(cases=[case("usb", "fail")])]))
    assert site.write(str(tmp_path))["case_history"]["rb3gen2/stock"]["cases"]["smoke/usb"] == "pf"


def test_branches_and_adhoc_runs(tmp_path):
    nxt = run("n1", created="2026-10-24T01:00:00Z")
    mst = run("m1", created="2026-10-24T01:05:00Z", targets=[target(boot="fail", stage="no-login")])
    mst["run"]["base"]["branch"] = "master"
    ad = run("a1", kind="adhoc", created="2026-10-24T05:00:00Z",
             targets=[dict(target(board="ventuno-q"), diff={"new_fail": [], "new_pass": ["smoke/usb"],
                                                            "still_fail": []})])
    ad["run"]["stack"] = [{"message_id": "x@y", "title": "t", "version": 4, "patches": 5, "applied": True}]
    ad["run"]["baseline"] = "n1"
    for r in (nxt, mst, ad):
        write(tmp_path, r)
    idx = site.write(str(tmp_path))
    assert sorted(idx["branches"]) == ["main", "master"] and idx["default_branch"] == "main"
    assert idx["latest_nightly"] == "n1"
    assert idx["branches"]["master"]["matrix"][0]["boot_stage"] == "no-login"
    a = idx["adhoc"][0]
    assert a["run"] == "a1" and a["baseline"] == "n1" and a["stack"][0]["version"] == 4
    assert a["cells"][0]["diff"]["new_pass"] == ["smoke/usb"]


def test_a_closed_run_shows_its_state(tmp_path):
    t = target(state="cancelled")
    t["state_detail"] = "workflow cancelled before this target finished"
    r = run("a1", kind="adhoc", targets=[t])
    r["state"] = "cancelled"
    write(tmp_path, r)
    idx = site.write(str(tmp_path))
    assert idx["runs"][0]["state"] == "cancelled"
    assert idx["adhoc"][0]["state"] == "cancelled" and idx["adhoc"][0]["cells"][0]["state"] == "cancelled"


def test_cell_flags_a_board_fragment_the_base_does_not_have(tmp_path):
    t = target(stack="open")
    t["components"][0]["configs"] = [{"name": "qcom_defconfig", "optional": False, "used": True},
                                      {"name": "arduino-ventuno-q.config", "optional": True, "used": False}]
    t["boot_chain"] = [{"stage": "XBL", "origin": "downstream"}, {"stage": "U-Boot", "origin": "upstream"}]
    other = target()
    other["components"][0]["configs"] = [{"name": "x.config", "optional": True, "used": None}]
    write(tmp_path, run("n1", targets=[t, other]))
    idx = site.write(str(tmp_path))
    assert idx["matrix"][0]["fragments_missing"] == ["arduino-ventuno-q.config"]
    assert idx["matrix"][0]["boot_chain"][0]["origin"] == "downstream"
    # Not built yet is not "missing".
    assert idx["matrix"][1]["fragments_missing"] == []
    assert idx["runs"][0]["base"]["url"] == \
        "https://git.u-boot-project.org/u-boot/u-boot/-/commit/f97bb5c1ad78e95856917b92c7270c82d4b11e21"
