"""Assemble the qcomflash tarball LAVA flashes for one board and stack.

python3 -m ubci.package <board> <stock|open|spl> <uefi image> <efi.bin> <out.tar.gz>
python3 -m ubci.package insert-bl2 <package.tar.gz> <board>
    adds the board's BL2 from the environment variable named by its pin
    (secret, gzip + base64), checked against the pinned sha256
python3 -m ubci.package insert-private <package.tar.gz> <board>
    completes the open stack of a board with private pins: tz.mbn, and
    the FIP of the private BL31 and OP-TEE around the package's U-Boot,
    wrapped and test-signed ("private" below)
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
  private an open stack whose TF-A and OP-TEE are built from sources the
         CI may not see (Wildcat: tf-a pin `private`): the images are
         pinned by sha256 (docs/private-firmware.md) and only the submit
         job gets them. The package carries the U-Boot under test as
         bl33.bin with tz.mbn and the uefi image deferred; insert-private
         fetches BL2, BL31 and OP-TEE, builds the FIP (ubci.fip), wraps
         and signs it, and drops bl33.bin;
  all    efi <- the ESP with the linux-next UKI.
Partitions whose image the package does not carry (dtb, rootfs, persist,
...) are left unwritten. SOURCES.json lists every file and its sha256.
"""
import base64
import glob
import gzip
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import config, fip
from .fetch import WORK, fetch, sha256

PTOOL = os.environ.get("QCOM_PTOOL_DIR", "/opt/qcom-ptool")
# What every package must carry besides the U-Boot slot and the ESP;
# a downstream section may name its own list (required:).
REQUIRED = ("xbl.elf", "xbl_config.elf", "tz.mbn", "cdt.bin")
# The U-Boot under test in a private open-stack package, until
# insert-private builds the FIP around it; no partition is written from it.
BL33 = "bl33.bin"


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
        image = slot(b, stack)
        if stack == "open" and config.private(b):
            os.remove(os.path.join(d, "tz.mbn"))
            deferred += ["tz.mbn", image]
            shutil.copy(uefi_image, os.path.join(d, BL33))
            components["bl2"] = b["pins"]["bl2"]["fingerprint"]
        elif stack == "open":
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
        if image not in deferred:
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


def rewrite(package, add, drop=()):
    """Add files (name -> bytes) to a package and drop others, keeping
    SOURCES.json true: added files leave "deferred" with their sha256."""
    tmp = package + ".tmp"
    top = None
    with tarfile.open(package) as src, tarfile.open(tmp, "w:gz", compresslevel=6) as dst:
        for m in src.getmembers():
            name = m.name.split("/", 1)[-1]
            if name in drop or name in add:
                continue
            f = src.extractfile(m) if m.isfile() else None
            if name == "SOURCES.json":
                meta = json.load(f)
                meta["deferred"] = [x for x in meta.get("deferred", []) if x not in add]
                for x in drop:
                    meta["files"].pop(x, None)
                for x, data in add.items():
                    meta["files"][x] = hashlib.sha256(data).hexdigest()
                blob = json.dumps(meta, indent=1).encode()
                m.size = len(blob)
                f = io.BytesIO(blob)
                top = m.name.split("/")[0]
            dst.addfile(m, f)
        if top is None:
            raise SystemExit("%s has no SOURCES.json" % package)
        for x, data in sorted(add.items()):
            info = tarfile.TarInfo(top + "/" + x)
            info.size, info.mode = len(data), 0o644
            dst.addfile(info, io.BytesIO(data))
    os.replace(tmp, package)


def member(package, name):
    with tarfile.open(package) as t:
        for m in t.getmembers():
            if m.name.split("/", 1)[-1] == name:
                return t.extractfile(m).read()
    raise SystemExit("%s has no %s" % (package, name))


def insert_bl2(package, board_name, env=os.environ):
    """Add the deferred BL2 to a package from the secret its pin names."""
    bl2 = config.board(board_name)["pins"]["bl2"]
    value = env.get(bl2["secret"])
    if not value:
        raise SystemExit("%s is not set" % bl2["secret"])
    data = gzip.decompress(base64.b64decode(value))
    if hashlib.sha256(data).hexdigest() != bl2["sha256"]:
        raise SystemExit("%s does not match the pinned sha256" % bl2["secret"])
    rewrite(package, {"tz.mbn": data})


