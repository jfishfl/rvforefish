#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

test "$(sed -n '2p' "$ROOT/version")" = ""
grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([~abd][0-9]+)?$' "$ROOT/version"
test "$(cat "$ROOT/gitHubInfo")" = "jfishfl:main"

bash -n "$ROOT/setup"
sh -n "$ROOT/services/foretravel-rvc/run"
sh -n "$ROOT/services/foretravel-rvc/log/run"
sh -n "$ROOT/scripts/runtime-preflight.sh"
sh -n "$ROOT/tools/import-legacy-config.sh"

PYTHONPATH="$ROOT/src" python3 -m foretravel_rvc.main \
    --config "$ROOT/config.default.json" --validate-config

PYTHONPATH="$ROOT/src" python3 -c \
    'import sys; from foretravel_rvc.config import load_config; c=load_config(sys.argv[1]); assert c.monitor_only; assert not c.can_tx_armed; assert not c.source_label_writes; assert not c.automatic_current_limit_switching' \
    "$ROOT/config.default.json"

if python3 -c 'import unittest' >/dev/null 2>&1; then
    PYTHONPATH="$ROOT/src" python3 -m unittest discover -s "$ROOT/tests" -v
else
    echo "python unittest module unavailable; skipped replay/unit suite on this host"
fi

echo "rvforefish package validation passed"
