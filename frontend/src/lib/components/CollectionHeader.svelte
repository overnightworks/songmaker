<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { AlbumCoverUrls, ShareResult } from '$lib/api/types';
	import CollectionHeaderFrame from './CollectionHeaderFrame.svelte';
	import Breadcrumb from './Breadcrumb.svelte';
	import CollectionMenu from './CollectionMenu.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import PlaylistCover from './PlaylistCover.svelte';
	import {
		ALBUM_COVER_ADD_LABEL,
		ALBUM_COVER_EDIT_LABEL,
		RAIL_LIBRARY_LABEL,
		RAIL_PLAYLISTS_LABEL
	} from '$lib/constants';
	import { historyLayerState, openLibraryWall } from '$lib/stores/navigation';
	import { playbackSource, setShuffle, type CollectionStart } from '$lib/stores/player';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';

	interface Props {
		kind: 'album' | 'playlist';
		collectionId: string;
		title: string;
		coverUrl: string | null;
		coverAlt: string;
		initials: string;
		artFill: string | null;
		/**
		 * Starts this collection at `start`, in the order the header has just set;
		 * null while the view has nothing to start.
		 */
		onplay: ((start: CollectionStart) => void) | null;
		onrename: (title: string) => Promise<void>;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		ondelete: () => void;
		onarchive?: () => void;
		oncover?: () => void;
		onremovecover?: () => void;
		onaddtoplaylist?: () => void;
		oncurate?: () => void;
		onsaveoffline?: () => void;
		offlineSaved?: boolean;
		offlineSaving?: boolean;
		offlineProgressLabel?: string | null;
		playlistCovers?: AlbumCoverUrls[];
		playlistCover?: AlbumCoverUrls | null;
		/** Album-only metadata editor (subtitle/year) rendered under the title. */
		metaEditor?: Snippet;
		/**
		 * Album-only: edits the cover in place of the cover itself, and ends
		 * editing through the close it is handed.
		 */
		coverEditor?: Snippet<[close: () => void]>;
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
		metaEditor,
		coverEditor
	}: Props = $props();

	let editableTitle: EditableTitle | undefined = $state();
	let coverFailed = $state(false);
	const editingCover = historyLayerState('cover-editing', false);

	// Cover editing belongs to the collection and the cover it opened on: a new
	// cover -- used, uploaded or removed -- or another collection ends it.
	$effect(() => {
		void collectionId;
		void coverUrl;
		coverFailed = false;
		editingCover.set(false);
	});

	const showCover = $derived(Boolean(coverUrl) && !coverFailed);
	const coverOpening = $derived(
		coverEditor
			? {
					label: showCover ? ALBUM_COVER_EDIT_LABEL : ALBUM_COVER_ADD_LABEL,
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
	const breadcrumbItems = $derived([
		{
			label: kind === 'playlist' ? RAIL_PLAYLISTS_LABEL : RAIL_LIBRARY_LABEL,
			onclick: () => void openLibraryWall()
		},
		{ label: title }
	]);

	function triggerRename(): void {
		editableTitle?.startEdit();
	}

	// The queue names where the music comes from; while that is this very
	// collection, the circle is its pause and resume rather than a fresh start.
	const queueIsThisCollection = $derived(
		audioPlayer.current !== null &&
			$playbackSource?.kind === kind &&
			$playbackSource.id === collectionId
	);
	const sounding = $derived(queueIsThisCollection && audioPlayer.status === 'playing');

	// The header is where a collection's play order is chosen: the circle plays
	// it in order from the top, the shuffle square beside it plays it shuffled
	// from a drawn song. Both set the player's own shuffle setting, so the
	// transport's shuffle control shows the order the header just chose; which
	// collection starts is the view's answer, through onplay. While this
	// collection already plays, the circle pauses and resumes it instead and the
	// order stays as it is — even once the collection has emptied under it. A
	// view with nothing to start passes no onplay, which dims the shuffle square
	// and, unless this collection is the queue, the circle, so no tap there
	// reaches the listener's shuffle setting.
	function onCircle(): void {
		if (sounding) audioPlayer.pause();
		else if (queueIsThisCollection) audioPlayer.play();
		else start('top');
	}

	function start(from: CollectionStart): void {
		if (!onplay) return;
		setShuffle(from === 'random');
		onplay(from);
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
		oncoveredit={coverEditor && showCover ? openCoverEditing : undefined}
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
	playing={sounding}
	onplay={onplay || queueIsThisCollection ? onCircle : null}
	onshuffle={onplay ? () => start('random') : null}
	{titleArea}
	{actions}
	coverFallback={kind === 'playlist' ? coverFallback : undefined}
	{coverOpening}
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

	@media (max-width: 768px) {
		.header-title {
			font-size: 1.2rem;
		}
	}
</style>
