"""SoundFont and FluidSynth validation and health-check utilities.

Provides diagnostic tools to verify FluidSynth installation, SoundFont
availability, and end-to-end rendering capability. Designed to produce
actionable error messages that guide users through setup.

Can be run standalone::

    python source_files/instrumental_engine/soundfont_validator.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from instrumental_engine.constants import SAMPLE_RATE
from instrumental_engine.soundfont_engine import (
    SOUNDFONT_PRIORITY,
    FLUIDSYNTH_CHECK_CMD,
    write_midi_file,
)


SOUNDFONTS_DIRECTORY: Final[str] = "soundfonts"

FLUIDSYNTH_INSTALL_INSTRUCTIONS: Final[str] = (
    """
╔══════════════════════════════════════════════════════════════════╗
║  FluidSynth is REQUIRED for SoundFont instrument rendering.    ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Windows (recommended):                                          ║
║    winget install FluidSynth.FluidSynth                          ║
║                                                                  ║
║  Windows (manual):                                               ║
║    1. Download from:                                             ║
║       https://github.com/FluidSynth/fluidsynth/releases         ║
║    2. Extract to C:\\tools\\fluidsynth (or any location)          ║
║    3. Add the 'bin' folder to your system PATH                   ║
║                                                                  ║
║  macOS:                                                          ║
║    brew install fluid-synth                                      ║
║                                                                  ║
║  Linux (Debian/Ubuntu):                                          ║
║    sudo apt-get install -y fluidsynth                            ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
""".strip()
)

SOUNDFONT_DOWNLOAD_INSTRUCTIONS: Final[str] = (
    """
