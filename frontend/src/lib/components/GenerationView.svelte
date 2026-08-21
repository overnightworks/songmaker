<script lang="ts">
	import { fetchSong, scoreGeneration, rateGeneration } from '$lib/api/client';
	import {
		selectedSong,
		selectedGeneration,
		replaceSongInList,
		playGeneration
	} from '$lib/stores/player';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import { addToast } from '$lib/stores/toast';
	import {
		NOW_PLAYING_TAKE_PREFIX,
		TAKE_FROM_RECIPE_PREFIX,
		TAKE_INSPECTOR_CLOSE,
		TAKE_SCORE_LABEL,
		TAKE_SCORING_LABEL
	} from '$lib/constants';
	import { scoreColor } from '$lib/utils/scores';
	import ActionButton from './ActionButton.svelte';

	let { onclose }: { onclose: () => void } = $props();

	let ratingValue = $state(50);
	let ratingNotes = $state('');
	let ratingSaving = $state(false);

	const song = $derived($selectedSong);
	const generation = $derived($selectedGeneration);
	const jobs = $derived($activeJobs);

	const scoring = $derived(
		generation
			? jobs.some(
					(j) =>
						j.genId === generation.id &&
						j.job.type === 'score' &&
						(j.job.status === 'running' || j.job.status === 'queued')
				)
			: false
	);

	const savedRating = $derived(generation?.scores?.user_rating ?? 50);
	const savedNotes = $derived(generation?.scores?.user_notes ?? '');
	const ratingDirty = $derived(ratingValue !== savedRating || ratingNotes !== savedNotes);

	$effect(() => {
		ratingValue = savedRating;
		ratingNotes = savedNotes;
	});

	const scores = $derived(generation?.scores);
	const params = $derived(generation?.generation_params);

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
		if (scores.bpm_detected !== undefined) {
			const dev = scores.bpm_deviation ?? 0;
			entries.push({
				label: 'BPM',
				value: scores.bpm_detected.toFixed(0),
				color: dev < 5 ? 'good' : dev < 15 ? 'ok' : 'bad'
			});
		}
		return entries;
	});

	async function onScore(): Promise<void> {
		if (!generation || !song) return;
		try {
			const job = await scoreGeneration(generation.id);
			trackJob(job, { songId: song.id, genId: generation.id });
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Scoring failed', 'error');
		}
	}

	function formatExpiryLine(): string | null {
		if (!generation) return null;
		if (generation.is_picked) return 'Kept forever — picked for album';
		if (generation.is_kept) return 'Kept forever — marked as keep';
		if (!generation.expires_at) return null;
		const expiry = new Date(generation.expires_at);
		const ms = expiry.getTime() - Date.now();
		const days = Math.ceil(ms / (1000 * 60 * 60 * 24));
		if (generation.is_archived) {
			if (days <= 0) return 'Archived — eligible for permanent deletion';
			return `Archived — permanent deletion in ${days} day${days === 1 ? '' : 's'} (${expiry.toLocaleDateString()})`;
		}
		if (days <= 0) return 'Auto-archive due any time now';
		return `Auto-archives in ${days} day${days === 1 ? '' : 's'} (${expiry.toLocaleDateString()}) unless picked or kept`;
	}

	async function onRate(): Promise<void> {
		if (!generation || ratingSaving) return;
		ratingSaving = true;
		try {
			await rateGeneration(generation.id, ratingValue, ratingNotes);
			if (song) {
				const updated = await fetchSong(song.id);
				replaceSongInList(updated);
			}
			addToast('Rating saved', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Rating failed', 'error');
		} finally {
			ratingSaving = false;
		}
	}
</script>

{#if generation && song}
	<div class="inspector" role="region" aria-label="{NOW_PLAYING_TAKE_PREFIX} inspector">
		<div class="inspector-header">
			<div>
				<h2 class="inspector-title">
					{`${NOW_PLAYING_TAKE_PREFIX} ${generation.generation_number}`}
				</h2>
				<div class="inspector-meta">
					{#if generation.version_number !== null}
						<span class="version-tag">{TAKE_FROM_RECIPE_PREFIX} {generation.version_number}</span>
					{/if}
					{#if generation.model_mode}
						<span class="model-tag">{generation.model_mode}</span>
					{/if}
					{#if generation.seed != null}
						<span class="seed-tag">seed:{generation.seed}</span>
					{/if}
				</div>
				{#if formatExpiryLine()}
					<div
						class="expiry-line"
						class:archived={generation.is_archived}
						class:safe={generation.is_picked || generation.is_kept}
					>
						{formatExpiryLine()}
					</div>
				{/if}
			</div>
			<div class="inspector-actions">
				<ActionButton
					icon="refresh-cw"
					label={scoring ? TAKE_SCORING_LABEL : TAKE_SCORE_LABEL}
					disabled={scoring}
					onclick={onScore}
				/>
				<button type="button" class="close-btn" onclick={onclose}>{TAKE_INSPECTOR_CLOSE}</button>
			</div>
		</div>

		{#if generation.src_generation_number}
			{@const srcGen = song?.generations.find((g) => g.id === generation.src_generation_id)}
			{@const repaintStartSec =
				generation.generation_params?.repainting_start != null &&
				generation.generation_params?.audio_duration
					? generation.generation_params.repainting_start *
						generation.generation_params.audio_duration
					: null}
			<div class="lineage">
				<span class="lineage-label">Source</span>
				<span class="lineage-chain">
					{#if generation.generation_params?.task_type === 'repaint'}
						Repainted from {NOW_PLAYING_TAKE_PREFIX}
						#{generation.src_generation_number}
						{#if generation.generation_params?.repainting_start != null && generation.generation_params.repainting_end != null}
							({(generation.generation_params.repainting_start * 100).toFixed(0)}%–{(
								generation.generation_params.repainting_end * 100
							).toFixed(0)}%)
						{/if}
					{:else if generation.generation_params?.task_type === 'cover'}
						Covered from {NOW_PLAYING_TAKE_PREFIX}
						#{generation.src_generation_number}
						{#if generation.generation_params?.audio_cover_strength != null}
							(strength {(generation.generation_params.audio_cover_strength * 100).toFixed(0)}%)
						{/if}
					{:else}
						From {NOW_PLAYING_TAKE_PREFIX}
						#{generation.src_generation_number}
					{/if}
				</span>
				{#if srcGen && song && repaintStartSec !== null}
					<div class="compare-buttons">
						<button
							type="button"
							class="compare-btn"
							class:active={audioPlayer.current?.generation.id === srcGen.id}
							onclick={() => {
								playGeneration(srcGen, song);
								audioPlayer.seek(repaintStartSec);
							}}>Source</button
						>
						<button
							type="button"
							class="compare-btn"
							class:active={audioPlayer.current?.generation.id === generation.id}
							onclick={() => {
								playGeneration(generation, song);
								audioPlayer.seek(repaintStartSec);
							}}>Result</button
						>
					</div>
				{/if}
			</div>
		{/if}

		<section class="section">
			<div class="section-header">
				<h5 class="section-title">Scores</h5>
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

			<div class="rating-section">
				<div class="rating-row">
					<span class="rating-label">Your Rating</span>
					<input
						type="range"
						class="rating-slider"
						min="0"
						max="100"
						step="1"
						bind:value={ratingValue}
					/>
					<span class="rating-number">{ratingValue}</span>
				</div>
				<textarea
					class="rating-notes"
					placeholder="Notes (optional)"
					bind:value={ratingNotes}
					rows="2"
				></textarea>
				{#if ratingDirty}
					<button type="button" class="rating-save" onclick={onRate} disabled={ratingSaving}>
						{ratingSaving ? 'Saving...' : 'Save Rating'}
					</button>
				{/if}
			</div>
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
{/if}

<style>
	.inspector {
		padding: 0.8rem 0 0;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
		border-top: 1px solid var(--border);
		margin-top: 0.8rem;
	}

	.inspector-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.7rem;
	}

	.inspector-title {
		font-family: var(--font-display);
		font-size: 1.2rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.13rem;
		margin: 0;
	}

	.inspector-meta {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.55rem;
		margin-top: 0.3rem;
	}

	.expiry-line {
		margin-top: 0.5rem;
		font-size: 0.75rem;
		color: var(--text-muted);
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.expiry-line.archived {
		color: #e07070;
	}

	.expiry-line.safe {
		color: #60a070;
	}

	.version-tag {
		font-size: 0.75rem;
		color: var(--primary);
		background: rgba(160, 32, 240, 0.1);
		padding: 0.15rem 0.7rem;
		border-radius: var(--btn-radius-sm);
		border: 1px solid var(--primary);
		font-family: var(--font-display);
		letter-spacing: var(--btn-letter-spacing);
	}

	.model-tag {
		font-size: 0.75rem;
		color: var(--text-muted);
		background: var(--surface);
		padding: 0.15rem 0.7rem;
		border-radius: var(--btn-radius-sm);
		border: 1px solid var(--border);
		font-family: var(--font-display);
	}

	.seed-tag {
		font-size: 0.7rem;
		color: var(--text-subtle);
		font-family: var(--font-body);
	}

	.inspector-actions {
		display: flex;
		gap: 0.55rem;
		align-items: center;
		flex-wrap: wrap;
		flex-shrink: 0;
	}

	.close-btn {
		padding: 0.25rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.close-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.lineage {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.55rem;
		padding: 0.5rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.lineage-label {
		font-size: 0.7rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		flex-shrink: 0;
	}

	.lineage-chain {
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.compare-buttons {
		display: flex;
		gap: 0.3rem;
		margin-left: auto;
	}

	.compare-btn {
		font-size: 0.7rem;
		padding: 0.15rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: none;
		color: var(--text-subtle);
		cursor: pointer;
		font-family: var(--font-display);
		letter-spacing: 0.3px;
	}

	.compare-btn:hover {
		color: var(--accent);
		border-color: var(--accent);
	}

	.compare-btn.active {
		color: var(--accent);
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
	}

	.section {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
		padding: 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.section-title {
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		color: var(--text-subtle);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.scores-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
		gap: 0.55rem;
	}

	.score-cell {
		display: flex;
		flex-direction: column;
		padding: 0.55rem 0.7rem;
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
		font-size: 0.7rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.score-value {
		font-size: 1.2rem;
		font-family: var(--font-display);
		color: var(--text);
	}

	.no-scores {
		font-size: 0.75rem;
		color: var(--text-subtle);
		font-style: italic;
	}

	.rating-section {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
		margin-top: 0.55rem;
		padding-top: 0.55rem;
		border-top: 1px solid var(--border);
	}

	.rating-row {
		display: flex;
		align-items: center;
		gap: 0.7rem;
	}

	.rating-label {
		font-size: 0.7rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		flex-shrink: 0;
	}

	.rating-slider {
		flex: 1;
		accent-color: var(--accent);
		cursor: pointer;
	}

	.rating-number {
		font-size: 1.2rem;
		font-family: var(--font-display);
		color: var(--text);
		min-width: 32px;
		text-align: right;
	}

	.rating-notes {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 1rem;
		font-family: var(--font-body);
		padding: 0.4rem 0.55rem;
		resize: vertical;
	}

	.rating-notes:focus {
		outline: none;
		border-color: var(--accent);
	}

	.rating-save {
		align-self: flex-end;
		padding: var(--btn-padding-sm);
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: rgba(160, 32, 240, 0.1);
		color: var(--accent);
		font-size: 0.75rem;
		font-family: var(--font-display);
		letter-spacing: var(--btn-letter-spacing);
		cursor: pointer;
	}

	.rating-save:hover:not(:disabled) {
		background: rgba(160, 32, 240, 0.2);
	}

	.rating-save:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.summary {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-top: 4px;
	}

	.summary-label {
		font-size: 0.7rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.summary-text {
		font-size: 0.87rem;
		color: var(--text-muted);
		line-height: 1.5;
	}

	.params-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}

	.param {
		font-size: 0.75rem;
		color: var(--text-muted);
		background: var(--bg);
		padding: 0.2rem 0.55rem;
		border-radius: 3px;
	}

	.whisper-text {
		white-space: pre-wrap;
		font-family: 'Courier New', monospace;
		font-size: 0.87rem;
		line-height: 1.6;
		color: var(--text-muted);
		margin: 0;
		max-height: 400px;
		overflow-y: auto;
	}
</style>
