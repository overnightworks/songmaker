<script lang="ts">
	import type { GenerationItem } from '$lib/api/types';
	import { scoreColor } from '$lib/utils/scores';
	import { addToast } from '$lib/stores/toast';
	import { getGenerationActions } from '$lib/contexts/generation-actions';
	import OverflowMenu from './OverflowMenu.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';

	interface Props {
		generation: GenerationItem;
		scoring?: boolean;
	}

	let { generation, scoring = false }: Props = $props();

	const actions = getGenerationActions();

	let ratingValue = $state(50);
	let ratingNotes = $state('');
	let showPlaylistPicker = $state(false);
	let ratingSaving = $state(false);

	const savedRating = $derived(generation.scores?.user_rating ?? 50);
	const savedNotes = $derived(generation.scores?.user_notes ?? '');
	let ratingDirty = $derived(ratingValue !== savedRating || ratingNotes !== savedNotes);

	$effect(() => {
		ratingValue = savedRating;
		ratingNotes = savedNotes;
	});

	async function saveRating(): Promise<void> {
		if (ratingSaving) return;
		ratingSaving = true;
		try {
			await actions.rate(generation.id, ratingValue, ratingNotes);
		} finally {
			ratingSaving = false;
		}
	}

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
			<button
				class="pick-btn"
				class:picked={generation.is_picked}
				onclick={() => actions.pick(generation.id, !generation.is_picked)}
				aria-label={generation.is_picked ? 'Unpick as album version' : 'Pick as album version'}
			>
				{generation.is_picked ? '★ Album Pick' : '☆ Pick for Album'}
			</button>
			<button
				class="keep-btn"
				class:kept={generation.is_kept}
				onclick={() => actions.keep(generation.id, !generation.is_kept)}
				aria-label={generation.is_kept ? 'Remove from kept' : 'Keep this generation'}
			>
				{generation.is_kept ? '♥ Kept' : '♡ Keep'}
			</button>
		</div>
		<div class="gen-meta">
			{#if generation.version_number !== null}
				{#if generation.version_id}
					{@const vid = generation.version_id}
					<button class="version-link" onclick={() => actions.clickVersion(vid)}>
						v{generation.version_number}
					</button>
				{:else}
					<span class="version-tag">v{generation.version_number}</span>
				{/if}
			{:else}
				<span class="version-tag unknown">unknown version</span>
			{/if}
			{#if generation.seed}
				<button class="seed" onclick={() => actions.pinSeed(generation.seed ?? 0)}>
					seed:{generation.seed}
				</button>
			{/if}
			<ShareButton
				isShared={generation.is_shared}
				shareSlug={generation.share_slug}
				onshare={() => actions.share(generation.id)}
				onunshare={() => actions.unshare(generation.id)}
			/>
			<div class="picker-anchor">
				<OverflowMenu
					items={[
						{
							label: 'Add to Playlist',
							onclick: () => (showPlaylistPicker = true)
						},
						{
							label: scoring ? 'Scoring...' : 'Re-Score',
							onclick: () => actions.score(generation.id)
						},
						{
							label: 'Delete Generation',
							confirmLabel: 'Confirm Delete',
							destructive: true,
							onclick: () => actions.del(generation.id)
						}
					]}
				/>
				{#if showPlaylistPicker}
					<PlaylistPicker
						onselect={async (playlistId) => {
							await actions.addToPlaylist(playlistId, generation.id);
							showPlaylistPicker = false;
						}}
						onclose={() => (showPlaylistPicker = false)}
					/>
				{/if}
			</div>
		</div>
	</div>

	{#if generation.is_shared && generation.share_slug}
		<button
			class="share-link"
			onclick={() => {
				const url = `${window.location.origin}/share/gen/${generation.share_slug}`;
				navigator.clipboard.writeText(url);
				addToast('Link copied', 'success');
			}}
			title="Click to copy share link"
		>
			{window.location.origin}/share/gen/{generation.share_slug}
		</button>
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
				<button class="rating-save" onclick={saveRating} disabled={ratingSaving}>
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

<style>
	.picker-anchor {
		position: relative;
	}

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
		border-radius: var(--card-radius);
	}

	.gen-header-left {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.pick-btn {
		padding: var(--btn-padding-sm);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-dim);
		font-size: 11px;
		font-family: var(--font-display);
		cursor: pointer;
		letter-spacing: var(--btn-letter-spacing);
	}

	.pick-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

	.pick-btn.picked {
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
		color: var(--accent);
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.15);
	}

	.picked-badge {
		font-size: 11px;
		color: var(--accent);
		font-family: var(--font-display);
		text-shadow: 0 0 6px rgba(160, 32, 240, 0.4);
	}

	.keep-btn {
		padding: var(--btn-padding-sm);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-dim);
		font-size: 11px;
		font-family: var(--font-display);
		cursor: pointer;
		letter-spacing: var(--btn-letter-spacing);
	}

	.keep-btn:hover {
		border-color: #e04050;
		color: #e04050;
	}

	.keep-btn.kept {
		border-color: #e04050;
		background: rgba(224, 64, 80, 0.1);
		color: #e04050;
		box-shadow: 0 0 8px rgba(224, 64, 80, 0.15);
	}

	.kept-badge {
		font-size: 11px;
		color: #e04050;
		font-family: var(--font-display);
		text-shadow: 0 0 6px rgba(224, 64, 80, 0.4);
	}

	.gen-heading {
		font-family: var(--font-display);
		font-size: 18px;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.5px;
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
		border-radius: var(--btn-radius-sm);
		font-size: 11px;
		cursor: pointer;
		font-family: var(--font-display);
		letter-spacing: var(--btn-letter-spacing);
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
		border-radius: var(--btn-radius-sm);
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
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}

	.seed:hover {
		color: var(--primary);
	}

	.section {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
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
		font-size: 11px;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.5px;
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
		transition: box-shadow 0.2s;
	}

	.score-cell.good {
		border-left: 3px solid var(--score-good);
		box-shadow: 0 0 12px rgba(68, 255, 68, 0.06);
	}

	.score-cell.ok {
		border-left: 3px solid var(--score-ok);
	}

	.score-cell.bad {
		border-left: 3px solid var(--score-bad);
		box-shadow: 0 0 12px rgba(255, 68, 68, 0.06);
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

	.rating-section {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-top: 8px;
		padding-top: 8px;
		border-top: 1px solid var(--border);
	}

	.rating-row {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.rating-label {
		font-size: 9px;
		color: var(--text-dim);
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
		font-size: 18px;
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
		font-size: 12px;
		font-family: var(--font-body);
		padding: 6px 8px;
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
		font-size: 11px;
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
