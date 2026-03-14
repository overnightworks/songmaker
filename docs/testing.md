# Songmaker — Testing Guide

## Goal
100% test coverage on all `src/` modules.

## Running Tests
```bash
.venv/bin/pytest

.venv/bin/pytest --cov=src --cov-report=term-missing

.venv/bin/pytest tests/test_mastering.py -v
```

## Structure
Tests mirror `src/` layout:
```
tests/
├── acestep_engine/
│   ├── test_client.py          # HTTP client, task polling
│   └── test_models.py          # AceStepConfig validation
├── audio_engine/
│   ├── test_audio_io.py        # WAV/MP3 read/write, mastering
│   ├── test_mastering.py       # Mastering chain (LUFS, compression)
│   └── test_constants.py       # Sample rate constants
├── songmaker_cli/
│   ├── test_generate.py        # Generate command
│   ├── test_parser.py          # Markdown/YAML parsing, SongMeta
│   ├── test_config.py          # OutputPaths, build_ace_config
│   └── test_player.py          # HTML player generation
└── conftest.py                 # Shared fixtures
```

## Rules

1. **Every public function gets a test.** No exceptions.
2. **Mock external services.** ACE-Step server, ffmpeg, Whisper — never call real services in tests.
3. **Tests must be fast.** Full suite < 10 seconds.
4. **No test inheritance.** Use pytest fixtures and parametrize.
5. **Arrange-Act-Assert pattern.** Three clear sections per test.
6. **Descriptive test names.** `test_master_to_mp3_applies_lufs_normalization` not `test_master`.
7. **Test edge cases.** Empty input, zero duration, missing files, invalid config.
8. **Use fixtures for audio data.** Create small numpy arrays (0.1s), not real audio files.

## Fixtures (conftest.py)

```python
@pytest.fixture
def silence_mono():
    """0.1s of silence at 44100 Hz."""
    return np.zeros(4410, dtype=np.float32)

@pytest.fixture
def sine_wave():
    """0.1s 440Hz sine wave at 44100 Hz."""
    t = np.linspace(0, 0.1, 4410, endpoint=False)
    return np.sin(2 * np.pi * 440 * t).astype(np.float32)

@pytest.fixture
def tmp_wav(tmp_path, sine_wave):
    """Write a temporary WAV file."""
    path = tmp_path / "test.wav"
    sf.write(str(path), sine_wave, 44100)
    return path
```

## Coverage Targets

| Module | Current | Target |
|--------|---------|--------|
| acestep_engine | 0% | 100% |
| audio_engine | ~10% | 100% |
| songmaker_cli | 0% | 100% |
