#!/bin/sh
# Build the XIAO firmware and send it to the board over WiFi. Usage: ./ota.sh [host]
set -e
cd "$(dirname "$0")"
HOST="${1:-door-cam.local}"
TOKEN=$(sed -n 's/.*DOORCAM_TOKEN "\(.*\)".*/\1/p' src/secrets.h)
[ -n "$TOKEN" ] || { echo "No token: copy src/secrets.h.example to src/secrets.h, then flash once over USB." >&2; exit 1; }
PIO=$(command -v pio || echo "$HOME/.platformio/penv/bin/pio")
"$PIO" run -e xiao_sense
curl --fail-with-body -sS -m 300 -H "X-Token: $TOKEN" -H "Content-Type: application/octet-stream" \
  --data-binary @.pio/build/xiao_sense/firmware.bin "http://$HOST/ota"
