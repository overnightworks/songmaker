<script lang="ts">
	import type { WhisperCue } from '$lib/api/types';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		NOW_PLAYING_LYRICS_UNSYNCED_NOTE,
		NOW_PLAYING_LYRICS_ROW_LABEL
	} from '$lib/constants/now-playing';
	import { alignInWorker } from '$lib/services/lyricsAlignment';
	import { activeLyricLineIndices, type AlignedLyricLine } from '$lib/utils/lyrics-align';

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

	// Sub-pixel rounding leaves a fraction of a pixel unscrolled at the very
	// end; anything under this counts as "the reader has seen the last line".
	const SCROLL_END_TOLERANCE_PX = 1;

	const hasLyrics = $derived(lyrics != null && lyrics.length > 0);
	const hasCues = $derived(cues != null && cues.length > 0);
	// Aligning a take is too slow for the main thread (#158), so the lines
	// arrive from a worker and the take is read as plain text until they do.
	// The request is keyed on the take: its lyrics and the identity of its cue
	// list, never on a playback tick.
	let alignedLines = $state<AlignedLyricLine[] | null>(null);

	$effect(() => {
		const takeLyrics = lyrics;
		const takeCues = cues;
		alignedLines = null;
		if (takeLyrics == null || takeLyrics.length === 0) return;
		if (takeCues == null || takeCues.length === 0) return;

		let superseded = false;
		alignInWorker(takeLyrics, takeCues)
			.then((lines) => {
				if (!superseded && lines) alignedLines = lines;
			})
			.catch((error) => console.error(error));
		return () => {
			superseded = true;
		};
	});
	// A cue window puts one span on several lines, so more than one line can be
	// active at a time. The scroll target is derived as a plain index so the
	// effect below runs on a change of line, not on every playback tick.
	const activeIndices = $derived(
		alignedLines ? activeLyricLineIndices(alignedLines, audioPlayer.currentTime) : []
	);
	const scrollTargetIndex = $derived(activeIndices.length > 0 ? activeIndices[0] : null);
	const showUnsyncedNote = $derived(hasLyrics && !hasCues && Boolean(whisperText));
	const renderedLineCount = $derived(alignedLines?.length ?? (hasLyrics ? 1 : 0));

	function overflowsBelow(el: HTMLElement | undefined): boolean {
		if (!el) return false;
		return el.scrollHeight - el.clientHeight - el.scrollTop > SCROLL_END_TOLERANCE_PX;
	}

	// The lyrics box is only as tall as the column allows — in the 400px docked
	// panel long lyrics are cut at its bottom edge, mid-line, which reads as
	// broken rather than as scrollable. The fade names the cut as "there is
	// more below" and lifts at the last line (#163/8).
	let moreBelow = $state(false);

	// Three things change the answer: scrolling (handled on the element), new
	// lyrics, and the box changing size — docking, expanding, collapsing or a
	// rotated phone all resize it without remounting anything, so a measurement
	// taken once would keep a fade over text that now fits, or leave a cut edge
	// unmarked.
	$effect(() => {
		const el = container;
		const lines = renderedLineCount;
		if (!el || lines === 0) {
			moreBelow = false;
			return;
		}
		const measure = () => {
			moreBelow = overflowsBelow(el);
		};
		measure();
		const observer = new ResizeObserver(measure);
		observer.observe(el);
		return () => observer.disconnect();
	});

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
		<div
			class="lyrics"
			class:lyrics-synced={alignedLines !== null}
			class:more-below={moreBelow}
			bind:this={container}
			onscroll={() => (moreBelow = overflowsBelow(container))}
		>
			{#if alignedLines}
				{#each alignedLines as line, index (index)}
					<p
						class="lyrics-line"
						class:active={activeIndices.includes(index)}
						data-line-index={index}
					>
						{line.text}
					</p>
				{/each}
			{:else}
				<p class="lyrics-text">{lyrics}</p>
			{/if}
		</div>
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
		--lyrics-fade: 2.5rem;
		flex: 1;
		min-height: 0;
		/* Keeps the line that follows the audio out of the faded strip, so a
		   synced line is never read half-transparent. */
		scroll-padding-block-end: var(--lyrics-fade);
		font-family: var(--font-body);
		font-size: 1rem;
		line-height: 1.6;
		color: var(--text);
	}
	.lyrics.more-below {
		mask-image: linear-gradient(to bottom, #000 calc(100% - var(--lyrics-fade)), transparent);
	}

	/* The take's own line breaks are the lyrics' shape — an unscored take has
	   no cues to split them by, so the raw text keeps them verbatim. */
	.lyrics-text {
		margin: 0;
		white-space: pre-wrap;
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
