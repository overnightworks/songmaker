<script lang="ts">
	import { onDestroy, tick } from 'svelte';
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
		ConversationMessagesResponse,
		MemoryBundle,
		SongItem,
		VersionItem
	} from '$lib/api/types';
	import { addToast } from '$lib/stores/toast';
	import { health } from '$lib/stores/health';
	import {
		COWRITER_CLAUDE_UNVERIFIED_LABEL,
		COWRITER_CONVERSATION_MENU_LABEL,
		COWRITER_DELETE_CONVERSATION_TITLE,
		COWRITER_DELETE_CONVERSATION_WARNING,
		COWRITER_MEMORY_LABEL,
		COWRITER_MEMORY_PROPOSAL_WAITING_LABEL,
		COWRITER_NEW_CONVERSATION_LABEL,
		COWRITER_RUNNING_TURN_POLL_FAILURE_LIMIT,
		COWRITER_RUNNING_TURN_POLL_MS,
		COWRITER_TOOL_CALL_FOREIGN_TARGET_TITLE,
		COWRITER_TOOL_CALL_TARGET_PREFIX
	} from '$lib/constants';
	import { historyLayerState } from '$lib/stores/layers';
	import { focusFirstIn, handleFocusTrapKeydown, refocusIfDropped } from '$lib/utils/focus-trap';
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
		conversationConfirmLabel,
		conversationLineLabel,
		conversationMenuOrder,
		conversationMessageCountLabel,
		conversationRowLabel,
		cowriterTurnFailureLabel,
		cowriterHeaderLabel,
		cowriterThinkingLabel,
		cowriterToolCallTarget,
		cowriterUnavailableLabel,
		providerDisplayName
	} from '$lib/utils/cowriter-ui';
	import ChatInput from './ChatInput.svelte';
	import Icon from './Icon.svelte';
	import MemoryEditor from './MemoryEditor.svelte';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';
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
		persistedId?: string;
		role: 'user' | 'assistant';
		text: string;
		toolCalls?: ToolCall[];
		error?: string;
	}

	const INCOMPLETE_TURN_MESSAGE = 'The co-writer did not answer. Try again.';
	const TURN_ALREADY_RUNNING_STATUS = 409;
	const LATEST_MESSAGE_SLACK_PX = 32;

	let messages: Message[] = $state([]);
	let input = $state('');
	let loading = $state(false);
	let historyLoading = $state(false);
	let historyError = $state('');
	let container: HTMLDivElement | undefined = $state();
	let inputEl: HTMLTextAreaElement | undefined = $state();
	let inputArea: HTMLDivElement | undefined = $state();

	let conversations: ConversationItem[] = $state([]);
	let activeConversationId: string | null = $state(null);
	let viewingConversationId: string | null = $state(null);
	const conversationMenuOpen = historyLayerState('cowriter-conversations-menu', false);
	let conversationMenuTrigger: HTMLButtonElement | undefined = $state();
	let conversationMenu: HTMLDivElement | undefined = $state();

	let conversationAwaitingDelete: ConversationItem | null = $state(null);
	const memoryOpen = historyLayerState('cowriter-memory', false);
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
	const showMentions = historyLayerState('cowriter-mention-list', false);
	let mentionCursorPos = $state(0);
	let selectedMentionIdx = $state(0);
	let providerName = $state('claude');
	let providerModel = $state('');
	let unmounted = false;
	let latestTurn: Promise<void> = Promise.resolve();

	onDestroy(() => {
		unmounted = true;
	});

	$effect(() => {
		void currentSongId;
		mentionedSongIds = [];
		mentionedVersionIds = [];
		mentionedAlbumId = null;
		$showMentions = false;
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
		const turnBeforeRead = latestTurn;
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
					await loadMessages(newActiveId, turnBeforeRead);
				} else {
					messages = [];
				}
			}
		} catch {
			historyError = 'Conversation history unavailable';
		}
	}

	function toMessages(history: ChatMessageItem[]): Message[] {
		return history.map((m) => ({
			persistedId: m.id,
			role: m.role as 'user' | 'assistant',
			text: m.content
		}));
	}

	/**
	 * `turnBeforeRead` is the latest turn when the history read began, which
	 * for the first read is its conversation-list step (#1170).
	 */
	async function loadMessages(
		conversationId: string,
		turnBeforeRead: Promise<void> = latestTurn
	): Promise<void> {
		historyLoading = true;
		historyError = '';
		let conversation: ConversationMessagesResponse | null = null;
		try {
			conversation = await fetchConversationMessages(conversationId);
		} catch {
			historyError = 'Conversation history unavailable';
		} finally {
			historyLoading = false;
		}
		if (latestTurn !== turnBeforeRead) {
			await keepTurnSentDuringRead(conversationId, conversation);
			return;
		}
		messages = conversation ? toMessages(conversation.messages) : [];
		followLatest();
		if (!conversation || conversationId !== activeConversationId || loading) return;
		followOrSettleTurn(conversation);
	}

	/**
	 * A message sent while the history was still being read owns the chat's
	 * end: once its turn settles, the history the read found goes before it
	 * rather than in its place, so the exchange keeps its answer, refusal or
	 * failure (#1170).
	 */
	async function keepTurnSentDuringRead(
		conversationId: string,
		conversation: ConversationMessagesResponse | null
	): Promise<void> {
		await latestTurn;
		if (!conversation || viewingConversationId !== conversationId) return;
		const history = toMessages(conversation.messages);
		const shown = withStoredIdOfSentMessage(messages, history.at(-1));
		const shownIds = new Set(shown.map((message) => message.persistedId));
		const unshownHistory = history.filter((message) => !shownIds.has(message.persistedId));
		messages = [...unshownHistory, ...shown];
		followLatest();
	}

	/**
	 * The server stores a sent message when its turn starts, so a history read
	 * that ends in it holds the sent bubble itself: a refused or failed turn
	 * never learned that id, and without it the message would show twice.
	 */
	function withStoredIdOfSentMessage(
		shown: Message[],
		newestStored: Message | undefined
	): Message[] {
		return shown.map((message) =>
			message.role === 'user' &&
			!message.persistedId &&
			isUnansweredResend(newestStored, message.text)
				? { ...message, persistedId: newestStored.persistedId }
				: message
		);
	}

	function followOrSettleTurn(conversation: ConversationMessagesResponse): void {
		if (conversation.turn_running) void followRunningTurn(conversation.conversation_id);
		else markUnansweredLastMessage();
	}

	/**
	 * A stream that drops without the server's own error frame did not fail
	 * the turn: the server runs it to completion regardless. Show what the
	 * conversation holds instead — the running turn, its reply, or the
	 * unanswered message — and name a failure only when the message never
	 * reached the server (#1014).
	 */
	async function reattachDroppedTurn(
		sentMessage: string,
		lastKnownPersistedId: string | undefined,
		assistantIndex: number
	): Promise<void> {
		const conversation = await readActiveConversation().catch(() => null);
		if (!conversation || !reachedServer(conversation, sentMessage, lastKnownPersistedId)) {
			markTurnFailed(assistantIndex, INCOMPLETE_TURN_MESSAGE);
			return;
		}
		const conversationChanged = activeConversationId !== conversation.conversation_id;
		if (conversationChanged) {
			activeConversationId = conversation.conversation_id;
			viewingConversationId = conversation.conversation_id;
		}
		messages = toMessages(conversation.messages);
		followOrSettleTurn(conversation);
		if (!conversation.turn_running) announceEndedTurn();
		else if (conversationChanged) void loadConversations();
	}

	/**
	 * A turn ended: its conversation's row counts what the chat now holds at
	 * once, the conversation list re-reads its counts, and the host hears of it.
	 */
	function announceEndedTurn(): void {
		countPersistedChatInItsRow();
		void loadConversations();
		if (onturncompleted) onturncompleted();
	}

	function countPersistedChatInItsRow(): void {
		const persistedCount = messages.filter((message) => message.persistedId).length;
		conversations = conversations.map((conversation) =>
			conversation.id === viewingConversationId
				? { ...conversation, message_count: persistedCount }
				: conversation
		);
	}

	/**
	 * Text alone cannot tell a repeated "ok" from the answered one before it:
	 * the message reached the server only when its turn still runs or the
	 * conversation grew past what the panel last knew persisted.
	 */
	function reachedServer(
		conversation: ConversationMessagesResponse,
		sentMessage: string,
		lastKnownPersistedId: string | undefined
	): boolean {
		const persisted = conversation.messages;
		const lastSent = persisted.findLast((message) => message.role === 'user');
		if (lastSent?.content !== sentMessage) return false;
		return conversation.turn_running || persisted.at(-1)?.id !== lastKnownPersistedId;
	}

	async function readActiveConversation(): Promise<ConversationMessagesResponse | null> {
		const conversationId =
			activeConversationId ??
			(await fetchConversations()).find((conversation) => conversation.archived_at === null)?.id;
		return conversationId ? fetchConversationMessages(conversationId) : null;
	}

	/**
	 * Another tab or panel is still running a turn: follow it, and keep what
	 * was typed unless the running turn is already answering that message.
	 */
	async function followTurnRunningElsewhere(
		sentMessage: string,
		assistantIndex: number
	): Promise<void> {
		messages = messages.slice(0, assistantIndex - 1);
		if (activeConversationId) await loadMessages(activeConversationId);
		else await loadConversations();
		const runningMessage = messages.findLast((message) => message.role === 'user')?.text;
		if (runningMessage !== sentMessage) input = sentMessage;
	}

	/**
	 * Wait out a turn the server still runs — started by a panel since left or
	 * by another tab — and show how it ended. The server's chat job decides
	 * whether a turn runs; a web-process restart ends one that process ran (#1014).
	 */
	async function followRunningTurn(conversationId: string): Promise<void> {
		const placeholderIndex = messages.length;
		messages = [...messages, { role: 'assistant', text: '' }];
		loading = true;
		let consecutiveFailedPolls = 0;
		try {
			while (consecutiveFailedPolls < COWRITER_RUNNING_TURN_POLL_FAILURE_LIMIT) {
				await new Promise((resolve) => setTimeout(resolve, COWRITER_RUNNING_TURN_POLL_MS));
				if (unmounted || viewingConversationId !== conversationId) return;
				let conversation: ConversationMessagesResponse;
				try {
					conversation = await fetchConversationMessages(conversationId);
				} catch {
					consecutiveFailedPolls += 1;
					continue;
				}
				consecutiveFailedPolls = 0;
				if (conversation.turn_running) continue;
				messages = toMessages(conversation.messages);
				markUnansweredLastMessage();
				announceEndedTurn();
				return;
			}
			messages = messages.slice(0, placeholderIndex);
			historyError = 'Conversation history unavailable';
		} finally {
			loading = false;
			void keepLatestInView();
		}
	}

	function markUnansweredLastMessage(): void {
		const last = messages.at(-1);
		if (last?.role !== 'user') return;
		messages = [...messages.slice(0, -1), { ...last, error: INCOMPLETE_TURN_MESSAGE }];
	}

	function markTurnFailed(assistantIndex: number, failureMessage: string): void {
		messages = messages.map((message, index) =>
			index === assistantIndex - 1 ? { ...message, error: failureMessage } : message
		);
		const current = messages[assistantIndex];
		if (current && !current.text) {
			messages = [...messages.slice(0, assistantIndex), ...messages.slice(assistantIndex + 1)];
		}
	}

	async function openConversation(conv: ConversationItem): Promise<void> {
		if (viewingConversationId !== conv.id) messages = [];
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
		} catch {
			addToast('Failed to start new conversation', 'error');
		}
	}

	function askToDelete(conv: ConversationItem): void {
		conversationAwaitingDelete = conv;
	}

	function closeDeleteConfirm(): void {
		conversationAwaitingDelete = null;
		conversationMenuTrigger?.focus();
	}

	async function confirmDelete(): Promise<void> {
		const conv = conversationAwaitingDelete;
		closeDeleteConfirm();
		if (conv) await deleteConversationNow(conv);
	}

	async function deleteConversationNow(conv: ConversationItem): Promise<void> {
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
		await sendMessage(input.trim());
	}

	async function retry(message: string): Promise<void> {
		await sendMessage(message);
	}

	async function sendMessage(msg: string): Promise<void> {
		if (!msg || loading) return;
		if (viewingConversationId !== null && viewingConversationId !== activeConversationId) {
			addToast('Viewing an archived conversation — start a new one to reply', 'info');
			return;
		}
		if (claudeDrifted) {
			addToast(cowriterUnavailableLabel(providerName), 'error');
			return;
		}
		latestTurn = runTurn(msg);
		await latestTurn;
	}

	async function runTurn(msg: string): Promise<void> {
		input = '';
		const lastKnownPersistedId = messages.findLast((message) => message.persistedId)?.persistedId;
		const sentAgain = unansweredMessageSentAgain(msg);
		const earlier = sentAgain ? messages.slice(0, -1) : messages;
		const assistantIndex = earlier.length + 1;
		messages = [
			...earlier,
			{ role: 'user', text: msg, persistedId: sentAgain?.persistedId },
			{ role: 'assistant', text: '', toolCalls: [] }
		];
		loading = true;
		followLatest();

		let streamError: string | null = null;
		let answeredConversationId: string | null = null;
		let refusal: ApiError | null = null;
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
					streamError = streamFailureMessage(event);
					break;
				}
				if (event.type === 'final') {
					answeredConversationId = event.conversation_id;
					if (activeConversationId !== event.conversation_id) {
						activeConversationId = event.conversation_id;
						viewingConversationId = event.conversation_id;
					}
					announceEndedTurn();
				}
				void keepLatestInView();
			}
		} catch (e) {
			if (e instanceof ApiError) refusal = e;
		} finally {
			loading = false;
		}
		if (refusal?.status === TURN_ALREADY_RUNNING_STATUS) {
			await followTurnRunningElsewhere(msg, assistantIndex);
		} else if (refusal) {
			markTurnFailed(assistantIndex, refusalMessage(refusal));
		} else if (streamError) {
			markTurnFailed(assistantIndex, streamError);
		} else if (answeredConversationId === null) {
			await reattachDroppedTurn(msg, lastKnownPersistedId, assistantIndex);
		} else {
			await adoptPersistedHistory(answeredConversationId);
		}
		void keepLatestInView();
	}

	/**
	 * An answered turn shows what the conversation holds, so the chat reads
	 * the same before and after a reload: an older failed message stays as the
	 * server stored it, or leaves when it never reached the server (#1014).
	 * Every reply keeps the tool calls it streamed in this session; they are
	 * not persisted. When the history cannot be read, the streamed exchange
	 * stays as it is.
	 */
	async function adoptPersistedHistory(conversationId: string): Promise<void> {
		const conversation = await fetchConversationMessages(conversationId).catch(() => null);
		if (!conversation || loading || viewingConversationId !== conversationId) return;
		const streamedToolCalls = new Map(
			messages
				.filter((message) => message.persistedId && message.toolCalls)
				.map((message) => [message.persistedId, message.toolCalls])
		);
		messages = toMessages(conversation.messages).map((message) => ({
			...message,
			toolCalls: streamedToolCalls.get(message.persistedId)
		}));
		countPersistedChatInItsRow();
		followOrSettleTurn(conversation);
	}

	/**
	 * The server answers an unanswered last message that is sent again instead
	 * of storing it twice (#1014), so the panel sends it in place of its bubble.
	 */
	function unansweredMessageSentAgain(msg: string): Message | undefined {
		const last = messages.at(-1);
		return isUnansweredResend(last, msg) ? last : undefined;
	}

	/** The server's resend rule (#1014): an unanswered last message with the same text is that message. */
	function isUnansweredResend(last: Message | undefined, text: string): last is Message {
		return last?.role === 'user' && last.text === text;
	}

	/**
	 * Only the newest message can be sent again: the server answers its stored
	 * copy, while an older one would be stored a second time (#1014). An older
	 * failure therefore reads as the reload shows it — a message without a reply.
	 */
	const retryableMessageIndex = $derived(
		messages.findLastIndex((message) => message.role === 'user')
	);

	function streamFailureMessage(frame: Extract<CoWriterStreamEvent, { type: 'error' }>): string {
		return cowriterTurnFailureLabel(frame, providerName) ?? INCOMPLETE_TURN_MESSAGE;
	}

	function refusalMessage(refusal: ApiError): string {
		if (refusal.status === 503) return refusal.detail || cowriterUnavailableLabel(providerName);
		return refusal.message;
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
			const sent = messages[assistantIndex - 1];
			messages[assistantIndex - 1] = { ...sent, persistedId: event.user_message.id };
			messages[assistantIndex] = {
				...current,
				persistedId: event.assistant_message.id,
				text: event.assistant_message.content
			};
		}
	}

	/*
	 * The chat follows the newest message unless the musician scrolled up to
	 * read. A pane hidden behind Edit or Takes has no box to scroll and loses
	 * its offset, so the place is taken again when the pane is shown (#1063).
	 * Only a scroll upwards stops the following: content growing under a
	 * scroll the chat made itself must not read as the musician leaving.
	 */
	let followsLatest = true;
	let readingScrollTop = 0;
	let chatShown = false;

	function followLatest(): void {
		followsLatest = true;
		void keepLatestInView();
	}

	async function keepLatestInView(): Promise<void> {
		await tick();
		if (container && chatShown && followsLatest) scrollChatTo(container, container.scrollHeight);
	}

	function scrollChatTo(chat: HTMLElement, top: number): void {
		chat.scrollTop = top;
		readingScrollTop = chat.scrollTop;
	}

	function rememberReadingPlace(): void {
		if (!container || !chatShown) return;
		const { scrollTop, scrollHeight, clientHeight } = container;
		if (scrollHeight - scrollTop - clientHeight <= LATEST_MESSAGE_SLACK_PX) followsLatest = true;
		else if (scrollTop < readingScrollTop) followsLatest = false;
		readingScrollTop = scrollTop;
	}

	function takeReadingPlace(chat: HTMLElement): void {
		scrollChatTo(chat, followsLatest ? chat.scrollHeight : readingScrollTop);
	}

	$effect(() => {
		const chat = container;
		if (!chat) return;
		chatShown = false;
		const shownAgain = new ResizeObserver(() => {
			const shown = chat.clientHeight > 0;
			if (shown && !chatShown) takeReadingPlace(chat);
			chatShown = shown;
		});
		shownAgain.observe(chat);
		return () => shownAgain.disconnect();
	});

	/*
	 * Pressing a composer button keeps focus in the composer. On the phone the
	 * composer losing focus brings the mini-player back, which moves Send up
	 * before the tap lands, so the tap missed it (#1063); the keyboard also
	 * stays open for the next message.
	 */
	$effect(() => {
		const area = inputArea;
		if (!area) return;
		function keepComposerFocus(event: MouseEvent): void {
			if (event.target instanceof Element && event.target.closest('button')) {
				event.preventDefault();
			}
		}
		area.addEventListener('mousedown', keepComposerFocus);
		return () => area.removeEventListener('mousedown', keepComposerFocus);
	});

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

	const memoryProposalWaiting = $derived(pendingProposals.length > 0);

	// The waiting dot is only drawn, so the controls that carry it say it in their names.
	function announcingProposalWaiting(label: string): string {
		if (!memoryProposalWaiting) return label;
		return `${label}, ${COWRITER_MEMORY_PROPOSAL_WAITING_LABEL.toLowerCase()}`;
	}

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
			$showMentions = true;
			selectedMentionIdx = 0;
		} else {
			$showMentions = false;
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
		$showMentions = false;
		mentionQuery = '';
		inputEl.focus();
	}

	function handleKeydown(e: KeyboardEvent): void {
		if ($showMentions && (activeMentionResults.length > 0 || catalogLoading)) {
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
		}
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			void send();
		}
	}

	const conversationLine = $derived(
		conversationLineLabel(
			conversations.find((c) => c.id === viewingConversationId),
			messages.length > 0,
			new Date()
		)
	);

	const menuConversations = $derived(conversationMenuOrder(conversations, activeConversationId));

	async function toggleConversationMenu(event: MouseEvent): Promise<void> {
		event.stopPropagation();
		$conversationMenuOpen = !$conversationMenuOpen;
		if (!$conversationMenuOpen) return;
		await tick();
		if (conversationMenu) focusFirstIn(conversationMenu);
	}

	function openMemory(): void {
		$memoryOpen = true;
	}

	function closeMemory(): void {
		$memoryOpen = false;
	}

	let menuOrMemoryWasOpen = false;
	$effect(() => {
		const isOpen = $conversationMenuOpen || $memoryOpen;
		if (menuOrMemoryWasOpen && !isOpen) refocusIfDropped(conversationMenuTrigger);
		menuOrMemoryWasOpen = isOpen;
	});

	function chooseFromConversationMenu(choice: () => void | Promise<void>): void {
		$conversationMenuOpen = false;
		conversationMenuTrigger?.focus();
		void choice();
	}

	$effect(() => {
		if (!$conversationMenuOpen) return;
		function closeOnOutsideClick(): void {
			$conversationMenuOpen = false;
		}
		function trapMenuKeys(event: KeyboardEvent): void {
			if (!conversationMenu) return;
			handleFocusTrapKeydown(conversationMenu, event);
		}
		document.addEventListener('click', closeOnOutsideClick);
		document.addEventListener('keydown', trapMenuKeys, true);
		return () => {
			document.removeEventListener('click', closeOnOutsideClick);
			document.removeEventListener('keydown', trapMenuKeys, true);
		};
	});

	const readOnly = $derived(
		viewingConversationId !== null && viewingConversationId !== activeConversationId
	);

	// Grok and Codex have no pre-emptive signal; only Claude's drifted or
	// unverified tool surface is caught before a turn is sent (ruling 26.09.2026).
	// Drift is a per-build verdict: the send path itself refuses. Unverified
	// only warns — the backend gate re-probes on every turn.
	const claudeDrifted = $derived(
		providerName === 'claude' && $health !== null && $health.claude_cli_tool_surface === 'drift'
	);
	const claudeUnverified = $derived(
		providerName === 'claude' &&
			$health !== null &&
			$health.claude_cli_tool_surface === 'unverified'
	);
