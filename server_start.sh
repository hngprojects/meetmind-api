#!/bin/bash
set -e

echo "=== MeetMind Server Startup ==="

# 1. Start virtual display (Chromium needs this on a headless server)
export DISPLAY=:99
pkill Xvfb 2>/dev/null || true
sleep 1
Xvfb :99 -screen 0 1280x720x24 -ac &
echo "Xvfb started on :99"
sleep 2

# 2. Start PulseAudio
pulseaudio --start --exit-idle-time=-1
sleep 1

# 3. Set up virtual audio devices
~/meetmind-audio-setup.sh

# 4. Export display for all child processes
export DISPLAY=:99
export PULSE_SINK=meetmind_hearing
export PULSE_SOURCE=meetmind_mic
