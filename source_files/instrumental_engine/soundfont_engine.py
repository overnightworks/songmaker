"""SoundFont-based instrument rendering via FluidSynth.

Provides high-quality sampled instruments using General MIDI SoundFonts.
FluidSynth is required for all ``sf:*`` instruments — no fallback to DSP.
"""

from __future__ import annotations

import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from instrumental_engine.constants import SAMPLE_RATE
from instrumental_engine.models import GMProgram


FLUIDSYNTH_CHECK_CMD: Final[str] = "fluidsynth"
DEFAULT_SOUNDFONT_PATHS: Final[tuple[str, ...]] = (
    "soundfonts/GeneralUser_GS.sf2",
    "soundfonts/FluidR3_GM.sf2",
    "soundfonts/default.sf2",
    "C:/tools/fluidsynth/share/soundfonts/default.sf2",
    "C:/soundfonts/GeneralUser_GS.sf2",
)


def find_soundfont() -> Path:
    """Locate a SoundFont file on the system.

    Searches known paths and the ``soundfonts/`` directory for ``.sf2`` files.

    Returns:
        Path to the first discovered SoundFont file.

    Raises:
        FileNotFoundError: With download instructions if no SoundFont found.
    """
    for sf_path in DEFAULT_SOUNDFONT_PATHS:
        path = Path(sf_path)
        if path.exists():
            return path

    sf_dir = Path("soundfonts")
    if sf_dir.is_dir():
        discovered = sorted(sf_dir.glob("*.sf2"))
        if discovered:
            return discovered[0]

    raise FileNotFoundError(
        "No SoundFont (.sf2) files found.\n"
        "\n"
        "Place a General MIDI SoundFont in the 'soundfonts/' directory:\n"
        "  soundfonts/FluidR3_GM.sf2\n"
        "\n"
        "Recommended downloads:\n"
        "  FluidR3_GM.sf2 (~140 MB): "
        "https://member.keymusician.com/Member/FluidR3_GM/FluidR3_GM.sf2\n"
        "  GeneralUser_GS.sf2 (~30 MB): https://generaluser.sourceforge.io/\n"
        "\n"
        "See docs/soundfont_setup.md for the complete setup guide."
    )


