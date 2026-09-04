<script lang="ts">
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
	} from '$lib/api/client';
	import {
		createAlbumCoverSuggestions,
		discardAlbumCoverSuggestions,
		fetchAlbumCoverSuggestions,
		selectAlbumCoverSuggestion
	} from '$lib/api/albums';
	import { fetchSongs } from '$lib/api/songs';
	import {
		albumList,
		albumSongsLoad,
		songList,
		loadSongsForAlbum,
		addAlbumToList,
		addSongsToList,
		removeAlbumFromList,
		removeSongsForAlbum,
		updateAlbumInList
	} from '$lib/stores/libraryData';
	import { curateAlbum, selectedAlbumId, playAlbum, playAlbumSong } from '$lib/stores/player';
	import { openLibraryCreate, selectSong } from '$lib/stores/navigation';
	import { setOpenCollection } from '$lib/stores/collection';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addAlbumToPlaylist } from '$lib/stores/playlists';
	import {
		ALBUM_ART_EMPTY_INITIALS,
		albumCoverSuggestionAlt,
		ALBUM_COVER_ACCEPT,
		ALBUM_COVER_ALT_TYPE,
		ALBUM_COVER_SUGGESTIONS_DETAIL,
		ALBUM_COVER_SUGGESTIONS_DISCARD_LABEL,
		ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK,
		ALBUM_COVER_SUGGESTIONS_FAILED_TITLE,
		ALBUM_COVER_SUGGESTIONS_LOADING,
		ALBUM_COVER_SUGGESTIONS_PROGRESS_TEMPLATE,
		ALBUM_COVER_SUGGESTIONS_RETRY_LABEL,
		ALBUM_COVER_SUGGESTIONS_TITLE,
		ALBUM_COVER_SUGGESTING_LABEL,
		ALBUM_COVER_SUGGESTION_USE_LABEL,
		ALBUM_COVER_SUGGEST_LABEL,
		ALBUM_YEAR_MAX,
		ALBUM_YEAR_MIN,
		collectionRowPlayLabel,
		LIBRARY_ALBUMS_LOADING,
		LIBRARY_RETRY_LABEL
	} from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { refreshSharesAfterMutation } from '$lib/stores/shares';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import type { CoverSuggestionsResponse, SongItem } from '$lib/api/types';
	import AlbumMetaEditor from './AlbumMetaEditor.svelte';
	import CollectionHeader from './CollectionHeader.svelte';
	import Icon from './Icon.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	interface Props {
		albumId?: string;
	}

	interface CoverSuggestionsState {
		albumId: string;
		data: CoverSuggestionsResponse | null;
		failure: string | null;
		isLoading: boolean;
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
	const coverUrl = $derived(selectedAlbum?.cover?.detail ?? null);
	const coverAlt = $derived(
		selectedAlbum ? `${ALBUM_COVER_ALT_TYPE} ${selectedAlbum.title}` : ALBUM_COVER_ALT_TYPE
	);
	const artFill = $derived(selectedAlbum ? usableAlbumPrimary(selectedAlbum.colors) : null);
	const initials = $derived(
		selectedAlbum ? titleInitials(selectedAlbum.title) : ALBUM_ART_EMPTY_INITIALS
	);
	let coverBusy = $state(false);
	let coverInput: HTMLInputElement | null = $state(null);
	let coverSuggestionsState = $state<CoverSuggestionsState | null>(null);
	let coverSuggestionsBusyAlbumId = $state<string | null>(null);
	let suggestionsRequest = 0;
	let completedCoverJobId: string | null = null;

	const activeCoverJob = $derived(
		currentAlbumId
			? ($activeJobs.find((active) => active.albumId === currentAlbumId) ?? null)
			: null
	);
	const coverSuggestions = $derived(
		coverSuggestionsState?.albumId === currentAlbumId ? coverSuggestionsState.data : null
	);
	const coverSuggestionsFailure = $derived(
		coverSuggestionsState?.albumId === currentAlbumId ? coverSuggestionsState.failure : null
	);
	const coverSuggestionsLoading = $derived(
		coverSuggestionsState?.albumId === currentAlbumId && coverSuggestionsState.isLoading
	);
	const coverSuggestionsBusy = $derived(coverSuggestionsBusyAlbumId === currentAlbumId);
	const latestCoverJob = $derived(coverSuggestions?.job ?? null);
	const isCoverSuggestionGenerating = $derived(
		Boolean(activeCoverJob) ||
			latestCoverJob?.status === 'queued' ||
			latestCoverJob?.status === 'running'
	);
	const coverSuggestionFailure = $derived(
		coverSuggestionsFailure ??
			(latestCoverJob?.status === 'failed'
				? (latestCoverJob.error ?? ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK)
				: null)
	);
	const coverSuggestionsProgress = $derived(
		activeCoverJob?.job.progress ?? latestCoverJob?.progress ?? 0
	);
	const hasSuggestions = $derived((coverSuggestions?.suggestions.length ?? 0) > 0);
	const showCoverSuggestionsPanel = $derived(
		Boolean(
			coverSuggestionsLoading ||
			isCoverSuggestionGenerating ||
			hasSuggestions ||
			coverSuggestionFailure ||
			!selectedAlbum?.cover
		)
	);
	const coverSuggestionsProgressMessage = $derived(
		coverSuggestions
			? formatCoverSuggestionProgress(coverSuggestions.used_today, coverSuggestions.daily_limit)
			: null
	);

	$effect(() => {
		const albumId = currentAlbumId;
		if (!albumId) {
			coverSuggestionsState = null;
			return;
		}
		coverSuggestionsState = {
			albumId,
			data: null,
			failure: null,
			isLoading: true
		};
		queueMicrotask(() => void loadCoverSuggestions(albumId));
	});

	$effect(() => {
		if (activeCoverJob) {
			completedCoverJobId = activeCoverJob.job.id;
			return;
		}
		if (completedCoverJobId && currentAlbumId) {
			const albumId = currentAlbumId;
			completedCoverJobId = null;
			queueMicrotask(() => void loadCoverSuggestions(albumId));
		}
	});

	async function loadCoverSuggestions(albumId: string): Promise<void> {
		const request = ++suggestionsRequest;
		updateCoverSuggestionsState(albumId, (state) => ({ ...state, isLoading: true }));
		try {
			const response = await fetchAlbumCoverSuggestions(albumId);
			if (request !== suggestionsRequest || albumId !== currentAlbumId) return;
			coverSuggestionsState = {
				albumId,
				data: response,
				failure: null,
				isLoading: false
			};
			if (response.job?.status === 'queued' || response.job?.status === 'running') {
				trackJob(response.job, { albumId });
			}
		} catch (error) {
			if (request !== suggestionsRequest || albumId !== currentAlbumId) return;
			coverSuggestionsState = {
				albumId,
				data: null,
				failure: errorMessage(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK),
				isLoading: false
			};
		}
	}

	function updateCoverSuggestionsState(
		albumId: string,
		update: (state: CoverSuggestionsState) => CoverSuggestionsState
	): void {
		if (albumId !== currentAlbumId) return;
		const state =
			coverSuggestionsState?.albumId === albumId
				? coverSuggestionsState
				: { albumId, data: null, failure: null, isLoading: false };
		coverSuggestionsState = update(state);
	}

	function errorMessage(error: unknown, fallback: string): string {
		return error instanceof Error && error.message ? error.message : fallback;
	}

	function formatCoverSuggestionProgress(used: number, limit: number): string {
		return ALBUM_COVER_SUGGESTIONS_PROGRESS_TEMPLATE.replace('{used}', String(used)).replace(
			'{limit}',
			String(limit)
		);
	}

	async function suggestCover(): Promise<void> {
		if (!selectedAlbum || isCoverSuggestionGenerating || coverSuggestionsLoading) return;
		const albumId = selectedAlbum.id;
		// A page-load GET can resolve after this deliberate POST. Its older
		// snapshot must not erase the just-created job and make progress vanish.
		suggestionsRequest += 1;
		updateCoverSuggestionsState(albumId, (state) => ({ ...state, failure: null, isLoading: true }));
		try {
			if (hasSuggestions) {
				await discardAlbumCoverSuggestions(albumId);
				updateCoverSuggestionsState(albumId, (state) => ({ ...state, data: null }));
			}
			const job = await createAlbumCoverSuggestions(albumId);
			if (albumId !== currentAlbumId) return;
			trackJob(job, { albumId });
			void loadCoverSuggestions(albumId);
		} catch (error) {
			updateCoverSuggestionsState(albumId, (state) => ({
				...state,
				failure: errorMessage(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK),
				isLoading: false
			}));
		}
	}

	async function discardCoverSuggestions(): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		coverSuggestionsBusyAlbumId = albumId;
		try {
			await discardAlbumCoverSuggestions(albumId);
			updateCoverSuggestionsState(albumId, (state) => ({
				...state,
				data: null,
				failure: null
			}));
		} catch (error) {
			updateCoverSuggestionsState(albumId, (state) => ({
				...state,
				failure: errorMessage(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK)
			}));
		} finally {
			if (coverSuggestionsBusyAlbumId === albumId) coverSuggestionsBusyAlbumId = null;
		}
	}

	async function selectCoverSuggestion(suggestionId: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		coverSuggestionsBusyAlbumId = albumId;
		try {
			const updated = await selectAlbumCoverSuggestion(albumId, {
				suggestion_id: suggestionId
			});
			try {
				await discardAlbumCoverSuggestions(albumId);
			} catch (error) {
				addToast(errorMessage(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK), 'error');
			}
			updateAlbumInList(albumId, () => updated);
			updateCoverSuggestionsState(albumId, (state) => ({
				...state,
				data: null,
				failure: null
			}));
			addToast('Cover saved', 'success');
		} catch (error) {
			updateCoverSuggestionsState(albumId, (state) => ({
				...state,
				failure: errorMessage(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK)
			}));
		} finally {
			if (coverSuggestionsBusyAlbumId === albumId) coverSuggestionsBusyAlbumId = null;
		}
	}

	async function onCoverFile(event: Event): Promise<void> {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !selectedAlbum) return;
		coverBusy = true;
		try {
			const updated = await uploadAlbumCover(selectedAlbum.id, file);
			updateAlbumInList(selectedAlbum.id, () => updated);
			addToast('Cover saved', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Cover upload failed', 'error');
		} finally {
			coverBusy = false;
		}
	}

	function onCoverAction(): void {
		coverInput?.click();
	}

	async function onCoverRemove(): Promise<void> {
		if (!selectedAlbum) return;
		coverBusy = true;
		try {
			const updated = await deleteAlbumCover(selectedAlbum.id);
			updateAlbumInList(selectedAlbum.id, () => updated);
			addToast('Cover removed', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Cover remove failed', 'error');
		} finally {
			coverBusy = false;
		}
	}

	async function onRenameAlbum(newTitle: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		try {
			const updated = await updateAlbum(albumId, { title: newTitle });
			updateAlbumInList(albumId, () => updated);
			addToast('Album renamed', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Rename failed', 'error');
			throw e;
		}
	}

	async function onSaveAlbumSubtitle(newSubtitle: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		try {
			const updated = await updateAlbum(albumId, { subtitle: newSubtitle });
			updateAlbumInList(albumId, () => updated);
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Update failed', 'error');
			throw e;
		}
	}

	async function onSaveAlbumYear(newYear: string): Promise<void> {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		const year = newYear ? Number(newYear) : null;
		if (newYear && !Number.isInteger(year)) {
			addToast('Year must be a whole number', 'error');
			throw new Error('Year must be a whole number');
		}
		if (year !== null && (year < ALBUM_YEAR_MIN || year > ALBUM_YEAR_MAX)) {
			addToast(`Year must be between ${ALBUM_YEAR_MIN} and ${ALBUM_YEAR_MAX}`, 'error');
			throw new Error('Year out of range');
		}
		try {
			const updated = await updateAlbum(albumId, { year });
			updateAlbumInList(albumId, () => updated);
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Update failed', 'error');
			throw e;
		}
	}

	async function onAlbumShareEnable() {
		if (!selectedAlbum) throw new Error('No album');
		const albumId = selectedAlbum.id;
		const result = await shareAlbum(albumId);
		updateAlbumInList(albumId, (a) => ({ ...a, is_shared: true, share_slug: result.share_slug }));
		await refreshSharesAfterMutation();
		return result;
	}

	async function onAlbumShareDisable() {
		if (!selectedAlbum) return;
		const albumId = selectedAlbum.id;
		await unshareAlbum(albumId);
		updateAlbumInList(albumId, (a) => ({ ...a, is_shared: false, share_slug: null }));
		await refreshSharesAfterMutation();
	}

	async function onAlbumDelete(): Promise<void> {
		if (!selectedAlbum) return;
		const album = selectedAlbum;
		const albumId = album.id;
		try {
			await deleteAlbum(albumId);
			removeAlbumFromList(albumId);
			removeSongsForAlbum(albumId);
			setOpenCollection(null);
			addUndoToast('Album deleted', {
				label: 'Undo',
				handler: async () => {
					try {
						const restored = await restoreAlbum(albumId);
						addAlbumToList(restored);
						const resp = await fetchSongs(albumId);
						addSongsToList(resp.items);
						addToast('Album restored', 'success');
					} catch {
						addToast('Restore failed', 'error');
					}
				}
			});
		} catch {
			addToast('Delete failed', 'error');
		}
	}

	async function onAlbumArchive(): Promise<void> {
		if (!selectedAlbum) return;
		const album = selectedAlbum;
		const albumId = album.id;
		try {
			await archiveAlbum(albumId);
			removeAlbumFromList(albumId);
			removeSongsForAlbum(albumId);
			setOpenCollection(null);
			addUndoToast('Album archived', {
				label: 'Undo',
				handler: async () => {
					try {
						const restored = await unarchiveAlbum(albumId);
						addAlbumToList(restored);
						const resp = await fetchSongs(albumId);
						addSongsToList(resp.items);
						addToast('Album unarchived', 'success');
					} catch {
						addToast('Unarchive failed', 'error');
					}
				}
			});
		} catch {
			addToast('Archive failed', 'error');
		}
	}

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!currentAlbumId) return;
		try {
			const result = await addAlbumToPlaylist(playlistId, currentAlbumId);
			if (result.skipped.length > 0) {
				addToast(`Added ${result.added_count}, skipped ${result.skipped.length}`, 'info');
			} else {
				addToast('Added to playlist', 'success');
			}
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		} finally {
			playlistPickerOpen = false;
		}
	}

	function onRowPlay(song: SongItem): void {
		if (!currentAlbumId) return;
		void playAlbumSong(currentAlbumId, song);
	}

	function onCurate(): void {
		if (!currentAlbumId) return;
		void curateAlbum(currentAlbumId);
	}
