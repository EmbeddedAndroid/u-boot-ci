import pytest

from ubci import request

BODY = """### Series

20261021-b4-monaco-v4-0-c90f0c01d312@oss.qualcomm.com
https://lore.kernel.org/u-boot/20260928-monaco-ventuno-q-v2-0-0e046c8242be@oss.qualcomm.com/

### Base

master

### Boards

ventuno-q

### Stacks

_No response_
"""


def test_issue_form_body():
    r = request.from_issue(BODY)
    assert r["series"] == ("20261021-b4-monaco-v4-0-c90f0c01d312@oss.qualcomm.com "
                           "20260928-monaco-ventuno-q-v2-0-0e046c8242be@oss.qualcomm.com")
    assert r["base"] == "master" and r["targets"] == "ventuno-q:stock,ventuno-q:open"


@pytest.mark.parametrize("series,base,boards,stacks,why", [
    ("", "main", "", "", "no series"),
    ("x@y", "next", "", "", "base"),
    ("x@y", "main", "rb3gen2 nope", "", "unknown board"),
    ("x@y", "main", "", "open; rm -rf /", "unknown stack"),
    ("x@y $(reboot)", "main", "", "", "Message-ID"),
])
def test_bad_requests_are_refused(series, base, boards, stacks, why):
    with pytest.raises(ValueError, match=why):
        request.check(series, base, boards, stacks)


def test_defaults_to_every_board_and_stack():
    assert request.check("x@y", "main", "", "")["targets"] == \
        ",".join("%s:%s" % (b, s) for b in ("lemans-evk", "qcs615-ride", "rb3gen2", "uno-q", "ventuno-q")
                 for s in ("stock", "open"))
