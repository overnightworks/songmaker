<script lang="ts">
	import ParamControls from './ParamControls.svelte';
	import type { VersionGenerationParams } from '$lib/api/types';

	interface Props {
		globalDefaults: Record<string, VersionGenerationParams>;
		builtins: Record<string, Required<VersionGenerationParams>>;
		onclose: () => void;
		onsave: (updated: Record<string, VersionGenerationParams>) => void;
	}

	let { globalDefaults, builtins, onclose, onsave }: Props = $props();

	let editModel = $state<'turbo' | 'sft'>('turbo');
	let editDefaults = $state<VersionGenerationParams>({});
	let saving = $state(false);
	let initialized = false;

	$effect(() => {
		if (!initialized && globalDefaults) {
			editDefaults = { ...(globalDefaults.turbo ?? {}) };
			initialized = true;
		}
	});

	function switchModel(model: 'turbo' | 'sft'): void {
		editModel = model;
		editDefaults = { ...(globalDefaults[model] ?? {}) };
	}

	async function save(): Promise<void> {
		saving = true;
		try {
			const cleaned = Object.keys(editDefaults).length > 0 ? editDefaults : {};
			await onsave({ ...globalDefaults, [editModel]: cleaned });
		} finally {
			saving = false;
		}
	}
</script>

<div class="panel">
	<div class="panel-header">
		<span>Global Defaults</span>
		<div class="model-tabs">
			<button
				class="model-tab"
				class:active={editModel === 'turbo'}
				onclick={() => switchModel('turbo')}
			>
				Turbo
			</button>
			<button
				class="model-tab"
				class:active={editModel === 'sft'}
				onclick={() => switchModel('sft')}
			>
				SFT
			</button>
		</div>
	</div>

	<ParamControls
		values={editDefaults}
		placeholders={builtins[editModel]}
		onchange={(p) => (editDefaults = p)}
	/>

	<div class="actions-row">
		<button class="save-btn" onclick={save} disabled={saving}>
			{saving ? 'Saving...' : 'Save Defaults'}
		</button>
		<button class="cancel-btn" onclick={onclose}>Cancel</button>
	</div>
</div>

<style>
	.panel {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
	}

	.panel-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.panel-header span {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.model-tabs {
		display: flex;
		gap: 4px;
	}

	.model-tab {
		padding: 2px 8px;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: transparent;
		color: var(--text-muted);
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.model-tab.active {
		border-color: var(--primary);
		color: var(--primary);
	}

	.actions-row {
		display: flex;
		gap: 8px;
	}

	.save-btn {
		padding: 3px 10px;
		border: 1px solid var(--primary);
		border-radius: 4px;
		background: var(--primary);
		color: #fff;
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.save-btn:disabled {
		opacity: 0.4;
	}

	.cancel-btn {
		padding: 3px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.cancel-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}
</style>
