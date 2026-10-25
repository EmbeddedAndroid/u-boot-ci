# GitHub and lab setup

What the workflows expect from the repository settings. No secret is set
at repository level: every secret lives in one of two environments, and
only the job that submits to LAVA declares one.

## Environments

| environment | deployment branches | reviewers | used by |
|---|---|---|---|
| `lava-hw` | `main` only | none | `submit` of `run.yml`: the nightly (`main` and `master`) and ad-hoc runs (`adhoc.yml`, `adhoc-issue.yml`) |
| `lava-pr` | any | Tyler (required) | `submit` of `pin-candidate.yml`, the one job that runs code from a PR branch with LAVA access |

A job waiting on `lava-pr` shows "Waiting for review" in the run; nothing
touches the lab until it is approved (pin bumps, docs/pins.md).

Both environments hold the same secrets:

| secret | content |
|---|---|
| `LAVA_TOKEN` | the LAVA token of the CI user `robotyler` |
| `STOCK_RESTORE_URL_RB3GEN2` | the lab image (its downstream firmware) an RB3 Gen 2 job restores at the end |
| `STOCK_RESTORE_URL_VENTUNO_Q`, `_UNO_Q`, `_QCS615_RIDE`, `_LEMANS_EVK` | the same for VENTUNO Q, UNO Q, QCS615 Ride and Lemans EVK |
| `PIN_BL2_RB3GEN2` | the open-stack tz image (`tz.mbn`) of RB3 Gen 2: `gzip -9 < tz-rb3gen2.mbn \| base64 -w0` |
| `PIN_BL2_VENTUNO_Q`, `_UNO_Q`, `_QCS615_RIDE`, `_LEMANS_EVK` | the same for the other boards (Lemans: its U-Boot SPL) |

The names keep `STOCK_` from before the downstream rename: they are
secret names in both environments, and renaming them means setting them
again.

The restore URLs are secrets, so they never appear in a log, the run
documents or the dashboard; the jobs read them from the environment and
put them only in the LAVA job definition. Without `LAVA_TOKEN` a run
does its host checks and marks hardware `skipped`.

The BL2 images are not redistributable and are not published anywhere:
the build jobs leave `tz.mbn` out of the open-stack packages, and the
submit job adds it from the secret after checking it against the sha256
pinned in `config/pins.yaml`. A missing or mismatching secret skips that
target with "BL2 pin not available". The dashboard shows the sha256 only.
(A LAVA artifact would have served too, but the LAVA artifact store keeps
uploads for at most 6 hours.)

## Variables (repository level)

| variable | value |
|---|---|
| `STOCK_RESTORE_TOKEN` | `Q_QLI_S3_TOKEN`: the name of the LAVA remote artifact token that authorizes the restore images (a name, not the secret) |
| `STOCK_RESTORE_HEADER` | `QLIAuthorization`: the header it goes in |

## Actions permissions

- Workflow permissions: read repository contents by default; every job
  that writes declares it (`contents: write` to push the `gh-pages`
  dashboard data or the pin branches, `pull-requests: write` to open or
  comment on the pin PRs, `issues: write` to answer an ad-hoc request,
  `actions: write` to dispatch `pin-candidate`).
- "Allow GitHub Actions to create and approve pull requests" is on: the
  pin watcher opens its PRs with the workflow token (bot identity
  `u-boot-ci`).
- Labels: `adhoc-run` (set by the issue form) and `adhoc-approved` (added
  by someone with triage rights to start a requested run).

## Not set up yet

- Pages: source "Deploy from a branch", branch `gh-pages`, folder `/`.
  Until then the dashboard data is on the `gh-pages` branch only.
- The CIL bridge concurrency cap of this repository. A run holds one CIL
  runner at a time (ad-hoc request, `prepare`, `ci`, `submit`), so the
  nightly holds two (one per branch); 4 covers the nightly and an ad-hoc
  run side by side. Only `ci` is a xeon lease. The arm64 pool takes two
  leases at a time, and a `submit` holds its lease while LAVA runs (up to
  6 h): while both nightly submits run, an ad-hoc run waits for an arm64
  slot before it starts.

## The LAVA user

`robotyler` needs submit rights on `qcs6490-rb3gen2`,
`monaco-arduino-monza`, `qrb2210-arduino-imola`, `qcs615-ride` and
`lemans-evk`, the artifact store of the LAVA MCP endpoint (the
packages are uploaded there for the length of a run) and the remote
artifact token named by `STOCK_RESTORE_TOKEN`. The runs never use the
production boards: `config/project.yaml` `lava.exclude_devices` keeps
them out of the device choice, and every job is pinned to the device it
was chosen for.