GITHUB_API = "https://api.github.com"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def github_get(url, token, accept):
    """url read with the bearer token. GitHub answers an asset with a
    redirect to its file host: that hop is fetched without the token."""
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "Accept": accept,
                                               "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=300) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"):
            raise
        location = urllib.parse.urljoin(url, e.headers["Location"])
    if urllib.parse.urlsplit(location).scheme != urllib.parse.urlsplit(GITHUB_API).scheme:
        raise ValueError("redirect leaves %s" % urllib.parse.urlsplit(GITHUB_API).scheme)
    with urllib.request.urlopen(urllib.request.Request(location), timeout=300) as r:
        return r.read()


def private_file(pin, env=os.environ, store=None):
    """A private pin's image: staged in $UBCI_WORK/pins, or the asset
    <file> of the release <release> of the private store (a private GitHub
    repository, pins.yaml private_store) read with $UBCI_PRIVATE_TOKEN;
    either way checked against the pinned sha256."""
    if os.path.exists(os.path.join(WORK, "pins", pin["file"])):
        return open(fetch(None, pin["sha256"], pin["file"]), "rb").read()
    token = env.get("UBCI_PRIVATE_TOKEN", "").strip()
    if not token:
        raise SystemExit("%s is not staged and UBCI_PRIVATE_TOKEN is not set" % pin["file"])
    store = store or yaml_pins()["private_store"]
    try:
        release = json.loads(github_get("%s/repos/%s/releases/tags/%s" % (GITHUB_API, store, pin["release"]),
                                        token, "application/vnd.github+json"))
        url = [a["url"] for a in release.get("assets", []) if a.get("name") == pin["file"]]
        if not url:
            raise SystemExit("%s: not in release %s of the private store" % (pin["file"], pin["release"]))
        # The token goes to the API only, whatever the release says.
        if not url[0].startswith(GITHUB_API + "/"):
            raise ValueError("asset URL outside the API")
        data = github_get(url[0], token, "application/octet-stream")
    except (OSError, ValueError, KeyError, http.client.HTTPException) as e:
        # Other errors can quote a URL or the header, and the reason is
        # published: only an HTTP status is said as is.
        if isinstance(e, urllib.error.HTTPError):
            why = "HTTP Error %d" % e.code
        else:
            why = type(e).__name__
            # The job log masks the token.
            print("private store: %r" % e, file=sys.stderr)
        raise SystemExit("%s: cannot be read from the private store (%s)" % (pin["file"], why))
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise SystemExit("%s does not match the pinned sha256" % pin["file"])
    return data


def qtestsign(elf, args):
    """elf signed by the pinned qtestsign (args: its version and image type)."""
    top = yaml_pins()["qtestsign"]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tree = subprocess.run([os.path.join(here, "scripts", "checkout.sh"), "qtestsign", top["repo"], top["commit"]],
                          check=True, capture_output=True, text=True).stdout.strip()
    work = tempfile.mkdtemp(dir=WORK)
    try:
        src, out = os.path.join(work, "in.elf"), os.path.join(work, "out.elf")
        open(src, "wb").write(elf)
        subprocess.run([sys.executable, os.path.join(tree, "qtestsign.py")] + list(args) + ["-o", out, src],
                       check=True, stdout=subprocess.DEVNULL)
        return open(out, "rb").read()
    finally:
        shutil.rmtree(work)


def yaml_pins():
    import yaml
    return yaml.safe_load(open(os.path.join(config.CONFIG, "pins.yaml")))


def insert_private(package, board_name, env=os.environ, sign=qtestsign):
    """Complete a private open-stack package: tz.mbn and the signed FIP
    of the private BL31 and OP-TEE around the package's bl33.bin."""
    b = config.board(board_name)
    p = b["pins"]
    tz, bl31, bl32 = (private_file(p[n], env) for n in ("bl2", "tf-a", "optee"))
    image = fip.build({"bl31": bl31, "bl32": bl32, "bl33": member(package, BL33)})
    signed = sign(fip.elf(image, int(p["tf-a"]["fip_load_addr"], 16)), p["tf-a"]["sign"])
    rewrite(package, {"tz.mbn": tz, slot(b, "open"): signed}, drop=(BL33,))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "insert-bl2":
        insert_bl2(sys.argv[2], sys.argv[3])
        sys.exit(0)
    if len(sys.argv) == 4 and sys.argv[1] == "insert-private":
        insert_private(sys.argv[2], sys.argv[3])
        sys.exit(0)
    if len(sys.argv) == 5 and sys.argv[1] == "blobs":
        print("\n".join(blobs(*sys.argv[2:5])))
        sys.exit(0)
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    name, skipped = build(*sys.argv[1:6])
    print(json.dumps({"path": name, "not_written": skipped}))
