<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { registerHistoryLayer } from '$lib/stores/navigation';
	import { handleFocusTrapKeydown } from '$lib/utils/focus-trap';

	let {
		title,
		items,
		warning = 'This cannot be undone.',
		confirmLabel = 'Delete',
		onconfirm,
		oncancel
	}: {
		title: string;
		items: string[];
		warning?: string;
		confirmLabel?: string;
		onconfirm: () => void;
		oncancel: () => void;
	} = $props();

	const titleId = $props.id();
	let dialog: HTMLDivElement;
	let cancelButton: HTMLButtonElement | undefined;

	// A menu that opens this confirm hands focus back to its trigger in a
	// microtask queued behind the mount, so the opener is read after that.
	onMount(() => {
		let opener: Element | null = null;
		void tick().then(() => {
			if (!cancelButton?.isConnected) return;
			opener = document.activeElement;
			cancelButton.focus();
		});
		return () => {
			if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
		};
	});

	// Back cancels the dialog, never confirms it (issue #1125): it holds one
	// history entry while shown, and each of its own answers steps back off that
	// entry before acting, so a navigation the answer starts lands after it.
	let historyLayer: ReturnType<typeof registerHistoryLayer> | undefined;

	function holdHistoryLayer(): () => void {
		historyLayer = registerHistoryLayer('confirm-delete-dialog', () => oncancel());
		return leaveHistoryLayer;
	}

	function leaveHistoryLayer(): void {
		if (historyLayer?.layered) historyLayer.leave();
	}

	function answer(action: () => void): () => void {
		return () => {
			leaveHistoryLayer();
			action();
		};
	}

	const cancel = answer(() => oncancel());

	// The trap claims Escape with preventDefault before closing, so the page's
	// global Escape (escape-level-up.ts) still yields once the dialog is gone.
	function trapKeys(event: KeyboardEvent): void {
		handleFocusTrapKeydown(dialog, event, cancel);
	}
</script>

<svelte:window onkeydown={trapKeys} />

<div class="overlay" onclick={cancel} role="presentation" {@attach holdHistoryLayer}>
	<div
		class="dialog"
		bind:this={dialog}
		onclick={(e) => e.stopPropagation()}
		onkeydown={trapKeys}
		tabindex="-1"
		role="dialog"
		aria-modal="true"
		aria-labelledby={titleId}
	>
		<h3 id={titleId}>{title}</h3>
		<ul>
			{#each items as item (item)}
				<li>{item}</li>
			{/each}
		</ul>
		<p class="warning">{warning}</p>
		<div class="actions">
			<button class="cancel-btn" bind:this={cancelButton} onclick={cancel}>Cancel</button>
			<button class="confirm-btn" onclick={answer(onconfirm)}>{confirmLabel}</button>
		</div>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.dialog {
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

	ul {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	li {
		font-size: 0.87rem;
		color: var(--text-muted);
		padding-left: 1rem;
		position: relative;
	}

	li::before {
		content: '•';
		position: absolute;
		left: 0;
		color: var(--score-bad);
	}

	.warning {
		font-size: 0.8rem;
		color: var(--score-bad);
		margin: 0;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.6rem;
	}

	.cancel-btn,
	.confirm-btn {
		padding: 0.5rem 1.2rem;
		border-radius: var(--btn-radius-sm);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.cancel-btn {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-muted);
	}

	.cancel-btn:hover {
		border-color: var(--text);
		color: var(--text);
	}

	.confirm-btn {
		background: var(--score-bad);
		border: 1px solid var(--score-bad);
		color: #fff;
	}

	.confirm-btn:hover {
		box-shadow: 0 0 12px rgba(255, 68, 68, 0.3);
	}
</style>
