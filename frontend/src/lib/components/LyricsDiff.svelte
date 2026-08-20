<script lang="ts">
	import { computeDiff } from '$lib/utils/diff';

	interface Props {
		oldText: string;
		newText: string;
		oldLabel?: string;
		newLabel?: string;
	}

	let { oldText, newText, oldLabel = 'Previous', newLabel = 'Current' }: Props = $props();

	const diffLines = $derived(computeDiff(oldText, newText));
	const hasChanges = $derived(diffLines.some((l) => l.type !== 'same'));
</script>

{#if hasChanges}
	<div class="diff-view">
		<div class="diff-header">
			<span class="diff-label remove-label">{oldLabel}</span>
			<span class="diff-arrow">→</span>
			<span class="diff-label add-label">{newLabel}</span>
		</div>
		<pre class="diff-content">{#each diffLines as line, i (i)}<span class="diff-line {line.type}"
					>{#if line.type === 'remove'}- {line.text}{:else if line.type === 'add'}+ {line.text}{:else}
						{line.text}{/if}
</span>{/each}</pre>
	</div>
{:else}
	<p class="no-changes">No changes</p>
{/if}

<style>
	.diff-view {
		border: 1px solid var(--border);
		border-radius: 4px;
		overflow: hidden;
	}

	.diff-header {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 10px;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
		font-size: 0.7rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.diff-label {
		color: var(--text-muted);
	}

	.remove-label {
		color: var(--score-bad);
	}

	.add-label {
		color: var(--score-good);
	}

	.diff-arrow {
		color: var(--text-decoration);
	}

	.diff-content {
		margin: 0;
		padding: 8px 0;
		font-family: 'Courier New', monospace;
		font-size: var(--label-font-size);
		line-height: 1.5;
		overflow-x: auto;
		max-height: 300px;
		overflow-y: auto;
	}

	.diff-line {
		display: block;
		padding: 0 10px;
	}

	.diff-line.remove {
		background: var(--score-bad-bg);
		color: var(--score-bad);
	}

	.diff-line.add {
		background: var(--score-good-bg);
		color: var(--score-good);
	}

	.diff-line.same {
		color: var(--text-muted);
	}

	.no-changes {
		font-size: var(--label-font-size);
		color: var(--text-subtle);
		font-style: italic;
	}
</style>
