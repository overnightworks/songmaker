<script lang="ts">
	import { chatWithClaude, updateSong, ApiError } from '$lib/api/client';
	import { pruneOldChatKeys, trimChatHistory } from '$lib/utils/chat';
	import {
		buildFullContext,
		buildConversation,
		extractApplyData,
		cleanDisplayText,
		isCurrentSong,
		type ApplyData
	} from '$lib/utils/chat-context';
	import { songList } from '$lib/stores/player';
	import { addToast } from '$lib/stores/toast';
	import type { SongItem, VersionItem } from '$lib/api/types';

	interface Props {
		songId?: string;
		songContext?: string;
		allSongs?: SongItem[];
		currentAlbumId?: string;
		versions?: VersionItem[];
		onapply?: (data: ApplyData) => void;
	}

	type ContextScope = 'song' | 'album';

	let {
		songId = '',
		songContext = '',
		allSongs = [],
		currentAlbumId = '',
		versions = [],
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

	let contextScope: ContextScope = $state('song');
	let mentionedSongIds: string[] = $state([]);
	let mentionedVersionNumbers: number[] = $state([]);
	let mentionQuery = $state('');
	let mentionMode: 'song' | 'version' | null = $state(null);
	let showMentions = $state(false);
	let mentionCursorPos = $state(0);
	let selectedMentionIdx = $state(0);

	const VERSION_MENTION_RE = /^v(?:ersion)?\s*(\d*)$/i;

	const mentionResults = $derived.by(() => {
		if (!mentionQuery || mentionMode !== 'song') return [];
		const q = mentionQuery.toLowerCase();
		return allSongs
			.filter(
				(s) =>
					s.title.toLowerCase().includes(q) && s.id !== songId && !mentionedSongIds.includes(s.id)
			)
			.slice(0, 8);
	});

	const versionMentionResults = $derived.by(() => {
		if (!mentionQuery || mentionMode !== 'version') return [];
		const numMatch = mentionQuery.match(VERSION_MENTION_RE);
		const prefix = numMatch?.[1] ?? '';
		return versions
			.filter(
				(v) =>
					!mentionedVersionNumbers.includes(v.version_number) &&
					String(v.version_number).startsWith(prefix)
			)
			.slice(0, 8);
	});

	const activeMentionResults = $derived(
		mentionMode === 'version' ? versionMentionResults : mentionResults
	);

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
			mentionedVersionNumbers = [];
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
			const ctx = buildFullContext(
				songContext,
				songId,
				contextScope,
				currentAlbumId,
				allSongs,
				mentionedSongIds,
				versions,
				mentionedVersionNumbers
			);

			for (let attempt = 0; attempt < 3; attempt++) {
				const conversation = buildConversation(messages, msg);
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

			const applyData = extractApplyData(responseText, currentAlbumId, allSongs);
			const newMsg: Message = { role: 'assistant', text: responseText, applyData };

			if (applyData && isCurrentSong(applyData, songId) && onapply) {
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
		if (isCurrentSong(msg.applyData, songId)) {
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

	function selectVersionMention(v: VersionItem): void {
		if (!inputEl) return;
		const before = input.slice(0, mentionCursorPos);
		const atIdx = before.lastIndexOf('@');
		const after = input.slice(mentionCursorPos);
		input = before.slice(0, atIdx) + after;
		mentionedVersionNumbers = [...mentionedVersionNumbers, v.version_number];
		showMentions = false;
		mentionQuery = '';
		inputEl.focus();
	}

	function removeVersionMention(vn: number): void {
		mentionedVersionNumbers = mentionedVersionNumbers.filter((n) => n !== vn);
	}

	function handleInput(): void {
		if (!inputEl) return;
		const pos = inputEl.selectionStart ?? 0;
		const textBefore = input.slice(0, pos);
		const atMatch = textBefore.match(/@([^@\n]*)$/);
		if (atMatch) {
			mentionQuery = atMatch[1];
			mentionCursorPos = pos;
			mentionMode = VERSION_MENTION_RE.test(mentionQuery) ? 'version' : 'song';
			showMentions = true;
			selectedMentionIdx = 0;
		} else {
			showMentions = false;
			mentionQuery = '';
			mentionMode = null;
		}
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (showMentions && activeMentionResults.length > 0) {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				selectedMentionIdx = (selectedMentionIdx + 1) % activeMentionResults.length;
				return;
			}
			if (e.key === 'ArrowUp') {
				e.preventDefault();
				selectedMentionIdx =
					(selectedMentionIdx - 1 + activeMentionResults.length) % activeMentionResults.length;
				return;
			}
			if (e.key === 'Enter' || e.key === 'Tab') {
				e.preventDefault();
				if (mentionMode === 'version') {
					selectVersionMention(versionMentionResults[selectedMentionIdx]);
				} else {
					selectMention(mentionResults[selectedMentionIdx]);
				}
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

	{#if mentionedSongs.length > 0 || mentionedVersionNumbers.length > 0}
		<div class="mentions-bar">
			{#each mentionedSongs as s (s.id)}
				<span class="mention-tag">
					{s.title}
					<button class="mention-remove" onclick={() => removeMention(s.id)}>✕</button>
				</span>
			{/each}
			{#each mentionedVersionNumbers as vn (vn)}
				<span class="mention-tag version">
					v{vn}
					<button class="mention-remove" onclick={() => removeVersionMention(vn)}>✕</button>
				</span>
			{/each}
		</div>
	{/if}

	<div class="messages" bind:this={container}>
		{#if messages.length === 0}
			<p class="empty-hint">
				Ask Claude to write lyrics, brainstorm ideas, or refine your song. Suggestions auto-apply to
				the editor. Use <strong>@song</strong> to reference other songs or <strong>@v1</strong> for version
				history.
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
								{#if msg.applyData.song && !isCurrentSong(msg.applyData, songId)}
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
		{#if showMentions && activeMentionResults.length > 0}
			<div class="mention-dropdown">
				{#if mentionMode === 'version'}
					{#each versionMentionResults as v, idx (v.id)}
						<button
							class="mention-option"
							class:selected={idx === selectedMentionIdx}
							onclick={() => selectVersionMention(v)}
						>
							<span class="mention-title">v{v.version_number}</span>
							<span class="mention-album">
								{v.created_at ? new Date(v.created_at).toLocaleDateString() : ''}
								{v.prompt ? `· ${v.prompt.slice(0, 40)}` : ''}
							</span>
						</button>
					{/each}
				{:else}
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
				{/if}
			</div>
		{/if}
		<div class="input-row">
			<textarea
				class="chat-input"
				rows="2"
				placeholder="Ask Claude... (@song or @v1 for versions)"
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

	.mention-tag.version {
		border-color: var(--accent);
		color: var(--accent);
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
