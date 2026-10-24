"""fwci is shared with tf-a-ci and optee-ci: it must not import ubci."""
import pathlib
import re

FWCI = pathlib.Path(__file__).resolve().parent.parent / "fwci"


def test_fwci_does_not_import_the_u_boot_project():
    for f in FWCI.glob("*.py"):
        text = f.read_text()
        assert not re.search(r"^\s*(from|import)\s+ubci", text, re.M), f
