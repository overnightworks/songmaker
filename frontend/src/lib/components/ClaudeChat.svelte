<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { claudeApiKey } from '$lib/stores/settings';
	import { chatWithClaude, updateSong, ApiError } from '$lib/api/client';
	import { pruneOldChatKeys, trimChatHistory } from '$lib/utils/chat';
	import { songList } from '$lib/stores/player';
	import { addToast } from '$lib/stores/toast';
	import type { SongItem } from '$lib/api/types';

	interface Props {
		songId?: string;
		songContext?: string;
		allSongs?: SongItem[];
		currentAlbumId?: string;
		onapply?: (data: ApplyData) => void;
	}

	export interface ApplyData {
		song?: string;
		songId?: string;
		lyrics?: string;
		prompt?: string;
		bpm?: number;
		duration?: number;
		key?: string;
	}

	type ContextScope = 'song' | 'album';

	let {
		songId = '',
		songContext = '',
		allSongs = [],
		currentAlbumId = '',
		onapply
	}: Props = $props();

	interface Message {
		role: 'user' | 'assistant';
		text: string;
		applied?: boolean;
		applyData?: ApplyData;
	}

	let messages: Message[] = $state([]);
	let input = $state('');
	let loading = $state(false);
	let error = $state('');
	let container: HTMLDivElement | undefined = $state();
	let inputEl: HTMLTextAreaElement | undefined = $state();
	const hasKey = $derived(!!$claudeApiKey);

	let contextScope: ContextScope = $state('song');
	let mentionedSongIds: string[] = $state([]);
	let mentionQuery = $state('');
	let showMentions = $state(false);
	let mentionCursorPos = $state(0);
	let selectedMentionIdx = $state(0);

	const mentionResults = $derived.by(() => {
		if (!mentionQuery) return [];
		const q = mentionQuery.toLowerCase();
		return allSongs
			.filter(
				(s) =>
					s.title.toLowerCase().includes(q) && s.id !== songId && !mentionedSongIds.includes(s.id)
			)
			.slice(0, 8);
	});

	let prevChatKey = $state('');

	function storageKey(): string {
		if (contextScope === 'album' && currentAlbumId) {
			return `songmaker:chat:album:${currentAlbumId}`;
		}
		return songId ? `songmaker:chat:${songId}` : 'songmaker:chat:new';
	}

	$effect(() => {
		const key = storageKey();
		if (key !== prevChatKey) {
			prevChatKey = key;
			loadHistory();
		}
	});

	function loadHistory(): void {
		try {
			const saved = localStorage.getItem(storageKey());
			const parsed: Message[] = saved ? JSON.parse(saved) : [];
			const trimmed = trimChatHistory(parsed);
			messages = trimmed;
			if (trimmed.length < parsed.length) {
				saveHistory();
			}
		} catch {
			messages = [];
		}
	}

	function saveHistory(): void {
		const trimmed = trimChatHistory(messages);
		const toSave = trimmed.map(({ role, text, applied, applyData }) => ({
			role,
			text,
			applied,
			applyData
		}));
		localStorage.setItem(storageKey(), JSON.stringify(toSave));
		pruneOldChatKeys();
	}

	function formatSongContext(s: SongItem): string {
		const parts = [`[Track ${s.track_number}] ${s.title}`];
		if (s.prompt) parts.push(`Style: ${s.prompt}`);
		const meta: string[] = [];
		if (s.key) meta.push(`Key: ${s.key}`);
		if (s.bpm) meta.push(`BPM: ${s.bpm}`);
		if (s.duration) meta.push(`Duration: ${s.duration}s`);
		if (meta.length) parts.push(meta.join(' | '));
		if (s.lyrics) parts.push(`Lyrics:\n${s.lyrics}`);
		return parts.join('\n');
	}

	function buildFullContext(): string {
		const parts: string[] = [];

		if (songContext) {
			parts.push(`[Current Song]\n${songContext}`);
		}

		const extraSongs: SongItem[] = [];

		if (contextScope === 'album' && currentAlbumId) {
			const albumSongs = allSongs
				.filter((s) => s.album_id === currentAlbumId && s.id !== songId)
				.sort((a, b) => a.track_number - b.track_number);
			extraSongs.push(...albumSongs);
		}

		for (const id of mentionedSongIds) {
			if (!extraSongs.some((s) => s.id === id)) {
				const s = allSongs.find((s) => s.id === id);
				if (s) extraSongs.push(s);
			}
		}

		if (extraSongs.length > 0) {
			parts.push('--- Other songs ---\n\n' + extraSongs.map(formatSongContext).join('\n\n'));
		}

		return parts.join('\n\n');
	}

	function buildConversation(newMessage: string): string {
		const parts: string[] = [];
		for (const msg of messages) {
			const prefix = msg.role === 'user' ? 'User' : 'Assistant';
			parts.push(`${prefix}: ${cleanDisplayText(msg.text)}`);
		}
		parts.push(`User: ${newMessage}`);
		return parts.join('\n\n');
	}

	function extractApplyData(text: string): ApplyData | undefined {
		const match = text.match(/```songmaker\s*\n([\s\S]*?)```/);
		if (!match) return undefined;
		try {
			const raw = JSON.parse(match[1].trim());
			const data: ApplyData = {};
			if (typeof raw.lyrics === 'string' && raw.lyrics.length <= 50_000) data.lyrics = raw.lyrics;
			if (typeof raw.prompt === 'string' && raw.prompt.length <= 5_000) data.prompt = raw.prompt;
			if (typeof raw.key === 'string' && raw.key.length <= 10) data.key = raw.key;
			if (typeof raw.bpm === 'number' && raw.bpm >= 0 && raw.bpm <= 999) data.bpm = raw.bpm;
			if (typeof raw.duration === 'number' && raw.duration >= 1 && raw.duration <= 600)
				data.duration = raw.duration;
			if (typeof raw.song === 'string') {
				data.song = raw.song;
				const q = raw.song.toLowerCase();
				const albumMatch = currentAlbumId
					? allSongs.find((s) => s.title.toLowerCase() === q && s.album_id === currentAlbumId)
					: undefined;
				const target = albumMatch ?? allSongs.find((s) => s.title.toLowerCase() === q);
				if (target) data.songId = target.id;
			}
			return Object.keys(data).filter((k) => k !== 'song' && k !== 'songId').length > 0
				? data
				: undefined;
		} catch {
			return undefined;
		}
	}

	function isCurrentSong(data: ApplyData): boolean {
		return !data.songId || data.songId === songId;
	}

	async function applyCrossSong(data: ApplyData): Promise<void> {
		if (!data.songId || !data.song) return;
		try {
			const updated = await updateSong(data.songId, {
				lyrics: data.lyrics,
				prompt: data.prompt,
				bpm: data.bpm,
				duration: data.duration,
				key: data.key
			});
			songList.update((songs) => songs.map((s) => (s.id === updated.id ? updated : s)));
			addToast(`Applied to ${data.song}`, 'success');
		} catch {
			addToast(`Failed to apply to ${data.song}`, 'error');
		}
	}

	function cleanDisplayText(text: string): string {
		return text.replace(/```songmaker\s*\n[\s\S]*?```/, '').trim();
	}

	async function send(): Promise<void> {
		const msg = input.trim();
		if (!msg || loading) return;

		input = '';
		error = '';
		showMentions = false;
		messages = [...messages, { role: 'user', text: msg }];
		loading = true;

		try {
			let responseText: string | undefined;
			const ctx = buildFullContext();

			for (let attempt = 0; attempt < 3; attempt++) {
				const conversation = buildConversation(msg);
				try {
					responseText = await chatWithClaude(conversation, ctx);
					break;
				} catch (e) {
					if (e instanceof ApiError && e.status === 422 && messages.length > 1) {
						const half = Math.max(1, Math.floor(messages.length / 2));
						messages = messages.slice(half);
						saveHistory();
						continue;
					}
					throw e;
				}
			}

			if (!responseText) throw new Error('Chat failed after trimming history');

			const applyData = extractApplyData(responseText);
			const newMsg: Message = { role: 'assistant', text: responseText, applyData };

			if (applyData && isCurrentSong(applyData) && onapply) {
				onapply(applyData);
				newMsg.applied = true;
			}

			messages = [...messages, newMsg];
			saveHistory();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Chat failed';
		} finally {
			loading = false;
			scrollToBottom();
		}
	}

	async function applyMessage(index: number): Promise<void> {
		const msg = messages[index];
		if (!msg?.applyData) return;
		if (isCurrentSong(msg.applyData)) {
			if (onapply) onapply(msg.applyData);
		} else {
			await applyCrossSong(msg.applyData);
		}
		messages[index] = { ...msg, applied: true };
		saveHistory();
	}

	function clearHistory(): void {
		messages = [];
		localStorage.removeItem(storageKey());
	}

	function scrollToBottom(): void {
		setTimeout(() => {
			if (container) container.scrollTop = container.scrollHeight;
		}, 50);
	}

	function removeMention(id: string): void {
		mentionedSongIds = mentionedSongIds.filter((sid) => sid !== id);
	}

	function selectMention(song: SongItem): void {
		if (!inputEl) return;
		const before = input.slice(0, mentionCursorPos);
		const atIdx = before.lastIndexOf('@');
		const after = input.slice(mentionCursorPos);
		input = before.slice(0, atIdx) + after;
		mentionedSongIds = [...mentionedSongIds, song.id];
		showMentions = false;
		mentionQuery = '';
		inputEl.focus();
	}

	function handleInput(): void {
		if (!inputEl) return;
		const pos = inputEl.selectionStart ?? 0;
		const textBefore = input.slice(0, pos);
		const atMatch = textBefore.match(/@([^@\n]*)$/);
		if (atMatch) {
			mentionQuery = atMatch[1];
			mentionCursorPos = pos;
			showMentions = true;
			selectedMentionIdx = 0;
		} else {
			showMentions = false;
			mentionQuery = '';
		}
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (showMentions && mentionResults.length > 0) {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				selectedMentionIdx = (selectedMentionIdx + 1) % mentionResults.length;
				return;
			}
			if (e.key === 'ArrowUp') {
				e.preventDefault();
				selectedMentionIdx =
					(selectedMentionIdx - 1 + mentionResults.length) % mentionResults.length;
				return;
			}
			if (e.key === 'Enter' || e.key === 'Tab') {
				e.preventDefault();
				selectMention(mentionResults[selectedMentionIdx]);
				return;
			}
			if (e.key === 'Escape') {
				e.preventDefault();
				showMentions = false;
				return;
			}
		}
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			send();
		}
	}

	const mentionedSongs = $derived(
		mentionedSongIds
			.map((id) => allSongs.find((s) => s.id === id))
			.filter((s): s is SongItem => !!s)
	);