def is_fluidsynth_available() -> bool:
    """Check if FluidSynth CLI is available on PATH.

    Returns:
        True if fluidsynth command is accessible, False otherwise.
    """
    try:
        subprocess.run(
            [FLUIDSYNTH_CHECK_CMD, "--version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def require_fluidsynth() -> None:
    """Require FluidSynth to be installed or raise with instructions.

    Raises:
        RuntimeError: With OS-specific installation instructions.
    """
    if is_fluidsynth_available():
        return

    raise RuntimeError(
        "FluidSynth is required but not found on PATH.\n"
        "\n"
        "Install FluidSynth:\n"
        "  Windows:  winget install FluidSynth.FluidSynth\n"
        "  macOS:    brew install fluid-synth\n"
        "  Linux:    sudo apt-get install -y fluidsynth\n"
        "\n"
        "Manual download: "
        "https://github.com/FluidSynth/fluidsynth/releases\n"
        "\n"
        "After installation, restart your terminal and verify:\n"
        "  fluidsynth --version\n"
        "\n"
        "See docs/soundfont_setup.md for the complete setup guide."
    )


def write_midi_file(
    midi_path: Path,
    notes: list[tuple[int, float, float, float]],
    program: int,
    bpm: int = 120,
) -> None:
    """Write a minimal MIDI file for FluidSynth rendering.

    Args:
        midi_path: Output MIDI file path.
        notes: List of (midi_note, start_seconds, duration_seconds, velocity_0_1).
        program: GM program number.
        bpm: Tempo.
    """
    ticks_per_beat = 480
    us_per_beat = int(60_000_000 / bpm)
    beats_per_second = bpm / 60.0
    ticks_per_second = ticks_per_beat * beats_per_second

    events: list[tuple[int, bytes]] = []

    events.append(
        (
            0,
            bytes(
                [
                    0xFF,
                    0x51,
                    0x03,
                    (us_per_beat >> 16) & 0xFF,
                    (us_per_beat >> 8) & 0xFF,
                    us_per_beat & 0xFF,
                ]
            ),
        )
    )

    events.append((0, bytes([0xC0, program & 0x7F])))

    for midi_note, start_s, dur_s, vel_01 in notes:
        vel = max(1, min(127, int(vel_01 * 127)))
        start_tick = int(start_s * ticks_per_second)
        dur_ticks = max(1, int(dur_s * ticks_per_second))
        end_tick = start_tick + dur_ticks
        events.append((start_tick, bytes([0x90, midi_note & 0x7F, vel])))
        events.append((end_tick, bytes([0x80, midi_note & 0x7F, 0x40])))

    events.sort(key=lambda e: e[0])

    track_data = bytearray()
    prev_tick = 0
    for abs_tick, data in events:
        delta = abs_tick - prev_tick
        prev_tick = abs_tick
        track_data.extend(_encode_variable_length(delta))
        track_data.extend(data)

    track_data.extend(_encode_variable_length(0))
    track_data.extend(bytes([0xFF, 0x2F, 0x00]))

    midi_data = bytearray()
    midi_data.extend(b"MThd")
    midi_data.extend(struct.pack(">I", 6))
    midi_data.extend(struct.pack(">HHH", 0, 1, ticks_per_beat))

    midi_data.extend(b"MTrk")
    midi_data.extend(struct.pack(">I", len(track_data)))
    midi_data.extend(track_data)

    midi_path.write_bytes(bytes(midi_data))


def _encode_variable_length(value: int) -> bytes:
    """Encode integer as MIDI variable-length quantity."""
    if value < 0:
        value = 0
    result: list[int] = []
    result.append(value & 0x7F)
    value >>= 7
    while value > 0:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.reverse()
    return bytes(result)


def _read_wav_to_floats(wav_path: Path) -> list[float]:
    """Read WAV file and return mono float samples.

    Args:
        wav_path: Path to WAV file.

    Returns:
        Mono float samples in [-1.0, 1.0].
    """
    with wave.open(str(wav_path), "r") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    samples: list[float] = []
    if sample_width == 2:
        for i in range(0, len(raw), 2 * n_channels):
            val = struct.unpack("<h", raw[i : i + 2])[0]
            samples.append(val / 32767.0)
    elif sample_width == 4:
        for i in range(0, len(raw), 4 * n_channels):
            val = struct.unpack("<i", raw[i : i + 4])[0]
            samples.append(val / 2147483647.0)
    elif sample_width == 1:
        for i in range(0, len(raw), n_channels):
            samples.append((raw[i] - 128) / 128.0)

    return samples


@dataclass
class SoundFontRenderer:
    """Renders notes using FluidSynth and a SoundFont file.

    Attributes:
        soundfont_path: Path to the .sf2 SoundFont file.
        gm_program: General MIDI program number.
        gain: FluidSynth output gain.
    """

    soundfont_path: Path
    gm_program: GMProgram = GMProgram.ACOUSTIC_GRAND_PIANO
    gain: float = 1.0

    def render_note(
        self, freq: float, duration_seconds: float, velocity: float
    ) -> list[float]:
        """Render a single note via FluidSynth.

        Args:
            freq: Note frequency in Hz.
            duration_seconds: Duration in seconds.
            velocity: Volume (0.0 - 1.0).

        Returns:
            Audio samples at SAMPLE_RATE.
        """
        midi_note = _freq_to_nearest_midi(freq)
        return self._render_midi_notes(
            [(midi_note, 0.0, duration_seconds, velocity)],
            duration_seconds + 0.5,
        )

    def render_chord(
        self,
        frequencies: tuple[float, ...],
        duration_seconds: float,
        velocity: float,
    ) -> list[float]:
        """Render a chord via FluidSynth.

        Args:
            frequencies: Chord note frequencies.
            duration_seconds: Duration in seconds.
            velocity: Volume.

        Returns:
            Audio samples.
        """
        notes = [
            (_freq_to_nearest_midi(f), 0.0, duration_seconds, velocity)
            for f in frequencies
        ]
        return self._render_midi_notes(notes, duration_seconds + 0.5)

    def render_sequence(
        self,
        notes: list[tuple[int, float, float, float]],
        total_duration: float,
    ) -> list[float]:
        """Render a sequence of MIDI notes via FluidSynth.

        Args:
            notes: List of (midi_note, start_seconds, duration_seconds, velocity).
            total_duration: Total audio duration in seconds.

        Returns:
            Audio samples.
        """
        return self._render_midi_notes(notes, total_duration)

    def _render_midi_notes(
        self,
        notes: list[tuple[int, float, float, float]],
        total_duration: float,
    ) -> list[float]:
        """Internal: render MIDI notes through FluidSynth pipeline."""
        with tempfile.TemporaryDirectory(prefix="_sf_") as tmpdir:
            tmp = Path(tmpdir)
            midi_path = tmp / "input.mid"
            wav_path = tmp / "output.wav"

            write_midi_file(midi_path, notes, int(self.gm_program))

            try:
                subprocess.run(
                    [
                        "fluidsynth",
                        "-ni",
                        "-g",
                        str(self.gain),
                        "-r",
                        str(SAMPLE_RATE),
                        "-F",
                        str(wav_path),
                        str(self.soundfont_path),
                        str(midi_path),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                print(f"   ⚠️  FluidSynth render failed: {exc}")
                return [0.0] * int(total_duration * SAMPLE_RATE)

            if wav_path.exists():
                samples = _read_wav_to_floats(wav_path)
                target_len = int(total_duration * SAMPLE_RATE)
                if len(samples) > target_len:
                    return samples[:target_len]
                while len(samples) < target_len:
                    samples.append(0.0)
                return samples

            return [0.0] * int(total_duration * SAMPLE_RATE)


def _freq_to_nearest_midi(freq: float) -> int:
    """Convert frequency to nearest MIDI note number.

    Args:
        freq: Frequency in Hz.

    Returns:
        MIDI note number (0-127).
    """
    import math

    midi = 69 + 12 * math.log2(freq / 440.0)
    return max(0, min(127, round(midi)))
