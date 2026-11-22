<script lang="ts">
	import type { WhisperCue } from '#lib/api/types.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import { alignInWorker } from '#lib/services/lyricsAlignment.svelte.ts';
	import {
		activeLyricLineIndices,
		displayWords,
		type AlignedLyricLine
	} from '#lib/utils/lyrics-align.ts';
	import { preferredScrollBehavior } from '#lib/utils/motion.ts';

	let {
		lyrics,
		cues,
		whisperText,
		emptyLabel,
		position,
		songTitle,
		sungMarks = false
	}: {
		lyrics: string | null;
		cues: WhisperCue[] | null;
		whisperText: string | null;
		emptyLabel: string;
		// Where the take stands, in seconds; null while nothing is sung, so no
		// line lights and the box stays where it is.
		position: number | null;
		// Names the song above its words where several songs share one page.
		songTitle?: string;
		// Underlines the words sung differently and opens what was sung under
		// their line; the signed-in player sets it, the share pages do not.
		sungMarks?: boolean;
	} = $props();

	let container: HTMLDivElement | undefined = $state();

	// Sub-pixel rounding stops a scroll a fraction of a pixel short of where
	// it was headed; anything under this counts as having arrived.
	const SCROLL_ROUNDING_PX = 1;
	// The faded strip at the bottom edge; the line that follows the audio is
	// kept above it, so a synced line is never read half-transparent.
	const LYRICS_FADE_PX = 40;
	// The keys that scroll a focused box: pressing one is the reader scrolling.
	const SCROLL_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']);

	const hasLyrics = $derived(lyrics != null && lyrics.length > 0);
	const hasCues = $derived(cues != null && cues.length > 0);
	// Aligning a take is too slow for the main thread (#158), so the lines
	// arrive from a worker and the take is read as plain text until they do.
	// The request is keyed on the take: its lyrics and the identity of its cue
	// list, never on a playback tick.
	let alignedLines = $state<AlignedLyricLine[] | null>(null);
	// Synced lyrics follow the sung line until the reader scrolls them by
	// hand; then they stay where the reader put them until Follow is pressed
	// or another take starts.
	let following = $state(true);

	// The one mark whose line shows its Sung line: the one a tap opened, or,
	// while nothing is opened and a fine pointer rests on a mark, the one it
	// rests on. A hover never replaces an opened line: closing it would pull
	// a lower mark out from under the pointer.
	interface MarkRef {
		line: number;
		word: number;
	}
	let tappedMark = $state<MarkRef | null>(null);
	let hoveredMark = $state<MarkRef | null>(null);
	const shownMark = $derived(tappedMark ?? hoveredMark);
	// Words stay separate nodes, so the space between them is written out.
	const WORD_SEPARATOR = ' ';
	const HOVER_POINTER = '(hover: hover) and (pointer: fine)';

	function isShown(line: number, word: number): boolean {
		return shownMark?.line === line && shownMark.word === word;
	}

	function toggleMark(line: number, word: number): void {
		if (tappedMark?.line === line && tappedMark.word === word) {
			// The pointer still rests on the mark and fires no new enter, so the
			// hover must not keep the closed line showing.
			tappedMark = null;
			hoveredMark = null;
		} else {
			tappedMark = { line, word };
		}
	}

	function hoverMark(mark: MarkRef | null): void {
		if (mark === null || window.matchMedia(HOVER_POINTER).matches) hoveredMark = mark;
	}

	$effect(() => {
		const takeLyrics = lyrics;
		const takeCues = cues;
		alignedLines = null;
		following = true;
		tappedMark = null;
		hoveredMark = null;
		if (takeLyrics == null || takeLyrics.length === 0) return;
		if (takeCues == null || takeCues.length === 0) return;

		let superseded = false;
		alignInWorker(takeLyrics, takeCues).then((lines) => {
			if (!superseded && lines) alignedLines = lines;
		});
		return () => {
			superseded = true;
		};
	});
	// A cue window puts one span on several lines, so more than one line can be
	// active at a time. The scroll target is derived as a plain index so the
	// effect below runs on a change of line, not on every playback tick.
	const activeIndices = $derived(
		alignedLines && position !== null ? activeLyricLineIndices(alignedLines, position) : []
	);
	const scrollTargetIndex = $derived(activeIndices.length > 0 ? activeIndices[0] : null);
	const showUnsyncedNote = $derived(hasLyrics && !hasCues && Boolean(whisperText));
	const renderedLineCount = $derived(alignedLines?.length ?? (hasLyrics ? 1 : 0));
	const showFollow = $derived(alignedLines !== null && !following);

	function canScroll(el: HTMLElement): boolean {
		return el.scrollHeight - el.clientHeight > SCROLL_ROUNDING_PX;
	}

	function overflowsBelow(el: HTMLElement | undefined): boolean {
		if (!el) return false;
		return el.scrollHeight - el.clientHeight - el.scrollTop > SCROLL_ROUNDING_PX;
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

	// Where the box last sent itself to the sung line: from where it set out
	// to where it was headed. A smooth scroll passes every position between
	// the two; once it arrives, only the arrival is still its own.
	let ownScroll: { from: number; to: number } | null = null;

	function pauseFollowing(): void {
		if (alignedLines && container && canScroll(container)) following = false;
	}

	// A box that grew since clamps its scroll to its new end, and that clamp
	// is still the box's own scroll rather than the reader's.
	function clampToScrollRange(el: HTMLElement, top: number): number {
		return Math.max(0, Math.min(top, el.scrollHeight - el.clientHeight));
	}

	// Wheel, touch and keys name the reader before the box even moves, but
	// a dragged scrollbar fires none of them: a scroll that lands anywhere the
	// box did not send itself is the reader's too.
	function followOrPauseAt(el: HTMLElement): void {
		if (!ownScroll) {
			pauseFollowing();
			return;
		}
		const from = clampToScrollRange(el, ownScroll.from);
		const to = clampToScrollRange(el, ownScroll.to);
		const position = el.scrollTop;
		const outsideOwnWay =
			position < Math.min(from, to) - SCROLL_ROUNDING_PX ||
			position > Math.max(from, to) + SCROLL_ROUNDING_PX;
		if (outsideOwnWay) pauseFollowing();
		else if (Math.abs(position - to) <= SCROLL_ROUNDING_PX) ownScroll = { from: to, to };
	}

	function onScroll(): void {
		if (!container) return;
		moreBelow = overflowsBelow(container);
		if (following) followOrPauseAt(container);
	}

	// Space on a focused mark activates the button; it is no reader scroll.
	function pauseOnScrollKey(event: KeyboardEvent): void {
		if (event.target instanceof HTMLButtonElement) return;
		if (SCROLL_KEYS.has(event.key)) pauseFollowing();
	}

	// Scrolls the lyrics box alone, never the surface around it: a listener
	// who scrolled the player to its transport or queue stays there.
	function revealLine(box: HTMLElement, line: HTMLElement): void {
		const view = box.getBoundingClientRect();
		const row = line.getBoundingClientRect();
		const readableBottom = Math.max(view.top, view.bottom - LYRICS_FADE_PX);
		let offset = 0;
		if (row.top < view.top) offset = row.top - view.top;
		else if (row.bottom > readableBottom) offset = row.bottom - readableBottom;
		if (offset === 0) return;
		// An absolute target: a relative scroll may add to a smooth scroll still
		// under way, landing past where the box was sent.
		ownScroll = { from: box.scrollTop, to: box.scrollTop + offset };
		box.scrollTo({ top: ownScroll.to, behavior: preferredScrollBehavior() });
	}

	$effect(() => {
		const index = scrollTargetIndex;
		if (!following || index === null || !container) return;
		const line = container.querySelector<HTMLElement>(`[data-line-index="${index}"]`);
		if (line) revealLine(container, line);
	});
</script>

<div class="np-lyrics">
	<p class="lyrics-heading">
		{songTitle
			? pageText('nowPlaying.lyricsHeadingTitled', { title: songTitle })
			: pageText('nowPlaying.lyricsHeading')}
	</p>
	{#if hasLyrics}
		<div
			class="lyrics"
			class:lyrics-synced={alignedLines !== null}
			class:more-below={moreBelow}
			style:--lyrics-fade="{LYRICS_FADE_PX}px"
			role="presentation"
			bind:this={container}
			onscroll={onScroll}
			onwheel={pauseFollowing}
			ontouchmove={pauseFollowing}
			onkeydown={pauseOnScrollKey}
		>
			{#if alignedLines}
				{#each alignedLines as line, index (index)}
					<p
						class="lyrics-line"
						class:active={activeIndices.includes(index)}
						data-line-index={index}
					>
						{#if sungMarks && line.marks.length > 0}
							{#each displayWords(line.text) as word, wordIndex (wordIndex)}
								{#if line.marks.includes(wordIndex)}
									<button
										type="button"
										class="sung-mark"
										data-hitbox="text"
										aria-expanded={isShown(index, wordIndex)}
										aria-controls="sung-line-{index}"
										onclick={() => toggleMark(index, wordIndex)}
										onpointerenter={(event) =>
											event.pointerType === 'mouse' && hoverMark({ line: index, word: wordIndex })}
										onpointerleave={() => hoverMark(null)}>{word}</button
									>
								{:else}
									{word}
								{/if}{WORD_SEPARATOR}
							{/each}
						{:else}
							{line.text}
						{/if}
					</p>
					{#if sungMarks && shownMark?.line === index}
						<p class="sung-line" id="sung-line-{index}">
							<span class="sung-label">{pageText('nowPlaying.sungLine')}</span>
							{#if line.sung}
								{#each line.sung as word, wordIndex (wordIndex)}
									<span class:sung-differs={word.differs}>{word.text}</span>{WORD_SEPARATOR}
								{/each}
							{:else}
								{pageText('nowPlaying.sungNothing')}
							{/if}
						</p>
					{/if}
				{/each}
			{:else}
				<p class="lyrics-text">{lyrics}</p>
			{/if}
		</div>
		{#if showFollow}
			<button
				type="button"
				class="lyrics-follow"
				data-hitbox="text"
				onclick={() => (following = true)}
				><span aria-hidden="true">↓</span> {pageText('nowPlaying.lyricsFollow')}</button
			>
		{/if}
		{#if showUnsyncedNote}
			<p class="lyrics-unsynced">{pageText('nowPlaying.lyricsUnsynced')}</p>
		{/if}
	{:else}
		<p class="lyrics-empty">{emptyLabel}</p>
	{/if}
</div>

<style>
	.np-lyrics {
		position: relative;
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
		font-family: var(--font-body);
		font-size: 1rem;
		line-height: 1.6;
		color: var(--text);
		/* A line rewrapping above the view as it turns bold must not shift the
		   box: an anchoring scroll would read as the reader's. */
		overflow-anchor: none;
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
	.sung-mark {
		padding: 0;
		border: none;
		background: none;
		font: inherit;
		color: inherit;
		text-decoration: underline dotted;
		text-underline-offset: 3px;
		cursor: pointer;
	}
	.sung-line {
		margin: -0.3rem 0 0.5rem;
		font-size: var(--label-font-size);
		color: var(--text-subtle);
	}
	.sung-label {
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	.sung-differs {
		font-weight: 600;
		color: var(--text-muted);
	}
	/* Over the faded strip's right end, where left-aligned lines leave room.
	   Placed without a transform: the app's press feedback scales buttons
	   with one, and a centring translate would jump away from the finger. */
	.lyrics-follow {
		position: absolute;
		right: 0.5rem;
		bottom: 0.25rem;
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.3rem 0.8rem;
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-pill);
		background: var(--surface);
		color: var(--accent);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
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
