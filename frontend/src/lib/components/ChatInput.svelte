<script lang="ts">
	import { COWRITER_COMPOSER_PLACEHOLDER, COWRITER_SEND_LABEL } from '$lib/constants';

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
		rows="1"
		placeholder={COWRITER_COMPOSER_PLACEHOLDER}
		bind:value
		bind:this={inputRef}
		{onkeydown}
		{oninput}></textarea>
	<button type="button" class="send-btn" onclick={onsend} {disabled}>{COWRITER_SEND_LABEL}</button>
</div>

<style>
	.input-row {
		display: flex;
		align-items: flex-end;
		gap: 0.5rem;
		padding: 0.6rem 0.6rem 0.6rem 0.75rem;
		background: var(--header-bg);
		border-top: 1px solid var(--border);
	}

	.chat-input {
		flex: 1;
		min-width: 0;
		min-height: var(--hitbox-frequent);
		max-height: 9rem;
		field-sizing: content;
		padding: 0.5rem 0.85rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		font-family: var(--font-body);
		font-size: 1rem;
		line-height: 1.4;
		resize: none;
	}

	.chat-input:focus {
		border-color: var(--primary);
		outline: none;
		box-shadow: 0 0 0 1px var(--primary);
	}

	.send-btn {
		flex-shrink: 0;
		min-height: var(--hitbox-frequent);
		padding: 0 1.5rem;
		border: 1px solid var(--primary);
		border-radius: var(--btn-radius-sm);
		background: var(--primary);
		color: var(--surface);
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
	}

	.send-btn:disabled {
		background: none;
		border-color: var(--border);
		color: var(--text-disabled);
		cursor: default;
	}
</style>
