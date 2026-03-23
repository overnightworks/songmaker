<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { TrackScores } from '$lib/api/types';
	import { browsingTrack, updateTrackScores } from '$lib/stores/player';
	import { rateVersion } from '$lib/api/client';
	import { trackFileToRoute } from '$lib/utils/html';

	interface Props {
		scores: TrackScores | null;
	}

	let { scores }: Props = $props();
	let collapsed = $state(true);

	const track = $derived($browsingTrack);

	let rating = $state(0);
	let comment = $state('');
	let touched = $state(false);
	let saveStatus = $state('');
	let saveTimeout: ReturnType<typeof setTimeout> | undefined;
	let statusTimeout: ReturnType<typeof setTimeout> | undefined;
	let lastLoadedFile = $state('');

	$effect(() => {
		if (!track) return;
		if (track.file === lastLoadedFile) return;
		lastLoadedFile = track.file;
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

	function onRatingChange(value: number): void {
		rating = value;
		touched = true;
		clearTimeout(saveTimeout);
		saveTimeout = setTimeout(save, 500);
	}

	function save(): void {
		if (!track) return;
		const key = `rating:${track.file}`;
		localStorage.setItem(key, JSON.stringify({ rating, comment }));

		updateTrackScores(track.file, { user_rating: rating, user_notes: comment });

		const { album, version } = trackFileToRoute(track.file);
		rateVersion(album, version, rating, comment).catch(() => {});

		saveStatus = 'Saved!';
		clearTimeout(statusTimeout);
		statusTimeout = setTimeout(() => (saveStatus = ''), 1500);
	}

	const SCORE_LABELS: Record<string, string> = {
		lyrical_coherence: 'Lyrical Coherence',
		lyrical_summary: 'Lyrical Summary',
		dynamics: 'Dynamics',
		text_accuracy: 'Text Accuracy',
		audiobox_enjoyment: 'Enjoyment',
		audiobox_understanding: 'Understanding',
		audiobox_complexity: 'Complexity',
		audiobox_quality: 'Production Quality',
		silence_gaps: 'Silence Gaps',
		spectral_artifacts: 'Artifacts'
	};

	const entries = $derived.by(() => {
		if (!scores) return [];
		return Object.entries(SCORE_LABELS)
			.filter(([key]) => scores[key as keyof TrackScores] !== undefined)
			.map(([key, label]) => {
				const raw = scores[key as keyof TrackScores];
				let display = String(raw);
				if (key === 'lyrical_coherence') display = `${raw}/10`;
				else if (typeof raw === 'number' && key !== 'silence_gaps' && key !== 'spectral_artifacts')
					display = raw.toFixed(1);
				return { key, label, display, raw };
			});
	});
</script>

<section class="panel" class:collapsed>
	<button
		class="panel-header"
		onclick={() => (collapsed = !collapsed)}
		aria-expanded={!collapsed}
		aria-label="Toggle scores"
	>
		<h3>{collapsed ? '▸' : '▾'} Scores</h3>
	</button>
	{#if !collapsed}
		<div class="grid">
			{#each entries as { key, label, display, raw } (key)}
				<div class="item">
					{label}:
					{#if key === 'lyrical_summary' && typeof raw === 'string' && raw.length > 40}
						<span class="value summary" title={raw}>{raw.substring(0, 40)}...</span>
					{:else}
						<span class="value">{display}</span>
					{/if}
				</div>
			{/each}
		</div>

		<div class="rating-section">
			<div class="rating-row">
				<span class="rating-label">Your Rating</span>
				<input
					type="range"
					class="rating-slider"
					min="0"
					max="100"
					step="0.1"
					bind:value={rating}
					oninput={() => onRatingChange(rating)}
					aria-label="Your rating"
				/>
				<span class="rating-value">{touched ? rating.toFixed(1) : '-'}</span>
			</div>
			<textarea
				class="comment"
				rows="2"
				placeholder="What stands out? Voice, groove, lyrics, production..."
				bind:value={comment}
				onblur={save}
			></textarea>
			{#if saveStatus}
				<span class="save-status">{saveStatus}</span>
			{/if}
		</div>
	{/if}
</section>

<style>
	.panel {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 10px 16px;
		margin: 4px 0 8px;
		flex-shrink: 0;
	}

	.panel-header {
		background: none;
		border: none;
		width: 100%;
		text-align: left;
		padding: 0;
	}

	.panel-header h3 {
		font-family: var(--font-display);
		font-size: 13px;
		color: var(--primary);
		text-transform: uppercase;
		letter-spacing: 1px;
		user-select: none;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 4px 16px;
		margin-top: 6px;
	}

	.item {
		font-size: 11px;
		color: var(--text-muted);
	}

	.value {
		color: var(--text-light);
	}

	.summary {
		cursor: help;
	}

	.rating-section {
		margin-top: 10px;
		padding-top: 8px;
		border-top: 1px solid var(--border);
	}

	.rating-row {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 6px;
	}

	.rating-label {
		font-size: 11px;
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.rating-slider {
		flex: 1;
		-webkit-appearance: none;
		appearance: none;
		height: 4px;
		background: var(--border);
		border-radius: 2px;
		outline: none;
	}

	.rating-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--primary);
		cursor: pointer;
	}

	.rating-value {
		font-size: 13px;
		font-family: var(--font-display);
		color: var(--text-light);
		min-width: 32px;
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
	}

	.comment:focus {
		border-color: var(--primary);
		outline: none;
	}

	.save-status {
		font-size: 11px;
		color: var(--success);
	}
</style>
