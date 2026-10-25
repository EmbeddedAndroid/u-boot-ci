import io
import json
import os
import shutil

import pytest

from fwci import bitbake, pinwatch
from ubci import config, stockpin

DATA = os.path.join(os.path.dirname(__file__), "data", "layers")
ROOTS = {"meta-qcom": os.path.join(DATA, "meta-qcom"),
         "meta-qcom-arduino": os.path.join(DATA, "meta-qcom-arduino")}


@pytest.mark.parametrize("board", ["rb3gen2", "ventuno-q"])
def test_real_recipes_give_the_current_pin(board):
    b = config.board(board)
    up = stockpin.upstream(b["downstream"]["upstream"], ROOTS)
    assert {k: up[k] for k in ("release", "bootbinaries", "cdt")} == stockpin.current(b["downstream"])


def test_cdt_include_resolves_against_another_layer():
    env = bitbake.parse(os.path.join(ROOTS["meta-qcom-arduino"],
                                     "recipes-bsp/firmware-boot/firmware-qcom-cdt-ventuno-q.bb"),
                        list(ROOTS.values()))
    assert env["CDT_ARTIFACTORY"].startswith("artifacts.codelinaro.org")
    assert bitbake.src_uri(env)[0]["downloadfilename"] == "cdt-qcs8275-monza_1.0.zip"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)


def test_missing_and_unparsable_recipes_are_errors(tmp_path):
    with pytest.raises(bitbake.RecipeError, match="no recipe"):
        bitbake.newest(str(tmp_path / "firmware-qcom-boot-x_*.bb"))
    write(str(tmp_path / "a_1.bb"), 'SRC_URI = "https://x/${UNKNOWN}/a.zip;name=a"\nSRC_URI[a.sha256sum] = "%s"\n' % ("0" * 64))
    with pytest.raises(bitbake.RecipeError, match="UNKNOWN"):
        bitbake.src_uri(bitbake.parse(str(tmp_path / "a_1.bb")))
    write(str(tmp_path / "b_1.bb"), 'SRC_URI = "https://x/b.zip;name=b"\n')
    with pytest.raises(bitbake.RecipeError, match="no sha256sum"):
        bitbake.src_uri(bitbake.parse(str(tmp_path / "b_1.bb")))
    write(str(tmp_path / "c_1.bb"), 'require missing.inc\n')
    with pytest.raises(bitbake.RecipeError, match="not found"):
        bitbake.parse(str(tmp_path / "c_1.bb"))


def test_newest_version_wins(tmp_path):
    for v in ("00099", "00142", "00021"):
        write(str(tmp_path / ("fw_%s.bb" % v)), "")
    assert bitbake.newest(str(tmp_path / "fw_*.bb")).endswith("fw_00142.bb")


def newer_layer(tmp_path):
    """meta-qcom with a 00150 QCM6490 release next to 00142."""
    root = tmp_path / "meta-qcom"
    shutil.copytree(ROOTS["meta-qcom"], root)
    d = root / "recipes-bsp" / "firmware-boot"
    text = (d / "firmware-qcom-boot-qcs6490_00142.bb").read_text()
    (d / "firmware-qcom-boot-qcs6490_00150.bb").write_text(
        text.replace("22e45047b3349a1611d27167616dd04f08e8351120ac121f6921b47b9f709216", "1" * 64))
    return {"meta-qcom": str(root)}


def test_bump_writes_the_pr_and_keeps_the_rest_of_the_config(tmp_path, monkeypatch):
    roots = newer_layer(tmp_path)
    monkeypatch.setattr(stockpin, "checkout", lambda name, layer: (roots[name], "c" * 40))
    out = tmp_path / "out"
    out.mkdir()
    r = stockpin.check("rb3gen2", str(out), verify=False)
    assert r == {"board": "rb3gen2", "result": "bump", "from": "QCM6490 boot binaries 00142",
                 "to": "QCM6490 boot binaries 00150"}
    new = (out / "rb3gen2.yaml").read_text()
    old = open(os.path.join(config.CONFIG, "boards", "rb3gen2.yaml")).read()
    assert "1" * 64 in new and "00150/QCM6490_bootbinaries_00150.zip" in new
    assert new.count("\n") == old.count("\n") and "# Qualcomm RB3 Gen 2" in new
    assert (out / "rb3gen2.title").read_text().startswith("config: rb3gen2: bump stock firmware")
    assert "https://github.com/qualcomm-linux/meta-qcom/commit/" + "c" * 40 in (out / "rb3gen2.body").read_text()


