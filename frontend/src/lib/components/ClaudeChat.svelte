<script lang="ts">
	import { claudeApiKey } from '$lib/stores/settings';
	import { chatWithClaude } from '$lib/api/client';

	interface Props {
		songId?: string;
		songContext?: string;
		onapply?: (data: ApplyData) => void;
	}

	export interface ApplyData {
		lyrics?: string;
		prompt?: string;
		bpm?: number;
		duration?: number;
		key?: string;
	}

	let { songId = '', songContext = '', onapply }: Props = $props();

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
	let showKeyInput = $state(false);
	let container: HTMLDivElement | undefined = $state();
	const hasKey = $derived(!!$claudeApiKey);

	const SYSTEM_PROMPT =
		'You are a songwriting assistant. Help write, improve, and refine song lyrics. ' +
		'Be creative but respect the style and theme.\n\n' +
		'When suggesting lyrics or song parameters, ALWAYS include a ```songmaker block ' +
		'at the end of your response with the applicable fields as JSON:\n' +
		'```songmaker\n{"lyrics": "[verse]\\n...", "prompt": "style...", "bpm": 120, "key": "Am"}\n```\n\n' +
		'Only include fields you are suggesting changes for. The lyrics field should use ' +
		'section tags like [verse], [chorus], [bridge]. Use \\n for newlines in lyrics.\n' +
		'If the user just asks a question without needing changes, skip the songmaker block.';

	let prevSongId = $state('');

	$effect(() => {
		if (songId !== prevSongId) {
			prevSongId = songId;
			loadHistory();
		}
	});

	function storageKey(): string {
		return songId ? `songmaker:chat:${songId}` : 'songmaker:chat:new';
	}

	function loadHistory(): void {
		try {
			const saved = localStorage.getItem(storageKey());
			messages = saved ? JSON.parse(saved) : [];
		} catch {
			messages = [];
		}
	}

	function saveHistory(): void {
		const toSave = messages.map(({ role, text, applied, applyData }) => ({
			role,
			text,
			applied,
			applyData
		}));
		localStorage.setItem(storageKey(), JSON.stringify(toSave));
	}

	function buildConversation(newMessage: string): string {
		const parts: string[] = [];
		for (const msg of messages) {
			const prefix = msg.role === 'user' ? 'User' : 'Assistant';
			parts.push(`${prefix}: ${cleanDisplayText(msg.text)}`);
		}
		parts.push(`User: ${newMessage}`);

		let fullPrompt = parts.join('\n\n');
		if (songContext) {
			fullPrompt = `Song context:\n${songContext}\n\n---\n\n${fullPrompt}`;
		}
		return fullPrompt;
	}

	function extractApplyData(text: string): ApplyData | undefined {
		const match = text.match(/```songmaker\s*\n([\s\S]*?)```/);
		if (!match) return undefined;
		try {
			return JSON.parse(match[1].trim());
		} catch {
			return undefined;
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
		messages = [...messages, { role: 'user', text: msg }];
		loading = true;

		try {
			const fullPrompt = buildConversation(msg);
			const responseText = await chatWithClaude(fullPrompt, '', SYSTEM_PROMPT);
			const applyData = extractApplyData(responseText);
			const newMsg: Message = { role: 'assistant', text: responseText, applyData };

			if (applyData && onapply) {
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

	function applyMessage(index: number): void {
		const msg = messages[index];
		if (!msg?.applyData || !onapply) return;
		onapply(msg.applyData);
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

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			send();
		}
	}
</script>

<div class="chat">
	<div class="chat-header">
		<h3>Claude Co-Writer</h3>
		<div class="header-actions">
			{#if messages.length > 0}
				<button class="clear-btn" onclick={clearHistory} aria-label="Clear chat">✕</button>
			{/if}
			<button
				class="key-toggle"
				onclick={() => (showKeyInput = !showKeyInput)}
				aria-label="API key settings"
			>
				{hasKey ? '🔑' : '⚙️'}
			</button>
		</div>
	</div>

	{#if showKeyInput}
		<div class="key-input">
			<input
				type="password"
				placeholder="Anthropic API key (optional)"
				value={$claudeApiKey}
				oninput={(e: Event) => claudeApiKey.set((e.target as HTMLInputElement).value)}
			/>
			<span class="key-hint">
				{#if hasKey}
					Using your API key
				{:else}
					No key — using server CLI
				{/if}
			</span>
		</div>
	{/if}

	<div class="messages" bind:this={container}>
		{#if messages.length === 0}
			<p class="empty-hint">
				Ask Claude to write lyrics, brainstorm ideas, or refine your song. Suggestions auto-apply to
				the editor.
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
							<span class="applied-badge">✓ Applied</span>
						{:else}
							<button class="apply-btn" onclick={() => applyMessage(i)}> Apply to editor </button>
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

	<div class="input-row">
		<textarea
			class="chat-input"
			rows="2"
			placeholder="Ask Claude..."
			bind:value={input}
			onkeydown={handleKeydown}
		></textarea>
		<button class="send-btn" onclick={send} disabled={loading || !input.trim()} aria-label="Send">
			↑
		</button>
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
		color: var(--primary);
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

	.key-toggle {
		background: none;
		border: none;
		font-size: 14px;
		cursor: pointer;
	}

	.key-input {
		padding: 8px 12px;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}

	.key-input input {
		width: 100%;
		padding: 4px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 11px;
	}

	.key-input input:focus {
		border-color: var(--primary);
		outline: none;
	}

	.key-hint {
		font-size: 9px;
		color: var(--text-dim);
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
		background: var(--primary);
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

	.input-row {
		display: flex;
		gap: 6px;
		padding: 8px;
		border-top: 1px solid var(--border);
		flex-shrink: 0;
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
		border-color: var(--primary);
		outline: none;
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
		background: var(--primary);
		color: #fff;
	}

	.send-btn:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
</style>
