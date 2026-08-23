<script lang="ts">
	import type { QueueStreamSkipItem } from '$lib/api/types';
	import type { QueueViewModel } from '$lib/stores/player';
	import {
		LIBRARY_TAKE_POOL_LABELS,
		LIBRARY_TAKE_POOLS,
		type LibraryTakePool
	} from '$lib/stores/playbackSettings';
	import {
		NOW_PLAYING_QUEUE_TAB,
		NOW_PLAYING_UP_NEXT_PREFIX,
		nowPlayingQueueHeading,
		nowPlayingTakeLabel
	} from '$lib/constants/now-playing';
	import { formatTime } from '$lib/utils/format';
	import QueueStreamFeedback from './QueueStreamFeedback.svelte';

	let {
		queue,
		contextLabel,
		currentSongTitle,
		takePool,
		onJump,
		skipped = [],
		skippedComplete = true,
		windowEnded = false,
		showTakeLabel = true
	}: {
		queue: QueueViewModel;
		// The name of what is playing, or null for the library pool, whose own
		// heading needs no collection name.
		contextLabel: string | null;
		currentSongTitle: string;
		// The take-pool picker, given only by the library queue: the pool is
		// what that queue is built from, and no other queue has one. Selection
		// and handler travel together so a queue can never offer a picker that
		// chooses nothing, or hide a pool it is actually built from.
		takePool?: { selected: LibraryTakePool; onChoose: (pool: LibraryTakePool) => void };
		onJump: (index: number) => void;
		skipped?: QueueStreamSkipItem[];
		skippedComplete?: boolean;
		windowEnded?: boolean;
		// Off for a public share queue — there is no real per-row take number to
		// show (see SharedCollection.svelte), and versionNumber is always null.
		showTakeLabel?: boolean;
	} = $props();

	const heading = $derived(nowPlayingQueueHeading(contextLabel));
</script>

<section class="np-queue" aria-label={NOW_PLAYING_QUEUE_TAB}>
	<div class="queue-heading-row">
		<h3 class="queue-heading">{heading}</h3>
		<div class="queue-heading-actions">
			{#if takePool}
				<div class="pool-trio" role="group" aria-label="Take pool">
					{#each LIBRARY_TAKE_POOLS as option (option)}
						<button
							type="button"
							class="pool-pill"
							class:on={takePool.selected === option}
							aria-pressed={takePool.selected === option}
							onclick={() => takePool.onChoose(option)}
						>
							{LIBRARY_TAKE_POOL_LABELS[option]}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>
	<div class="queue-feedback">
		<QueueStreamFeedback {skipped} {skippedComplete} {windowEnded} />
	</div>
	<ol class="queue-list">
		{#if queue.items.length > 0}
			{#each queue.items as item, index (item.key)}
				<li>
					<button
						type="button"
						class="queue-row"
						class:current={index === queue.currentIndex}
						aria-current={index === queue.currentIndex ? 'true' : undefined}
						onclick={() => onJump(index)}
					>
						<span class="queue-position">{index === queue.currentIndex ? '' : index + 1}</span>
						<span class="queue-title">{item.songTitle}</span>
						{#if showTakeLabel}
							<span class="queue-take">
								{nowPlayingTakeLabel(item.versionNumber, item.generationNumber)}
							</span>
						{/if}
						<span class="queue-duration"
							>{item.durationSec != null ? formatTime(item.durationSec) : ''}</span
						>
					</button>
				</li>
			{/each}
		{:else}
			<li class="queue-row current" aria-current="true">
				<span class="queue-title">{currentSongTitle}</span>
			</li>
		{/if}
	</ol>
	{#if queue.upNext}
		<p class="up-next">{NOW_PLAYING_UP_NEXT_PREFIX} {queue.upNext.songTitle}</p>
	{/if}
</section>

<style>
	.np-queue {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}
	.queue-heading-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.queue-heading {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.72rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.queue-heading-actions {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		margin-left: auto;
	}
	.pool-trio {
		display: flex;
		gap: 0.25rem;
	}
	.pool-pill {
		padding: 0.2rem 0.6rem;
		border-radius: var(--btn-radius-pill);
		border: 1px solid var(--border);
		background: transparent;
		color: var(--text-muted);
		font-size: 0.7rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		cursor: pointer;
	}
	.pool-pill:hover {
		border-color: var(--primary);
		color: var(--text);
	}
	.pool-pill.on {
		background: var(--primary);
		border-color: var(--primary);
		color: #fff;
	}
	.queue-feedback {
		align-self: flex-start;
	}
	.queue-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		overflow: hidden;
	}
	.queue-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.7rem;
		border: 0;
		border-bottom: 1px solid var(--border);
		background: var(--surface);
		color: var(--text);
		text-align: left;
		cursor: pointer;
		font-size: 0.85rem;
	}
	li:last-child .queue-row {
		border-bottom: 0;
	}
	.queue-row:hover {
		background: var(--surface-hover);
	}
	.queue-row.current {
		background: color-mix(in srgb, var(--primary) 10%, var(--surface));
		border-left: 3px solid var(--primary);
		cursor: default;
	}
	.queue-position {
		width: 1.2rem;
		flex-shrink: 0;
		text-align: center;
		color: var(--text-subtle);
		font-size: 0.72rem;
	}
	.queue-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.queue-take {
		flex-shrink: 0;
		color: var(--text-subtle);
		font-size: 0.72rem;
	}
	.queue-duration {
		flex-shrink: 0;
		color: var(--text-subtle);
		font-size: 0.72rem;
	}
	.up-next {
		margin: 0;
		font-size: 0.75rem;
		color: var(--text-muted);
	}
</style>
