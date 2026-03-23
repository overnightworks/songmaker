<script lang="ts">
	import type { LyricsLine, SrtLine } from '$lib/api/types';
	import { formatTime } from '$lib/utils/format';

	interface Props {
		lines: (SrtLine | LyricsLine)[];
		currentTime?: number;
		onseek?: (time: number) => void;
	}

	let { lines, currentTime = 0, onseek }: Props = $props();

	const hasTimestamps = $derived(lines.some((l) => l.time >= 0));

	const activeIndex = $derived.by(() => {
		if (!hasTimestamps) return -1;
		for (let i = lines.length - 1; i >= 0; i--) {
			const line = lines[i];
			if (!isSection(line) && line.time >= 0 && currentTime >= line.time) {
				return i;
			}
		}
		return -1;
	});

	function isSection(line: SrtLine | LyricsLine): boolean {
		return 'section' in line && line.section;
	}

	function getConfidence(line: SrtLine | LyricsLine): number | undefined {
		return 'confidence' in line ? line.confidence : undefined;
	}

	function handleClick(line: SrtLine | LyricsLine): void {
		if (hasTimestamps && line.time >= 0 && onseek) {
			onseek(line.time);
		}
	}

	let container: HTMLDivElement | undefined = $state();

	$effect(() => {
		if (activeIndex >= 0 && container) {
			const activeLine = container.querySelector(`[data-idx="${activeIndex}"]`);
			if (activeLine instanceof HTMLElement) {
				const lineTop = activeLine.offsetTop - container.offsetTop;
				const scrollTarget = lineTop - container.clientHeight / 3;
				container.scrollTop = scrollTarget;
			}
		}
	});
</script>

<div class="lyrics" class:static={!hasTimestamps} bind:this={container}>
	{#if lines.length === 0}
		<p class="no-lyrics">No lyrics available</p>
	{:else}
		{#each lines as line, i (i)}
			{#if isSection(line)}
				<div class="lyric-line section-tag">{line.text}</div>
			{:else}
				{@const conf = getConfidence(line)}
				<button
					class="lyric-line"
					class:active={i === activeIndex}
					class:past={i < activeIndex}
					data-idx={i}
					onclick={() => handleClick(line)}
					style:opacity={conf !== undefined && conf < 0.5 ? Math.max(0.25, conf / 0.5) : undefined}
				>
					{#if hasTimestamps && line.time >= 0}
						<span class="timestamp">{formatTime(line.time)}</span>
					{/if}
					{#if conf !== undefined}
						{@const pct = Math.round(conf * 100)}
						<span
							class="conf-badge"
							class:conf-high={conf >= 0.7}
							class:conf-mid={conf >= 0.4 && conf < 0.7}
							class:conf-low={conf < 0.4}
						>
							{pct}
						</span>
					{/if}
					{line.text}
				</button>
			{/if}
		{/each}
	{/if}
</div>

<style>
	.lyrics {
		padding: 8px 0;
		flex: 1;
		overflow-y: auto;
		scroll-behavior: smooth;
		min-height: 120px;
	}

	.lyric-line {
		display: block;
		width: 100%;
		padding: 6px 16px;
		margin: 3px 0;
		font-size: 17px;
		line-height: 1.5;
		color: var(--text-dim);
		transition: all 0.3s ease;
		border: none;
		border-left: 3px solid transparent;
		background: transparent;
		text-align: left;
		font-family: inherit;
	}

	.lyrics:not(.static) .lyric-line {
		cursor: pointer;
	}

	.lyrics:not(.static) .lyric-line:hover {
		color: #999;
	}

	.lyrics.static .lyric-line {
		color: #ccc;
		cursor: default;
	}

	.lyrics.static .lyric-line:hover {
		color: #fff;
	}

	.lyric-line.active {
		color: #fff;
		font-size: 19px;
		border-left-color: var(--primary);
		background: rgba(255, 255, 255, 0.03);
	}

	.lyric-line.past {
		color: #666;
	}

	.section-tag {
		color: var(--primary);
		font-family: var(--font-display);
		font-size: 13px;
		letter-spacing: 2px;
		opacity: 0.6;
		cursor: default;
		padding: 10px 16px 2px;
	}

	.timestamp {
		font-family: var(--font-display);
		font-size: 11px;
		color: var(--primary);
		margin-right: 8px;
		opacity: 0.5;
	}

	.conf-badge {
		font-size: 9px;
		font-family: var(--font-display);
		padding: 1px 4px;
		border-radius: 3px;
		margin-right: 6px;
		vertical-align: middle;
	}

	.conf-high {
		color: #4a4;
	}

	.conf-mid {
		color: #a84;
	}

	.conf-low {
		color: #a44;
		background: rgba(170, 68, 68, 0.15);
	}

	.no-lyrics {
		text-align: center;
		color: var(--text-dim);
		font-style: italic;
		padding: 40px 20px;
	}
</style>
