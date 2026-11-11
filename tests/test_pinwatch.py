import hashlib
import io
import json
import os
import shutil
import subprocess

import pytest

from fwci import bitbake, pinwatch
from ubci import config, stockpin

DATA = os.path.join(os.path.dirname(__file__), "data", "layers")
ROOTS = {"meta-qcom": os.path.join(DATA, "meta-qcom"),
         "meta-qcom-arduino": os.path.join(DATA, "meta-qcom-arduino")}


@pytest.mark.parametrize("board", config.boards())
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
    """meta-qcom with a 00151 QCM6490 release next to 00150, the pin."""
    root = tmp_path / "meta-qcom"
    shutil.copytree(ROOTS["meta-qcom"], root)
    d = root / "recipes-bsp" / "firmware-boot"
    text = (d / "firmware-qcom-boot-qcs6490_00150.bb").read_text()
    (d / "firmware-qcom-boot-qcs6490_00151.bb").write_text(
        text.replace("f6982fed9eaa546649f53c4aedc960f031123c3b7dac06803dc7dabbff533ee0", "1" * 64))
    return {"meta-qcom": str(root)}


def test_bump_writes_the_pr_and_keeps_the_rest_of_the_config(tmp_path, monkeypatch):
    roots = newer_layer(tmp_path)
    monkeypatch.setattr(stockpin, "checkout", lambda name, layer: (roots[name], "c" * 40))
    out = tmp_path / "out"
    out.mkdir()
    r = stockpin.check("rb3gen2", str(out), verify=False)
    assert r == {"board": "rb3gen2", "result": "bump", "from": "QCM6490 boot binaries 00150",
                 "to": "QCM6490 boot binaries 00151"}
    new = (out / "rb3gen2.yaml").read_text()
    old = open(os.path.join(config.CONFIG, "boards", "rb3gen2.yaml")).read()
    assert "1" * 64 in new and "00151/QCM6490_bootbinaries_00151.zip" in new
    assert new.count("\n") == old.count("\n") and "# Qualcomm RB3 Gen 2" in new
    assert (out / "rb3gen2.title").read_text().startswith("config: rb3gen2: bump downstream firmware")
    assert "https://github.com/qualcomm-linux/meta-qcom/commit/" + "c" * 40 in (out / "rb3gen2.body").read_text()
    # The pin records the layer commit it was read at.
    assert "source: {meta-qcom: %s}" % ("c" * 40) in new


def test_board_without_a_cdt_recipe_bumps_its_boot_firmware_and_its_section_only(tmp_path, monkeypatch):
    root = tmp_path / "meta-qcom-arduino"
    shutil.copytree(ROOTS["meta-qcom-arduino"], root)
    d = root / "recipes-bsp" / "firmware-boot"
    text = (d / "firmware-qcom-boot-qrb2210-arduino-imola_251020.bb").read_text()
    (d / "firmware-qcom-boot-qrb2210-arduino-imola_251110.bb").write_text(
        text.replace("c606e95d0107f8c58d0dd9494e00624d1db7c4361cca20513bc78ef02ca28dd1", "2" * 64))
    roots = dict(ROOTS, **{"meta-qcom-arduino": str(root)})
    monkeypatch.setattr(stockpin, "checkout", lambda name, layer: (roots[name], name[-1] * 40))
    out = tmp_path / "out"
    out.mkdir()
    r = stockpin.check("uno-q", str(out), verify=False)
    assert r["result"] == "bump" and r["to"] == "Arduino UNO Q boot firmware 251110"
    new = (out / "uno-q.yaml").read_text()
    head, opn = new.split("\ndownstream_open:\n")
    assert "unoq-bootloader-emmc-linux-251110.zip" in head and "2" * 64 in head
    assert "meta-qcom: %s" % ("m" * 40) in head and "meta-qcom-arduino: %s" % ("o" * 40) in head
    # downstream_open was not read at the new commits: its pin stays.
    assert "source: {meta-qcom: c853febcdeb149021fd043ac7a5eaae88f29f7b7}" in opn
    assert "| CDT |" not in (out / "uno-q.body").read_text()


def test_a_cdt_appearing_or_vanishing_is_bumped_by_hand():
    old = {"release": "a", "bootbinaries": [{"url": "u", "sha256": "1"}], "cdt": None}
    new = dict(old, release="b", cdt={"url": "c", "sha256": "2"})
    with pytest.raises(pinwatch.PinError, match="by hand"):
        stockpin.bump("x\ndownstream:\n  release: a\n", old, new)


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


def test_an_open_pr_is_updated_through_the_rest_api():
    gh = FakeGh([pr(7, "old title", "old\nSource: x")])
    assert pinwatch.open_or_update_pr("pin/stock-rb3gen2", "t=1", "b\nSource: y", run=gh) == ("updated", 7)
    assert gh.calls[1:] == [("api", "-X", "PATCH", "repos/{owner}/{repo}/pulls/7",
                             "-f", "title=t=1", "-f", "body=b\nSource: y")]
    assert not [c for c in gh.calls if c[:2] == ("pr", "edit")]


