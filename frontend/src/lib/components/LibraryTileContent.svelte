<script lang="ts">
	import { titleInitials } from '$lib/utils/format';

	// The cover/fill/initials fallback chain, and the title/subtitle text
	// block, are identical between the full wall grid (LibraryWall.svelte)
	// and the compressed row (LibraryRow.svelte) -- only the outer button,
	// its size, selection marking, and any play affordance stay owned by
	// each caller. Sizing that genuinely differs between the two (initials
	// glyph size, meta padding, title/subtitle type scale) is exposed as CSS
	// custom properties so a caller's own stylesheet can override it on the
	// element it mounts this into, without either caller re-declaring the
	// fallback markup itself.
	interface Props {
		title: string;
		subtitle: string;
		coverAlt: string;
		coverUrl?: string | null;
		fill?: string | null;
	}

	let { title, subtitle, coverAlt, coverUrl = null, fill = null }: Props = $props();
</script>

<span class="tile-cover">
	{#if coverUrl}
		<img src={coverUrl} alt={coverAlt} draggable="false" />
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
