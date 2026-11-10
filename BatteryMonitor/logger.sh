#!/bin/sh
# Battery Monitor background logger: one battery sample per minute.
# Writes raw sysfs values; the app normalises units when it reads the log.
APP="$(cd "$(dirname "$0")" && pwd)"
LOG="$APP/data/battery.csv"
PIDF=/tmp/batterymonitor_log.pid
SYS="${BATTMON_SYSFS:-/sys/class/power_supply}"
INTERVAL="${BATTMON_INTERVAL:-60}"
MAXLINES=60000      # ~6 weeks at one sample a minute
KEEPLINES=45000

if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then exit 0; fi
echo $$ > "$PIDF"
mkdir -p "$APP/data"

BAT=""; EXT=""
for d in "$SYS"/*; do
    t="$(cat "$d/type" 2>/dev/null)"
    case "$t" in
        Battery) [ -z "$BAT" ] && [ -f "$d/capacity" ] && BAT="$d" ;;
        USB|Mains|USB_C|USB_PD|USB_DCP|USB_CDP) EXT="$EXT $d" ;;
    esac
done
[ -z "$BAT" ] && exit 1

rd() { cat "$1" 2>/dev/null; }
n=0
while :; do
    ST="$(rd "$BAT/status")"
    if [ "$ST" = "Not charging" ] || [ "$ST" = "Unknown" ] || [ -z "$ST" ]; then
        for e in $EXT; do
            if [ "$(rd "$e/online")" = "1" ]; then
                if [ "$(rd "$BAT/capacity")" -ge 99 ] 2>/dev/null; then ST="Full"; else ST="Charging"; fi
            fi
        done
    fi
    echo "$(date +%s),$(rd "$BAT/capacity"),$(rd "$BAT/voltage_now"),$(rd "$BAT/current_now"),${ST:-Unknown},$(rd "$BAT/temp")" >> "$LOG"
    n=$((n + 1))
    if [ $((n % 120)) -eq 0 ] && [ "$(wc -l < "$LOG")" -gt "$MAXLINES" ]; then
        tail -n "$KEEPLINES" "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    fi
    sleep "$INTERVAL"
done
