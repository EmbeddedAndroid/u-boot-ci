import hashlib
import json
import os
import shutil
import zipfile

import pytest

from ubci import config, package


def test_unzip_top_flattens_release_directories(tmp_path):
    z = tmp_path / "bb.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("QCM6490_bootbinaries/xbl.elf", "x")
        f.writestr("QCM6490_bootbinaries/sail_nor/rawprogram0.xml", "nested")
        f.writestr("QCM6490_bootbinaries/", "")
    out = tmp_path / "out"
    out.mkdir()
    package.unzip_top(str(z), str(out))
    assert sorted(os.listdir(out)) == ["xbl.elf"]


def test_skip_missing_blanks_only_absent_images(tmp_path):
    (tmp_path / "xbl.elf").write_text("x")
    (tmp_path / "rawprogram0.xml").write_text(
        '<data>\n'
        '<program SECTOR_SIZE_IN_BYTES="4096" filename="xbl.elf" label="xbl_a" start_sector="6"/>\n'
        '<program SECTOR_SIZE_IN_BYTES="4096" filename="dtb.bin" label="dtb_a" start_sector="9"/>\n'
        '<program SECTOR_SIZE_IN_BYTES="4096" filename="" label="ddr_a" start_sector="12"/>\n'
        '</data>\n')
    assert package.skip_missing(str(tmp_path)) == ["dtb_a (dtb.bin)"]
    text = (tmp_path / "rawprogram0.xml").read_text()
    assert 'filename="xbl.elf"' in text and 'filename="dtb.bin"' not in text
    assert text.count('filename=""') == 2


@pytest.mark.skipif(not shutil.which("qcom-ptool"), reason="needs the CI container")
@pytest.mark.parametrize("board,stack", [(b, s) for b in config.boards() for s in config.STACKS
                                         if s in config.board(b)["u-boot"]])
def test_partition_layout_has_the_partitions_the_jobs_flash(board, stack, tmp_path):
    b = config.board(board)
    d = config.downstream(b, stack)
    package.partitions(d["partitions"], str(tmp_path))
    names = os.listdir(tmp_path)
    for lun in b["lava"]["luns"]:
        assert "rawprogram%d.xml" % lun in names and "patch%d.xml" % lun in names
    written = package.written_images(str(tmp_path))
    want = set(d.get("required", package.REQUIRED)) | {package.slot(b, stack), "efi.bin", "tz.mbn"}
    if stack == "spl":
        want.add(b["spl"]["slot"])
    assert want <= written, want - written
    if d.get("cdt"):
        assert "cdt.bin" in written


def fake_board(slot="boot.img"):
    """RB3 Gen 2 as if its downstream firmware ended in ABL (as UNO Q's)."""
    b = config.board("rb3gen2")
    b["u-boot"]["stock"]["slot"] = slot
    d = b["downstream"]
    d.update(bootbinaries=[{"url": "https://x/bb.zip", "sha256": "1" * 64}],
             required=["xbl.elf", "xbl_feature_config.elf", "tz.mbn", "abl.elf"], release="ABL firmware 1")
    del d["cdt"], d["xbl_config"]
    return b


LAYOUT = """<data>
<program filename="xbl.elf" label="xbl_a"/>
<program filename="tz.mbn" label="tz_a"/>
<program filename="abl.elf" label="abl_a"/>
<program filename="xbl_feature_config.elf" label="xbl_config_a"/>
<program filename="boot.img" label="boot_a"/>
<program filename="dtb.bin" label="dtb_a"/>
<program filename="efi.bin" label="efi"/>
</data>
"""


