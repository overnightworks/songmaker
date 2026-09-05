<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { AlbumCoverUrls, ShareResult } from '$lib/api/types';
	import CollectionHeaderFrame from './CollectionHeaderFrame.svelte';
	import Breadcrumb from './Breadcrumb.svelte';
	import CollectionMenu from './CollectionMenu.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import PlaylistCover from './PlaylistCover.svelte';
	import { ALBUM_ADD_SONG_GLYPH, ALBUM_ADD_SONG_LABEL, RAIL_LIBRARY_LABEL } from '$lib/constants';
	import { openLibraryWall } from '$lib/stores/navigation';

	interface Props {
		kind: 'album' | 'playlist';
		title: string;
		coverUrl: string | null;
		coverAlt: string;
		initials: string;
		artFill: string | null;
		onplay: () => void;
		onrename: (title: string) => Promise<void>;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		ondelete: () => void;
		onarchive?: () => void;
		oncover?: () => void;
		oncoversuggest?: () => void;
		onremovecover?: () => void;
		onaddtoplaylist?: () => void;
		onaddsong?: () => void;
		oncurate?: () => void;
		onsaveoffline?: () => void;
		offlineSaved?: boolean;
		offlineSaving?: boolean;
		offlineProgressLabel?: string | null;
		playlistCovers?: AlbumCoverUrls[];
		playlistCover?: AlbumCoverUrls | null;
		/** Album-only metadata editor (subtitle/year) rendered under the title. */
		metaEditor?: Snippet;
	}

	let {
		kind,
		title,
		coverUrl,
		coverAlt,
		initials,
		artFill,
		onplay,
		onrename,
		isShared,
		shareSlug,
		onshare,
		onunshare,
		ondelete,
		onarchive,
		oncover,
		oncoversuggest,
		onremovecover,
		onaddtoplaylist,
		onaddsong,
		oncurate,
		onsaveoffline,
		offlineSaved = false,
		offlineSaving = false,
		offlineProgressLabel = null,
		playlistCovers,
		playlistCover,
		metaEditor
	}: Props = $props();

	let editableTitle: EditableTitle | undefined = $state();
	let coverFailed = $state(false);

	$effect(() => {
		void coverUrl;
		coverFailed = false;
	});

	const showCover = $derived(Boolean(coverUrl) && !coverFailed);
	const breadcrumbItems = $derived([
		{ label: RAIL_LIBRARY_LABEL, onclick: () => void openLibraryWall() },
		{ label: title }
	]);

	function triggerRename(): void {
		editableTitle?.startEdit();
	}
</script>

{#snippet titleArea()}
	<h2 class="header-title" aria-label={title}>
		<EditableTitle
			bind:this={editableTitle}
			value={title}
			onsave={onrename}
			ariaLabel={`${kind} title`}
		/>
	</h2>
	{#if metaEditor}{@render metaEditor()}{/if}
	<Breadcrumb items={breadcrumbItems} />
{/snippet}

{#snippet actions()}
	{#if onaddsong}
		<button
			type="button"
			class="add-song-btn"
			data-hitbox="frequent"
			onclick={onaddsong}
			aria-label={ALBUM_ADD_SONG_LABEL}
			title={ALBUM_ADD_SONG_LABEL}
		>
			<span class="add-song-full">{ALBUM_ADD_SONG_LABEL}</span>
			<span class="add-song-glyph" aria-hidden="true">{ALBUM_ADD_SONG_GLYPH}</span>
		</button>
	{/if}
	<CollectionMenu
		{kind}
		{title}
		{isShared}
		{shareSlug}
		{onshare}
		{onunshare}
		{ondelete}
		{onarchive}
		{oncover}
		{oncoversuggest}
		hasCover={showCover}
		{onremovecover}
		{onaddtoplaylist}
		{oncurate}
		{onsaveoffline}
		{offlineSaved}
		{offlineSaving}
		{offlineProgressLabel}
		onrename={triggerRename}
	/>
{/snippet}

{#snippet coverFallback()}
	{#if kind === 'playlist' && playlistCovers}
		<PlaylistCover {title} covers={playlistCovers} cover={playlistCover} size="56px" />
	{/if}
{/snippet}

<CollectionHeaderFrame
	{coverUrl}
	{showCover}
	onCoverError={() => (coverFailed = true)}
	{coverAlt}
	{initials}
	{artFill}
	{onplay}
	{titleArea}
	{actions}
	coverFallback={kind === 'playlist' ? coverFallback : undefined}
/>

<style>
	.header-title {
		font-family: var(--font-display);
		font-size: 1.55rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1.5px;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.add-song-btn {
		padding: 0 0.7rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		white-space: nowrap;
	}

	.add-song-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.add-song-glyph {
		display: none;
	}

	@media (max-width: 768px) {
		.header-title {
			font-size: 1.2rem;
		}

		.add-song-btn {
			padding: 0;
		}

		.add-song-full {
			display: none;
		}

		.add-song-glyph {
			display: inline;
			font-size: 1.1rem;
			line-height: 1;
		}
	}
</style>
