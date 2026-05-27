#!/bin/bash

# op25 install script for macOS (Apple Silicon and Intel)
# Requires Homebrew: https://brew.sh

set -e

if [ ! -d op25/gr-op25 ]; then
    echo "====== error, op25 top level directories not found"
    echo "====== you must change to the op25 top level directory"
    echo "====== before running this script"
    exit 1
fi

# Initialize variables
FORCE=false

# Parse command-line arguments
while getopts ":f" opt; do
    case $opt in
        f) FORCE=true ;;
        *) ;;
    esac
done

# -----------------------------------------------------------------------
# Determine Homebrew prefix (Apple Silicon uses /opt/homebrew, Intel /usr/local)
# -----------------------------------------------------------------------
if command -v brew &>/dev/null; then
    BREW_PREFIX=$(brew --prefix)
else
    echo "====== Homebrew not found. Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Re-source Homebrew environment
    if [ -f /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -f /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    BREW_PREFIX=$(brew --prefix)
fi

echo "====== Homebrew prefix: ${BREW_PREFIX}"

# -----------------------------------------------------------------------
# Install system dependencies via Homebrew
# -----------------------------------------------------------------------
echo "====== Installing system dependencies via Homebrew..."

# gr-osmosdr is not in the standard Homebrew tap; it lives in the
# trunkrecorder/install tap. Add it before trying to install.
echo "====== Tapping trunkrecorder/install for gr-osmosdr..."
brew tap trunkrecorder/install

BREW_PACKAGES=(
    gnuradio                          # GNURadio 3.10 + Python bindings
    trunkrecorder/install/gr-osmosdr  # osmosdr source block (RTL-SDR, HackRF, Airspy, etc.)
    librtlsdr                         # RTL-SDR USB driver (via libusb)
    hackrf                            # HackRF support
    airspy                            # Airspy support
    libsndfile                        # audio file I/O (libsndfile1-dev equivalent)
    spdlog                            # fast logging library
    cmake                             # build system
    pybind11                          # Python/C++ bindings
    cppunit                           # unit test framework (required by cmake)
    gnuplot                           # plotting
    doxygen                           # documentation
    pkg-config                        # package config helper
)

if [ "$FORCE" = true ]; then
    brew install "${BREW_PACKAGES[@]}" || true
else
    echo "====== The following Homebrew packages will be installed:"
    printf '  %s\n' "${BREW_PACKAGES[@]}"
    read -r -p "Proceed? [y/N] " confirm
    case "$confirm" in
        [yY][eE][sS]|[yY]) brew install "${BREW_PACKAGES[@]}" || true ;;
        *) echo "Skipping Homebrew package installation."; exit 0 ;;
    esac
fi

# -----------------------------------------------------------------------
# Determine the Python3 provided by the Homebrew gnuradio formula
# -----------------------------------------------------------------------
# Homebrew's gnuradio brings its own Python; use that as the base for the
# virtualenv so that gnuradio's C extension modules are accessible.
GR_PYTHON=$(brew --prefix gnuradio)/bin/python3 2>/dev/null || true
if [ ! -x "${GR_PYTHON}" ]; then
    # Fall back to any Homebrew python3
    GR_PYTHON="${BREW_PREFIX}/bin/python3"
fi
if [ ! -x "${GR_PYTHON}" ]; then
    GR_PYTHON=$(command -v python3)
fi
echo "====== Using base Python: ${GR_PYTHON} ($(${GR_PYTHON} --version))"

# -----------------------------------------------------------------------
# Create a virtualenv with --system-site-packages
# -----------------------------------------------------------------------
# --system-site-packages lets the venv inherit Homebrew's gnuradio,
# osmosdr and other native modules, while still allowing pip installs
# without hitting the "externally-managed-environment" restriction.
APPS_DIR="$(pwd)/op25/gr-op25_repeater/apps"
VENV_DIR="${APPS_DIR}/.venv"

echo "====== Creating virtualenv at ${VENV_DIR} ..."
"${GR_PYTHON}" -m venv --system-site-packages "${VENV_DIR}"
VENV_PYTHON="${VENV_DIR}/bin/python3"

# -----------------------------------------------------------------------
# Install Python dependencies into the virtualenv
# -----------------------------------------------------------------------
echo "====== Installing Python dependencies into virtualenv..."

PIP_PACKAGES=(
    numpy
    waitress
    requests
    websockets
    "fastapi"
    "uvicorn[standard]"
)

"${VENV_PYTHON}" -m pip install --upgrade pip
"${VENV_PYTHON}" -m pip install "${PIP_PACKAGES[@]}"

# -----------------------------------------------------------------------
# Tell op25 which Python to use
# -----------------------------------------------------------------------
echo "${VENV_PYTHON}" > op25/gr-op25_repeater/apps/op25_python
echo "====== Wrote op25_python -> ${VENV_PYTHON}"

# -----------------------------------------------------------------------
# macOS RTL-SDR note
# -----------------------------------------------------------------------
# On macOS, RTL-SDR uses libusb via librtlsdr — no kernel module blacklist
# is needed. If you see "usb_claim_interface error -6" when connecting the
# dongle, the Apple USB CDC driver may have claimed it. Run:
#
#   sudo kextunload -b com.apple.driver.usb.cdc.ncm 2>/dev/null || true
#
# or install the rtl-sdr udev rules equivalent via:
#   brew install librtlsdr
# and follow any post-install caveats printed above.

# -----------------------------------------------------------------------
# Build op25
# -----------------------------------------------------------------------
echo "====== Building op25..."

rm -rf build
mkdir build
cd build

# Pass the Homebrew prefix so cmake can locate all Homebrew-installed libs.
cmake ../ \
    -DCMAKE_PREFIX_PATH="${BREW_PREFIX}" \
    -DCMAKE_INSTALL_PREFIX="${BREW_PREFIX}" \
    2>&1 | tee cmake.log

make -j"$(sysctl -n hw.logicalcpu)" 2>&1 | tee make.log

echo "====== Installing op25 (may require sudo)..."
sudo make install 2>&1 | tee install.log

# Update the dynamic linker cache (macOS uses dyld; no ldconfig needed,
# but ensure the Homebrew lib path is in DYLD_LIBRARY_PATH if required).
echo "====== Build and install complete."
echo ""
echo "====== If gnuradio modules are not found at runtime, add the following"
echo "====== to your shell profile (~/.zshrc or ~/.bash_profile):"
echo ""
echo "    export PYTHONPATH=\"\${PYTHONPATH}:${BREW_PREFIX}/lib/python3/dist-packages\""
echo "    export DYLD_LIBRARY_PATH=\"\${DYLD_LIBRARY_PATH}:${BREW_PREFIX}/lib\""
echo ""
echo "====== Then run: cd op25/gr-op25_repeater/apps && ./op25.sh"
