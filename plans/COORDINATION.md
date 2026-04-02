# Agent Coordination

Active plans being worked in parallel. Check file ownership before editing.

## Active Agents

### Agent A — ACE-Step Modes (`plans/acestep-modes.md`)
**Working on:** Phase 2 (Repaint Mode)
**Owns:**
- `src/songmaker_cli/acestep_manager.py`
- `src/songmaker_cli/config.py`
- `src/songmaker_cli/generation_api.py`
- `src/songmaker_cli/music_worker.py`
- `src/songmaker_cli/jobs.py`
- `src/songmaker_cli/generate.py`
- `src/acestep_engine/` (client, models)
- `frontend/src/lib/components/GenerationSettings.svelte`
- `frontend/src/lib/components/ParamControls.svelte`
- `frontend/src/lib/components/PresetChips.svelte`
- `frontend/src/lib/components/GenerationsList.svelte`
- `frontend/src/routes/+page.svelte` (generate button area, model dropdown)

### Agent B — Co-writer UX (`plans/cowriter-ux.md`)
**Owns:**
- `frontend/src/lib/components/ClaudeChat.svelte`
- `src/songmaker_cli/chat_api.py` (if exists)
- Co-writer related stores and components

## Shared Files (coordinate before editing)
- `src/songmaker_cli/api_models/songs.py` — both may add fields
- `src/songmaker_cli/db/models.py` — both may add columns
- `src/songmaker_cli/db/queries/generations.py` — both may add query params
- `frontend/src/lib/api/client.ts` — both may add API functions
- `frontend/src/lib/api/types.ts` — auto-generated, regenerate after changes
- `frontend/src/routes/+page.svelte` — large file, different sections
