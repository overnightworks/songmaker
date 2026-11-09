<script lang="ts">
	import { EXPIRY_WARN_DAYS } from '#lib/constants/expiry.ts';
	import { localDayAndMonth, localDaysBetween } from '#lib/utils/format.ts';

	let { deletesAt, now }: { deletesAt: string; now: Date } = $props();

	const deletion = $derived.by(() => {
		const deletesOn = new Date(deletesAt);
		return {
			days: Math.max(localDaysBetween(now, deletesOn), 0),
			tooltip: `Deleted on ${localDayAndMonth(deletesOn, now)} — keep to preserve`
		};
	});
</script>

<span class="exp" class:warn={deletion.days <= EXPIRY_WARN_DAYS} title={deletion.tooltip}
	>⏳ {deletion.days}d</span
>

<style>
	.exp {
		display: inline-block;
		margin-inline-start: 3px;
		padding: 0 5px;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: var(--bg);
		font-size: 12px;
		line-height: 18px;
		color: var(--text-muted);
		white-space: nowrap;
	}

	.exp.warn {
		border-color: var(--warn-line);
		background: var(--warn-bg);
		color: var(--warn-ink);
	}
</style>
