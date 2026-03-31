<script lang="ts">
	import { onMount } from 'svelte';
	import {
		cancelJob,
		fetchAlbums,
		fetchSongs,
		fetchSong,
		generateSong,
		scoreGeneration,
		pickGeneration,
		unpickGeneration
	} from '$lib/api/client';
	import { activeJobs, trackJob, removeJob } from '$lib/stores/jobs';
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
		currentVersionIndex,
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
			const ver = $versions[$currentVersionIndex];
			const job = await generateSong(song.id, genCount, null, ver?.id);
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
						{/if}
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
								onversionclick={onVersionClick}
								onscore={onScore}
								onpick={onPick}
							/>
						</div>
					{:else}
						<GenerationsList
							{song}
							onselect={(gen) => selectGeneration(gen, song)}
							onscore={onScore}
							onpick={onPick}
						/>
					{/if}
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
			</div>
		{:else}
			<div class="empty-state">
				<div class="empty-waveform" aria-hidden="true">
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
					<span class="wave-bar"></span>
				</div>
				Select a song or create a new one
			</div>
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
		position: relative;
		background-image:
			linear-gradient(rgba(160, 32, 240, 0.02) 1px, transparent 1px),
			linear-gradient(90deg, rgba(160, 32, 240, 0.02) 1px, transparent 1px);
		background-size: 40px 40px;
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

	.gen-count-select {
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--text-light);
		padding: 4px 8px;
		border-radius: var(--input-radius);
		font-size: 11px;
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
		flex-direction: column;
		gap: 16px;
	}

	.empty-waveform {
		display: flex;
		align-items: flex-end;
		gap: 3px;
		height: 32px;
	}

	.wave-bar {
		width: 3px;
		background: linear-gradient(to top, var(--primary), var(--accent));
		border-radius: 2px;
		opacity: 0.3;
	}

	@media (prefers-reduced-motion: no-preference) {
		.wave-bar {
			animation: wave-idle 1.5s ease-in-out infinite;
		}

		.wave-bar:nth-child(1) {
			animation-delay: 0s;
			height: 12px;
		}
		.wave-bar:nth-child(2) {
			animation-delay: 0.15s;
			height: 20px;
		}
		.wave-bar:nth-child(3) {
			animation-delay: 0.3s;
			height: 28px;
		}
		.wave-bar:nth-child(4) {
			animation-delay: 0.45s;
			height: 20px;
		}
		.wave-bar:nth-child(5) {
			animation-delay: 0.6s;
			height: 12px;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.wave-bar:nth-child(1) {
			height: 12px;
		}
		.wave-bar:nth-child(2) {
			height: 20px;
		}
		.wave-bar:nth-child(3) {
			height: 28px;
		}
		.wave-bar:nth-child(4) {
			height: 20px;
		}
		.wave-bar:nth-child(5) {
			height: 12px;
		}
	}

	@keyframes wave-idle {
		0%,
		100% {
			transform: scaleY(0.6);
		}
		50% {
			transform: scaleY(1);
		}
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

		.song-title {
			font-size: 18px;
		}
	}
</style>
