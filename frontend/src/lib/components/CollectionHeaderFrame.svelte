<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';

	interface Props {
		coverUrl: string | null;
		showCover: boolean;
		onCoverError: () => void;
		coverAlt: string;
		initials: string;
		artFill: string | null;
		onplay: () => void;
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
		onplay,
		titleArea,
		actions,
		coverFallback
	}: Props = $props();
</script>

<div class="collection-header">
	<span class="header-cover">
		{#if showCover && coverUrl}
			<img src={coverUrl} alt={coverAlt} onerror={onCoverError} />
		{:else if coverFallback}
			{@render coverFallback()}
		{:else if artFill}
			<span class="header-cover-fallback" style:background={artFill} aria-hidden="true"></span>
		{:else}
			<span class="header-cover-fallback header-cover-initials" aria-hidden="true">{initials}</span>
		{/if}
	</span>
	<div class="header-titles">
		{@render titleArea()}
	</div>
	<div class="header-actions">
		<button class="play-btn" data-hitbox="text" onclick={onplay} aria-label="Play">
			<Icon name="play" size={16} />
			<span>Play</span>
		</button>
		{#if actions}{@render actions()}{/if}
	</div>
</div>

<style>
	.collection-header {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		padding: 1.2rem 1.5rem 0.8rem;
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

	/* The title keeps a readable width instead of collapsing to a letter: the
	   header wraps its action cluster onto a second row rather than shrinking
	   the title past this floor. `overflow: hidden` on the title itself still
	   ellipsises whatever does not fit. */
	.header-titles {
		min-width: 10rem;
		flex: 1;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-shrink: 0;
	}

	.play-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.5rem 1.1rem;
		border-radius: var(--btn-radius-pill);
		border: none;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		font-family: var(--font-display);
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.play-btn:hover {
		box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 40%, transparent);
	}

	@media (max-width: 768px) {
		.collection-header {
			padding: 0.8rem 0.8rem 0.6rem;
		}
	}
</style>
