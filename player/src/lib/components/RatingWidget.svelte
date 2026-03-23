<script lang="ts">
	import { onDestroy } from 'svelte';
	import { browsingTrack } from '$lib/stores/player';
	import { rateVersion } from '$lib/api/client';
	import { trackFileToRoute } from '$lib/utils/html';

	let rating = $state(0);
	let comment = $state('');
	let touched = $state(false);
	let saveStatus = $state('');
	let saveTimeout: ReturnType<typeof setTimeout> | undefined;
	let statusTimeout: ReturnType<typeof setTimeout> | undefined;

	const track = $derived($browsingTrack);

	$effect(() => {
		if (!track) return;
		loadRating(track.file, track.scores?.user_rating, track.scores?.user_notes);
	});

	onDestroy(() => {
		clearTimeout(saveTimeout);
		clearTimeout(statusTimeout);
	});

	function loadRating(
		file: string,
		serverRating: number | undefined,
		serverNotes: string | undefined
	): void {
		rating = 0;
		comment = '';
		touched = false;

		const key = `rating:${file}`;
		try {
			const saved = JSON.parse(localStorage.getItem(key) ?? '{}');
			if (saved.rating !== undefined && saved.rating > 0) {
				rating = saved.rating;
				comment = saved.comment ?? '';
				touched = true;
			}
		} catch {
			// ignore corrupt localStorage
		}

		if (!touched && serverRating !== undefined) {
			rating = serverRating;
			comment = serverNotes ?? '';
			touched = true;
		}
	}

	function onSliderInput(e: Event): void {
		const input = e.target as HTMLInputElement;
		rating = parseFloat(input.value);
		touched = true;
		clearTimeout(saveTimeout);
		saveTimeout = setTimeout(save, 500);
	}

	function save(): void {
		if (!track) return;
		const key = `rating:${track.file}`;
		localStorage.setItem(key, JSON.stringify({ rating, comment }));

		const { album, version } = trackFileToRoute(track.file);
		rateVersion(album, version, rating, comment).catch(() => {});

		saveStatus = 'Saved!';
		clearTimeout(statusTimeout);
		statusTimeout = setTimeout(() => (saveStatus = ''), 1500);
	}
</script>

<div class="rating-widget">
	<div class="rating-row">
		<span class="label">Rating</span>
		<input
			type="range"
			class="slider"
			min="0"
			max="100"
			step="0.1"
			value={rating}
			oninput={onSliderInput}
			aria-label="Rating"
		/>
		<span class="value">{touched ? rating.toFixed(1) : '-'}</span>
	</div>
	<textarea
		class="comment"
		rows="2"
		placeholder="What stands out? Voice, groove, lyrics, production..."
		bind:value={comment}
		onblur={save}
	></textarea>
	{#if saveStatus}
		<span class="status">{saveStatus}</span>
	{/if}
</div>

<style>
	.rating-widget {
		margin-top: 8px;
		border-top: 1px solid var(--border);
		padding-top: 8px;
	}

	.rating-row {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 8px;
	}

	.label {
		font-size: 12px;
		color: var(--text-muted);
		width: 50px;
		flex-shrink: 0;
	}

	.slider {
		flex: 1;
		-webkit-appearance: none;
		appearance: none;
		height: 4px;
		background: var(--border);
		border-radius: 2px;
		outline: none;
	}

	.slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--primary);
		cursor: pointer;
	}

	.value {
		font-size: 13px;
		font-family: var(--font-display);
		color: var(--text-light);
		width: 32px;
		text-align: right;
	}

	.comment {
		width: 100%;
		background: var(--surface-hover);
		border: 1px solid var(--border);
		color: var(--text-light);
		padding: 6px 10px;
		font-family: var(--font-body);
		font-size: 12px;
		border-radius: 4px;
		resize: none;
		margin-top: 4px;
	}

	.comment:focus {
		border-color: var(--primary);
		outline: none;
	}

	.status {
		font-size: 11px;
		color: var(--success);
	}
</style>
