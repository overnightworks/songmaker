<script lang="ts">
	import type { CoverSuggestionDiscard } from '#lib/api/albums.ts';
	import {
		archiveAlbum,
		deleteAlbum,
		deleteAlbumCover,
		restoreAlbum,
		shareAlbum,
		unarchiveAlbum,
		unshareAlbum,
		updateAlbum,
		uploadAlbumCover
	} from '#lib/api/client.ts';
	import { describeFailure } from '#lib/api/fetch.ts';
	import { fetchSongs } from '#lib/api/songs.ts';
	import {
		albumList,
		albumSongsLoad,
		albumSongsLoadFailure,
		songList,
		loadSongsForAlbum,
		addAlbumToList,
		addSongsToList,
		removeAlbumFromList,
		removeSongsForAlbum,
		updateAlbumInList
	} from '#lib/stores/libraryData.ts';
	import {
		curateAlbum,
		isSongCurrent,
		playAlbum,
		playAlbumSong,
		selectedAlbumId
	} from '#lib/stores/player.ts';
	import { selectSong } from '#lib/stores/navigation.ts';
	import { historyLayerState, holdOpenWhile } from '#lib/stores/layers.ts';
	import { setOpenCollection } from '#lib/stores/collection.ts';
	import { forgetListenedPlace, readRestoredPlace } from '#lib/stores/libraryOrder.ts';
	import { addToast, addUndoToast } from '#lib/stores/toast.ts';
	import { addAlbumToPlaylist } from '#lib/stores/playlists.ts';
	import {
		coverStanding,
		discardCoverSuggestions,
		knownAfterSave,
		knownCoverSuggestions,
		watchCoverActivity
	} from '#lib/stores/coverActivity.ts';
	import {
		PLACE_LINE_SEPARATOR,
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_COVER_ACCEPT,
		ALBUM_YEAR_MAX,
		ALBUM_YEAR_MIN
	} from '#lib/constants/album.ts';
	import { titleInitials } from '#lib/utils/format.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import { albumHasPlayableTake, albumSongsSettled, songPlayability } from '#lib/utils/playable.ts';
	import type { SongItem } from '#lib/api/types.ts';
	import { usableAlbumPrimary } from '#lib/utils/contrast.ts';
	import AlbumCoverEditor from './AlbumCoverEditor.svelte';
	import AlbumMetaEditor, { type AlbumDetails } from './AlbumMetaEditor.svelte';
	import CollectionHeader from './CollectionHeader.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import SongRow from './SongRow.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import Icon from './Icon.svelte';
	import NewSongCard from './NewSongCard.svelte';

	interface Props {
		albumId?: string;
	}

	let { albumId }: Props = $props();

	let playlistPickerOpen = $state(false);
	let showDeleteConfirm = $state(false);

	const albums = $derived($albumList);
	const allSongs = $derived($songList);
	const currentAlbumId = $derived(albumId ?? $selectedAlbumId);

	const selectedAlbum = $derived(
		currentAlbumId ? (albums.find((a) => a.id === currentAlbumId) ?? null) : null
	);
	const albumSongs = $derived(
		currentAlbumId
			? allSongs
					.filter((s) => s.album_id === currentAlbumId)
					.sort((a, b) => a.track_number - b.track_number)
			: []
	);
	const albumLoad = $derived(currentAlbumId ? $albumSongsLoad[currentAlbumId] : undefined);
	// An album with nothing to hear gives the header nothing to start, so
	// neither of its controls can reach the running queue.
	const albumHasTakes = $derived(
		selectedAlbum !== null &&
			albumHasPlayableTake(selectedAlbum, albumSongs, {
				songsComplete: albumSongsSettled(albumLoad)
			})
	);
	const albumLoadFailure = $derived(currentAlbumId ? albumSongsLoadFailure(currentAlbumId) : null);
	const coverUrl = $derived(selectedAlbum?.cover?.detail ?? null);
	const coverAlt = $derived(
		selectedAlbum
			? pageText('albumPage.coverAlt', { title: selectedAlbum.title })
			: pageText('albumPage.coverAltFallback')
	);
	const artFill = $derived(selectedAlbum ? usableAlbumPrimary(selectedAlbum.colors) : null);
	const initials = $derived(
		selectedAlbum ? titleInitials(selectedAlbum.title) : ALBUM_ART_EMPTY_INITIALS
	);
	const albumMeta = $derived(
		[selectedAlbum?.subtitle, selectedAlbum?.year].filter(Boolean).join(PLACE_LINE_SEPARATOR)
	);
	// Holds the album the card adds to, so a card opened on one album never
	// shows on the next one this view is reused for.
	const newSongIn = historyLayerState<string | null>('album-new-song', null);
	const newSongOpen = $derived(currentAlbumId !== undefined && $newSongIn === currentAlbumId);
	let newSongRow: HTMLButtonElement | undefined = $state();
	let newSongShown = false;
	let focusRowOnFold = true;

	$effect(() => {
		if (newSongShown && !newSongOpen && focusRowOnFold) newSongRow?.focus();
		focusRowOnFold = true;
		newSongShown = newSongOpen;
	});

	function startNewSong(): void {
		$newSongIn = currentAlbumId ?? null;
	}

	function cancelNewSong(): void {
		$newSongIn = null;
	}

	function foldCreatedSong(): void {
		focusRowOnFold = false;
		$newSongIn = null;
	}

	// The album page keeps the cover state read, for the closed cover's mark and
	// for the editor, whether or not the editor is open.
	$effect(() => {
		if (currentAlbumId) return watchCoverActivity(currentAlbumId);
	});
	const coverMark = $derived(
		$coverStanding?.albumId === currentAlbumId ? $coverStanding : undefined
	);

	let coverBusy = $state(false);
	let coverInput: HTMLInputElement | null = $state(null);
	// What the cover state knew when Upload was pressed; a successful upload
	// releases that, and the run known by then.
	const NOTHING_KNOWN: CoverSuggestionDiscard = { suggestionIds: [], jobIds: [] };
	let releasedByUpload = NOTHING_KNOWN;

	async function onCoverFile(event: Event): Promise<void> {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !selectedAlbum) return;
		const uploadedAlbumId = selectedAlbum.id;
		const known = releasedByUpload;
		releasedByUpload = NOTHING_KNOWN;
		coverBusy = true;
		try {
			const updated = await holdOpenWhile('cover-saving', uploadAlbumCover(uploadedAlbumId, file));
			updateAlbumInList(uploadedAlbumId, () => updated);
			addToast(pageText('albumCover.saved'), 'success');
			await discardSuggestionsAfterUpload(uploadedAlbumId, knownAfterSave(uploadedAlbumId, known));
		} catch (e) {
			addToast(describeFailure(e, pageText('albumPage.coverUploadFailed')), 'error');
		} finally {
			coverBusy = false;
		}
	}

	// An uploaded cover ends the suggestions the editor knew: its run is stopped
	// before they go. A failure is told here; the state is read again either way.
	async function discardSuggestionsAfterUpload(
		albumId: string,
		known: CoverSuggestionDiscard
	): Promise<void> {
		try {
			await discardCoverSuggestions(albumId, known);
		} catch (error) {
			addToast(describeFailure(error, pageText('albumPage.coverDiscardFailed')), 'error');
		}
	}

	function onCoverAction(): void {
		releasedByUpload = selectedAlbum ? knownCoverSuggestions(selectedAlbum.id) : NOTHING_KNOWN;
		coverInput?.click();
	}

	async function onCoverRemove(): Promise<void> {
		if (!selectedAlbum) return;
		coverBusy = true;
		try {
			const updated = await holdOpenWhile('cover-saving', deleteAlbumCover(selectedAlbum.id));
			updateAlbumInList(selectedAlbum.id, () => updated);
			addToast(pageText('albumPage.coverRemoved'), 'success');
		} catch (e) {
			addToast(describeFailure(e, pageText('albumPage.coverRemoveFailed')), 'error');
		} finally {
			coverBusy = false;
		}
	}

	async function onSaveAlbumDetails(details: AlbumDetails): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		const year = details.year ? Number(details.year) : null;
		if (details.year && !Number.isInteger(year)) {
			addToast(pageText('albumPage.yearWhole'), 'error');
			throw new Error('Year must be a whole number');
		}
		if (year !== null && (year < ALBUM_YEAR_MIN || year > ALBUM_YEAR_MAX)) {
			addToast(
				pageText('albumPage.yearRange', {
					min: String(ALBUM_YEAR_MIN),
					max: String(ALBUM_YEAR_MAX)
				}),
				'error'
			);
			throw new Error('Year out of range');
		}
		try {
			const updated = await updateAlbum(albumId, {
				title: details.title,
				subtitle: details.subtitle,
				year
			});
			updateAlbumInList(albumId, () => updated);
			addToast(pageText('albumDetails.saved'), 'success');
		} catch (e) {
			addToast(describeFailure(e, pageText('albumDetails.saveFailed')), 'error');
			throw e;
		}
	}

	async function onAlbumShareEnable() {
		if (!selectedAlbum) throw new Error('No album');
		const albumId = selectedAlbum.id;
		const result = await shareAlbum(albumId);
		updateAlbumInList(albumId, (a) => ({ ...a, is_shared: true, share_slug: result.share_slug }));
		return result;
	}

	async function onAlbumShareDisable() {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		await unshareAlbum(albumId);
		updateAlbumInList(albumId, (a) => ({ ...a, is_shared: false, share_slug: null }));
	}

	async function onAlbumDelete(): Promise<void> {
		if (!selectedAlbum) return;
		const album = selectedAlbum;
		const albumId = album.id;
		try {
			await deleteAlbum(albumId);
			removeAlbumFromList(albumId);
			forgetListenedPlace('album', albumId);
			removeSongsForAlbum(albumId);
			setOpenCollection(null);
			addUndoToast(pageText('albumPage.deleted'), {
				label: pageText('albumPage.undo'),
				handler: async () => {
					try {
						const restored = await restoreAlbum(albumId);
						addAlbumToList(restored);
						void readRestoredPlace('album', albumId);
						const resp = await fetchSongs(albumId);
						addSongsToList(resp.items);
						addToast(pageText('albumPage.restored'), 'success');
					} catch {
						addToast(pageText('albumPage.restoreFailed'), 'error');
					}
				}
			});
		} catch {
			addToast(pageText('albumPage.deleteFailed'), 'error');
		}
	}

	async function onAlbumArchive(): Promise<void> {
		if (!selectedAlbum) return;
		const album = selectedAlbum;
		const albumId = album.id;
		try {
			await archiveAlbum(albumId);
			removeAlbumFromList(albumId);
			forgetListenedPlace('album', albumId);
			removeSongsForAlbum(albumId);
			setOpenCollection(null);
			addUndoToast(pageText('albumPage.archived'), {
				label: pageText('albumPage.undo'),
				handler: async () => {
					try {
						const restored = await unarchiveAlbum(albumId);
						addAlbumToList(restored);
						void readRestoredPlace('album', albumId);
						const resp = await fetchSongs(albumId);
						addSongsToList(resp.items);
						addToast(pageText('albumPage.unarchived'), 'success');
					} catch {
						addToast(pageText('albumPage.unarchiveFailed'), 'error');
					}
				}
			});
		} catch {
			addToast(pageText('albumPage.archiveFailed'), 'error');
		}
	}

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!currentAlbumId) return;
		try {
			const result = await addAlbumToPlaylist(playlistId, currentAlbumId);
			if (result.skipped.length > 0) {
				addToast(
					pageText('albumPage.addedSkipped', {
						added: String(result.added_count),
						skipped: String(result.skipped.length)
					}),
					'info'
				);
			} else {
				addToast(pageText('albumPage.addedToPlaylist'), 'success');
			}
		} catch (e) {
			addToast(describeFailure(e, pageText('albumPage.addFailed')), 'error');
		} finally {
			playlistPickerOpen = false;
		}
	}

	function onCurate(): void {
		if (!currentAlbumId) return;
		void curateAlbum(currentAlbumId);
	}

	// Unknown takes go straight to the player, which owns loading and cancellation.
	// Only a song already known to have nothing to hear opens the editor.
	function onSongTap(song: SongItem): void {
		if (songPlayability(song) === 'none') selectSong(song.id);
		else void playAlbumSong(song.album_id, song.id);
	}
