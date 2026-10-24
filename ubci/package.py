"""Assemble the qcomflash tarball LAVA flashes for one board and stack.

python3 -m ubci.package <board> <stock|open> <uefi image> <efi.bin> <out.tar.gz>
python3 -m ubci.package insert-bl2 <package.tar.gz> <board>
    adds the board's BL2 from the environment variable named by its pin
    (secret, gzip + base64), checked against the pinned sha256

The base is what meta-qcom's qcomflash image holds for the board: the
public boot binaries and CDT it pins, and the GPT, rawprogram and patch
files qcom-ptool makes from the board's layout. Then:
  stock  uefi_a/uefi_b <- the U-Boot under test (u-boot.mbn); the stock
         tz.mbn stays;
  open   tz_a/tz_b <- the pinned pre-signed TF-A BL2, uefi_a/uefi_b <-
         fip.elf (BL31 + OP-TEE + U-Boot). The BL2 is not public: when it is
         not staged in $UBCI_WORK/pins (CI build jobs hold no secrets), the
         package goes without tz.mbn ("deferred" in SOURCES.json) and the
         submit job adds it from its secret (insert-bl2 below);
  both   efi <- the ESP with the linux-next UKI.
Partitions whose image the package does not carry (dtb, rootfs, persist,
...) are left unwritten. SOURCES.json lists every file and its sha256.
"""
import base64
import glob
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from . import config
from .fetch import WORK, fetch, sha256

PTOOL = os.environ.get("QCOM_PTOOL_DIR", "/opt/qcom-ptool")
REQUIRED = ("xbl.elf", "xbl_config.elf", "tz.mbn", "uefi.elf", "efi.bin", "cdt.bin")


def unzip_top(zpath, dest):
    """Top-level files of each directory in the archive into dest."""
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if info.is_dir() or len(parts) != 2:
                continue
            with z.open(info) as src, open(os.path.join(dest, parts[1]), "wb") as dst:
                shutil.copyfileobj(src, dst)


def partitions(layout, dest):
    """GPT and rawprogram/patch files for the layout, generated in dest."""
    work = tempfile.mkdtemp(dir=dest)
    if "conf" in layout:
        subprocess.run(["qcom-ptool", "gen_partition", "-i", os.path.join(PTOOL, layout["conf"]),
                        "-o", os.path.join(work, "partitions.xml")], check=True)
        out = work
    else:
        subprocess.run(["qcom-ptool", "gen_partition", "--board", os.path.join(PTOOL, layout["board"]),
                        "-C", work], check=True)
        out = os.path.join(work, layout["storage"])
    subprocess.run(["qcom-ptool", "ptool", "-x", "partitions.xml"], cwd=out, check=True,
                   stdout=subprocess.DEVNULL)
    for pat in ("rawprogram*.xml", "patch*.xml", "gpt_*.bin", "zeros_*.bin"):
        for f in glob.glob(os.path.join(out, pat)):
            shutil.move(f, os.path.join(dest, os.path.basename(f)))
    shutil.rmtree(work)


def skip_missing(d, keep=()):
    """Blank the filename of program entries whose file the package does
    not carry, so qdl leaves those partitions alone. Returns their labels."""
    skipped = []
    for rp in sorted(glob.glob(os.path.join(d, "rawprogram*.xml"))):
        text = open(rp).read()

        def blank(m):
            name = m.group(2)
            if name and name not in keep and not os.path.exists(os.path.join(d, name)):
                label = re.search(r'label="([^"]*)"', m.group(0))
                skipped.append("%s (%s)" % (label.group(1) if label else "?", name))
                return m.group(0).replace('filename="%s"' % name, 'filename=""')
            return m.group(0)
        open(rp, "w").write(re.sub(r'<program ([^>]*?)filename="([^"]*)"[^>]*/>', blank, text))
    return skipped


