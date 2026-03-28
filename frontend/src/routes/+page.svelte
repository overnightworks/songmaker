<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchAlbums,
		fetchSongs,
		fetchSong,
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
		selectedGeneration,
		ensureGenerationsLoaded
	} from '$lib/stores/player';
	import {
		selectGeneration,
		clearGenerationSelection,
		navigateToSongTab,
		switchTab,
		detailTab,
		initNavigation
	} from '$lib/stores/navigation';
	import {
		editLyrics,
		editPrompt,
		editBpm,
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
	import SongList from '$lib/components/SongList.svelte';
	import CreateForm from '$lib/components/CreateForm.svelte';
	import ClaudeChat from '$lib/components/ClaudeChat.svelte';
	import GenerationDetail from '$lib/components/GenerationDetail.svelte';
	import GenerationsList from '$lib/components/GenerationsList.svelte';
	import SongEditor from '$lib/components/SongEditor.svelte';
	import ToastContainer from '$lib/components/ToastContainer.svelte';
	import { addToast } from '$lib/stores/toast';

	let loading = $state(true);
	let loadError = $state(false);
	let showCreate = $state(false);
	let genCount = $state(1);

	const song = $derived($selectedSong);
	const activeGen = $derived($selectedGeneration);
	const albums = $derived($albumList);
	const dirty = $derived($isDirty);
	const isSaving = $derived($saving);
	const statusMsg = $derived($status);
	const jobs = $derived($activeJobs);
	const tab = $derived($detailTab);

	const songJobs = $derived(song ? jobs.filter((j) => j.songId === song.id) : []);
	const isGenerating = $derived(
		songJobs.some(
			(j) => j.job.type === 'generate' && (j.job.status === 'running' || j.job.status === 'queued')
		)
	);

	$effect(() => {
		if (song) {
			showCreate = false;
			loadSongData(song);
			ensureGenerationsLoaded(song.id);
		}
	});

	onMount(() => {
		let cleanup: (() => void) | undefined;

		(async () => {
			try {
				const [a, s] = await Promise.all([fetchAlbums(), fetchSongs()]);
				albumList.set(a.items);
				songList.set(s.items);
			} catch (e) {
				addToast(e instanceof Error ? e.message : 'Failed to load', 'error');
				loadError = true;
			} finally {
				loading = false;
			}
			if (!loadError) {
				cleanup = initNavigation();
			}
		})();

		return () => cleanup?.();
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
			const job = await generateSong(song.id, genCount);
			trackJob(job, { songId: song.id });
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Generation failed', 'error');
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
			addToast(e instanceof Error ? e.message : 'Pick failed', 'error');
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

	const songContext = $derived(
		song
			? `Song: ${song.title}\nAlbum: ${song.album_title}\nStyle: ${$editPrompt}\nKey: ${$editKey}\nBPM: ${$editBpm}\n\nLyrics:\n${$editLyrics}`
			: ''
	);
</script>

{#if loading}
	<div class="loading">Loading...</div>
{:else if loadError}
	<div class="error">Failed to load. Please refresh.</div>
{:else}
	<aside class="sidebar" class:has-detail={!!song || showCreate}>
		<SongList
			onNewSong={() => {
				showCreate = !showCreate;
			}}
		/>
	</aside>

	<main class="main-content" class:has-detail={!!song || showCreate}>
		{#if showCreate}
			<CreateForm {albums} />
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
							{#if tab === 'edit' && dirty}
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
								{#if j.job.status === 'queued'}
									{j.job.type} queued
								{:else if j.job.status === 'running'}
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
					</div>
				</div>

				{#if activeGen}
					{@const genScoring = jobs.some(
						(j) =>
							j.genId === activeGen.id &&
							j.job.type === 'score' &&
							(j.job.status === 'running' || j.job.status === 'queued')
					)}
					<GenerationDetail
						generation={activeGen}
						scoring={genScoring}
						onversionclick={onVersionClick}
						onscore={onScore}
						onpick={onPick}
					/>
				{:else}
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
						<GenerationsList
							{song}
							onselect={(gen) => selectGeneration(gen, song)}
							onscore={onScore}
							onpick={onPick}
						/>
					{:else if tab === 'edit'}
						<SongEditor ondeleteversion={onDeleteVersion} />
					{:else if tab === 'chat'}
						<div class="chat-tab">
							<ClaudeChat
								songId={song?.id ?? ''}
								{songContext}
								allSongs={$songList}
								currentAlbumId={song?.album_id ?? ''}
								onapply={handleApply}
							/>
						</div>
					{/if}
				{/if}
			</div>
		{:else}
			<div class="empty-state">Select a song or create a new one</div>
		{/if}
	</main>
{/if}

<ToastContainer />

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

	.main-content {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.detail-panel {
		padding: 16px 20px calc(var(--player-height) + 16px);
		display: flex;
		flex-direction: column;
		gap: 12px;
		flex: 1;
		max-width: 800px;
		width: 100%;
		min-width: 0;
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
		letter-spacing: 1px;
		cursor: pointer;
	}

	.tab-btn:hover {
		color: var(--text);
	}

	.tab-btn.active {
		color: var(--primary);
		border-bottom-color: var(--primary);
	}

	.chat-tab {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
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
		.sidebar {
			position: static;
			width: 100%;
			min-width: 0;
			height: 100%;
			border-right: none;
			transform: none;
		}

		.sidebar.has-detail {
			display: none;
		}

		.main-content {
			display: none;
		}

		.main-content.has-detail {
			display: flex;
		}

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
	}
</style>
