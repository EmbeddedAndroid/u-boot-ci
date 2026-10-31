"""scripts/build-open-stack.sh for a board with private pins: nothing is
built or fetched, U-Boot goes in as bl33.bin for the submit job."""
import json
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_private_board_builds_no_tf_a_or_op_tee(tmp_path):
    bl33 = tmp_path / "u-boot.bin"
    bl33.write_bytes(b"U-Boot under test")
    out = tmp_path / "out"
    # No toolchain and an empty work tree: any TF-A or OP-TEE step fails.
    env = dict(os.environ, UBCI_WORK=str(tmp_path / "work"), CROSS_COMPILE="/nonexistent-")
    p = subprocess.run([os.path.join(REPO, "scripts", "build-open-stack.sh"), "sm8750-mtp", str(bl33), "fp-1",
                        str(out)], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    assert (out / "bl33.bin").read_bytes() == b"U-Boot under test"
    meta = json.load(open(out / "open-stack.json"))
    assert meta["private"] is True and meta["image"] == "bl33.bin" and meta["fingerprint"] == "fp-1"
    assert sorted(os.listdir(out)) == ["bl33.bin", "open-stack.json"]
    assert not (tmp_path / "work").exists()