</script>

<div class="chat">
	<div class="chat-header">
		<h3>Claude Co-Writer</h3>
		<div class="header-actions">
			<div class="scope-toggle">
				<button
					class="scope-btn"
					class:active={contextScope === 'song'}
					onclick={() => (contextScope = 'song')}>Song</button
				>
				<button
					class="scope-btn"
					class:active={contextScope === 'album'}
					onclick={() => (contextScope = 'album')}>Album</button
				>
			</div>
			{#if messages.length > 0}
				<button class="clear-btn" onclick={clearHistory} aria-label="Clear chat">✕</button>
			{/if}
		</div>
	</div>

	{#if !hasKey}
		<div class="key-hint">
			<a href="/settings/integrations">Configure API key in Settings</a>
		</div>
	{/if}

	{#if mentionedSongs.length > 0}
		<div class="mentions-bar">
			{#each mentionedSongs as s (s.id)}
				<span class="mention-tag">
					{s.title}
					<button class="mention-remove" onclick={() => removeMention(s.id)}>✕</button>
				</span>
			{/each}
		</div>
	{/if}

	<div class="messages" bind:this={container}>
		{#if messages.length === 0}
			<p class="empty-hint">
				Ask Claude to write lyrics, brainstorm ideas, or refine your song. Suggestions auto-apply to
				the editor. Use <strong>@song name</strong> to reference other songs.
			</p>
		{/if}
		{#each messages as msg, i (i)}
			<div
				class="message"
				class:user={msg.role === 'user'}
				class:assistant={msg.role === 'assistant'}
			>
				<pre class="message-text">{cleanDisplayText(msg.text)}</pre>
				{#if msg.role === 'assistant' && msg.applyData}
					<div class="apply-row">
						{#if msg.applied}
							<span class="applied-badge"
								>✓ Applied{msg.applyData.song ? ` to ${msg.applyData.song}` : ''}</span
							>
						{:else}
							<button class="apply-btn" onclick={() => applyMessage(i)}>
								{#if msg.applyData.song && !isCurrentSong(msg.applyData)}
									Apply to {msg.applyData.song}
								{:else}
									Apply to editor
								{/if}
							</button>
						{/if}
					</div>
				{/if}
			</div>
		{/each}
		{#if loading}
			<div class="message assistant">
				<span class="typing">Thinking...</span>
			</div>
		{/if}
		{#if error}
			<div class="chat-error">{error}</div>
		{/if}
	</div>

	<div class="input-area">
		{#if showMentions && mentionResults.length > 0}
			<div class="mention-dropdown">
				{#each mentionResults as s, idx (s.id)}
					<button
						class="mention-option"
						class:selected={idx === selectedMentionIdx}
						onclick={() => selectMention(s)}
					>
						<span class="mention-title">{s.title}</span>
						<span class="mention-album">{s.album_title}</span>
					</button>
				{/each}
			</div>
		{/if}
		<div class="input-row">
			<textarea
				class="chat-input"
				rows="2"
				placeholder="Ask Claude... (@song to reference)"
				bind:value={input}
				bind:this={inputEl}
				onkeydown={handleKeydown}
				oninput={handleInput}
			></textarea>
			<button class="send-btn" onclick={send} disabled={loading || !input.trim()} aria-label="Send">
				↑
			</button>
		</div>
	</div>
</div>

<style>
	.chat {
		display: flex;
		flex-direction: column;
		height: 100%;
		max-height: 100%;
		border-left: 1px solid var(--border);
		overflow: hidden;
	}

	.chat-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.chat-header h3 {
		font-family: var(--font-display);
		font-size: 13px;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.header-actions {
		display: flex;
		gap: 4px;
		align-items: center;
	}

	.scope-toggle {
		display: flex;
		border: 1px solid var(--border);
		border-radius: 4px;
		overflow: hidden;
	}

	.scope-btn {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 9px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 2px 8px;
		cursor: pointer;
	}

	.scope-btn.active {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
	}

	.clear-btn {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 12px;
		cursor: pointer;
		padding: 2px 6px;
	}

	.clear-btn:hover {
		color: var(--score-bad);
	}

	.key-hint {
		padding: 6px 12px;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
		font-size: 10px;
	}

	.key-hint a {
		color: var(--text-dim);
		text-decoration: none;
	}

	.key-hint a:hover {
		color: var(--primary);
	}

	.mentions-bar {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		padding: 6px 12px;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.mention-tag {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		background: var(--surface);
		border: 1px solid var(--primary);
		color: var(--primary);
		padding: 1px 8px;
		border-radius: 10px;
		font-size: 10px;
	}

	.mention-remove {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 10px;
		cursor: pointer;
		padding: 0;
		line-height: 1;
	}

	.mention-remove:hover {
		color: var(--score-bad);
	}

	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 8px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.empty-hint {
		color: var(--text-dim);
		font-size: 12px;
		text-align: center;
		padding: 20px;
		font-style: italic;
	}

	.message {
		max-width: 90%;
		padding: 8px 12px;
		border-radius: 8px;
		font-size: 12px;
		line-height: 1.5;
	}

	.message.user {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		align-self: flex-end;
		border-bottom-right-radius: 2px;
	}

	.message.assistant {
		background: var(--surface);
		color: var(--text);
		align-self: flex-start;
		border-bottom-left-radius: 2px;
	}

	.message-text {
		white-space: pre-wrap;
		font-family: var(--font-body);
		font-size: 12px;
		margin: 0;
	}

	.apply-row {
		margin-top: 6px;
		padding-top: 6px;
		border-top: 1px solid var(--border);
	}

	.apply-btn {
		background: none;
		border: 1px solid var(--primary);
		color: var(--primary);
		padding: 3px 12px;
		border-radius: 12px;
		font-size: 10px;
		cursor: pointer;
	}

	.apply-btn:hover {
		background: var(--primary);
		color: #fff;
	}

	.applied-badge {
		color: var(--success);
		font-size: 10px;
	}

	.typing {
		color: var(--text-muted);
		font-style: italic;
	}

	.chat-error {
		color: var(--score-bad);
		font-size: 11px;
		padding: 4px 8px;
	}

	.input-area {
		flex-shrink: 0;
		position: relative;
	}

	.mention-dropdown {
		position: absolute;
		bottom: 100%;
		left: 8px;
		right: 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		max-height: 200px;
		overflow-y: auto;
		box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.3);
		z-index: 10;
	}

	.mention-option {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: 6px 12px;
		background: none;
		border: none;
		color: var(--text);
		font-size: 12px;
		cursor: pointer;
		text-align: left;
	}

	.mention-option:hover,
	.mention-option.selected {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
	}

	.mention-title {
		font-weight: 500;
	}

	.mention-album {
		font-size: 10px;
		opacity: 0.6;
	}

	.input-row {
		display: flex;
		gap: 6px;
		padding: 8px;
		border-top: 1px solid var(--border);
	}

	.chat-input {
		flex: 1;
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 12px;
		resize: none;
	}

	.chat-input:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.send-btn {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		border: 2px solid var(--primary);
		background: transparent;
		color: var(--primary);
		font-size: 16px;
		flex-shrink: 0;
		align-self: flex-end;
	}

	.send-btn:hover:not(:disabled) {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		border-color: transparent;
		color: #fff;
	}

	.send-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
</style>
