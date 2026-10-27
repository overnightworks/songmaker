<script lang="ts">
	import Icon from './Icon.svelte';

	// The words are ruled German (Art. 50 AI Act) and stay German in the English UI.
	const WORDS = {
		generated: 'KI-generiert',
		writing: 'Du schreibst mit einer KI'
	} as const;

	// A badge's lead text and the badge share one wrapping row: a long lead pushes the badge
	// onto its own row, whole.
	let { look, lead = '' }: { look: 'badge' | 'line'; lead?: string } = $props();
</script>

{#if look === 'badge'}
	<span class="row">
		{#if lead}<span class="lead">{lead}</span>{/if}
		<span class="ai-notice badge" lang="de"
			><span class="spark" aria-hidden="true"><Icon name="spark" size={14} /></span
			>{WORDS.generated}</span
		>
	</span>
{:else}
	<p class="ai-notice line" lang="de">
		<span class="spark" aria-hidden="true"><Icon name="spark" size={14} /></span>{WORDS.writing}
	</p>
{/if}

<style>
	.ai-notice {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		margin: 0;
		color: var(--text-muted);
		font-size: 0.78rem;
		line-height: 1.35;
	}
	.spark {
		display: inline-flex;
		flex: none;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.2rem 0.6rem;
	}
	.badge {
		padding: 0.1rem 0.6rem 0.1rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		white-space: nowrap;
	}
	.line .spark {
		color: var(--primary);
	}
	.line {
		display: flex;
		flex: none;
		padding: 0.45rem 0.75rem;
		border-bottom: 1px solid var(--border);
	}
</style>
