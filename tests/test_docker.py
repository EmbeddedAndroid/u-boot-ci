"""The two images of docker/Dockerfile: the control image (prepare and
submit, on small arm64 runners) carries the same pins as the CI image and
what those jobs run."""
import os
import re

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pins(name):
    out = {}
    for line in open(os.path.join(REPO, "docker", name)):
        line = line.split("#")[0].strip()
        if line:
            k, v = line.split("==")
            out[k.lower()] = v
    return out


def test_control_pins_match_the_ci_image():
    control, full = pins("requirements-control.txt"), pins("requirements.txt")
    assert control and all(full.get(k) == v for k, v in control.items()), control


def test_control_is_a_stage_and_the_ci_image_the_default():
    froms = re.findall(r"^FROM (\S+)(?: AS (\S+))?$", open(os.path.join(REPO, "docker", "Dockerfile")).read(), re.M)
    assert froms[0][1] == "control"
    # docker build without --target builds the last stage: the CI image.
    assert froms[-1][1] == ""


def test_control_has_what_submit_needs():
    # fwci.lava_mcp uploads packages with curl.
    text = open(os.path.join(REPO, "docker", "Dockerfile")).read()
    control = text[:text.index("\nFROM ", text.index("AS control"))]
    apt = re.search(r"apt-get install -y --no-install-recommends \\\n\t(.*) \\\n", control).group(1).split()
    for tool in ("curl", "git", "python3"):
        assert tool in apt, (tool, apt)


@pytest.mark.parametrize("job", ["prepare", "submit"])
def test_prepare_and_submit_run_their_commands_in_the_control_image(job):
    j = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "run.yml")))["jobs"][job]
    assert j["env"]["UBCI_IMAGE"] == "u-boot-ci-control:1"
    builds = [line.strip() for s in j["steps"] for line in s.get("run", "").splitlines()
              if "docker build" in line]
    assert builds == ['docker build --network host -q --target control -t "$UBCI_IMAGE" docker']
    assert '"${UBCI_IMAGE:-u-boot-ci:1}"' in open(os.path.join(REPO, "scripts", "in-container.sh")).read()
