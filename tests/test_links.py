from fwci import links

SHA = "8649a54d301a4d0ac526324c7a7ad2574939ff27"


def test_commit_links_per_host():
    assert links.commit_url("https://git.u-boot-project.org/u-boot/u-boot.git", SHA) == \
        "https://git.u-boot-project.org/u-boot/u-boot/-/commit/" + SHA
    assert links.commit_url("https://github.com/EmbeddedAndroid/arm-trusted-firmware", "f2b3") == \
        "https://github.com/EmbeddedAndroid/arm-trusted-firmware/commit/f2b3"
    assert links.commit_url("https://github.com/OP-TEE/optee_os.git", "ab") == \
        "https://github.com/OP-TEE/optee_os/commit/ab"
    nxt = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    assert links.commit_url(nxt, "20a3") == nxt + "/commit/?id=20a3"
    assert links.tag_url(nxt, "next-20261023") == nxt + "/tag/?h=next-20261023"
    assert links.commit_url("https://review.trustedfirmware.org/TF-A/trusted-firmware-a", "c") == \
        "https://review.trustedfirmware.org/TF-A/trusted-firmware-a/+/c"


def test_file_links_point_at_the_commit():
    assert links.file_url("https://github.com/qualcomm-linux/meta-qcom", "c853", "/recipes-bsp/firmware-boot") == \
        "https://github.com/qualcomm-linux/meta-qcom/tree/c853/recipes-bsp/firmware-boot"
    nxt = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
    assert links.file_url(nxt, "20a3", "arch/arm64/configs/defconfig") == \
        nxt + "/tree/arch/arm64/configs/defconfig?id=20a3"


def test_unknown_host_or_no_commit_gives_no_link():
    assert links.commit_url("https://example.org/x.git", SHA) is None
    assert links.file_url("https://example.org/x.git", SHA, "a") is None
    assert links.commit_url("https://github.com/a/b", None) is None
    assert links.commit_url(None, SHA) is None
    assert links.tag_url("https://example.org/x.git", "t") is None