@pytest.fixture
def fake_build(tmp_path, monkeypatch):
    z = tmp_path / "bb.zip"
    with zipfile.ZipFile(z, "w") as f:
        for n in ("xbl.elf", "tz.mbn", "abl.elf", "xbl_feature_config.elf", "boot.img"):
            f.writestr("fw/" + n, "downstream " + n)
        for n in ("rawprogram0.xml", "rawprogram0.nouser.xml"):
            f.writestr("fw/" + n, "<data><program filename=\"../disk.img\" label=\"x\"/></data>")
        f.writestr("fw/gpt_main1.bin", "archive gpt")
    monkeypatch.setattr(package, "WORK", str(tmp_path))
    monkeypatch.setattr(package, "fetch", lambda url, sha, name=None: str(z))

    def go(board, layout=LAYOUT, stack="stock"):
        monkeypatch.setattr(config, "board", lambda name: board)
        monkeypatch.setattr(package, "partitions",
                            lambda lay, d: open(os.path.join(d, "rawprogram0.xml"), "w").write(layout))
        (tmp_path / "uboot.img").write_text("U-Boot under test")
        (tmp_path / "spl.mbn").write_text("U-Boot SPL under test")
        (tmp_path / "efi.bin").write_text("esp")
        out = str(tmp_path / "pkg.tar.gz")
        name, skipped = package.build("rb3gen2", stack, str(tmp_path / "uboot.img"), str(tmp_path / "efi.bin"), out)
        return name, skipped, package.sources(out), out
    return go


def test_abl_chainload_puts_u_boot_in_the_boot_image_slot(fake_build):
    import tarfile
    name, skipped, src, out = fake_build(fake_board())
    assert skipped == ["dtb_a (dtb.bin)"]
    with tarfile.open(out) as t:
        assert t.extractfile(name + "/boot.img").read() == b"U-Boot under test"
        rp = t.extractfile(name + "/rawprogram0.xml").read().decode()
        members = t.getnames()
    # The layout is qcom-ptool's, never the archive's own.
    assert "disk.img" not in rp and 'filename="boot.img"' in rp
    assert name + "/rawprogram0.nouser.xml" not in members and name + "/gpt_main1.bin" not in members
    assert src["components"] == {"downstream": "ABL firmware 1"}


def test_a_layout_that_does_not_write_the_slot_is_refused(fake_build):
    b = fake_board()
    with pytest.raises(SystemExit, match="writes no boot.img"):
        fake_build(b, layout=LAYOUT.replace("boot.img", "other.img"))
    with pytest.raises(SystemExit, match="writes no tz.mbn"):
        fake_build(b, layout=LAYOUT.replace('"tz.mbn"', '"other.mbn"'))


def test_a_package_without_a_required_image_is_refused(fake_build):
    b = fake_board()
    b["downstream"]["required"] = ["xbl.elf", "hyp.mbn"]
    with pytest.raises(SystemExit, match="package lacks hyp.mbn"):
        fake_build(b)


def spl_board(slot="tz.mbn"):
    b = fake_board(slot="uefi.elf")
    b["u-boot"]["spl"] = dict(b["u-boot"]["stock"])
    b["spl"] = {"slot": slot, "sign": "tz"}
    b["pins"]["bl2"]["pending"] = "never used by the spl stack"
    return b


SPL_LAYOUT = LAYOUT.replace("boot.img", "uefi.elf")


@pytest.mark.parametrize("slot", ["tz.mbn", "xbl.elf"])
def test_spl_stack_puts_the_spl_built_here_in_its_slot(fake_build, slot):
    import tarfile
    name, _, src, out = fake_build(spl_board(slot), layout=SPL_LAYOUT, stack="spl")
    with tarfile.open(out) as t:
        assert t.extractfile(name + "/" + slot).read() == b"U-Boot SPL under test"
        assert t.extractfile(name + "/uefi.elf").read() == b"U-Boot under test"
        other = "xbl.elf" if slot == "tz.mbn" else "tz.mbn"
        assert t.extractfile(name + "/" + other).read() == b"downstream " + other.encode()
    # Nothing is deferred: the SPL is not a secret pin.
    assert src["deferred"] == [] and src["components"]["spl"] == slot
    assert "bl2" not in src["components"]


