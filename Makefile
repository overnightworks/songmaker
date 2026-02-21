# Songmaker — Common Tasks
# Usage: make sync | make sync-all | make test

PYTHON = .venv/Scripts/python.exe

.PHONY: sync sync-all test clean

## Install core + RVC dependencies, patch fairseq for Python 3.12
sync:
	uv sync
	$(PYTHON) scripts/patch_fairseq.py

## Install all dependencies (including XTTS, MusicGen, Demucs)
sync-all:
	uv sync --all-extras
	$(PYTHON) scripts/patch_fairseq.py

## Run tests
test:
	$(PYTHON) -m pytest

## Remove generated audio temp files
clean:
	rm -rf _temp_bark _temp_musicgen _temp_demucs
