<script lang="ts">
	import { chatWithClaude } from '$lib/api/client';
	import { claudeApiKey } from '$lib/stores/settings';

	interface Props {
		songContext?: string;
	}

	let { songContext = '' }: Props = $props();

	interface Message {
		role: 'user' | 'assistant';
		text: string;
	}

	let messages: Message[] = $state([]);
	let input = $state('');
	let loading = $state(false);
	let error = $state('');
	let showKeyInput = $state(false);
	let container: HTMLDivElement | undefined = $state();
	const hasKey = $derived(!!$claudeApiKey);

	const SYSTEM_PROMPT =
		'You are a songwriting assistant. Help the user write, improve, and refine song lyrics. ' +
		'Be creative but respect the style and theme. When suggesting lyrics, format them with ' +
		'section tags like [verse], [chorus], [bridge]. Keep responses concise.';

	async function send(): Promise<void> {
		const msg = input.trim();
		if (!msg || loading) return;

		input = '';
		error = '';
		messages = [...messages, { role: 'user', text: msg }];
		loading = true;

		try {
			const response = await chatWithClaude(msg, songContext, SYSTEM_PROMPT);
			messages = [...messages, { role: 'assistant', text: response }];
		} catch (e) {
			error = e instanceof Error ? e.message : 'Chat failed';
		} finally {
			loading = false;
			scrollToBottom();
		}
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
		<button
			class="key-toggle"
			onclick={() => (showKeyInput = !showKeyInput)}
			aria-label="API key settings"
		>
			{hasKey ? '🔑' : '⚙️'}
		</button>
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
				Ask Claude to help write lyrics, brainstorm ideas, or refine your song.
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
		border-left: 1px solid var(--border);
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
