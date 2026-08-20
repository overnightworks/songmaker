<script lang="ts">
	import { APP_NAME } from '$lib/constants';

	interface Props {
		kind: 'loading' | 'missing' | 'error';
		resource: string;
		onretry?: () => void;
	}

	let { kind, resource, onretry }: Props = $props();

	const heading =
		kind === 'loading'
			? `Loading ${resource}`
			: kind === 'missing'
				? `${resource} not found`
				: `Could not load this ${resource}`;
</script>

<section class="share-status" aria-live="polite">
	<h1 tabindex="-1">{heading}</h1>
	{#if kind === 'missing'}
		<p>This share link is invalid or was removed.</p>
		<a class="primary" href="/login">Go to {APP_NAME}</a>
	{:else if kind === 'error'}
		<p>Something went wrong while loading this {resource}.</p>
		{#if onretry}
			<button type="button" class="primary" onclick={onretry}>Try again</button>
		{/if}
		<a href="/login">Go to {APP_NAME}</a>
	{/if}
</section>

<style>
	.share-status {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
		min-height: 40vh;
		padding: 2rem 1.25rem;
		text-align: center;
	}

	h1 {
		margin: 0;
		font-size: 1.4rem;
	}

	p {
		margin: 0;
		color: var(--text-muted);
		max-width: 28rem;
	}

	.primary {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		margin-top: 0.5rem;
		padding: 0.55rem 1.1rem;
		border-radius: 8px;
		background: var(--primary);
		color: white;
		text-decoration: none;
		border: none;
		font: inherit;
		cursor: pointer;
	}

	a:not(.primary) {
		color: var(--text-dim);
	}
</style>
