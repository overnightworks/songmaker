<script lang="ts">
	import type { ReferenceRecordingResponse } from '#lib/api/types.ts';
	import Icon from '#lib/components/Icon.svelte';
	import ReferenceMenu from '#lib/components/ReferenceMenu.svelte';
	import ReferenceUses from '#lib/components/ReferenceUses.svelte';
	import {
		REFERENCE_KEEP_LABEL,
		REFERENCE_UNKEEP_LABEL,
		TRANSPORT_PAUSE_LABEL,
		TRANSPORT_PLAY_LABEL
	} from '#lib/constants.ts';
	import { formatTime, localDayAndMonth } from '#lib/utils/format.ts';

	const NO_LENGTH = '—';
	const META_SEPARATOR = ' · ';

	let {
		reference,
		now,
		playing,
		fault,
		usesOpen,
		ontoggle,
		onusestoggle,
		onshowuses,
		onkeeptoggle,
		ondelete
	}: {
		reference: ReferenceRecordingResponse;
		now: Date;
		playing: boolean;
		fault: string | null;
		usesOpen: boolean;
		ontoggle: () => void;
		onusestoggle: () => void;
		onshowuses: () => void;
		onkeeptoggle: () => void;
		ondelete: () => void;
	} = $props();

	function lengthLabel(durationSec: number | null): string {
		return durationSec === null ? NO_LENGTH : formatTime(durationSec);
	}

	function metaLabel(): string {
		const uploaded = localDayAndMonth(new Date(reference.created_at), now);
		return `${lengthLabel(reference.duration_sec)}${META_SEPARATOR}${uploaded}`;
	}

	function usedLabel(): string {
		const counts = [
			[reference.used_by_takes, 'take'],
			[reference.used_by_versions, 'version']
		] as const;
		const kinds = counts
			.filter(([count]) => count > 0)
			.map(([count, noun]) => `${count} ${noun}${count === 1 ? '' : 's'}`);
		return `Used in ${kinds.join(', ')}`;
	}
</script>

<!-- Keyboard users reach the row through its button, so the row takes no focus. -->
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<li
	class="reference-row"
	class:playing
	onclick={(event) => {
		if ((event.target as Element).closest('.reference-uses')) return;
		ontoggle();
	}}
>
	<button
		type="button"
		class="reference-play"
		aria-label={`${playing ? TRANSPORT_PAUSE_LABEL : TRANSPORT_PLAY_LABEL} ${reference.filename}`}
		onclick={(event) => {
			event.stopPropagation();
			ontoggle();
		}}
	>
		<Icon name={playing ? 'pause' : 'play'} size={16} />
	</button>
	<span class="reference-text">
		<span class="reference-name" title={reference.filename}>{reference.filename}</span>
		<span class="reference-meta"
			>{metaLabel()}{#if reference.in_use}{META_SEPARATOR}<button
					type="button"
					class="reference-used"
					aria-expanded={usesOpen}
					aria-controls={usesOpen ? `uses-${reference.id}` : undefined}
					onclick={(event) => {
						event.stopPropagation();
						onusestoggle();
					}}>{usedLabel()}</button
				>
			{/if}</span
		>
		{#if fault !== null}
			<span class="reference-meta reference-fault" role="alert">{fault}</span>
		{/if}
	</span>
	<button
		type="button"
		class="reference-keep"
		class:kept={reference.is_kept}
		data-hitbox="frequent"
		aria-pressed={reference.is_kept}
		aria-label={`${reference.is_kept ? REFERENCE_UNKEEP_LABEL : REFERENCE_KEEP_LABEL} ${reference.filename}`}
		onclick={(event) => {
			event.stopPropagation();
			onkeeptoggle();
		}}
	>
		<Icon name={reference.is_kept ? 'heart-filled' : 'heart'} size={16} />
	</button>
	<!-- The menu's clicks are the menu's own, never the row's preview toggle. -->
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<span class="reference-menu" onclick={(event) => event.stopPropagation()}>
		<ReferenceMenu
			filename={reference.filename}
			inUse={reference.in_use}
			usesCount={reference.used_by_takes + reference.used_by_versions}
			{onshowuses}
			{ondelete}
		/>
	</span>
	{#if usesOpen}
		<div class="reference-uses">
			<ReferenceUses id={`uses-${reference.id}`} referenceId={reference.id} />
		</div>
	{/if}
</li>

<style>
	.reference-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 12px;
		min-width: 0;
		min-height: 56px;
		padding: 6px 14px;
		cursor: pointer;
	}

	.reference-uses {
		flex: 1 0 100%;
		margin: 0 -14px -6px;
		cursor: default;
	}

	.reference-row.playing {
		background: color-mix(in srgb, var(--accent) 10%, var(--surface));
	}

	.reference-play {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 32px;
		height: 32px;
		padding: 0;
		background: none;
		border: 1px solid var(--border);
		border-radius: 50%;
		color: var(--text);
		cursor: pointer;
	}

	.reference-row.playing .reference-play {
		border-color: var(--accent);
		color: var(--accent);
	}

	.reference-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
		min-width: 0;
	}

	.reference-keep {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: none;
		padding: 0;
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
	}

	.reference-keep:hover,
	.reference-keep.kept {
		color: var(--keep);
	}

	.reference-menu {
		display: flex;
		flex: none;
	}

	.reference-name {
		font-size: 15px;
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.reference-meta {
		font-size: 12px;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}

	.reference-used {
		position: relative;
		padding: 0;
		background: none;
		border: none;
		font: inherit;
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 2px;
		cursor: pointer;
	}

	/* The text stays 12px in the meta line; the pointer target grows around it. */
	.reference-used::after {
		content: '';
		position: absolute;
		inset: calc((100% - var(--hitbox-frequent)) / 2) 0;
	}

	.reference-fault {
		color: var(--fail);
	}

	@media (max-width: 640px) {
		.reference-row {
			min-height: 64px;
		}

		.reference-play {
			width: 40px;
			height: 40px;
		}
	}
</style>
