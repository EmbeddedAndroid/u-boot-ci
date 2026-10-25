import json

import pytest

from fwci import lava_mcp

# The tool error of nightly 40152748187 (master/submit log).
REFUSED = ("Error executing tool submit_job: POST https://lava.infra.foundries.io/api/v0.3/jobs/ "
           "-> HTTP 400: {\"message\":\"Problem with submitted job data: You do not have "
           "permission to submit jobs to device 'rb3g2-02'.\"}")


class Fake(lava_mcp.Lava):
    def __init__(self, text):
        super().__init__(url="http://mcp.example", token="t")
        self._sid = "s"
        self.text = text

    def _rpc(self, body):
        return {"result": {"isError": True, "content": [{"type": "text", "text": self.text}]}}


def test_a_client_error_is_a_rejection_with_lavas_whole_message():
    with pytest.raises(lava_mcp.Rejected) as e:
        Fake(REFUSED).call("submit_job", definition="x")
    assert e.value.status == 400
    assert e.value.message == ("Problem with submitted job data: You do not have permission "
                               "to submit jobs to device 'rb3g2-02'.")


def test_a_body_that_is_not_json_is_kept_as_text():
    with pytest.raises(lava_mcp.Rejected) as e:
        Fake("POST https://l/api/v0.3/jobs/ -> HTTP 403: Forbidden").call("submit_job")
    assert e.value.status == 403 and e.value.message == "Forbidden"


@pytest.mark.parametrize("status", [408, 429, 500, 502])
def test_a_timeout_or_server_error_is_not_a_rejection(status):
    text = "POST https://l/api/v0.3/jobs/ -> HTTP %d: %s" % (status, json.dumps({"message": "m"}))
    with pytest.raises(RuntimeError) as e:
        Fake(text).call("submit_job")
    assert not isinstance(e.value, lava_mcp.Rejected)


def test_an_error_without_an_http_status_is_not_a_rejection():
    with pytest.raises(RuntimeError) as e:
        Fake("Error executing tool submit_job: connection reset").call("submit_job")
    assert not isinstance(e.value, lava_mcp.Rejected)
    assert "connection reset" in str(e.value)
