# Adding a board

1. `config/boards/<board>.yaml`, modelled on an existing board:
   - `lava`: device type, storage, LUNs to flash, firehose programmer and
     the XBL line every boot prints (the gates start there);
   - `downstream`: the boot binaries and CDT the board's meta layer pins
     (URL and sha256 of each archive; no `cdt` when the board's CDT is not
     rewritten), the `xbl_config` to use, the qcom-ptool layout, the
     images every package must carry (`required`, default xbl, xbl_config,
     tz, cdt) and the recipes the pin watcher follows (`upstream`);
     `downstream_open` when the open stack needs other boot firmware;
   - `u-boot`: configs, device tree, image and, when it is not
     `uefi.elf`, the package file it is written as (`slot`; `bootimg` for
     an Android boot image ABL chainloads);
   - `linux`: the board DTB, upstream overlays per stack, known gaps,
     command line;
   - `uboot_checks` and `smoke` (storage, USB, network commands, CPU
     count);
   - `restore`: the environment suffix of its stock restore image
     (`STOCK_RESTORE_URL_<SUFFIX>`), the directory inside that image and,
     from a proven restore on the device type, the exact UEFI build it
     prints (`uefi_ver`), the line the check ends on (`end`), its LUNs and
     storage when they differ, and images flashed first (`pre`).
2. For an open stack, its pins in `config/pins.yaml` (TF-A, OP-TEE, a
   signed BL2) and `python3 -m ubci.carry`.
3. Add it to `boards` in `config/project.yaml` (the `ci` job builds every
   board and stack of the run document) and its DTB and overlays to the
   `<base>-linux` artifact of the `ci` job in `.github/workflows/run.yml`.
4. `docs/boards/<board>.md`: the stock boot path chosen and why (replace
   UEFI where U-Boot is meant to be the UEFI, chainload from ABL where that
   is the upstream norm), the open stack, known gaps.
5. Run the tests and the dry run, then one job by hand that ends on the
   stock restore before the board goes into the nightly.
