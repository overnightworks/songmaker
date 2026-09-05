<script lang="ts">
	import type { AlbumCoverUrls } from '$lib/api/types';
	import { titleInitials } from '$lib/utils/format';
	import PlaylistCover from './PlaylistCover.svelte';

	interface Props {
		title: string;
		subtitle: string;
		coverAlt: string;
		coverUrl?: string | null;
		fill?: string | null;
		playlistCovers?: AlbumCoverUrls[] | null;
	}

	let { title, subtitle, coverAlt, coverUrl = null, fill = null, playlistCovers = null }: Props =
		$props();
</script>

<span class="tile-cover">
	{#if coverUrl}
		<img src={coverUrl} alt={coverAlt} draggable="false" loading="lazy" decoding="async" />
	{:else if playlistCovers}
		<PlaylistCover title={title} covers={playlistCovers} size="100%" />
	{:else if fill}
		<span class="tile-cover-fill" style:background={fill} aria-hidden="true"></span>
	{:else}
		<span class="tile-cover-fill tile-cover-initials" aria-hidden="true"
			>{titleInitials(title)}</span
		>
	{/if}
</span>
<span class="tile-meta">
	<span class="tile-title">{title}</span>
	<span class="tile-subtitle">{subtitle}</span>
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
</style>
