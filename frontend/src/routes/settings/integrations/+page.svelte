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
				autocomplete="one-time-code"
				data-1p-ignore
				data-lpignore="true"
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
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.5rem;
		margin-bottom: 1.5rem;
	}

	h2 {
		font-size: 1rem;
		color: var(--text-muted);
		margin-bottom: 0.5rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
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
		border-color: var(--accent);
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.key-actions {
		display: flex;
		gap: 0.5rem;
	}

	.save-btn {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: white;
		border: none;
		border-radius: 16px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		transition: box-shadow 0.2s;
	}

	.save-btn:hover:not(:disabled) {
		box-shadow: 0 0 16px rgba(160, 32, 240, 0.3);
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
