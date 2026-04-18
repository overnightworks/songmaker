<script lang="ts">
	import { tick } from 'svelte';
	import {
		sendCoWriterTurn,
		fetchConversations,
		fetchConversationMessages,
		startNewConversation,
		deleteConversation,
		ApiError
	} from '$lib/api/client';
	import type { ChatMessageItem, ConversationItem } from '$lib/api/types';
	import { addToast } from '$lib/stores/toast';
	import ChatInput from './ChatInput.svelte';

	interface Props {
		currentSongId?: string;
		visible?: boolean;
		onturncompleted?: () => void;
	}

	let { currentSongId = '', visible = true, onturncompleted }: Props = $props();

	interface Message {
		role: 'user' | 'assistant';
		text: string;
	}

	let messages: Message[] = $state([]);
	let input = $state('');
	let loading = $state(false);
	let historyLoading = $state(false);
	let error = $state('');
	let container: HTMLDivElement | undefined = $state();
	let inputEl: HTMLTextAreaElement | undefined = $state();

	let conversations: ConversationItem[] = $state([]);
	let activeConversationId: string | null = $state(null);
	let viewingConversationId: string | null = $state(null);
	let showConversations = $state(false);

	$effect(() => {
		if (visible) {
			void loadConversations();
		}
	});

	async function loadConversations(): Promise<void> {
		try {
			const list = await fetchConversations();
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
			/* transient — leave state */
		}
	}

	async function loadMessages(conversationId: string): Promise<void> {
		historyLoading = true;
		try {
			const result = await fetchConversationMessages(conversationId);
			messages = result.messages.map((m: ChatMessageItem) => ({
				role: m.role as 'user' | 'assistant',
				text: m.content
			}));
		} catch {
			messages = [];
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
		messages = [...messages, { role: 'user', text: msg }];
		loading = true;

		try {
			const result = await sendCoWriterTurn(msg, currentSongId || null);
			messages = [...messages, { role: 'assistant', text: result.assistant_message.content }];
			if (activeConversationId !== result.conversation_id) {
				activeConversationId = result.conversation_id;
				viewingConversationId = result.conversation_id;
				void loadConversations();
			}
			if (onturncompleted) onturncompleted();
		} catch (e) {
			if (e instanceof ApiError && e.status === 503) {
				error = 'Claude is currently unavailable';
			} else {
				error = e instanceof Error ? e.message : 'Chat failed';
			}
			messages = messages.slice(0, -1);
		} finally {
			loading = false;
			void scrollToBottom();
		}
	}

	async function scrollToBottom(): Promise<void> {
		await tick();
		if (container) container.scrollTop = container.scrollHeight;
	}

	function handleInput(): void {
		/* no-op — kept for ChatInput contract; the @-mention picker is gone. */
	}

	function handleKeydown(e: KeyboardEvent): void {
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
			<h3>Claude Co-Writer</h3>
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

	{#if historyLoading}
		<div class="history-loading">Loading chat...</div>
	{:else}
		<div class="messages" bind:this={container}>
			{#if messages.length === 0}
				<p class="empty-hint">
					Hey! I can see the song you have open. Tell me what you want to work on, or ask me to
					browse your other songs — I'll pull them up as needed.
				</p>
			{/if}
			{#each messages as msg, i (i)}
				<div
					class="message"
					class:user={msg.role === 'user'}
					class:assistant={msg.role === 'assistant'}
				>
					<pre class="message-text">{msg.text}</pre>
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
	{/if}

	{#if readOnly}
		<div class="readonly-banner">
			Archived — <button class="link" onclick={startNew}>start a new conversation</button> to reply.
		</div>
	{/if}

	<div class="input-area">
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
	}

	.conv-wrapper {
		position: relative;
		min-width: 0;
	}

	.conv-toggle {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-dim);
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
		color: var(--text-dim);
	}

	.conv-del {
		background: none;
		border: none;
		color: var(--text-dim);
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
		color: var(--text-dim);
		font-style: italic;
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

	.chat-error {
		color: var(--score-bad);
		font-size: 0.75rem;
		padding: 4px 8px;
	}

	.readonly-banner {
		padding: 6px 12px;
		background: var(--surface);
		color: var(--text-dim);
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

	.input-area {
		position: relative;
	}
</style>
