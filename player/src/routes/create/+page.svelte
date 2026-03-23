<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchAlbums } from '$lib/api/client';
	import { createSong, updateSong, type SongDetail } from '$lib/api/songs';
	import type { AlbumItem } from '$lib/api/types';
	import ClaudeChat from '$lib/components/ClaudeChat.svelte';
	import type { ApplyData } from '$lib/components/ClaudeChat.svelte';

	let albums: AlbumItem[] = $state([]);
	let showChat = $state(false);
	let saving = $state(false);
	let status = $state('');
	let song: SongDetail | null = $state(null);

	let title = $state('');
	let albumId = $state('');
	let lyrics = $state('');
	let prompt = $state('');
	let bpm = $state(120);
	let duration = $state(180);
	let key = $state('');
	let language = $state('');

	interface RevisionItem {
		id: string;
		index: number;
		total: number;
		lyrics: string;
		prompt: string;
		bpm: number;
		duration: number;
		key: string;
		created_at: string | null;
	}

	let revisions: RevisionItem[] = $state([]);
	let currentRevIndex = $state(0);

	onMount(async () => {
		albums = await fetchAlbums();
		if (albums.length > 0) albumId = albums[0].id;
	});

	async function save(): Promise<void> {
		if (!title.trim() || !albumId) return;
		saving = true;
		status = '';
		try {
			if (song) {
				song = await updateSong(song.id, { lyrics, prompt, bpm, duration, key });
				status = `Saved revision ${song.revision_count}`;
			} else {
				song = await createSong({
					title,
					album_id: albumId,
					lyrics,
					prompt,
					bpm,
					duration,
					key,
					language
				});
				status = 'Created!';
			}
			await loadRevisions();
		} catch (e) {
			status = e instanceof Error ? e.message : 'Save failed';
		} finally {
			saving = false;
			setTimeout(() => (status = ''), 3000);
		}
	}

	async function loadRevisions(): Promise<void> {
		if (!song) return;
		const resp = await fetch(`/api/songs/${song.id}/revisions`);
		if (resp.ok) {
			revisions = await resp.json();
			currentRevIndex = 0;
		}
	}

	function loadRevision(index: number): void {
		const rev = revisions[index];
		if (!rev) return;
		currentRevIndex = index;
		lyrics = rev.lyrics;
		prompt = rev.prompt;
		bpm = rev.bpm;
		duration = rev.duration;
		key = rev.key;
	}

	function handleApply(data: ApplyData): void {
		if (data.lyrics !== undefined) lyrics = data.lyrics;
		if (data.prompt !== undefined) prompt = data.prompt;
		if (data.bpm !== undefined) bpm = data.bpm;
		if (data.duration !== undefined) duration = data.duration;
		if (data.key !== undefined) key = data.key;
	}

	const songContext = $derived(
		`Song: ${title}\nAlbum: ${albumId}\nStyle: ${prompt}\nKey: ${key}\nBPM: ${bpm}\n\nLyrics:\n${lyrics}`
	);

	const isLatestRevision = $derived(currentRevIndex === 0);
</script>

