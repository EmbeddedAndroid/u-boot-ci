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


@pytest.mark.parametrize("job", ["prepare", "submit", "finalize"])
def test_prepare_and_submit_run_their_commands_in_the_control_image(job):
    j = yaml.safe_load(open(os.path.join(REPO, ".github", "workflows", "run.yml")))["jobs"][job]
    assert j["env"]["UBCI_IMAGE"] == "u-boot-ci-control:1"
    builds = [line.strip() for s in j["steps"] for line in s.get("run", "").splitlines()
              if "docker build" in line]
    assert builds == ['docker build --network host -q --target control -t "$UBCI_IMAGE" docker']
    assert '"${UBCI_IMAGE:-u-boot-ci:1}"' in open(os.path.join(REPO, "scripts", "in-container.sh")).read()


def forwarded():
    return set(re.findall(r"-e ([A-Z_0-9]+)\b", open(os.path.join(REPO, "scripts", "in-container.sh")).read()))


def secret_env():
    """(workflow, job, variable) for every variable a job that runs its
    commands through in-container.sh takes from a secret or a variable."""
    import glob
    for wf in sorted(glob.glob(os.path.join(REPO, ".github", "workflows", "*.yml"))):
        for n, j in (yaml.safe_load(open(wf))["jobs"] or {}).items():
            if "$CI_RUN" not in yaml.safe_dump(j):
                continue
            env = dict(j.get("env") or {})
            for s in j.get("steps", []):
                env.update(s.get("env") or {})
            for k, v in env.items():
                if re.search(r"\$\{\{\s*(secrets|vars)\.", str(v)):
                    yield os.path.basename(wf), n, k


def test_every_secret_a_job_holds_reaches_the_container():
    # docker run passes no variable it is not told to: a secret left out
    # is empty inside, e.g. the BL2 pins (open stack "PIN_BL2_* is not set").
    held = list(secret_env())
    assert {k for _, _, k in held} >= {"LAVA_TOKEN", "PIN_BL2_RB3GEN2", "PIN_BL2_VENTUNO_Q"}
    missing = [h for h in held if h[2] not in forwarded()]
    assert not missing, missing


def test_every_bl2_pin_secret_reaches_the_container():
    pins_yaml = yaml.safe_load(open(os.path.join(REPO, "config", "pins.yaml")))
    names = set(re.findall(r"secret: (PIN_BL2_[A-Z_0-9]+)", yaml.safe_dump(pins_yaml)))
    assert names and names <= forwarded(), names
