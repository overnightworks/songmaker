<script lang="ts">
	import { tick } from 'svelte';
	import {
		streamCoWriterTurn,
		fetchConversations,
		fetchConversationMessages,
		startNewConversation,
		deleteConversation,
		fetchMemory,
		saveUserMemory,
		saveSongMemory,
		saveAlbumMemory,
		fetchCowriterSettings,
		ApiError
	} from '$lib/api/client';
	import type { CoWriterStreamEvent } from '$lib/api/client';
	import type {
		ChatMessageItem,
		ConversationItem,
		MemoryBundle,
		SongItem,
		VersionItem
	} from '$lib/api/types';
	import { addToast } from '$lib/stores/toast';
	import {
		collectPendingProposals,
		proposalKey,
		proposalTargetForMemory,
		stripMemoryProposals,
		type MemoryProposal,
		type MemoryScope
	} from '$lib/utils/memory-proposals';
	import {
		filterMentionItems,
		mentionQueryAtCursor,
		replaceMentionToken,
		type MentionItem
	} from '$lib/utils/mentions';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { playerTakeIdForSong } from '$lib/utils/cowriter-take';
	import {
		cowriterHeaderLabel,
		cowriterThinkingLabel,
		cowriterUnavailableLabel
	} from '$lib/utils/cowriter-ui';
	import ChatInput from './ChatInput.svelte';
	import MemoryEditor from './MemoryEditor.svelte';
	import MentionDropdown from './MentionDropdown.svelte';

	interface Props {
		currentSongId?: string;
		currentAlbumId?: string;
		currentAlbumTitle?: string;
		allSongs?: SongItem[];
		versions?: VersionItem[];
		catalogLoading?: boolean;
		visible?: boolean;
		onturncompleted?: () => void;
	}

	let {
		currentSongId = '',
		currentAlbumId = '',
		currentAlbumTitle = '',
		allSongs = [],
		versions = [],
		catalogLoading = false,
		visible = true,
		onturncompleted
	}: Props = $props();

	interface ToolCall {
		name: string;
		input: Record<string, unknown>;
	}

	interface Message {
		role: 'user' | 'assistant';
		text: string;
		toolCalls?: ToolCall[];
	}

	let messages: Message[] = $state([]);
	let input = $state('');
	let loading = $state(false);
	let historyLoading = $state(false);
	let historyError = $state('');
	let error = $state('');
	let container: HTMLDivElement | undefined = $state();
	let inputEl: HTMLTextAreaElement | undefined = $state();

	let conversations: ConversationItem[] = $state([]);
	let activeConversationId: string | null = $state(null);
	let viewingConversationId: string | null = $state(null);
	let showConversations = $state(false);

	let memoryBundle: MemoryBundle | null = $state(null);
	let memoryLoading = $state(false);
	let memoryError = $state('');
	let memoryRequestId = 0;
	let savingScope: MemoryScope | null = $state(null);
	let rejectedProposalKeys: string[] = $state([]);

	let mentionedSongIds: string[] = $state([]);
	let mentionedVersionIds: string[] = $state([]);
	let mentionedAlbumId: string | null = $state(null);
	let mentionQuery = $state('');
	let showMentions = $state(false);
	let mentionCursorPos = $state(0);
	let selectedMentionIdx = $state(0);
	let providerName = $state('claude');
	let providerModel = $state('');

	$effect(() => {
		void currentSongId;
		mentionedSongIds = [];
		mentionedVersionIds = [];
		mentionedAlbumId = null;
		showMentions = false;
	});

	$effect(() => {
		if (visible) {
			void loadConversations();
			void loadCowriterSettings();
		}
	});

	$effect(() => {
		if (visible) {
			void loadMemory(currentSongId || null);
		}
	});

	async function loadConversations(): Promise<void> {
		try {
			const list = await fetchConversations();
			historyError = '';
			conversations = list;
			const active = list.find((c) => c.archived_at === null);
			const newActiveId = active?.id ?? null;
			if (newActiveId !== activeConversationId) {
				activeConversationId = newActiveId;
				viewingConversationId = newActiveId;
				if (newActiveId) {
					await loadMessages(newActiveId);
				} else {
					messages = [];
				}
			}
		} catch {
			historyError = 'Conversation history unavailable';
		}
	}

	async function loadMessages(conversationId: string): Promise<void> {
		historyLoading = true;
		historyError = '';
		try {
			const result = await fetchConversationMessages(conversationId);
			messages = result.messages.map((m: ChatMessageItem) => ({
				role: m.role as 'user' | 'assistant',
				text: m.content
			}));
		} catch {
			messages = [];
			historyError = 'Conversation history unavailable';
		} finally {
			historyLoading = false;
			void scrollToBottom();
		}
	}

	async function openConversation(conv: ConversationItem): Promise<void> {
		showConversations = false;
		viewingConversationId = conv.id;
		await loadMessages(conv.id);
	}

	async function startNew(): Promise<void> {
		try {
			const conv = await startNewConversation();
			conversations = [conv, ...conversations.filter((c) => c.id !== conv.id)];
			activeConversationId = conv.id;
			viewingConversationId = conv.id;
			messages = [];
			showConversations = false;
		} catch {
			addToast('Failed to start new conversation', 'error');
		}
	}

	async function handleDelete(conv: ConversationItem): Promise<void> {
		try {
			await deleteConversation(conv.id);
			conversations = conversations.filter((c) => c.id !== conv.id);
			if (activeConversationId === conv.id) {
				activeConversationId = null;
			}
			if (viewingConversationId === conv.id) {
				viewingConversationId = activeConversationId;
				if (activeConversationId) {
					await loadMessages(activeConversationId);
				} else {
					messages = [];
				}
			}
		} catch {
			addToast('Failed to delete conversation', 'error');
		}
	}

	async function send(): Promise<void> {
		const msg = input.trim();
		if (!msg || loading) return;
		if (viewingConversationId !== null && viewingConversationId !== activeConversationId) {
			addToast('Viewing an archived conversation — start a new one to reply', 'info');
			return;
		}

		input = '';
		error = '';
		const assistantIndex = messages.length + 1;
		messages = [
			...messages,
			{ role: 'user', text: msg },
			{ role: 'assistant', text: '', toolCalls: [] }
		];
		loading = true;

		let streamError: string | null = null;
		try {
			const playing = audioPlayer.current;
			const currentGenerationId = playerTakeIdForSong(
				currentSongId,
				playing ? { songId: playing.songId, generationId: playing.generation.id } : null
			);
			for await (const event of streamCoWriterTurn({
				message: msg,
				current_song_id: currentSongId || null,
				mentioned_song_ids: mentionedSongIds,
				mentioned_version_ids: mentionedVersionIds,
				mentioned_album_id: mentionedAlbumId,
				current_generation_id: currentGenerationId
			})) {
				applyStreamEvent(assistantIndex, event);
				if (event.type === 'error') {
					streamError = event.message;
					break;
				}
				if (event.type === 'final') {
					if (activeConversationId !== event.conversation_id) {
						activeConversationId = event.conversation_id;
						viewingConversationId = event.conversation_id;
						void loadConversations();
					}
					if (onturncompleted) onturncompleted();
				}
				void scrollToBottom();
			}
		} catch (e) {
			if (e instanceof ApiError && e.status === 503) {
				streamError = e.detail || cowriterUnavailableLabel(providerName);
			} else {
				streamError = e instanceof Error ? e.message : 'Chat failed';
			}
		} finally {
			loading = false;
			if (streamError) {
				error = streamError;
				const current = messages[assistantIndex];
				if (current && !current.text) {
					messages = [...messages.slice(0, assistantIndex), ...messages.slice(assistantIndex + 1)];
				}
			}
			void scrollToBottom();
		}
	}

	function applyStreamEvent(assistantIndex: number, event: CoWriterStreamEvent): void {
		const current = messages[assistantIndex];
		if (!current) return;
		if (event.type === 'assistant_text') {
			messages[assistantIndex] = { ...current, text: current.text + event.text };
			return;
		}
		if (event.type === 'tool_call') {
			const calls = [...(current.toolCalls ?? []), { name: event.name, input: event.input }];
			messages[assistantIndex] = { ...current, toolCalls: calls };
			return;
		}
		if (event.type === 'final') {
			messages[assistantIndex] = {
				...current,
				text: event.assistant_message.content
			};
		}
	}

	async function scrollToBottom(): Promise<void> {
		await tick();
		if (container) container.scrollTop = container.scrollHeight;
	}

	async function loadCowriterSettings(): Promise<void> {
		try {
			const settings = await fetchCowriterSettings();
			providerName = settings.provider;
			providerModel = settings.model;
		} catch {
			/* leave last known labels */
		}
	}

	async function loadMemory(songId: string | null): Promise<void> {
		const requestId = ++memoryRequestId;
		memoryLoading = true;
		memoryError = '';
		try {
			const loaded = await fetchMemory(songId);
			if (requestId === memoryRequestId) memoryBundle = loaded;
		} catch {
			if (requestId === memoryRequestId) {
				memoryBundle = null;
				memoryError = 'Memory unavailable';
			}
		} finally {
			if (requestId === memoryRequestId) memoryLoading = false;
		}
	}

	const pendingProposals = $derived(
		collectPendingProposals(
			messages.filter((msg) => msg.role === 'assistant').map((msg) => msg.text),
			rejectedProposalKeys
		).filter((proposal) => proposalTargetForMemory(proposal, memoryBundle) !== null)
	);

	async function saveMemoryScope(
		scope: MemoryScope,
		targetId: string,
		body: string
	): Promise<boolean> {
		savingScope = scope;
		try {
			if (scope === 'user') {
				const saved = await saveUserMemory(body);
				if (memoryBundle) memoryBundle = { ...memoryBundle, user: saved };
			} else if (scope === 'song') {
				const saved = await saveSongMemory(targetId, body);
				if (memoryBundle) memoryBundle = { ...memoryBundle, song: saved };
			} else {
				const saved = await saveAlbumMemory(targetId, body);
				if (memoryBundle) memoryBundle = { ...memoryBundle, album: saved };
			}
			return true;
		} catch {
			addToast('Failed to save memory', 'error');
			return false;
		} finally {
			savingScope = null;
		}
	}

	async function acceptProposal(proposal: MemoryProposal): Promise<void> {
		const targetId = proposalTargetForMemory(proposal, memoryBundle);
		if (!targetId) {
			addToast('Memory proposal is stale or belongs elsewhere', 'error');
			return;
		}
		const saved = await saveMemoryScope(proposal.scope, targetId, proposal.proposedBody);
		if (saved) {
			rejectedProposalKeys = [...rejectedProposalKeys, proposalKey(proposal)];
		}
	}

	function rejectProposal(proposal: MemoryProposal): void {
		rejectedProposalKeys = [...rejectedProposalKeys, proposalKey(proposal)];
	}

	const activeMentionResults: MentionItem[] = $derived(
		filterMentionItems({
			query: mentionQuery,
			albumMentioned: mentionedAlbumId !== null,
			currentAlbumId,
			currentSongId,
			versions,
			allSongs,
			mentionedSongIds,
			mentionedVersionIds
		})
	);

	const mentionedSongs = $derived(
		mentionedSongIds
			.map((id) => allSongs.find((song) => song.id === id))
			.filter((song): song is SongItem => song !== undefined)
	);

	const mentionedVersions = $derived(
		mentionedVersionIds
			.map((id) => versions.find((version) => version.id === id))
			.filter((version): version is VersionItem => version !== undefined)
	);

	function handleInput(): void {
		if (!inputEl) return;
		const pos = inputEl.selectionStart ?? 0;
		const found = mentionQueryAtCursor(input, pos);
		if (found) {
			mentionQuery = found.query;
			mentionCursorPos = pos;
			showMentions = true;
			selectedMentionIdx = 0;
		} else {
			showMentions = false;
			mentionQuery = '';
		}
	}

	function selectMentionItem(item: MentionItem): void {
		if (!inputEl) return;
		if (item.type === 'album') {
			input = replaceMentionToken(input, mentionCursorPos, '@album ');
			mentionedAlbumId = currentAlbumId || null;
		} else if (item.type === 'version') {
			input = replaceMentionToken(input, mentionCursorPos, `@v${item.item.version_number} `);
			if (!mentionedVersionIds.includes(item.item.id)) {
				mentionedVersionIds = [...mentionedVersionIds, item.item.id];
			}
		} else if (!mentionedSongIds.includes(item.item.id)) {
			input = replaceMentionToken(input, mentionCursorPos, `@${item.item.title} `);
			mentionedSongIds = [...mentionedSongIds, item.item.id];
		}
		showMentions = false;
		mentionQuery = '';
		inputEl.focus();
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (showMentions && (activeMentionResults.length > 0 || catalogLoading)) {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				if (activeMentionResults.length === 0) return;
				selectedMentionIdx = (selectedMentionIdx + 1) % activeMentionResults.length;
				return;
			}
			if (e.key === 'ArrowUp') {
				e.preventDefault();
				if (activeMentionResults.length === 0) return;
				selectedMentionIdx =
					(selectedMentionIdx - 1 + activeMentionResults.length) % activeMentionResults.length;
				return;
			}
			if ((e.key === 'Enter' || e.key === 'Tab') && activeMentionResults.length > 0) {
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
			void send();
		}
	}

	function conversationLabel(conv: ConversationItem): string {
		if (conv.title) return conv.title;
		const when = new Date(conv.created_at).toLocaleDateString();
		return `Conversation ${when}`;
	}

	function currentLabel(): string {
		if (viewingConversationId === null) return 'New conversation';
		const viewing = conversations.find((c) => c.id === viewingConversationId);
		if (!viewing) return 'Conversation';
		if (viewing.archived_at) return `${conversationLabel(viewing)} (archived)`;
		return conversationLabel(viewing);
	}

	const readOnly = $derived(
		viewingConversationId !== null && viewingConversationId !== activeConversationId
	);
