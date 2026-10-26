<script module lang="ts">
	export interface CoverMark {
		running: boolean;
		startedAt: string | null;
		waiting: number;
	}
</script>

<script lang="ts">
	import { albumCoverWaitingText } from '$lib/constants/album-cover-mark';
	import CoverRunElapsed from './CoverRunElapsed.svelte';

	let { running, startedAt, waiting }: CoverMark = $props();
</script>

<!-- The cover button's accessible name says what the mark shows, without the ticking time. -->
{#if running}
	<span class="cover-mark" aria-hidden="true">
		<span class="mark-ring"></span>
		{#if startedAt}<CoverRunElapsed {startedAt} separated={false} />{/if}
	</span>
{:else if waiting > 0}
	<span class="cover-mark" aria-hidden="true">
		<span class="mark-dot"></span>
		{albumCoverWaitingText(waiting)}
	</span>
{/if}

<style>
	.cover-mark {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		height: 17px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 4px;
		background: color-mix(in srgb, black 74%, transparent);
		color: var(--text);
		font-family: var(--font-body);
		font-size: 10px;
		font-variant-numeric: tabular-nums;
		line-height: 1;
		white-space: nowrap;
	}

	.mark-ring {
		width: 9px;
		height: 9px;
		box-sizing: border-box;
		border-radius: 50%;
		border: 2px solid color-mix(in srgb, white 30%, transparent);
		border-top-color: white;
		animation: mark-turn 2.4s linear infinite;
	}

	.mark-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--accent);
	}

	@keyframes mark-turn {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.mark-ring {
			animation: none;
		}
	}
</style>
