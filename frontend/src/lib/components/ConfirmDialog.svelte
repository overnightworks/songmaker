<script lang="ts">
	let {
		title,
		message,
		confirmLabel = 'Confirm',
		onconfirm,
		secondaryLabel,
		onsecondary,
		oncancel
	}: {
		title: string;
		message: string;
		confirmLabel?: string;
		onconfirm: () => void;
		secondaryLabel?: string;
		onsecondary?: () => void;
		oncancel: () => void;
	} = $props();

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') oncancel();
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div
	class="overlay"
	onclick={oncancel}
	onkeydown={(e) => e.key === 'Escape' && oncancel()}
	role="presentation"
>
	<div class="dialog" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
		<h3>{title}</h3>
		<p class="message">{message}</p>
		<div class="actions">
			<button class="cancel-btn" onclick={oncancel}>Cancel</button>
			{#if secondaryLabel && onsecondary}
				<button class="secondary-btn" onclick={onsecondary}>{secondaryLabel}</button>
			{/if}
			<button class="confirm-btn" onclick={onconfirm}>{confirmLabel}</button>
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

	.message {
		margin: 0;
		font-size: 0.87rem;
		color: var(--text-muted);
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.6rem;
	}

	.cancel-btn,
	.secondary-btn,
	.confirm-btn {
		padding: 0.5rem 1.2rem;
		border-radius: var(--btn-radius-sm);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.cancel-btn,
	.secondary-btn {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-muted);
	}

	.cancel-btn:hover,
	.secondary-btn:hover {
		border-color: var(--text);
		color: var(--text);
	}

	.confirm-btn {
		background: var(--primary);
		border: 1px solid var(--primary);
		color: #fff;
	}

	.confirm-btn:hover {
		box-shadow: 0 0 12px rgba(160, 32, 240, 0.3);
	}
</style>
