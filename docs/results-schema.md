# Results schema (fwci-run/1)

One JSON document per run (`fwci/schema/run.schema.json`, checked with
JSON Schema 2020-12 every time a document is written or the site is
built). The same schema serves u-boot-ci, tf-a-ci and optee-ci.

- `run`: id, kind (`nightly`, `adhoc`, `pin-candidate`, `series`),
  created/updated, CI link, the base (repository, branch, commit) and the
  id of the baseline run it was compared with. An ad-hoc run has
  `stack[]`, the series in the order they were applied: Message-ID, lore
  link, title, version, patch count, `applied` (true, false, or null when
  an earlier series did not apply), `added_as_prerequisite_of` for a
  series fetched because a cover letter named it, `failed_patch` (number,
  subject, git's error) and `unresolved_prerequisites` (prerequisite
  patch ids a cover letter declares that the stack does not carry).
- `state`: `queued`, `building`, `testing`, `done`, or `error` /
  `cancelled` when the workflow failed or was cancelled before the run
  finished (`ubci.run close`; `note` says which). `done`, `error` and
  `cancelled` are final.
- `linux`: the linux-next tag, commit (with `url` and `tag_url`), kernel
  release, config and the sha256 of the Image and modules every board
  booted.
- `host_checks[]`: name, result, summary, log link.
- `targets[]`, one per board and firmware stack:
  - `state` (`queued`, `building`, `flashing`, `testing`, `done`,
    `skipped`, `error`, `cancelled`), `state_detail`, `queue_position`;
  - `fingerprint` and `components[]`, the exact software of the target:
    name, role (`under-test`, `pinned`, `stock` for the downstream
    firmware, `payload` for Linux), `origin` (`upstream`, `downstream`),
    repository, branch, commit with its link (`url`), release,
    fingerprint, sha256. The U-Boot under test has its `configs` (each
    `used` true, false for an optional board fragment the base does not
    have, or null before the build), `device_tree`; the downstream
    firmware its `files` (download link, sha256) and `layers` (meta layer
    commit, links); pinned components `soc_branch`, `pending` while their
    commit is not public, and `upstream`: base, `distance` and the
    `carried` commits with their review links (distance to upstream);
    Linux the linux-next tag and commit, `config` and `dtbs` with links
    at that commit, `dtb_sha256` of the DTB the UKI carries;
  - `boot_chain[]`: every boot stage with its `origin` (`upstream`,
    `downstream`, `none`), the component it links to and a detail;
  - `lava`: job id, link, device, health; `recovery` when a recovery job
    had to restore the board;
  - `fingerprint_gate`: `pass` only when the console showed every
    component with its expected fingerprint;
  - `linux_boot`: the boots-Linux verdict (below);
  - `restore`: the end-of-job lab firmware restore (`pass`, `fail`, `not-run`,
    `recovery-job` while a recovery job runs);
  - `cases[]`: suite, name, result, link to the log line, flake id,
    `note` (for example the known gap that made a case `skip`, or "no
    verdict" for a shell check that never finished) and, for a failed
    shell check, `output`: the console lines it printed (for
    `smoke/dmesg-errors`, the kernel errors left after the allowlist; at
    most 200, the link points at the first);
  - `diff`: `new_fail`, `new_pass`, `still_fail` against the baseline
    (only when both fingerprint gates passed).

## The boots-Linux verdict

`linux_boot.verdict` is `pass` when the login prompt of the pristine
linux-next payload appeared, `fail` when the boot was attempted and did
not get there, `not-run` when the job never reached the Linux handoff.
`stage` says where it stopped, from the console of the first boot
(`fwci/boot_verdict.py`):

| stage | meaning |
|---|---|
| `login` | login prompt reached |
| `nothing-booted` | the bootloader ran its boot command and came back to its prompt: nothing it could boot (no boot device, no bootable image) |
| `no-efi-stub` | the bootloader ran its boot command, no kernel output followed and it never came back |
| `hang-before-console` | the EFI stub printed, the kernel console never came up |
| `early-panic` | a kernel panic, oops or `Internal error` before login |
| `no-login` | the kernel ran, no login prompt |
| `not-reached` | the console never got to the handoff |

`last_lines` holds the console tail (around the panic for `early-panic`)
and `url` links that line in the LAVA log (`#L<index>`, 0-based).
`versus_baseline` compares with the same board and stack of the baseline:
`regression` (the baseline booted, this run did not: for a series, the
series broke Linux boot), `upstream-gap` (the baseline does not boot
either), `fixed`, `same` or `unknown` (no baseline). `gaps` names the
upstream pieces the board is known to lack.