</script>

{#if selectedAlbum}
	<div class="detail-panel">
		<CollectionHeader
			kind="album"
			collectionId={selectedAlbum.id}
			title={selectedAlbum.title}
			{coverUrl}
			{coverAlt}
			{initials}
			{artFill}
			onplay={currentAlbumId && albumHasTakes ? () => playAlbum(currentAlbumId) : null}
			meta={albumMeta}
			songCount={albumLoad === 'idle' ? albumSongs.length : selectedAlbum.song_count}
			isShared={selectedAlbum.is_shared}
			shareSlug={selectedAlbum.share_slug}
			onshare={onAlbumShareEnable}
			onunshare={onAlbumShareDisable}
			ondelete={() => (showDeleteConfirm = true)}
			onarchive={onAlbumArchive}
			onaddtoplaylist={() => (playlistPickerOpen = true)}
			oncurate={onCurate}
			{coverMark}
		>
			{#snippet detailsEditor(close: () => void)}
				<AlbumMetaEditor
					details={{
						title: selectedAlbum.title,
						subtitle: selectedAlbum.subtitle,
						year: selectedAlbum.year
					}}
					onsave={onSaveAlbumDetails}
					onclose={close}
				/>
			{/snippet}
			{#snippet coverEditor(close: () => void)}
				<AlbumCoverEditor
					album={selectedAlbum}
					onclose={close}
					onupload={onCoverAction}
					onremove={onCoverRemove}
					saving={coverBusy}
				/>
			{/snippet}
		</CollectionHeader>
		<input
			bind:this={coverInput}
			class="cover-file-input"
			type="file"
			accept={ALBUM_COVER_ACCEPT}
			disabled={coverBusy}
			onchange={onCoverFile}
		/>

		{#if playlistPickerOpen}
			<div class="picker-anchor">
				<PlaylistPicker onselect={onAddToPlaylist} onclose={() => (playlistPickerOpen = false)} />
			</div>
		{/if}

		<div class="item-list">
			{#if albumLoad === 'loading' && albumSongs.length === 0}
				<p class="empty-tab" role="status">{pageText('albumPage.loading')}</p>
			{:else if $albumLoadFailure && albumSongs.length === 0}
				<p class="empty-tab" role="alert">{$albumLoadFailure}</p>
				<button
					class="retry-btn"
					onclick={() => currentAlbumId && loadSongsForAlbum(currentAlbumId)}
					>{pageText('albumPage.retry')}</button
				>
			{:else if albumSongs.length > 0 || albumLoad !== 'unreachable'}
				{#if albumSongs.length === 0}
					<p class="empty-tab">{pageText('albumPage.noSongs')}</p>
				{/if}
				{#each albumSongs as s (s.id)}
					<SongRow
						title={s.title}
						meta={pageText('albumPage.songTakes', s.generation_count)}
						current={isSongCurrent(s.id)}
						onclick={() => onSongTap(s)}
						onedit={() => selectSong(s.id)}
					/>
				{/each}
				{#if newSongOpen}
					<NewSongCard album={selectedAlbum} oncancel={cancelNewSong} oncreated={foldCreatedSong} />
				{:else}
					<div class="new-song-row song-row-frame">
						<button
							bind:this={newSongRow}
							class="new-song-body"
							data-hitbox="text"
							onclick={startNewSong}
						>
							<Icon name="plus" size={16} />
							<span class="new-song-label">{pageText('newSong.rowLabel')}</span>
						</button>
					</div>
				{/if}
			{/if}
		</div>
	</div>
{/if}

{#if showDeleteConfirm && selectedAlbum}
	{@const totalGens = albumSongs.reduce((sum, s) => sum + s.generation_count, 0)}
	<ConfirmDeleteDialog
		title={pageText('albumPage.deleteTitle', { title: selectedAlbum.title })}
		items={[
			pageText('albumPage.deleteSongs', albumSongs.length, {
				titles: albumSongs.map((s) => s.title).join(', ')
			}),
			pageText('albumPage.deleteTakes', totalGens),
			pageText('albumPage.deleteHistory')
		]}
		confirmLabel={pageText('albumPage.deleteConfirm')}
		onconfirm={() => {
			showDeleteConfirm = false;
			onAlbumDelete();
		}}
		oncancel={() => (showDeleteConfirm = false)}
	/>
{/if}

<style>
	.detail-panel {
		padding-bottom: var(--player-height);
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		flex: 1;
		max-width: 1200px;
		width: 100%;
		min-width: 0;
		min-height: 0;
	}

	.cover-file-input {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.picker-anchor {
		position: relative;
		margin: 0 1.5rem;
	}

	.item-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 0 1.5rem;
	}

	.new-song-row {
		display: flex;
		color: var(--text-muted);
		font-size: 0.93rem;
	}

	.new-song-row:hover {
		color: var(--text);
	}

	.new-song-body {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex: 1;
		min-width: 0;
		background: none;
		border: none;
		padding: var(--song-row-inset-block) var(--song-row-inset-inline);
		text-align: left;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	/* The global press scale would shrink the target mid-press and send a release
	   near the row's edge to the row. */
	.new-song-row .new-song-body:active:not(:disabled) {
		transform: none;
	}

	.new-song-label {
		flex: 1;
		line-height: var(--song-row-line-height);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.empty-tab {
		color: var(--text-subtle);
		font-size: 0.87rem;
		font-style: italic;
		padding: 0.8rem 1.5rem;
	}

	.retry-btn {
		display: block;
		margin: 0.4rem 1.5rem 0.8rem;
		padding: 6px 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		cursor: pointer;
	}

	.retry-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

	@media (max-width: 768px) {
		.item-list,
		.picker-anchor {
			padding-left: 0.8rem;
			padding-right: 0.8rem;
		}

		.empty-tab {
			padding: 0.8rem;
		}

		.retry-btn {
			margin-inline: 0.8rem;
		}
	}
</style>
