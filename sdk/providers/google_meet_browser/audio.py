import asyncio
import os


HEARING_SINK = "meetmind_hearing"
SPEAKING_SINK = "meetmind_speaking"
VIRTUAL_MIC = "meetmind_mic"


async def setup_audio_devices():
    """Create virtual audio devices. Safe to call multiple times."""
    cmds = [
        ["pactl", "unload-module", "module-null-sink"],
        ["pactl", "unload-module", "module-virtual-source"],
    ]
    for cmd in cmds:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    await asyncio.sleep(1)

    load_cmds = [
        ["pactl", "load-module", "module-null-sink",
         f"sink_name={HEARING_SINK}",
         f"sink_properties=device.description=MeetMind_Hearing"],

        ["pactl", "load-module", "module-null-sink",
         f"sink_name={SPEAKING_SINK}",
         f"sink_properties=device.description=MeetMind_Speaking"],

        ["pactl", "load-module", "module-virtual-source",
         f"source_name={VIRTUAL_MIC}",
         f"source_properties=device.description=MeetMind_Mic",
         f"master={SPEAKING_SINK}.monitor"],
    ]
    for cmd in load_cmds:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    # Unmute and set volumes
    volume_cmds = [
        ["pactl", "set-sink-volume", HEARING_SINK, "65536"],
        ["pactl", "set-sink-volume", SPEAKING_SINK, "65536"],
        ["pactl", "set-sink-mute", HEARING_SINK, "0"],
        ["pactl", "set-sink-mute", SPEAKING_SINK, "0"],
        ["pactl", "set-source-mute", VIRTUAL_MIC, "0"],
        ["pactl", "set-source-volume", VIRTUAL_MIC, "65536"],
        ["pactl", "set-default-source", VIRTUAL_MIC],
        ["pactl", "set-default-sink", HEARING_SINK],
    ]
    for cmd in volume_cmds:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()


async def route_sink_inputs_to_hearing():
    """Move all active sink inputs to meetmind_hearing."""
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sinks",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    sink_index = None
    for line in stdout.decode().splitlines():
        if HEARING_SINK in line and ".2" not in line:
            sink_index = line.split()[0]
            break

    if not sink_index:
        return 0

    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sink-inputs",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    moved = 0
    for line in stdout.decode().splitlines():
        if not line.strip():
            continue
        parts = line.split()
        input_index = parts[0]
        current_sink = parts[1] if len(parts) > 1 else ""
        if current_sink != sink_index:
            proc = await asyncio.create_subprocess_exec(
                "pactl", "move-sink-input", input_index, sink_index,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            moved += 1
    return moved


def get_env_for_chromium() -> dict:
    """Environment variables that point Chromium at virtual devices."""
    return {
        **os.environ,
        "PULSE_SINK": HEARING_SINK,
        "PULSE_SOURCE": VIRTUAL_MIC,
        "DISPLAY": os.environ.get("DISPLAY", ":99"),
    }