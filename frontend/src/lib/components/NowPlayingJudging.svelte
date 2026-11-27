<script lang="ts" module>
	// How long the note rests before it saves on its own.
	export const NOTE_SAVE_PAUSE_MS = 800;
</script>

<script lang="ts">
	import { untrack } from 'svelte';
	import type { GenerationItem, SongItem } from '#lib/api/types.ts';
	import { rate, toggleKeep, togglePick } from '#lib/stores/takeActions.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from './Icon.svelte';

	let {
		generation,
		song
	}: {
		generation: GenerationItem;
		song: SongItem;
	} = $props();

	const ratingId = $props.id();

	// The rate route takes a rating with every note, so an unrated take starts
	// its slider at the middle.
	const UNRATED_START = 50;

	const savedRating = $derived(generation.scores?.user_rating ?? UNRATED_START);
	const savedNotes = $derived(generation.scores?.user_notes ?? '');

	let ratingValue = $state(UNRATED_START);
	let notes = $state('');
	let shownRating = UNRATED_START;
	let shownNotes = '';
	let pauseTimer: ReturnType<typeof setTimeout> | undefined;
	let pendingNoteSave: (() => void) | null = null;

	// A saved value that arrives later (the song loads, another surface rates)
	// replaces only a field the listener has not touched.
	$effect(() => {
		const rating = savedRating;
		const saved = savedNotes;
		untrack(() => {
			if (ratingValue === shownRating) ratingValue = rating;
			if (notes === shownNotes) notes = saved;
			shownRating = rating;
			shownNotes = saved;
		});
	});

	function saveRating(): void {
		cancelNoteSave();
		void rate(song.id, generation.id, ratingValue, notes);
	}

	function cancelNoteSave(): void {
		clearTimeout(pauseTimer);
		pendingNoteSave = null;
	}

	function onNoteInput(): void {
		clearTimeout(pauseTimer);
		const args = [song.id, generation.id, ratingValue, notes] as const;
		pendingNoteSave = () => void rate(...args);
		pauseTimer = setTimeout(flushNoteSave, NOTE_SAVE_PAUSE_MS);
	}

	function flushNoteSave(): void {
		clearTimeout(pauseTimer);
		const save = pendingNoteSave;
		pendingNoteSave = null;
		save?.();
	}

	$effect(() => flushNoteSave);
</script>

<section class="judging" aria-label={pageText('nowPlayingJudging.label')}>
	<div class="judging-top">
		<button
			type="button"
			class="badge-btn"
			data-hitbox="frequent"
			class:on={generation.is_picked}
			onclick={() => togglePick(song.id, generation)}
			aria-pressed={generation.is_picked}
			aria-label={pageText(
				generation.is_picked ? 'nowPlayingJudging.unpick' : 'nowPlayingJudging.pick'
			)}
			title={pageText(generation.is_picked ? 'nowPlayingJudging.unpick' : 'nowPlayingJudging.pick')}
		>
			<Icon name={generation.is_picked ? 'star-filled' : 'star'} size={18} />
			{pageText('nowPlayingJudging.pick')}
		</button>
		<button
			type="button"
			class="badge-btn"
			data-hitbox="frequent"
			class:on={generation.is_kept}
			onclick={() => toggleKeep(song.id, generation)}
			aria-pressed={generation.is_kept}
			aria-label={pageText(
				generation.is_kept ? 'nowPlayingJudging.unkeep' : 'nowPlayingJudging.keep'
			)}
			title={pageText(generation.is_kept ? 'nowPlayingJudging.unkeep' : 'nowPlayingJudging.keep')}
		>
			<Icon name={generation.is_kept ? 'heart-filled' : 'heart'} size={18} />
			{pageText('nowPlayingJudging.keep')}
		</button>
	</div>
	<div class="judging-rating">
		<label class="rating-label" for={ratingId}>{pageText('nowPlayingJudging.rating')}</label>
		<input
			id={ratingId}
			type="range"
			class="rating-slider"
			min="0"
			max="100"
			step="1"
			bind:value={ratingValue}
			onchange={saveRating}
		/>
		<span class="rating-number">{ratingValue}</span>
	</div>
	<textarea
		class="rating-notes"
		aria-label={pageText('nowPlayingJudging.ratingNotes')}
		placeholder={pageText('nowPlayingJudging.ratingNotes')}
		bind:value={notes}
		oninput={onNoteInput}
		onblur={flushNoteSave}
		rows="2"></textarea>
</section>

<style>
	.judging {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		align-self: stretch;
		padding: 0.6rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}
	.judging-top,
	.judging-rating {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.badge-btn {
		flex: 1;
		min-height: 36px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.4rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		font-family: var(--font-body);
		font-weight: 600;
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
	.rating-label {
		font-size: var(--label-font-size);
		color: var(--text-muted);
	}
	.rating-slider {
		flex: 1;
		min-width: 0;
		accent-color: var(--accent);
		cursor: pointer;
	}
	.rating-number {
		min-width: 28px;
		text-align: right;
		font-size: 1rem;
		font-family: var(--font-display);
		color: var(--text);
	}
	.rating-notes {
		background: var(--header-bg);
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
</style>
