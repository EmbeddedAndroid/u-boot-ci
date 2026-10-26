# How pins are updated

Everything the hardware runs besides the U-Boot under test is pinned:
the downstream firmware per board (`config/boards/<board>.yaml`,
`downstream`), the
open stack per board (`config/pins.yaml`), the Linux payload by policy
(newest linux-next tag, rebuilt when the tag moves) and the tools (in
`docker/`). A pin only changes through a pull request that Tyler reviews
and merges.

## Downstream firmware: the pin watcher

`.github/workflows/pin-watch.yml` runs daily (06:41 UTC) on a small CIL
runner with only the workflow token (contents and pull-requests write).
For each board it:

1. clones the meta layers named in `downstream.upstream.layers`
   (meta-qcom; meta-qcom-arduino too for VENTUNO Q and UNO Q);
2. reads the recipes named there (`bootbinaries.recipe`, the newest
   version matching the glob, and `cdt.recipe` where the board has one),
   expanding `PV`, the
   artifactory variables and the includes, into the release name, the
   URLs and the sha256 of every archive (`fwci/bitbake.py`, which handles
   plain assignments, `require`/`include` and `${VAR}` only; anything else
   is an error for that board, not a guess);
3. compares them with the pin; when they differ, downloads every new
   archive and checks its sha256 against the recipe (a mismatch is an
   error and opens no PR);
4. commits the bumped board config, with the layer commits it was read
   at in `downstream.source`, to `pin/stock-<board>` and opens a pull
   request for it, or updates the open one: there is never more than one
   per board, and a bump a reviewer closed unmerged is not opened again
   (a bump with a different pin table, release or any sha256, is). Its
   body names the meta layer commit(s);
5. dispatches the validation below for that branch when the bump changed
   or the PR is new (pushes made with the workflow token start no
   workflow runs by themselves).

A board whose recipe cannot be read fails the workflow run with the reason
in its log and gets no PR. `downstream_open` (UNO Q's open-stack boot
firmware) is pinned by hand.

## Validation of a downstream pin PR

`.github/workflows/pin-candidate.yml` runs for that branch (dispatched by
the watcher, or on a push to the PR): it builds the
nightly's U-Boot `main` for the board's downstream stack twice, with the
current pin (from `main`) and with the candidate (the PR), and once Tyler approves the
`lava-pr` deployment of its submit job (it runs PR-branch code with the
LAVA token), runs both LAVA jobs (one after the other on that device type) and publishes the
results as a `pin-candidate` run. The dashboard's "Pin-candidate runs"
section shows both side by side (fingerprint gate, boots Linux, cases),
and the workflow posts the same table as a PR comment. Merging stays with
the reviewer.

## Open stack

TF-A and OP-TEE pins move by hand for now: bump `config/pins.yaml`, sign
a new BL2 when TF-A changes (and replace its `PIN_BL2_<BOARD>` secret in
both environments, [setup.md](setup.md); the sha256 in `pins.yaml` is what
the submit job checks it against), run `python3 -m ubci.carry` to refresh the
carried patches, open the PR. A pin marked `pending` (UNO Q and QCS615 Ride
pin the hardware-gated `qcom/integration` snapshot of 2026-10-24/25, not
pushed) moves, with the `pending` line dropped, to
the pushed `qcom/integration` head of the EmbeddedAndroid forks, the
platform branch recorded in `soc_branch`; RB3 Gen 2 and VENTUNO Q move to
the same branch in the same kind of PR. The watcher is generic (`fwci/pinwatch.py`:
compare, verify, one PR per pin branch), so an open-stack watcher of the
upstream tips is a new reader plus the same calls.

## Linux and tools

The nightly always takes the newest linux-next tag, so there is nothing to
bump; the tag and the kernel's sha256 are recorded in every run. The
toolchain and test tools change with `docker/` (pinned versions and
commits), also by PR.
