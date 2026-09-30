<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		collectionPauseLabel,
		collectionPlayLabel,
		collectionShuffleLabel,
		type CollectionPlayKind
	} from '$lib/constants';
	import Icon from './Icon.svelte';

	interface Props {
		coverUrl: string | null;
		showCover: boolean;
		onCoverError: () => void;
		coverAlt: string;
		initials: string;
		artFill: string | null;
		kind: CollectionPlayKind;
		/** Whether this collection is sounding, so the circle offers to pause it. */
		playing: boolean;
		/** The circle's action; null while the circle has nothing to act on, which dims it. */
		onplay: (() => void) | null;
		/**
		 * The shuffle square's action; absent where the surface offers no
		 * shuffle, null while the collection has nothing to start, which dims it.
		 */
		onshuffle?: (() => void) | null;
		titleArea: Snippet;
		actions?: Snippet;
		coverFallback?: Snippet;
	}

	let {
		coverUrl,
		showCover,
		onCoverError,
		coverAlt,
		initials,
		artFill,
		kind,
		playing,
		onplay,
		onshuffle,
		titleArea,
		actions,
		coverFallback
	}: Props = $props();

	const playLabel = $derived(playing ? collectionPauseLabel(kind) : collectionPlayLabel(kind));
</script>

<div class="collection-header">
	<div class="header-identity">
		<span class="header-cover">
			{#if showCover && coverUrl}
				<img src={coverUrl} alt={coverAlt} onerror={onCoverError} />
			{:else if coverFallback}
				{@render coverFallback()}
			{:else if artFill}
				<span class="header-cover-fallback" style:background={artFill} aria-hidden="true"></span>
			{:else}
				<span class="header-cover-fallback header-cover-initials" aria-hidden="true"
					>{initials}</span
				>
			{/if}
		</span>
		<div class="header-titles">
			{@render titleArea()}
		</div>
	</div>
	<div class="header-actions">
		<button
			type="button"
			class="play-circle"
			data-hitbox="frequent"
			disabled={!onplay}
			onclick={() => onplay?.()}
			aria-label={playLabel}
			title={playLabel}
		>
			<Icon name={playing ? 'pause' : 'play'} size={22} />
		</button>
		{#if onshuffle !== undefined}
			<button
				type="button"
				class="shuffle-btn"
				data-hitbox="frequent"
				disabled={!onshuffle}
				onclick={() => onshuffle?.()}
				aria-label={collectionShuffleLabel(kind)}
				title={collectionShuffleLabel(kind)}
			>
				<Icon name="shuffle" size={20} />
			</button>
		{/if}
		{#if actions}<span class="header-actions-end">{@render actions()}</span>{/if}
	</div>
</div>

<style>
	.collection-header {
		--collection-play-circle: 48px;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		padding: 1.2rem 1.5rem 0.8rem;
	}

	.header-identity {
		display: flex;
		align-items: center;
		gap: 1rem;
		min-width: 0;
	}

	.header-cover {
		display: block;
		width: 56px;
		height: 56px;
		flex-shrink: 0;
		overflow: hidden;
		background: var(--surface-hover);
	}

	.header-cover img,
	.header-cover-fallback {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.header-cover-initials {
		font-family: var(--font-display);
		font-size: 1.1rem;
		letter-spacing: 0.06em;
		color: var(--text);
		user-select: none;
	}

	.header-titles {
		min-width: 0;
		flex: 1;
	}

	.header-actions,
	.header-actions-end {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}

	.header-actions-end {
		margin-left: auto;
	}

	.play-circle {
		width: var(--collection-play-circle);
		height: var(--collection-play-circle);
		border-radius: 50%;
		border: none;
		background: var(--primary);
		color: #fff;
		margin-right: 0.2rem;
	}

	.play-circle:hover:not(:disabled) {
		box-shadow: 0 0 14px color-mix(in srgb, var(--primary) 45%, transparent);
	}

	.shuffle-btn {
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		border: none;
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
	}

	.shuffle-btn:hover:not(:disabled) {
		color: var(--primary);
	}

	.play-circle:disabled,
	.shuffle-btn:disabled {
		opacity: 0.4;
	}

	@media (max-width: 768px) {
		.collection-header {
			padding: 0.8rem 0.8rem 0.6rem;
		}
	}
</style>
