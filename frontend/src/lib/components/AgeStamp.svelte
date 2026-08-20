<script lang="ts">
	import { formatExactLocalTime, formatRelativeAge } from '$lib/utils/recency';

	let { createdAt }: { createdAt?: string | null } = $props();

	const exact = $derived(formatExactLocalTime(createdAt));
	const relative = $derived(formatRelativeAge(createdAt));
</script>

<span class="age" title={exact} aria-label={exact}>{relative}</span>

<style>
	.age {
		flex-shrink: 0;
		font-size: 0.68rem;
		color: var(--text-dim);
		letter-spacing: 0.2px;
		text-transform: none;
		font-family: var(--font-body);
	}
</style>
