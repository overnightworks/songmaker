<script lang="ts">
	import type { GenerationItem } from '$lib/api/types';
	import { scoreColor } from '$lib/utils/scores';

	interface Props {
		generation: GenerationItem;
		scoring?: boolean;
		onversionclick?: (versionId: string) => void;
		onscore?: (genId: string) => void;
		onpick?: (genId: string, picked: boolean) => void;
	}

	let { generation, scoring = false, onversionclick, onscore, onpick }: Props = $props();

	const scores = $derived(generation.scores);
	const params = $derived(generation.generation_params);

	interface ScoreEntry {
		label: string;
		value: string;
		color: string;
	}

	const scoreEntries = $derived.by((): ScoreEntry[] => {
		if (!scores) return [];
		const entries: ScoreEntry[] = [];
		if (scores.user_rating !== undefined)
			entries.push({
				label: 'Rating',
				value: scores.user_rating.toFixed(0),
				color: scoreColor('user_rating', scores.user_rating)
			});
		if (scores.audiobox_enjoyment !== undefined)
			entries.push({
				label: 'Enjoyment',
				value: scores.audiobox_enjoyment.toFixed(2),
				color: scoreColor('audiobox_enjoyment', scores.audiobox_enjoyment)
			});
		if (scores.audiobox_quality !== undefined)
			entries.push({
				label: 'Quality',
				value: scores.audiobox_quality.toFixed(2),
				color: scoreColor('audiobox_quality', scores.audiobox_quality)
			});
		if (scores.lyrical_coherence !== undefined)
			entries.push({
				label: 'Coherence',
				value: String(scores.lyrical_coherence),
				color: scoreColor('lyrical_coherence', scores.lyrical_coherence)
			});
		if (scores.dynamics !== undefined)
			entries.push({
				label: 'Dynamics',
				value: scores.dynamics.toFixed(0),
				color: scoreColor('dynamics', scores.dynamics)
			});
		if (scores.text_accuracy !== undefined)
			entries.push({
				label: 'Text Accuracy',
				value: scores.text_accuracy.toFixed(0) + '%',
				color: scoreColor('text_accuracy', scores.text_accuracy)
			});
		if (scores.audiobox_understanding !== undefined)
			entries.push({
				label: 'Understanding',
				value: scores.audiobox_understanding.toFixed(2),
				color: 'ok'
			});
		if (scores.audiobox_complexity !== undefined)
			entries.push({
				label: 'Complexity',
				value: scores.audiobox_complexity.toFixed(2),
				color: 'ok'
			});
		return entries;
	});
</script>

