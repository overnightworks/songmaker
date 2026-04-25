<script lang="ts">
	import {
		editLyrics,
		editPrompt,
		editBpm,
		editAudioDuration,
		editKeyScale,
		setDraftLyrics,
		setDraftPrompt,
		setDraftBpm,
		setDraftAudioDuration,
		setDraftKeyScale,
		versions,
		currentVersionIndex,
		isDirty,
		diffMode,
		appliedDiffMode,
		activeDiff,
		loadVersion,
		handleDiffChange
	} from '$lib/stores/editor';
	import type { GenerationItem, SongItem, VersionGenerationParams } from '$lib/api/types';
	import GenerationSettings from '$lib/components/GenerationSettings.svelte';
	import WaveformRangePicker from '$lib/components/WaveformRangePicker.svelte';
	import LyricsDiff from '$lib/components/LyricsDiff.svelte';
	import VersionTimeline from '$lib/components/VersionTimeline.svelte';

	interface Props {
		ondeleteversion: (versionId: string, deleteGenerations: boolean) => void;
		selectedModel?: string | null;
		song?: SongItem | null;
		sourceGeneration?: GenerationItem | null;
		sourceMode?: 'repaint' | 'cover';
		repaintStart?: number;
		repaintEnd?: number;
		coverStrength?: number;
		repaintMode?: string;
		repaintStrength?: number;
		coverNoiseStrength?: number;
		onrepaintrangechange?: (start: number, end: number) => void;
		oncoverstrengthchange?: (strength: number) => void;
		onrepaintmodechange?: (mode: string) => void;
		onrepaintstrengthchange?: (strength: number) => void;
		oncovernoisestrengthchange?: (strength: number) => void;
		onsourcemodechange?: (mode: 'repaint' | 'cover') => void;
		onsourceclear?: () => void;
		onsourceselect?: (gen: GenerationItem) => void;
	}

	let {
		ondeleteversion,
		selectedModel = null,
		song = null,
		sourceGeneration = null,
		sourceMode = 'repaint',
		repaintStart = 0,
		repaintEnd = 1,
		coverStrength = 0.7,
		repaintMode = '',
		repaintStrength = 0.5,
		coverNoiseStrength = 0,
		onrepaintrangechange,
		oncoverstrengthchange,
		onrepaintmodechange,
		onrepaintstrengthchange,
		oncovernoisestrengthchange,
		onsourcemodechange,
		onsourceclear,
		onsourceselect
	}: Props = $props();

	let showSourcePicker = $state(false);

	const generations = $derived(song?.generations?.filter((g) => g.status === 'completed') ?? []);

	const vers = $derived($versions);
	const verIndex = $derived($currentVersionIndex);
	const dirty = $derived($isDirty);
	const diff = $derived($activeDiff);
	const isDiff = $derived($diffMode);
	const isAppliedDiff = $derived($appliedDiffMode);

	const GEN_PARAM_LABELS: Record<string, string> = {
		inference_steps: 'Steps',
		guidance_scale: 'Guidance',
		shift: 'Shift',
		thinking: 'Think',
		lm_temperature: 'LM Temp',
		infer_method: 'Method'
	};

	function genParamChanges(
		a: VersionGenerationParams | null,
		b: VersionGenerationParams | null
	): { key: string; label: string; oldVal: string; newVal: string }[] {
		const allKeys = new Set([...Object.keys(a ?? {}), ...Object.keys(b ?? {})]);
		const changes: { key: string; label: string; oldVal: string; newVal: string }[] = [];
		for (const k of allKeys) {
			const oldV = (a as Record<string, unknown>)?.[k];
			const newV = (b as Record<string, unknown>)?.[k];
			if (String(oldV ?? '') !== String(newV ?? '')) {
				changes.push({
					key: k,
					label: GEN_PARAM_LABELS[k] ?? k,
					oldVal: oldV !== undefined ? String(oldV) : '—',
					newVal: newV !== undefined ? String(newV) : '—'
				});
			}
		}
		return changes;
	}
</script>

