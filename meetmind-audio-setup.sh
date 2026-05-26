#!/bin/bash
set -e

echo "=== MeetMind Audio Setup ==="

# Clean up any existing modules
pactl unload-module module-null-sink 2>/dev/null || true
pactl unload-module module-virtual-source 2>/dev/null || true
sleep 1

# Hearing sink — Meet audio output flows here, ffmpeg reads it for STT
pactl load-module module-null-sink \
    sink_name=meetmind_hearing \
    sink_properties=device.description=MeetMind_Hearing

# Speaking sink — TTS audio flows here, Meet picks it up as mic input
pactl load-module module-null-sink \
    sink_name=meetmind_speaking \
    sink_properties=device.description=MeetMind_Speaking

# Virtual mic — reads from speaking sink monitor, Chromium uses this as its mic
pactl load-module module-virtual-source \
    source_name=meetmind_mic \
    source_properties=device.description=MeetMind_Mic \
    master=meetmind_speaking.monitor

# Set volumes and unmute everything
pactl set-sink-volume meetmind_hearing 65536
pactl set-sink-volume meetmind_speaking 65536
pactl set-sink-mute meetmind_hearing 0
pactl set-sink-mute meetmind_speaking 0
pactl set-source-mute meetmind_mic 0
pactl set-source-volume meetmind_mic 65536

# Set as defaults so Chromium picks them up automatically
pactl set-default-sink meetmind_hearing
pactl set-default-source meetmind_mic

echo "=== Audio Setup Complete ==="
echo "Sinks:"
pactl list short sinks | grep meetmind
echo "Sources:"
pactl list short sources | grep meetmind
echo "Default sink:   $(pactl info | grep 'Default Sink')"
echo "Default source: $(pactl info | grep 'Default Source')"
