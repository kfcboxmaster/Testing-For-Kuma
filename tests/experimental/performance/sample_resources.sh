#!/usr/bin/env bash
# Sample container CPU & memory every 2s into a CSV. Run alongside load_runner.py.
# Usage:  ./sample_resources.sh <duration_s> <out.csv> [container]
set -e
DUR="${1:-60}"
OUT="${2:-resources.csv}"
CONTAINER="${3:-uptime-kuma}"
END=$((SECONDS + DUR))
echo "ts,cpu_pct,mem_mib,mem_pct" > "$OUT"
while [ $SECONDS -lt $END ]; do
    LINE=$(docker stats --no-stream --format "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}" "$CONTAINER" 2>/dev/null || echo "")
    if [ -n "$LINE" ]; then
        TS=$(date +%s)
        # CPU: strip %
        CPU=$(echo "$LINE" | awk -F'|' '{gsub("%","",$1); print $1}')
        # MemUsage looks like "123.4MiB / 15.52GiB" — extract the used side, normalize to MiB
        MEM=$(echo "$LINE" | awk -F'|' '{print $2}' | awk '{print $1}')
        MEM_NUM=$(echo "$MEM" | sed -E 's/MiB//; s/GiB/*1024/')
        MEM_MIB=$(echo "$MEM_NUM" | bc 2>/dev/null || echo "0")
        # MemPerc
        MP=$(echo "$LINE" | awk -F'|' '{gsub("%","",$3); print $3}')
        echo "$TS,$CPU,$MEM_MIB,$MP" >> "$OUT"
    fi
    sleep 2
done
echo "[done] -> $OUT"
