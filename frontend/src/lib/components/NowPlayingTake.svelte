<script lang="ts">
	import type { GenerationItem, SongItem } from '$lib/api/types';
	import { NOW_PLAYING_TAKE_PREFIX, TAKE_USE_AS_REFERENCE_LABEL } from '$lib/constants';
	import {
		NOW_PLAYING_DEVIATIONS_EMPTY,
		NOW_PLAYING_DEVIATIONS_LABEL,
		NOW_PLAYING_DEVIATIONS_UNAVAILABLE,
		NOW_PLAYING_DEVIATION_ADDED_TITLE,
		NOW_PLAYING_KEEP_LABEL,
		NOW_PLAYING_LYRICS_ROW_LABEL,
		NOW_PLAYING_PICK_LABEL,
		NOW_PLAYING_PIN_SEED_PREFIX,
		NOW_PLAYING_RATING_LABEL,
		NOW_PLAYING_RATING_NOTES_PLACEHOLDER,
		NOW_PLAYING_RATING_SAVE,
		NOW_PLAYING_RATING_SAVING,
		NOW_PLAYING_SCORES_EMPTY,
		NOW_PLAYING_SCORES_LABEL,
		NOW_PLAYING_UNKEEP_LABEL,
		NOW_PLAYING_UNPICK_LABEL
	} from '$lib/constants/now-playing';
	import { revealPlayingSong } from '$lib/stores/navigation';
	import { closeNowPlaying } from '$lib/stores/player';
	import { pendingSource } from '$lib/stores/recipe';
	import { pinSeed, rate, setKeep, setPick } from '$lib/stores/takeActions';
	import { computeDiffByKey } from '$lib/utils/diff';
	import { normalizeLyricsToken } from '$lib/utils/lyrics-normalize';
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

	interface DeviationToken {
		text: string;
		kind: 'same' | 'changed' | 'missing' | 'added';
		lyricsText?: string;
	}

	interface WordToken {
		raw: string;
		key: string;
	}

	const STRUCTURAL_LINE = /^\[[^\]]+\]$/;

	// The whisper transcript is a plain sung transcription with its own line
	// breaks (or none) — it shares neither the lyrics text's line wrapping nor
	// its blank paragraph breaks and [Verse]/[Chorus] markers. Comparing whole
	// lines against that would flag nearly every lyrics line as "removed"
	// without ever finding the sung line it corresponds to. Splitting both
	// texts into words instead — after dropping the lines-only artifacts —
	// makes a substituted, skipped, or added word the unit of comparison,
	// where a real sung deviation is actually visible. Each word carries a
	// normalized `key` (issue #45's contract) alongside its `raw` display
	// text, so punctuation and casing differences never register as
	// deviations — only an actually different word does. A word that
	// normalizes to nothing (pure punctuation) carries no sung content and is
	// dropped before diffing.
	function tokenizeWords(text: string): WordToken[] {
		return text
			.split('\n')
			.map((line) => line.trim())
			.filter((line) => line.length > 0 && !STRUCTURAL_LINE.test(line))
			.join(' ')
			.split(/\s+/)
			.filter(Boolean)
			.map((raw) => ({ raw, key: normalizeLyricsToken(raw) }))
			.filter((token) => token.key.length > 0);
	}

	// computeDiffByKey only marks an index null on the side that has no
	// matched token (an 'add' has no oldIndex, a 'remove' has no newIndex);
	// every call site below reads the index on the side its own entry type
	// guarantees is set, so a missing index here means the diff and the
	// token arrays it was built from have gone out of sync — a bug worth
	// failing loudly on, not silently working around.
	function rawAt(tokens: WordToken[], index: number | null): string {
		if (index === null) throw new Error('Expected a matched word-diff index');
		return tokens[index].raw;
	}

	function buildDeviationTokens(
		lyricsTokens: WordToken[],
		whisperTokens: WordToken[]
	): DeviationToken[] {
		const diff = computeDiffByKey(
			lyricsTokens.map((token) => token.key),
			whisperTokens.map((token) => token.key)
		);
		const tokens: DeviationToken[] = [];
		let i = 0;
		while (i < diff.length) {
			const entry = diff[i];
			if (entry.type === 'same') {
				tokens.push({ text: rawAt(whisperTokens, entry.newIndex), kind: 'same' });
				i++;
			} else if (entry.type === 'remove' && diff[i + 1]?.type === 'add') {
				tokens.push({
					text: rawAt(whisperTokens, diff[i + 1].newIndex),
					kind: 'changed',
					lyricsText: rawAt(lyricsTokens, entry.oldIndex)
				});
				i += 2;
			} else if (entry.type === 'remove') {
				tokens.push({ text: rawAt(lyricsTokens, entry.oldIndex), kind: 'missing' });
				i++;
			} else {
				tokens.push({ text: rawAt(whisperTokens, entry.newIndex), kind: 'added' });
				i++;
			}
		}
		return tokens;
	}

	const hasTranscript = $derived(Boolean(lyrics && generation.whisper_text));
	const deviationTokens = $derived.by((): DeviationToken[] => {
		if (!lyrics || !generation.whisper_text) return [];
		return buildDeviationTokens(tokenizeWords(lyrics), tokenizeWords(generation.whisper_text));
	});
	const hasDeviations = $derived(deviationTokens.some((token) => token.kind !== 'same'));

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

	// Hands the take off to the editor's repaint/cover source (stores/recipe.ts
	// pendingSource) and navigates to its song. Now Playing closes first so
	// the editor underneath is visible. SongDetailView only applies
	// pendingSource once that target song is the one actually mounted — if a
	// dirty-draft guard defers the navigation and the user then cancels it,
	// SongDetailView clears pendingSource instead of applying it to the song
	// the user stayed on.
	function onUseAsReference(): void {
		pendingSource.set({ generation, mode: 'repaint' });
		closeNowPlaying();
		void revealPlayingSong(song, generation.id);
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
		{:else if !hasDeviations}
			<p class="empty-note">{NOW_PLAYING_DEVIATIONS_EMPTY}</p>
		{:else}
			<p class="deviation-text">
				{#each deviationTokens as token, index (index)}<span
						class="dev-token"
						class:changed={token.kind === 'changed'}
						class:missing={token.kind === 'missing'}
						class:added={token.kind === 'added'}
						title={token.lyricsText
							? `${NOW_PLAYING_LYRICS_ROW_LABEL}: ${token.lyricsText}`
							: token.kind === 'added'
								? NOW_PLAYING_DEVIATION_ADDED_TITLE
								: undefined}
						aria-label={token.kind === 'added'
							? `${token.text} (${NOW_PLAYING_DEVIATION_ADDED_TITLE})`
							: undefined}>{token.text}</span
					>{/each}
			</p>
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
		<textarea
			class="rating-notes"
			placeholder={NOW_PLAYING_RATING_NOTES_PLACEHOLDER}
			bind:value={ratingNotes}
			rows="2"
		></textarea>
		{#if ratingDirty}
			<button type="button" class="rating-save" onclick={onSaveRating} disabled={ratingSaving}>
				{ratingSaving ? NOW_PLAYING_RATING_SAVING : NOW_PLAYING_RATING_SAVE}
			</button>
		{/if}
	</section>

	<div class="take-links">
		{#if generation.seed != null}
			<button type="button" class="pin-seed" onclick={onPinSeed}>
				{NOW_PLAYING_PIN_SEED_PREFIX}
				{generation.seed}
			</button>
		{/if}
		<button type="button" class="use-as-reference" onclick={onUseAsReference}>
			{TAKE_USE_AS_REFERENCE_LABEL}
		</button>
	</div>
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
	.deviation-text {
		margin: 0;
		padding: 0.6rem 0.7rem;
		background: var(--surface);
		border-radius: 4px;
		font-family: 'Courier New', monospace;
		font-size: 0.8rem;
		line-height: 1.8;
		color: var(--text-muted);
		overflow-wrap: break-word;
	}
	.dev-token {
		margin-right: 0.3em;
	}
	.dev-token.changed {
		color: #f44;
		text-decoration: underline dotted;
		text-underline-offset: 2px;
		cursor: help;
	}
	.dev-token.missing {
		color: var(--text-subtle);
		text-decoration: line-through;
	}
	.dev-token.added {
		color: #f90;
		text-decoration: underline dotted;
		text-underline-offset: 2px;
		cursor: help;
	}
	.rating-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.rating-notes {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 0.8rem;
		font-family: var(--font-body);
		padding: 0.4rem 0.55rem;
		resize: vertical;
	}
	.rating-notes:focus {
		outline: none;
		border-color: var(--accent);
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
	.take-links {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.pin-seed,
	.use-as-reference {
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
	.pin-seed:hover,
	.use-as-reference:hover {
		border-color: var(--primary);
		color: var(--text);
	}
</style>
