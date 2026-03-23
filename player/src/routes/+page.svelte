<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchAlbums,
		fetchSongs,
		createSong,
		generateSong,
		scoreGeneration
	} from '$lib/api/client';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import {
		albumList,
		songList,
		selectedSong,
		selectSong,
		selectedGeneration,
		clearGenerationSelection
	} from '$lib/stores/player';
	import {
		editLyrics,
		editPrompt,
		editBpm,
		editDuration,
		editKey,
		isDirty,
		versions,
		currentVersionIndex,
		saving,
		status,
		diffMode,
		appliedDiffMode,
		activeDiff,
		loadSongData,
		loadVersion,
		handleSave,
		handleDeleteVersion,
		handleDiffChange,
		handleApply
	} from '$lib/stores/editor';
	import AlbumNav from '$lib/components/AlbumNav.svelte';
	import SongList from '$lib/components/SongList.svelte';
	import ClaudeChat from '$lib/components/ClaudeChat.svelte';
	import GenerationDetail from '$lib/components/GenerationDetail.svelte';
	import LyricsDiff from '$lib/components/LyricsDiff.svelte';
	import VersionTimeline from '$lib/components/VersionTimeline.svelte';

	let loading = $state(true);
	let error = $state('');
	let showChat = $state(false);

	let newTitle = $state('');
	let newAlbumId = $state('');
	let showNewSong = $state(false);
	let creating = $state(false);

	const song = $derived($selectedSong);
	const activeGen = $derived($selectedGeneration);
	const albums = $derived($albumList);
	const dirty = $derived($isDirty);
	const isSaving = $derived($saving);
	const statusMsg = $derived($status);
	const vers = $derived($versions);
	const verIndex = $derived($currentVersionIndex);
	const diff = $derived($activeDiff);
	const isDiffMode = $derived($diffMode);
	const isAppliedDiff = $derived($appliedDiffMode);
	const jobs = $derived($activeJobs);

	const songJobs = $derived(song ? jobs.filter((j) => j.songId === song.id) : []);
	const isGenerating = $derived(
		songJobs.some((j) => j.job.type === 'generate' && j.job.status === 'running')
	);

	let genCount = $state(1);

	$effect(() => {
		if (song) loadSongData(song);
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
		try {
			const job = await generateSong(song.id, genCount);
			trackJob(job, { songId: song.id });
		} catch (e) {
			error = e instanceof Error ? e.message : 'Generation failed';
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

	async function handleCreate(): Promise<void> {
		if (!newTitle.trim() || !newAlbumId) return;
		creating = true;
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
			showNewSong = false;
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
	<aside class="sidebar">
		<header class="sidebar-header">
			<h1>Songmaker</h1>
		</header>
		<AlbumNav />
		<SongList />
		<button class="new-song-btn" onclick={() => (showNewSong = !showNewSong)}> + New Song </button>
	</aside>

	<main class="main-content">
		{#if showNewSong}
			<div class="new-song-form">
				<h2>New Song</h2>
				<div class="new-song-fields">
					<input type="text" bind:value={newTitle} placeholder="Song title" />
					<select bind:value={newAlbumId}>
						<option value="">Select album</option>
						{#each albums as a (a.id)}
							<option value={a.id}>{a.title}</option>
						{/each}
					</select>
					<button onclick={handleCreate} disabled={creating || !newTitle.trim() || !newAlbumId}>
						{creating ? 'Creating...' : 'Create'}
					</button>
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
						{#if dirty && !activeGen}
							<button class="save-btn" onclick={onSave} disabled={isSaving}>
								{isSaving ? 'Saving...' : 'Save'}
							</button>
						{/if}
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
					/>
				{:else}
					<div class="lyrics-edit">
						{#if vers.length > 0}
							<VersionTimeline
								versions={vers}
								currentIndex={verIndex}
								{dirty}
								onselect={loadVersion}
								ondiff={handleDiffChange}
								ondelete={onDeleteVersion}
							/>
						{/if}

						<div class="generate-bar">
							<div class="gen-controls">
								<button
									class="generate-btn"
									onclick={onGenerate}
									disabled={isGenerating || dirty}
									title={dirty ? 'Save changes before generating' : ''}
								>
									{isGenerating ? 'Generating...' : 'Generate'}
								</button>
								<select class="gen-count-select" bind:value={genCount}>
									{#each [1, 2, 3, 5, 10] as n (n)}
										<option value={n}>×{n}</option>
									{/each}
								</select>
							</div>
							{#each songJobs as j (j.job.id)}
								<div class="job-status" class:failed={j.job.status === 'failed'}>
									<span class="job-type">{j.job.type}</span>
									{#if j.job.status === 'running'}
										<span class="job-progress">{Math.round(j.job.progress * 100)}%</span>
									{:else if j.job.status === 'completed'}
										<span class="job-done">Done</span>
									{:else if j.job.status === 'failed'}
										<span class="job-error">{j.job.error || 'Failed'}</span>
									{:else}
										<span class="job-queued">Queued</span>
									{/if}
								</div>
							{/each}
						</div>

						{#if isAppliedDiff && !isDiffMode}
							<div class="diff-banner">
								<span>Claude applied changes</span>
							</div>
						{/if}

						{#if diff}
							{@const d = diff}
							{@const isVer = isDiffMode}
							{@const oldLabel = isVer ? `v${d.old.version_number}` : 'Before'}
							{@const newLabel = isVer ? `v${d.new.version_number}` : 'After'}

							<div class="edit-field">
								<span>Style Prompt {d.old.prompt !== d.new.prompt ? '●' : ''}</span>
								{#if d.old.prompt !== d.new.prompt}
									<LyricsDiff oldText={d.old.prompt} newText={d.new.prompt} {oldLabel} {newLabel} />
								{:else}
									<div class="diff-readonly">{d.new.prompt || '—'}</div>
								{/if}
							</div>

							<div class="params-diff">
								<span class="param-change">
									BPM:
									{#if d.old.bpm !== d.new.bpm}
										<span class="old">{d.old.bpm}</span> →
										<span class="new">{d.new.bpm}</span>
									{:else}
										{d.new.bpm}
									{/if}
								</span>
								<span class="param-change">
									Duration:
									{#if d.old.duration !== d.new.duration}
										<span class="old">{d.old.duration}</span> →
										<span class="new">{d.new.duration}</span>
									{:else}
										{d.new.duration}
									{/if}
								</span>
								<span class="param-change">
									Key:
									{#if d.old.key !== d.new.key}
										<span class="old">{d.old.key || '—'}</span> →
										<span class="new">{d.new.key || '—'}</span>
									{:else}
										{d.new.key || '—'}
									{/if}
								</span>
							</div>

							<div class="edit-field">
								<span>Lyrics {d.old.lyrics !== d.new.lyrics ? '●' : ''}</span>
								{#if d.old.lyrics !== d.new.lyrics}
									<LyricsDiff oldText={d.old.lyrics} newText={d.new.lyrics} {oldLabel} {newLabel} />
								{:else}
									<pre class="diff-readonly lyrics-readonly">{d.new.lyrics || '—'}</pre>
								{/if}
							</div>
						{:else}
							<label class="edit-field" class:changed={$editPrompt !== $editPrompt}>
								<span>Style Prompt</span>
								<textarea rows="4" bind:value={$editPrompt}></textarea>
							</label>

							<div class="params-row">
								<label class="edit-field small">
									<span>BPM</span>
									<input type="number" bind:value={$editBpm} />
								</label>
								<label class="edit-field small">
									<span>Duration</span>
									<input type="number" bind:value={$editDuration} />
								</label>
								<label class="edit-field small">
									<span>Key</span>
									<input type="text" bind:value={$editKey} />
								</label>
							</div>

							<label class="edit-field">
								<span>Lyrics</span>
								<textarea class="lyrics-area" rows="15" bind:value={$editLyrics}></textarea>
							</label>
						{/if}
					</div>
				{/if}
			</div>
		{:else}
			<div class="empty-state">Select a song or create a new one</div>
		{/if}
	</main>

	{#if showChat && song && !activeGen}
		<aside class="chat-panel">
			<ClaudeChat songId={song.id} {songContext} onapply={handleApply} />
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

	.sidebar-header {
		padding: 12px;
		border-bottom: 2px solid var(--primary);
		flex-shrink: 0;
	}

	.sidebar-header h1 {
		font-family: var(--font-display);
		font-size: 24px;
		color: var(--primary);
		letter-spacing: 6px;
		text-transform: uppercase;
	}

	.new-song-btn {
		margin: 8px 12px;
		padding: 8px;
		border: 1px dashed var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 12px;
		cursor: pointer;
		flex-shrink: 0;
	}

	.new-song-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
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

	/* Lyrics editor */
	.lyrics-edit {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.generate-bar {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.gen-controls {
		display: flex;
		gap: 6px;
		align-items: center;
	}

	.generate-btn {
		padding: 6px 16px;
		border: 2px solid var(--score-good);
		border-radius: 16px;
		background: var(--score-good);
		color: #000;
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

	.job-status {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 10px;
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.job-status.failed {
		color: var(--score-bad);
	}

	.job-type {
		color: var(--text-dim);
	}

	.job-progress {
		color: var(--score-ok);
	}

	.job-done {
		color: var(--score-good);
	}

	.job-error {
		color: var(--score-bad);
		font-family: var(--font-body);
		text-transform: none;
	}

	.job-queued {
		color: var(--text-dim);
	}

	.diff-banner {
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 11px;
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.params-diff {
		display: flex;
		gap: 12px;
		flex-wrap: wrap;
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 12px;
	}

	.param-change {
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 11px;
	}

	.param-change .old {
		color: var(--score-bad);
		text-decoration: line-through;
	}

	.param-change .new {
		color: var(--score-good);
	}

	.diff-readonly {
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 13px;
	}

	.lyrics-readonly {
		font-family: 'Courier New', monospace;
		font-size: 14px;
		line-height: 1.6;
		white-space: pre-wrap;
		margin: 0;
		max-height: 300px;
		overflow-y: auto;
	}

	.edit-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.edit-field span {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.edit-field input,
	.edit-field textarea {
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 13px;
	}

	.edit-field input:focus,
	.edit-field textarea:focus {
		border-color: var(--primary);
		outline: none;
	}

	.params-row {
		display: flex;
		gap: 10px;
	}

	.edit-field.small {
		flex: 1;
	}

	.lyrics-area {
		font-family: 'Courier New', monospace;
		font-size: 14px;
		line-height: 1.6;
		min-height: 200px;
		resize: vertical;
	}

	.chat-panel {
		width: 350px;
		min-width: 300px;
		height: 100%;
		flex-shrink: 0;
	}

	.new-song-form {
		padding: 20px;
	}

	.new-song-form h2 {
		font-family: var(--font-display);
		color: var(--primary);
		font-size: 20px;
		margin-bottom: 12px;
		text-transform: uppercase;
	}

	.new-song-fields {
		display: flex;
		gap: 8px;
		max-width: 500px;
	}

	.new-song-fields input,
	.new-song-fields select {
		flex: 1;
		padding: 8px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 13px;
	}

	.new-song-fields button {
		padding: 8px 20px;
		border: 2px solid var(--primary);
		border-radius: 20px;
		background: var(--primary);
		color: #fff;
		font-family: var(--font-display);
		font-size: 12px;
		cursor: pointer;
	}

	.new-song-fields button:disabled {
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
		.sidebar {
			width: 100%;
			height: auto;
			max-height: 40vh;
			min-width: unset;
			border-right: none;
			border-bottom: 1px solid var(--border);
		}

		.chat-panel {
			display: none;
		}
	}
</style>
