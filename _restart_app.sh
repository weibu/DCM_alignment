#!/usr/bin/env bash
# Kill only the dcm_align_app.py process, then relaunch
wmic process where "commandline like '%dcm_align_app%'" delete 2>/dev/null || true
sleep 1
cd "$(dirname "$0")"
py dcm_align_app.py &
