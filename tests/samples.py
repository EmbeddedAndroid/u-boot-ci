"""Small run documents for the tests and the dashboard dry run."""
import copy

BASE = {"repo": "https://git.u-boot-project.org/u-boot/u-boot.git", "branch": "main",
        "commit": "f97bb5c1ad78e95856917b92c7270c82d4b11e21"}
LINUX = {"tag": "next-20261023", "commit": "20a33c6b6cbe7e4805dfb6cd68816937443aa148",
         "release": "7.3.0-next-20261023", "config": "arch/arm64/configs/defconfig",
         "image_sha256": "5" * 64, "modules_sha256": "e" * 64}


def case(name, result, suite="smoke"):
    return {"suite": suite, "name": name, "result": result}


def target(board="rb3gen2", stack="stock", boot="pass", stage="login", cases=None,
           gate="pass", state="done"):
    return {"board": board, "stack": stack, "state": state, "fingerprint": "ubci-1",
            "components": [{"name": "u-boot", "role": "under-test", "commit": BASE["commit"]},
                           {"name": "tf-a", "role": "pinned", "commit": "4930db33",
                            "upstream": {"base": "9599954c", "distance": 2, "carried": [
                                {"commit": "a" * 40, "subject": "feat(x): one", "review": None},
                                {"commit": "b" * 40, "subject": "fix(x): two",
                                 "review": "https://review.trustedfirmware.org/c/TF-A/trusted-firmware-a/+/1"}]}}],
            "lava": {"job_id": 1, "url": "https://lava.example/scheduler/job/1", "device": "d1",
                     "health": "Complete"},
            "fingerprint_gate": gate, "restore": "pass",
            "linux_boot": {"verdict": boot, "stage": stage},
            "cases": cases if cases is not None else [case("usb", "pass"), case("storage", "fail")]}


def run(rid="n1", kind="nightly", created="2026-10-24T01:00:00Z", targets=None):
    return {"schema": "fwci-run/1", "project": "u-boot",
            "run": {"id": rid, "kind": kind, "title": "main f97bb5c1ad78", "created": created,
                    "updated": created, "ci_url": None, "base": dict(BASE), "series": None,
                    "baseline": None},
            "state": "done", "linux": dict(LINUX),
            "host_checks": [{"name": "buildman", "result": "pass", "summary": "ok"}],
            "targets": copy.deepcopy(targets if targets is not None else [target()])}
