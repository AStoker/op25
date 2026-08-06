# syntax=docker/dockerfile:1.7
#
# OP25 Home Assistant add-on.
#
# THE BUILD CONTEXT IS THE REPOSITORY ROOT, not this directory. CI passes
# `context: "."` with `file: addons/op25/Dockerfile`. Supervisor's *local*
# add-on build would give this folder as the context, which is why the
# published add-on sets `image:` and never builds on device.
#
# Debian trixie, deliberately:
#   - gnuradio 3.10.12 and gr-osmosdr 0.2.6
#   - librtlsdr 2.0.2, which already knows the RTL-SDR Blog V4
#     (rtlsdr_check_dongle_model(dev, "RTLSDRBlog", "Blog V4")). On bookworm's
#     0.6.0 we would have to build the rtlsdrblog fork, as update-rtlsdr.sh does.
#   - python3-fastapi / python3-uvicorn packaged, so no pip and no PEP 668.
ARG BUILD_ARCH=amd64
ARG BASE_IMAGE=ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:trixie

# --------------------------------------------------------------- web UI ---
FROM node:22-bookworm-slim AS webui
WORKDIR /app
COPY op25/gr-op25_repeater/www/app/package.json \
     op25/gr-op25_repeater/www/app/yarn.lock ./
RUN yarn install --frozen-lockfile --non-interactive --network-timeout 600000
COPY op25/gr-op25_repeater/www/app/ ./
# vite build.outDir is ../dist relative to the app dir, so this lands in /dist.
# Built here rather than shipping the committed www/dist because `yarn build`
# runs `tsc -b` first: a type error fails the image build instead of shipping.
RUN yarn build

# ---------------------------------------------------------- native build ---
FROM ${BASE_IMAGE} AS builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# xterm FIRST and on its own: Debian's gnuradio has
#   Depends: gnome-terminal | x-terminal-emulator
# and apt takes the first alternative -- dragging in all of GNOME -- unless a
# provider is already installed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends xterm \
    && apt-get install -y --no-install-recommends \
        build-essential cmake pkg-config \
        gnuradio gnuradio-dev gr-osmosdr \
        libcppunit-dev python3-pybind11 python3-numpy \
        liborc-0.4-dev libsndfile1-dev libspdlog-dev \
        librtlsdr-dev libhackrf-dev libuhd-dev \
    && rm -rf /var/lib/apt/lists/*

# C++/CMake inputs ONLY. apps/ and www/ are deliberately excluded so editing
# Python or the UI does not invalidate a ~10 minute compile.
COPY CMakeLists.txt                            /src/CMakeLists.txt
COPY cmake                                     /src/cmake
COPY op25/gr-op25                              /src/op25/gr-op25
COPY op25/gr-op25_repeater/CMakeLists.txt      /src/op25/gr-op25_repeater/CMakeLists.txt
# Needed: gr-op25_repeater/CMakeLists.txt installs gnuradio-op25_repeaterConfig
# .cmake from here and configures targetConfig.cmake.in out of it.
COPY op25/gr-op25_repeater/cmake               /src/op25/gr-op25_repeater/cmake
COPY op25/gr-op25_repeater/include             /src/op25/gr-op25_repeater/include
COPY op25/gr-op25_repeater/lib                 /src/op25/gr-op25_repeater/lib
COPY op25/gr-op25_repeater/python              /src/op25/gr-op25_repeater/python
COPY op25/gr-op25_repeater/grc                 /src/op25/gr-op25_repeater/grc
COPY op25/gr-op25_repeater/apps/CMakeLists.txt /src/op25/gr-op25_repeater/apps/CMakeLists.txt
# GNU Radio's GrPybind.cmake configure_file()s this one 4 KB header for every
# pybind target, so cmake fails without it.  Just the header -- the rest of
# docs/ is 2.6 MB of doxygen scaffolding that is never built (the top-level
# add_subdirectory(docs) is commented out).
COPY op25/gr-op25/docs/doxygen/pydoc_macros.h \
     /src/op25/gr-op25/docs/doxygen/pydoc_macros.h
COPY op25/gr-op25_repeater/docs/doxygen/pydoc_macros.h \
     /src/op25/gr-op25_repeater/docs/doxygen/pydoc_macros.h

# -DCMAKE_INSTALL_PREFIX=/usr is required, not cosmetic: the pybind modules go
# to ${GR_PYTHON_DIR}/gnuradio/op25*, and with the default /usr/local prefix
# that does not land on Debian's sys.path reliably. arch-install.sh does the same.
RUN cmake -S /src -B /build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    && cmake --build /build --parallel "$(nproc)" \
    && DESTDIR=/install cmake --install /build --strip \
    && rm -rf /install/usr/include /install/usr/lib/cmake

# -------------------------------------------------------------- runtime ---
FROM ${BASE_IMAGE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends xterm \
    && apt-get install -y --no-install-recommends \
        gnuradio gr-osmosdr rtl-sdr \
        python3-numpy python3-packaging python3-requests \
        python3-fastapi python3-uvicorn python3-websockets \
        jq \
    && rm -rf /var/lib/apt/lists/*
# Deliberately absent: python3-sounddevice/libportaudio2 (local speaker output
# is meaningless in a container; sockaudio.py guards the import and degrades),
# gnuplot (the subprocess plot path was removed), waitress (http_server.py was
# removed), git and doxygen.

COPY --from=builder /install/ /
RUN ldconfig

# apps/ and www/dist MUST stay siblings: websocket_server.py computes
# _DIST_DIR = realpath(dirname(__file__)/../www/dist).
COPY op25/gr-op25_repeater/apps  /opt/op25/apps
COPY --from=webui /dist          /opt/op25/www/dist
COPY addons/op25/rootfs          /

# Sample config for a first run, referenced by the fatal-error message in
# init-op25 when the user has not supplied one yet.
COPY addons/op25/samples         /opt/op25/samples

# Fail the build here rather than at 3am on someone's NUC.
RUN python3 -c 'import gnuradio.op25, gnuradio.op25_repeater' \
    && python3 -c 'import fastapi, uvicorn, numpy, packaging' \
    && test -f /opt/op25/www/dist/index.html \
    && grep -q './op25-react.js' /opt/op25/www/dist/index.html

LABEL io.hass.type="addon"

WORKDIR /opt/op25/apps