╔══════════════════════════════════════════════════════════════════╗
║  No SoundFont (.sf2) files found in 'soundfonts/' directory.   ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  Download a General MIDI SoundFont:                              ║
║                                                                  ║
║  FluidR3_GM.sf2 (~140 MB, recommended):                          ║
║    https://member.keymusician.com/Member/FluidR3_GM/FluidR3_GM.sf2║
║                                                                  ║
║  GeneralUser_GS.sf2 (~30 MB, lightweight):                       ║
║    https://generaluser.sourceforge.io/                            ║
║                                                                  ║
║  Timbres of Heaven (~350 MB, highest quality):                    ║
║    https://midkar.com/soundfonts/                                ║
║                                                                  ║
║  Place the .sf2 file in the 'soundfonts/' directory:             ║
║    soundfonts/FluidR3_GM.sf2                                     ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
""".strip()
)

_C_MAJOR_SCALE_NOTES: Final[list[tuple[int, float, float, float]]] = [
    (60, 0.0, 0.4, 0.8),
    (62, 0.5, 0.4, 0.8),
    (64, 1.0, 0.4, 0.8),
    (65, 1.5, 0.4, 0.8),
    (67, 2.0, 0.4, 0.8),
    (69, 2.5, 0.4, 0.8),
    (71, 3.0, 0.4, 0.8),
    (72, 3.5, 0.8, 0.8),
]


class SoundFontSetupError(RuntimeError):
    """Raised when FluidSynth or SoundFont setup is incomplete."""


@dataclass(frozen=True)
class SoundFontHealth:
    """Result of a SoundFont system health check.

    Attributes:
        fluidsynth_installed: Whether FluidSynth CLI is on PATH.
        fluidsynth_version: Version string if installed, empty otherwise.
        soundfont_path: Path to discovered .sf2 file, or None.
        render_test_passed: Whether a test render completed successfully.
        status: Overall status summary.
        details: Human-readable diagnostic details.
    """

    fluidsynth_installed: bool
    fluidsynth_version: str
    soundfont_path: Path | None
    render_test_passed: bool
    status: str
    details: str


def detect_fluidsynth_version() -> str:
    """Detect FluidSynth CLI version string.

    Returns:
        Version string (e.g. "2.3.4") or empty string if not found.
    """
    try:
        result = subprocess.run(
            [FLUIDSYNTH_CHECK_CMD, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip() or result.stderr.strip()
        for line in output.splitlines():
            if "fluidsynth" in line.lower() or "version" in line.lower():
                return line.strip()
        return output.splitlines()[0].strip() if output else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, IndexError):
        return ""


def scan_soundfonts() -> list[Path]:
    """Scan the soundfonts directory for .sf2 files.

    Returns:
        List of discovered SoundFont file paths.
    """
    sf_dir = Path(SOUNDFONTS_DIRECTORY)
    if not sf_dir.is_dir():
        return []
    return sorted(sf_dir.glob("*.sf2"))


def find_best_soundfont() -> Path | None:
    """Locate the best available SoundFont file.

    Checks the known search paths first, then scans the soundfonts directory.

    Returns:
        Path to SoundFont file, or None if not found.
    """
    for sf_path_str in SOUNDFONT_PRIORITY:
        path = Path(sf_path_str)
        if path.exists():
            return path

    discovered = scan_soundfonts()
    return discovered[0] if discovered else None


def test_render(soundfont_path: Path) -> bool:
    """Test FluidSynth rendering by generating a C major scale to WAV.

    Args:
        soundfont_path: Path to SoundFont file.

    Returns:
        True if rendering succeeded and produced a non-empty WAV.
    """
    with tempfile.TemporaryDirectory(prefix="_sf_validate_") as tmpdir:
        tmp = Path(tmpdir)
        midi_path = tmp / "test_scale.mid"
        wav_path = tmp / "test_output.wav"

        write_midi_file(midi_path, list(_C_MAJOR_SCALE_NOTES), program=0, bpm=120)

        try:
            subprocess.run(
                [
                    "fluidsynth",
                    "-ni",
                    "-g",
                    "1.0",
                    "-r",
                    str(SAMPLE_RATE),
                    "-F",
                    str(wav_path),
                    str(soundfont_path),
                    str(midi_path),
                ],
                check=True,
                capture_output=True,
                timeout=15,
            )
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            return False

        return wav_path.exists() and wav_path.stat().st_size > 100


def check_soundfont_health() -> SoundFontHealth:
    """Run a comprehensive health check on the SoundFont rendering stack.

    Checks FluidSynth installation, SoundFont availability, and
    performs a test render. Returns a diagnostic result with actionable
    information.

    Returns:
        Complete health check result.
    """
    version = detect_fluidsynth_version()
    fluidsynth_ok = bool(version)
    soundfont_path = find_best_soundfont()
    render_ok = False
    details_parts: list[str] = []

    if fluidsynth_ok:
        details_parts.append(f"✅ FluidSynth found: {version}")
    else:
        details_parts.append("❌ FluidSynth not found on PATH")
        details_parts.append(FLUIDSYNTH_INSTALL_INSTRUCTIONS)

    if soundfont_path is not None:
        size_mb = soundfont_path.stat().st_size / (1024 * 1024)
        details_parts.append(f"✅ SoundFont found: {soundfont_path} ({size_mb:.1f} MB)")
    else:
        details_parts.append("❌ No SoundFont (.sf2) files found")
        details_parts.append(SOUNDFONT_DOWNLOAD_INSTRUCTIONS)

    if fluidsynth_ok and soundfont_path is not None:
        render_ok = test_render(soundfont_path)
        if render_ok:
            details_parts.append("✅ Test render: C major scale rendered successfully")
        else:
            details_parts.append(
                "❌ Test render failed: FluidSynth could not produce output"
            )

    if render_ok:
        status = "ready"
    elif not fluidsynth_ok:
        status = "missing_fluidsynth"
    elif soundfont_path is None:
        status = "missing_soundfont"
    else:
        status = "render_failed"

    return SoundFontHealth(
        fluidsynth_installed=fluidsynth_ok,
        fluidsynth_version=version,
        soundfont_path=soundfont_path,
        render_test_passed=render_ok,
        status=status,
        details="\n".join(details_parts),
    )


def require_soundfont_setup() -> tuple[Path, str]:
    """Require FluidSynth and SoundFont or raise with setup instructions.

    This is the primary entry point for code that needs SoundFont rendering.
    It validates the entire stack and raises a descriptive error if any
    component is missing.

    Returns:
        Tuple of (soundfont_path, fluidsynth_version).

    Raises:
        SoundFontSetupError: With installation instructions if setup incomplete.
    """
    health = check_soundfont_health()

    if health.status == "ready":
        assert health.soundfont_path is not None
        return health.soundfont_path, health.fluidsynth_version

    error_parts = [
        "SoundFont rendering is not available.",
        "",
        health.details,
        "",
        "Run the validator for full diagnostics:",
        "  python source_files/instrumental_engine/soundfont_validator.py",
        "",
        "See docs/soundfont_setup.md for the complete setup guide.",
    ]
    raise SoundFontSetupError("\n".join(error_parts))


def _print_health_report(health: SoundFontHealth) -> None:
    """Print a formatted health report to stdout.

    Args:
        health: Health check result to display.

    Side Effects:
        Writes formatted report to stdout.
    """
    print("=" * 64)
    print("  SoundFont Rendering — Health Check Report")
    print("=" * 64)
    print()
    print(health.details)
    print()
    print("-" * 64)

    status_labels = {
        "ready": "✅ READY — SoundFont rendering is fully operational",
        "missing_fluidsynth": "❌ FAILED — FluidSynth is not installed",
        "missing_soundfont": "❌ FAILED — No SoundFont files available",
        "render_failed": "❌ FAILED — FluidSynth render test did not succeed",
    }
    print(f"  Status: {status_labels.get(health.status, health.status)}")
    print("=" * 64)


def main() -> None:
    """Run standalone health check and print report.

    Side Effects:
        Prints diagnostic report to stdout.
        Exits with code 0 on success, 1 on failure.
    """
    health = check_soundfont_health()
    _print_health_report(health)

    raise SystemExit(0 if health.status == "ready" else 1)


if __name__ == "__main__":
    main()
