<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchAlbums, fetchSongs, createSong, updateSong, fetchVersions } from '$lib/api/client';
	import {
		albumList,
		songList,
		selectedSong,
		selectSong,
		playGeneration,
		playback
	} from '$lib/stores/player';
	import type { GenerationItem, SongItem, VersionItem } from '$lib/api/types';
	import AlbumNav from '$lib/components/AlbumNav.svelte';
	import SongList from '$lib/components/SongList.svelte';
	import ClaudeChat from '$lib/components/ClaudeChat.svelte';
	import type { ApplyData } from '$lib/components/ClaudeChat.svelte';

	let loading = $state(true);
	let error = $state('');
	let activeTab: 'lyrics' | 'generations' = $state('generations');
	let showChat = $state(false);
	let saving = $state(false);
	let status = $state('');
	let versions: VersionItem[] = $state([]);
	let currentVersionIndex = $state(0);

	// Editable fields
	let editLyrics = $state('');
	let editPrompt = $state('');
	let editBpm = $state(0);
	let editDuration = $state(180);
	let editKey = $state('');

	// Saved state (for dirty tracking)
	let savedLyrics = $state('');
	let savedPrompt = $state('');
	let savedBpm = $state(0);
	let savedDuration = $state(180);
	let savedKey = $state('');

	const isDirty = $derived(
		editLyrics !== savedLyrics ||
			editPrompt !== savedPrompt ||
			editBpm !== savedBpm ||
			editDuration !== savedDuration ||
			editKey !== savedKey
	);

	const changedFields = $derived.by(() => {
		const fields: string[] = [];
		if (editLyrics !== savedLyrics) fields.push('Lyrics');
		if (editPrompt !== savedPrompt) fields.push('Prompt');
		if (editBpm !== savedBpm) fields.push('BPM');
		if (editDuration !== savedDuration) fields.push('Duration');
		if (editKey !== savedKey) fields.push('Key');
		return fields;
	});

	// New song form
	let newTitle = $state('');
	let newAlbumId = $state('');
	let showNewSong = $state(false);

	const song = $derived($selectedSong);
	const pb = $derived($playback);
	const albums = $derived($albumList);

	$effect(() => {
		if (song) loadSongData(song);
	});

	function setSavedState(
		lyrics: string,
		prompt: string,
		bpm: number,
		dur: number,
		key: string
	): void {
		savedLyrics = lyrics;
		savedPrompt = prompt;
		savedBpm = bpm;
		savedDuration = dur;
		savedKey = key;
	}

	function loadSongData(s: SongItem): void {
		editLyrics = s.lyrics;
		editPrompt = s.prompt;
		editBpm = s.bpm;
		editDuration = s.duration;
		editKey = s.key;
		setSavedState(s.lyrics, s.prompt, s.bpm, s.duration, s.key);
		loadVersions(s.id);
	}

	async function loadVersions(songId: string): Promise<void> {
		versions = await fetchVersions(songId);
		currentVersionIndex = 0;
	}

	function loadVersion(index: number): void {
		const v = versions[index];
		if (!v) return;
		currentVersionIndex = index;
		editLyrics = v.lyrics;
		editPrompt = v.prompt;
		editBpm = v.bpm;
		editDuration = v.duration;
		editKey = v.key;
		setSavedState(v.lyrics, v.prompt, v.bpm, v.duration, v.key);
	}

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

	async function handleSave(): Promise<void> {
		if (!song) return;
		saving = true;
		try {
			const updated = await updateSong(song.id, {
				lyrics: editLyrics,
				prompt: editPrompt,
				bpm: editBpm,
				duration: editDuration,
				key: editKey
			});
			setSavedState(editLyrics, editPrompt, editBpm, editDuration, editKey);
			songList.update((songs) => songs.map((s) => (s.id === updated.id ? updated : s)));
			await loadVersions(song.id);
			status = `Saved version ${updated.version_count}`;
		} catch (e) {
			status = e instanceof Error ? e.message : 'Save failed';
		} finally {
			saving = false;
			setTimeout(() => (status = ''), 3000);
		}
	}

	async function handleCreate(): Promise<void> {
		if (!newTitle.trim() || !newAlbumId) return;
		saving = true;
		try {
			const created = await createSong({
				title: newTitle,
				album_id: newAlbumId,
				lyrics: editLyrics,
				prompt: editPrompt,
				bpm: editBpm,
				duration: editDuration,
				key: editKey
			});
			songList.update((songs) => [...songs, created]);
			selectSong(created.id);
			showNewSong = false;
			newTitle = '';
			status = 'Created!';
		} catch (e) {
			status = e instanceof Error ? e.message : 'Create failed';
		} finally {
			saving = false;
			setTimeout(() => (status = ''), 3000);
		}
	}

	function handleApply(data: ApplyData): void {
		if (data.lyrics !== undefined) editLyrics = data.lyrics;
		if (data.prompt !== undefined) editPrompt = data.prompt;
		if (data.bpm !== undefined) editBpm = data.bpm;
		if (data.duration !== undefined) editDuration = data.duration;
		if (data.key !== undefined) editKey = data.key;
	}

	function handlePlayGen(gen: GenerationItem): void {
		if (song) playGeneration(gen, song);
	}

	const songContext = $derived(
		song
			? `Song: ${song.title}\nAlbum: ${song.album_title}\nStyle: ${editPrompt}\nKey: ${editKey}\nBPM: ${editBpm}\n\nLyrics:\n${editLyrics}`
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
					<button onclick={handleCreate} disabled={saving || !newTitle.trim() || !newAlbumId}>
						{saving ? 'Creating...' : 'Create'}
					</button>
				</div>
			</div>
		{:else if song}
			<div class="detail-panel">
				<div class="detail-header">
					<div>
						<h2 class="song-title">{song.title}</h2>
						<span class="song-album">{song.album_title} · {song.artist}</span>
					</div>
					<div class="detail-actions">
						<button
							class="action-btn chat-btn"
							class:active={showChat}
							onclick={() => (showChat = !showChat)}
						>
							💬
						</button>
					</div>
				</div>

				{#if status}
					<div class="status-msg">{status}</div>
				{/if}

				<div class="tabs">
					<button
						class="tab"
						class:active={activeTab === 'generations'}
						onclick={() => (activeTab = 'generations')}
					>
						Generations ({song.generation_count})
					</button>
					<button
						class="tab"
						class:active={activeTab === 'lyrics'}
						onclick={() => (activeTab = 'lyrics')}
					>
						Lyrics
					</button>
				</div>

				{#if activeTab === 'generations'}
					<div class="gen-list">
						{#each song.generations as gen (gen.id)}
							<div class="gen-item" class:playing={pb?.generation.id === gen.id}>
								<button
									class="gen-play"
									onclick={() => handlePlayGen(gen)}
									aria-label="Play generation {gen.generation_number}"
								>
									{pb?.generation.id === gen.id ? '🔊' : '▶'}
								</button>
								<span class="gen-num">gen{gen.generation_number}</span>
								{#if gen.scores?.dynamics}
									<span class="gen-score">D:{gen.scores.dynamics.toFixed(0)}</span>
								{/if}
								{#if gen.scores?.lyrical_coherence}
									<span class="gen-score">L:{gen.scores.lyrical_coherence}</span>
								{/if}
								{#if gen.scores?.audiobox_enjoyment}
									<span class="gen-score">E:{gen.scores.audiobox_enjoyment.toFixed(1)}</span>
								{/if}
								{#if gen.scores?.user_rating}
									<span class="gen-rating">★{gen.scores.user_rating.toFixed(0)}</span>
								{/if}
								{#if gen.seed}
									<span class="gen-seed">seed:{gen.seed}</span>
								{/if}
							</div>
						{:else}
							<p class="empty-gens">No generations yet. Edit lyrics and generate!</p>
						{/each}
					</div>
				{:else}
					<div class="lyrics-edit">
						{#if versions.length > 1}
							<div class="version-nav">
								<button
									onclick={() =>
										loadVersion(Math.min(currentVersionIndex + 1, versions.length - 1))}
									disabled={currentVersionIndex >= versions.length - 1}
								>
									◄
								</button>
								<span>
									v{versions[currentVersionIndex]?.version_number} / {versions.length}
									{#if currentVersionIndex > 0}
										<span class="old-tag">(old)</span>
									{/if}
								</span>
								<button
									onclick={() => loadVersion(Math.max(currentVersionIndex - 1, 0))}
									disabled={currentVersionIndex <= 0}
								>
									►
								</button>
								{#if currentVersionIndex > 0}
									<button class="latest-btn" onclick={() => loadVersion(0)}>Latest</button>
								{/if}
							</div>
						{/if}

						<label class="edit-field" class:changed={editPrompt !== savedPrompt}>
							<span>Style Prompt {editPrompt !== savedPrompt ? '●' : ''}</span>
							<textarea rows="2" bind:value={editPrompt}></textarea>
						</label>

						<div class="params-row">
							<label class="edit-field small" class:changed={editBpm !== savedBpm}>
								<span>BPM {editBpm !== savedBpm ? '●' : ''}</span>
								<input type="number" bind:value={editBpm} />
							</label>
							<label class="edit-field small" class:changed={editDuration !== savedDuration}>
								<span>Duration {editDuration !== savedDuration ? '●' : ''}</span>
								<input type="number" bind:value={editDuration} />
							</label>
							<label class="edit-field small" class:changed={editKey !== savedKey}>
								<span>Key {editKey !== savedKey ? '●' : ''}</span>
								<input type="text" bind:value={editKey} />
							</label>
						</div>

						<label class="edit-field" class:changed={editLyrics !== savedLyrics}>
							<span>Lyrics {editLyrics !== savedLyrics ? '●' : ''}</span>
							<textarea class="lyrics-area" rows="15" bind:value={editLyrics}></textarea>
						</label>

						{#if isDirty}
							<div class="change-indicator">
								Changed: {changedFields.join(', ')}
							</div>
						{/if}

						<button class="save-btn" onclick={handleSave} disabled={saving || !isDirty}>
							{saving ? 'Saving...' : isDirty ? 'Save New Version' : 'No changes'}
						</button>
					</div>
				{/if}
			</div>
		{:else}
			<div class="empty-state">Select a song or create a new one</div>
		{/if}
	</main>

	{#if showChat && song}
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
		padding: 16px 20px;
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

	.song-title {
		font-family: var(--font-display);
		font-size: 22px;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 2px;
	}

	.song-album {
		font-size: 12px;
		color: var(--text-muted);
	}

	.detail-actions {
		display: flex;
		gap: 6px;
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
		font-size: 12px;
		color: var(--success);
	}

	.tabs {
		display: flex;
		gap: 0;
		border-bottom: 1px solid var(--border);
	}

	.tab {
		padding: 8px 20px;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 1px;
		cursor: pointer;
	}

	.tab:hover {
		color: var(--text);
	}

	.tab.active {
		color: var(--primary);
		border-bottom-color: var(--primary);
	}

	/* Generations tab */
	.gen-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.gen-item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px;
		border-radius: 4px;
		font-size: 12px;
	}

	.gen-item:hover {
		background: var(--surface-hover);
	}

	.gen-item.playing {
		background: #1a1a2a;
	}

	.gen-play {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 14px;
	}

	.gen-num {
		font-family: var(--font-display);
		color: var(--text);
		min-width: 40px;
	}

	.gen-score {
		font-size: 10px;
		color: var(--text-muted);
		background: var(--surface);
		padding: 1px 6px;
		border-radius: 3px;
	}

	.gen-rating {
		font-size: 10px;
		color: var(--score-ok);
		font-family: var(--font-display);
	}

	.gen-seed {
		font-size: 9px;
		color: var(--text-dim);
		margin-left: auto;
	}

	.empty-gens {
		color: var(--text-dim);
		font-style: italic;
		padding: 20px;
		text-align: center;
	}

	/* Lyrics tab */
	.lyrics-edit {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.version-nav {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		background: var(--surface);
		border-radius: 4px;
		font-size: 12px;
		color: var(--text-muted);
	}

	.version-nav button {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-muted);
		padding: 2px 8px;
		border-radius: 3px;
		cursor: pointer;
	}

	.version-nav button:disabled {
		opacity: 0.3;
	}

	.old-tag {
		color: var(--score-ok);
		font-size: 10px;
	}

	.latest-btn {
		margin-left: auto;
		border-color: var(--score-ok) !important;
		color: var(--score-ok) !important;
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

	.edit-field.changed span {
		color: var(--score-ok);
	}

	.edit-field.changed input,
	.edit-field.changed textarea {
		border-color: var(--score-ok);
	}

	.change-indicator {
		font-size: 11px;
		color: var(--score-ok);
		padding: 4px 0;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.save-btn {
		padding: 8px 24px;
		border: 2px solid var(--primary);
		border-radius: 20px;
		background: var(--primary);
		color: #fff;
		font-family: var(--font-display);
		font-size: 13px;
		letter-spacing: 1px;
		text-transform: uppercase;
		cursor: pointer;
		align-self: flex-start;
	}

	.save-btn:disabled {
		opacity: 0.4;
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
