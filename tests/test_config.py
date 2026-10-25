"""ubci.config: the downstream firmware a stack is built on."""
import copy

from ubci import config


def test_open_stack_on_its_own_downstream_firmware():
    b = copy.deepcopy(config.board("rb3gen2"))
    assert config.downstream(b, "open") is b["downstream"]
    b["downstream_open"] = {"release": "other"}
    assert config.downstream(b, "stock") is b["downstream"]
    assert config.downstream(b, "open") is b["downstream_open"]
