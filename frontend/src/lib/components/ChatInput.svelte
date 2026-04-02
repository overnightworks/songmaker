<script lang="ts">
	interface Props {
		value: string;
		disabled: boolean;
		inputRef?: HTMLTextAreaElement;
		oninput: () => void;
		onkeydown: (e: KeyboardEvent) => void;
		onsend: () => void;
	}

	let {
		value = $bindable(),
		disabled,
		inputRef = $bindable(),
		oninput,
		onkeydown,
		onsend
	}: Props = $props();
</script>

<div class="input-row">
	<textarea
		class="chat-input"
		rows="2"
		placeholder="Ask Claude... (@song, @album, or @v1)"
		bind:value
		bind:this={inputRef}
		{onkeydown}
		{oninput}
	></textarea>
	<button class="send-btn" onclick={onsend} {disabled} aria-label="Send"> ↑ </button>
</div>

<style>
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
