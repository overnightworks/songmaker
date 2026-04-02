<script lang="ts">
	import type { GenerationItem } from '$lib/api/types';

	interface Props {
		generation: GenerationItem;
		onsubmit: (start: number, end: number, lyrics: string | null, prompt: string | null) => void;
		oncancel: () => void;
	}

	let { generation, onsubmit, oncancel }: Props = $props();

	const duration = $derived(generation.generation_params?.duration ?? 180);

	let startPercent = $state(0);
	let endPercent = $state(100);
	let lyrics = $state('');
	let prompt = $state('');

	const startSeconds = $derived(Math.round((startPercent / 100) * duration));
	const endSeconds = $derived(Math.round((endPercent / 100) * duration));

	function formatTime(seconds: number): string {
		const m = Math.floor(seconds / 60);
		const s = seconds % 60;
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function handleSubmit(): void {
		onsubmit(startPercent / 100, endPercent / 100, lyrics || null, prompt || null);
	}
</script>

<div class="repaint-overlay" role="dialog">
	<div class="repaint-dialog">
		<h3>Repaint gen{generation.generation_number}</h3>

		<div class="range-section">
			<label class="range-label">
				<span>Start: {formatTime(startSeconds)}</span>
				<input type="range" min="0" max="99" bind:value={startPercent} />
			</label>
			<label class="range-label">
				<span>End: {formatTime(endSeconds)}</span>
				<input type="range" min="1" max="100" bind:value={endPercent} />
			</label>
			<div class="range-bar">
				<div
					class="range-selection"
					style="left: {startPercent}%; width: {endPercent - startPercent}%"
				></div>
			</div>
			<div class="range-info">
				{formatTime(startSeconds)} - {formatTime(endSeconds)}
				({(endPercent - startPercent).toFixed(0)}%)
			</div>
		</div>

		<label class="field">
			<span>New lyrics for this section (optional)</span>
			<textarea rows="4" bind:value={lyrics} placeholder="Leave empty to keep current lyrics"
			></textarea>
		</label>

		<label class="field">
			<span>Style prompt override (optional)</span>
			<input type="text" bind:value={prompt} placeholder="Leave empty to keep current prompt" />
		</label>

		<div class="actions">
			<button class="cancel-btn" onclick={oncancel}>Cancel</button>
			<button class="submit-btn" onclick={handleSubmit} disabled={startPercent >= endPercent}>
				Repaint
			</button>
		</div>
	</div>
</div>

<style>
	.repaint-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.7);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
	}

	.repaint-dialog {
		background: var(--surface-dark, #1a1a2e);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 20px;
		width: 400px;
		max-width: 90vw;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	h3 {
		margin: 0;
		font-size: 14px;
		font-family: var(--font-display);
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.range-section {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.range-label {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 11px;
		color: var(--text-muted);
	}

	.range-label input[type='range'] {
		width: 60%;
		accent-color: var(--primary);
	}

	.range-bar {
		height: 8px;
		background: var(--surface);
		border-radius: 4px;
		position: relative;
		overflow: hidden;
	}

	.range-selection {
		position: absolute;
		top: 0;
		height: 100%;
		background: var(--primary);
		opacity: 0.6;
		border-radius: 4px;
	}

	.range-info {
		text-align: center;
		font-size: 12px;
		color: var(--text-light);
		font-family: var(--font-body);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.field span {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.field textarea,
	.field input[type='text'] {
		padding: 6px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
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
		gap: 8px;
		margin-top: 4px;
	}

	.cancel-btn,
	.submit-btn {
		padding: 6px 16px;
		border-radius: 4px;
		font-size: 12px;
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

	.submit-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