<div class="create-page">
	<div class="editor-panel">
		<header class="editor-header">
			<h1>{song ? 'Edit Song' : 'Create Song'}</h1>
			<div class="header-actions">
				<button class="save-btn" onclick={save} disabled={saving || !title.trim()}>
					{saving ? 'Saving...' : song ? 'Save Revision' : 'Create'}
				</button>
				<button class="chat-btn" class:active={showChat} onclick={() => (showChat = !showChat)}>
					💬 Claude
				</button>
			</div>
		</header>

		{#if status}
			<div class="status">{status}</div>
		{/if}

		{#if revisions.length > 1}
			<div class="revision-nav">
				<button
					class="rev-btn"
					onclick={() => loadRevision(Math.min(currentRevIndex + 1, revisions.length - 1))}
					disabled={currentRevIndex >= revisions.length - 1}
					aria-label="Older revision"
				>
					◄
				</button>
				<span class="rev-label">
					Rev {revisions[currentRevIndex]?.index ?? '?'} / {revisions[0]?.total ?? '?'}
					{#if !isLatestRevision}
						<span class="rev-old">(old)</span>
					{/if}
				</span>
				<button
					class="rev-btn"
					onclick={() => loadRevision(Math.max(currentRevIndex - 1, 0))}
					disabled={currentRevIndex <= 0}
					aria-label="Newer revision"
				>
					►
				</button>
				{#if !isLatestRevision}
					<button class="restore-btn" onclick={() => loadRevision(0)}> Back to latest </button>
				{/if}
			</div>
		{/if}

		<div class="form-grid">
			<label class="field">
				<span>Title</span>
				<input type="text" bind:value={title} placeholder="Song title" disabled={!!song} />
			</label>

			<label class="field">
				<span>Album</span>
				<select bind:value={albumId} disabled={!!song}>
					{#each albums as a (a.id)}
						<option value={a.id}>{a.title}</option>
					{/each}
				</select>
			</label>

			<label class="field">
				<span>Style Prompt</span>
				<textarea
					rows="3"
					bind:value={prompt}
					placeholder="e.g. heavy 808, male rapper, soulful chorus..."
				></textarea>
			</label>

			<div class="params-row">
				<label class="field small">
					<span>BPM</span>
					<input type="number" bind:value={bpm} min="0" max="300" />
				</label>
				<label class="field small">
					<span>Duration (s)</span>
					<input type="number" bind:value={duration} min="30" max="600" />
				</label>
				<label class="field small">
					<span>Key</span>
					<input type="text" bind:value={key} placeholder="Am" />
				</label>
				<label class="field small">
					<span>Language</span>
					<input type="text" bind:value={language} placeholder="en" />
				</label>
			</div>
		</div>

		<div class="lyrics-editor">
			<div class="lyrics-label">
				<span>Lyrics</span>
				<span class="lyrics-hint">Use [verse], [chorus], [bridge] for sections</span>
			</div>
			<textarea
				class="lyrics-textarea"
				bind:value={lyrics}
				placeholder="[verse]&#10;First line of your song...&#10;&#10;[chorus]&#10;The hook goes here..."
				rows="20"
				aria-label="Lyrics"
			></textarea>
		</div>
	</div>

	{#if showChat}
		<aside class="chat-panel">
			<ClaudeChat {songContext} onapply={handleApply} />
		</aside>
	{/if}
</div>

<style>
	.create-page {
		display: flex;
		height: 100%;
		overflow: hidden;
	}

	.editor-panel {
		flex: 1;
		overflow-y: auto;
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.editor-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.editor-header h1 {
		font-family: var(--font-display);
		font-size: 24px;
		color: var(--primary);
		text-transform: uppercase;
		letter-spacing: 4px;
	}

	.header-actions {
		display: flex;
		gap: 8px;
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
	}

	.save-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.chat-btn {
		padding: 8px 20px;
		border: 2px solid var(--border);
		border-radius: 20px;
		background: transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 13px;
		letter-spacing: 1px;
		text-transform: uppercase;
		cursor: pointer;
	}

	.chat-btn.active {
		border-color: var(--primary);
		color: var(--primary);
	}

	.status {
		font-size: 12px;
		color: var(--success);
		padding: 4px 0;
	}

	.revision-nav {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
	}

	.rev-btn {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-muted);
		padding: 2px 8px;
		border-radius: 3px;
		font-size: 12px;
		cursor: pointer;
	}

	.rev-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}

	.rev-btn:hover:not(:disabled) {
		border-color: var(--primary);
		color: var(--text);
	}

	.rev-label {
		font-size: 12px;
		font-family: var(--font-display);
		color: var(--text-muted);
	}

	.rev-old {
		color: var(--score-ok);
		font-size: 10px;
	}

	.restore-btn {
		background: none;
		border: 1px solid var(--score-ok);
		color: var(--score-ok);
		padding: 2px 10px;
		border-radius: 3px;
		font-size: 10px;
		cursor: pointer;
		margin-left: auto;
	}

	.restore-btn:hover {
		background: var(--score-ok);
		color: #000;
	}

	.form-grid {
		display: flex;
		flex-direction: column;
		gap: 10px;
		max-width: 700px;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.field span {
		font-size: 11px;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 1px;
		font-family: var(--font-display);
	}

	.field input,
	.field select,
	.field textarea {
		padding: 8px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 13px;
	}

	.field input:focus,
	.field select:focus,
	.field textarea:focus {
		border-color: var(--primary);
		outline: none;
	}

	.field textarea {
		resize: vertical;
	}

	.params-row {
		display: flex;
		gap: 12px;
	}

	.field.small {
		flex: 1;
	}

	.field.small input {
		width: 100%;
	}

	.lyrics-editor {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 4px;
		max-width: 700px;
	}

	.lyrics-label {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}

	.lyrics-label span {
		font-size: 11px;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 1px;
		font-family: var(--font-display);
	}

	.lyrics-hint {
		font-size: 10px !important;
		color: var(--text-dim) !important;
		text-transform: none !important;
		letter-spacing: 0 !important;
		font-family: var(--font-body) !important;
	}

	.lyrics-textarea {
		flex: 1;
		min-height: 300px;
		padding: 12px 16px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-family: 'Courier New', monospace;
		font-size: 14px;
		line-height: 1.6;
		resize: vertical;
	}

	.lyrics-textarea:focus {
		border-color: var(--primary);
		outline: none;
	}

	.lyrics-textarea::placeholder {
		color: var(--text-dim);
	}

	.chat-panel {
		width: 350px;
		min-width: 300px;
		height: 100%;
		flex-shrink: 0;
	}

	@media (max-width: 768px) {
		.params-row {
			flex-wrap: wrap;
		}

		.chat-panel {
			display: none;
		}
	}
</style>
