<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchAlbums,
		fetchSongs,
		createSong,
		updateSong,
		fetchVersions,
		deleteVersion as apiDeleteVersion,
		fetchSong
	} from '$lib/api/client';
	import {
		albumList,
		songList,
		selectedSong,
		selectSong,
		selectedGeneration
	} from '$lib/stores/player';
	import type { SongItem, VersionItem } from '$lib/api/types';
	import AlbumNav from '$lib/components/AlbumNav.svelte';
	import SongList from '$lib/components/SongList.svelte';
	import ClaudeChat from '$lib/components/ClaudeChat.svelte';
	import GenerationDetail from '$lib/components/GenerationDetail.svelte';
	import LyricsDiff from '$lib/components/LyricsDiff.svelte';
	import VersionTimeline from '$lib/components/VersionTimeline.svelte';
	import type { ApplyData } from '$lib/components/ClaudeChat.svelte';

	let loading = $state(true);
	let error = $state('');
	let showChat = $state(false);
	let saving = $state(false);
	let status = $state('');
	let versions: VersionItem[] = $state([]);
	let currentVersionIndex = $state(0);

	let editLyrics = $state('');
	let editPrompt = $state('');
	let editBpm = $state(0);
	let editDuration = $state(180);
	let editKey = $state('');

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

	let newTitle = $state('');
	let newAlbumId = $state('');
	let showNewSong = $state(false);

	const song = $derived($selectedSong);
	const activeGen = $derived($selectedGeneration);
	const albums = $derived($albumList);

	$effect(() => {
		if (song) loadSongData(song);
	});

	$effect(() => {
		if (!activeGen?.version_id || versions.length === 0) return;
		const idx = versions.findIndex((v) => v.id === activeGen.version_id);
		if (idx !== -1 && idx !== currentVersionIndex) {
			loadVersion(idx);
		}
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

	async function handleDeleteVersion(versionId: string, deleteGenerations: boolean): Promise<void> {
		if (!song) return;
		try {
			await apiDeleteVersion(versionId, deleteGenerations);
			const updated = await fetchSong(song.id);
			songList.update((songs) => songs.map((s) => (s.id === updated.id ? updated : s)));
			await loadVersions(song.id);
		} catch {
			status = 'Delete failed';
			setTimeout(() => (status = ''), 3000);
		}
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
			dismissAppliedDiff();
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

	// --- Diff state (version compare or Claude apply) ---
	let diffBase: VersionItem | null = $state(null);
	let diffTarget: VersionItem | null = $state(null);

	const diffMode = $derived(diffBase !== null && diffTarget !== null);

	function handleDiffChange(pair: [VersionItem, VersionItem] | null): void {
		if (pair) {
			[diffBase, diffTarget] = pair;
		} else {
			diffBase = null;
			diffTarget = null;
		}
	}

	// Applied diff from Claude (synthetic version-like objects)
	let appliedDiffBase: VersionItem | null = $state(null);
	let appliedDiffTarget: VersionItem | null = $state(null);

	const appliedDiffMode = $derived(appliedDiffBase !== null && appliedDiffTarget !== null);

	function handleApply(data: ApplyData): void {
		const before: VersionItem = {
			id: 'before',
			version_number: 0,
			lyrics: editLyrics,
			prompt: editPrompt,
			bpm: editBpm,
			duration: editDuration,
			key: editKey,
			created_at: null
		};
		if (data.lyrics !== undefined) editLyrics = data.lyrics;
		if (data.prompt !== undefined) editPrompt = data.prompt;
		if (data.bpm !== undefined) editBpm = data.bpm;
		if (data.duration !== undefined) editDuration = data.duration;
		if (data.key !== undefined) editKey = data.key;
		const after: VersionItem = {
			id: 'after',
			version_number: 0,
			lyrics: editLyrics,
			prompt: editPrompt,
			bpm: editBpm,
			duration: editDuration,
			key: editKey,
			created_at: null
		};
		appliedDiffBase = before;
		appliedDiffTarget = after;
	}

	function dismissAppliedDiff(): void {
		appliedDiffBase = null;
		appliedDiffTarget = null;
	}

	// Active diff source (version compare takes priority over applied)
	const activeDiff = $derived.by((): { old: VersionItem; new: VersionItem } | null => {
		if (diffBase && diffTarget) return { old: diffBase, new: diffTarget };
		if (appliedDiffBase && appliedDiffTarget)
			return { old: appliedDiffBase, new: appliedDiffTarget };
		return null;
	});

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
							aria-label="Toggle chat"
						>
							💬
						</button>
					</div>
				</div>

				{#if status}
					<div class="status-msg">{status}</div>
				{/if}

				{#if activeGen}
					<GenerationDetail generation={activeGen} />
				{/if}

				<div class="lyrics-edit">
					{#if versions.length > 0}
						<VersionTimeline
							{versions}
							currentIndex={currentVersionIndex}
							dirty={isDirty}
							onselect={loadVersion}
							ondiff={handleDiffChange}
							ondelete={handleDeleteVersion}
						/>
					{/if}

					{#if appliedDiffMode && !diffMode}
						<div class="diff-banner">
							<span>Claude applied changes</span>
						</div>
					{/if}

					{#if activeDiff}
						{@const d = activeDiff}
						{@const isVer = diffMode}
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
									<span class="old">{d.old.bpm}</span> → <span class="new">{d.new.bpm}</span>
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
					{/if}

					{#if isDirty}
						<div class="change-indicator">
							Changed: {changedFields.join(', ')}
						</div>
					{/if}

					<button class="save-btn" onclick={handleSave} disabled={saving || !isDirty}>
						{saving ? 'Saving...' : isDirty ? 'Save New Version' : 'No changes'}
					</button>
				</div>
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

	/* Lyrics editor */
	.lyrics-edit {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.diff-banner {
		display: flex;
		justify-content: space-between;
		align-items: center;
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
