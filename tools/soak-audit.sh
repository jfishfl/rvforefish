#!/bin/sh
set -eu

# Read-only resource and safety sampler for the monitor-only deployment.
# Defaults: one sample every five minutes for 24 hours.

INTERVAL=${1:-300}
SAMPLES=${2:-288}
APP=${APP:-/data/apps/foretravel-rvc}
SERVICE=${SERVICE:-/service/foretravel-rvc}
LOGDIR=${LOGDIR:-/var/log/foretravel-rvc}
OUT=${OUT:-/data/log/foretravel-rvc-soak.tsv}
PIDFILE=${PIDFILE:-/data/log/foretravel-rvc-soak.pid}
IFACE=${IFACE:-vecan0}

case "$INTERVAL:$SAMPLES" in
    *[!0-9:]*|0:*|*:0)
        echo "interval and sample count must be positive integers" >&2
        exit 2
        ;;
esac

if test -f "$PIDFILE"; then
    old_pid=$(cat "$PIDFILE" 2>/dev/null || true)
    if test -n "$old_pid" && kill -0 "$old_pid" 2>/dev/null; then
        echo "soak audit is already running as PID $old_pid" >&2
        exit 1
    fi
fi

printf '%s\n' "$$" > "$PIDFILE"
cleanup() {
    test "$(cat "$PIDFILE" 2>/dev/null || true)" = "$$" && rm -f "$PIDFILE"
}
trap cleanup EXIT INT TERM

if ! test -s "$OUT"; then
    printf 'epoch_utc\tiso_utc\tservice_up\tpid\tcpu_ticks\trss_kb\tthreads\tapp_kb\tlog_kb\tdata_avail_kb\tcan_state\trx_packets\trx_errors\trx_dropped\ttx_packets\ttx_errors\ttx_dropped\taudit_tx_count\tgenerator_owner_count\tbattery_service_count\taggregate_present\tactive_bms_present\tberr_tx\tberr_rx\tcan_restarts\tcan_bus_errors\tcan_error_warn\tcan_error_passive\tcan_bus_off\n' > "$OUT"
fi

started=$(date +%s)
sample=0
while test "$sample" -lt "$SAMPLES"; do
    epoch=$(date +%s)
    iso=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    status=$(svstat "$SERVICE" 2>/dev/null || true)
    case "$status" in
        *': up '*) service_up=1 ;;
        *) service_up=0 ;;
    esac
    pid=$(printf '%s\n' "$status" | sed -n 's/.*pid \([0-9][0-9]*\).*/\1/p')
    cpu_ticks=0
    rss_kb=0
    threads=0
    if test -n "$pid" && test -r "/proc/$pid/stat"; then
        cpu_ticks=$(awk '{print $14+$15}' "/proc/$pid/stat")
        rss_kb=$(sed -n 's/^VmRSS:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "/proc/$pid/status")
        threads=$(sed -n 's/^Threads:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "/proc/$pid/status")
    fi
    app_kb=$(du -sk "$APP" 2>/dev/null | awk '{print $1}')
    log_kb=$(du -sk "$LOGDIR" 2>/dev/null | awk '{print $1}')
    data_avail_kb=$(df -k /data | awk 'NR==2 {print $4}')
    can_detail=$(ip -details -statistics link show "$IFACE" 2>/dev/null || true)
    can_state=$(printf '%s\n' "$can_detail" | sed -n 's/.*can state \([^ ]*\).*/\1/p')
    berr_tx=$(printf '%s\n' "$can_detail" | sed -n 's/.*berr-counter tx \([0-9][0-9]*\) rx.*/\1/p')
    berr_rx=$(printf '%s\n' "$can_detail" | sed -n 's/.*berr-counter tx [0-9][0-9]* rx \([0-9][0-9]*\).*/\1/p')
    can_restarts=$(printf '%s\n' "$can_detail" | awk '/re-started[[:space:]]+bus-errors/{getline; print $1; exit}')
    can_bus_errors=$(printf '%s\n' "$can_detail" | awk '/re-started[[:space:]]+bus-errors/{getline; print $2; exit}')
    can_error_warn=$(printf '%s\n' "$can_detail" | awk '/re-started[[:space:]]+bus-errors/{getline; print $4; exit}')
    can_error_passive=$(printf '%s\n' "$can_detail" | awk '/re-started[[:space:]]+bus-errors/{getline; print $5; exit}')
    can_bus_off=$(printf '%s\n' "$can_detail" | awk '/re-started[[:space:]]+bus-errors/{getline; print $6; exit}')
    stats="/sys/class/net/$IFACE/statistics"
    rx_packets=$(cat "$stats/rx_packets" 2>/dev/null || echo 0)
    rx_errors=$(cat "$stats/rx_errors" 2>/dev/null || echo 0)
    rx_dropped=$(cat "$stats/rx_dropped" 2>/dev/null || echo 0)
    tx_packets=$(cat "$stats/tx_packets" 2>/dev/null || echo 0)
    tx_errors=$(cat "$stats/tx_errors" 2>/dev/null || echo 0)
    tx_dropped=$(cat "$stats/tx_dropped" 2>/dev/null || echo 0)
    audit_tx_count=$(grep -c 'AUDIT TX' "$LOGDIR/current" 2>/dev/null || true)
    generator_owner_count=$(dbus -y 2>/dev/null | grep -c '^com\.victronenergy\.generator\.' || true)
    battery_services=$(dbus -y 2>/dev/null | grep '^com\.victronenergy\.battery' || true)
    battery_service_count=$(printf '%s\n' "$battery_services" | sed '/^$/d' | wc -l | tr -d ' ')
    aggregate_present=$(printf '%s\n' "$battery_services" | grep -c '^com\.victronenergy\.battery\.aggregate$' || true)
    active_bms=$(dbus -y com.victronenergy.system /ActiveBmsService GetValue 2>/dev/null || true)
    case "$active_bms" in
        *com.victronenergy.battery*) active_bms_present=1 ;;
        *) active_bms_present=0 ;;
    esac

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$epoch" "$iso" "$service_up" "${pid:-0}" "$cpu_ticks" \
        "${rss_kb:-0}" "${threads:-0}" "${app_kb:-0}" "${log_kb:-0}" \
        "${data_avail_kb:-0}" "${can_state:-UNKNOWN}" "$rx_packets" \
        "$rx_errors" "$rx_dropped" "$tx_packets" "$tx_errors" \
        "$tx_dropped" "${audit_tx_count:-0}" "${generator_owner_count:-0}" \
        "$battery_service_count" "${aggregate_present:-0}" \
        "$active_bms_present" "${berr_tx:-0}" "${berr_rx:-0}" \
        "${can_restarts:-0}" "${can_bus_errors:-0}" \
        "${can_error_warn:-0}" "${can_error_passive:-0}" \
        "${can_bus_off:-0}" >> "$OUT"

    sample=$((sample + 1))
    if test "$sample" -lt "$SAMPLES"; then
        next=$((started + sample * INTERVAL))
        now=$(date +%s)
        delay=$((next - now))
        test "$delay" -le 0 || sleep "$delay"
    fi
done
