<script lang="ts">
	import { tick } from 'svelte';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import type { UnplayableSongSummary } from '$lib/api/types';

	const SHARE_DIALOG_TITLE = 'Missing from the share page';
	const SHARE_DIALOG_INTRO = "These songs have no playable take and won't appear when shared:";
	const SHARE_DIALOG_CLOSE_LABEL = 'Got it';

	let { songs, onclose }: { songs: UnplayableSongSummary[]; onclose: () => void } = $props();

	let dialog: HTMLDivElement | undefined = $state();

	$effect(() => {
		void tick().then(() => {
			if (dialog) focusFirstIn(dialog);
		});
	});

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!dialog) return;
		handleFocusTrapKeydown(dialog, event, onclose);
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#if songs.length > 0}
	<div class="overlay">
		<button
			class="overlay-backdrop"
			tabindex="-1"
			onclick={onclose}
			aria-label={SHARE_DIALOG_CLOSE_LABEL}
		></button>
		<div
			bind:this={dialog}
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-label={SHARE_DIALOG_TITLE}
			tabindex="-1"
		>
			<h3>{SHARE_DIALOG_TITLE}</h3>
			<p class="message">{SHARE_DIALOG_INTRO}</p>
			<ul>
				{#each songs as song (song.id)}
					<li>{song.title}</li>
				{/each}
			</ul>
			<div class="actions">
				<button class="confirm-btn" onclick={onclose}>{SHARE_DIALOG_CLOSE_LABEL}</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.overlay-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		margin: 0;
		padding: 0;
		border: 0;
		background: rgba(0, 0, 0, 0.6);
		cursor: default;
	}

	.dialog {
		position: relative;
		z-index: 1;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		padding: 1.5rem;
		width: 400px;
		max-width: 90vw;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	h3 {
		margin: 0;
		font-family: var(--font-display);
		font-size: 1.2rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.message {
		margin: 0;
		font-size: 0.87rem;
		color: var(--text-muted);
	}

	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		max-height: 12rem;
		overflow-y: auto;
	}

	li {
		font-size: 0.87rem;
		color: var(--text);
		padding-left: 1rem;
		position: relative;
	}

	li::before {
		content: '•';
		position: absolute;
		left: 0;
		color: var(--score-bad);
	}

	.actions {
		display: flex;
		justify-content: flex-end;
	}

	.confirm-btn {
		padding: 0.5rem 1.2rem;
		border-radius: var(--btn-radius-sm);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
		background: var(--primary);
		border: 1px solid var(--primary);
		color: #fff;
	}

	.confirm-btn:hover {
		box-shadow: 0 0 12px rgba(160, 32, 240, 0.3);
	}
</style>
