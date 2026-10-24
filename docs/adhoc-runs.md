# Ad-hoc runs: stacked series

An ad-hoc run tests one or more series from the list, applied in order
onto `main` or `master`, on the boards and stacks chosen, with the same
jobs as the nightly. Its results are compared case by case with the
latest nightly of the same base branch on the same board and stack.

## Starting one

From the Actions tab: workflow **adhoc**, "Run workflow" on `main`, with

| input | value |
|---|---|
| series | Message-IDs or lore links of the cover letters (or of the first patch when there is no cover), space separated, in the order to apply them |
| base | `main` (default) or `master` |
| boards | space separated (`rb3gen2`, `ventuno-q`); empty for both |
| stacks | `stock` and/or `open`; empty for both |
| title | shown on the dashboard (optional) |

or with the GitHub CLI:

    gh workflow run adhoc.yml --ref main \
      -f series="<msgid 1> <msgid 2>" -f base=main -f boards=ventuno-q

Anyone can also ask for a run with the issue form "Ad-hoc run of stacked
series"; it starts when someone with triage rights adds the
`adhoc-approved` label, and the workflow comments on the issue with the
run link (or with why the request is invalid).

The submit job of an ad-hoc run uses the `lava-hw` environment, which
deploys from `main` only, so the workflow on any other branch gets no
hardware.

## What happens

1. `ubci.request` checks the request: every series is a Message-ID or a
   lore / patch.msgid.link URL, the base, boards and stacks are known.
2. `ubci.stack fetch` runs `b4 am` for each series, in order, into
   `s01.mbx`, `s02.mbx`, ... A series whose cover letter names another
   with `prerequisite-message-id` gets that one fetched and placed in
   front of it unless the stack already has it (recorded as
   `added_as_prerequisite_of`). `prerequisite-patch-id` trailers name
   patches, not messages, so they are not fetched; they are checked after
   applying instead.
3. `ubci.stack apply` applies every series with `git am --3way` onto the
   base commit. When a series does not apply, the run stops there: that
   series is recorded with the failing patch (its number, subject and
   git's error), the series after it are marked not tried, and every
   hardware cell is `skipped` with "does not apply: <series> v<N>, patch
   k/N: <subject>". Nothing is built.
4. When the whole stack applies, each declared prerequisite patch id that
   no commit of the applied stack matches (`git patch-id --stable`) is
   listed as `unresolved_prerequisites` of its series. This is
   information, not a failure: the series may build and boot without it.
5. Build, host checks and hardware run as in the nightly on the stacked
   tree. checkpatch checks the stacked commits (from the base commit).

The run document records the exact stack (`run.stack`, see
[results-schema.md](results-schema.md)). The dashboard lists the run under
"Ad-hoc runs": one line per series (title, version, patch count, applied
or the failing patch), then one cell per board and stack with the
fingerprint gate, boots Linux, and the difference from the baseline (new
failures, new passes, the boot verdict against the baseline's).

## Worked example: QCS8300 v4 + VENTUNO Q v2 on VENTUNO Q

The VENTUNO Q needs the QCS8300 clock and pinctrl series under its own
board series. The request:

    gh workflow run adhoc.yml --ref main -f base=main -f boards=ventuno-q \
      -f series="20261021-b4-monaco-v4-0-c90f0c01d312@oss.qualcomm.com 20260928-monaco-ventuno-q-v2-0-0e046c8242be@oss.qualcomm.com" \
      -f title="QCS8300 v4 + VENTUNO Q v2"

Result of the fetch and apply onto `main` at `f97bb5c1ad` (2026-10-24):

| # | series | version | patches | applied |
|---|---|---|---|---|
| 1 | qcom: qcs8300/monaco-evk: pinctrl and RPMH clock | v4 | 5 | yes |
| 2 | qcom: add support for the Arduino VENTUNO Q | v2 | 4 | yes |

The VENTUNO Q v2 cover letter declares seven prerequisite patch ids
(written against QCS8300 v2); four of them match nothing in the stack,
because QCS8300 v4 dropped or reworked those patches (the interconnect and
reboot-mode changes). The run shows them as unresolved prerequisites of
series 2; the stack still applies.

QCS8300 v4 renames `qcom_qcs8300_defconfig` to `qcom_monaco_defconfig`.
Board configs name alternatives for such cases: the VENTUNO Q stock stack
builds `qcom_monaco_defconfig|qcom_qcs8300_defconfig` (the first one the
tree has), and the open stack adds `arduino-ventuno-q.config?` (the
board fragment of VENTUNO Q v2, used when present), so the same board
config serves the nightly and the stacked tree.

## Tests

`tests/test_series.py` (two series stacked in order, a conflict reported
with the failing patch and the later series not tried, a missing
prerequisite, a prerequisite-message-id fetched first, the Message-ID
forms), `tests/test_request.py` (inputs and issue form, invalid ids,
bases, boards and stacks) and `tests/test_run.py` (the stack recorded in
the run, every cell skipped when the stack does not apply).
