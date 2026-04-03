<script lang="ts">
	import type { GenerationItem } from '$lib/api/types';

	interface Props {
		generation: GenerationItem;
		onsubmit: (strength: number, lyrics: string | null, prompt: string | null) => void;
		oncancel: () => void;
	}

	let { generation, onsubmit, oncancel }: Props = $props();

	let strength = $state(80);
	let lyrics = $state('');
	let prompt = $state('');

	function handleSubmit(): void {
		onsubmit(strength / 100, lyrics || null, prompt || null);
	}
</script>

<div class="cover-overlay" role="dialog">
	<div class="cover-dialog">
		<h3>Cover gen{generation.generation_number}</h3>
		<p class="description">
			Re-interpret this generation with different style or lyrics while keeping the melody
			structure.
		</p>

		<label class="field">
			<span>Cover strength: {strength}%</span>
			<input type="range" min="0" max="100" bind:value={strength} />
			<div class="strength-labels">
				<span>Free reinterpretation</span>
				<span>Strict structure</span>
			</div>
		</label>

		<label class="field">
			<span>New lyrics (optional)</span>
			<textarea rows="4" bind:value={lyrics} placeholder="Leave empty to keep current lyrics"
			></textarea>
		</label>

		<label class="field">
			<span>Style prompt (optional)</span>
			<input type="text" bind:value={prompt} placeholder="e.g. jazz version, acoustic" />
		</label>

		<div class="actions">
			<button class="cancel-btn" onclick={oncancel}>Cancel</button>
			<button class="submit-btn" onclick={handleSubmit}>Cover</button>
		</div>
	</div>
</div>

<style>
	.cover-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.7);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.cover-dialog {
		background: var(--surface-dark, #1a1a2e);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 1.33rem;
		width: 400px;
		max-width: 90vw;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}

	h3 {
		margin: 0;
		font-size: 0.93rem;
		font-family: var(--font-display);
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.description {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		margin: 0;
		line-height: 1.4;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 0.27rem;
	}

	.field span {
		font-size: 0.7rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.field input[type='range'] {
		width: 100%;
		accent-color: var(--primary);
	}

	.strength-labels {
		display: flex;
		justify-content: space-between;
		font-size: 0.6rem;
		color: var(--text-dim);
	}

	.field textarea,
	.field input[type='text'] {
		padding: 0.4rem 0.53rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: var(--label-font-size);
		resize: vertical;
	}

	.field textarea:focus,
	.field input:focus {
		border-color: var(--accent);
		outline: none;
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.53rem;
		margin-top: 0.27rem;
	}

	.cancel-btn,
	.submit-btn {
		padding: 0.4rem 1.07rem;
		border-radius: 4px;
		font-size: var(--label-font-size);
		cursor: pointer;
		border: 1px solid var(--border);
	}

	.cancel-btn {
		background: transparent;
		color: var(--text-muted);
	}

	.submit-btn {
		background: var(--primary);
		color: #fff;
		border-color: var(--primary);
	}
</style>
