<script lang="ts">
	import { HITBOX_FREQUENT_PX, SONG_NEXT_LABEL } from '$lib/constants';
	import {
		NOW_PLAYING_CURATE_DONE_LABEL,
		NOW_PLAYING_CURATE_GROUP_LABEL,
		NOW_PLAYING_CURATE_SKIP_LABEL,
		NOW_PLAYING_KEEP_LABEL,
		NOW_PLAYING_PICK_LABEL,
		NOW_PLAYING_UNKEEP_LABEL
	} from '$lib/constants/now-playing';
	import Icon from './Icon.svelte';

	let {
		progressLabel,
		picked,
		kept,
		canSkip,
		onpick,
		onkeep,
		onskip,
		ondone
	}: {
		progressLabel: string;
		picked: boolean;
		kept: boolean;
		canSkip: boolean;
		onpick: () => void;
		onkeep: () => void;
		onskip: () => void;
		ondone: () => void;
	} = $props();
</script>

<div class="curation-bar" role="group" aria-label={NOW_PLAYING_CURATE_GROUP_LABEL}>
	<p class="curation-progress">{progressLabel}</p>
	<div class="curation-actions">
		<button
			type="button"
			class="curate-btn keep"
			class:on={kept}
			onclick={onkeep}
			aria-pressed={kept}
			aria-label={kept ? NOW_PLAYING_UNKEEP_LABEL : NOW_PLAYING_KEEP_LABEL}
			title={kept ? NOW_PLAYING_UNKEEP_LABEL : NOW_PLAYING_KEEP_LABEL}
		>
			<Icon name={kept ? 'heart-filled' : 'heart'} size={22} />
		</button>
		<button
			type="button"
			class="curate-btn pick"
			class:on={picked}
			onclick={onpick}
			aria-label={NOW_PLAYING_PICK_LABEL}
			title={NOW_PLAYING_PICK_LABEL}
		>
			<Icon name={picked ? 'star-filled' : 'star'} size={26} />
		</button>
		<button
			type="button"
			class="curate-btn skip"
			onclick={onskip}
			disabled={!canSkip}
			aria-label={`${NOW_PLAYING_CURATE_SKIP_LABEL} — ${SONG_NEXT_LABEL}`}
			title={NOW_PLAYING_CURATE_SKIP_LABEL}
		>
			<Icon name="skip-forward" size={22} />
		</button>
	</div>
	<button
		type="button"
		class="curation-done"
		style:min-height="{HITBOX_FREQUENT_PX}px"
		onclick={ondone}
	>
		{NOW_PLAYING_CURATE_DONE_LABEL}
	</button>
</div>

<style>
	.curation-bar {
		width: min(320px, 80%);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.6rem;
		padding: 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: color-mix(in srgb, var(--surface) 70%, transparent);
	}
	.curation-progress {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.72rem;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.curation-actions {
		display: flex;
		align-items: center;
		gap: 1.1rem;
	}
	.curate-btn {
		flex-shrink: 0;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 48px;
		height: 48px;
		border-radius: 50%;
		border: 2px solid var(--border);
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
	}
	.curate-btn:hover:not(:disabled) {
		color: var(--text);
		border-color: var(--primary);
		background: var(--surface-hover);
	}
	.curate-btn:disabled {
		color: var(--text-disabled);
		cursor: default;
	}
	.curate-btn.on {
		color: var(--accent);
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}
	.curate-btn.pick {
		width: 60px;
		height: 60px;
		border-color: var(--primary);
		color: var(--primary);
	}
	.curate-btn.pick.on {
		border-color: var(--accent);
		color: var(--accent);
		background: color-mix(in srgb, var(--accent) 18%, var(--surface));
	}
	.curation-done {
		padding: 0.4rem 0.9rem;
		border: none;
		background: none;
		color: var(--text-subtle);
		font-size: 0.76rem;
		text-decoration: underline;
		text-underline-offset: 2px;
		cursor: pointer;
	}
	.curation-done:hover {
		color: var(--text);
	}
</style>
