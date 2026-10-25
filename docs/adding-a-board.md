# Adding a board

1. `config/boards/<board>.yaml`, modelled on an existing board:
   - `lava`: device type, storage, LUNs to flash, firehose programmer and
     the XBL line every boot prints (the gates start there);
   - `downstream`: the boot binaries and CDT the board's meta layer pins
     (URL and sha256 of each archive; no `cdt` when the board's CDT is not
     rewritten), the `xbl_config` to use, the qcom-ptool layout, the
     images every package must carry (`required`, default xbl, xbl_config,
     tz, cdt), the layer commit the pin was read at (`source`) and the
     recipes the pin watcher follows (`upstream`); `downstream_open` when
     the open stack needs other boot firmware;
   - `u-boot`: configs (`a|b` for a defconfig a series renames, `x?` for
     a board fragment a series adds), device tree, image and, when it is
     not `uefi.elf`, the package file it is written as (`slot`;
     `bootimg` for an Android boot image ABL chainloads);
   - `boot_chain`: every boot stage per stack, `upstream`, `downstream`
     or `none`;
   - `linux`: the board DTB, upstream overlays per stack, known gaps,
     command line;
   - `uboot_checks` and `smoke` (storage, USB, network commands, CPU
     count).

   The package must write every partition the boot chain reads: no job
   restores the lab's image afterwards, so the next job sees only what
   its own package flashed (anything the package leaves out, like the
   Lemans SAIL NOR, is whatever the lab last wrote).
2. For an open stack, its pins in `config/pins.yaml` (TF-A, OP-TEE, the
   signed tz image), `python3 -m ubci.carry`, and its `PIN_BL2_<BOARD>`
   secret in both environments, in
   `scripts/in-container.sh` and in the `submit` jobs of `run.yml` and
   `pin-candidate.yml` ([setup.md](setup.md)).
3. Add it to `boards` in `config/project.yaml` (the `ci` job builds every
   board and stack of the run document) and its DTB and overlays to the
   `<base>-linux` artifact of the `ci` job in `.github/workflows/run.yml`.
4. `docs/boards/<board>.md`: the downstream boot path chosen and why
   (replace UEFI where U-Boot is meant to be the UEFI, chainload from ABL
   where that is the upstream norm), each source, the open stack, known
   gaps.
5. Run the tests and the dry run, validate the rendered jobs with LAVA,
   then one job by hand before the board goes into the nightly.
