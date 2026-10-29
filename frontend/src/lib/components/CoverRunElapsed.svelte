<script lang="ts">
	import { formatTime } from '#lib/utils/format.ts';

	const TICK_MS = 1000;

	let { startedAt, separated = true }: { startedAt: string; separated?: boolean } = $props();

	let now = $state(Date.now());

	$effect(() => {
		now = Date.now();
		const timer = setInterval(() => (now = Date.now()), TICK_MS);
		return () => clearInterval(timer);
	});

	const elapsedSeconds = $derived(Math.max(0, (now - Date.parse(startedAt)) / TICK_MS));
</script>

<span aria-hidden="true"
	>{#if separated}&nbsp;·&nbsp;{/if}{formatTime(elapsedSeconds)}</span
>