</script>

{#snippet proposalWaitingMark()}
	<span class="proposal-waiting" aria-hidden="true"></span>
{/snippet}

<div class="cowriter">
	<div class="convo">
		<span class="convo-line">
			{#if providerModel}<b>{providerDisplayName(providerName)}</b> ·{/if}
			{conversationLine}
		</span>
		<div class="convo-menu-anchor">
			<button
				bind:this={conversationMenuTrigger}
				type="button"
				class="convo-menu-btn"
				data-hitbox="frequent"
				aria-haspopup="menu"
				aria-expanded={$conversationMenuOpen}
				aria-label={announcingProposalWaiting(COWRITER_CONVERSATION_MENU_LABEL)}
				title={COWRITER_CONVERSATION_MENU_LABEL}
				onclick={toggleConversationMenu}
			>
				<Icon name="more-horizontal" size={18} />
				{#if memoryProposalWaiting}{@render proposalWaitingMark()}{/if}
			</button>
			{#if $conversationMenuOpen}
				<div
					bind:this={conversationMenu}
					class="convo-menu"
					role="menu"
					tabindex="-1"
					onclick={(e) => e.stopPropagation()}
					onkeydown={(e) => e.stopPropagation()}
				>
					{#if providerModel}
						<p class="menu-heading">{cowriterHeaderLabel(providerName, providerModel)}</p>
					{/if}
					<button
						type="button"
						role="menuitem"
						class="convo-new"
						data-hitbox="text"
						onclick={() => chooseFromConversationMenu(startNew)}
						>{COWRITER_NEW_CONVERSATION_LABEL}</button
					>
					<button
						type="button"
						role="menuitem"
						class="convo-memory"
						aria-label={announcingProposalWaiting(COWRITER_MEMORY_LABEL)}
						onclick={() => chooseFromConversationMenu(openMemory)}
						>{COWRITER_MEMORY_LABEL}{#if memoryProposalWaiting}{@render proposalWaitingMark()}{/if}</button
					>
					{#each menuConversations as conv (conv.id)}
						<div class="conv-row" role="none" class:active={conv.id === viewingConversationId}>
							<button
								type="button"
								role="menuitem"
								class="conv-pick"
								onclick={() => chooseFromConversationMenu(() => openConversation(conv))}
							>
								<span class="conv-title">{conversationRowLabel(conv, new Date())}</span>
								<span class="conv-meta">{conversationMessageCountLabel(conv.message_count)}</span>
							</button>
							<button
								type="button"
								role="menuitem"
								class="conv-del"
								data-hitbox="frequent"
								onclick={() => chooseFromConversationMenu(() => askToDelete(conv))}
								aria-label="Delete conversation">&#x2715;</button
							>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	{#if conversationAwaitingDelete}
		<ConfirmDeleteDialog
			title={COWRITER_DELETE_CONVERSATION_TITLE}
			items={[conversationConfirmLabel(conversationAwaitingDelete, new Date())]}
			warning={COWRITER_DELETE_CONVERSATION_WARNING}
			onconfirm={confirmDelete}
			oncancel={closeDeleteConfirm}
		/>
	{/if}

	<MemoryEditor
		open={$memoryOpen}
		onClose={closeMemory}
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
		<div class="messages" bind:this={container} onscroll={rememberReadingPlace}>
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
								{@const target = cowriterToolCallTarget(
									call.name,
									call.input,
									allSongs,
									currentSongId
								)}
								<div class="tool-call" title={JSON.stringify(call.input)}>
									<span class="tool-dot" aria-hidden="true">▸</span>
									<span class="tool-name">ran tool: {call.name}</span>
									{#if target}
										<span
											class="tool-target"
											class:foreign={target.foreign}
											title={target.foreign ? COWRITER_TOOL_CALL_FOREIGN_TARGET_TITLE : undefined}
											>{COWRITER_TOOL_CALL_TARGET_PREFIX} {target.title}</span
										>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
					{#if msg.text}
						<pre class="message-text">{stripMemoryProposals(msg.text)}</pre>
					{:else if msg.role === 'assistant' && loading && i === messages.length - 1}
						<span class="typing">{cowriterThinkingLabel(providerName)}</span>
					{/if}
					{#if msg.error && i === retryableMessageIndex}
						<div class="turn-error" role="alert">
							<span>{msg.error}</span>
							<button type="button" class="retry-turn" onclick={() => retry(msg.text)}
								>Try again</button
							>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if readOnly}
		<div class="readonly-banner">
			Archived — <button class="link" onclick={startNew}>start a new conversation</button> to reply.
		</div>
	{/if}

	{#if claudeDrifted}
		<div class="unavailable-banner" role="status">{cowriterUnavailableLabel(providerName)}</div>
	{:else if claudeUnverified}
		<div class="unverified-banner" role="status">{COWRITER_CLAUDE_UNVERIFIED_LABEL}</div>
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

	<div class="input-area" bind:this={inputArea}>
		{#if $showMentions}
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
			disabled={loading || !input.trim() || readOnly || claudeDrifted}
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
		background: var(--bg);
	}

	.convo {
		position: relative;
		flex: none;
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-height: 40px;
		padding: 0 0.1rem 0 0.75rem;
		border-bottom: 1px solid var(--border);
		font-size: 0.78rem;
		color: var(--text-subtle);
	}

	.convo-line {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.convo-line b {
		color: var(--text-light);
		font-weight: 600;
	}

	.convo-menu-btn {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
	}

	.convo-menu-btn:hover,
	.convo-menu-btn[aria-expanded='true'] {
		color: var(--primary);
	}

	.convo-menu {
		position: absolute;
		right: 0.25rem;
		top: calc(100% + 4px);
		z-index: 10;
		width: 18rem;
		max-width: calc(100vw - 2rem);
		max-height: 360px;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 0.25rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}

	.menu-heading {
		margin: 0 0 0.25rem;
		padding: 0.3rem 0.55rem 0.4rem;
		font-size: var(--label-font-size);
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.convo-new {
		background: none;
		border: 1px solid var(--primary);
		color: var(--primary);
		padding: 4px 8px;
		border-radius: 4px;
		font-size: 0.8rem;
		cursor: pointer;
		margin-bottom: 4px;
	}

	.convo-new:hover {
		background: var(--primary);
		color: #fff;
	}

	.convo-memory {
		background: none;
		border: none;
		border-bottom: 1px solid var(--border);
		color: var(--text);
		padding: 6px;
		margin-bottom: 4px;
		text-align: left;
		font-size: 0.85rem;
		cursor: pointer;
	}

	.proposal-waiting {
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--primary);
		flex-shrink: 0;
	}

	.convo-menu-btn .proposal-waiting {
		position: absolute;
		top: 6px;
		right: 6px;
	}

	.convo-memory .proposal-waiting {
		margin-left: 6px;
		vertical-align: middle;
	}

	.convo-memory:hover {
		background: var(--bg);
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
		/* Without this, a flex child defaults to min-height: auto — its full
		   message-list content height — so it never shrinks to the column's
		   bound and the pinned input below it gets pushed out of view. */
		min-height: 0;
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
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tool-target {
		flex-shrink: 0;
		font-family: var(--font-body);
		color: var(--text-subtle);
	}

	.tool-target.foreign {
		display: inline-flex;
		align-items: center;
		padding: 1px 7px;
		border: 1px solid var(--accent);
		border-radius: 10px;
		color: var(--accent);
		font-weight: 600;
	}

	.turn-error {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 6px;
		font-size: 0.75rem;
	}

	.retry-turn {
		border: 1px solid currentColor;
		border-radius: 4px;
		background: transparent;
		color: inherit;
		cursor: pointer;
		font: inherit;
		padding: 2px 6px;
	}

	.retry-turn:hover {
		background: color-mix(in srgb, currentColor 15%, transparent);
	}

	.readonly-banner {
		padding: 6px 12px;
		background: var(--surface);
		color: var(--text-subtle);
		font-size: 0.8rem;
		border-top: 1px solid var(--border);
	}

	.unavailable-banner {
		padding: 6px 12px;
		background: var(--surface);
		color: var(--score-bad);
		font-size: 0.8rem;
		border-top: 1px solid var(--border);
	}

	.unverified-banner {
		padding: 6px 12px;
		background: var(--surface);
		color: var(--score-ok);
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