def test_spl_stack_needs_a_layout_that_writes_its_slot(fake_build):
    with pytest.raises(SystemExit, match="writes no xbl.elf"):
        fake_build(spl_board("xbl.elf"), layout=SPL_LAYOUT.replace('"xbl.elf"', '"other.elf"'), stack="spl")


BLOBS = {"QcLib.elf": b"qclib", "shrm.elf": b"shrm"}


def blob_board(files=BLOBS):
    b = spl_board("xbl.elf")
    b["spl"]["pre_ddr"] = [{"name": n.split(".")[0].lower(), "file": n, "load": "0xc00000",
                            "entry": "0xc00000", "description": n,
                            "sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()]
    return b


@pytest.fixture
def blob_zip(tmp_path, monkeypatch):
    def go(files):
        z = tmp_path / "bb.zip"
        with zipfile.ZipFile(z, "w") as f:
            for n, d in files.items():
                f.writestr("fw/" + n, d)
        monkeypatch.setattr(package, "WORK", str(tmp_path))
        monkeypatch.setattr(package, "fetch", lambda url, sha, name=None: str(z))
        return str(tmp_path / "blobs")
    return go


def test_pre_ddr_blobs_come_from_the_downstream_archive_checked(blob_zip, monkeypatch):
    b = blob_board()
    monkeypatch.setattr(config, "board", lambda name: b)
    dest = blob_zip(dict(BLOBS, **{"xbl.elf": b"x"}))
    assert package.blobs("shikra", "spl", dest) == ["QcLib.elf", "shrm.elf"]
    assert sorted(os.listdir(dest)) == ["QcLib.elf", "shrm.elf"]


def test_a_missing_pre_ddr_blob_is_refused(blob_zip, monkeypatch):
    b = blob_board()
    monkeypatch.setattr(config, "board", lambda name: b)
    dest = blob_zip({"QcLib.elf": b"qclib"})
    with pytest.raises(SystemExit, match="lack the pre-ddr blob shrm.elf"):
        package.blobs("shikra", "spl", dest)


def test_a_pre_ddr_blob_with_another_sha256_is_refused(blob_zip, monkeypatch):
    b = blob_board()
    monkeypatch.setattr(config, "board", lambda name: b)
    dest = blob_zip({"QcLib.elf": b"qclib", "shrm.elf": b"other shrm"})
    with pytest.raises(SystemExit, match="pre-ddr blob shrm.elf: sha256"):
        package.blobs("shikra", "spl", dest)


def private_board():
    b = fake_board(slot="uefi.elf")
    b["u-boot"]["open"] = dict(b["u-boot"]["stock"])
    p = {n: {"private": "internal x", "file": "%s-b.bin" % n, "sha256": "", "fingerprint": "FP-1"}
         for n in ("tf-a", "bl2", "optee")}
    p["tf-a"].update(fip_load_addr="0xa7000000", sign=["-v7", "uefi"])
    b["pins"] = p
    return b


def test_a_private_open_stack_leaves_tz_and_the_fip_to_the_submit_job(fake_build):
    import tarfile
    name, skipped, src, out = fake_build(private_board(), layout=LAYOUT.replace("boot.img", "uefi.elf"),
                                         stack="open")
    assert src["deferred"] == ["tz.mbn", "uefi.elf"] and src["files"]["bl33.bin"]
    with tarfile.open(out) as t:
        names = [n.split("/", 1)[-1] for n in t.getnames()]
        assert t.extractfile(name + "/bl33.bin").read() == b"U-Boot under test"
    # Never the downstream QTEE or a stale image in their place.
    assert "tz.mbn" not in names and "uefi.elf" not in names
    assert "tz_a (tz.mbn)" not in skipped and "uefi_a (uefi.elf)" not in skipped


def stage_private(tmp_path, monkeypatch, b, data):
    import hashlib
    from ubci import fetch
    (tmp_path / "pins").mkdir(exist_ok=True)
    for n, blob in data.items():
        (tmp_path / "pins" / b["pins"][n]["file"]).write_bytes(blob)
        b["pins"][n]["sha256"] = hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr(package, "WORK", str(tmp_path))
    monkeypatch.setattr(fetch, "WORK", str(tmp_path))
    monkeypatch.setattr(package, "fetch", fetch.fetch)


def test_insert_private_builds_the_signed_fip_around_the_u_boot_under_test(fake_build, tmp_path, monkeypatch):
    import tarfile
    from ubci import fip
    b = private_board()
    name, _, _, out = fake_build(b, layout=LAYOUT.replace("boot.img", "uefi.elf"), stack="open")
    stage_private(tmp_path, monkeypatch, b, {"bl2": b"bl2", "tf-a": b"bl31", "optee": b"tee"})
    signed = []

    def sign(elf, args):
        signed.append((elf, args))
        return b"signed:" + elf
    package.insert_private(out, "x", env={}, sign=sign)
    elf, args = signed[0]
    assert args == ["-v7", "uefi"]
    assert elf == fip.elf(fip.build({"bl31": b"bl31", "bl32": b"tee", "bl33": b"U-Boot under test"}), 0xa7000000)
    with tarfile.open(out) as t:
        assert t.extractfile(name + "/uefi.elf").read() == b"signed:" + elf
        assert t.extractfile(name + "/tz.mbn").read() == b"bl2"
        assert name + "/bl33.bin" not in t.getnames()
    src = package.sources(out)
    assert src["deferred"] == [] and "bl33.bin" not in src["files"] and set(src["files"]) >= {"tz.mbn", "uefi.elf"}


def test_insert_private_refuses_a_wrong_or_missing_image(fake_build, tmp_path, monkeypatch):
    b = private_board()
    _, _, _, out = fake_build(b, layout=LAYOUT.replace("boot.img", "uefi.elf"), stack="open")
    stage_private(tmp_path, monkeypatch, b, {"bl2": b"bl2", "tf-a": b"bl31", "optee": b"tee"})
    b["pins"]["optee"]["sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="sha256"):
        package.insert_private(out, "x", env={}, sign=lambda e, a: e)
    (tmp_path / "pins" / b["pins"]["optee"]["file"]).unlink()
    with pytest.raises(SystemExit, match="UBCI_PRIVATE_TOKEN is not set"):
        package.insert_private(out, "x", env={}, sign=lambda e, a: e)
    assert package.sources(out)["deferred"] == ["tz.mbn", "uefi.elf"]


def test_private_file_is_a_release_asset_read_with_the_token_only_from_the_api(tmp_path, monkeypatch, capsys):
    import hashlib
    import http.server
    import threading
    monkeypatch.setattr(package, "WORK", str(tmp_path))
    seen = []
    servers = []

    def serve(handler):
        srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return "http://127.0.0.1:%d" % srv.server_port

    class Quiet(http.server.BaseHTTPRequestHandler):
        def reply(self, code, body=b"", **headers):
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Files(Quiet):
        def do_GET(self):
            seen.append(("files", self.path, self.headers.get("Authorization"), self.headers.get("Accept")))
            self.reply(200, b"image") if self.path == "/blob/bl31?sig=1" else self.reply(404)

    files = serve(Files)

    class Api(Quiet):
        def do_GET(self):
            seen.append(("api", self.path, self.headers.get("Authorization"), self.headers.get("Accept")))
            assets = [{"name": "bl31-b.bin", "url": api + "/repos/o/fw/releases/assets/1"},
                      {"name": "gone.bin", "url": api + "/repos/o/fw/releases/assets/2"},
                      {"name": "loop.bin", "url": api + "/repos/o/fw/releases/assets/3"},
                      {"name": "far.bin", "url": files + "/repos/o/fw/releases/assets/4"}]
            if self.path == "/repos/o/fw/releases/tags/r1":
                self.reply(200, json.dumps({"assets": assets}).encode())
            elif self.path == "/repos/o/fw/releases/assets/1":
                self.reply(302, Location=files + "/blob/bl31?sig=1")
            elif self.path == "/repos/o/fw/releases/assets/3":
                self.reply(302, Location="ftp://elsewhere/x")
            else:
                self.reply(404)

    api = serve(Api)
    monkeypatch.setattr(package, "GITHUB_API", api)
    try:
        env = {"UBCI_PRIVATE_TOKEN": "s3cret\n"}
        pin = {"file": "bl31-b.bin", "release": "r1", "sha256": hashlib.sha256(b"image").hexdigest()}
        assert package.private_file(pin, env, store="o/fw") == b"image"
        assert seen == [("api", "/repos/o/fw/releases/tags/r1", "Bearer s3cret", "application/vnd.github+json"),
                        ("api", "/repos/o/fw/releases/assets/1", "Bearer s3cret", "application/octet-stream"),
                        ("files", "/blob/bl31?sig=1", None, None)]
        with pytest.raises(SystemExit, match="does not match"):
            package.private_file(dict(pin, sha256="0" * 64), env, store="o/fw")
        with pytest.raises(SystemExit, match="not in release r1 of the private store"):
            package.private_file(dict(pin, file="new.bin"), env, store="o/fw")
        for change in ({"file": "gone.bin"}, {"file": "loop.bin"}, {"file": "far.bin"}, {"release": "r2"}):
            with pytest.raises(SystemExit, match="cannot be read from the private store") as e:
                package.private_file(dict(pin, **change), env, store="o/fw")
            assert "s3cret" not in str(e.value) and "127.0.0.1" not in str(e.value)
        # A redirect off the API's scheme is refused before it is followed.
        assert "redirect leaves" in capsys.readouterr().err
        # The token went to the API and nowhere else.
        assert [x for x in seen if x[2]] == [x for x in seen if x[0] == "api"]
        assert not [x for x in seen if x[0] == "files" and x[1] != "/blob/bl31?sig=1"]
        # A broken token is reported without quoting it.
        with pytest.raises(SystemExit, match="cannot be read from the private store") as e:
            package.private_file(pin, {"UBCI_PRIVATE_TOKEN": "s3cret\nX: y"}, store="o/fw")
        assert "s3cret" not in str(e.value)
        # The job log, where the token is masked, gets the cause.
        assert "ValueError" in capsys.readouterr().err
        with pytest.raises(SystemExit, match="UBCI_PRIVATE_TOKEN is not set"):
            package.private_file(pin, {"UBCI_PRIVATE_TOKEN": " "}, store="o/fw")
    finally:
        for srv in servers:
            srv.shutdown()


def test_the_private_pins_name_a_release_of_the_store():
    pins = config.pins()
    assert package.yaml_pins()["private_store"].count("/") == 1
    for board, p in pins.items():
        for name in ("bl2", "tf-a", "optee"):
            if (p.get(name) or {}).get("private"):
                assert p[name]["release"] and p[name]["file"], (board, name)

def test_the_signed_fip_elf_matches_tf_a_and_qtestsign():
    # The pinned qtestsign over ubci.fip's ELF gives what qtestsign gives
    # over generate_fip_elf.sh's linker output (tests/test_fip.py).
    import hashlib
    from ubci import fip
    import subprocess
    from tests.test_fip import GOLDEN, GOLDEN_SIGNED
    top = package.yaml_pins()["qtestsign"]
    try:
        subprocess.run([os.path.join(package.config.ROOT, "scripts", "checkout.sh"), "qtestsign", top["repo"],
                        top["commit"]], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pytest.skip("needs the pinned qtestsign (network on first use)")
    signed = package.qtestsign(fip.elf(fip.build(GOLDEN), 0xa7000000), ["-v7", "uefi"])
    assert hashlib.sha256(signed).hexdigest() == GOLDEN_SIGNED
