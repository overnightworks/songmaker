<script lang="ts">
	import { toasts, dismissToast } from '$lib/stores/toast';
</script>

{#if $toasts.length > 0}
	<div class="toast-container">
		{#each $toasts as toast (toast.id)}
			<div class="toast toast-{toast.type}" role="alert">
				<span class="toast-message">{toast.message}</span>
				<button class="toast-dismiss" onclick={() => dismissToast(toast.id)} aria-label="Dismiss">&times;</button>
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
	}

	.toast-error {
		background: #3a1111;
		border: 1px solid var(--score-bad, #e53935);
		color: #ff8a80;
	}

	.toast-success {
		background: #0a2e1a;
		border: 1px solid var(--score-good, #43a047);
		color: #69f0ae;
	}

	.toast-info {
		background: #1a1a2e;
		border: 1px solid #5c6bc0;
		color: #9fa8da;
	}

	.toast-message {
		flex: 1;
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
