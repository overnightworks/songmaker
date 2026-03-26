<script lang="ts">
	import { claudeApiKey } from '$lib/stores/settings';

	const hasKey = $derived(!!$claudeApiKey);
	let keyValue = $state($claudeApiKey);

	function handleSave(): void {
		claudeApiKey.set(keyValue.trim());
	}

	function handleClear(): void {
		keyValue = '';
		claudeApiKey.set('');
	}
</script>

<div class="page">
	<h1>Integrations</h1>

	<section>
		<h2>Claude API Key</h2>
		<p class="hint">
			Provide your own Anthropic API key for the Claude co-writer. Leave empty to use the server CLI
			fallback.
		</p>
		<div class="key-form">
			<input
				type="text"
				placeholder="sk-ant-..."
				bind:value={keyValue}
				class="key-input"
				autocomplete="off"
				spellcheck="false"
			/>
			<div class="key-actions">
				<button class="save-btn" onclick={handleSave} disabled={keyValue.trim() === $claudeApiKey}>
					Save
				</button>
				{#if hasKey}
					<button class="clear-btn" onclick={handleClear}>Clear</button>
				{/if}
			</div>
		</div>
		<p class="status">
			{#if hasKey}
				<span class="connected">Using your API key</span>
			{:else}
				<span class="fallback">No key — using server CLI</span>
			{/if}
		</p>
	</section>
</div>

<style>
	.page {
		padding: 2rem;
		max-width: 600px;
	}

	h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--primary);
		font-size: 1.5rem;
		margin-bottom: 1.5rem;
	}

	h2 {
		font-size: 1rem;
		color: var(--text-muted);
		margin-bottom: 0.5rem;
	}

	.hint {
		color: var(--text-dim);
		font-size: 0.85rem;
		margin-bottom: 1rem;
	}

	.key-form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.key-input {
		width: 100%;
		padding: 0.6rem 0.8rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.95rem;
		font-family: monospace;
	}

	.key-input:focus {
		outline: none;
		border-color: var(--primary);
	}

	.key-actions {
		display: flex;
		gap: 0.5rem;
	}

	.save-btn {
		background: var(--primary);
		color: white;
		border: none;
		border-radius: 4px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		font-family: var(--font-body);
	}

	.save-btn:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	.save-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.clear-btn {
		background: transparent;
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-body);
	}

	.clear-btn:hover {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.status {
		font-size: 0.85rem;
		margin-top: 0.5rem;
	}

	.connected {
		color: var(--score-good);
	}

	.fallback {
		color: var(--text-dim);
	}
</style>