def test_a_failed_update_is_not_reported_as_updated():
    def run(*args):
        if args[0] == "api":
            raise subprocess.CalledProcessError(1, ["gh"] + list(args))
        return json.dumps([pr(7, "t", "old")])
    with pytest.raises(subprocess.CalledProcessError):
        pinwatch.open_or_update_pr("pin/stock-rb3gen2", "t", "b", run=run)


def fake_gh_on_path(tmp_path, monkeypatch, script):
    exe = tmp_path / "gh"
    exe.write_text("#!/bin/sh\n" + script)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (tmp_path, os.environ["PATH"]))


def test_gh_failure_prints_its_stderr(tmp_path, monkeypatch, capsys):
    fake_gh_on_path(tmp_path, monkeypatch, "echo 'GraphQL: Projects (classic) is being deprecated' >&2\nexit 1\n")
    with pytest.raises(subprocess.CalledProcessError) as e:
        pinwatch.gh("pr", "edit", "1")
    assert e.value.returncode == 1
    assert "Projects (classic) is being deprecated" in capsys.readouterr().err


def test_gh_success_returns_stdout_and_prints_nothing(tmp_path, monkeypatch, capsys):
    fake_gh_on_path(tmp_path, monkeypatch, 'echo "$@"; echo noise >&2\n')
    assert pinwatch.gh("api", "-X", "PATCH", "x") == "api -X PATCH x\n"
    assert capsys.readouterr().err == ""


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


def test_bump_of_a_board_whose_downstream_section_is_an_anchor(tmp_path, monkeypatch):
    import yaml
    root = tmp_path / "meta-qcom"
    shutil.copytree(ROOTS["meta-qcom"], root)
    d = root / "recipes-bsp" / "firmware-boot"
    text = (d / "firmware-qcom-boot-qcs9100_00142.bb").read_text()
    (d / "firmware-qcom-boot-qcs9100_00150.bb").write_text(
        text.replace("17d2c5bae5c17b665bafd9bba8962f41aec7be2f874cde90b0976730f0098bf6", "3" * 64)
            .replace("1aa0b67671ef026a40ca133f32128d07fffd614a47cf51eaa5cd5c7d4941d034", "4" * 64))
    monkeypatch.setattr(stockpin, "checkout", lambda name, layer: (str(root), "c" * 40))
    out = tmp_path / "out"
    out.mkdir()
    assert stockpin.check("lemans-evk", str(out), verify=False)["result"] == "bump"
    b = yaml.safe_load((out / "lemans-evk.yaml").read_text())
    assert b["downstream"]["release"] == "QCS9100 boot binaries 00150"
    assert b["downstream"]["source"] == {"meta-qcom": "c" * 40}
    # downstream_spl is the same release with its own XBLConfig.
    assert b["downstream_spl"]["bootbinaries"] == b["downstream"]["bootbinaries"]
    assert b["downstream_spl"]["xbl_config"] == "xbl_config_spl.elf"
    # The watcher goes on to the next board.
    monkeypatch.setattr(config, "boards", lambda: ["lemans-evk", "rb3gen2"])
    assert stockpin.main([str(tmp_path / "all"), "--no-verify"]) == 0
    assert [r["result"] for r in json.load(open(tmp_path / "all" / "summary.json"))] == ["bump", "up to date"]


def test_a_board_without_a_stock_stack_is_not_watched(tmp_path, monkeypatch):
    def no_checkout(name, layer):
        raise AssertionError("no layer is read for it")
    monkeypatch.setattr(stockpin, "checkout", no_checkout)
    assert stockpin.check("sm8750-mtp", str(tmp_path), verify=False) == {
        "board": "sm8750-mtp", "result": "no stock stack to validate a bump on"}
    assert os.listdir(tmp_path) == []


class _Flaky:
    """fetch() that fails `fails` times with `exc`, then serves `data`."""
    def __init__(self, data, fails, exc):
        self.data, self.fails, self.exc, self.calls = data, fails, exc, 0

    def __call__(self, url):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc
        return io.BytesIO(self.data)


def test_verify_retries_a_transient_download_error():
    import urllib.error
    data = b"fw"
    f = _Flaky(data, 2, urllib.error.URLError("_ssl.c:983: The handshake operation timed out"))
    pinwatch.verify([("https://x/a.zip", hashlib.sha256(data).hexdigest())], fetch=f, sleep=lambda s: None)
    assert f.calls == 3


def test_verify_gives_up_after_the_last_attempt():
    f = _Flaky(b"fw", 5, TimeoutError("timed out"))
    with pytest.raises(TimeoutError):
        pinwatch.verify([("https://x/a.zip", "00")], fetch=f, sleep=lambda s: None)
    assert f.calls == 3


def test_verify_does_not_retry_a_digest_mismatch():
    f = _Flaky(b"fw", 0, OSError())
    with pytest.raises(pinwatch.PinError):
        pinwatch.verify([("https://x/a.zip", "00")], fetch=f, sleep=lambda s: None)
    assert f.calls == 1
