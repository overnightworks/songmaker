<script lang="ts">
	import type { WhisperCue } from '$lib/api/types';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		NOW_PLAYING_LYRICS_UNSYNCED_NOTE,
		NOW_PLAYING_LYRICS_ROW_LABEL
	} from '$lib/constants/now-playing';
	import { activeLyricLineIndices, alignLyricsToCues } from '$lib/utils/lyrics-align';

	let {
		lyrics,
		cues,
		whisperText,
		emptyLabel
	}: {
		lyrics: string | null;
		cues: WhisperCue[] | null;
		whisperText: string | null;
		emptyLabel: string;
	} = $props();

	let container: HTMLDivElement | undefined = $state();

	const hasLyrics = $derived(lyrics != null && lyrics.length > 0);
	const hasCues = $derived(cues != null && cues.length > 0);
	const alignedLines = $derived.by(() => {
		if (lyrics == null || lyrics.length === 0) return null;
		if (cues == null || cues.length === 0) return null;
		return alignLyricsToCues(lyrics, cues);
	});
	// A cue window puts one span on several lines, so more than one line can be
	// active at a time. The scroll target is derived as a plain index so the
	// effect below runs on a change of line, not on every playback tick.
	const activeIndices = $derived(
		alignedLines ? activeLyricLineIndices(alignedLines, audioPlayer.currentTime) : []
	);
	const scrollTargetIndex = $derived(activeIndices.length > 0 ? activeIndices[0] : null);
	const showUnsyncedNote = $derived(hasLyrics && !hasCues && Boolean(whisperText));

	$effect(() => {
		const index = scrollTargetIndex;
		if (index === null || !container) return;
		const el = container.querySelector<HTMLElement>(`[data-line-index="${index}"]`);
		if (!el || typeof el.scrollIntoView !== 'function') return;
		const reducedMotion =
			typeof window !== 'undefined' &&
			typeof window.matchMedia === 'function' &&
			window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		el.scrollIntoView({ block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' });
	});
</script>

<div class="np-lyrics">
	<p class="lyrics-heading">{NOW_PLAYING_LYRICS_ROW_LABEL}</p>
	{#if hasLyrics}
		{#if alignedLines}
			<div class="lyrics lyrics-synced" bind:this={container}>
				{#each alignedLines as line, index (index)}
					<p
						class="lyrics-line"
						class:active={activeIndices.includes(index)}
						data-line-index={index}
					>
						{line.text}
					</p>
				{/each}
			</div>
		{:else}
			<div class="lyrics">{lyrics}</div>
		{/if}
		{#if showUnsyncedNote}
			<p class="lyrics-unsynced">{NOW_PLAYING_LYRICS_UNSYNCED_NOTE}</p>
		{/if}
	{:else}
		<p class="lyrics-empty">{emptyLabel}</p>
	{/if}
</div>

<style>
	.np-lyrics {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
		min-height: 6rem;
	}
	.lyrics-heading {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.68rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-subtle);
	}
	.lyrics,
	.lyrics-empty {
		margin: 0;
		min-height: 4.5rem;
		max-height: 60vh;
		overflow: auto;
		overflow-wrap: anywhere;
	}
	.lyrics {
		flex: 1;
		min-height: 0;
		white-space: pre-wrap;
		font-family: var(--font-body);
		font-size: 1rem;
		line-height: 1.6;
		color: var(--text);
	}
	.lyrics-synced {
		white-space: normal;
	}
	.lyrics-line {
		margin: 0 0 0.5rem;
		color: var(--text-muted);
		transition: color 0.15s ease;
	}
	.lyrics-line.active {
		color: var(--text);
		font-weight: 600;
	}
	.lyrics-empty {
		color: var(--text-muted);
		font-size: 0.85rem;
	}
	.lyrics-unsynced {
		margin: 0;
		font-size: 0.78rem;
		color: var(--text-subtle);
	}

	@media (prefers-reduced-motion: reduce) {
		.lyrics-line {
			transition: none;
		}
	}
</style>
