#!/usr/bin/env bash
# Run two lecture-camera feeds in parallel for one class: one watching the
# board, one watching the projector screen. Both resume the SAME live
# lecture the audio recorder started (Knottra fuses all three streams).
#
# Usage:
#   scripts/run-cameras.sh <class-id> [board-device] [slide-device]
#   BOARD_DEVICE=0 SLIDE_DEVICE=1 scripts/run-cameras.sh algorithms-2026
#
# Don't know the device indices yet? Run: uv run lecture-camera --list-devices
set -euo pipefail
cd "$(dirname "$0")/.."

CLASS="${1:?usage: scripts/run-cameras.sh <class-id> [board-device] [slide-device]}"
BOARD_DEVICE="${2:-${BOARD_DEVICE:-0}}"
SLIDE_DEVICE="${3:-${SLIDE_DEVICE:-1}}"

echo "[run-cameras] class '$CLASS' — board on device $BOARD_DEVICE, slide on device $SLIDE_DEVICE"
echo "[run-cameras] Ctrl+C stops both."

uv run lecture-camera --class "$CLASS" --modality board --device "$BOARD_DEVICE" --auto-aim &
BOARD_PID=$!
uv run lecture-camera --class "$CLASS" --modality slide --device "$SLIDE_DEVICE" --auto-aim &
SLIDE_PID=$!

trap 'echo; echo "[run-cameras] stopping both …"; kill "$BOARD_PID" "$SLIDE_PID" 2>/dev/null' INT TERM
wait "$BOARD_PID" "$SLIDE_PID"
