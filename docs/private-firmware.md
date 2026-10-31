# Private open-stack firmware (Wildcat boards)

The Wildcat platforms (SM8750 MTP, Kaanapali MTP, and later Glymur,
Hamoa/Purwa, Mahua, Nord) boot an open stack whose TF-A and OP-TEE are
built from an internal `qcom/integration` tree. This repository and its
runners may not see those sources, yet U-Boot `main` should be tested on
these boards like on every other one.

## The choice

Two ways were weighed:

1. A private lane: a runner with internal access builds TF-A and OP-TEE
   from source and runs the jobs, publishing only results.
2. Prebuilt images: the internal build is done once, gated on hardware,
   and its images are pinned by sha256 and fingerprint, like the
   pre-signed BL2s of the public boards; CI never needs the sources.

The second fits the security split of [architecture.md](architecture.md).
The one job that builds untrusted code (`ci`) holds no secret and must
not: a runner with internal access that also builds list patches would
hand those patches the internal sources. Prebuilt images instead go
where secrets already go, the `submit` job, which builds nothing from the
tree under test and only moves bytes. The pins also change only by a
reviewed PR, so a run always says exactly which internal build it used.
The cost is that a Wildcat TF-A or OP-TEE change reaches CI only when its
images are re-pinned, which is how the integration gate already works.

## How a run uses them

A board is private when its `tf-a` pin has `private:` (what the images
were built from, shown on the dashboard instead of a link); `release` is
the release of the private store that holds `file`:

```yaml
sm8750-mtp:
  tf-a:   {private: ..., release: qcom-integration-20261031, file: bl31-sm8750-mtp.bin,
           sha256: ..., fingerprint: ..., fip_load_addr: "0xa7000000", sign: [-v7, uefi]}
  bl2:    {private: ..., origin: downstream, release: ..., file: tz-sm8750-mtp.mbn, sha256: ..., fingerprint: ...}
  optee:  {private: ..., release: ..., file: tee-sm8750-mtp.bin, sha256: ..., fingerprint: ...}
```

1. `ci` builds U-Boot, the ESP and the package as for any open stack, but
   no TF-A or OP-TEE (`scripts/build-open-stack.sh`): the package carries
   the U-Boot under test as `bl33.bin`, with `tz.mbn` and the uefi image
   deferred in `SOURCES.json`.
2. `submit` (`ubci.package insert-private`, called by `ubci.run submit`)
   fetches the three images, checks each sha256, builds the FIP of BL31,
   OP-TEE and that `bl33.bin` (`ubci/fip.py`: fiptool's layout), wraps it
   in the ELF XBL loads at `fip_load_addr` and test-signs it with the
   pinned qtestsign (`sign` arguments), then writes `tz.mbn` and the
   uefi image into the package and drops `bl33.bin`. It runs only the
   pinned tools, never code from the tree under test. `ubci/fip.py`
   reproduces the internal build's own fiptool + ld + qtestsign output
   byte for byte.
3. The fingerprint gate expects each private image's own fingerprint on
   BL2, BL31 and OP-TEE, and the run's on U-Boot.
4. If the images cannot be had (no token, a missing asset, a sha256
   mismatch) or the FIP cannot be built (for example a failed
   qtestsign clone), the target is `skipped` with "private firmware not
   available: ..." and nothing is sent to LAVA. The reason is public: it
   never quotes a URL or the token (an HTTP status or the error type at
   most). When the store cannot be reached, the submit job's log has the
   error itself, with the token masked.

The images come from `$UBCI_WORK/pins/<file>` when staged there (local
runs), otherwise from the private store: the release assets of the
private GitHub repository `private_store` in `config/pins.yaml`
(EmbeddedAndroid/ubci-private-firmware), read through the GitHub API
with `Authorization: Bearer $UBCI_PRIVATE_TOKEN`, a read-only token of
that repository and a secret of the `lava-hw` environment
([setup.md](setup.md)). The submit job looks the asset up by name in the
pinned release, then asks for it with `Accept: application/octet-stream`;
GitHub answers with a redirect to its file host, which is followed
without the token. The token is only ever sent to `api.github.com`.

## What is public

The LAVA jobs stay public like every other job: their console shows the
fingerprints (the images are built with the fingerprint as their version
string, so no internal commit is printed). The package itself is not
public: it lives in the LAVA artifact store, which serves it only with
an artifact token, and the job definition names that token but does not
hold its value (the pre-signed BL2s travel the same way). The dashboard
names the internal build (`private`), its sha256 and fingerprint, and
marks those stages downstream in the boot chain.

## Bumping

Build the internal integration with a fresh fingerprint, gate it on the
boards, then upload the images (`tz.mbn`; BL31 and OP-TEE out of its FIP,
`python3 -m ubci.fip unpack fip.bin <dir>`) as the assets of a new
release of the store, with each sha256 in the release notes:

    gh release create <tag> --repo EmbeddedAndroid/ubci-private-firmware \
        --notes-file notes.md tz-<board>.mbn bl31-<board>.bin tee-<board>.bin

and open a PR with the new `release`, `sha256` and `fingerprint` of each
pin. A release is never edited once pinned: a new build is a new
release. The images are never committed to this repository.
