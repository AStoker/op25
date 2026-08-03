#!/bin/bash
#
# One-shot deployment of the W1JPI op25 fork (PA3FWM NBFM noise squelch)
# on a Ubuntu 22.04 / 24.04 host.  Installs GNU Radio 3.10 and build
# dependencies, builds and installs op25, then runs the squelch self-tests.
#
#     sudo ./deploy.sh
#
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "error: run as root (sudo ./deploy.sh)" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
APPS="$REPO/op25/gr-op25_repeater/apps"
if [ ! -d "$REPO/op25/gr-op25_repeater" ]; then
    echo "error: op25 tree not found above $SCRIPT_DIR" >&2
    exit 1
fi

GR_VER=$(apt list gnuradio 2>/dev/null | grep -m 1 gnuradio | cut -d' ' -f2 | cut -d'.' -f1,2 || true)
echo "== apt offers GNURadio ${GR_VER:-unknown}"
if [ "$GR_VER" != "3.10" ]; then
    echo "error: this branch needs GNURadio 3.10 (Ubuntu 22.04/24.04)" >&2
    exit 1
fi

echo "== enabling source repositories (for apt build-dep)"
if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
    # Ubuntu 24.04+ deb822 format
    sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources
else
    sed -i -- 's/^# *deb-src/deb-src/' /etc/apt/sources.list
fi

echo "== installing dependencies (this is the slow part)"
apt-get update -qq
apt-get build-dep -y -qq gnuradio
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    gnuradio gnuradio-dev gr-osmosdr librtlsdr-dev libuhd-dev \
    libhackrf-dev liborc-dev cmake git build-essential pkg-config \
    python3-pybind11 python3-numpy python3-waitress python3-requests \
    libsndfile1-dev libspdlog-dev rtl-sdr alsa-utils

echo "/usr/bin/python3" > "$APPS/op25_python"

if [ ! -f /etc/modprobe.d/blacklist-rtl.conf ]; then
    echo "== blacklisting rtl28xx DVB kernel drivers"
    install -m 0644 "$REPO/blacklist-rtl.conf" /etc/modprobe.d/
    rmmod dvb_usb_rtl28xxu 2>/dev/null || true
fi

echo "== building op25"
cd "$REPO"
rm -rf build
mkdir build
cd build
cmake .. > cmake.log 2>&1
make -j"$(nproc)" > make.log 2>&1
make install > install.log 2>&1
ldconfig

echo "== running squelch self-tests"
cd "$APPS"
python3 squelch_core_test.py
python3 squelch_gr_test.py

cat <<'EOF'

== deploy complete ==

Next steps:
  1. plug in the RTL-SDR and check it:      rtl_test -t
     (if the DVB driver grabbed it, reboot once - the blacklist is installed)
  2. edit the test frequency and gain in:   field-test/cfg-nbfm-noise.json
  3. start listening:                       field-test/run-field-test.sh noise
See field-test/README.md for the full test plan.
EOF