def test_sha_mismatch_opens_no_pr(tmp_path, monkeypatch):
    roots = newer_layer(tmp_path)
    monkeypatch.setattr(stockpin, "checkout", lambda name, layer: (roots[name], "c" * 40))
    monkeypatch.setattr(pinwatch.urllib.request, "urlopen", lambda u, timeout=0: io.BytesIO(b"not it"))
    monkeypatch.setattr(config, "boards", lambda: ["rb3gen2"])
    out = tmp_path / "out"
    assert stockpin.main([str(out)]) == 1
    summary = json.load(open(out / "summary.json"))
    assert summary[0]["result"] == "error" and "sha256" in summary[0]["error"]
    assert not (out / "rb3gen2.title").exists() and not (out / "rb3gen2.yaml").exists()


def test_unreadable_recipe_is_an_error_without_pr(tmp_path, monkeypatch):
    root = tmp_path / "meta-qcom"
    (root / "recipes-bsp" / "firmware-boot").mkdir(parents=True)
    monkeypatch.setattr(stockpin, "checkout", lambda name, layer: (str(root), "c" * 40))
    monkeypatch.setattr(config, "boards", lambda: ["rb3gen2"])
    out = tmp_path / "out"
    assert stockpin.main([str(out), "--no-verify"]) == 1
    assert json.load(open(out / "summary.json"))[0]["result"] == "error"
    assert sorted(os.listdir(out)) == ["summary.json"]


def test_verify_accepts_matching_files():
    import hashlib
    data = b"boot binaries"
    pinwatch.verify([("https://x/a.zip", hashlib.sha256(data).hexdigest())], fetch=lambda u: io.BytesIO(data))


class FakeGh:
    def __init__(self, prs):
        self.prs, self.calls = prs, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("pr", "list"):
            return json.dumps(self.prs)
        if args[:2] == ("pr", "create"):
            return "https://github.com/o/r/pull/7\n"
        return ""


def pr(number, title, body, state="OPEN"):
    return {"number": number, "title": title, "body": body, "state": state}


def test_pr_is_created_once_then_updated_never_duplicated():
    gh = FakeGh([])
    assert pinwatch.open_or_update_pr("pin/stock-rb3gen2", "t", "b", run=gh) == \
        ("created", "https://github.com/o/r/pull/7")
    gh = FakeGh([pr(7, "t", "old")])
    assert pinwatch.open_or_update_pr("pin/stock-rb3gen2", "t", "b", run=gh) == ("updated", 7)
    assert not [c for c in gh.calls if c[:2] == ("pr", "create")]
    gh = FakeGh([pr(7, "t", "b")])
    assert pinwatch.open_or_update_pr("pin/stock-rb3gen2", "t", "b", run=gh) == ("unchanged", 7)
    assert [c[:2] for c in gh.calls] == [("pr", "list")]


def test_a_declined_bump_is_not_reopened_but_a_newer_one_is():
    gh = FakeGh([pr(7, "bump to 00150", "b", state="CLOSED")])
    assert pinwatch.open_or_update_pr("pin/stock-rb3gen2", "bump to 00150", "b", run=gh) == ("declined", None)
    assert pinwatch.declined("pin/stock-rb3gen2", "bump to 00150", "b", run=gh)
    assert not [c for c in gh.calls if c[:2] == ("pr", "create")]
    # the same release with other files (a CDT change, a re-spin) is a new bump
    assert pinwatch.open_or_update_pr("pin/stock-rb3gen2", "bump to 00150", "b2\nSource: x", run=gh)[0] == "created"
    gh = FakeGh([pr(7, "bump to 00150", "b", state="CLOSED"), pr(8, "bump to 00150", "b", state="MERGED")])
    assert pinwatch.open_or_update_pr("pin/stock-rb3gen2", "bump to 00160", "b", run=gh)[0] == "created"


def test_source_links_alone_do_not_make_a_new_bump():
    gh = FakeGh([pr(7, "t", "table\nSource: https://x/commit/1", state="CLOSED")])
    assert pinwatch.open_or_update_pr("b", "t", "table\nSource: https://x/commit/2", run=gh) == ("declined", None)


def test_unparsable_src_uri_append_is_an_error(tmp_path):
    write(str(tmp_path / "d_1.bb"), 'SRC_URI = "https://x/d.zip;name=d"\nSRC_URI[d.sha256sum] = "%s"\n'
          "SRC_URI:append = ' https://x/e.zip;name=e'\n" % ("0" * 64))
    with pytest.raises(bitbake.RecipeError, match="cannot read"):
        bitbake.parse(str(tmp_path / "d_1.bb"))


def test_diff():
    assert pinwatch.diff({"a": 1, "b": 2}, {"a": 1, "b": 3}) == {"b": (2, 3)}
