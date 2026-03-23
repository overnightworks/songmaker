<script lang="ts">
	import type { GenerationItem } from '$lib/api/types';

	interface Props {
		generation: GenerationItem;
	}

	let { generation }: Props = $props();

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
				color: scores.user_rating >= 70 ? 'good' : scores.user_rating >= 40 ? 'ok' : 'bad'
			});
		if (scores.audiobox_enjoyment !== undefined)
			entries.push({
				label: 'Enjoyment',
				value: scores.audiobox_enjoyment.toFixed(2),
				color:
					scores.audiobox_enjoyment >= 7 ? 'good' : scores.audiobox_enjoyment >= 4 ? 'ok' : 'bad'
			});
		if (scores.audiobox_quality !== undefined)
			entries.push({
				label: 'Quality',
				value: scores.audiobox_quality.toFixed(2),
				color: scores.audiobox_quality >= 7 ? 'good' : scores.audiobox_quality >= 4 ? 'ok' : 'bad'
			});
		if (scores.lyrical_coherence !== undefined)
			entries.push({
				label: 'Coherence',
				value: String(scores.lyrical_coherence),
				color: scores.lyrical_coherence >= 7 ? 'good' : scores.lyrical_coherence >= 4 ? 'ok' : 'bad'
			});
		if (scores.dynamics !== undefined)
			entries.push({
				label: 'Dynamics',
				value: scores.dynamics.toFixed(0),
				color: scores.dynamics >= 60 ? 'good' : scores.dynamics >= 30 ? 'ok' : 'bad'
			});
		if (scores.text_accuracy !== undefined)
			entries.push({
				label: 'Text Accuracy',
				value: scores.text_accuracy.toFixed(0) + '%',
				color: scores.text_accuracy >= 70 ? 'good' : scores.text_accuracy >= 40 ? 'ok' : 'bad'
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
	<h4 class="gen-heading">
		Generation {generation.generation_number}
		{#if generation.seed}
			<span class="seed">seed:{generation.seed}</span>
		{/if}
	</h4>

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

	{#if params}
		<details class="params-section">
			<summary class="params-toggle">Generation params</summary>
			<div class="params-grid">
				{#if params.acestep_model}
					<span class="param">model: {params.acestep_model}</span>
				{/if}
				{#if params.guidance_scale}
					<span class="param">cfg: {params.guidance_scale}</span>
				{/if}
				{#if params.inference_steps}
					<span class="param">steps: {params.inference_steps}</span>
				{/if}
				{#if params.shift}
					<span class="param">shift: {params.shift}</span>
				{/if}
				{#if params.lm_temperature}
					<span class="param">temp: {params.lm_temperature}</span>
				{/if}
				{#if params.infer_method}
					<span class="param">method: {params.infer_method}</span>
				{/if}
				{#if params.think_mode !== undefined}
					<span class="param">think: {params.think_mode ? 'on' : 'off'}</span>
				{/if}
			</div>
		</details>
	{/if}

	{#if generation.whisper_text}
		<details class="params-section">
			<summary class="params-toggle">Whisper transcript</summary>
			<pre class="whisper-text">{generation.whisper_text}</pre>
		</details>
	{/if}
</div>

<style>
	.gen-detail {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
	}

	.gen-heading {
		font-family: var(--font-display);
		font-size: 14px;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1px;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.seed {
		font-size: 10px;
		color: var(--text-dim);
		font-family: var(--font-body);
	}

	.scores-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
		gap: 6px;
	}

	.score-cell {
		display: flex;
		flex-direction: column;
		padding: 6px 8px;
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
		font-size: 16px;
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
		line-height: 1.4;
	}

	.params-section {
		font-size: 11px;
	}

	.params-toggle {
		color: var(--text-dim);
		cursor: pointer;
		font-size: 10px;
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.params-toggle:hover {
		color: var(--text-muted);
	}

	.params-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 6px;
	}

	.param {
		font-size: 10px;
		color: var(--text-muted);
		background: var(--bg);
		padding: 2px 6px;
		border-radius: 3px;
	}

	.whisper-text {
		white-space: pre-wrap;
		font-family: 'Courier New', monospace;
		font-size: 11px;
		color: var(--text-muted);
		margin-top: 6px;
		max-height: 200px;
		overflow-y: auto;
	}
</style>