def build(board_name, stack, uefi_image, efi, out):
    b = config.board(board_name)
    s = b["stock"]
    dirname = "ubci-%s-%s" % (board_name, stack)
    stage = tempfile.mkdtemp(dir=WORK)
    d = os.path.join(stage, dirname)
    os.makedirs(d)
    try:
        for bb in s["bootbinaries"]:
            unzip_top(fetch(bb["url"], bb["sha256"]), d)
        for f in glob.glob(os.path.join(d, "partition_*.xml")):
            os.remove(f)
        if s["xbl_config"] != "xbl_config.elf":
            shutil.copy(os.path.join(d, s["xbl_config"]), os.path.join(d, "xbl_config.elf"))
        with zipfile.ZipFile(fetch(s["cdt"]["url"], s["cdt"]["sha256"])) as z, \
                open(os.path.join(d, "cdt.bin"), "wb") as f:
            f.write(z.read(s["cdt"]["file"]))
        partitions(s["partitions"], d)
        components = {"stock": s["release"]}
        deferred = []
        if stack == "open":
            bl2 = b["pins"]["bl2"]
            staged = os.path.join(WORK, "pins", bl2["file"])
            if os.path.exists(staged):
                shutil.copy(fetch(None, bl2["sha256"], bl2["file"]), os.path.join(d, "tz.mbn"))
            else:
                os.remove(os.path.join(d, "tz.mbn"))  # never the stock QTEE in place of BL2
                deferred.append("tz.mbn")
            components["bl2"] = bl2["fingerprint"]
        shutil.copy(uefi_image, os.path.join(d, "uefi.elf"))
        shutil.copy(efi, os.path.join(d, "efi.bin"))
        for f in REQUIRED:
            if f not in deferred and not os.path.exists(os.path.join(d, f)):
                raise SystemExit("package lacks %s" % f)
        skipped = skip_missing(d, keep=deferred)
        files = sorted(f for f in os.listdir(d))
        json.dump({"board": board_name, "stack": stack, "components": components,
                   "deferred": deferred,
                   "not_written": skipped,
                   "files": {f: sha256(os.path.join(d, f)) for f in files}},
                  open(os.path.join(d, "SOURCES.json"), "w"), indent=1)
        with tarfile.open(out, "w:gz", compresslevel=6) as t:
            t.add(d, arcname=dirname)
    finally:
        shutil.rmtree(stage)
    return dirname, skipped


def sources(package):
    with tarfile.open(package) as t:
        for m in t.getmembers():
            if m.name.endswith("/SOURCES.json"):
                return json.load(t.extractfile(m))
    raise SystemExit("%s has no SOURCES.json" % package)


def insert_bl2(package, board_name, env=os.environ):
    """Add the deferred BL2 to a package from the secret its pin names."""
    bl2 = config.board(board_name)["pins"]["bl2"]
    value = env.get(bl2["secret"])
    if not value:
        raise SystemExit("%s is not set" % bl2["secret"])
    data = gzip.decompress(base64.b64decode(value))
    if hashlib.sha256(data).hexdigest() != bl2["sha256"]:
        raise SystemExit("%s does not match the pinned sha256" % bl2["secret"])
    tmp = package + ".tmp"
    with tarfile.open(package) as src, tarfile.open(tmp, "w:gz", compresslevel=6) as dst:
        for m in src.getmembers():
            f = src.extractfile(m) if m.isfile() else None
            if m.name.endswith("/SOURCES.json"):
                meta = json.load(f)
                meta["deferred"] = [x for x in meta.get("deferred", []) if x != "tz.mbn"]
                meta["files"]["tz.mbn"] = bl2["sha256"]
                blob = json.dumps(meta, indent=1).encode()
                m.size = len(blob)
                f = io.BytesIO(blob)
                top = m.name.split("/")[0]
            dst.addfile(m, f)
        info = tarfile.TarInfo(top + "/tz.mbn")
        info.size, info.mode = len(data), 0o644
        dst.addfile(info, io.BytesIO(data))
    os.replace(tmp, package)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "insert-bl2":
        insert_bl2(sys.argv[2], sys.argv[3])
        sys.exit(0)
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    name, skipped = build(*sys.argv[1:6])
    print(json.dumps({"path": name, "not_written": skipped}))
