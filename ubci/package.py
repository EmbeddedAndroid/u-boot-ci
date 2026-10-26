"""Assemble the qcomflash tarball LAVA flashes for one board and stack.

python3 -m ubci.package <board> <stock|open|spl> <uefi image> <efi.bin> <out.tar.gz>
python3 -m ubci.package insert-bl2 <package.tar.gz> <board>
    adds the board's BL2 from the environment variable named by its pin
    (secret, gzip + base64), checked against the pinned sha256
python3 -m ubci.package blobs <board> <stack> <dir>
    extracts the pre-ddr blobs the board's SPL FIT carries (spl.pre_ddr)
    from the stack's downstream boot binaries into <dir>, each checked
    against its pinned sha256

The base is what the board's meta layer flashes: the public downstream
boot binaries and CDT it pins (downstream, or downstream_open for the
open stack of a board that needs other boot firmware there), and the
GPT, rawprogram and patch files qcom-ptool makes from the board's
layout. Then:
  stock  the U-Boot under test goes where the board's downstream firmware
         loads it (u-boot.stock.slot: uefi.elf for uefi_a/uefi_b, or
         boot.img for boot_a/boot_b when ABL chainloads it); the
         downstream tz.mbn stays;
  open   tz_a/tz_b <- the pinned pre-signed image XBL loads from tz (TF-A
         BL2, or U-Boot SPL on Lemans), uefi_a/uefi_b <- fip.elf or the
         SPL FIT (BL31 + OP-TEE + U-Boot). The tz image is not public:
         when it is not staged in $UBCI_WORK/pins (CI build jobs hold no
         secrets), the package goes without tz.mbn ("deferred" in
         SOURCES.json) and the submit job adds it from its secret
         (insert-bl2 below);
  spl    the image the board's SPL replaces (spl.slot: tz.mbn when XBL
         loads it, xbl.elf when the boot ROM does) <- the U-Boot SPL built
         and signed with U-Boot (spl.mbn next to the uefi image),
         uefi_a/uefi_b <- the SPL FIT;
  all    efi <- the ESP with the linux-next UKI.
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
# What every package must carry besides the U-Boot slot and the ESP;
# a downstream section may name its own list (required:).
REQUIRED = ("xbl.elf", "xbl_config.elf", "tz.mbn", "cdt.bin")


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


def blobs(board_name, stack, dest):
    """The board's pre-ddr blobs, from the downstream boot binaries of
    the stack, into dest; each must be there with its pinned sha256."""
    b = config.board(board_name)
    want = (b.get("spl") or {}).get("pre_ddr", [])
    os.makedirs(dest, exist_ok=True)
    stage = tempfile.mkdtemp(dir=WORK)
    try:
        for bb in config.downstream(b, stack)["bootbinaries"]:
            unzip_top(fetch(bb["url"], bb["sha256"]), stage)
        for blob in want:
            path = os.path.join(stage, blob["file"])
            if not os.path.exists(path):
                raise SystemExit("the downstream boot binaries lack the pre-ddr blob %s" % blob["file"])
            if sha256(path) != blob["sha256"]:
                raise SystemExit("pre-ddr blob %s: sha256 %s, pinned %s" % (
                    blob["file"], sha256(path), blob["sha256"]))
            shutil.copy(path, os.path.join(dest, blob["file"]))
    finally:
        shutil.rmtree(stage)
    return [blob["file"] for blob in want]


def slot(board, stack):
    """The package file the stack's U-Boot image (or FIP) is written as."""
    return board["u-boot"][stack].get("slot", "uefi.elf")


def build(board_name, stack, uefi_image, efi, out):
    b = config.board(board_name)
    s = config.downstream(b, stack)
    dirname = "ubci-%s-%s" % (board_name, stack)
    stage = tempfile.mkdtemp(dir=WORK)
    d = os.path.join(stage, dirname)
    os.makedirs(d)
    try:
        for bb in s["bootbinaries"]:
            unzip_top(fetch(bb["url"], bb["sha256"]), d)
        # The layout comes from qcom-ptool, never from what an archive ships.
        for pat in ("partition_*.xml", "rawprogram*.xml", "patch*.xml", "gpt_*.bin"):
            for f in glob.glob(os.path.join(d, pat)):
                os.remove(f)
        if s.get("xbl_config", "xbl_config.elf") != "xbl_config.elf":
            shutil.copy(os.path.join(d, s["xbl_config"]), os.path.join(d, "xbl_config.elf"))
        if s.get("cdt"):
            with zipfile.ZipFile(fetch(s["cdt"]["url"], s["cdt"]["sha256"])) as z, \
                    open(os.path.join(d, "cdt.bin"), "wb") as f:
                f.write(z.read(s["cdt"]["file"]))
        partitions(s["partitions"], d)
        components = {"downstream": s["release"]}
        deferred = []
        if stack == "open":
            bl2 = b["pins"]["bl2"]
            staged = os.path.join(WORK, "pins", bl2["file"])
            if os.path.exists(staged):
                shutil.copy(fetch(None, bl2["sha256"], bl2["file"]), os.path.join(d, "tz.mbn"))
            else:
                os.remove(os.path.join(d, "tz.mbn"))  # never the downstream QTEE in place of BL2
                deferred.append("tz.mbn")
            components["bl2"] = bl2["fingerprint"]
        first = None
        if stack == "spl":
            first = b["spl"]["slot"]
            shutil.copy(os.path.join(os.path.dirname(uefi_image), "spl.mbn"), os.path.join(d, first))
            components["spl"] = first
        image = slot(b, stack)
        shutil.copy(uefi_image, os.path.join(d, image))
        shutil.copy(efi, os.path.join(d, "efi.bin"))
        for f in list(s.get("required", REQUIRED)) + [image, "efi.bin"]:
            if f not in deferred and not os.path.exists(os.path.join(d, f)):
                raise SystemExit("package lacks %s" % f)
        skipped = skip_missing(d, keep=deferred)
        written = written_images(d)
        for f in (image, "efi.bin", "tz.mbn", first or "tz.mbn"):
            if f not in written:
                raise SystemExit("the %s layout writes no %s" % (board_name, f))
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


def written_images(d):
    """Files the package's rawprogram files write (non-empty filename)."""
    out = set()
    for rp in glob.glob(os.path.join(d, "rawprogram*.xml")):
        out.update(re.findall(r'<program [^>]*?filename="([^"]+)"', open(rp).read()))
    return out


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
    if len(sys.argv) == 5 and sys.argv[1] == "blobs":
        print("\n".join(blobs(*sys.argv[2:5])))
        sys.exit(0)
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    name, skipped = build(*sys.argv[1:6])
    print(json.dumps({"path": name, "not_written": skipped}))
