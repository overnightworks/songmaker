<script lang="ts">
	import {
		cancelJob,
		fetchSong,
		generateSong,
		scoreGeneration,
		pickGeneration,
		unpickGeneration,
		deleteSong,
		cleanupSong,
		shareSong,
		unshareSong,
		shareGeneration,
		unshareGeneration,
		deleteGeneration,
		rateGeneration,
		repaintGeneration,
		coverGeneration,
		keepGeneration,
		unkeepGeneration
	} from '$lib/api/client';
	import { activeJobs, trackJob, removeJob } from '$lib/stores/jobs';
	import {
		selectedSong,
		selectedGeneration,
		ensureGenerationsLoaded,
		replaceSongInList,
		updateSongInList,
		updateGenerationInList,
		removeGenerationFromSong,
		removeSongFromList
	} from '$lib/stores/player';
	import {
		selectGeneration,
		clearGenerationSelection,
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
	import { setGenerationActions } from '$lib/contexts/generation-actions';
	import type { GenerationItem } from '$lib/api/types';
	import GenerationDetail from './GenerationDetail.svelte';
	import GenerationsList from './GenerationsList.svelte';
	import SongEditor from './SongEditor.svelte';
	import ClaudeChat from './ClaudeChat.svelte';
	import OverflowMenu from './OverflowMenu.svelte';
	import PlaylistPicker from './PlaylistPicker.svelte';
	import ShareButton from './ShareButton.svelte';
	import CoverDialog from './CoverDialog.svelte';
	import RepaintDialog from './RepaintDialog.svelte';
	import { selectSong } from '$lib/stores/navigation';

	let genCount = $state(1);
	let selectedModel = $state<string | null>(null);
	let pinnedSeed = $state<number | null>(null);
	let repaintTarget = $state<GenerationItem | null>(null);
	let coverTarget = $state<GenerationItem | null>(null);
	let playlistPickerFor = $state<
		| { type: 'song'; id: string }
		| { type: 'generation'; id: string }
		| null
	>(null);

	const song = $derived($selectedSong);
	const activeGen = $derived($selectedGeneration);
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
		repaint: (gen) => (repaintTarget = gen),
		cover: (gen) => (coverTarget = gen)
	});

	function onSave(): void {
		if (song) handleSave(song.id);
	}

	function onDeleteVersion(versionId: string, deleteGenerations: boolean): void {
		if (song) handleDeleteVersion(song.id, versionId, deleteGenerations);
	}

	async function onGenerate(): Promise<void> {
		if (!song) return;
		try {
			const ver = $versions[$currentVersionIndex];
			const job = await generateSong(song.id, genCount, selectedModel, ver?.id, pinnedSeed);
			pinnedSeed = null;
			trackJob(job, { songId: song.id });
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Generation failed', 'error');
		}
	}

	async function onRepaintSubmit(
		start: number, end: number, lyrics: string | null, prompt: string | null,
	): Promise<void> {
		if (!song || !repaintTarget) return;
		try {
			const job = await repaintGeneration(
				repaintTarget.id, start, end, lyrics, prompt, selectedModel,
			);
			repaintTarget = null;
			trackJob(job, { songId: song.id });
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Repaint failed', 'error');
		}
	}

	async function onCoverSubmit(
		strength: number, lyrics: string | null, prompt: string | null,
	): Promise<void> {
		if (!song || !coverTarget) return;
		try {
			const job = await coverGeneration(
				coverTarget.id, strength, lyrics, prompt, selectedModel,
			);
			coverTarget = null;
			trackJob(job, { songId: song.id });
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Cover failed', 'error');
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

	async function onSongCleanup(): Promise<void> {
		if (!song) return;
		try {
			const result = await cleanupSong(song.id);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
			addToast(`Deleted ${result.deleted} generation${result.deleted !== 1 ? 's' : ''}`, 'success');
		} catch {
			addToast('Cleanup failed', 'error');
		}
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
		updateGenerationInList(genId, (g) => ({ ...g, is_shared: true, share_slug: result.share_slug }));
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
			clearGenerationSelection();
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
				<button class="song-title-btn" onclick={clearGenerationSelection}>
					<h2 class="song-title">{song.title}</h2>
				</button>
				<span class="song-album">{song.artist}</span>
			</div>
			<div class="detail-actions">
				{#if tab === 'edit' && dirty}
					<button class="save-btn" onclick={onSave} disabled={isSaving}>
						{isSaving ? 'Saving...' : 'Save'}
					</button>
				{:else}
					<button
						class="generate-btn"
						class:generating={isGenerating}
						onclick={onGenerate}
						disabled={isGenerating || !song?.lyrics || !song?.prompt}
						title={!song?.lyrics || !song?.prompt ? 'Add lyrics and style prompt first' : ''}
					>
						{isGenerating ? 'Generating...' : 'Generate'}
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
					<OverflowMenu
						items={[
							{
								label: 'Add to Playlist',
								onclick: () => (playlistPickerFor = { type: 'song', id: song.id })
							},
							{
								label: 'Clean Up Generations',
								confirmLabel: 'Confirm Clean Up',
								onclick: onSongCleanup
							},
							{
								label: 'Delete Song',
								confirmLabel: 'Confirm Delete',
								destructive: true,
								onclick: onDeleteSong
							}
						]}
					/>
					{#if playlistPickerFor?.type === 'song' && playlistPickerFor.id === song.id}
						<PlaylistPicker
							onselect={onAddToPlaylist}
							onclose={() => (playlistPickerFor = null)}
						/>
					{/if}
				</div>
				{#each songJobs as j (j.job.id)}
					{#if j.job.status === 'failed'}
						<span class="job-indicator failed">
							{j.job.error || 'Failed'}
						</span>
					{:else if j.job.status === 'queued' || j.job.status === 'running'}
						<span class="job-indicator">
							<span class="job-progress-bar">
								<span
									class="job-progress-fill"
									style="width: {Math.round(j.job.progress * 100)}%"
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
			{#if activeGen}
				{@const genScoring = jobs.some(
					(j) =>
						j.genId === activeGen.id &&
						j.job.type === 'score' &&
						(j.job.status === 'running' || j.job.status === 'queued')
				)}
				<div class="gen-detail-wrapper">
					<button class="back-btn" onclick={clearGenerationSelection}>
						<span class="back-arrow">←</span> All generations
					</button>
					<GenerationDetail
						generation={activeGen}
						scoring={genScoring}
					/>
				</div>
			{:else}
				<GenerationsList
					{song}
					onselect={(gen) => selectGeneration(gen, song)}
				/>
			{/if}
		{:else if tab === 'edit'}
			<SongEditor ondeleteversion={onDeleteVersion} {selectedModel} />
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

{#if repaintTarget}
	<RepaintDialog
		generation={repaintTarget}
		onsubmit={onRepaintSubmit}
		oncancel={() => (repaintTarget = null)}
	/>
{/if}

{#if coverTarget}
	<CoverDialog
		generation={coverTarget}
		onsubmit={onCoverSubmit}
		oncancel={() => (coverTarget = null)}
	/>
{/if}

<style>
	.detail-panel {
		padding: 16px 20px calc(var(--player-height) + 16px);
		display: flex;
		flex-direction: column;
		gap: 12px;
		flex: 1;
		max-width: 1000px;
		width: 100%;
		min-width: 0;
		min-height: 0;
		margin: 0 auto;
	}

	.detail-panel.chat-active {
		max-width: 100%;
		padding-left: 32px;
		padding-right: 32px;
	}

	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.song-title-btn {
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}

	.song-title {
		font-family: var(--font-display);
		font-size: 22px;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 2px;
	}

	.song-title-btn:hover .song-title {
		color: var(--primary);
	}

	.song-album {
		font-size: 12px;
		color: var(--text-muted);
	}

	.detail-actions {
		display: flex;
		gap: 8px;
		align-items: center;
	}

	.status-msg {
		font-size: 11px;
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
		padding: 4px 8px;
		border-radius: var(--input-radius);
		font-size: 11px;
	}

	.pinned-seed {
		font-size: 10px;
		padding: 2px 6px;
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
		font-size: 10px;
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
		font-size: 10px;
		font-family: var(--font-display);
		padding: 1px 4px;
		margin-left: 4px;
		line-height: 1;
		border-radius: 3px;
		border: 1px solid var(--border);
	}

	.job-cancel:hover {
		color: var(--score-bad);
		border-color: var(--score-bad);
	}

	.gen-detail-wrapper {
		display: flex;
		flex-direction: column;
		flex: 1;
		overflow: auto;
	}

	.back-btn {
		display: flex;
		align-items: center;
		gap: 6px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 11px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 8px 16px;
		cursor: pointer;
		border-bottom: 1px solid var(--border);
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.back-arrow {
		font-size: 14px;
	}

	.tab-bar {
		display: flex;
		gap: 2px;
		border-bottom: 1px solid var(--border);
		padding-bottom: 0;
	}

	.tab-btn {
		padding: 8px 16px;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 11px;
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
			padding: 12px 12px calc(var(--player-height) + 12px);
		}

		.song-title {
			font-size: 18px;
		}
	}
</style>
