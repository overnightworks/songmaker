# ACE-Step Base Model Tasks — Lego, Extract, Complete

**Status:** Proposed
**Date:** 2026-04-09

## Goal

Expose ACE-Step's Base-model-only audio manipulation tasks: Lego (layer instruments), Extract (stem separation), Complete (add accompaniment). These require the Base DiT model (`acestep-v15-base`), which is not currently deployed.

## What These Modes Do

| Mode | task_type | Requires | What It Does |
|------|-----------|----------|--------------|
| Lego | `lego` | src_audio + start/end | Add new instrument tracks on top of existing audio |
| Extract | `extract` | src_audio | Separate stems from mixed audio (vocals, drums, bass, etc.) |
| Complete | `complete` | src_audio | Generate full accompaniment around a solo instrument/vocal |

## Why Deferred

- Require Base model download + deployment (Turbo/SFT don't support these tasks)
- Niche audio engineering tools — lower priority than Cover/Repaint workflows
- Need a separate "Audio Tools" UI panel (different interaction model from generation)
- Model switching architecture (from acestep-modes plan) is a prerequisite

## Prerequisites

- Model switching must work (acestep-modes Phase 1)
- Base model must be downloadable + configurable
- File upload for src_audio (shared with Cover/Repaint)

## Implementation Sketch

- Auto-detect task_type → validate Base model is active, reject otherwise
- Dedicated "Audio Tools" panel in frontend (not generation settings)
- Lego: waveform selection (time range) + prompt for what to add
- Extract: upload/select audio → get back separated stems
- Complete: upload/select solo track → get full arrangement
