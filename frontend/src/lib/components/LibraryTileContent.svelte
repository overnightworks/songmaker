<script lang="ts">
	import type { AlbumCoverUrls } from '#lib/api/types.ts';
	import { titleInitials } from '#lib/utils/format.ts';
	import PlayingMark from './PlayingMark.svelte';
	import PlaylistCover from './PlaylistCover.svelte';

	interface Props {
		presentation?: 'cover' | 'row';
		current?: boolean;
		title: string;
		initialsSource?: string;
		subtitle: string;
		coverAlt: string;
		coverUrl?: string | null;
		fill?: string | null;
		playlistCovers?: AlbumCoverUrls[] | null;
	}

	let {
		presentation = 'cover',
		current = false,
		title,
		initialsSource,
		subtitle,
		coverAlt,
		coverUrl = null,
		fill = null,
		playlistCovers = null
	}: Props = $props();
</script>

<span class="tile-cover" class:row={presentation === 'row'}>
	{#if coverUrl}
		<img src={coverUrl} alt={coverAlt} draggable="false" loading="lazy" decoding="async" />
	{:else if playlistCovers}
		<PlaylistCover {title} covers={playlistCovers} size="100%" />
	{:else if fill}
		<span class="tile-cover-fill" style:background={fill} aria-hidden="true"></span>
	{:else}
		<span class="tile-cover-fill tile-cover-initials" aria-hidden="true"
			>{titleInitials(initialsSource ?? title)}</span
		>
	{/if}
</span>
<span class="tile-meta" class:row={presentation === 'row'} class:current>
	<span class="tile-title">{title}</span>
	<span class="tile-subtitle"
		>{#if presentation === 'row'}<PlayingMark {current} />{/if}{subtitle}</span
	>
</span>

<style>
	.tile-cover {
		display: block;
		width: 100%;
		aspect-ratio: 1;
		background: var(--surface-hover);
		overflow: hidden;
	}

	.tile-cover img,
	.tile-cover-fill {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.tile-cover :global(.playlist-cover) {
		width: 100%;
		height: 100%;
		border-radius: 0;
	}

	.tile-cover-initials {
		font-family: var(--font-display);
		font-size: var(--tile-initials-size, 1.4rem);
		letter-spacing: 0.06em;
		color: var(--text);
		user-select: none;
	}

	.tile-meta {
		display: flex;
		flex-direction: column;
		min-width: 0;
		gap: 1px;
		padding: var(--tile-meta-padding, 8px 40px 8px 8px);
	}

	.tile-title {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--font-display);
		font-size: var(--tile-title-size, 0.85rem);
		letter-spacing: 0.3px;
		color: var(--text);
	}

	.tile-subtitle {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--tile-subtitle-size, 0.68rem);
		color: var(--text-subtle);
	}

	.tile-cover.row {
		width: 42px;
		height: 42px;
		flex: none;
		border-radius: 3px;
		--tile-initials-size: 0.85rem;
		--playlist-initials-min: 14px;
	}
	.tile-meta.row {
		flex: 1;
		padding: 0;
		gap: 2px;
		--tile-title-size: 0.95rem;
		--tile-subtitle-size: 0.78rem;
	}
	.row .tile-title {
		font-family: var(--font-body);
		font-weight: 600;
		letter-spacing: normal;
	}
	.row.current .tile-title {
		color: var(--accent);
	}
	.row .tile-subtitle {
		display: flex;
		align-items: center;
		gap: 5px;
	}
</style>
