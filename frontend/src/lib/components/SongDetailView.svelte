<script lang="ts">
	import { tick } from 'svelte';
	import { get } from 'svelte/store';
	import {
		cancelJob,
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
	import { activeJobs, trackJob, removeJob } from '$lib/stores/jobs';
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
		openRecipeSurface,
		openTakesSurface,
		selectNeighborSong
	} from '$lib/stores/navigation';
	import { openCollection } from '$lib/stores/collection';
	import {
		isDirty,
		versions,
		currentVersionIndex,
		saving,
		status,
		pinnedSeed,
		loadSongData,
		loadVersion,
		handleSave,
		handleDeleteVersion,
		applyGenerationSettings
	} from '$lib/stores/editor';
	import { activeModels } from '$lib/stores/presets';
	import { addToast, addUndoToast } from '$lib/stores/toast';
	import { addGenerationToPlaylist, addSongToPlaylist } from '$lib/stores/playlists';
	import { pendingSource, recipeParamsFromTake, type SourceMode } from '$lib/stores/source';
	import { setGenerationActions } from '$lib/contexts/generation-actions';
	import type { GenerationItem } from '$lib/api/types';
	import {
		EXPIRY_WARN_DAYS,
		LIBRARY_NARROW_MEDIA,
		RAIL_LIBRARY_LABEL,
		SONG_NEXT_LABEL,
		SONG_PREVIOUS_LABEL,
		SONG_SPLIT_PANE_GAP_PX,
		SONG_SPLIT_PANE_MIN_PX,
		SONG_SURFACE_COWRITER,
		SONG_SURFACE_RECIPE,
		SONG_SURFACE_SWITCH_LABEL,
		SONG_SURFACE_TAKES,
		ALBUM_ART_EMPTY_INITIALS,
		ALBUM_COVER_ACCEPT,
		ALBUM_COVER_ALT_TYPE,
		SONG_COVER_ALT_TYPE,
		SONG_COVER_REMOVE_LABEL,
		SONG_COVER_REPLACE_LABEL,
		SONG_COVER_UPLOAD_LABEL,
		TAKE_AUDIO_COVER_LABEL,
		TAKE_REPAINT_LABEL,
		TAKES_ERROR,
		canSplitSongPanes
	} from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import Breadcrumb from './Breadcrumb.svelte';
	import GenerationsList from './GenerationsList.svelte';
	import GenerationView from './GenerationView.svelte';
	import SongEditor from './SongEditor.svelte';
	import CoWriterPanel from './CoWriterPanel.svelte';
	import ActionButton from './ActionButton.svelte';
	import Icon from './Icon.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	const COWRITER_FOCUSABLE =
		'a[href], button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])';

	let genCount = $state(1);
	let selectedModel = $state<string | null>(null);
	let showDeleteConfirm = $state(false);
	let sourceGeneration = $state<GenerationItem | null>(null);
	let sourceMode = $state<SourceMode>('repaint');
	let repaintStart = $state(0);
	let repaintEnd = $state(1);
	let coverStrength = $state(0.7);
	let repaintMode = $state<string>('');
	let repaintStrength = $state(0.5);
	let coverNoiseStrength = $state(0);
	let playlistPickerFor = $state<
		{ type: 'song'; id: string } | { type: 'generation'; id: string } | null
	>(null);
	let coWriterOpen = $state(false);
	let compact = $state(false);
	let songRail = $state(false);
	let split = $state(false);
	let panesEl: HTMLElement | undefined = $state();
	let recipePaneEl: HTMLElement | undefined = $state();
	let coWriterPanelEl: HTMLDivElement | undefined = $state();
	let coWriterTrigger: HTMLButtonElement | undefined = $state();
	let recipeScrollTop = 0;
	let takesStatus = $state<'loading' | 'ready' | 'error'>('ready');
	let takesError = $state<string | null>(null);
	let coverFailed = $state(false);
	let coverBusy = $state(false);
	let coverInput: HTMLInputElement | null = $state(null);
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
	const recipe = $derived(tab !== 'generations');
	const dirty = $derived($isDirty);
	const isSaving = $derived($saving);
	const statusMsg = $derived($status);
	const cowriterShowing = $derived(coWriterOpen && (split || recipe));
	const cowriterModal = $derived(cowriterShowing && !split);

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
			coWriterOpen = false;
			loadSongData(current);
			void refreshTakes(current.id);
			return;
		}
		void ensureGenerationsLoaded(current.id);
	});

	$effect(() => {
		const pending = $pendingSource;
		if (!pending) return;
		applySource(pending.generation, pending.mode);
		pendingSource.set(null);
	});

	const songJobs = $derived(song ? jobs.filter((j) => j.songId === song.id) : []);
	const isGenerating = $derived(
		songJobs.some(
			(j) => j.job.type === 'generate' && (j.job.status === 'running' || j.job.status === 'queued')
		)
	);
	const activeGenerateJob = $derived(songJobs.find((j) => j.job.type === 'generate')?.job ?? null);
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
		if (selectedModel === null && $activeModels.length > 0) {
			selectedModel = $activeModels[0].id;
		}
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

	$effect(() => {
		const el = panesEl;
		const isCompact = compact;
		if (!el || isCompact || typeof ResizeObserver === 'undefined') {
			split = false;
			return;
		}
		const syncSplit = () => {
			split = canSplitSongPanes(el.getBoundingClientRect().width);
		};
		syncSplit();
		const observer = new ResizeObserver(() => {
			syncSplit();
		});
		observer.observe(el);
		return () => observer.disconnect();
	});

	$effect(() => {
		if (!split && !recipe) {
			coWriterOpen = false;
		}
	});

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
		useAsSource: (gen) => applySource(gen, 'repaint')
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

	function applySource(gen: GenerationItem, mode: SourceMode): void {
		sourceGeneration = gen;
		sourceMode = mode;
		if (mode === 'repaint') {
			repaintStart = 0;
			repaintEnd = 1;
		}
		openRecipeSurface();
	}

	function applyAgain(gen: GenerationItem): void {
		sourceGeneration = null;
		const takeRecipeParams = recipeParamsFromTake(gen.generation_params);
		if (Object.keys(takeRecipeParams).length > 0) {
			applyGenerationSettings(takeRecipeParams);
		}
		if (gen.seed != null && gen.seed >= 0) pinnedSeed.set(gen.seed);
		openRecipeSurface();
	}

	function closeInspector(): void {
		clearGenerationSelection();
		persistLibraryHistory();
	}

	function openCoWriter(): void {
		recipeScrollTop = recipePaneEl?.scrollTop ?? 0;
		coWriterOpen = true;
	}

	function closeCoWriter(): void {
		if (!coWriterOpen) return;
		coWriterOpen = false;
		void tick().then(() => {
			if (recipePaneEl) recipePaneEl.scrollTop = recipeScrollTop;
			coWriterTrigger?.focus();
		});
	}

	$effect(() => {
		if (!cowriterShowing) return;
		void tick().then(() => {
			const first = coWriterPanelEl?.querySelector<HTMLElement>(COWRITER_FOCUSABLE);
			(first ?? coWriterPanelEl)?.focus();
		});
	});

	function onCoWriterKeydown(event: KeyboardEvent): void {
		if (!cowriterShowing || !coWriterPanelEl) return;
		if (event.key === 'Escape') {
			if (event.defaultPrevented) return;
			event.preventDefault();
			closeCoWriter();
			return;
		}
		if (!cowriterModal || event.key !== 'Tab') return;
		const focusable = Array.from(coWriterPanelEl.querySelectorAll<HTMLElement>(COWRITER_FOCUSABLE));
		if (focusable.length === 0) {
			event.preventDefault();
			coWriterPanelEl.focus();
			return;
		}
		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		const active = document.activeElement;
		if (
			event.shiftKey &&
			(active === first || active === coWriterPanelEl || !coWriterPanelEl.contains(active))
		) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && (active === last || !coWriterPanelEl.contains(active))) {
			event.preventDefault();
			first.focus();
		}
	}

	function onSave(): void {
		if (song) handleSave(song.id);
	}

	function onDeleteVersion(versionId: string, deleteGenerations: boolean): void {
		if (song) handleDeleteVersion(song.id, versionId, deleteGenerations);
	}

	async function onGenerate(): Promise<void> {
		if (!song || selectedModel === null) return;
		const model: string = selectedModel;
		try {
			if (dirty) {
				await handleSave(song.id);
			}
			const ver = $versions[$currentVersionIndex];
			const versionId = ver?.id;

			const seedToUse = $pinnedSeed;
			if (sourceGeneration && sourceMode === 'repaint') {
				const { repaintGeneration } = await import('$lib/api/client');
				const job = await repaintGeneration(sourceGeneration.id, repaintStart, repaintEnd, {
					model,
					seed: seedToUse,
					versionId,
					count: genCount,
					repaintMode: repaintMode || undefined,
					repaintStrength: repaintMode === 'balanced' ? repaintStrength : undefined
				});
				pinnedSeed.set(null);
				trackJob(job, { songId: song.id });
			} else if (sourceGeneration && sourceMode === 'cover') {
				const { coverGeneration } = await import('$lib/api/client');
				const job = await coverGeneration(sourceGeneration.id, coverStrength, {
					model,
					seed: seedToUse,
					versionId,
					count: genCount,
					coverNoiseStrength: coverNoiseStrength > 0 ? coverNoiseStrength : undefined
				});
				pinnedSeed.set(null);
				trackJob(job, { songId: song.id });
			} else {
				const job = await generateSong(song.id, genCount, model, versionId, seedToUse);
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
		navigateToSongTab('edit');
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

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!playlistPickerFor) return;
		try {
			if (playlistPickerFor.type === 'generation') {
				await addGenerationToPlaylist(playlistId, playlistPickerFor.id);
			}
			if (playlistPickerFor.type === 'song') {
				await addSongToPlaylist(playlistId, playlistPickerFor.id);
			}
			addToast('Added to playlist', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		} finally {
			playlistPickerFor = null;
		}
	}
</script>

<svelte:window onkeydown={onCoWriterKeydown} />

{#if song}
	<div
		class="detail-panel"
		class:split
		style:--song-split-pane-min="{SONG_SPLIT_PANE_MIN_PX}px"
		style:--song-split-gap="{SONG_SPLIT_PANE_GAP_PX}px"
	>
		<div class="detail-header">
			<div class="detail-identity">
				<div class="cover-hero">
					{#if coverUrl && !coverFailed}
						<img src={coverUrl} alt={coverAlt} onerror={() => (coverFailed = true)} />
					{:else if artFill}
						<span class="cover-fallback" style:background={artFill} aria-hidden="true"></span>
					{:else}
						<span class="cover-fallback cover-initials" aria-hidden="true">{initials}</span>
					{/if}
					<input
						bind:this={coverInput}
						class="cover-file-input"
						type="file"
						accept={ALBUM_COVER_ACCEPT}
						onchange={onCoverFile}
					/>
					<button
						type="button"
						class="cover-hit"
						onclick={() => coverInput?.click()}
						disabled={coverBusy}
						aria-label={coverActionLabel}
					></button>
					{#if hasOwnCover}
						<button
							type="button"
							class="cover-remove"
							onclick={onCoverRemove}
							disabled={coverBusy}
							aria-label={SONG_COVER_REMOVE_LABEL}
						>
							×
						</button>
					{/if}
				</div>
				<div class="song-heading">
					<h2 class="song-title">
						<EditableTitle value={song.title} onsave={onRenameSong} ariaLabel="Song title" />
					</h2>
					{#if songRail}
						<div class="song-rail">
							<button
								type="button"
								class="song-neighbor"
								data-hitbox="frequent"
								data-hitbox-face
								aria-label={SONG_PREVIOUS_LABEL}
								disabled={!neighbors.previous}
								onclick={() => neighbors.previous && selectNeighborSong(neighbors.previous)}
							>
								<Icon name="skip-back" size={14} />
							</button>
							<Breadcrumb items={breadcrumbItems} />
							<button
								type="button"
								class="song-neighbor"
								data-hitbox="frequent"
								data-hitbox-face
								aria-label={SONG_NEXT_LABEL}
								disabled={!neighbors.next}
								onclick={() => neighbors.next && selectNeighborSong(neighbors.next)}
							>
								<Icon name="skip-forward" size={14} />
							</button>
						</div>
					{:else}
						<Breadcrumb items={breadcrumbItems} />
					{/if}
				</div>
			</div>
			<div class="detail-actions">
				<ShareButton
					isShared={song.is_shared}
					shareSlug={song.share_slug}
					onshare={onSongShareEnable}
					onunshare={onSongShareDisable}
				/>
				<div class="picker-anchor">
					<ActionButton
						icon="list-plus"
						label="Add to Playlist"
						onclick={() => (playlistPickerFor = { type: 'song', id: song.id })}
					/>
					{#if playlistPickerFor?.type === 'song' && playlistPickerFor.id === song.id}
						<PlaylistPicker onselect={onAddToPlaylist} onclose={() => (playlistPickerFor = null)} />
					{/if}
				</div>
				<ActionButton
					icon="trash"
					label="Delete Song"
					destructive
					onclick={() => (showDeleteConfirm = true)}
				/>
				{#each songJobs as j (j.job.id)}
					{#if j.job.status === 'queued' || j.job.status === 'running'}
						<span class="job-indicator">
							<span class="job-progress-bar">
								<span class="job-progress-fill" style="width: {Math.round(j.job.progress * 100)}%"
								></span>
							</span>
							<span class="job-progress-label">
								{j.job.type}
								{j.job.status === 'queued' ? 'queued' : `${Math.round(j.job.progress * 100)}%`}
							</span>
							<button
								type="button"
								class="job-cancel"
								onclick={() =>
									cancelJob(j.job.id)
										.then(() => removeJob(j.job.id))
										.catch(() => {})}
								title="Cancel job">×</button
							>
						</span>
					{/if}
				{/each}
				{#if statusMsg}
					<span class="status-msg">{statusMsg}</span>
				{/if}
			</div>
		</div>

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

		{#if !split}
			<div class="surface-switch" role="tablist" aria-label={SONG_SURFACE_SWITCH_LABEL}>
				<button
					type="button"
					class="tab-btn"
					role="tab"
					aria-selected={recipe}
					class:active={recipe}
					onclick={() => openRecipeSurface()}
				>
					{SONG_SURFACE_RECIPE}
				</button>
				<button
					type="button"
					class="tab-btn"
					role="tab"
					aria-selected={!recipe}
					class:active={!recipe}
					onclick={() => openTakesSurface()}
				>
					{SONG_SURFACE_TAKES}
				</button>
			</div>
		{/if}

		<div class="panes" bind:this={panesEl}>
			<section
				class="recipe-pane"
				class:hidden={!split && !recipe}
				bind:this={recipePaneEl}
				aria-label={SONG_SURFACE_RECIPE}
			>
				{#if split}
					<h3 class="pane-title">{SONG_SURFACE_RECIPE}</h3>
				{/if}
				<div class="recipe-toolbar">
					{#if dirty}
						<button type="button" class="save-btn" onclick={onSave} disabled={isSaving}>
							{isSaving ? 'Saving...' : 'Save'}
						</button>
					{/if}
					<button
						type="button"
						class="generate-btn"
						class:generating={isGenerating}
						onclick={onGenerate}
						disabled={isGenerating || !song?.lyrics || !song?.prompt || selectedModel === null}
						title={!song?.lyrics || !song?.prompt
							? 'Add lyrics and style prompt first'
							: selectedModel === null
								? $activeModels.length === 0
									? 'No models enabled. Ask admin to enable one.'
									: 'Select a model first'
								: queueDepthCapReached
									? 'System busy — submit may be rejected'
									: ''}
					>
						{#if isGenerating && activeGenerateJob?.status === 'queued'}
							{activeGenerateJob.queue_position
								? `Queued (#${activeGenerateJob.queue_position})`
								: 'Queued...'}
						{:else if sourceGeneration}
							{isGenerating
								? 'Generating...'
								: sourceMode === 'repaint'
									? TAKE_REPAINT_LABEL
									: TAKE_AUDIO_COVER_LABEL}
						{:else}
							{isGenerating ? 'Generating...' : 'Generate'}
						{/if}
					</button>
					<select class="gen-count-select" bind:value={genCount}>
						{#each [1, 2, 3, 5, 10] as n (n)}
							<option value={n}>×{n}</option>
						{/each}
					</select>
					{#if $activeModels.length > 1}
						<select class="model-select" bind:value={selectedModel}>
							{#each $activeModels as m (m.id)}
								<option value={m.id}>{m.id.toUpperCase()}</option>
							{/each}
						</select>
					{/if}
					{#if $activeModels.length === 0}
						<span class="no-models-warning" data-testid="no-models-warning">
							No models enabled. Ask admin to enable one.
						</span>
					{/if}
					{#if $pinnedSeed != null}
						<button
							type="button"
							class="pinned-seed"
							onclick={() => pinnedSeed.set(null)}
							title="Click to clear pinned seed"
						>
							seed:{$pinnedSeed} ✕
						</button>
					{/if}
					<button
						type="button"
						class="cowriter-open"
						bind:this={coWriterTrigger}
						aria-expanded={cowriterShowing}
						onclick={openCoWriter}
					>
						{SONG_SURFACE_COWRITER}
					</button>
				</div>
				<SongEditor
					ondeleteversion={onDeleteVersion}
					{selectedModel}
					{song}
					{sourceGeneration}
					{sourceMode}
					{repaintStart}
					{repaintEnd}
					{coverStrength}
					{repaintMode}
					{repaintStrength}
					{coverNoiseStrength}
					onrepaintrangechange={(s, e) => {
						repaintStart = s;
						repaintEnd = e;
					}}
					oncoverstrengthchange={(s) => (coverStrength = s)}
					onrepaintmodechange={(m) => (repaintMode = m)}
					onrepaintstrengthchange={(s) => (repaintStrength = s)}
					oncovernoisestrengthchange={(s) => (coverNoiseStrength = s)}
					onsourcemodechange={(m) => (sourceMode = m)}
					onsourceclear={() => (sourceGeneration = null)}
					onsourceselect={(gen) => applySource(gen, 'repaint')}
				/>
				<div class="cowriter-layer" class:open={cowriterShowing} class:compact>
					{#if compact}
						<button
							type="button"
							class="cowriter-backdrop"
							tabindex="-1"
							onclick={closeCoWriter}
							aria-label="Close"
						></button>
					{/if}
					<div
						class="cowriter-sheet"
						bind:this={coWriterPanelEl}
						role="dialog"
						aria-modal={cowriterModal}
						aria-label={SONG_SURFACE_COWRITER}
						tabindex="-1"
					>
						<CoWriterPanel
							currentSongId={song?.id ?? ''}
							currentAlbumId={song?.album_id ?? ''}
							currentAlbumTitle={song?.album_title ?? ''}
							allSongs={songs}
							versions={$versions}
							visible={coWriterOpen}
							onclose={closeCoWriter}
							onturncompleted={() => {
								if (song) {
									void fetchSong(song.id).then((fresh) => {
										replaceSongInList(fresh);
										loadSongData(fresh);
									});
								}
							}}
						/>
					</div>
				</div>
			</section>

			<section class="takes-pane" class:hidden={!split && recipe} aria-label={SONG_SURFACE_TAKES}>
				{#if split}
					<h3 class="pane-title">{SONG_SURFACE_TAKES}</h3>
				{/if}
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
								: `in ${expiringSoon.minDays} day${expiringSoon.minDays === 1 ? '' : 's'}`} — pick or
							keep to preserve.
						</span>
					</div>
				{/if}
				<GenerationsList
					{song}
					selectedId={inspected?.id ?? null}
					loadStatus={takesStatus}
					loadError={takesError}
					onselect={(gen) => selectGeneration(gen, song)}
					onagain={applyAgain}
					onrepaint={(gen) => applySource(gen, 'repaint')}
					onaudiocover={(gen) => applySource(gen, 'cover')}
					onretry={() => {
						if (song) void refreshTakes(song.id);
					}}
				/>
				{#if inspected}
					<GenerationView onclose={closeInspector} />
				{/if}
			</section>
		</div>
	</div>
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
		margin-bottom: 0.5rem;
	}

	.expiry-digest-icon {
		font-size: 1rem;
	}

	.detail-panel {
		padding: 1.2rem 1.5rem calc(var(--player-height) + 1.2rem);
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		flex: 1;
		max-width: 1200px;
		width: 100%;
		min-width: 0;
		min-height: 0;
	}

	.detail-header {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.55rem;
		min-width: 0;
	}

	.detail-identity {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		min-width: 0;
		flex: 1;
	}

	.cover-hero {
		position: relative;
		width: 4.5rem;
		height: 4.5rem;
		flex-shrink: 0;
		overflow: hidden;
		background: var(--surface-hover);
	}

	.cover-hero img,
	.cover-fallback {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.cover-fallback {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.cover-initials {
		font-family: var(--font-display);
		font-size: 1.1rem;
		letter-spacing: 0.06em;
		user-select: none;
	}

	.cover-file-input {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.cover-hit {
		position: absolute;
		inset: 0;
		padding: 0;
		border: none;
		background: transparent;
		cursor: pointer;
	}

	.cover-hit:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.cover-remove {
		position: absolute;
		top: 0;
		right: 0;
		z-index: 1;
		width: 1.5rem;
		height: 1.5rem;
		padding: 0;
		border: none;
		background: color-mix(in srgb, var(--bg) 75%, transparent);
		color: var(--text);
		font-size: 1rem;
		line-height: 1;
		cursor: pointer;
	}

	.song-heading {
		min-width: 0;
		flex: 1 1 12rem;
	}

	.song-title {
		font-family: var(--font-display);
		font-size: 1.73rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.13rem;
	}

	.song-rail {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem;
		min-width: 0;
		max-width: 100%;
	}

	.song-rail :global(.breadcrumb) {
		flex: 1 1 auto;
		min-width: 0;
	}

	.song-neighbor {
		color: var(--text-muted);
		background: none;
		border: none;
	}

	.song-neighbor:disabled {
		opacity: 0.4;
	}

	.detail-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.55rem;
		align-items: center;
		min-width: 0;
	}

	.status-msg {
		font-size: 0.75rem;
		color: var(--success);
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
	}

	.share-link:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.surface-switch {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--border);
		padding-bottom: 0;
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
		border-bottom: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent)) 1;
	}

	.panes {
		display: flex;
		flex: 1;
		min-height: 0;
		min-width: 0;
	}

	.detail-panel.split .panes {
		display: grid;
		grid-template-columns: minmax(var(--song-split-pane-min), 1fr) minmax(
				var(--song-split-pane-min),
				1fr
			);
		gap: var(--song-split-gap);
	}

	.recipe-pane,
	.takes-pane {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow-y: auto;
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}

	.recipe-pane.hidden,
	.takes-pane.hidden {
		display: none;
	}

	.pane-title {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.87rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
	}

	.recipe-toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 0.55rem;
		align-items: center;
	}

	.save-btn,
	.generate-btn {
		padding: var(--btn-padding-pill);
		border: none;
		border-radius: var(--btn-radius-pill);
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
		transition: box-shadow 0.2s;
	}

	.save-btn:hover:not(:disabled),
	.generate-btn:hover:not(:disabled) {
		box-shadow: 0 0 20px rgba(160, 32, 240, 0.3);
	}

	.save-btn:disabled,
	.generate-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	@media (prefers-reduced-motion: no-preference) {
		.generate-btn.generating {
			animation: gen-pulse 1.5s ease-in-out infinite;
		}
	}

	@keyframes gen-pulse {
		0%,
		100% {
			box-shadow: 0 0 6px rgba(160, 32, 240, 0.2);
		}
		50% {
			box-shadow: 0 0 20px rgba(160, 32, 240, 0.4);
		}
	}

	.gen-count-select,
	.model-select {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text-light);
		padding: 0.3rem 0.55rem;
		border-radius: var(--input-radius);
		font-size: 0.75rem;
	}

	.pinned-seed {
		font-size: 0.7rem;
		padding: 0.15rem 0.4rem;
		border-radius: 3px;
		background: var(--surface);
		border: 1px solid var(--accent);
		color: var(--accent);
		cursor: pointer;
		font-family: var(--font-body);
	}

	.pinned-seed:hover {
		background: var(--accent);
		color: #fff;
	}

	.cowriter-open {
		padding: 0.3rem 0.7rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.cowriter-open:hover,
	.cowriter-open[aria-expanded='true'] {
		border-color: var(--primary);
		color: var(--primary);
	}

	.cowriter-layer {
		display: none;
	}

	.cowriter-layer.open {
		display: block;
		position: absolute;
		inset: 0;
		z-index: 20;
	}

	.cowriter-backdrop {
		position: absolute;
		inset: 0;
		border: none;
		background: rgba(0, 0, 0, 0.45);
		cursor: pointer;
	}

	.cowriter-sheet {
		height: 100%;
		min-height: 0;
		background: var(--bg);
		border: 1px solid var(--border);
		display: flex;
		flex-direction: column;
	}

	.cowriter-layer.open.compact .cowriter-sheet {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		height: 85%;
		border-bottom: none;
		border-radius: 12px 12px 0 0;
	}

	.cowriter-sheet :global(.cowriter) {
		border-left: none;
		flex: 1;
		min-height: 0;
	}

	.job-indicator {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.7rem;
		color: var(--score-ok);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.job-progress-bar {
		width: 60px;
		height: 4px;
		background: var(--border);
		border-radius: 2px;
		overflow: hidden;
	}

	.job-progress-fill {
		display: block;
		height: 100%;
		background: var(--score-ok);
		border-radius: 2px;
		transition: width 0.3s ease;
	}

	.job-progress-label {
		min-width: 70px;
	}

	.job-cancel {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 0.7rem;
		font-family: var(--font-display);
		padding: 0.1rem 0.3rem;
		margin-left: 4px;
		line-height: 1;
		border-radius: 3px;
		border: 1px solid var(--border);
	}

	.job-cancel:hover {
		color: var(--score-bad);
		border-color: var(--score-bad);
	}

	.picker-anchor {
		position: relative;
	}

	@media (max-width: 768px) {
		.detail-header {
			flex-direction: column;
			gap: 8px;
		}

		.cover-hero {
			width: 3.5rem;
			height: 3.5rem;
		}

		.detail-actions {
			flex-wrap: wrap;
		}

		.detail-panel {
			padding: 0.8rem 0.8rem calc(var(--player-height) + 0.8rem);
		}

		.song-title {
			font-size: 1.2rem;
		}
	}
</style>
