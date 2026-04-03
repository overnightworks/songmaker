<script lang="ts">
	import {
		fetchSong,
		scoreGeneration,
		pickGeneration,
		unpickGeneration,
		keepGeneration,
		unkeepGeneration,
		shareGeneration,
		unshareGeneration,
		deleteGeneration,
		rateGeneration
	} from '$lib/api/client';
	import {
		selectedSong,
		selectedGeneration,
		replaceSongInList,
		removeGenerationFromSong
	} from '$lib/stores/player';
	import { backToSong } from '$lib/stores/navigation';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import { addToast } from '$lib/stores/toast';
	import { addGenerationToPlaylist } from '$lib/stores/playlists';
	import { pendingSource } from '$lib/stores/source';
	import { setGenerationActions } from '$lib/contexts/generation-actions';
	import { scoreColor } from '$lib/utils/scores';
	import ActionButton from './ActionButton.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	let showPlaylistPicker = $state(false);
	let showDeleteConfirm = $state(false);
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

	async function onPick(picked: boolean): Promise<void> {
		if (!generation || !song) return;
		try {
			if (picked) await pickGeneration(generation.id);
			else await unpickGeneration(generation.id);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Pick failed', 'error');
		}
	}

	async function onKeep(kept: boolean): Promise<void> {
		if (!generation || !song) return;
		try {
			if (kept) await keepGeneration(generation.id);
			else await unkeepGeneration(generation.id);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Keep failed', 'error');
		}
	}

	async function onDelete(): Promise<void> {
		if (!generation || !song) return;
		try {
			await deleteGeneration(generation.id);
			removeGenerationFromSong(song.id, generation.id);
			backToSong();
			addToast('Generation deleted', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Delete failed', 'error');
		}
	}

	async function onShareEnable() {
		if (!generation) throw new Error('No generation');
		return await shareGeneration(generation.id);
	}

	async function onShareDisable() {
		if (!generation) return;
		await unshareGeneration(generation.id);
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

	function onUseAsSource(): void {
		if (!generation) return;
		pendingSource.set(generation);
		backToSong();
	}

	setGenerationActions({
		score: () => onScore(),
		pick: (_id, picked) => onPick(picked),
		keep: (_id, kept) => onKeep(kept),
		del: () => onDelete(),
		rate: async (_id, rating, notes) => {
			ratingValue = rating;
			ratingNotes = notes;
			await onRate();
		},
		share: () => onShareEnable(),
		unshare: () => onShareDisable(),
		addToPlaylist: async (playlistId, genId) => {
			await addGenerationToPlaylist(playlistId, genId);
			addToast('Added to playlist', 'success');
		},
		pinSeed: (seed) => {
			addToast(`Seed ${seed} pinned for next generation`, 'success');
		},
		clickVersion: () => {
			backToSong();
		},
		useAsSource: onUseAsSource
	});
</script>

{#if generation && song}
	<div class="detail-panel">
		<button class="back-btn" onclick={backToSong}>
			<span class="back-arrow">←</span>
			{song.title}
		</button>

		<div class="detail-header">
			<div>
				<h2 class="detail-title">Generation {generation.generation_number}</h2>
				<div class="detail-meta">
					{#if generation.version_number !== null}
						<span class="version-tag">v{generation.version_number}</span>
					{/if}
					{#if generation.model_mode}
						<span class="model-tag">{generation.model_mode}</span>
					{/if}
					{#if generation.seed}
						<span class="seed-tag">seed:{generation.seed}</span>
					{/if}
				</div>
			</div>
			<div class="detail-actions">
				<ActionButton
					icon="star"
					activeIcon="star-filled"
					label={generation.is_picked ? 'Unpick' : 'Pick'}
					active={generation.is_picked}
					onclick={() => onPick(!generation.is_picked)}
				/>
				<ActionButton
					icon="heart"
					activeIcon="heart-filled"
					label={generation.is_kept ? 'Unkept' : 'Keep'}
					active={generation.is_kept}
					onclick={() => onKeep(!generation.is_kept)}
				/>
				<ActionButton
					icon="refresh-cw"
					label={scoring ? 'Scoring...' : 'Score'}
					disabled={scoring}
					onclick={onScore}
				/>
				<div class="picker-anchor">
					<ActionButton
						icon="list-plus"
						label="Add to Playlist"
						onclick={() => (showPlaylistPicker = true)}
					/>
					{#if showPlaylistPicker}
						<PlaylistPicker
							onselect={async (playlistId) => {
								await addGenerationToPlaylist(playlistId, generation.id);
								showPlaylistPicker = false;
								addToast('Added to playlist', 'success');
							}}
							onclose={() => (showPlaylistPicker = false)}
						/>
					{/if}
				</div>
				<ShareButton
					isShared={generation.is_shared}
					shareSlug={generation.share_slug}
					onshare={onShareEnable}
					onunshare={onShareDisable}
				/>
				<ActionButton
					icon="trash"
					label="Delete"
					destructive
					onclick={() => (showDeleteConfirm = true)}
				/>
				<button class="use-as-source-btn" onclick={onUseAsSource}>Use as Source</button>
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

		{#if generation.src_generation_number}
			<div class="lineage">
				<span class="lineage-label">Source</span>
				<span class="lineage-chain">
					{#if generation.generation_params?.task_type === 'repaint'}
						Repainted from Gen #{generation.src_generation_number}
						{#if generation.generation_params?.repainting_start != null && generation.generation_params.repainting_end != null}
							({(generation.generation_params.repainting_start * 100).toFixed(0)}%–{(
								generation.generation_params.repainting_end * 100
							).toFixed(0)}%)
						{/if}
					{:else if generation.generation_params?.task_type === 'cover'}
						Covered from Gen #{generation.src_generation_number}
						{#if generation.generation_params?.audio_cover_strength != null}
							(strength {(generation.generation_params.audio_cover_strength * 100).toFixed(0)}%)
						{/if}
					{:else}
						From Gen #{generation.src_generation_number}
					{/if}
				</span>
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
					<button class="rating-save" onclick={onRate} disabled={ratingSaving}>
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

	{#if showDeleteConfirm}
		<ConfirmDeleteDialog
			title={`Delete Generation #${generation.generation_number}?`}
			items={['Audio files will be permanently deleted']}
			confirmLabel="Delete Generation"
			onconfirm={() => {
				showDeleteConfirm = false;
				onDelete();
			}}
			oncancel={() => (showDeleteConfirm = false)}
		/>
	{/if}
{/if}

<style>
	.picker-anchor {
		position: relative;
	}

	.detail-panel {
		padding: 1.2rem 1.5rem calc(var(--player-height) + 1.2rem);
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		flex: 1;
		max-width: 1200px;
		width: 100%;
		min-width: 0;
		min-height: 0;
	}

	.back-btn {
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.8rem;
		cursor: pointer;
		padding: 0;
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.back-arrow {
		font-size: 1rem;
	}

	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.detail-title {
		font-family: var(--font-display);
		font-size: 1.73rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.13rem;
	}

	.detail-meta {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		margin-top: 0.3rem;
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
		color: var(--text-dim);
		font-family: var(--font-body);
	}

	.detail-actions {
		display: flex;
		gap: 0.55rem;
		align-items: center;
		flex-wrap: wrap;
	}

	.use-as-source-btn {
		padding: var(--btn-padding-pill);
		border: none;
		border-radius: var(--btn-radius-pill);
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		font-size: 0.78rem;
		font-family: var(--font-display);
		letter-spacing: var(--btn-letter-spacing);
		cursor: pointer;
		white-space: nowrap;
	}

	.use-as-source-btn:hover {
		filter: brightness(1.2);
	}

	.share-link {
		font-size: 0.75rem;
		color: var(--text-dim);
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 0.3rem 0.6rem;
		cursor: pointer;
		word-break: break-all;
		text-align: left;
	}

	.share-link:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.lineage {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		padding: 0.5rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.lineage-label {
		font-size: 0.7rem;
		color: var(--text-dim);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		flex-shrink: 0;
	}

	.lineage-chain {
		font-size: 0.8rem;
		color: var(--text-muted);
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
