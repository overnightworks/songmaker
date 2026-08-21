<script lang="ts">
	import { formatCreatedAge, formatExactLocalTime, formatRelativeAge } from '$lib/utils/recency';

	let { createdAt, named = false }: { createdAt?: string | null; named?: boolean } = $props();

	const exact = $derived(formatExactLocalTime(createdAt));
	const relative = $derived(named ? formatCreatedAge(createdAt) : formatRelativeAge(createdAt));
</script>

<span class="age" title={exact} aria-label={exact}>{relative}</span>

<style>
	.age {
		flex-shrink: 0;
		font-size: 0.68rem;
		color: var(--text-subtle);
		letter-spacing: 0.2px;
		text-transform: none;
		font-family: var(--font-body);
	}
</style>