<div class="gen-detail">
	<div class="gen-header">
		<div class="gen-header-left">
			<h4 class="gen-heading">
				Generation {generation.generation_number}
			</h4>
			{#if onpick}
				<button
					class="pick-btn"
					class:picked={generation.is_picked}
					onclick={() => onpick(generation.id, !generation.is_picked)}
					aria-label={generation.is_picked ? 'Unpick as album version' : 'Pick as album version'}
				>
					{generation.is_picked ? '★ Album Pick' : '☆ Pick for Album'}
				</button>
			{:else if generation.is_picked}
				<span class="picked-badge">★ Album Pick</span>
			{/if}
		</div>
		<div class="gen-meta">
			{#if generation.version_number !== null}
				{#if onversionclick && generation.version_id}
					{@const vid = generation.version_id}
					<button class="version-link" onclick={() => onversionclick(vid)}>
						v{generation.version_number}
					</button>
				{:else}
					<span class="version-tag">v{generation.version_number}</span>
				{/if}
			{:else}
				<span class="version-tag unknown">unknown version</span>
			{/if}
			{#if generation.seed}
				<span class="seed">seed:{generation.seed}</span>
			{/if}
		</div>
	</div>

	<section class="section">
		<div class="section-header">
			<h5 class="section-title">Scores</h5>
			{#if onscore}
				<button class="score-btn" onclick={() => onscore(generation.id)} disabled={scoring}>
					{scoring ? 'Scoring...' : 'Re-score'}
				</button>
			{/if}
		</div>
		{#if scoreEntries.length > 0}
			<div class="scores-grid">
				{#each scoreEntries as entry (entry.label)}
					<div class="score-cell {entry.color}">
						<span class="score-label">{entry.label}</span>
						<span class="score-value">{entry.value}</span>
					</div>
				{/each}
			</div>
		{:else}
			<p class="no-scores">No scores yet</p>
		{/if}

		{#if scores?.lyrical_summary}
			<div class="summary">
				<span class="summary-label">Summary</span>
				<p class="summary-text">{scores.lyrical_summary}</p>
			</div>
		{/if}

		{#if scores?.user_notes}
			<div class="summary">
				<span class="summary-label">Notes</span>
				<p class="summary-text">{scores.user_notes}</p>
			</div>
		{/if}
	</section>

	{#if generation.whisper_text}
		<section class="section">
			<h5 class="section-title">Transcript</h5>
			<pre class="whisper-text">{generation.whisper_text}</pre>
		</section>
	{/if}

	{#if params}
		{@const entries = Object.entries(params).filter(([, v]) => v !== null && v !== undefined)}
		{#if entries.length > 0}
			<section class="section">
				<h5 class="section-title">Parameters</h5>
				<div class="params-grid">
					{#each entries as [key, value] (key)}
						<span class="param"
							>{key}: {typeof value === 'boolean' ? (value ? 'on' : 'off') : value}</span
						>
					{/each}
				</div>
			</section>
		{/if}
	{/if}
</div>

<style>
	.gen-detail {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	.gen-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
	}

	.gen-header-left {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.pick-btn {
		padding: 3px 12px;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: none;
		color: var(--text-dim);
		font-size: 11px;
		font-family: var(--font-display);
		cursor: pointer;
		letter-spacing: 0.5px;
	}

	.pick-btn:hover {
		border-color: var(--score-ok);
		color: var(--score-ok);
	}

	.pick-btn.picked {
		border-color: var(--score-ok);
		background: var(--score-ok-bg);
		color: var(--score-ok);
	}

	.picked-badge {
		font-size: 11px;
		color: var(--score-ok);
		font-family: var(--font-display);
	}

	.gen-heading {
		font-family: var(--font-display);
		font-size: 18px;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.gen-meta {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.version-link {
		background: none;
		border: 1px solid var(--primary);
		color: var(--primary);
		padding: 2px 10px;
		border-radius: 10px;
		font-size: 11px;
		cursor: pointer;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.version-link:hover {
		background: var(--primary);
		color: #fff;
	}

	.version-tag {
		font-size: 11px;
		color: var(--text-muted);
		background: var(--surface);
		padding: 2px 10px;
		border-radius: 10px;
		border: 1px solid var(--border);
		font-family: var(--font-display);
	}

	.version-tag.unknown {
		color: var(--text-dim);
	}

	.seed {
		font-size: 10px;
		color: var(--text-dim);
		font-family: var(--font-body);
	}

	.section {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
	}

	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.section-title {
		font-family: var(--font-display);
		font-size: 11px;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.score-btn {
		padding: 3px 12px;
		border: 1px solid var(--primary);
		border-radius: 10px;
		background: none;
		color: var(--primary);
		font-size: 10px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.score-btn:hover:not(:disabled) {
		background: var(--primary);
		color: #fff;
	}

	.score-btn:disabled {
		opacity: 0.4;
	}

	.scores-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
		gap: 8px;
	}

	.score-cell {
		display: flex;
		flex-direction: column;
		padding: 8px 10px;
		border-radius: 4px;
		background: var(--bg);
	}

	.score-cell.good {
		border-left: 3px solid var(--score-good);
	}

	.score-cell.ok {
		border-left: 3px solid var(--score-ok);
	}

	.score-cell.bad {
		border-left: 3px solid var(--score-bad);
	}

	.score-label {
		font-size: 9px;
		color: var(--text-dim);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.score-value {
		font-size: 18px;
		font-family: var(--font-display);
		color: var(--text);
	}

	.no-scores {
		font-size: 11px;
		color: var(--text-dim);
		font-style: italic;
	}

	.summary {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-top: 4px;
	}

	.summary-label {
		font-size: 9px;
		color: var(--text-dim);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.summary-text {
		font-size: 12px;
		color: var(--text-muted);
		line-height: 1.5;
	}

	.params-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.param {
		font-size: 11px;
		color: var(--text-muted);
		background: var(--bg);
		padding: 3px 8px;
		border-radius: 3px;
	}

	.whisper-text {
		white-space: pre-wrap;
		font-family: 'Courier New', monospace;
		font-size: 13px;
		line-height: 1.6;
		color: var(--text-muted);
		margin: 0;
		max-height: 400px;
		overflow-y: auto;
	}
</style>
