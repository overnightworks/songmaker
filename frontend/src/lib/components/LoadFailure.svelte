<script lang="ts">
	import Icon from '#lib/components/Icon.svelte';

	let {
		message,
		retryLabel,
		onretry
	}: { message: string; retryLabel: string; onretry: () => void } = $props();
</script>

<div class="load-error" role="alert">
	<span class="load-error-title">
		<Icon name="triangle-alert" size={16} />{message}
	</span>
	<div class="load-error-foot">
		<button
			type="button"
			class="retry-btn"
			data-hitbox="frequent"
			data-hitbox-face
			onclick={onretry}
			aria-label={retryLabel}
			title={retryLabel}
		>
			<Icon name="refresh-cw" size={16} />
		</button>
	</div>
</div>

<style>
	.load-error {
		display: flex;
		flex-direction: column;
		gap: 9px;
		margin-bottom: 12px;
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--fail);
		border-radius: var(--card-radius);
	}

	.load-error-title {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 15px;
		color: var(--fail);
	}

	.load-error-foot {
		display: flex;
		justify-content: flex-end;
		color: var(--fail);
	}

	.retry-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: none;
		padding: 0;
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
	}

	.retry-btn:hover {
		color: var(--primary);
	}
</style>
