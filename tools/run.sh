#!/bin/bash
# usage: tools/run.sh <image.cue|bin>  — 기존 PCSX2 종료 후 가상 디스플레이 :99에서 부팅
pkill -x pcsx2-qt; sleep 2
pgrep -f "Xvfb :99" >/dev/null || (Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 &)
mkdir -p work
DISPLAY=:99 nohup flatpak run --user net.pcsx2.PCSX2 -batch -fastboot -- "$(realpath "$1")" > work/pcsx2_run.log 2>&1 &
disown
