<script lang="ts">
	import { get } from 'svelte/store';
	import { onMount, type ComponentProps } from 'svelte';
	import {
		fetchSong,
		renameSong,
		deleteSong,
		restoreSong,
		shareSong,
		unshareSong,
		shareGeneration,
		unshareGeneration,
		deleteGeneration,
		uploadSongCover,
		deleteSongCover
	} from '$lib/api/client';
	import { describeFailure, NetworkError } from '$lib/api/fetch';
	import { offline, whenBackOnline } from '$lib/stores/connectivity';
	import { fetchAlbum } from '$lib/api/albums';
	import { startHealthPolling, stopHealthPolling } from '$lib/stores/health';
	import {
		albumList,
		songList,
		replaceSongInList,
		updateSongInList,
		updateGenerationInList,
		removeGenerationFromSong,
		removeSongFromList,
		addSongsToList,
		addAlbumToList
	} from '$lib/stores/libraryData';
	import { selectedSong, selectedGenerationId, ensureGenerationsLoaded } from '$lib/stores/player';
	import {
		albumTrackNeighbors,
		backToCollection,
		compareAlbumTracks,
		openCollectionEntry,
		openLibraryWall,
		openEditTab,
		clearGenerationSelection,
		persistLibraryHistory,
		selectNeighborSong,
		pendingDirtyNavigation,
		detailTab
	} from '$lib/stores/navigation';
	import { openCollection } from '$lib/stores/collection';
	import {
		isDirty,
		versions,
		loadSongData,
		loadVersionAsDraft,
		pendingVersionLoad,
		versionDeleteRequest,
		handleDeleteVersion,
		handleSave,
		computeDraftVersionNumber,
		draftSavesAsNewVersion,
		discardDraft,
		pinnedSeed,
		editBpm,
		editAudioDuration,
		editKeyScale,
		editGenParams,
		savedSongData
	} from '$lib/stores/editor';
	import { activeModels, loadActiveModels } from '$lib/stores/presets';
	import { loras, loadLoras } from '$lib/stores/loras';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addGenerationToPlaylist, addSongToPlaylist } from '$lib/stores/playlists';
	import {
		coWriterOpen,
		pendingSource,
		recipeChips,
		recipeModel,
		recipeOpen,
		repaintMode,
		resetRecipeSourceForSong,
		seedRecipeModel,
		setSourceFromGeneration,
		sourceGeneration,
		sourceMode,
		takesPerGenerate,
		type SourceMode
	} from '$lib/stores/recipe';
	import { setGenerationActions, takeActionsFor } from '$lib/contexts/generation-actions';
	import type { GenerationItem, SongItem, VersionItem } from '$lib/api/types';
	import {
		EXPIRY_WARN_DAYS,
		LIBRARY_NARROW_MEDIA,
		RAIL_LIBRARY_LABEL,
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_COVER_ALT_TYPE,
		SONG_COVER_ALT_TYPE,
		SONG_COVER_REPLACE_LABEL,
		SONG_COVER_UPLOAD_LABEL,
		EDITOR_SAVE_ACCESSIBLE_LABEL,
		EDITOR_SAVE_FAILED,
		EDITOR_SAVE_LABEL,
		EDITOR_UNSAVED_TITLE,
		EDITOR_UNSAVED_MESSAGE,
		EDITOR_UNSAVED_SAVE_LABEL,
		EDITOR_UNSAVED_DISCARD_LABEL,
		TAKES_ERROR,
		TOAST_UNDO_LABEL,
		VERSION_DELETE_CONFIRM_LABEL,
		VERSION_DELETE_PICK_WARNING,
		VERSION_REPLACE_DRAFT_CONFIRM_LABEL,
		VERSION_REPLACE_DRAFT_TITLE,
		versionDeleteTitle,
		versionLabel,
		versionLoadedToastLabel,
		versionReplaceDraftMessage
	} from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import EditorHeader from './editor/EditorHeader.svelte';
	import RecipeChips from './editor/RecipeChips.svelte';
	import RecipePanel from './editor/RecipePanel.svelte';
	import EditorStacked from './editor/EditorStacked.svelte';
	import WriteColumn from './editor/WriteColumn.svelte';
	import TakesList from './editor/TakesList.svelte';
	import { phoneAppBar } from '$lib/stores/ui';
	import SongPhoneView from './editor/SongPhoneView.svelte';
	import CoWriterPanel from './CoWriterPanel.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import ConfirmDialog from './ConfirmDialog.svelte';
	import ShareLinkChip from './ShareLinkChip.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';

	let showDeleteConfirm = $state(false);
	let versionAwaitingReplace = $state<{
		version: VersionItem;
		answer: (loaded: boolean) => void;
	} | null>(null);
	let compact = $state(false);
	let songRail = $state(false);
	let takesStatus = $state<'loading' | 'ready' | 'error'>('ready');
	let takesError = $state<string | null>(null);
	let coverFailed = $state(false);
	let coverBusy = $state(false);
	let requestedParentAlbumId: string | null = $state(null);
	let stackedExpanded = $state(false);

	const song = $derived($selectedSong);
	const songs = $derived($songList);
	const albums = $derived($albumList);
	const parentAlbum = $derived(
		song ? (albums.find((album) => album.id === song.album_id) ?? null) : null
	);
	const ownCoverUrl = $derived(song?.cover?.detail ?? null);
	const inheritedCoverUrl = $derived(ownCoverUrl ? null : (parentAlbum?.cover?.detail ?? null));
	const coverUrl = $derived(ownCoverUrl ?? inheritedCoverUrl);
	const hasOwnCover = $derived(Boolean(song?.cover));
	const coverAlt = $derived(
		ownCoverUrl && song
			? `${SONG_COVER_ALT_TYPE} ${song.title}`
			: parentAlbum
				? `${ALBUM_COVER_ALT_TYPE} ${parentAlbum.title}`
				: SONG_COVER_ALT_TYPE
	);
	const artFill = $derived(parentAlbum ? usableAlbumPrimary(parentAlbum.colors) : null);
	const initials = $derived(song ? titleInitials(song.title) : ALBUM_ART_EMPTY_INITIALS);
	const coverActionLabel = $derived(
		hasOwnCover ? SONG_COVER_REPLACE_LABEL : SONG_COVER_UPLOAD_LABEL
	);
	const neighbors = $derived(
		song ? albumTrackNeighbors(song.id, songs) : { previous: null, next: null }
	);
	const albumTracks = $derived(
		song ? songs.filter((item) => item.album_id === song.album_id).sort(compareAlbumTracks) : []
	);
	const trackPosition = $derived(
		song ? albumTracks.findIndex((item) => item.id === song.id) + 1 : 0
	);
	const trackTotal = $derived(albumTracks.length);
	const albumSongCount = $derived(parentAlbum?.song_count ?? trackTotal);
	const albumCoverUrl = $derived(parentAlbum?.cover?.card ?? null);
	const albumArtFill = $derived(parentAlbum ? usableAlbumPrimary(parentAlbum.colors) : null);
	const albumInitials = $derived(titleInitials(parentAlbum?.title ?? song?.album_title ?? ''));
	const collection = $derived($openCollection);
	const breadcrumbItems = $derived(
		song
			? [
					{ label: RAIL_LIBRARY_LABEL, onclick: () => void openLibraryWall() },
					{
						label: song.album_title,
						onclick: collection ? () => openCollectionEntry(collection) : undefined
					},
					{ label: trackTotal > 0 ? `Track ${trackPosition} of ${trackTotal}` : song.title }
				]
			: []
	);
	const dirty = $derived($isDirty);
	// song.version_count is a *count* of surviving versions, not the highest
	// version number — the two diverge once any version has been deleted, so
	// neither label below may use it. See computeDraftVersionNumber().
	const draftVersionNumber = $derived(
		computeDraftVersionNumber($versions, song?.generations ?? [], $draftSavesAsNewVersion)
	);
	const latestVersionNumber = $derived($versions[0]?.version_number ?? song?.version_count ?? 1);

	let editorSongId: string | null = null;

	$effect(() => {
		void coverUrl;
		coverFailed = false;
	});

	$effect(() => {
		const current = song;
		if (!current) {
			requestedParentAlbumId = null;
			return;
		}
		if (parentAlbum) {
			requestedParentAlbumId = current.album_id;
			return;
		}
		if (requestedParentAlbumId === current.album_id) return;
		const albumId = current.album_id;
		requestedParentAlbumId = albumId;
		void fetchAlbum(albumId)
			.then((album) => {
				if (album.id !== albumId) return;
				addAlbumToList(album);
			})
			.catch(() => undefined);
	});

	async function onCoverFile(event: Event): Promise<void> {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !song) return;
		coverBusy = true;
		try {
			const updated = await uploadSongCover(song.id, file);
			updateSongInList(song.id, (current) => ({ ...current, cover: updated.cover }));
			coverFailed = false;
			addToast('Cover saved', 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Cover upload failed'), 'error');
		} finally {
			coverBusy = false;
		}
	}

	async function onCoverRemove(): Promise<void> {
		if (!song) return;
		coverBusy = true;
		try {
			const updated = await deleteSongCover(song.id);
			updateSongInList(song.id, (current) => ({ ...current, cover: updated.cover ?? null }));
			coverFailed = false;
			addToast('Cover removed', 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Cover remove failed'), 'error');
		} finally {
			coverBusy = false;
		}
	}

	$effect(() => {
		const current = song;
		if (!current) {
			editorSongId = null;
			return;
		}
		if (current.id !== editorSongId) {
			editorSongId = current.id;
			resetRecipeSourceForSong();
			loadSongData(current);
			void refreshTakes(current.id);
			return;
		}
		void ensureGenerationsLoaded(current.id);
	});

	$effect(() => {
		const pending = $pendingSource;
		if (!pending || !song || pending.generation.song_id !== song.id) return;
		useSource(pending.generation, pending.mode);
		pendingSource.set(null);
	});

	$effect(() => {
		const pending = $pendingVersionLoad;
		if (!pending || !song || pending.songId !== song.id) return;
		if (!$versions.some((version) => version.id === pending.versionId)) return;
		pendingVersionLoad.set(null);
		void onVersionClick(pending.versionId);
	});

	const expiringSoon = $derived.by(() => {
		if (!song) return { count: 0, minDays: 0 };
		const now = Date.now();
		const dayMs = 1000 * 60 * 60 * 24;
		let count = 0;
		let minDays = Infinity;
		for (const gen of song.generations) {
			if (gen.is_picked || gen.is_kept || gen.is_archived || !gen.expires_at) continue;
			const days = Math.ceil((new Date(gen.expires_at).getTime() - now) / dayMs);
			if (days <= EXPIRY_WARN_DAYS) {
				count += 1;
				if (days < minDays) minDays = days;
			}
		}
		return { count, minDays: count > 0 ? Math.max(0, minDays) : 0 };
	});

	$effect(() => {
		startHealthPolling();
		return () => stopHealthPolling();
	});

	$effect(() => {
		void loadActiveModels();
	});

	onMount(() => {
		void loadLoras(true).catch(() => {});
	});

	onMount(() =>
		whenBackOnline(() => {
			if (song && takesStatus !== 'ready') void refreshTakes(song.id);
		})
	);

	$effect(() => {
		seedRecipeModel($activeModels.map((m) => m.id));
	});

	$effect(() => {
		return subscribeCompactLayout((value) => {
			compact = value;
		});
	});

	$effect(() => {
		if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
			songRail = false;
			return;
		}
		const media = window.matchMedia(LIBRARY_NARROW_MEDIA);
		const sync = () => {
			songRail = media.matches;
		};
		sync();
		media.addEventListener('change', sync);
		return () => media.removeEventListener('change', sync);
	});

	const chips = $derived(
		recipeChips({
			model: $recipeModel,
			takes: $takesPerGenerate,
			bpm: $editBpm,
			audioDuration: $editAudioDuration,
			keyScale: $editKeyScale,
			voiceLabel: resolveVoiceLabel($editGenParams?.user_lora_id ?? null),
			pinnedSeed: $pinnedSeed,
			genParams: $editGenParams,
			sourceGeneration: $sourceGeneration,
			sourceMode: $sourceMode,
			repaintMode: $repaintMode,
			savedBpm: $savedSongData.bpm,
			savedAudioDuration: $savedSongData.audio_duration,
			savedKeyScale: $savedSongData.key_scale,
			savedGenParams: $savedSongData.genParams
		})
	);

	// Both toggles stacked pushes the full Recipe panel's three multi-field
	// groups below the fold — see EditorStacked.svelte. Not relevant on
	// compact, where Recipe expands inline.
	const stacked = $derived($coWriterOpen && $recipeOpen && !compact);

	$effect(() => {
		if (!stacked) stackedExpanded = false;
	});

	function resolveVoiceLabel(loraId: string | null): string {
		if (!loraId) return 'None';
		const voice = $loras.find((l) => l.id === loraId);
		if (!voice) return 'Custom';
		return voice.deleted_at ? `${voice.name} — voice deleted` : voice.name;
	}

	setGenerationActions({
		...takeActionsFor(() => song),
		del: onDeleteGeneration,
		share: onGenShareEnable,
		unshare: onGenShareDisable,
		// Plain mutation: the take row that asked for it owns the outcome the
		// listener sees, success and failure alike (#163/3).
		addToPlaylist: addGenerationToPlaylist,
		clickVersion: onVersionClick
	});

	/**
	 * A load that got no network answer while the page is offline leaves the
	 * list waiting, with what is on screen kept: the one offline strip says it,
	 * and the list reloads by itself once the page is back online (#1039 O4).
	 * Without the strip nothing would ever reload it, so any other failure is
	 * named, in the server's own words where it gave some, with Try again.
	 */
	async function refreshTakes(songId: string): Promise<void> {
		const current = get(selectedSong);
		if (
			current &&
			current.id === songId &&
			current.generations.length >= current.generation_count
		) {
			takesStatus = 'ready';
			takesError = null;
			return;
		}
		takesStatus = 'loading';
		takesError = null;
		try {
			await ensureGenerationsLoaded(songId);
			if (editorSongId !== songId) return;
			takesStatus = 'ready';
		} catch (e) {
			if (editorSongId !== songId) return;
			if (e instanceof NetworkError && get(offline)) return;
			takesStatus = 'error';
			takesError = describeFailure(e, TAKES_ERROR);
		}
	}

	const takeListProps = $derived(
		song
			? ({
					song,
					voices: $loras,
					loadStatus: takesStatus,
					loadError: takesError,
					dirty,
					draftVersionNumber,
					latestVersionNumber,
					onsource: useSource,
					onretry: () => {
						if (song) void refreshTakes(song.id);
					}
				} satisfies ComponentProps<typeof TakesList>)
			: null
	);

	function useSource(gen: GenerationItem, mode: SourceMode): void {
		setSourceFromGeneration(gen, mode);
		if (compact) openEditTab();
	}

	async function onVersionClick(versionId: string): Promise<boolean> {
		const loaded = await askToLoadVersion(versionId);
		if (loaded && compact) openEditTab();
		return loaded;
	}

	function askToLoadVersion(versionId: string): Promise<boolean> {
		const version = get(versions).find((v) => v.id === versionId);
		if (!version) return Promise.resolve(false);
		if (!get(isDirty)) {
			loadVersionWithUndo(version);
			return Promise.resolve(true);
		}
		return new Promise((answer) => {
			versionAwaitingReplace = { version, answer };
		});
	}

	function answerVersionReplace(replace: boolean): void {
		const awaiting = versionAwaitingReplace;
		versionAwaitingReplace = null;
		if (!awaiting) return;
		if (replace) loadVersionWithUndo(awaiting.version);
		awaiting.answer(replace);
	}

	async function confirmVersionDelete(): Promise<void> {
		const request = get(versionDeleteRequest);
		versionDeleteRequest.set(null);
		if (!request) return;
		try {
			await handleDeleteVersion(request.songId, request.version.id, true);
			addToast(`Deleted ${versionLabel(request.version.version_number)}`, 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Delete failed'), 'error');
		}
	}

	function loadVersionWithUndo(version: VersionItem): void {
		const load = loadVersionAsDraft(version);
		if (!load) return;
		addUndoToast(
			versionLoadedToastLabel(version.version_number),
			{ label: TOAST_UNDO_LABEL, handler: load.undo, holds: load.holds },
			'brief'
		);
	}

	async function onRenameSong(newTitle: string): Promise<void> {
		if (!song) return;
		const songId = song.id;
		try {
			const updated = await renameSong(songId, newTitle);
			updateSongInList(songId, () => updated);
			addToast('Song renamed', 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Rename failed'), 'error');
			throw e;
		}
	}

	async function onSongShareEnable() {
		if (!song) throw new Error('No song');
		const songId = song.id;
		const result = await shareSong(songId);
		updateSongInList(songId, (s) => ({ ...s, is_shared: true, share_slug: result.share_slug }));
		return result;
	}

	async function onSongShareDisable() {
		if (!song) return;
		const songId = song.id;
		await unshareSong(songId);
		updateSongInList(songId, (s) => ({ ...s, is_shared: false, share_slug: null }));
	}

	async function onDeleteSong(): Promise<void> {
		if (!song) return;
		const songId = song.id;
		try {
			await deleteSong(songId);
			removeSongFromList(songId);
			backToCollection();
			addUndoToast('Song deleted', {
				label: 'Undo',
				handler: async () => {
					try {
						const restored = await restoreSong(songId);
						addSongsToList([restored]);
						addToast('Song restored', 'success');
					} catch (e) {
						addToast(describeFailure(e, 'Restore failed'), 'error');
					}
				}
			});
		} catch (e) {
			addToast(describeFailure(e, 'Delete failed'), 'error');
		}
	}

	async function onGenShareEnable(genId: string) {
		const result = await shareGeneration(genId);
		updateGenerationInList(genId, (g) => ({
			...g,
			is_shared: true,
			share_slug: result.share_slug
		}));
		return result;
	}

	async function onGenShareDisable(genId: string) {
		await unshareGeneration(genId);
		updateGenerationInList(genId, (g) => ({ ...g, is_shared: false, share_slug: null }));
	}

	async function onDeleteGeneration(genId: string): Promise<void> {
		if (!song) return;
		const selectedId = get(selectedGenerationId);
		try {
			await deleteGeneration(genId);
			removeGenerationFromSong(song.id, genId);
			if (selectedId === genId) {
				clearGenerationSelection();
				persistLibraryHistory();
			}
			addToast('Take deleted', 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Delete failed'), 'error');
		}
	}

	async function onAddSongToPlaylist(playlistId: string): Promise<void> {
		if (!song) return;
		try {
			await addSongToPlaylist(playlistId, song.id);
			addToast('Added to playlist', 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Failed to add'), 'error');
		}
	}

	let songPlaylistPickerOpen = $state(false);

	async function onSaveVersion(): Promise<void> {
		if (!song) return;
		try {
			await handleSave(song.id);
			const savedVersionNumber = get(versions)[0]?.version_number;
			addToast(`Saved version ${savedVersionNumber}`, 'success');
		} catch (e) {
			addToast(describeFailure(e, EDITOR_SAVE_FAILED), 'error');
		}
	}

	$effect(() => {
		if (!song) {
			phoneAppBar.set(null);
			return;
		}
		phoneAppBar.set({
			kind: 'song',
			title: song.title,
			onrename: onRenameSong,
			share: {
				isShared: song.is_shared,
				shareSlug: song.share_slug,
				onshare: onSongShareEnable,
				onunshare: onSongShareDisable
			},
			menu: {
				saveDisabled: !dirty,
				onsave: () => void onSaveVersion(),
				onaddtoplaylist: () => (songPlaylistPickerOpen = true),
				ondelete: () => (showDeleteConfirm = true)
			}
		});
		return () => phoneAppBar.set(null);
	});

	function onTurnCompleted(): void {
		if (!song) return;
		const songId = song.id;
		void fetchSong(songId).then((fresh) => {
			replaceSongInList(fresh);
			loadSongData(fresh);
		});
	}

	async function resolveDirtyNavigation(choice: 'save' | 'discard' | 'cancel'): Promise<void> {
		const action = get(pendingDirtyNavigation);
		pendingDirtyNavigation.set(null);
		if (choice === 'cancel') {
			pendingSource.set(null);
			pendingVersionLoad.set(null);
			return;
		}
		if (!action) return;
		if (choice === 'save') {
			if (!song) return;
			try {
				await handleSave(song.id);
			} catch (e) {
				addToast(describeFailure(e, EDITOR_SAVE_FAILED), 'error');
				pendingSource.set(null);
				pendingVersionLoad.set(null);
				return;
			}
		} else {
			discardDraft();
		}
		await action();
	}
</script>

{#if song && takeListProps}
	{#snippet saveAction()}
		<div class="write-save">
			<p class="write-save-hint" role="status">
				{#if dirty}{EDITOR_UNSAVED_TITLE}{/if}
			</p>
			<button
				type="button"
				class="save-btn"
				class:dirty
				data-hitbox="text"
				disabled={!dirty}
				aria-label={EDITOR_SAVE_ACCESSIBLE_LABEL}
				onclick={() => void onSaveVersion()}
			>
				{EDITOR_SAVE_LABEL}
			</button>
		</div>
	{/snippet}

	{#snippet writeSurface(current: SongItem, withCowriter: boolean, isCompact: boolean)}
		<div class="write-surface">
			{#if !compact}
				{@render saveAction()}
			{/if}
			<WriteColumn song={current} coWriterOpen={withCowriter} compact={isCompact} {cowriterPanel} />
		</div>
	{/snippet}

	{#snippet header()}
		<EditorHeader
			{song}
			{coverUrl}
			{coverFailed}
			{coverAlt}
			{artFill}
			{initials}
			{hasOwnCover}
			{coverBusy}
			{coverActionLabel}
			onrenamesong={onRenameSong}
			oncoverfile={onCoverFile}
			oncoverremove={onCoverRemove}
			oncovererror={() => (coverFailed = true)}
			{breadcrumbItems}
			{songRail}
			albumTitle={song.album_title}
			{albumSongCount}
			{albumCoverUrl}
			{albumArtFill}
			{albumInitials}
			previousDisabled={!neighbors.previous}
			nextDisabled={!neighbors.next}
			onselectprevious={() => neighbors.previous && selectNeighborSong(neighbors.previous)}
			onselectnext={() => neighbors.next && selectNeighborSong(neighbors.next)}
			isShared={song.is_shared}
			shareSlug={song.share_slug}
			onshare={onSongShareEnable}
			onunshare={onSongShareDisable}
			onaddtoplaylist={() => (songPlaylistPickerOpen = true)}
			ondeletesong={() => (showDeleteConfirm = true)}
			recipeOpen={$recipeOpen}
			coWriterOpen={$coWriterOpen}
			ontogglerecipe={() => recipeOpen.update((v) => !v)}
			ontogglecowriter={() => coWriterOpen.update((v) => !v)}
			saveDisabled={!dirty}
			onsave={() => void onSaveVersion()}
		/>
	{/snippet}

	{#snippet sharedLink()}
		{#if song.is_shared && song.share_slug}
			<ShareLinkChip url={`${window.location.origin}/share/song/${song.share_slug}`} />
		{/if}
	{/snippet}

	{#snippet recipe()}
		<RecipeChips {chips} open={$recipeOpen} onclick={() => recipeOpen.update((v) => !v)} />
		{#if $recipeOpen && !compact}
			{#if stacked && !stackedExpanded}
				<EditorStacked {chips} onexpand={() => (stackedExpanded = true)} />
			{:else}
				<RecipePanel
					onclose={() => {
						if (stacked) stackedExpanded = false;
						else recipeOpen.set(false);
					}}
				/>
			{/if}
		{/if}
	{/snippet}

	{#snippet phoneEdit()}
		{@render writeSurface(song, false, true)}
	{/snippet}

	{#snippet cowriterPanel()}
		<CoWriterPanel
			currentSongId={song.id}
			currentAlbumId={song.album_id}
			currentAlbumTitle={song.album_title}
			allSongs={songs}
			versions={$versions}
			onturncompleted={onTurnCompleted}
		/>
	{/snippet}

	<div
		class="detail-panel"
		class:compact
		class:grows-with-content={compact && $detailTab !== 'cowriter'}
	>
		{#if compact}
			<SongPhoneView
				{sharedLink}
				edit={phoneEdit}
				cowriter={cowriterPanel}
				{expiryDigest}
				{takeListProps}
				{chips}
			/>
		{:else}
			{@render header()}
			<div class="editor-body">
				{@render sharedLink()}
				{@render recipe()}
				{#if $coWriterOpen}
					{@render writeSurface(song, true, compact)}
				{:else}
					<div class="editor-columns">
						{@render writeSurface(song, false, compact)}
						<div class="takes-column">
							{@render expiryDigest()}
							<TakesList {...takeListProps} />
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	{#snippet expiryDigest()}
		{#if expiringSoon.count > 0}
			<div class="expiry-digest">
				<span class="expiry-digest-icon">⏳</span>
				<span>
					{expiringSoon.count} take{expiringSoon.count === 1 ? '' : 's'} expire{expiringSoon.count ===
					1
						? 's'
						: ''}
					{expiringSoon.minDays === 0
						? 'soon'
						: `in ${expiringSoon.minDays} day${expiringSoon.minDays === 1 ? '' : 's'}`} — pick or keep
					to preserve.
				</span>
			</div>
		{/if}
	{/snippet}

	{#if songPlaylistPickerOpen}
		<PlaylistPicker
			onselect={(playlistId) => {
				void onAddSongToPlaylist(playlistId);
				songPlaylistPickerOpen = false;
			}}
			onclose={() => (songPlaylistPickerOpen = false)}
		/>
	{/if}
{/if}

{#if $pendingDirtyNavigation}
	<ConfirmDialog
		title={EDITOR_UNSAVED_TITLE}
		message={EDITOR_UNSAVED_MESSAGE}
		confirmLabel={EDITOR_UNSAVED_SAVE_LABEL}
		onconfirm={() => void resolveDirtyNavigation('save')}
		secondaryLabel={EDITOR_UNSAVED_DISCARD_LABEL}
		onsecondary={() => void resolveDirtyNavigation('discard')}
		oncancel={() => void resolveDirtyNavigation('cancel')}
	/>
{/if}

{#if versionAwaitingReplace}
	<ConfirmDialog
		title={VERSION_REPLACE_DRAFT_TITLE}
		message={versionReplaceDraftMessage(versionAwaitingReplace.version.version_number)}
		confirmLabel={VERSION_REPLACE_DRAFT_CONFIRM_LABEL}
		onconfirm={() => answerVersionReplace(true)}
		oncancel={() => answerVersionReplace(false)}
	/>
{/if}

{#if $versionDeleteRequest}
	{@const request = $versionDeleteRequest}
	<ConfirmDeleteDialog
		title={versionDeleteTitle(request.version.version_number, request.takeCount)}
		items={request.holdsPick ? [VERSION_DELETE_PICK_WARNING] : []}
		confirmLabel={VERSION_DELETE_CONFIRM_LABEL}
		onconfirm={() => void confirmVersionDelete()}
		oncancel={() => versionDeleteRequest.set(null)}
	/>
{/if}

{#if showDeleteConfirm && song}
	<ConfirmDeleteDialog
		title={`Delete "${song.title}"?`}
		items={[
			`${song.generation_count} take${song.generation_count !== 1 ? 's' : ''}`,
			`${song.version_count} version${song.version_count !== 1 ? 's' : ''}`,
			'All scores, ratings, and chat history'
		]}
		confirmLabel="Delete Song"
		onconfirm={() => {
			showDeleteConfirm = false;
			onDeleteSong();
		}}
		oncancel={() => (showDeleteConfirm = false)}
	/>
{/if}

<style>
	.detail-panel {
		padding: 1.2rem 1.5rem calc(var(--player-height) + 1.2rem);
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		flex: 1;
		max-width: 1400px;
		width: 100%;
		min-width: 0;
		min-height: 0;
	}

	/* The phone's sticky Edit/Takes tabs can only stick inside this box, so
	   it must be as tall as the page it scrolls — shrunk to `main`'s height
	   they let go after one screen (#1017). The co-writer keeps the bounded
	   box: its message list scrolls inside it with the composer pinned. */
	.detail-panel.grows-with-content {
		flex: 1 0 auto;
	}

	/* Everything under the header answers to the width the editor actually
	   has — docking Now Playing takes NOW_PLAYING_DOCKED_WIDTH_PX out of
	   `main`, and these columns must fold for that exactly as they fold for a
	   smaller screen (#185). Named `editor`, so WriteColumn, RecipePanel and
	   the takes column can all ask the same question.

	   It deliberately starts below the header: a size container also becomes
	   the containing block for `position: fixed` descendants, and the header
	   carries two of them — the song menu's full-viewport backdrop and the
	   overlays — which would re-anchor to the editor.

	   The two-up floor is two 20rem columns plus the 1.2rem gap — 659.2px,
	   rounded up to a round 680. Below it the editor stacks, as it does in the
	   compact shell. */
	.editor-body {
		container: editor / inline-size;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
	}

	/* On a desktop shell the header stays put and everything under it scrolls
	   here: this fills the editor's height while the columns stand side by
	   side, each scrolling in place, and scrolls itself once they stack or the
	   Recipe panel grows taller than the room there is — so a take row is
	   always reachable rather than clipped. The compact shell keeps its own
	   rule: the whole panel scrolls in `main`, whose bottom padding is what
	   clears the sticky Generate bar. */
	.detail-panel:not(.compact) .editor-body {
		flex: 1;
		min-height: 0;
		overflow: hidden auto;
	}

	.write-surface {
		display: flex;
		flex-direction: column;
		flex: 1;
		gap: 0.6rem;
		min-width: 0;
		min-height: 0;
	}

	.write-save {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-width: 0;
	}

	.write-save-hint {
		margin: 0;
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.save-btn {
		padding: var(--btn-padding-pill);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		background: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
	}

	.save-btn.dirty {
		border-color: var(--primary);
		color: var(--primary);
		background: rgba(160, 32, 240, 0.08);
	}

	.save-btn:hover:not(:disabled) {
		border-color: var(--primary);
		color: var(--primary);
	}

	.save-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	/* One column by default, two where the editor has the room for two — never
	   a track with a floor of its own, which is what pushed a take row's
	   actions outside `main` (#185). */
	.editor-columns {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 1.2rem;
	}

	@container editor (min-width: 680px) {
		.editor-columns {
			grid-template-columns: repeat(2, minmax(0, 1fr));
			flex: 1;
			min-height: 0;
		}

		/* Only two-up does the column get a height of its own to scroll in;
		   stacked it runs on and `.editor-body` scrolls instead. */
		.takes-column {
			overflow-y: auto;
		}
	}

	.takes-column {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}

	.expiry-digest {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 0.8rem;
		background: rgba(220, 140, 20, 0.1);
		border: 1px solid rgba(220, 140, 20, 0.4);
		border-radius: 4px;
		font-size: 0.8rem;
		color: #d89040;
	}

	.expiry-digest-icon {
		font-size: 1rem;
	}

	@media (max-width: 768px) {
		.detail-panel {
			padding: var(--row-padding);
		}
	}
</style>
