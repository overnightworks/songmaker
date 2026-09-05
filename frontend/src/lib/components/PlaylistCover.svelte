<script lang="ts">
	import type { AlbumCoverUrls } from '$lib/api/types';
	import { titleInitials } from '$lib/utils/format';

	interface Props {
		title: string;
		covers: AlbumCoverUrls[];
		size?: string;
		visible?: boolean;
	}

	let { title, covers, size = '18px', visible = true }: Props = $props();

	const initials = $derived(titleInitials(title));
	const cells = $derived(Array.from({ length: 4 }, (_, index) => covers[index] ?? null));
	let failedCoverUrls = $state(new Set<string>());

	function hideFailedCover(url: string): void {
		failedCoverUrls = new Set([...failedCoverUrls, url]);
	}
</script>

<span class="playlist-cover" style:--playlist-cover-size={size} aria-hidden="true">
	{#each cells as cover, index (index)}
		<span class="playlist-cover-cell">
			{#if visible && cover && !failedCoverUrls.has(cover.card)}
				<img
					src={cover.card}
					alt=""
					draggable="false"
					loading="lazy"
					decoding="async"
					onerror={() => hideFailedCover(cover.card)}
				/>
			{:else}
				<span class="playlist-cover-initials">{initials}</span>
			{/if}
		</span>
	{/each}
</span>

<style>
	.playlist-cover {
		display: grid;
		width: var(--playlist-cover-size);
		aspect-ratio: 1;
		flex: 0 0 var(--playlist-cover-size);
		grid-template-columns: repeat(2, minmax(0, 1fr));
		grid-template-rows: repeat(2, minmax(0, 1fr));
		gap: var(--playlist-cover-gap, 1px);
		padding: var(--playlist-cover-padding, 0);
		overflow: hidden;
		border-radius: 3px;
		background: var(--surface);
	}

	.playlist-cover-cell {
		display: grid;
		min-width: 0;
		min-height: 0;
		place-items: center;
		overflow: hidden;
		background: var(--surface-hover);
	}

	.playlist-cover-cell img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.playlist-cover-initials {
		color: var(--text-subtle);
		font-family: var(--font-display);
		font-size: calc(var(--playlist-cover-size) * 0.32);
		font-weight: 600;
		line-height: 1;
	}
</style>
