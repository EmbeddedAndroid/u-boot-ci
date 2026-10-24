# Adding a board

1. `config/boards/<board>.yaml`, modelled on an existing board:
   - `lava`: device type, storage, LUNs to flash, firehose programmer and
     the XBL line every boot prints (the gates start there);
   - `stock`: the boot binaries and CDT meta-qcom pins for the board (URL
     and sha256 of each archive), the `xbl_config` to use, the qcom-ptool
     layout;
   - `u-boot`: configs, device tree and image for each stack;
   - `linux`: the board DTB, upstream overlays per stack, known gaps,
     command line;
   - `uboot_checks` and `smoke` (storage, USB, network commands, CPU
     count);
   - `restore`: the environment suffix of its stock restore image
     (`STOCK_RESTORE_URL_<SUFFIX>`) and the directory inside that image.
2. For an open stack, its pins in `config/pins.yaml` (TF-A, OP-TEE, a
   signed BL2) and `python3 -m ubci.carry`.
3. Add it to `boards` in `config/project.yaml`, the linux artifact list
   (its DTB and overlays) and the build matrix in
   `.github/workflows/nightly.yml`.
4. `docs/boards/<board>.md`: the stock boot path chosen and why (replace
   UEFI where U-Boot is meant to be the UEFI, chainload from ABL where that
   is the upstream norm), the open stack, known gaps.
5. Run the tests and the dry run, then one job by hand that ends on the
   stock restore before the board goes into the nightly.
