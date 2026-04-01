<script lang="ts">
	import { tick } from 'svelte';
	import { chatWithClaude, createSong, updateSong, ApiError } from '$lib/api/client';
	import { pruneOldChatKeys, trimChatHistory } from '$lib/utils/chat';
	import {
		buildFullContext,
		buildConversation,
		extractAllApplyData,
		isCurrentSong,
		type ApplyData
	} from '$lib/utils/chat-context';
	import { songList } from '$lib/stores/player';
	import { addToast } from '$lib/stores/toast';
	import type { SongItem, VersionItem } from '$lib/api/types';
	import MentionDropdown from './MentionDropdown.svelte';
	import MessageList from './MessageList.svelte';
	import ChatInput from './ChatInput.svelte';

	interface Props {
		songId?: string;
		songContext?: string;
		allSongs?: SongItem[];
		currentAlbumId?: string;
		versions?: VersionItem[];
		onapply?: (data: ApplyData) => void;
		oncreate?: (song: SongItem) => void;
	}

	let {
		songId = '',
		songContext = '',
		allSongs = [],
		currentAlbumId = '',
		versions = [],
		onapply,
		oncreate
	}: Props = $props();

	interface Message {
		role: 'user' | 'assistant';
		text: string;
		appliedIndices?: number[];
		applyDataList?: ApplyData[];
	}

	type MentionItem =
		| { type: 'album' }
		| { type: 'version'; item: VersionItem }
		| { type: 'song'; item: SongItem };

	let messages: Message[] = $state([]);
	let input = $state('');
	let loading = $state(false);
	let error = $state('');
	let container: HTMLDivElement | undefined = $state();
	let inputEl: HTMLTextAreaElement | undefined = $state();

	let mentionedSongIds: string[] = $state([]);
	let albumMentioned: boolean = $state(false);
	let mentionedVersionNumbers: number[] = $state([]);
	let mentionQuery = $state('');
	let showMentions = $state(false);
	let mentionCursorPos = $state(0);
	let selectedMentionIdx = $state(0);

	const VERSION_MENTION_RE = /^v(?:ersion)?\s*(\d*)$/i;

	const activeMentionResults: MentionItem[] = $derived.by(() => {
		const results: MentionItem[] = [];

		if (!albumMentioned && currentAlbumId && 'album'.startsWith(mentionQuery.toLowerCase())) {
			results.push({ type: 'album' });
		}

		if (VERSION_MENTION_RE.test(mentionQuery)) {
			const numMatch = mentionQuery.match(VERSION_MENTION_RE);
			const prefix = numMatch?.[1] ?? '';
			const vResults = versions
				.filter(
					(v) =>
						!mentionedVersionNumbers.includes(v.version_number) &&
						String(v.version_number).startsWith(prefix)
				)
				.slice(0, 8);
			results.push(...vResults.map((v) => ({ type: 'version' as const, item: v })));
		}

		if (mentionQuery) {
			const q = mentionQuery.toLowerCase();
			const sResults = allSongs
				.filter(
					(s) =>
						s.title.toLowerCase().includes(q) &&
						s.id !== songId &&
						!mentionedSongIds.includes(s.id)
				)
				.slice(0, 8);
			results.push(...sResults.map((s) => ({ type: 'song' as const, item: s })));
		} else {
			const sResults = allSongs
				.filter((s) => s.id !== songId && !mentionedSongIds.includes(s.id))
				.slice(0, 5);
			results.push(...sResults.map((s) => ({ type: 'song' as const, item: s })));
		}

		return results;
	});

	let prevChatKey = $state('');

	function storageKey(): string {
		return songId ? `songmaker:chat:${songId}` : 'songmaker:chat:new';
	}

	$effect(() => {
		const key = storageKey();
		if (key !== prevChatKey) {
			prevChatKey = key;
			mentionedSongIds = [];
			mentionedVersionNumbers = [];
			albumMentioned = false;
			loadHistory();
		}
	});

	function loadHistory(): void {
		try {
			const saved = localStorage.getItem(storageKey());
			const raw: Message[] = saved ? JSON.parse(saved) : [];
			const parsed = raw.filter((m): m is Message => m != null && typeof m.role === 'string');
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
		const toSave = trimmed.map(({ role, text, appliedIndices, applyDataList }) => ({
			role,
			text,
			appliedIndices,
			applyDataList
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

	async function createNewSong(data: ApplyData): Promise<void> {
		if (!data.title) return;
		const albumId = currentAlbumId;
		if (!albumId) {
			addToast('No album selected for song creation', 'error');
			return;
		}
		try {
			const song = await createSong({
				title: data.title,
				album_id: albumId,
				lyrics: data.lyrics,
				prompt: data.prompt,
				bpm: data.bpm,
				duration: data.duration,
				key: data.key
			});
			songList.update((songs) => [...songs, song]);
			addToast(`Created "${data.title}"`, 'success');
			if (oncreate) oncreate(song);
		} catch {
			addToast(`Failed to create "${data.title}"`, 'error');
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

		const originSongId = songId;
		const originAlbumId = currentAlbumId;
		const originSongs = allSongs;

		try {
			let responseText: string | undefined;
			const ctx = buildFullContext(
				songContext,
				originSongId,
				originAlbumId,
				originSongs,
				mentionedSongIds,
				albumMentioned,
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

			const applyDataList = extractAllApplyData(responseText, originAlbumId, originSongs);
			const newMsg: Message = { role: 'assistant', text: responseText, applyDataList, appliedIndices: [] };

			const switchedAway = songId !== originSongId;

			if (!switchedAway) {
				messages = [...messages, newMsg];
				saveHistory();
			}
		} catch (e) {
			if (songId === originSongId) {
				error = e instanceof Error ? e.message : 'Chat failed';
			}
		} finally {
			loading = false;
			scrollToBottom();
		}
	}

	async function applyAtIndex(msgIndex: number, dataIndex: number): Promise<void> {
		const msg = messages[msgIndex];
		const data = msg?.applyDataList?.[dataIndex];
		if (!data) return;
		if (data.create) {
			await createNewSong(data);
		} else if (isCurrentSong(data, songId)) {
			if (onapply) onapply(data);
		} else {
			await applyCrossSong(data);
		}
		const applied = new Set(msg.appliedIndices ?? []);
		applied.add(dataIndex);
		messages[msgIndex] = { ...msg, appliedIndices: [...applied] };
		saveHistory();
	}

	function clearHistory(): void {
		messages = [];
		localStorage.removeItem(storageKey());
	}

	async function scrollToBottom(): Promise<void> {
		await tick();
		if (container) container.scrollTop = container.scrollHeight;
	}

	$effect(() => {
		messages.length;
		loading;
		scrollToBottom();
	});

	function removeMention(id: string): void {
		mentionedSongIds = mentionedSongIds.filter((sid) => sid !== id);
	}

	function selectMention(song: SongItem): void {
		if (!inputEl) return;
		const before = input.slice(0, mentionCursorPos);
		const atIdx = before.lastIndexOf('@');
		const after = input.slice(mentionCursorPos);
		input = before.slice(0, atIdx) + `@${song.title} ` + after;
		mentionedSongIds = [...mentionedSongIds, song.id];
		showMentions = false;
		mentionQuery = '';
		inputEl.focus();
	}

	function selectAlbumMention(): void {
		if (!inputEl) return;
		const before = input.slice(0, mentionCursorPos);
		const atIdx = before.lastIndexOf('@');
		const after = input.slice(mentionCursorPos);
		input = before.slice(0, atIdx) + '@album ' + after;
		albumMentioned = true;
		showMentions = false;
		mentionQuery = '';
		inputEl.focus();
	}

	function selectVersionMention(v: VersionItem): void {
		if (!inputEl) return;
		const before = input.slice(0, mentionCursorPos);
		const atIdx = before.lastIndexOf('@');
		const after = input.slice(mentionCursorPos);
		input = before.slice(0, atIdx) + `@v${v.version_number} ` + after;
		mentionedVersionNumbers = [...mentionedVersionNumbers, v.version_number];
		showMentions = false;
		mentionQuery = '';
		inputEl.focus();
	}

	function selectMentionItem(item: MentionItem): void {
		if (item.type === 'album') selectAlbumMention();
		else if (item.type === 'version') selectVersionMention(item.item);
		else selectMention(item.item);
	}

	function removeVersionMention(vn: number): void {
		mentionedVersionNumbers = mentionedVersionNumbers.filter((n) => n !== vn);
	}

	function removeAlbumMention(): void {
		albumMentioned = false;
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
				const item = activeMentionResults[selectedMentionIdx];
				if (item) selectMentionItem(item);
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

	const currentAlbumTitle = $derived.by(() => {
		if (!currentAlbumId) return '';
		const albumSong = allSongs.find((s) => s.album_id === currentAlbumId);
		return albumSong?.album_title ?? '';
	});
</script>

<div class="chat">
	<div class="chat-header">
		<h3>Claude Co-Writer</h3>
		<div class="header-actions">
			{#if messages.length > 0}
				<button class="clear-btn" onclick={clearHistory} aria-label="Clear chat">✕</button>
			{/if}
		</div>
	</div>

	{#if mentionedSongs.length > 0 || mentionedVersionNumbers.length > 0 || albumMentioned}
		<div class="mentions-bar">
			{#if albumMentioned}
				<span class="mention-tag album">
					{currentAlbumTitle || 'Album'}
					<button class="mention-remove" onclick={removeAlbumMention}>✕</button>
				</span>
			{/if}
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

	<MessageList
		{messages}
		{loading}
		{error}
		{songId}
		bind:containerRef={container}
		onapply={applyAtIndex}
	/>

	<div class="input-area">
		{#if showMentions && activeMentionResults.length > 0}
			<MentionDropdown
				items={activeMentionResults}
				selectedIndex={selectedMentionIdx}
				albumTitle={currentAlbumTitle}
				onselect={selectMentionItem}
			/>
		{/if}
		<ChatInput
			bind:value={input}
			disabled={loading || !input.trim()}
			bind:inputRef={inputEl}
			oninput={handleInput}
			onkeydown={handleKeydown}
			onsend={send}
		/>
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

	.mention-tag.album {
		border-color: var(--success, #4caf50);
		color: var(--success, #4caf50);
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

	.input-area {
		flex-shrink: 0;
		position: relative;
	}
</style>
