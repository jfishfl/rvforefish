#!/bin/sh
set -eu

PACKAGE=${PACKAGE:-/data/rvforefish}
DATA_DIR=${DATA_DIR:-/data/rvforefish-data}
CONFIG="$DATA_DIR/config.json"

test -f "$CONFIG"
test -f "$PACKAGE/src/foretravel_rvc/main.py"
test -x "$PACKAGE/services/foretravel-rvc/run"
test -x "$PACKAGE/services/foretravel-rvc/log/run"

PYTHONPATH="$PACKAGE/src" python3 -m foretravel_rvc.main \
    --config "$CONFIG" --validate-config

values=$(PYTHONPATH="$PACKAGE/src" python3 -c \
    'import sys; from foretravel_rvc.config import load_config; c=load_config(sys.argv[1]); print(c.interface, c.genset_device_instance, c.switch_device_instance)' \
    "$CONFIG")
set -- $values
interface=$1
gensetInstance=$2
switchInstance=$3

ip link show "$interface" >/dev/null

if ! ps w | grep -q "[d]bus-rv-c.*$interface"; then
    echo "dbus-rv-c is not running on $interface" >&2
    exit 1
fi

# The bridge has not started yet when this runs, so any existing service with
# one of its configured instances is a real ownership collision.
for service in $(dbus -y | grep '^com\.victronenergy\.genset\.' || true); do
    instance=$(dbus -y "$service" /DeviceInstance GetValue 2>/dev/null | \
        sed -n 's/.*Value = //p')
    if test "$instance" = "$gensetInstance"; then
        echo "genset device instance $gensetInstance is already used by $service" >&2
        exit 1
    fi
done

for service in $(dbus -y | grep '^com\.victronenergy\.switch\.' || true); do
    instance=$(dbus -y "$service" /DeviceInstance GetValue 2>/dev/null | \
        sed -n 's/.*Value = //p')
    if test "$instance" = "$switchInstance"; then
        echo "switch device instance $switchInstance is already used by $service" >&2
        exit 1
    fi
done

echo "rvforefish runtime preflight passed"
