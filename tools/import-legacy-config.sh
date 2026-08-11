#!/bin/sh
set -eu

PACKAGE=/data/rvforefish
LEGACY=/data/apps/foretravel-rvc
DATA_DIR=/data/rvforefish-data
CONFIG="$DATA_DIR/config.json"
TEMP="$DATA_DIR/config.json.tmp.$$"

if test -e "$LEGACY/state/own-generator-demand"; then
    echo "legacy generator-demand ownership marker exists; refusing migration" >&2
    exit 1
fi

if test ! -f "$LEGACY/config.json"; then
    echo "legacy configuration not found at $LEGACY/config.json" >&2
    exit 1
fi

if test -e "$CONFIG"; then
    echo "$CONFIG already exists; refusing to overwrite it" >&2
    exit 1
fi

PYTHONPATH="$PACKAGE/src" python3 -m foretravel_rvc.main \
    --config "$LEGACY/config.json" --validate-config

mkdir -p "$DATA_DIR/state"
chmod 700 "$DATA_DIR" "$DATA_DIR/state"
cp "$LEGACY/config.json" "$TEMP"
chmod 600 "$TEMP"
mv "$TEMP" "$CONFIG"

echo "imported legacy configuration to $CONFIG"
echo "no service was stopped, started, or modified"
echo "review the imported write/control gates before installing the package"
