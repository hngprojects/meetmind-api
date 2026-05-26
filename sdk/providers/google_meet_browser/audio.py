import asyncio
import os
import logging

logger = logging.getLogger(__name__)


HEARING_SINK = "meetmind_hearing"
SPEAKING_SINK = "meetmind_speaking"
VIRTUAL_MIC = "meetmind_mic"

async def _suspend_other_sinks():
    """Suspend all sinks except meetmind ones so Chromium has no alternative."""
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sinks",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    for line in stdout.decode().splitlines():
        parts = line.split()
        if not parts:
            continue
        sink_index = parts[0]
        sink_name = parts[1] if len(parts) > 1 else ""
        if "meetmind" not in sink_name:
            logger.info("Suspending non-meetmind sink: %s (%s)", sink_index, sink_name)
            proc2 = await asyncio.create_subprocess_exec(
                "pactl", "suspend-sink", sink_index, "1",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc2.wait()


async def setup_audio_devices():
    """Create virtual audio devices. Safe to call multiple times."""
    logger.info("Setting up audio devices...")
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
    
    await _suspend_other_sinks()
    logger.info(
        "Audio devices ready — sinks: %s, %s | source: %s",
        HEARING_SINK, SPEAKING_SINK, VIRTUAL_MIC,
    )


async def route_sink_inputs_to_hearing():
    """Move sink-inputs to hearing sink, protect speaking sink."""

    # Force default sink
    proc = await asyncio.create_subprocess_exec(
        "pactl", "set-default-sink", HEARING_SINK,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Build index → name map for all sinks
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sinks",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    sink_index_to_name = {}
    for line in stdout.decode().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sink_index_to_name[parts[0]] = parts[1]

    logger.debug("Sink map: %s", sink_index_to_name)

    # Now parse sink-inputs using detailed output
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "sink-inputs",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()

    if not output.strip():
        logger.debug("route_sink_inputs: no sink-inputs active")
        return 0

    current_input = None
    moved = 0
    skipped = 0

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("Sink Input #"):
            current_input = line.split("#")[1]

        elif line.startswith("Sink:") and current_input:
            # Value here is the sink INDEX number
            sink_index = line.split(":", 1)[1].strip()
            sink_name = sink_index_to_name.get(sink_index, "unknown")

            logger.debug(
                "sink-input #%s is on sink index %s (%s)",
                current_input, sink_index, sink_name,
            )

            if HEARING_SINK in sink_name:
                logger.debug(
                    "sink-input #%s already on %s — OK",
                    current_input, HEARING_SINK,
                )
                current_input = None
                continue

            if SPEAKING_SINK in sink_name:
                logger.debug(
                    "sink-input #%s is on %s (bot TTS) — leaving alone",
                    current_input, SPEAKING_SINK,
                )
                skipped += 1
                current_input = None
                continue

            # Wrong sink — move to hearing
            logger.info(
                "Moving sink-input #%s from '%s' (%s) → %s",
                current_input, sink_name, sink_index, HEARING_SINK,
            )
            move_proc = await asyncio.create_subprocess_exec(
                "pactl", "move-sink-input", current_input, HEARING_SINK,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await move_proc.wait()
            moved += 1
            current_input = None

    if moved > 0:
        logger.info(
            "route_sink_inputs: moved %d input(s) to %s | %d left on %s",
            moved, HEARING_SINK, skipped, SPEAKING_SINK,
        )

    return moved


async def log_sink_levels():
    """
    Log the current state of all meetmind sinks and their inputs.
    Call this periodically to confirm audio is flowing.
    """
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sink-inputs",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    lines = [l for l in stdout.decode().splitlines() if l.strip()]

    if not lines:
        logger.warning("AUDIO CHECK: no active sink-inputs — meeting audio may not be flowing")
        return

    for line in lines:
        logger.info("AUDIO CHECK sink-input: %s", line.strip())

    # Also check sink states
    proc2 = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sinks",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout2, _ = await proc2.communicate()
    for line in stdout2.decode().splitlines():
        if "meetmind" in line:
            state = "RUNNING" if "RUNNING" in line else ("IDLE" if "IDLE" in line else "SUSPENDED")
            logger.info("AUDIO CHECK sink: %s — %s", line.split()[1], state)



def get_env_for_chromium() -> dict:
    """Environment variables that point Chromium at virtual devices."""
    return {
        **os.environ,
        "PULSE_SINK": HEARING_SINK,
        "PULSE_SOURCE": VIRTUAL_MIC,
        "DISPLAY": os.environ.get("DISPLAY", ":99"),
    }

