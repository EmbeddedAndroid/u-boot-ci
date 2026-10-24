# Build and test container for u-boot-ci: the same image runs locally
# (docker compose run ci ...) and on the CI runners (x86_64 or arm64).
#
# It carries the parts of the upstream U-Boot CI image
# (tools/docker/Dockerfile in U-Boot) that the Qualcomm boards need: the
# kernel.org GCC 14.2.0 aarch64 toolchain, buildman, test.py, the Sphinx
# docs stack and QEMU, plus the firmware packaging tools (qcom-ptool,
# ukify with the arm64 systemd-boot stub, mtools) and Buildroot's host
# needs, and the host tools sandbox test.py and the docs build use
# (as upstream installs them).
FROM ubuntu:noble-20251013

ENV DEBIAN_FRONTEND=noninteractive
ARG TCVER=14.2.0

RUN apt-get update && apt-get install -y --no-install-recommends \
	bc bison build-essential bzip2 ca-certificates cpio curl \
	device-tree-compiler dosfstools e2fsprogs file flex gdisk git \
	gnutls-dev kmod libelf-dev libgnutls28-dev libpython3-dev libssl-dev \
	lz4 make mtools openssl patch perl python-is-python3 python3 \
	python3-dev python3-pip python3-venv qemu-system-arm rsync swig \
	systemd-ukify unzip uuid-dev wget xxd xz-utils zstd \
	&& apt-get install -y --no-install-recommends \
	cgpt efitools erofs-utils exfatprogs fdisk fontconfig graphviz \
	imagemagick ipxe-qemu libsdl2-dev lzma-alone lzop mkbootimg mtd-utils \
	parted qemu-utils sbsigntool swtpm swtpm-tools vboot-kernel-utils \
	&& rm -rf /var/lib/apt/lists/*

# kernel.org toolchain, the one upstream U-Boot CI builds aarch64 with.
RUN host=$([ "$(dpkg --print-architecture)" = arm64 ] && echo arm64 || echo x86_64) \
	&& wget -qO- https://mirrors.edge.kernel.org/pub/tools/crosstool/files/bin/$host/${TCVER}/$host-gcc-${TCVER}-nolibc-aarch64-linux.tar.xz \
	| tar -C /opt -xJ
ENV PATH=/opt/gcc-${TCVER}-nolibc/aarch64-linux/bin:$PATH \
	CROSS_COMPILE=aarch64-linux-

# ukify needs the aarch64 systemd-boot stub. An arm64 host installs it;
# noble on amd64 ships only the x86 stub, so take it from the arm64 package
# of the same release.
RUN if [ "$(dpkg --print-architecture)" = arm64 ]; then \
		apt-get update && apt-get install -y --no-install-recommends systemd-boot-efi; \
	else \
		dpkg --add-architecture arm64 \
		&& sed -i 's/^Types: deb$/Types: deb\nArchitectures: amd64/' /etc/apt/sources.list.d/ubuntu.sources \
		&& printf 'Types: deb\nURIs: http://ports.ubuntu.com/ubuntu-ports\nSuites: noble noble-updates\nComponents: main universe\nArchitectures: arm64\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n' \
			> /etc/apt/sources.list.d/ports.sources \
		&& apt-get update && cd /tmp && apt-get download systemd-boot-efi:arm64 \
		&& dpkg-deb -x systemd-boot-efi_*_arm64.deb /tmp/sdboot \
		&& install -D -m 0644 /tmp/sdboot/usr/lib/systemd/boot/efi/linuxaa64.efi.stub \
			/usr/lib/systemd/boot/efi/linuxaa64.efi.stub \
		&& rm -rf /tmp/sdboot /tmp/*.deb; \
	fi \
	&& test -f /usr/lib/systemd/boot/efi/linuxaa64.efi.stub \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
ARG QCOM_PTOOL_REV=c6c8fec1139a83e66f62c5cf05d341cc51db13e4
RUN python3 -m venv /opt/venv \
	&& /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
	&& git clone -q https://github.com/qualcomm-linux/qcom-ptool /opt/qcom-ptool \
	&& git -C /opt/qcom-ptool checkout -q ${QCOM_PTOOL_REV} \
	&& /opt/venv/bin/pip install --no-cache-dir /opt/qcom-ptool \
	&& rm /tmp/requirements.txt
ENV PATH=/opt/venv/bin:$PATH

# test.py board hooks, as upstream CI clones them.
ARG TEST_HOOKS_REV=59437fd1c7a6a84da05efe5cefde47264f78dcbe
RUN git clone -q https://git.u-boot-project.org/u-boot/u-boot-test-hooks /opt/u-boot-test-hooks \
	&& git -C /opt/u-boot-test-hooks checkout -q ${TEST_HOOKS_REV}

# Runs as the invoking user (compose passes UID/GID); HOME must be writable.
ENV HOME=/tmp/home
RUN mkdir -m 1777 /tmp/home && git config --system --add safe.directory '*' \
	&& printf '[toolchain]\nroot = /usr\nkernelorg = /opt/gcc-%s-nolibc/*\n' ${TCVER} > /etc/buildman \
	&& ln -s /etc/buildman /tmp/home/.buildman
WORKDIR /work
