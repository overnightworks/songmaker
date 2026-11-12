<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path, and backHref is already a resolved library address */
	type Props =
		| { kind: 'loading'; message: string }
		| {
				kind: 'unknown';
				head: string;
				explanation: string;
				backLabel: string;
				backHref: string;
		  }
		| { kind: 'unreachable'; message: string; retryLabel: string; onRetry: () => void };

	const overlay: Props = $props();
</script>

{#if overlay.kind === 'loading'}
	<div class="address-overlay">{overlay.message}</div>
{:else if overlay.kind === 'unknown'}
	<div class="address-overlay" role="alert">
		<h1>{overlay.head}</h1>
		<p>{overlay.explanation}</p>
		<a class="address-action" href={overlay.backHref}>{overlay.backLabel}</a>
	</div>
{:else}
	<div class="address-overlay" role="alert">
		<p>{overlay.message}</p>
		<button class="address-action" type="button" onclick={overlay.onRetry}
			>{overlay.retryLabel}</button
		>
	</div>
{/if}

<style>
	.address-overlay {
		position: absolute;
		inset: 0;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 16px;
		padding: 0 24px;
		text-align: center;
		color: var(--text-muted);
		background: var(--bg);
	}

	.address-overlay h1 {
		margin: 0;
		font-family: var(--font-display);
		font-size: 1.4rem;
		color: var(--text);
	}

	.address-overlay p {
		margin: 0;
	}

	.address-action {
		padding: 6px 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		text-decoration: none;
		cursor: pointer;
	}

	.address-action:hover {
		border-color: var(--accent);
		color: var(--accent);
	}
</style>
