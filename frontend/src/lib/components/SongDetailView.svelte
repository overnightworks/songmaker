<script lang="ts">
	import { get } from 'svelte/store';
	import {
		fetchSong,
		generateSong,
		renameSong,
		scoreGeneration,
		pickGeneration,
		unpickGeneration,
		deleteSong,
		restoreSong,
		shareSong,
		unshareSong,
		shareGeneration,
		unshareGeneration,
		deleteGeneration,
		rateGeneration,
		keepGeneration,
		unkeepGeneration,
		uploadSongCover,
		deleteSongCover
	} from '$lib/api/client';
	import { fetchAlbum } from '$lib/api/albums';
	import { refreshSharesAfterMutation } from '$lib/stores/shares';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import { health, startHealthPolling, stopHealthPolling } from '$lib/stores/health';
	import {
		selectedSong,
		selectedGeneration,
		selectedGenerationId,
		ensureGenerationsLoaded,
		albumList,
		songList,
		replaceSongInList,
		updateSongInList,
		updateGenerationInList,
		removeGenerationFromSong,
		removeSongFromList,
		addSongsToList,
		addAlbumToList
	} from '$lib/stores/player';
	import {
		albumTrackNeighbors,
		backToCollection,
		compareAlbumTracks,
		selectGeneration,
		navigateToSongTab,
		openCollectionEntry,
		openLibraryWall,
		clearGenerationSelection,
		persistLibraryHistory,
		detailTab,
		selectNeighborSong,
		switchTab
	} from '$lib/stores/navigation';
	import { openCollection } from '$lib/stores/collection';
	import {
		isDirty,
		versions,
		currentVersionIndex,
		loadSongData,
		loadVersion,
		handleSave,
		pinnedSeed
	} from '$lib/stores/editor';
	import { activeModels, loadActiveModels } from '$lib/stores/presets';
	import { loras } from '$lib/stores/loras';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addGenerationToPlaylist, addSongToPlaylist } from '$lib/stores/playlists';
	import {
		applyAgainFromGeneration,
		coWriterOpen,
		coverNoiseStrength,
		coverStrength,
		pendingSource,
		recipeChips,
		recipeModel,
		recipeOpen,
		repaintEnd,
		repaintMode,
		repaintStart,
		repaintStrength,
		resetRecipeSourceForSong,
		seedRecipeModel,
		setSourceFromGeneration,
		sourceGeneration,
		sourceMode,
		takesPerGenerate
	} from '$lib/stores/recipe';
	import { setGenerationActions } from '$lib/contexts/generation-actions';
	import type { GenerationItem } from '$lib/api/types';
	import {
		EXPIRY_WARN_DAYS,
		LIBRARY_NARROW_MEDIA,
		RAIL_LIBRARY_LABEL,
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_COVER_ALT_TYPE,
		SONG_COVER_ALT_TYPE,
		SONG_COVER_REPLACE_LABEL,
		SONG_COVER_UPLOAD_LABEL,
		EDITOR_GENERATE_LABEL,
		EDITOR_GENERATING_LABEL,
		EDITOR_MISSING_CONTENT_TITLE,
		EDITOR_NO_MODELS_WARNING,
		EDITOR_QUEUED_LABEL,
		EDITOR_QUEUE_BUSY_TITLE,
		EDITOR_SELECT_MODEL_TITLE,
		EDITOR_TAB_TAKES_LABEL,
		EDITOR_TAB_WRITE_LABEL,
		EDITOR_TABS_LABEL,
		TAKES_ERROR
	} from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import EditorHeader from './editor/EditorHeader.svelte';
	import RecipeChips from './editor/RecipeChips.svelte';
	import RecipePanel from './editor/RecipePanel.svelte';
	import WriteColumn from './editor/WriteColumn.svelte';
	import TakesList from './editor/TakesList.svelte';
	import EditorSheet from './editor/EditorSheet.svelte';
	import GenerationView from './GenerationView.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	let showDeleteConfirm = $state(false);
	let compact = $state(false);
	let songRail = $state(false);
	let takesStatus = $state<'loading' | 'ready' | 'error'>('ready');
	let takesError = $state<string | null>(null);
	let coverFailed = $state(false);
	let coverBusy = $state(false);
	let requestedParentAlbumId: string | null = $state(null);

	const song = $derived($selectedSong);
	const inspected = $derived($selectedGeneration);
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
	const jobs = $derived($activeJobs);
	const tab = $derived($detailTab);
	const dirty = $derived($isDirty);
	const draftVersionNumber = $derived(song ? song.version_count + 1 : 1);

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
			addToast(e instanceof Error ? e.message : 'Cover upload failed', 'error');
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
			addToast(e instanceof Error ? e.message : 'Cover remove failed', 'error');
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
		if (!pending) return;
		setSourceFromGeneration(pending.generation, pending.mode);
		pendingSource.set(null);
	});

	const songJobs = $derived(song ? jobs.filter((j) => j.songId === song.id) : []);
	const generateJob = $derived(songJobs.find((j) => j.job.type === 'generate')?.job ?? null);
	const isGenerating = $derived(
		generateJob !== null && (generateJob.status === 'running' || generateJob.status === 'queued')
	);
	const queueDepthCapReached = $derived($health?.queue_depth_cap_reached ?? false);

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
			bpm: song?.bpm ?? 0,
			audioDuration: song?.audio_duration ?? 0,
			keyScale: song?.key_scale ?? '',
			voiceLabel: resolveVoiceLabel(song?.generation_params?.user_lora_id ?? null),
			pinnedSeed: $pinnedSeed,
			genParams: song?.generation_params ?? null,
			sourceGeneration: $sourceGeneration,
			sourceMode: $sourceMode,
			repaintMode: $repaintMode
		})
	);

	function resolveVoiceLabel(loraId: string | null): string {
		if (!loraId) return 'None';
		return $loras.find((l) => l.id === loraId)?.name ?? 'Custom';
	}

	setGenerationActions({
		score: onScore,
		pick: onPick,
		keep: onKeep,
		del: onDeleteGeneration,
		rate: onRate,
		share: onGenShareEnable,
		unshare: onGenShareDisable,
		addToPlaylist: async (playlistId, genId) => {
			await addGenerationToPlaylist(playlistId, genId);
			addToast('Added to playlist', 'success');
		},
		pinSeed: (seed) => {
			pinnedSeed.set(seed);
			addToast(`Seed ${seed} pinned for next generation`, 'success');
		},
		clickVersion: onVersionClick,
		useAsSource: (gen) => setSourceFromGeneration(gen, 'repaint')
	});

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
			takesStatus = 'error';
			takesError = e instanceof Error ? e.message : TAKES_ERROR;
		}
	}

	function applyAgain(gen: GenerationItem): void {
		applyAgainFromGeneration(gen);
	}

	function closeInspector(): void {
		clearGenerationSelection();
		persistLibraryHistory();
	}

	function onInspectorKeydown(event: KeyboardEvent): void {
		if (!inspected) return;
		if (event.key !== 'Escape') return;
		event.preventDefault();
		closeInspector();
	}

	async function onGenerate(): Promise<void> {
		if (!song || $recipeModel === null) return;
		const model: string = $recipeModel;
		try {
			if (dirty) {
				await handleSave(song.id);
			}
			const ver = $versions[$currentVersionIndex];
			const versionId = ver?.id;

			const seedToUse = $pinnedSeed;
			const source = $sourceGeneration;
			if (source && $sourceMode === 'repaint') {
				const { repaintGeneration } = await import('$lib/api/client');
				const job = await repaintGeneration(source.id, $repaintStart, $repaintEnd, {
					model,
					seed: seedToUse,
					versionId,
					count: $takesPerGenerate,
					repaintMode: $repaintMode,
					repaintStrength: $repaintMode === 'balanced' ? $repaintStrength : undefined
				});
				pinnedSeed.set(null);
				trackJob(job, { songId: song.id });
			} else if (source && $sourceMode === 'cover') {
				const { coverGeneration } = await import('$lib/api/client');
				const job = await coverGeneration(source.id, $coverStrength, {
					model,
					seed: seedToUse,
					versionId,
					count: $takesPerGenerate,
					coverNoiseStrength: $coverNoiseStrength > 0 ? $coverNoiseStrength : undefined
				});
				pinnedSeed.set(null);
				trackJob(job, { songId: song.id });
			} else {
				const job = await generateSong(song.id, $takesPerGenerate, model, versionId, seedToUse);
				pinnedSeed.set(null);
				trackJob(job, { songId: song.id });
			}
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Generation failed', 'error');
		}
	}

	async function onPick(genId: string, picked: boolean): Promise<void> {
		if (!song) return;
		try {
			if (picked) await pickGeneration(genId);
			else await unpickGeneration(genId);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Pick failed', 'error');
		}
	}

	async function onKeep(genId: string, kept: boolean): Promise<void> {
		if (!song) return;
		try {
			if (kept) await keepGeneration(genId);
			else await unkeepGeneration(genId);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Keep failed', 'error');
		}
	}

	async function onRate(genId: string, rating: number, notes: string): Promise<void> {
		if (!song) return;
		try {
			await rateGeneration(genId, rating, notes);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
			addToast('Rating saved', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Rating failed', 'error');
		}
	}

	async function onScore(genId: string): Promise<void> {
		if (!song) return;
		try {
			const job = await scoreGeneration(genId);
			trackJob(job, { songId: song.id, genId });
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Scoring failed', 'error');
		}
	}

	function onVersionClick(versionId: string): void {
		const idx = $versions.findIndex((v) => v.id === versionId);
		if (idx !== -1) loadVersion(idx);
		navigateToSongTab('write');
	}

	async function onRenameSong(newTitle: string): Promise<void> {
		if (!song) return;
		const songId = song.id;
		try {
			const updated = await renameSong(songId, newTitle);
			updateSongInList(songId, () => updated);
			addToast('Song renamed', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Rename failed', 'error');
			throw e;
		}
	}

	async function onSongShareEnable() {
		if (!song) throw new Error('No song');
		const songId = song.id;
		const result = await shareSong(songId);
		updateSongInList(songId, (s) => ({ ...s, is_shared: true, share_slug: result.share_slug }));
		await refreshSharesAfterMutation();
		return result;
	}

	async function onSongShareDisable() {
		if (!song) return;
		const songId = song.id;
		await unshareSong(songId);
		updateSongInList(songId, (s) => ({ ...s, is_shared: false, share_slug: null }));
		await refreshSharesAfterMutation();
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
					} catch {
						addToast('Restore failed', 'error');
					}
				}
			});
		} catch {
			addToast('Delete failed', 'error');
		}
	}

	async function onGenShareEnable(genId: string) {
		const result = await shareGeneration(genId);
		updateGenerationInList(genId, (g) => ({
			...g,
			is_shared: true,
			share_slug: result.share_slug
		}));
		await refreshSharesAfterMutation();
		return result;
	}

	async function onGenShareDisable(genId: string) {
		await unshareGeneration(genId);
		updateGenerationInList(genId, (g) => ({ ...g, is_shared: false, share_slug: null }));
		await refreshSharesAfterMutation();
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
			addToast(e instanceof Error ? e.message : 'Delete failed', 'error');
		}
	}

	async function onAddSongToPlaylist(playlistId: string): Promise<void> {
		if (!song) return;
		try {
			await addSongToPlaylist(playlistId, song.id);
			addToast('Added to playlist', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		}
	}

	let songPlaylistPickerOpen = $state(false);

	function generateTitle(): string {
		if (!song?.lyrics || !song?.prompt) return EDITOR_MISSING_CONTENT_TITLE;
		if ($recipeModel === null) {
			return $activeModels.length === 0 ? EDITOR_NO_MODELS_WARNING : EDITOR_SELECT_MODEL_TITLE;
		}
		return queueDepthCapReached ? EDITOR_QUEUE_BUSY_TITLE : '';
	}

	function generateLabel(): string {
		if (isGenerating && generateJob?.status === 'queued') {
			return generateJob.queue_position
				? `${EDITOR_QUEUED_LABEL} (#${generateJob.queue_position})`
				: EDITOR_QUEUED_LABEL;
		}
		return isGenerating ? EDITOR_GENERATING_LABEL : EDITOR_GENERATE_LABEL;
	}
</script>

<svelte:window onkeydown={onInspectorKeydown} />

{#if song}
	<div class="detail-panel">
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
			ongenerate={onGenerate}
			generateLabel={generateLabel()}
			generateDisabled={isGenerating || !song.lyrics || !song.prompt || $recipeModel === null}
			generateTitle={generateTitle()}
			generating={isGenerating}
			{compact}
		/>

		{#if song.is_shared && song.share_slug}
			<button
				type="button"
				class="share-link"
				onclick={() => {
					const url = `${window.location.origin}/share/song/${song.share_slug}`;
					navigator.clipboard.writeText(url);
					addToast('Link copied', 'success');
				}}
				title="Click to copy share link"
			>
				{window.location.origin}/share/song/{song.share_slug}
			</button>
		{/if}

		<RecipeChips {chips} open={$recipeOpen} onclick={() => recipeOpen.update((v) => !v)} />
		{#if $recipeOpen && !compact}
			<RecipePanel onclose={() => recipeOpen.set(false)} />
		{/if}

		{#if $coWriterOpen}
			<WriteColumn
				{song}
				allSongs={songs}
				coWriterOpen={true}
				{compact}
				onselecttake={(genId) => {
					const gen = song.generations.find((g) => g.id === genId);
					if (gen) selectGeneration(gen, song);
				}}
				onturncompleted={() => {
					void fetchSong(song.id).then((fresh) => {
						replaceSongInList(fresh);
						loadSongData(fresh);
					});
				}}
			/>
		{:else if compact}
			<div class="editor-tabs" role="tablist" aria-label={EDITOR_TABS_LABEL}>
				<button
					type="button"
					class="tab-btn"
					role="tab"
					aria-selected={tab === 'write'}
					class:active={tab === 'write'}
					onclick={() => switchTab('write')}
				>
					{EDITOR_TAB_WRITE_LABEL}
				</button>
				<button
					type="button"
					class="tab-btn"
					role="tab"
					aria-selected={tab === 'takes'}
					class:active={tab === 'takes'}
					onclick={() => switchTab('takes')}
				>
					{EDITOR_TAB_TAKES_LABEL} · {song.generations.length}
				</button>
			</div>
			{#if tab === 'write'}
				<WriteColumn
					{song}
					allSongs={songs}
					coWriterOpen={false}
					{compact}
					onselecttake={() => {}}
					onturncompleted={() => {}}
				/>
			{:else}
				{@render expiryDigest()}
				<TakesList
					{song}
					selectedId={inspected?.id ?? null}
					loadStatus={takesStatus}
					loadError={takesError}
					{dirty}
					{draftVersionNumber}
					{generateJob}
					compact
					onselect={(gen) => selectGeneration(gen, song)}
					onagain={applyAgain}
					onuseasreference={(gen) => setSourceFromGeneration(gen, 'repaint')}
					onretry={() => {
						if (song) void refreshTakes(song.id);
					}}
				/>
			{/if}
		{:else}
			<div class="editor-columns">
				<WriteColumn
					{song}
					allSongs={songs}
					coWriterOpen={false}
					{compact}
					onselecttake={() => {}}
					onturncompleted={() => {}}
				/>
				<div class="takes-column">
					{@render expiryDigest()}
					<TakesList
						{song}
						selectedId={inspected?.id ?? null}
						loadStatus={takesStatus}
						loadError={takesError}
						{dirty}
						{draftVersionNumber}
						{generateJob}
						onselect={(gen) => selectGeneration(gen, song)}
						onagain={applyAgain}
						onuseasreference={(gen) => setSourceFromGeneration(gen, 'repaint')}
						onretry={() => {
							if (song) void refreshTakes(song.id);
						}}
					/>
				</div>
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
		{#await import('./PlaylistPicker.svelte') then { default: PlaylistPicker }}
			<PlaylistPicker
				onselect={(playlistId) => {
					void onAddSongToPlaylist(playlistId);
					songPlaylistPickerOpen = false;
				}}
				onclose={() => (songPlaylistPickerOpen = false)}
			/>
		{/await}
	{/if}

	{#if compact}
		<EditorSheet open={$recipeOpen} label="Recipe" onclose={() => recipeOpen.set(false)}>
			<RecipePanel onclose={() => recipeOpen.set(false)} />
		</EditorSheet>
	{/if}

	{#if inspected}
		<div class="inspector-modal">
			<button class="inspector-backdrop" tabindex="-1" onclick={closeInspector} aria-label="Close"
			></button>
			<div
				class="inspector-sheet"
				role="dialog"
				aria-modal="true"
				aria-label="Take details"
				tabindex="-1"
			>
				<GenerationView onclose={closeInspector} />
			</div>
		</div>
	{/if}
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

	.share-link {
		font-size: 0.75rem;
		color: var(--text-subtle);
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 0.3rem 0.6rem;
		cursor: pointer;
		word-break: break-all;
		text-align: left;
		align-self: flex-start;
	}

	.share-link:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.editor-tabs {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--border);
	}

	.tab-btn {
		padding: 0.55rem 1.1rem;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.87rem;
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
		cursor: pointer;
	}

	.tab-btn:hover {
		color: var(--text);
	}

	.tab-btn.active {
		color: var(--primary);
		border-bottom: 2px solid var(--primary);
	}

	.editor-columns {
		display: grid;
		grid-template-columns: minmax(320px, 1fr) minmax(360px, 1fr);
		gap: 1.2rem;
		flex: 1;
		min-height: 0;
	}

	.takes-column {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
		overflow-y: auto;
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

	.inspector-modal {
		position: fixed;
		inset: 0;
		z-index: 200;
	}

	.inspector-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: color-mix(in srgb, #000 50%, transparent);
		cursor: default;
	}

	.inspector-sheet {
		position: absolute;
		top: 5vh;
		left: 50%;
		transform: translateX(-50%);
		width: min(720px, 92vw);
		max-height: 90vh;
		overflow-y: auto;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		padding: 0.8rem 1.2rem 1.2rem;
		box-shadow: 0 12px 48px rgba(0, 0, 0, 0.4);
	}

	@media (max-width: 900px) {
		.editor-columns {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 768px) {
		.detail-panel {
			padding: 0.8rem 0.8rem calc(var(--player-height) + 0.8rem);
		}
	}
</style>
