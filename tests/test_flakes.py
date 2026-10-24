import datetime

from fwci import flakes

from samples import case, run, target

TODAY = datetime.date(2026, 10, 24)


def entry(**kw):
    e = {"id": "F1", "case": "smoke/usb", "issue": "https://github.com/EmbeddedAndroid/u-boot-ci/issues/1",
         "suspected_cause": "USB hub enumerates late", "confirmed": "2026-10-20",
         "failures": [{"run": "n1", "date": "2026-10-15", "board": "rb3g2-01"},
                      {"run": "n2", "date": "2026-10-18", "board": "rb3g2-02"},
                      {"run": "n3", "date": "2026-10-20", "board": "rb3g2-01"}]}
    e.update(kw)
    return e


def test_entry_meeting_the_bar_is_active():
    assert flakes.problems(entry(), TODAY) == []


def test_entries_below_the_bar():
    assert "missing issue" in flakes.problems(entry(issue=""), TODAY)
    assert "issue must be a link" in flakes.problems(entry(issue="see chat"), TODAY)
    assert any("need 3" in p for p in flakes.problems(entry(failures=entry()["failures"][:2]), TODAY))
    one_board = [dict(f, board="rb3g2-01") for f in entry()["failures"]]
    assert any("need 2" in p for p in flakes.problems(entry(failures=one_board), TODAY))
    assert flakes.problems(entry(failures=one_board, single_board_type=True), TODAY) == []
    spread = [dict(f, date=d) for f, d in zip(entry()["failures"], ("2026-09-01", "2026-09-20", "2026-10-15"))]
    assert any("need 3" in p for p in flakes.problems(entry(failures=spread), TODAY))
    changed = entry()["failures"] + [{"run": "s9", "date": "2026-10-21", "board": "x", "code_change": True}]
    assert any("without code change" in p for p in flakes.problems(entry(failures=changed), TODAY))


def test_expiry_after_thirty_days():
    assert flakes.problems(entry(), datetime.date(2026, 11, 19)) == []
    assert any(p.startswith("expired") for p in flakes.problems(entry(), datetime.date(2026, 11, 20)))


def test_mark_tags_only_failed_matching_cases():
    r = run(targets=[target(cases=[case("usb", "fail"), case("storage", "fail")]),
                     target(stack="open", cases=[case("usb", "pass")])])
    flakes.mark(r, [entry(), entry(id="F2", case="smoke/storage", issue="")], TODAY)
    c = r["targets"][0]["cases"]
    assert c[0]["flake"] == "F1" and "flake" not in c[1]
    assert "flake" not in r["targets"][1]["cases"][0]


def test_mark_respects_board_scope():
    r = run(targets=[target(board="ventuno-q", cases=[case("usb", "fail")])])
    flakes.mark(r, [entry(boards=["rb3gen2"])], TODAY)
    assert "flake" not in r["targets"][0]["cases"][0]
