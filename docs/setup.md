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
| `PIN_BL2_RB3GEN2` | the open-stack tz image (`tz.mbn`) of RB3 Gen 2: `gzip -9 < tz-rb3gen2.mbn \| base64 -w0` |
| `PIN_BL2_VENTUNO_Q`, `_UNO_Q`, `_QCS615_RIDE`, `_LEMANS_EVK` | the same for the other boards (Lemans: its U-Boot SPL) |

`lava-hw` also holds the read token of the private store of the Wildcat
boards' TF-A and OP-TEE images, the release assets of the private
repository EmbeddedAndroid/ubci-private-firmware
([private-firmware.md](private-firmware.md)); `lava-pr` does not need it
(pin candidates validate the stock stack):

| secret | content |
|---|---|
| `UBCI_PRIVATE_TOKEN` | a fine-grained personal access token that can read that one repository's contents and nothing else |

To create it:

1. GitHub, Settings, Developer settings, Personal access tokens,
   Fine-grained tokens, Generate new token, as the owner of the store
   (EmbeddedAndroid).
2. Name `ubci-private-firmware-read`, an expiration (a year at most; the
   cells skip with "HTTP Error 401" once it lapses), resource owner
   EmbeddedAndroid.
3. Repository access: Only select repositories,
   `EmbeddedAndroid/ubci-private-firmware`.
4. Repository permissions: Contents, Read-only (Metadata, Read-only is
   added by GitHub). No other permission, no account permission.
5. Generate, then in u-boot-ci: Settings, Environments, `lava-hw`, Add
   environment secret `UBCI_PRIVATE_TOKEN` with the token as its value,
   or from a shell (it prompts for the value, so the token stays out of
   the shell history):

       gh secret set UBCI_PRIVATE_TOKEN --env lava-hw --repo EmbeddedAndroid/u-boot-ci

6. Check it without printing it, from a u-boot-ci checkout (or the
   control container): with nothing staged, `ubci.package` reads every
   private image from the store and checks its sha256:

       read -rs UBCI_PRIVATE_TOKEN; export UBCI_PRIVATE_TOKEN
       UBCI_WORK=$(mktemp -d) python3 -c 'from ubci import config, package
       for b, p in config.pins().items():
           for n in ("bl2", "tf-a", "optee"):
               if (p.get(n) or {}).get("private"):
                   package.private_file(p[n]); print(b, n, "ok")'

Without `LAVA_TOKEN` a run does its host checks and marks hardware
`skipped`; without `UBCI_PRIVATE_TOKEN` the private boards' open stacks
are `skipped` with "private firmware not available".

The jobs no longer restore the lab's image at the end (every job flashes
its whole package, [architecture.md](architecture.md)), so the
`STOCK_RESTORE_URL_*` secrets and the `STOCK_RESTORE_TOKEN` and
`STOCK_RESTORE_HEADER` variables are not read by anything and can be
deleted.

The BL2 images are not redistributable and are not published anywhere:
the build jobs leave `tz.mbn` out of the open-stack packages, and the
submit job adds it from the secret after checking it against the sha256
pinned in `config/pins.yaml`. A missing or mismatching secret skips that
target with "BL2 pin not available". The dashboard shows the sha256 only.
(A LAVA artifact would have served too, but the LAVA artifact store keeps
uploads for at most 6 hours.)

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
packages are uploaded there for the length of a run). The runs never use the
production boards: `config/project.yaml` `lava.exclude_devices` keeps
them out of the device choice, and every job is pinned to the device it
was chosen for.
