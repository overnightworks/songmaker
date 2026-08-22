<script lang="ts">
	import type { GenerationItem, SongItem } from '$lib/api/types';
	import { NOW_PLAYING_TAKE_PREFIX } from '$lib/constants';
	import {
		NOW_PLAYING_DEVIATIONS_EMPTY,
		NOW_PLAYING_DEVIATIONS_LABEL,
		NOW_PLAYING_DEVIATIONS_UNAVAILABLE,
		NOW_PLAYING_KEEP_LABEL,
		NOW_PLAYING_LYRICS_ROW_LABEL,
		NOW_PLAYING_PICK_LABEL,
		NOW_PLAYING_PIN_SEED_PREFIX,
		NOW_PLAYING_RATING_LABEL,
		NOW_PLAYING_RATING_SAVE,
		NOW_PLAYING_RATING_SAVING,
		NOW_PLAYING_SCORES_EMPTY,
		NOW_PLAYING_SCORES_LABEL,
		NOW_PLAYING_SUNG_ROW_LABEL,
		NOW_PLAYING_UNKEEP_LABEL,
		NOW_PLAYING_UNPICK_LABEL
	} from '$lib/constants/now-playing';
	import { pinSeed, rate, setKeep, setPick } from '$lib/stores/takeActions';
	import { computeDiff, type DiffLine } from '$lib/utils/diff';
	import { scoreColor } from '$lib/utils/scores';
	import Icon from './Icon.svelte';

	let {
		generation,
		song,
		lyrics
	}: {
		generation: GenerationItem;
		song: SongItem;
		lyrics: string | null;
	} = $props();

	interface ScoreEntry {
		label: string;
		value: string;
		color: string;
	}

	const scores = $derived(generation.scores);

	const scoreEntries = $derived.by((): ScoreEntry[] => {
		if (!scores) return [];
		const entries: ScoreEntry[] = [];
		if (scores.user_rating !== undefined)
			entries.push({
				label: 'Rating',
				value: scores.user_rating.toFixed(0),
				color: scoreColor('user_rating', scores.user_rating)
			});
		if (scores.text_accuracy !== undefined)
			entries.push({
				label: 'Lyrics sung',
				value: scores.text_accuracy.toFixed(0) + '%',
				color: scoreColor('text_accuracy', scores.text_accuracy)
			});
		if (scores.dynamics !== undefined)
			entries.push({
				label: 'Dynamics',
				value: scores.dynamics.toFixed(0),
				color: scoreColor('dynamics', scores.dynamics)
			});
		if (scores.audiobox_quality !== undefined)
			entries.push({
				label: 'Quality',
				value: scores.audiobox_quality.toFixed(2),
				color: scoreColor('audiobox_quality', scores.audiobox_quality)
			});
		if (scores.audiobox_enjoyment !== undefined)
			entries.push({
				label: 'Enjoyment',
				value: scores.audiobox_enjoyment.toFixed(2),
				color: scoreColor('audiobox_enjoyment', scores.audiobox_enjoyment)
			});
		if (scores.lyrical_coherence !== undefined)
			entries.push({
				label: 'Coherence',
				value: String(scores.lyrical_coherence),
				color: scoreColor('lyrical_coherence', scores.lyrical_coherence)
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

	interface DeviationRow {
		lyricsLine: string | null;
		sungLine: string | null;
	}

	const STRUCTURAL_LINE = /^\[[^\]]+\]$/;

	// The whisper transcript is a plain sung transcription: it never contains
	// the lyrics text's blank paragraph breaks or [Verse]/[Chorus] markers.
	// Left in, computeDiff's line-level comparison flags nearly every lyrics
	// line as "removed" against those artifacts alone, drowning out the sung
	// deviations that actually matter. Dropping them from both sides before
	// diffing compares only lines that could plausibly have been sung.
	function normalizeForDiff(text: string): string {
		return text
			.split('\n')
			.map((line) => line.trim())
			.filter((line) => line.length > 0 && !STRUCTURAL_LINE.test(line))
			.join('\n');
	}

	function pairDeviations(diffLines: DiffLine[]): DeviationRow[] {
		const rows: DeviationRow[] = [];
		let i = 0;
		while (i < diffLines.length) {
			const line = diffLines[i];
			if (line.type === 'same') {
				i++;
				continue;
			}
			if (line.type === 'remove' && diffLines[i + 1]?.type === 'add') {
				rows.push({ lyricsLine: line.text, sungLine: diffLines[i + 1].text });
				i += 2;
			} else if (line.type === 'remove') {
				rows.push({ lyricsLine: line.text, sungLine: null });
				i++;
			} else {
				rows.push({ lyricsLine: null, sungLine: line.text });
				i++;
			}
		}
		return rows;
	}

	const hasTranscript = $derived(Boolean(lyrics && generation.whisper_text));
	const deviationRows = $derived.by((): DeviationRow[] => {
		if (!lyrics || !generation.whisper_text) return [];
		return pairDeviations(
			computeDiff(normalizeForDiff(lyrics), normalizeForDiff(generation.whisper_text))
		);
	});

	let ratingValue = $state(50);
	let ratingNotes = $state('');
	let ratingSaving = $state(false);

	const savedRating = $derived(generation.scores?.user_rating ?? 50);
	const savedNotes = $derived(generation.scores?.user_notes ?? '');
	const ratingDirty = $derived(ratingValue !== savedRating || ratingNotes !== savedNotes);

	$effect(() => {
		ratingValue = savedRating;
		ratingNotes = savedNotes;
	});

	async function onTogglePick(): Promise<void> {
		await setPick(song.id, generation.id, !generation.is_picked);
	}

	async function onToggleKeep(): Promise<void> {
		await setKeep(song.id, generation.id, !generation.is_kept);
	}

	async function onSaveRating(): Promise<void> {
		if (ratingSaving) return;
		ratingSaving = true;
		try {
			await rate(song.id, generation.id, ratingValue, ratingNotes);
		} finally {
			ratingSaving = false;
		}
	}

	function onPinSeed(): void {
		if (generation.seed == null) return;
		pinSeed(generation.seed);
	}
</script>

<div class="np-take" aria-label="{NOW_PLAYING_TAKE_PREFIX} {generation.generation_number}">
	<div class="take-heading-row">
		<h3 class="take-heading">
			{#if generation.version_number != null}v{generation.version_number} ·
			{/if}{NOW_PLAYING_TAKE_PREFIX}
			{generation.generation_number}
		</h3>
		<div class="take-badges">
			<button
				type="button"
				class="badge-btn"
				class:on={generation.is_picked}
				onclick={onTogglePick}
				aria-pressed={generation.is_picked}
				aria-label={generation.is_picked ? NOW_PLAYING_UNPICK_LABEL : NOW_PLAYING_PICK_LABEL}
				title={generation.is_picked ? NOW_PLAYING_UNPICK_LABEL : NOW_PLAYING_PICK_LABEL}
			>
				<Icon name={generation.is_picked ? 'star-filled' : 'star'} size={18} />
			</button>
			<button
				type="button"
				class="badge-btn"
				class:on={generation.is_kept}
				onclick={onToggleKeep}
				aria-pressed={generation.is_kept}
				aria-label={generation.is_kept ? NOW_PLAYING_UNKEEP_LABEL : NOW_PLAYING_KEEP_LABEL}
				title={generation.is_kept ? NOW_PLAYING_UNKEEP_LABEL : NOW_PLAYING_KEEP_LABEL}
			>
				<Icon name={generation.is_kept ? 'heart-filled' : 'heart'} size={18} />
			</button>
		</div>
	</div>

	<section class="take-section">
		<h4 class="section-title">{NOW_PLAYING_SCORES_LABEL}</h4>
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
			<p class="empty-note">{NOW_PLAYING_SCORES_EMPTY}</p>
		{/if}
	</section>

	<section class="take-section">
		<h4 class="section-title">{NOW_PLAYING_DEVIATIONS_LABEL}</h4>
		{#if !hasTranscript}
			<p class="empty-note">{NOW_PLAYING_DEVIATIONS_UNAVAILABLE}</p>
		{:else if deviationRows.length === 0}
			<p class="empty-note">{NOW_PLAYING_DEVIATIONS_EMPTY}</p>
		{:else}
			<ul class="deviation-list">
				{#each deviationRows as row, index (index)}
					<li class="deviation-row">
						{#if row.lyricsLine != null}
							<span class="deviation-line lyrics-line"
								><span class="deviation-tag">{NOW_PLAYING_LYRICS_ROW_LABEL}</span
								>{row.lyricsLine}</span
							>
						{/if}
						{#if row.sungLine != null}
							<span class="deviation-line sung-line"
								><span class="deviation-tag">{NOW_PLAYING_SUNG_ROW_LABEL}</span>{row.sungLine}</span
							>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="take-section">
		<div class="rating-row">
			<span class="section-title">{NOW_PLAYING_RATING_LABEL}</span>
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
		{#if ratingDirty}
			<button type="button" class="rating-save" onclick={onSaveRating} disabled={ratingSaving}>
				{ratingSaving ? NOW_PLAYING_RATING_SAVING : NOW_PLAYING_RATING_SAVE}
			</button>
		{/if}
	</section>

	{#if generation.seed != null}
		<button type="button" class="pin-seed" onclick={onPinSeed}>
			{NOW_PLAYING_PIN_SEED_PREFIX}
			{generation.seed}
		</button>
	{/if}
</div>

<style>
	.np-take {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
	}
	.take-heading-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.take-heading {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.72rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.take-badges {
		display: flex;
		gap: 0.4rem;
		margin-left: auto;
	}
	.badge-btn {
		width: 32px;
		height: 32px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--border);
		border-radius: 50%;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
	}
	.badge-btn:hover {
		color: var(--text);
		background: var(--surface-hover);
	}
	.badge-btn.on {
		color: var(--accent);
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}
	.take-section {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
	}
	.section-title {
		font-family: var(--font-display);
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-subtle);
	}
	.empty-note {
		margin: 0;
		font-size: 0.78rem;
		color: var(--text-subtle);
		font-style: italic;
	}
	.scores-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0.5rem;
	}
	.score-cell {
		display: flex;
		flex-direction: column;
		padding: 0.5rem 0.6rem;
		border-radius: 4px;
		background: var(--surface);
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
		font-size: 0.66rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.4px;
	}
	.score-value {
		font-size: 1.05rem;
		font-family: var(--font-display);
		color: var(--text);
	}
	.deviation-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.deviation-row {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		padding: 0.5rem 0.6rem;
		background: var(--surface);
		border-radius: 4px;
		font-family: 'Courier New', monospace;
		font-size: 0.78rem;
	}
	.deviation-line {
		overflow-wrap: anywhere;
	}
	.deviation-tag {
		display: inline-block;
		min-width: 3.6rem;
		color: var(--text-subtle);
		font-family: var(--font-display);
		font-size: 0.6rem;
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}
	.lyrics-line {
		color: var(--text-muted);
	}
	.sung-line {
		color: #f44;
	}
	.rating-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.rating-slider {
		flex: 1;
		accent-color: var(--accent);
		cursor: pointer;
	}
	.rating-number {
		font-size: 1rem;
		font-family: var(--font-display);
		color: var(--text);
		min-width: 28px;
		text-align: right;
	}
	.rating-save {
		align-self: flex-end;
		padding: var(--btn-padding-sm);
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
		color: var(--accent);
		font-size: 0.72rem;
		font-family: var(--font-display);
		letter-spacing: var(--btn-letter-spacing);
		cursor: pointer;
	}
	.rating-save:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.pin-seed {
		align-self: flex-start;
		padding: 0.3rem 0.7rem;
		border-radius: var(--btn-radius-pill);
		border: 1px solid var(--border);
		background: transparent;
		color: var(--text-muted);
		font-size: 0.72rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		cursor: pointer;
	}
	.pin-seed:hover {
		border-color: var(--primary);
		color: var(--text);
	}
</style>
