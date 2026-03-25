<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchAlbums,
		fetchSongs,
		fetchSong,
		createAlbum,
		createSong,
		generateSong,
		scoreGeneration,
		pickGeneration,
		unpickGeneration
	} from '$lib/api/client';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import {
		albumList,
		songList,
		selectedSong,
		selectSong,
		selectedGeneration,
		clearGenerationSelection,
		ensureGenerationsLoaded,
		playback
	} from '$lib/stores/player';
	import {
		editLyrics,
		editPrompt,
		editBpm,
		editDuration,
		editKey,
		isDirty,
		versions,
		saving,
		status,
		loadSongData,
		loadVersion,
		handleSave,
		handleDeleteVersion,
		handleApply
	} from '$lib/stores/editor';
	import { sidebarOpen, closeSidebar } from '$lib/stores/ui';
	import SongList from '$lib/components/SongList.svelte';
	import ClaudeChat from '$lib/components/ClaudeChat.svelte';
	import GenerationDetail from '$lib/components/GenerationDetail.svelte';
	import SongEditor from '$lib/components/SongEditor.svelte';

	let loading = $state(true);
	let error = $state('');
	let showChat = $state(false);

	let newTitle = $state('');
	let newAlbumId = $state('');
	let newAlbumTitle = $state('');
	let newAlbumArtist = $state('');
	let showCreate = $state(false);
	let creating = $state(false);
	let creatingAlbum = $state(false);

	const song = $derived($selectedSong);
	const activeGen = $derived($selectedGeneration);
	const albums = $derived($albumList);
	const dirty = $derived($isDirty);
	const isSaving = $derived($saving);
	const statusMsg = $derived($status);
	const jobs = $derived($activeJobs);
	const sbOpen = $derived($sidebarOpen);
	const hasPlayer = $derived($playback !== null);

	const songJobs = $derived(song ? jobs.filter((j) => j.songId === song.id) : []);
	const isGenerating = $derived(
		songJobs.some((j) => j.job.type === 'generate' && j.job.status === 'running')
	);

	let genCount = $state(1);

	$effect(() => {
		if (song) {
			loadSongData(song);
			ensureGenerationsLoaded(song.id);
		}
	});

	onMount(async () => {
		try {
			const [a, s] = await Promise.all([fetchAlbums(), fetchSongs()]);
			albumList.set(a);
			songList.set(s);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load';
		} finally {
			loading = false;
		}
	});

	function onSave(): void {
		if (song) handleSave(song.id);
	}

	function onDeleteVersion(versionId: string, deleteGenerations: boolean): void {
		if (song) handleDeleteVersion(song.id, versionId, deleteGenerations);
	}

	async function onGenerate(): Promise<void> {
		if (!song) return;
		error = '';
		try {
			const job = await generateSong(song.id, genCount);
			trackJob(job, { songId: song.id });
		} catch (e) {
			error = e instanceof Error ? e.message : 'Generation failed';
		}
	}

	async function onPick(genId: string, picked: boolean): Promise<void> {
		if (!song) return;
		try {
			if (picked) {
				await pickGeneration(genId);
			} else {
				await unpickGeneration(genId);
			}
			const updated = await fetchSong(song.id);
			songList.update((songs) => songs.map((s) => (s.id === updated.id ? updated : s)));
		} catch (e) {
			error = e instanceof Error ? e.message : 'Pick failed';
		}
	}

	async function onScore(genId: string): Promise<void> {
		if (!song) return;
		try {
			const job = await scoreGeneration(genId);
			trackJob(job, { songId: song.id, genId });
		} catch (e) {
			error = e instanceof Error ? e.message : 'Scoring failed';
		}
	}

	function onVersionClick(versionId: string): void {
		const idx = $versions.findIndex((v) => v.id === versionId);
		if (idx !== -1) loadVersion(idx);
		clearGenerationSelection();
	}

	async function handleCreateAlbum(): Promise<void> {
		if (!newAlbumTitle.trim()) return;
		creatingAlbum = true;
		error = '';
		try {
			const album = await createAlbum(newAlbumTitle.trim(), newAlbumArtist.trim());
			albumList.set(await fetchAlbums());
			newAlbumId = album.id;
			newAlbumTitle = '';
			newAlbumArtist = '';
		} catch (e) {
			error = e instanceof Error ? e.message : 'Album creation failed';
		} finally {
			creatingAlbum = false;
		}
	}

	async function handleCreateSong(): Promise<void> {
		if (!newTitle.trim() || !newAlbumId) return;
		creating = true;
		error = '';
		try {
			const created = await createSong({
				title: newTitle,
				album_id: newAlbumId,
				lyrics: $editLyrics,
				prompt: $editPrompt,
				bpm: $editBpm,
				duration: $editDuration,
				key: $editKey
			});
			songList.update((songs) => [...songs, created]);
			selectSong(created.id);
			showCreate = false;
			newTitle = '';
		} catch (e) {
			error = e instanceof Error ? e.message : 'Create failed';
		} finally {
			creating = false;
		}
	}

	const songContext = $derived(
		song
			? `Song: ${song.title}\nAlbum: ${song.album_title}\nStyle: ${$editPrompt}\nKey: ${$editKey}\nBPM: ${$editBpm}\n\nLyrics:\n${$editLyrics}`
			: ''
	);
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if error}
	<div class="error">{error}</div>
{:else}
	<aside class="sidebar" class:open={sbOpen}>
		<SongList
			onNewSong={() => {
				showCreate = !showCreate;
				closeSidebar();
			}}
		/>
	</aside>

	<main class="main-content">
		{#if showCreate}
			<div class="create-panel">
				<div class="create-header">
					<h2>Create</h2>
					<button class="cancel-create" onclick={() => (showCreate = false)}>Cancel</button>
				</div>

				<div class="create-section">
					<h3>New Album</h3>
					<div class="create-fields">
						<input type="text" bind:value={newAlbumTitle} placeholder="Album title" />
						<input type="text" bind:value={newAlbumArtist} placeholder="Artist (optional)" />
						<button onclick={handleCreateAlbum} disabled={creatingAlbum || !newAlbumTitle.trim()}>
							{creatingAlbum ? 'Creating...' : 'Create'}
						</button>
					</div>
				</div>

				<div class="create-section">
					<h3>New Song</h3>
					<div class="create-fields">
						<input type="text" bind:value={newTitle} placeholder="Song title" />
						<select bind:value={newAlbumId}>
							<option value="">Select album</option>
							{#each albums as a (a.id)}
								<option value={a.id}>{a.title}</option>
							{/each}
						</select>
						<button
							onclick={handleCreateSong}
							disabled={creating || !newTitle.trim() || !newAlbumId}
						>
							{creating ? 'Creating...' : 'Create'}
						</button>
					</div>
				</div>
			</div>
		{:else if song}
			<div class="detail-panel">
				<div class="detail-header">
					<div>
						<button class="song-title-btn" onclick={clearGenerationSelection}>
							<h2 class="song-title">{song.title}</h2>
						</button>
						<span class="song-album">{song.album_title} · {song.artist}</span>
					</div>
					<div class="detail-actions">
						{#if !activeGen}
							{#if dirty}
								<button class="save-btn" onclick={onSave} disabled={isSaving}>
									{isSaving ? 'Saving...' : 'Save'}
								</button>
							{:else}
								<button
									class="generate-btn"
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
							{/if}
						{/if}
						{#each songJobs as j (j.job.id)}
							<span class="job-indicator" class:failed={j.job.status === 'failed'}>
								{#if j.job.status === 'running'}
									{j.job.type} {Math.round(j.job.progress * 100)}%
								{:else if j.job.status === 'completed'}
									Done
								{:else if j.job.status === 'failed'}
									{j.job.error || 'Failed'}
								{/if}
							</span>
						{/each}
						{#if statusMsg}
							<span class="status-msg">{statusMsg}</span>
						{/if}
						{#if !activeGen}
							<button
								class="action-btn chat-btn"
								class:active={showChat}
								onclick={() => (showChat = !showChat)}
								aria-label="Toggle chat"
							>
								💬
							</button>
						{/if}
					</div>
				</div>

				{#if activeGen}
					{@const genScoring = jobs.some(
						(j) => j.genId === activeGen.id && j.job.type === 'score' && j.job.status === 'running'
					)}
					<GenerationDetail
						generation={activeGen}
						scoring={genScoring}
						onversionclick={onVersionClick}
						onscore={onScore}
						onpick={onPick}
					/>
				{:else}
					<SongEditor ondeleteversion={onDeleteVersion} />
				{/if}
			</div>
		{:else}
			<div class="empty-state">Select a song or create a new one</div>
		{/if}
	</main>

	{#if showChat && !activeGen}
		<aside class="chat-panel" class:with-player={hasPlayer}>
			<ClaudeChat songId={song?.id ?? ''} {songContext} onapply={handleApply} />
		</aside>
	{/if}
{/if}

<style>
	.sidebar {
		width: 320px;
		min-width: 280px;
		height: 100%;
		display: flex;
		flex-direction: column;
		border-right: 1px solid var(--border);
		flex-shrink: 0;
	}

	@media (max-width: 768px) {
		.sidebar {
			position: fixed;
			top: var(--header-height);
			left: 0;
			bottom: 0;
			width: 300px;
			z-index: 160;
			background: var(--bg);
			transform: translateX(-100%);
			transition: transform 0.2s ease;
		}

		.sidebar.open {
			transform: translateX(0);
		}
	}

	.main-content {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
	}

	.detail-panel {
		padding: 16px 20px calc(var(--player-height) + 16px);
		display: flex;
		flex-direction: column;
		gap: 12px;
		flex: 1;
		max-width: 800px;
		width: 100%;
		margin: 0 auto;
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

	.action-btn {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		border: 2px solid var(--border);
		background: transparent;
		font-size: 16px;
		cursor: pointer;
	}

	.action-btn:hover,
	.action-btn.active {
		border-color: var(--primary);
	}

	.status-msg {
		font-size: 11px;
		color: var(--success);
	}

	.save-btn {
		padding: 6px 16px;
		border: 2px solid var(--primary);
		border-radius: 16px;
		background: var(--primary);
		color: #fff;
		font-family: var(--font-display);
		font-size: 11px;
		letter-spacing: 1px;
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
	}

	.save-btn:disabled {
		opacity: 0.4;
	}

	.generate-btn {
		padding: 6px 16px;
		border: 2px solid var(--primary);
		border-radius: 16px;
		background: var(--primary);
		color: #fff;
		font-family: var(--font-display);
		font-size: 11px;
		letter-spacing: 1px;
		text-transform: uppercase;
		cursor: pointer;
		white-space: nowrap;
	}

	.generate-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.gen-count-select {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text-light);
		padding: 4px 8px;
		border-radius: 4px;
		font-size: 11px;
	}

	.job-indicator {
		font-size: 10px;
		color: var(--score-ok);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.job-indicator.failed {
		color: var(--score-bad);
	}

	.chat-panel {
		width: 350px;
		min-width: 300px;
		height: 100%;
		flex-shrink: 0;
	}

	.create-panel {
		padding: 20px;
		max-width: 600px;
	}

	.create-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 16px;
	}

	.create-header h2 {
		font-family: var(--font-display);
		color: var(--primary);
		font-size: 20px;
		margin: 0;
		text-transform: uppercase;
	}

	.cancel-create {
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		padding: 4px 12px;
		font-size: 11px;
		cursor: pointer;
	}

	.cancel-create:hover {
		border-color: var(--text-muted);
	}

	.create-section {
		margin-bottom: 16px;
	}

	.create-section h3 {
		font-family: var(--font-display);
		color: var(--text-muted);
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 1px;
		margin: 0 0 8px;
	}

	.create-fields {
		display: flex;
		gap: 8px;
	}

	.create-fields input,
	.create-fields select {
		flex: 1;
		padding: 8px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 13px;
	}

	.create-fields button {
		padding: 8px 20px;
		border: 2px solid var(--primary);
		border-radius: 20px;
		background: var(--primary);
		color: #fff;
		font-family: var(--font-display);
		font-size: 12px;
		cursor: pointer;
		white-space: nowrap;
	}

	.create-fields button:disabled {
		opacity: 0.4;
	}

	.loading,
	.error,
	.empty-state {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		color: var(--text-muted);
		font-style: italic;
	}

	.error {
		color: var(--score-bad);
	}

	@media (max-width: 768px) {
		.create-fields {
			flex-direction: column;
		}

		.create-fields button {
			align-self: flex-start;
		}

		.detail-header {
			flex-direction: column;
			gap: 8px;
		}

		.detail-actions {
			flex-wrap: wrap;
		}

		.chat-panel {
			position: fixed;
			top: var(--header-height);
			left: 0;
			right: 0;
			bottom: 0;
			width: 100%;
			z-index: 170;
			background: var(--bg);
		}

		.chat-panel.with-player {
			bottom: var(--player-height);
		}
	}
</style>
