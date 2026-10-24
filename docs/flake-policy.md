# Flake policy

A known flake explains a failure; it never hides one. Flaky cases stay
failed on the dashboard and carry a "flake" badge with the entry id.

The bar to get on the list (`config/flakes.yaml`, enforced by
`fwci/flakes.py`):

- the case failed on a base branch (`main` or `master`) with no code change at
  least 3 times within 14 days,
- on at least 2 boards (or 3 runs of a device type the lab has only one
  board of: `single_board_type: true`),
- with a linked issue and a named suspected cause.

An entry lists the qualifying failures (run, date, board) and the date it
was last confirmed; it expires 30 days after that unless re-confirmed.
Entries that do not meet the bar are ignored. Adding, re-confirming or
removing an entry is a pull request reviewed by Tyler.

## Allowlisted kernel errors

The `smoke/dmesg-errors` case fails on any kernel line at level 0-3,
except the lines `config/known-errors.yaml` allowlists. The bar is the
same as for a flake: a pattern seen on a base branch without a code change
at least 3 times in 14 days on at least 2 boards, linked evidence, a named
cause, confirmed within 30 days (`fwci.flakes.active` checks entries of
both lists). Only lines caused by a firmware file the minimal initramfs
does not carry qualify (a driver reporting a missing file, and the probe
that fails because of it); anything else stays a failure. The patterns
are POSIX extended regular expressions matched on the board, without
single quotes.

## Known gaps

A case a board cannot pass for a reason outside U-Boot and outside the
lab's control, documented in its board page, is listed under `known_gaps`
in the board config with the reason. The collector reports such a case as
`skip` with the reason as its note, so it is visible and never counted as
a regression. Example: USB on the RB3 Gen 2 ([boards/rb3gen2.md](boards/rb3gen2.md)).