</script>

{#if selectedAlbum}
	<div class="detail-panel">
		<CollectionHeader
			kind="album"
			title={selectedAlbum.title}
			{coverUrl}
			{coverAlt}
			{initials}
			{artFill}
			onplay={() => currentAlbumId && playAlbum(currentAlbumId)}
			onrename={onRenameAlbum}
			isShared={selectedAlbum.is_shared}
			shareSlug={selectedAlbum.share_slug}
			onshare={onAlbumShareEnable}
			onunshare={onAlbumShareDisable}
			ondelete={() => (showDeleteConfirm = true)}
			onarchive={onAlbumArchive}
			oncover={onCoverAction}
			oncoversuggest={selectedAlbum.cover ? suggestCover : undefined}
			onremovecover={onCoverRemove}
			onaddtoplaylist={() => (playlistPickerOpen = true)}
			onaddsong={openLibraryCreate}
			oncurate={onCurate}
		>
			{#snippet metaEditor()}
				<AlbumMetaEditor
					subtitle={selectedAlbum.subtitle}
					year={selectedAlbum.year}
					onsavesubtitle={onSaveAlbumSubtitle}
					onsaveyear={onSaveAlbumYear}
				/>
			{/snippet}
		</CollectionHeader>
		{#if showCoverSuggestionsPanel}
			<section class="cover-suggestions" aria-live="polite">
				{#if coverSuggestionsLoading && !isCoverSuggestionGenerating}
					<p class="cover-suggestions-loading" role="status">{ALBUM_COVER_SUGGESTIONS_LOADING}</p>
				{:else if isCoverSuggestionGenerating}
					<h3>{ALBUM_COVER_SUGGESTING_LABEL}</h3>
					{#if coverSuggestionsProgressMessage}
						<p>{coverSuggestionsProgressMessage}</p>
					{/if}
					<div class="suggestion-placeholders" aria-label={ALBUM_COVER_SUGGESTING_LABEL}>
						{#each [1, 2, 3] as placeholder (placeholder)}
							<span class="suggestion-placeholder"></span>
						{/each}
					</div>
					<div
						class="suggestion-progress"
						aria-label={`${Math.round(coverSuggestionsProgress * 100)}%`}
					>
						<span style:width={`${Math.max(4, coverSuggestionsProgress * 100)}%`}></span>
					</div>
				{:else if coverSuggestionFailure}
					<div class="cover-suggestion-failure" role="alert">
						<strong>{ALBUM_COVER_SUGGESTIONS_FAILED_TITLE}</strong>
						<p>{coverSuggestionFailure}</p>
						<button type="button" onclick={suggestCover}
							>{ALBUM_COVER_SUGGESTIONS_RETRY_LABEL}</button
						>
					</div>
				{:else if hasSuggestions}
					<h3>{ALBUM_COVER_SUGGESTIONS_TITLE}</h3>
					<p>{ALBUM_COVER_SUGGESTIONS_DETAIL}</p>
					<div class="suggestion-grid">
						{#each coverSuggestions?.suggestions ?? [] as suggestion (suggestion.id)}
							<article class="cover-suggestion">
								<img src={suggestion.url} alt={albumCoverSuggestionAlt(selectedAlbum.title)} />
								<button
									type="button"
									disabled={coverSuggestionsBusy}
									onclick={() => selectCoverSuggestion(suggestion.id)}
								>
									{ALBUM_COVER_SUGGESTION_USE_LABEL}
								</button>
							</article>
						{/each}
					</div>
					<button
						class="suggestion-discard"
						type="button"
						disabled={coverSuggestionsBusy}
						onclick={discardCoverSuggestions}>{ALBUM_COVER_SUGGESTIONS_DISCARD_LABEL}</button
					>
				{:else if !selectedAlbum.cover}
					<button class="suggest-cover" type="button" onclick={suggestCover}
						>{ALBUM_COVER_SUGGEST_LABEL}</button
					>
				{/if}
			</section>
		{/if}
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
			{#if albumLoad?.status === 'loading' && albumSongs.length === 0}
				<p class="empty-tab" role="status">{LIBRARY_ALBUMS_LOADING}</p>
			{:else if albumLoad?.status === 'error' && albumSongs.length === 0}
				<p class="empty-tab" role="alert">{albumLoad.error}</p>
				<button
					class="retry-btn"
					onclick={() => currentAlbumId && loadSongsForAlbum(currentAlbumId)}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else if albumSongs.length === 0}
				<p class="empty-tab">No songs in this album yet.</p>
			{:else}
				{#each albumSongs as s (s.id)}
					<div class="item-row">
						<button
							class="item-play"
							data-hitbox="frequent"
							disabled={s.generation_count === 0}
							onclick={() => onRowPlay(s)}
							aria-label={collectionRowPlayLabel(s.title)}
						>
							<Icon name="play" size={14} />
						</button>
						<button class="item-body" onclick={() => selectSong(s.id)}>
							<span class="item-title">{s.title}</span>
							<span class="item-meta">
								{s.generation_count} take{s.generation_count !== 1 ? 's' : ''}
							</span>
						</button>
					</div>
				{/each}
			{/if}
		</div>
	</div>
{/if}

{#if showDeleteConfirm && selectedAlbum}
	{@const totalGens = albumSongs.reduce((sum, s) => sum + s.generation_count, 0)}
	<ConfirmDeleteDialog
		title={`Delete "${selectedAlbum.title}"?`}
		items={[
			`${albumSongs.length} song${albumSongs.length !== 1 ? 's' : ''} (${albumSongs.map((s) => s.title).join(', ')})`,
			`${totalGens} take${totalGens !== 1 ? 's' : ''}`,
			'All versions, scores, and chat history'
		]}
		confirmLabel="Delete Album"
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

	.cover-suggestions {
		display: flex;
		flex-direction: column;
		gap: 0.65rem;
		margin: 0 1.5rem;
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.cover-suggestions h3,
	.cover-suggestions p {
		margin: 0;
	}

	.cover-suggestions h3 {
		font-family: var(--font-display);
		font-size: 1rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.cover-suggestions p {
		color: var(--text-subtle);
		font-size: 0.83rem;
	}

	.cover-suggestions-loading {
		font-style: italic;
	}

	.suggest-cover,
	.cover-suggestion button,
	.suggestion-discard,
	.cover-suggestion-failure button {
		align-self: flex-start;
		padding: 0.45rem 0.8rem;
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: var(--accent);
		color: #fff;
		font-family: var(--font-display);
		font-size: 0.78rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		cursor: pointer;
	}

	.suggestion-grid,
	.suggestion-placeholders {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0.75rem;
	}

	.cover-suggestion {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
		min-width: 0;
		padding: 0.45rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface-hover);
	}

	.cover-suggestion img,
	.suggestion-placeholder {
		display: block;
		width: 100%;
		aspect-ratio: 1;
		border-radius: calc(var(--card-radius) / 2);
		object-fit: cover;
	}

	.suggestion-placeholder {
		background: linear-gradient(
			110deg,
			var(--surface-hover) 20%,
			var(--border) 45%,
			var(--surface-hover) 70%
		);
		background-size: 220% 100%;
		animation: cover-suggestion-loading 1.2s linear infinite;
	}

	.suggestion-progress {
		height: 0.25rem;
		overflow: hidden;
		border-radius: 999px;
		background: var(--border);
	}

	.suggestion-progress span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--accent);
		transition: width 180ms ease-out;
	}

	.suggestion-discard {
		border-color: var(--border);
		background: transparent;
		color: var(--text-muted);
	}

	.cover-suggestion-failure {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		padding: 0.85rem;
		border: 1px solid var(--danger);
		border-left-width: 4px;
		border-radius: var(--card-radius);
		background: color-mix(in srgb, var(--danger) 12%, var(--surface));
	}

	.cover-suggestion-failure strong {
		color: var(--text);
	}

	@keyframes cover-suggestion-loading {
		to {
			background-position: -220% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.suggestion-placeholder {
			animation: none;
		}

		.suggestion-progress span {
			transition: none;
		}
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

	.item-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.65rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		font-size: 0.93rem;
	}

	.item-row:hover {
		border-color: var(--primary);
		background: var(--surface-hover);
	}

	.item-play {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 1.9rem;
		height: 1.9rem;
		flex-shrink: 0;
		border-radius: 50%;
		border: 1px solid var(--border);
		background: none;
		color: var(--text-muted);
		cursor: pointer;
	}

	.item-play:hover:not(:disabled) {
		border-color: var(--primary);
		color: var(--primary);
	}

	.item-play:disabled {
		opacity: 0.35;
		cursor: default;
	}

	.item-body {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex: 1;
		min-width: 0;
		background: none;
		border: none;
		padding: 0;
		text-align: left;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.item-title {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.item-meta {
		font-size: 0.75rem;
		color: var(--text-subtle);
		flex-shrink: 0;
	}

	.empty-tab {
		color: var(--text-subtle);
		font-size: 0.87rem;
		font-style: italic;
		padding: 0.8rem 1.5rem;
	}

	@media (max-width: 768px) {
		.cover-suggestions {
			margin: 0 0.8rem;
		}

		.suggestion-grid,
		.suggestion-placeholders {
			grid-template-columns: 1fr;
		}

		.cover-suggestion {
			display: grid;
			grid-template-columns: 4.4rem minmax(0, 1fr);
			align-items: center;
		}

		.cover-suggestion img {
			width: 4.4rem;
		}

		.item-list,
		.picker-anchor {
			padding-left: 0.8rem;
			padding-right: 0.8rem;
		}

		.empty-tab {
			padding: 0.8rem;
		}
	}
</style>
