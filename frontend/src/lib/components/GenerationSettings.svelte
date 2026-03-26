<script lang="ts">
	import { onMount } from 'svelte';
	import { editGenParams } from '$lib/stores/editor';
	import {
		presets,
		builtinDefaults,
		loadPresets,
		loadBuiltins,
		savePreset,
		setDefault,
		deletePreset
	} from '$lib/stores/presets';
	import { fetchGenerationDefaults, updateGenerationDefaults } from '$lib/api/client';
	import type { VersionGenerationParams } from '$lib/api/types';

	let open = $state(false);
	let showDefaults = $state(false);
	let savingDefaults = $state(false);
	let showSavePreset = $state(false);
	let presetName = $state('');
	let presetAsDefault = $state(false);
	let savingPreset = $state(false);

	const FALLBACK_DEFAULTS: Record<string, Required<VersionGenerationParams>> = {
		turbo: {
			inference_steps: 8,
			guidance_scale: 0.0,
			shift: 3.0,
			think_mode: 'deep',
			lm_temperature: 0.85,
			lm_top_k: 0,
			lm_top_p: 0.9,
			lm_cfg_scale: 2.0,
			lm_negative_prompt: '',
			infer_method: 'ode',
			batch_size: 1
		},
		sft: {
			inference_steps: 50,
			guidance_scale: 0.0,
			shift: 3.0,
			think_mode: 'deep',
			lm_temperature: 0.85,
			lm_top_k: 0,
			lm_top_p: 0.9,
			lm_cfg_scale: 2.0,
			lm_negative_prompt: '',
			infer_method: 'ode',
			batch_size: 1
		}
	};

	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});

	const builtins = $derived.by((): Record<string, Required<VersionGenerationParams>> => {
		const b = $builtinDefaults;
		return {
			turbo: {
				...FALLBACK_DEFAULTS.turbo,
				...(b.turbo ?? {})
			} as Required<VersionGenerationParams>,
			sft: { ...FALLBACK_DEFAULTS.sft, ...(b.sft ?? {}) } as Required<VersionGenerationParams>
		};
	});

	const effectiveDefaults = $derived.by((): Required<VersionGenerationParams> => {
		return {
			...builtins.turbo,
			...(globalDefaults.turbo ?? {})
		} as Required<VersionGenerationParams>;
	});

	const modePresets = $derived.by(() => {
		return {
			turbo: $presets.filter((p) => p.model_mode === 'turbo'),
			sft: $presets.filter((p) => p.model_mode === 'sft')
		};
	});

	onMount(async () => {
		await Promise.all([
			loadBuiltins(),
			loadPresets(),
			fetchGenerationDefaults()
				.then((d) => (globalDefaults = d))
				.catch(() => {})
		]);
	});

	function getParam<K extends keyof VersionGenerationParams>(
		key: K
	): VersionGenerationParams[K] | undefined {
		return $editGenParams?.[key];
	}

	function setParam<K extends keyof VersionGenerationParams>(
		key: K,
		value: VersionGenerationParams[K] | undefined
	): void {
		const current = $editGenParams ?? {};
		if (value === undefined) {
			const { [key]: _, ...rest } = current;
			$editGenParams = Object.keys(rest).length > 0 ? rest : null;
		} else {
			$editGenParams = { ...current, [key]: value };
		}
	}

	function handleNumber(key: keyof VersionGenerationParams, raw: string): void {
		if (raw === '') {
			setParam(key, undefined);
		} else {
			const num = Number(raw);
			if (!isNaN(num)) setParam(key, num as never);
		}
	}

	const hasOverrides = $derived(
		$editGenParams !== null && Object.keys($editGenParams ?? {}).length > 0
	);

	let editModel = $state<'turbo' | 'sft'>('turbo');
	let editDefaults = $state<VersionGenerationParams>({});

	function openDefaults(): void {
		editModel = 'turbo';
		editDefaults = { ...(globalDefaults.turbo ?? {}) };
		showDefaults = true;
	}

	function switchModel(model: 'turbo' | 'sft'): void {
		editModel = model;
		editDefaults = { ...(globalDefaults[model] ?? {}) };
	}

	function setDefaultNum(key: keyof VersionGenerationParams, raw: string): void {
		if (raw === '') {
			const { [key]: _, ...rest } = editDefaults;
			editDefaults = rest;
		} else {
			const num = Number(raw);
			if (!isNaN(num)) editDefaults = { ...editDefaults, [key]: num };
		}
	}

	function setDefaultVal(key: keyof VersionGenerationParams, val: unknown): void {
		if (val === undefined || val === '') {
			const { [key]: _, ...rest } = editDefaults;
			editDefaults = rest;
		} else {
			editDefaults = { ...editDefaults, [key]: val };
		}
	}

	async function saveDefaults(): Promise<void> {
		savingDefaults = true;
		try {
			const cleaned = Object.keys(editDefaults).length > 0 ? editDefaults : undefined;
			const data = { ...globalDefaults, [editModel]: cleaned ?? {} };
			globalDefaults = await updateGenerationDefaults(data);
			showDefaults = false;
		} catch {
			/* save failed */
		} finally {
			savingDefaults = false;
		}
	}

	function loadPresetParams(presetId: string): void {
		const preset = $presets.find((p) => p.id === presetId);
		if (preset) {
			$editGenParams = { ...preset.params };
		}
	}

	async function handleSavePreset(): Promise<void> {
		if (!presetName.trim()) return;
		savingPreset = true;
		try {
			await savePreset(presetName.trim(), 'turbo', $editGenParams ?? {}, presetAsDefault);
			showSavePreset = false;
			presetName = '';
			presetAsDefault = false;
		} catch {
			/* save failed */
		} finally {
			savingPreset = false;
		}
	}

	async function handleSetDefault(presetId: string): Promise<void> {
		try {
			await setDefault(presetId);
		} catch {
			/* failed */
		}
	}

	async function handleDeletePreset(presetId: string): Promise<void> {
		try {
			await deletePreset(presetId);
		} catch {
			/* failed */
		}
	}
