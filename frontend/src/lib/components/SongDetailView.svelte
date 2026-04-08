<script lang="ts">
	import {
		cancelJob,
		fetchSong,
		generateSong,
		scoreGeneration,
		pickGeneration,
		unpickGeneration,
		deleteSong,
		shareSong,
		unshareSong,
		shareGeneration,
		unshareGeneration,
		deleteGeneration,
		rateGeneration,
		keepGeneration,
		unkeepGeneration
	} from '$lib/api/client';
	import { activeJobs, trackJob, removeJob } from '$lib/stores/jobs';
	import {
		selectedSong,
		ensureGenerationsLoaded,
		replaceSongInList,
		updateSongInList,
		updateGenerationInList,
		removeGenerationFromSong,
		removeSongFromList
	} from '$lib/stores/player';
	import {
		selectGeneration,
		navigateToSongTab,
		switchTab,
		backToAlbum,
		detailTab
	} from '$lib/stores/navigation';
	import {
		isDirty,
		versions,
		currentVersionIndex,
		saving,
		status,
		loadSongData,
		loadVersion,
		handleSave,
		handleDeleteVersion,
		handleApply
	} from '$lib/stores/editor';
	import { activeModels } from '$lib/stores/presets';
	import { songList } from '$lib/stores/player';
	import { addToast } from '$lib/stores/toast';
	import { addGenerationToPlaylist, addSongToPlaylist } from '$lib/stores/playlists';
	import { pendingSource } from '$lib/stores/source';
	import { setGenerationActions } from '$lib/contexts/generation-actions';
	import type { GenerationItem } from '$lib/api/types';
	import GenerationsList from './GenerationsList.svelte';
	import SongEditor from './SongEditor.svelte';
	import ClaudeChat from './ClaudeChat.svelte';
	import ActionButton from './ActionButton.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
	import { selectSong } from '$lib/stores/navigation';

	let genCount = $state(1);
	let selectedModel = $state<string | null>(null);
	let showDeleteConfirm = $state(false);
	let pinnedSeed = $state<number | null>(null);
	let sourceGeneration = $state<GenerationItem | null>(null);
	let sourceMode = $state<'repaint' | 'cover'>('repaint');
	let repaintStart = $state(0);
	let repaintEnd = $state(1);
	let coverStrength = $state(0.7);
	let repaintMode = $state<string>('');
	let repaintStrength = $state(0.5);
	let coverNoiseStrength = $state(0);
	let playlistPickerFor = $state<
		{ type: 'song'; id: string } | { type: 'generation'; id: string } | null
	>(null);

	const song = $derived($selectedSong);
	const jobs = $derived($activeJobs);
	const tab = $derived($detailTab);
	const dirty = $derived($isDirty);
	const isSaving = $derived($saving);
	const statusMsg = $derived($status);

	$effect(() => {
		if (song) {
			loadSongData(song);
			ensureGenerationsLoaded(song.id);
		}
	});

	$effect(() => {
		const pending = $pendingSource;
		if (pending) {
			sourceGeneration = pending;
			sourceMode = 'repaint';
			repaintStart = 0;
			repaintEnd = 1;
			pendingSource.set(null);
			switchTab('edit');
		}
	});

	const songJobs = $derived(song ? jobs.filter((j) => j.songId === song.id) : []);
	const isGenerating = $derived(
		songJobs.some(
			(j) => j.job.type === 'generate' && (j.job.status === 'running' || j.job.status === 'queued')
		)
	);

	$effect(() => {
		if (selectedModel === null && $activeModels.length > 0) {
			selectedModel = $activeModels[0].id;
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
			pinnedSeed = seed;
			addToast(`Seed ${seed} pinned for next generation`, 'success');
		},
		clickVersion: onVersionClick,
		useAsSource: (gen) => {
			sourceGeneration = gen;
			sourceMode = 'repaint';
			repaintStart = 0;
			repaintEnd = 1;
			switchTab('edit');
		}
	});

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

			if (sourceGeneration && sourceMode === 'repaint') {
				const { repaintGeneration } = await import('$lib/api/client');
				const job = await repaintGeneration(sourceGeneration.id, repaintStart, repaintEnd, {
					model,
					seed: pinnedSeed,
					versionId,
					count: genCount,
					repaintMode: repaintMode || undefined,
					repaintStrength: repaintMode === 'balanced' ? repaintStrength : undefined
				});
				pinnedSeed = null;
				trackJob(job, { songId: song.id });
			} else if (sourceGeneration && sourceMode === 'cover') {
				const { coverGeneration } = await import('$lib/api/client');
				const job = await coverGeneration(sourceGeneration.id, coverStrength, {
					model,
					seed: pinnedSeed,
					versionId,
					count: genCount,
					coverNoiseStrength: coverNoiseStrength > 0 ? coverNoiseStrength : undefined
				});
				pinnedSeed = null;
				trackJob(job, { songId: song.id });
			} else {
				const job = await generateSong(song.id, genCount, model, versionId, pinnedSeed);
				pinnedSeed = null;
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
			backToAlbum();
			addToast('Song deleted', 'success');
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
		return result;
	}

	async function onGenShareDisable(genId: string) {
		await unshareGeneration(genId);
		updateGenerationInList(genId, (g) => ({ ...g, is_shared: false, share_slug: null }));
	}

	async function onDeleteGeneration(genId: string): Promise<void> {
		if (!song) return;
		try {
			await deleteGeneration(genId);
			removeGenerationFromSong(song.id, genId);
			addToast('Generation deleted', 'success');
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

{#if song}
	<div class="detail-panel" class:chat-active={tab === 'chat'}>
		<button class="back-btn" onclick={backToAlbum}>
			<span class="back-arrow">←</span>
			{song.album_title}
		</button>
		<div class="detail-header">
			<div>
				<h2 class="song-title">{song.title}</h2>
				<span class="song-album">{song.artist}</span>
			</div>
			<div class="detail-actions">
				{#if tab === 'edit' || tab === 'chat'}
					{#if dirty}
						<button class="save-btn" onclick={onSave} disabled={isSaving}>
							{isSaving ? 'Saving...' : 'Save'}
						</button>
					{/if}
					<button
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
								: ''}
					>
						{#if sourceGeneration}
							{isGenerating ? 'Generating...' : sourceMode === 'repaint' ? 'Repaint' : 'Cover'}
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
					{#if pinnedSeed != null}
						<button
							class="pinned-seed"
							onclick={() => (pinnedSeed = null)}
							title="Click to clear pinned seed"
						>
							seed:{pinnedSeed} ✕
						</button>
					{/if}
				{/if}
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
					{#if j.job.status === 'failed'}
						<span class="job-indicator failed">
							{j.job.error || 'Failed'}
						</span>
					{:else if j.job.status === 'queued' || j.job.status === 'running'}
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

		<div class="tab-bar">
			<button
				class="tab-btn"
				class:active={tab === 'generations'}
				onclick={() => switchTab('generations')}
			>
				Generations
			</button>
			<button class="tab-btn" class:active={tab === 'edit'} onclick={() => switchTab('edit')}>
				Edit
			</button>
			<button class="tab-btn" class:active={tab === 'chat'} onclick={() => switchTab('chat')}>
				Co-Writer
			</button>
		</div>

		{#if tab === 'generations'}
			<GenerationsList {song} onselect={(gen) => selectGeneration(gen, song)} />
		{:else if tab === 'edit'}
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
				onsourceselect={(gen) => {
					sourceGeneration = gen;
					sourceMode = 'repaint';
					repaintStart = 0;
					repaintEnd = 1;
				}}
			/>
		{/if}
		<div class="chat-tab" class:hidden={tab !== 'chat'}>
			<ClaudeChat
				songId={song?.id ?? ''}
				allSongs={$songList}
				currentAlbumId={song?.album_id ?? ''}
				versions={$versions}
				visible={tab === 'chat'}
				onapply={handleApply}
				oncreate={(s) => selectSong(s.id)}
				onnavigate={(id) => {
					selectSong(id);
					switchTab('chat');
				}}
			/>
		</div>
	</div>
{/if}

{#if showDeleteConfirm && song}
	<ConfirmDeleteDialog
		title={`Delete "${song.title}"?`}
		items={[
			`${song.generation_count} generation${song.generation_count !== 1 ? 's' : ''}`,
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
		max-width: 1200px;
		width: 100%;
		min-width: 0;
		min-height: 0;
	}

	.detail-panel.chat-active {
		padding-left: 2.1rem;
		padding-right: 2.1rem;
	}

	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.song-title {
		font-family: var(--font-display);
		font-size: 1.73rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.13rem;
	}

	.song-album {
		font-size: 0.87rem;
		color: var(--text-muted);
	}

	.detail-actions {
		display: flex;
		gap: 0.55rem;
		align-items: center;
	}

	.status-msg {
		font-size: 0.75rem;
		color: var(--success);
	}

	.save-btn {
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

	.save-btn:hover:not(:disabled) {
		box-shadow: 0 0 20px rgba(160, 32, 240, 0.3);
	}

	.save-btn:disabled {
		opacity: 0.4;
	}

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

	.generate-btn:hover:not(:disabled) {
		box-shadow: 0 0 20px rgba(160, 32, 240, 0.3);
	}

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

	.job-indicator.failed {
		color: var(--score-bad);
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

	.back-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.87rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 0.55rem 1.1rem;
		cursor: pointer;
		border-bottom: 1px solid var(--border);
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.back-arrow {
		font-size: 0.93rem;
	}

	.tab-bar {
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

	.chat-tab {
		flex: 1;
		min-height: 400px;
		display: flex;
		flex-direction: column;
	}

	.chat-tab.hidden {
		display: none;
	}

	.picker-anchor {
		position: relative;
	}

	@media (max-width: 768px) {
		.detail-header {
			flex-direction: column;
			gap: 8px;
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
