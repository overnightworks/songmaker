<script lang="ts">
	import {
		editLyrics,
		editPrompt,
		editBpm,
		editDuration,
		editKey,
		versions,
		currentVersionIndex,
		isDirty,
		diffMode,
		appliedDiffMode,
		activeDiff,
		loadVersion,
		handleDiffChange
	} from '$lib/stores/editor';
	import type { VersionGenerationParams } from '$lib/api/types';
	import GenerationSettings from '$lib/components/GenerationSettings.svelte';
	import LyricsDiff from '$lib/components/LyricsDiff.svelte';
	import VersionTimeline from '$lib/components/VersionTimeline.svelte';

	interface Props {
		ondeleteversion: (versionId: string, deleteGenerations: boolean) => void;
	}

	let { ondeleteversion }: Props = $props();

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
		think_mode: 'Think',
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
				{#if d.old.duration !== d.new.duration}
					<span class="old">{d.old.duration}</span> →
					<span class="new">{d.new.duration}</span>
				{:else}
					{d.new.duration}
				{/if}
			</span>
			<span class="param-change">
				Key:
				{#if d.old.key !== d.new.key}
					<span class="old">{d.old.key || '—'}</span> →
					<span class="new">{d.new.key || '—'}</span>
				{:else}
					{d.new.key || '—'}
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
			<textarea rows="4" bind:value={$editPrompt}></textarea>
		</label>

		<div class="params-row">
			<label class="edit-field small">
				<span>BPM</span>
				<input type="number" bind:value={$editBpm} />
			</label>
			<label class="edit-field small">
				<span>Duration</span>
				<input type="number" bind:value={$editDuration} />
			</label>
			<label class="edit-field small">
				<span>Key</span>
				<input type="text" bind:value={$editKey} />
			</label>
		</div>

		<GenerationSettings />

		<label class="edit-field">
			<span>Lyrics</span>
			<textarea class="lyrics-area" rows="15" bind:value={$editLyrics}></textarea>
		</label>
	{/if}
</div>

<style>
	.lyrics-edit {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.diff-banner {
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 11px;
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.params-diff {
		display: flex;
		gap: 12px;
		flex-wrap: wrap;
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 12px;
	}

	.param-change {
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 11px;
	}

	.param-change .old {
		color: var(--score-bad);
		text-decoration: line-through;
	}

	.param-change .new {
		color: var(--score-good);
	}

	.diff-readonly {
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 13px;
	}

	.lyrics-readonly {
		font-family: 'Courier New', monospace;
		font-size: 14px;
		line-height: 1.6;
		white-space: pre-wrap;
		margin: 0;
		max-height: 300px;
		overflow-y: auto;
	}

	.edit-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.edit-field span {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.edit-field input,
	.edit-field textarea {
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 13px;
	}

	.edit-field input:focus,
	.edit-field textarea:focus {
		border-color: var(--primary);
		outline: none;
	}

	.params-row {
		display: flex;
		gap: 10px;
	}

	.edit-field.small {
		flex: 1;
	}

	.lyrics-area {
		font-family: 'Courier New', monospace;
		font-size: 14px;
		line-height: 1.6;
		min-height: 200px;
		resize: vertical;
	}
</style>
