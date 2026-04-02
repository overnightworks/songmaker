<script lang="ts">
	import { cleanDisplayText, type ApplyData } from '$lib/utils/chat-context';
	import { isCurrentSong } from '$lib/utils/chat-context';

	interface Message {
		role: 'user' | 'assistant';
		text: string;
		appliedIndices?: number[];
		applyDataList?: ApplyData[];
	}

	interface Props {
		messages: Message[];
		loading: boolean;
		error: string;
		songId: string;
		containerRef?: HTMLDivElement;
		onapply: (msgIndex: number, dataIndex: number) => void;
	}

	let { messages, loading, error, songId, containerRef = $bindable(), onapply }: Props = $props();

	function applyLabel(data: ApplyData): string {
		if (data.create) return `Create "${data.title}"`;
		if (data.song && !isCurrentSong(data, songId)) return `Apply to ${data.song}`;
		return 'Apply to editor';
	}

	function appliedLabel(data: ApplyData): string {
		if (data.create) return `Created "${data.title}"`;
		if (data.song) return `Applied to ${data.song}`;
		return 'Applied';
	}
</script>

<div class="messages" bind:this={containerRef}>
	{#if messages.length === 0}
		<p class="empty-hint">
			Ask Claude to write lyrics, brainstorm ideas, or refine your song. Use <strong>@song</strong>
			to reference other songs, <strong>@album</strong> for full album context, or
			<strong>@v1</strong> for version history.
		</p>
	{/if}
	{#each messages as msg, i (i)}
		<div
			class="message"
			class:user={msg.role === 'user'}
			class:assistant={msg.role === 'assistant'}
		>
			<pre class="message-text">{cleanDisplayText(msg.text)}</pre>
			{#if msg.role === 'assistant' && msg.applyDataList && msg.applyDataList.length > 0}
				{#each msg.applyDataList as data, di (di)}
					<div class="apply-row">
						{#if msg.appliedIndices?.includes(di)}
							<span class="applied-badge">{appliedLabel(data)}</span>
						{:else}
							<button class="apply-btn" onclick={() => onapply(i, di)}>
								{applyLabel(data)}
							</button>
						{/if}
					</div>
				{/each}
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

<style>
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
</style>
