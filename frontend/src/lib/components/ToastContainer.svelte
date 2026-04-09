<script lang="ts">
	import { toasts, dismissToast } from '$lib/stores/toast';
</script>

{#if $toasts.length > 0}
	<div class="toast-container">
		{#each $toasts as toast (toast.id)}
			<div class="toast toast-{toast.type}" role="alert">
				<span class="toast-message">{toast.message}</span>
				{#if toast.action}
					<button class="toast-action" onclick={() => toast.action?.handler()}>
						{toast.action.label}
					</button>
				{/if}
				<button class="toast-dismiss" onclick={() => dismissToast(toast.id)} aria-label="Dismiss"
					>&times;</button
				>
			</div>
		{/each}
	</div>
{/if}

<style>
	.toast-container {
		position: fixed;
		bottom: 1rem;
		right: 1rem;
		z-index: 9999;
		display: flex;
		flex-direction: column-reverse;
		gap: 0.5rem;
		max-width: 400px;
	}

	.toast {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		border-radius: 8px;
		font-size: 0.875rem;
		line-height: 1.4;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
		animation: slide-in 0.2s ease-out;
		backdrop-filter: blur(10px);
	}

	.toast-error {
		background: rgba(58, 17, 17, 0.9);
		border: 1px solid var(--score-bad, #e53935);
		color: #ff8a80;
		box-shadow: 0 4px 16px rgba(255, 68, 68, 0.15);
	}

	.toast-success {
		background: rgba(10, 46, 26, 0.9);
		border: 1px solid var(--score-good, #43a047);
		color: #69f0ae;
		box-shadow: 0 4px 16px rgba(67, 160, 71, 0.15);
	}

	.toast-info {
		background: rgba(26, 12, 46, 0.9);
		border: 1px solid var(--accent, #a020f0);
		color: #ce93d8;
		box-shadow: 0 4px 16px rgba(160, 32, 240, 0.15);
	}

	.toast-message {
		flex: 1;
	}

	.toast-action {
		background: rgba(255, 255, 255, 0.1);
		border: 1px solid currentColor;
		color: inherit;
		padding: 0.25rem 0.6rem;
		border-radius: 4px;
		font-size: 0.8rem;
		cursor: pointer;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.toast-action:hover {
		background: rgba(255, 255, 255, 0.2);
	}

	.toast-dismiss {
		background: none;
		border: none;
		color: inherit;
		opacity: 0.6;
		font-size: 1.25rem;
		cursor: pointer;
		padding: 0;
		line-height: 1;
	}

	.toast-dismiss:hover {
		opacity: 1;
	}

	.toast-error .toast-dismiss {
		opacity: 1;
		border: 1px solid currentColor;
		border-radius: 4px;
		width: 1.5rem;
		height: 1.5rem;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	@keyframes slide-in {
		from {
			transform: translateX(100%);
			opacity: 0;
		}
		to {
			transform: translateX(0);
			opacity: 1;
		}
	}

	@media (max-width: 768px) {
		.toast-container {
			left: 1rem;
			right: 1rem;
			max-width: none;
		}
	}
</style>
