<script lang="ts">
	import type { GenerationItem } from '$lib/api/types';
	import { scoreColor } from '$lib/utils/scores';
	import { addToast } from '$lib/stores/toast';
	import { getGenerationActions } from '$lib/contexts/generation-actions';
	import ActionButton from './ActionButton.svelte';
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
		<h4 class="gen-heading">
			Generation {generation.generation_number}
		</h4>
		<div class="gen-actions-bar">
			<div class="action-group">
				<ActionButton
					icon="star"
					activeIcon="star-filled"
					label={generation.is_picked ? 'Unpick' : 'Pick for Album'}
					active={generation.is_picked}
					showLabel
					onclick={() => actions.pick(generation.id, !generation.is_picked)}
				/>
				<ActionButton
					icon="heart"
					activeIcon="heart-filled"
					label={generation.is_kept ? 'Remove from kept' : 'Keep'}
					active={generation.is_kept}
					showLabel
					onclick={() => actions.keep(generation.id, !generation.is_kept)}
				/>
			</div>
			<div class="action-group">
				<ActionButton
					icon="paintbrush"
					label="Repaint"
					showLabel
					onclick={() => actions.repaint(generation)}
				/>
				<ActionButton
					icon="layers"
					label="Cover"
					showLabel
					onclick={() => actions.cover(generation)}
				/>
			</div>
			<div class="action-group">
				<ActionButton
					icon="refresh-cw"
					label={scoring ? 'Scoring...' : 'Score'}
					showLabel
					disabled={scoring}
					onclick={() => actions.score(generation.id)}
				/>
				<div class="picker-anchor">
					<ActionButton
						icon="list-plus"
						label="Add to Playlist"
						showLabel
						onclick={() => (showPlaylistPicker = true)}
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
				<ShareButton
					isShared={generation.is_shared}
					shareSlug={generation.share_slug}
					onshare={() => actions.share(generation.id)}
					onunshare={() => actions.unshare(generation.id)}
				/>
				<ActionButton
					icon="trash"
					label="Delete"
					destructive
					confirm
					showLabel
					onclick={() => actions.del(generation.id)}
				/>
			</div>
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
		gap: 1.1rem;
	}

	.gen-header {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		padding: 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.gen-actions-bar {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		flex-wrap: wrap;
	}

	.action-group {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}

	.gen-heading {
		font-family: var(--font-display);
		font-size: 1.2rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.gen-meta {
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}

	.version-link {
		background: none;
		border: 1px solid var(--primary);
		color: var(--primary);
		padding: 0.15rem 0.7rem;
		border-radius: var(--btn-radius-sm);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-display);
		letter-spacing: var(--btn-letter-spacing);
	}

	.version-link:hover {
		background: var(--primary);
		color: #fff;
	}

	.version-tag {
		font-size: 0.75rem;
		color: var(--text-muted);
		background: var(--surface);
		padding: 0.15rem 0.7rem;
		border-radius: var(--btn-radius-sm);
		border: 1px solid var(--border);
		font-family: var(--font-display);
	}

	.version-tag.unknown {
		color: var(--text-dim);
	}

	.seed {
		font-size: 0.7rem;
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
		color: var(--text-dim);
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
		font-size: 0.7rem;
		color: var(--text-dim);
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
		color: var(--text-dim);
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
		color: var(--text-dim);
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
