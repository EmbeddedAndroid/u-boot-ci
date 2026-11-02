"""fwci/lava_boottime is a byte copy of lava-boottime's parser
(scripts/vendor-boottime.sh): changes go to lava-boottime and are
vendored again, never made here."""
import hashlib
import json
import pathlib

from fwci.lava_boottime import parser

DIR = pathlib.Path(__file__).resolve().parent.parent / "fwci" / "lava_boottime"


def test_vendored_files_match_the_manifest():
    vendor = json.loads((DIR / "VENDOR.json").read_text())
    assert len(vendor["commit"]) == 40
    for name, sha in vendor["files"].items():
        assert hashlib.sha256((DIR / name).read_bytes()).hexdigest() == sha, name


def test_nothing_but_the_vendored_files():
    vendor = json.loads((DIR / "VENDOR.json").read_text())
    have = {str(p.relative_to(DIR)) for p in DIR.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}
    assert have == set(vendor["files"]) | {"__init__.py", "VENDOR.json"}


def test_platform_files_load():
    assert "xbl" in parser.LOADERS
    assert parser.STAGE_ORDER[0] == "loader" and parser.STAGE_ORDER[-1] == "login"