</script>

<div class="gen-settings">
	<button class="toggle" onclick={() => (open = !open)} aria-expanded={open}>
		<span class="toggle-icon">{open ? '▾' : '▸'}</span>
		<span>Generation Settings</span>
		{#if hasOverrides}
			<span class="override-badge">custom</span>
		{/if}
	</button>

	{#if open}
		{#if modePresets.turbo.length > 0}
			<div class="presets-row">
				<span class="presets-label">Presets:</span>
				{#each modePresets.turbo as preset (preset.id)}
					<button
						class="preset-chip"
						class:is-default={preset.is_default}
						onclick={() => loadPresetParams(preset.id)}
						title="Load preset"
					>
						{preset.name}
						{#if preset.is_default}*{/if}
					</button>
				{/each}
			</div>
		{/if}

		<div class="settings-grid">
			<label class="setting">
				<span>Inference Steps</span>
				<input
					type="number"
					min="1"
					max="200"
					value={getParam('inference_steps') ?? ''}
					placeholder={String(effectiveDefaults.inference_steps)}
					oninput={(e) => handleNumber('inference_steps', e.currentTarget.value)}
				/>
			</label>

			<label class="setting">
				<span>Guidance Scale</span>
				<input
					type="number"
					min="0"
					step="0.5"
					value={getParam('guidance_scale') ?? ''}
					placeholder={String(effectiveDefaults.guidance_scale)}
					oninput={(e) => handleNumber('guidance_scale', e.currentTarget.value)}
				/>
			</label>

			<label class="setting">
				<span>Shift</span>
				<input
					type="number"
					min="0"
					step="0.5"
					value={getParam('shift') ?? ''}
					placeholder={String(effectiveDefaults.shift)}
					oninput={(e) => handleNumber('shift', e.currentTarget.value)}
				/>
			</label>

			<label class="setting">
				<span>LM Temperature</span>
				<input
					type="number"
					min="0"
					max="2"
					step="0.05"
					value={getParam('lm_temperature') ?? ''}
					placeholder={String(effectiveDefaults.lm_temperature)}
					oninput={(e) => handleNumber('lm_temperature', e.currentTarget.value)}
				/>
			</label>

			<label class="setting">
				<span>Infer Method</span>
				<select
					value={getParam('infer_method') ?? ''}
					onchange={(e) => {
						const val = e.currentTarget.value;
						setParam('infer_method', val || undefined);
					}}
				>
					<option value="">default ({effectiveDefaults.infer_method})</option>
					<option value="ode">ode</option>
					<option value="sde">sde</option>
				</select>
			</label>

			<label class="setting">
				<span>Think Mode</span>
				<select
					value={getParam('think_mode') ?? ''}
					onchange={(e) => {
						const val = e.currentTarget.value;
						setParam('think_mode', val || undefined);
					}}
				>
					<option value="">default ({effectiveDefaults.think_mode})</option>
					<option value="deep">deep</option>
					<option value="off">off</option>
				</select>
			</label>

			<label class="setting">
				<span>LM Top-K</span>
				<input
					type="number"
					min="0"
					max="200"
					value={getParam('lm_top_k') ?? ''}
					placeholder={String(effectiveDefaults.lm_top_k)}
					oninput={(e) => handleNumber('lm_top_k', e.currentTarget.value)}
				/>
			</label>

			<label class="setting">
				<span>LM Top-P</span>
				<input
					type="number"
					min="0"
					max="1"
					step="0.05"
					value={getParam('lm_top_p') ?? ''}
					placeholder={String(effectiveDefaults.lm_top_p)}
					oninput={(e) => handleNumber('lm_top_p', e.currentTarget.value)}
				/>
			</label>

			<label class="setting">
				<span>LM CFG Scale</span>
				<input
					type="number"
					min="0"
					max="10"
					step="0.5"
					value={getParam('lm_cfg_scale') ?? ''}
					placeholder={String(effectiveDefaults.lm_cfg_scale)}
					oninput={(e) => handleNumber('lm_cfg_scale', e.currentTarget.value)}
				/>
			</label>

			<label class="setting">
				<span>Batch Size</span>
				<input
					type="number"
					min="1"
					max="8"
					value={getParam('batch_size') ?? ''}
					placeholder={String(effectiveDefaults.batch_size)}
					oninput={(e) => handleNumber('batch_size', e.currentTarget.value)}
				/>
			</label>

			<label class="setting full-width">
				<span>LM Negative Prompt</span>
				<input
					type="text"
					value={getParam('lm_negative_prompt') ?? ''}
					placeholder="e.g. bad quality, noise"
					oninput={(e) => {
						const val = e.currentTarget.value;
						setParam('lm_negative_prompt', val || undefined);
					}}
				/>
			</label>
		</div>

		<div class="actions-row">
			{#if hasOverrides}
				<button class="reset-btn" onclick={() => ($editGenParams = null)}>
					Reset to defaults
				</button>
				<button class="reset-btn" onclick={() => (showSavePreset = true)}> Save as preset </button>
			{/if}
			<button class="reset-btn" onclick={openDefaults}> Edit global defaults </button>
		</div>

		{#if showSavePreset}
			<div class="defaults-panel">
				<div class="defaults-header">
					<span>Save Preset</span>
				</div>
				<div class="save-preset-form">
					<input
						type="text"
						placeholder="Preset name"
						bind:value={presetName}
						class="preset-name-input"
					/>
					<label class="preset-default-label">
						<input type="checkbox" bind:checked={presetAsDefault} />
						<span>Set as default</span>
					</label>
				</div>
				<div class="actions-row">
					<button
						class="save-defaults-btn"
						onclick={handleSavePreset}
						disabled={savingPreset || !presetName.trim()}
					>
						{savingPreset ? 'Saving...' : 'Save'}
					</button>
					<button class="reset-btn" onclick={() => (showSavePreset = false)}> Cancel </button>
				</div>
			</div>
		{/if}

		{#if modePresets.turbo.length > 0}
			<div class="defaults-panel">
				<div class="defaults-header">
					<span>Saved Presets</span>
				</div>
				<div class="preset-list">
					{#each modePresets.turbo as preset (preset.id)}
						<div class="preset-row">
							<span class="preset-name">{preset.name}</span>
							{#if !preset.is_default}
								<button
									class="preset-action"
									onclick={() => handleSetDefault(preset.id)}
									title="Set as default"
								>
									set default
								</button>
							{:else}
								<span class="preset-default-tag">default</span>
							{/if}
							<button
								class="preset-action delete"
								onclick={() => handleDeletePreset(preset.id)}
								title="Delete preset"
							>
								delete
							</button>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		{#if showDefaults}
			<div class="defaults-panel">
				<div class="defaults-header">
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

				<div class="settings-grid">
					<label class="setting">
						<span>Inference Steps</span>
						<input
							type="number"
							min="1"
							max="200"
							value={editDefaults.inference_steps ?? ''}
							placeholder={String(builtins[editModel].inference_steps)}
							oninput={(e) => setDefaultNum('inference_steps', e.currentTarget.value)}
						/>
					</label>
					<label class="setting">
						<span>Guidance Scale</span>
						<input
							type="number"
							min="0"
							step="0.5"
							value={editDefaults.guidance_scale ?? ''}
							placeholder={String(builtins[editModel].guidance_scale)}
							oninput={(e) => setDefaultNum('guidance_scale', e.currentTarget.value)}
						/>
					</label>
					<label class="setting">
						<span>Shift</span>
						<input
							type="number"
							min="0"
							step="0.5"
							value={editDefaults.shift ?? ''}
							placeholder={String(builtins[editModel].shift)}
							oninput={(e) => setDefaultNum('shift', e.currentTarget.value)}
						/>
					</label>
					<label class="setting">
						<span>LM Temperature</span>
						<input
							type="number"
							min="0"
							max="2"
							step="0.05"
							value={editDefaults.lm_temperature ?? ''}
							placeholder={String(builtins[editModel].lm_temperature)}
							oninput={(e) => setDefaultNum('lm_temperature', e.currentTarget.value)}
						/>
					</label>
					<label class="setting">
						<span>Infer Method</span>
						<select
							value={editDefaults.infer_method ?? ''}
							onchange={(e) => setDefaultVal('infer_method', e.currentTarget.value || undefined)}
						>
							<option value="">default ({builtins[editModel].infer_method})</option>
							<option value="ode">ode</option>
							<option value="sde">sde</option>
						</select>
					</label>
					<label class="setting">
						<span>Think Mode</span>
						<select
							value={editDefaults.think_mode ?? ''}
							onchange={(e) => setDefaultVal('think_mode', e.currentTarget.value || undefined)}
						>
							<option value="">default ({builtins[editModel].think_mode})</option>
							<option value="deep">deep</option>
							<option value="off">off</option>
						</select>
					</label>
					<label class="setting">
						<span>LM Top-K</span>
						<input
							type="number"
							min="0"
							max="200"
							value={editDefaults.lm_top_k ?? ''}
							placeholder={String(builtins[editModel].lm_top_k)}
							oninput={(e) => setDefaultNum('lm_top_k', e.currentTarget.value)}
						/>
					</label>
					<label class="setting">
						<span>LM Top-P</span>
						<input
							type="number"
							min="0"
							max="1"
							step="0.05"
							value={editDefaults.lm_top_p ?? ''}
							placeholder={String(builtins[editModel].lm_top_p)}
							oninput={(e) => setDefaultNum('lm_top_p', e.currentTarget.value)}
						/>
					</label>
					<label class="setting">
						<span>LM CFG Scale</span>
						<input
							type="number"
							min="0"
							max="10"
							step="0.5"
							value={editDefaults.lm_cfg_scale ?? ''}
							placeholder={String(builtins[editModel].lm_cfg_scale)}
							oninput={(e) => setDefaultNum('lm_cfg_scale', e.currentTarget.value)}
						/>
					</label>
					<label class="setting">
						<span>Batch Size</span>
						<input
							type="number"
							min="1"
							max="8"
							value={editDefaults.batch_size ?? ''}
							placeholder={String(builtins[editModel].batch_size)}
							oninput={(e) => setDefaultNum('batch_size', e.currentTarget.value)}
						/>
					</label>
				</div>

				<div class="actions-row">
					<button class="save-defaults-btn" onclick={saveDefaults} disabled={savingDefaults}>
						{savingDefaults ? 'Saving...' : 'Save Defaults'}
					</button>
					<button class="reset-btn" onclick={() => (showDefaults = false)}> Cancel </button>
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.gen-settings {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.toggle:hover {
		color: var(--text);
	}

	.toggle-icon {
		font-size: 10px;
		width: 10px;
	}

	.override-badge {
		font-size: 9px;
		padding: 1px 5px;
		border-radius: 3px;
		background: var(--primary);
		color: #fff;
		letter-spacing: 0.5px;
	}

	.presets-row {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}

	.presets-label {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.preset-chip {
		padding: 2px 8px;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: transparent;
		color: var(--text-muted);
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
	}

	.preset-chip:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-chip.is-default {
		border-color: var(--primary);
		color: var(--primary);
	}

	.settings-grid {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		gap: 8px;
	}

	.setting {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.setting span {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.setting.full-width {
		grid-column: 1 / -1;
	}

	.setting input[type='text'],
	.setting input[type='number'],
	.setting select {
		padding: 5px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
		width: 100%;
	}

	.setting input:focus,
	.setting select:focus {
		border-color: var(--primary);
		outline: none;
	}

	.actions-row {
		display: flex;
		gap: 8px;
	}

	.reset-btn {
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

	.reset-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.defaults-panel {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
	}

	.defaults-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.defaults-header span {
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

	.save-defaults-btn {
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

	.save-defaults-btn:disabled {
		opacity: 0.4;
	}

	.save-preset-form {
		display: flex;
		gap: 8px;
		align-items: center;
	}

	.preset-name-input {
		padding: 5px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
		flex: 1;
	}

	.preset-name-input:focus {
		border-color: var(--primary);
		outline: none;
	}

	.preset-default-label {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 10px;
		color: var(--text-muted);
		cursor: pointer;
		white-space: nowrap;
	}

	.preset-list {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.preset-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 0;
	}

	.preset-name {
		flex: 1;
		font-size: 12px;
		color: var(--text);
	}

	.preset-default-tag {
		font-size: 9px;
		padding: 1px 5px;
		border-radius: 3px;
		background: var(--primary);
		color: #fff;
		letter-spacing: 0.5px;
	}

	.preset-action {
		padding: 1px 6px;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: transparent;
		color: var(--text-muted);
		font-size: 9px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
	}

	.preset-action:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-action.delete:hover {
		border-color: var(--danger, #e74c3c);
		color: var(--danger, #e74c3c);
	}
</style>
