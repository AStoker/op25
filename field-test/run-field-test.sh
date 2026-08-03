#!/bin/bash
#
# Launch multi_rx with one of the prepared NBFM squelch test configs.
#
#     ./run-field-test.sh [noise|power|voice] [verbosity]
#
# Default mode is "noise", default verbosity 2 (shows squelch open/close
# transitions with measured quieting in dB).  Status page: http://<host>:8080
#
set -euo pipefail

MODE="${1:-noise}"
VERBOSITY="${2:-2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
APPS="$REPO/op25/gr-op25_repeater/apps"
CFG="$SCRIPT_DIR/cfg-nbfm-$MODE.json"

if [ ! -f "$CFG" ]; then
    echo "usage: $0 [noise|power|voice] [verbosity]" >&2
    exit 1
fi

cd "$APPS"
exec python3 multi_rx.py -c "$CFG" -v "$VERBOSITY"