</script>

<div class="cowriter">
	<div class="cowriter-header">
		<div class="header-left">
			<h3>
				Co-Writer
				{#if providerModel}
					<span class="provider-label">{cowriterHeaderLabel(providerName, providerModel)}</span>
				{/if}
			</h3>
			<div class="conv-wrapper">
				<button
					class="conv-toggle"
					onclick={() => (showConversations = !showConversations)}
					aria-label="Conversations"
					title={currentLabel()}
				>
					{currentLabel()}
					<span class="caret">▾</span>
				</button>
				{#if showConversations}
					<div class="conv-dropdown">
						<button class="conv-new" onclick={startNew}>+ New conversation</button>
						{#each conversations as conv (conv.id)}
							<div class="conv-row" class:active={conv.id === viewingConversationId}>
								<button class="conv-pick" onclick={() => openConversation(conv)}>
									<span class="conv-title">{conversationLabel(conv)}</span>
									<span class="conv-meta">
										{conv.message_count} msg{conv.message_count === 1 ? '' : 's'}
										{#if conv.archived_at}· archived{/if}
									</span>
								</button>
								<button
									class="conv-del"
									onclick={() => handleDelete(conv)}
									aria-label="Delete conversation">&#x2715;</button
								>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
		<div class="header-actions">
			<button class="new-btn" onclick={startNew} aria-label="New conversation">+ New</button>
		</div>
	</div>

	<MemoryEditor
		bundle={memoryBundle}
		loading={memoryLoading}
		error={memoryError}
		{savingScope}
		proposals={pendingProposals}
		onSave={saveMemoryScope}
		onAccept={acceptProposal}
		onReject={rejectProposal}
	/>

	{#if historyLoading}
		<div class="history-loading">Loading chat…</div>
	{:else if historyError}
		<div class="history-error" role="alert">{historyError}</div>
	{:else}
		<div class="messages" bind:this={container}>
			{#if messages.length === 0}
				<p class="empty-hint">
					I can see the song you have open. Tell me what you want to work on, or ask me to browse
					your other songs — I'll pull them up as needed.
				</p>
			{/if}
			{#each messages as msg, i (i)}
				<div
					class="message"
					class:user={msg.role === 'user'}
					class:assistant={msg.role === 'assistant'}
				>
					{#if msg.role === 'assistant' && msg.toolCalls && msg.toolCalls.length > 0}
						<div class="tool-calls">
							{#each msg.toolCalls as call, ci (ci)}
								<div class="tool-call" title={JSON.stringify(call.input)}>
									<span class="tool-dot" aria-hidden="true">▸</span>
									<span class="tool-name">ran tool: {call.name}</span>
								</div>
							{/each}
						</div>
					{/if}
					{#if msg.text}
						<pre class="message-text">{stripMemoryProposals(msg.text)}</pre>
					{:else if msg.role === 'assistant' && loading && i === messages.length - 1}
						<span class="typing">{cowriterThinkingLabel(providerName)}</span>
					{/if}
				</div>
			{/each}
			{#if error}
				<div class="chat-error">{error}</div>
			{/if}
		</div>
	{/if}

	{#if readOnly}
		<div class="readonly-banner">
			Archived — <button class="link" onclick={startNew}>start a new conversation</button> to reply.
		</div>
	{/if}

	{#if mentionedSongs.length > 0 || mentionedVersions.length > 0 || mentionedAlbumId}
		<div class="mentions-bar">
			{#if mentionedAlbumId}
				<span class="mention-tag album">
					{currentAlbumTitle || 'Album'}
					<button class="mention-remove" onclick={() => (mentionedAlbumId = null)}>&#x2715;</button>
				</span>
			{/if}
			{#each mentionedSongs as song (song.id)}
				<span class="mention-tag">
					{song.title}
					<button
						class="mention-remove"
						onclick={() => (mentionedSongIds = mentionedSongIds.filter((id) => id !== song.id))}
						>&#x2715;</button
					>
				</span>
			{/each}
			{#each mentionedVersions as version (version.id)}
				<span class="mention-tag version">
					v{version.version_number}
					<button
						class="mention-remove"
						onclick={() =>
							(mentionedVersionIds = mentionedVersionIds.filter((id) => id !== version.id))}
						>&#x2715;</button
					>
				</span>
			{/each}
		</div>
	{/if}

	<div class="input-area">
		{#if showMentions}
			<MentionDropdown
				items={activeMentionResults}
				selectedIndex={selectedMentionIdx}
				albumTitle={currentAlbumTitle}
				loading={catalogLoading}
				onselect={selectMentionItem}
			/>
		{/if}
		<ChatInput
			bind:value={input}
			disabled={loading || !input.trim() || readOnly}
			bind:inputRef={inputEl}
			oninput={handleInput}
			onkeydown={handleKeydown}
			onsend={send}
		/>
	</div>
</div>

<style>
	.cowriter {
		display: flex;
		flex-direction: column;
		height: 100%;
		max-height: 100%;
		border-left: 1px solid var(--border);
		background: var(--bg);
	}

	.cowriter-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		gap: 8px;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
		flex: 1;
	}

	.header-left h3 {
		margin: 0;
		font-size: 1rem;
		white-space: nowrap;
		display: inline-flex;
		align-items: baseline;
		gap: 8px;
	}

	.provider-label {
		font-size: 0.75rem;
		font-weight: 400;
		color: var(--text-subtle);
	}

	.conv-wrapper {
		position: relative;
		min-width: 0;
	}

	.conv-toggle {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-subtle);
		font-size: 0.8rem;
		padding: 2px 8px;
		border-radius: 4px;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.conv-toggle:hover {
		border-color: var(--primary);
		color: var(--text);
	}

	.caret {
		font-size: 0.7rem;
		opacity: 0.7;
	}

	.conv-dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		margin-top: 4px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		min-width: 240px;
		max-width: 360px;
		max-height: 360px;
		overflow-y: auto;
		z-index: 10;
		padding: 4px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.conv-new {
		background: none;
		border: 1px solid var(--primary);
		color: var(--primary);
		padding: 4px 8px;
		border-radius: 4px;
		font-size: 0.8rem;
		cursor: pointer;
		margin-bottom: 4px;
	}

	.conv-new:hover {
		background: var(--primary);
		color: #fff;
	}

	.conv-row {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.conv-row.active .conv-pick {
		background: var(--bg);
	}

	.conv-pick {
		flex: 1;
		background: none;
		border: none;
		color: var(--text);
		padding: 4px 6px;
		text-align: left;
		cursor: pointer;
		border-radius: 3px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.conv-pick:hover {
		background: var(--bg);
	}

	.conv-title {
		font-size: 0.85rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.conv-meta {
		font-size: 0.7rem;
		color: var(--text-subtle);
	}

	.conv-del {
		background: none;
		border: none;
		color: var(--text-subtle);
		cursor: pointer;
		padding: 4px 6px;
		font-size: 0.8rem;
	}

	.conv-del:hover {
		color: var(--score-bad);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.new-btn {
		background: none;
		border: 1px solid var(--primary);
		color: var(--primary);
		padding: 2px 10px;
		border-radius: 4px;
		font-size: 0.75rem;
		cursor: pointer;
	}

	.new-btn:hover {
		background: var(--primary);
		color: #fff;
	}

	.history-loading {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--text-subtle);
		font-style: italic;
	}

	.history-error {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--score-bad);
		font-size: 0.8rem;
		padding: 20px;
		text-align: center;
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
		color: var(--text-subtle);
		font-size: 0.85rem;
		text-align: center;
		padding: 20px;
		font-style: italic;
	}

	.message {
		max-width: 90%;
		padding: 8px 12px;
		border-radius: 8px;
		font-size: 1rem;
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
		font-size: 1rem;
		margin: 0;
	}

	.typing {
		color: var(--text-muted);
		font-style: italic;
	}

	.tool-calls {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 6px;
	}

	.tool-call {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 3px 8px;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-family: var(--font-mono, monospace);
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.tool-dot {
		color: var(--accent);
	}

	.tool-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.chat-error {
		color: var(--score-bad);
		font-size: 0.75rem;
		padding: 4px 8px;
	}

	.readonly-banner {
		padding: 6px 12px;
		background: var(--surface);
		color: var(--text-subtle);
		font-size: 0.8rem;
		border-top: 1px solid var(--border);
	}

	.link {
		background: none;
		border: none;
		color: var(--primary);
		cursor: pointer;
		text-decoration: underline;
		padding: 0;
		font-size: inherit;
	}

	.mentions-bar {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		padding: 6px 12px;
		border-top: 1px solid var(--border);
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
		font-size: 0.7rem;
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
		color: var(--text-subtle);
		font-size: 0.7rem;
		cursor: pointer;
		padding: 0;
		line-height: 1;
	}

	.mention-remove:hover {
		color: var(--score-bad);
	}

	.input-area {
		position: relative;
	}
</style>
