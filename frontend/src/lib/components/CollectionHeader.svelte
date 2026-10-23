<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { AlbumCoverUrls, ShareResult } from '$lib/api/types';
	import CollectionHeaderFrame from './CollectionHeaderFrame.svelte';
	import CollectionMenu from './CollectionMenu.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import PlaylistCover from './PlaylistCover.svelte';
	import { ALBUM_COVER_ADD_LABEL, ALBUM_COVER_EDIT_LABEL } from '$lib/constants';
	import { albumCoverMarkedLabel } from '$lib/constants/album-cover-mark';
	import type { CoverMark } from './CoverActivityMark.svelte';
	import { songCountLabel } from '$lib/utils/format';
	import { historyLayerState } from '$lib/stores/layers';
	import { collectionTransport, toggleOrStartCollection, setShuffle } from '$lib/stores/player';

	interface Props {
		kind: 'album' | 'playlist';
		collectionId: string;
		title: string;
		coverUrl: string | null;
		coverAlt: string;
		initials: string;
		artFill: string | null;
		/** Starts this collection from the top; null while the view has nothing to start. */
		onplay: (() => void) | null;
		/** The songs the page lists, read under the title. */
		songCount: number;
		/** Renames in place through the title; a collection with detailsEditor renames there instead. */
		onrename?: (title: string) => Promise<void>;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		ondelete: () => void;
		onarchive?: () => void;
		/** Playlist-only: an album's cover changes through its coverEditor. */
		oncover?: () => void;
		/** Playlist-only, like oncover. */
		onremovecover?: () => void;
		onaddtoplaylist?: () => void;
		oncurate?: () => void;
		onsaveoffline?: () => void;
		offlineSaved?: boolean;
		offlineSaving?: boolean;
		offlineProgressLabel?: string | null;
		playlistCovers?: AlbumCoverUrls[];
		playlistCover?: AlbumCoverUrls | null;
		/** Album-only: the subtitle and year line read under the title, empty when neither is set. */
		meta?: string;
		/**
		 * Album-only: edits the details -- title, subtitle and year -- in place of
		 * the title, opened from the menu's Edit details and ended through the
		 * close it is handed.
		 */
		detailsEditor?: Snippet<[close: () => void]>;
		/**
		 * Album-only: edits the cover in place of the cover itself, and ends
		 * editing through the close it is handed.
		 */
		coverEditor?: Snippet<[close: () => void]>;
		/** Album-only: what the closed cover carries, a running suggestion or waiting ones. */
		coverMark?: CoverMark;
	}

	let {
		kind,
		collectionId,
		title,
		coverUrl,
		coverAlt,
		initials,
		artFill,
		onplay,
		songCount,
		onrename,
		isShared,
		shareSlug,
		onshare,
		onunshare,
		ondelete,
		onarchive,
		oncover,
		onremovecover,
		onaddtoplaylist,
		oncurate,
		onsaveoffline,
		offlineSaved = false,
		offlineSaving = false,
		offlineProgressLabel = null,
		playlistCovers,
		playlistCover,
		meta = '',
		detailsEditor,
		coverEditor,
		coverMark
	}: Props = $props();

	let editableTitle: EditableTitle | undefined = $state();
	let coverFailed = $state(false);
	const editingCover = historyLayerState('cover-editing', false);
	const editingDetails = historyLayerState('details-editing', false);

	// Cover editing belongs to the collection and the cover it opened on: a new
	// cover -- used, uploaded or removed -- or another collection ends it.
	$effect(() => {
		void collectionId;
		void coverUrl;
		coverFailed = false;
		editingCover.set(false);
	});

	$effect(() => {
		void collectionId;
		editingDetails.set(false);
	});

	const showCover = $derived(Boolean(coverUrl) && !coverFailed);
	const coverLabel = $derived(showCover ? ALBUM_COVER_EDIT_LABEL : ALBUM_COVER_ADD_LABEL);
	const coverOpening = $derived(
		coverEditor
			? {
					label: coverLabel,
					name: albumCoverMarkedLabel(coverLabel, coverMark),
					onopen: openCoverEditing
				}
			: undefined
	);

	function openCoverEditing(): void {
		editingCover.set(true);
	}

	function closeCoverEditing(): void {
		editingCover.set(false);
	}

	function triggerRename(): void {
		editableTitle?.startEdit();
	}

	function openDetailsEditing(): void {
		editingDetails.set(true);
	}

	function closeDetailsEditing(): void {
		editingDetails.set(false);
	}

	const collectionState = $derived($collectionTransport(kind, collectionId));

	// The circle plays the collection in order from the top, so it turns the
	// player's shuffle off, and the player's shuffle control shows that order;
	// shuffling is the player's (#1354 rule 24). Which collection starts is the
	// view's answer, through onplay. While this collection already plays, the
	// circle pauses and resumes it instead and the order stays as it is — even
	// once the collection has emptied under it. A view with nothing to start
	// passes no onplay, which dims the circle unless this collection is the
	// queue, so no tap there reaches the listener's shuffle setting.
	function onCircle(): void {
		toggleOrStartCollection(kind, collectionId, onplay ? startFromTheTop : null);
	}

	function startFromTheTop(): void {
		if (!onplay) return;
		setShuffle(false);
		onplay();
	}
</script>

{#snippet titleArea()}
	{#if detailsEditor && $editingDetails}
		{@render detailsEditor(closeDetailsEditing)}
	{:else}
		<h2 class="header-title" aria-label={title}>
			{#if onrename}
				<EditableTitle
					bind:this={editableTitle}
					value={title}
					onsave={onrename}
					ariaLabel={`${kind} title`}
				/>
			{:else}
				{title}
			{/if}
		</h2>
		{#if meta}<p class="header-meta">{meta}</p>{/if}
	{/if}
	<p class="header-count">{songCountLabel(songCount)}</p>
{/snippet}

{#snippet actions()}
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
		oncoveredit={coverEditor ? openCoverEditing : undefined}
		hasCover={showCover}
		{onremovecover}
		{onaddtoplaylist}
		{oncurate}
		{onsaveoffline}
		{offlineSaved}
		{offlineSaving}
		{offlineProgressLabel}
		oneditdetails={detailsEditor ? openDetailsEditing : undefined}
		onrename={onrename ? triggerRename : undefined}
	/>
{/snippet}

{#snippet coverEditing()}
	{@render coverEditor?.(closeCoverEditing)}
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
	{kind}
	transport={collectionState.transport}
	onplay={onplay || collectionState.current || collectionState.waiting ? onCircle : null}
	{titleArea}
	{actions}
	coverFallback={kind === 'playlist' ? coverFallback : undefined}
	{coverOpening}
	{coverMark}
	coverEditing={$editingCover ? coverEditing : undefined}
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

	.header-meta,
	.header-count {
		margin: 0.15rem 0 0;
		font-size: 0.8rem;
		color: var(--text-muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	@media (max-width: 768px) {
		.header-title {
			font-size: 1.2rem;
		}
	}
</style>