<div class="lyrics-edit">
	{#if !sourceGeneration && generations.length > 0}
		<div class="source-picker-row">
			<button class="select-source-btn" onclick={() => (showSourcePicker = !showSourcePicker)}>
				{showSourcePicker ? 'Cancel' : 'Select Source for Repaint / Cover'}
			</button>
			{#if showSourcePicker}
				<div class="source-picker-list">
					{#each generations as gen (gen.id)}
						<button
							class="source-picker-item"
							onclick={() => {
								showSourcePicker = false;
								onsourceselect?.(gen);
							}}
						>
							<span class="source-picker-num">Gen #{gen.generation_number}</span>
							{#if gen.version_number !== null}
								<span class="source-picker-ver">v{gen.version_number}</span>
							{/if}
							{#if gen.model_mode}
								<span class="source-picker-model">{gen.model_mode}</span>
							{/if}
							{#if gen.is_picked}
								<span class="source-picker-badge">★</span>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	{#if sourceGeneration}
		<div class="source-bar">
			<div class="source-info">
				<span class="source-label">Source: Gen #{sourceGeneration.generation_number}</span>
				{#if sourceGeneration.version_number !== null}
					<span class="source-version">(v{sourceGeneration.version_number})</span>
				{/if}
			</div>
			<div class="source-mode-toggle">
				<button
					class="mode-btn"
					class:active={sourceMode === 'repaint'}
					onclick={() => onsourcemodechange?.('repaint')}
				>
					Repaint
				</button>
				<button
					class="mode-btn"
					class:active={sourceMode === 'cover'}
					onclick={() => onsourcemodechange?.('cover')}
				>
					Cover
				</button>
			</div>
			<button class="source-dismiss" onclick={() => onsourceclear?.()} title="Clear source"
				>×</button
			>
		</div>

		{#if sourceMode === 'repaint'}
			{@const duration = sourceGeneration.generation_params?.audio_duration ?? 180}
			<WaveformRangePicker
				audioUrl={`/audio/${sourceGeneration.mp3_path}`}
				{duration}
				startPercent={repaintStart}
				endPercent={repaintEnd}
				onchange={(s, e) => onrepaintrangechange?.(s, e)}
			/>
			<div class="repaint-options">
				<label class="setting">
					<span>Repaint Mode</span>
					<select
						value={repaintMode}
						onchange={(e) => onrepaintmodechange?.(e.currentTarget.value)}
					>
						<option value="">default</option>
						<option value="conservative">conservative</option>
						<option value="balanced">balanced</option>
						<option value="aggressive">aggressive</option>
					</select>
				</label>
				{#if repaintMode === 'balanced'}
					<label class="setting">
						<span>Repaint Strength</span>
						<input
							type="range"
							class="strength-slider"
							min="0"
							max="100"
							step="1"
							value={repaintStrength * 100}
							oninput={(e) => onrepaintstrengthchange?.(Number(e.currentTarget.value) / 100)}
						/>
						<span class="strength-value">{Math.round(repaintStrength * 100)}%</span>
					</label>
				{/if}
			</div>
		{:else}
			<div class="cover-strength">
				<span class="strength-label">Free</span>
				<input
					type="range"
					class="strength-slider"
					min="0"
					max="100"
					step="1"
					value={coverStrength * 100}
					oninput={(e) => oncoverstrengthchange?.(Number(e.currentTarget.value) / 100)}
				/>
				<span class="strength-label">Strict</span>
				<span class="strength-value">{Math.round(coverStrength * 100)}%</span>
			</div>
			<div class="cover-noise">
				<label class="setting">
					<span>Noise Strength</span>
					<input
						type="range"
						class="strength-slider"
						min="0"
						max="100"
						step="1"
						value={coverNoiseStrength * 100}
						oninput={(e) => oncovernoisestrengthchange?.(Number(e.currentTarget.value) / 100)}
					/>
					<span class="strength-value">{Math.round(coverNoiseStrength * 100)}%</span>
				</label>
			</div>
		{/if}
	{/if}

	{#if vers.length > 0}
		<VersionTimeline
			versions={vers}
			currentIndex={verIndex}
			{dirty}
			onselect={loadVersion}
			ondiff={handleDiffChange}
			ondelete={ondeleteversion}
		/>
	{/if}

	{#if isAppliedDiff && !isDiff}
		<div class="diff-banner">
			<span>Claude applied changes</span>
		</div>
	{/if}

	{#if diff}
		{@const d = diff}
		{@const isVer = isDiff}
		{@const oldLabel = isVer ? `v${d.old.version_number}` : 'Before'}
		{@const newLabel = isVer ? `v${d.new.version_number}` : 'After'}

		<div class="edit-field">
			<span>Style Prompt {d.old.prompt !== d.new.prompt ? '●' : ''}</span>
			{#if d.old.prompt !== d.new.prompt}
				<LyricsDiff oldText={d.old.prompt} newText={d.new.prompt} {oldLabel} {newLabel} />
			{:else}
				<div class="diff-readonly">{d.new.prompt || '—'}</div>
			{/if}
		</div>

		<div class="params-diff">
			<span class="param-change">
				BPM:
				{#if d.old.bpm !== d.new.bpm}
					<span class="old">{d.old.bpm}</span> →
					<span class="new">{d.new.bpm}</span>
				{:else}
					{d.new.bpm}
				{/if}
			</span>
			<span class="param-change">
				Duration:
				{#if d.old.audio_duration !== d.new.audio_duration}
					<span class="old">{d.old.audio_duration}</span> →
					<span class="new">{d.new.audio_duration}</span>
				{:else}
					{d.new.audio_duration}
				{/if}
			</span>
			<span class="param-change">
				Key:
				{#if d.old.key_scale !== d.new.key_scale}
					<span class="old">{d.old.key_scale || '—'}</span> →
					<span class="new">{d.new.key_scale || '—'}</span>
				{:else}
					{d.new.key_scale || '—'}
				{/if}
			</span>
			{#each genParamChanges(d.old.generation_params, d.new.generation_params) as change (change.key)}
				<span class="param-change">
					{change.label}:
					<span class="old">{change.oldVal}</span> →
					<span class="new">{change.newVal}</span>
				</span>
			{/each}
		</div>

		<div class="edit-field">
			<span>Lyrics {d.old.lyrics !== d.new.lyrics ? '●' : ''}</span>
			{#if d.old.lyrics !== d.new.lyrics}
				<LyricsDiff oldText={d.old.lyrics} newText={d.new.lyrics} {oldLabel} {newLabel} />
			{:else}
				<pre class="diff-readonly lyrics-readonly">{d.new.lyrics || '—'}</pre>
			{/if}
		</div>
	{:else}
		<label class="edit-field">
			<span>Style Prompt</span>
			<textarea rows="4" value={$editPrompt} oninput={(e) => setDraftPrompt(e.currentTarget.value)}
			></textarea>
		</label>

		<div class="params-row">
			<label class="edit-field small">
				<span>BPM <small class="hint">(0 = auto)</small></span>
				<input
					type="number"
					min="0"
					max="999"
					value={$editBpm}
					oninput={(e) => setDraftBpm(Number(e.currentTarget.value))}
				/>
			</label>
			<label class="edit-field small">
				<span>Duration <small class="hint">(0 = auto)</small></span>
				<input
					type="number"
					min="0"
					max="600"
					value={$editAudioDuration}
					oninput={(e) => setDraftAudioDuration(Number(e.currentTarget.value))}
				/>
			</label>
			<label class="edit-field small">
				<span>Key</span>
				<input
					type="text"
					value={$editKeyScale}
					oninput={(e) => setDraftKeyScale(e.currentTarget.value)}
				/>
			</label>
		</div>

		<label class="edit-field">
			<span>Lyrics</span>
			<textarea
				class="lyrics-area"
				rows="15"
				value={$editLyrics}
				oninput={(e) => setDraftLyrics(e.currentTarget.value)}
			></textarea>
		</label>

		<GenerationSettings {selectedModel} />
	{/if}
</div>

<style>
	.lyrics-edit {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.diff-banner {
		padding: 0.4rem 0.7rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.75rem;
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.params-diff {
		display: flex;
		gap: 0.8rem;
		flex-wrap: wrap;
		padding: 0.4rem 0.7rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.8rem;
	}

	.param-change {
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.75rem;
	}

	.param-change .old {
		color: var(--score-bad);
		text-decoration: line-through;
	}

	.param-change .new {
		color: var(--score-good);
	}

	.diff-readonly {
		padding: 0.4rem 0.7rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 0.87rem;
	}

	.lyrics-readonly {
		font-family: 'Courier New', monospace;
		font-size: 1rem;
		line-height: 1.6;
		white-space: pre-wrap;
		margin: 0;
		max-height: 300px;
		overflow-y: auto;
	}

	.edit-field {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.edit-field span {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.edit-field .hint {
		font-size: 0.75em;
		opacity: 0.6;
		text-transform: none;
		letter-spacing: 0;
		margin-left: 0.3em;
	}

	.edit-field input,
	.edit-field textarea {
		padding: 0.6rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 1rem;
		width: 100%;
		min-width: 0;
	}

	.edit-field input:focus,
	.edit-field textarea:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.params-row {
		display: flex;
		gap: 0.7rem;
	}

	.edit-field.small {
		flex: 1;
	}

	.lyrics-area {
		font-family: 'Courier New', monospace;
		font-size: 1rem;
		line-height: 1.6;
		min-height: 200px;
		resize: vertical;
	}

	.source-bar {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 0.5rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--primary);
		border-radius: var(--card-radius);
	}

	.source-info {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		flex: 1;
		min-width: 0;
	}

	.source-label {
		font-size: 0.8rem;
		font-family: var(--font-display);
		color: var(--text);
		letter-spacing: 0.5px;
	}

	.source-version {
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.source-mode-toggle {
		display: flex;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		overflow: hidden;
	}

	.mode-btn {
		padding: 0.25rem 0.6rem;
		border: none;
		background: var(--bg);
		color: var(--text-muted);
		font-size: 0.7rem;
		font-family: var(--font-display);
		letter-spacing: var(--btn-letter-spacing);
		cursor: pointer;
	}

	.mode-btn.active {
		background: var(--primary);
		color: #fff;
	}

	.source-dismiss {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 1.1rem;
		cursor: pointer;
		padding: 0 0.2rem;
		line-height: 1;
	}

	.source-dismiss:hover {
		color: var(--text);
	}

	.repaint-options,
	.cover-noise {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 0.5rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.repaint-options .setting,
	.cover-noise .setting {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex: 1;
	}

	.repaint-options .setting span,
	.cover-noise .setting span {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		flex-shrink: 0;
	}

	.repaint-options select {
		padding: 0.3rem 0.5rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.85rem;
	}

	.cover-strength {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		padding: 0.5rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.strength-label {
		font-size: 0.7rem;
		color: var(--text-dim);
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		flex-shrink: 0;
	}

	.strength-slider {
		flex: 1;
		accent-color: var(--accent);
		cursor: pointer;
	}

	.strength-value {
		font-size: 0.85rem;
		font-family: var(--font-display);
		color: var(--text);
		min-width: 32px;
		text-align: right;
	}

	.source-picker-row {
		position: relative;
	}

	.select-source-btn {
		width: 100%;
		padding: 0.5rem 0.8rem;
		background: var(--surface);
		border: 1px dashed var(--border);
		border-radius: var(--card-radius);
		color: var(--text-muted);
		font-size: 0.8rem;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		cursor: pointer;
		text-align: center;
	}

	.select-source-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.source-picker-list {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		max-height: 240px;
		overflow-y: auto;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		z-index: 10;
		display: flex;
		flex-direction: column;
		margin-top: 0.2rem;
	}

	.source-picker-item {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		padding: 0.5rem 0.8rem;
		background: none;
		border: none;
		border-bottom: 1px solid var(--border);
		color: var(--text);
		font-size: 0.8rem;
		cursor: pointer;
		text-align: left;
	}

	.source-picker-item:last-child {
		border-bottom: none;
	}

	.source-picker-item:hover {
		background: rgba(160, 32, 240, 0.1);
	}

	.source-picker-num {
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.source-picker-ver {
		font-size: 0.7rem;
		color: var(--primary);
		background: rgba(160, 32, 240, 0.1);
		padding: 0.1rem 0.4rem;
		border-radius: 3px;
	}

	.source-picker-model {
		font-size: 0.7rem;
		color: var(--text-dim);
	}

	.source-picker-badge {
		color: var(--score-ok);
	}
</style>
