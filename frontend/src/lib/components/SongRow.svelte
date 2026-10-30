<script lang="ts">
	import type { Snippet } from 'svelte';
	import { songEditorOpenLabel } from '#lib/constants.ts';
	import Icon from './Icon.svelte';
	import PlayingMark from './PlayingMark.svelte';

	interface Props {
		title: string;
		/** A second line under the title: whose take it is, and which. */
		detail?: string;
		/** A short note at the end of the title's line, such as the take count. */
		meta?: string;
		/** Whether the take is the one picked for its song. */
		picked?: boolean;
		/** Whether the transport holds this song: the box turns violet and carries the playing mark. */
		current: boolean;
		/** What a tap anywhere on the box does. */
		onclick: () => void;
		/** Gives the box its ✎, which opens the song editor; a surface without the editor passes none. */
		onedit?: () => void;
		/** The surface's own ⋯ after the ✎, sized to the frequent hitbox like it. */
		menu?: Snippet;
	}

	let { title, detail, meta, picked = false, current, onclick, onedit, menu }: Props = $props();

	const controlCount = $derived(Number(Boolean(onedit)) + Number(Boolean(menu)));
</script>

<!-- The box and its controls share the box's one grid cell (#1053): the box's
     target fills the whole card, and the later-painted controls stay their own
     targets above it, with the box's text kept clear of them. -->
<div class="song-row song-row-frame" class:current style:--song-row-controls={controlCount}>
	<button type="button" class="song-row-body" data-hitbox="text" {onclick}>
		<PlayingMark {current} />
		<span class="song-row-text">
			<span class="song-row-title">
				{#if picked}<span class="picked-star">★</span>{/if}
				{title}
			</span>
			{#if detail}<span class="song-row-detail">{detail}</span>{/if}
		</span>
		{#if meta}<span class="song-row-meta">{meta}</span>{/if}
	</button>
	{#if controlCount > 0}
		<div class="song-row-controls">
			{#if onedit}
				<button
					type="button"
					class="song-row-edit"
					data-hitbox="frequent"
					aria-label={songEditorOpenLabel(title)}
					title={songEditorOpenLabel(title)}
					onclick={onedit}
				>
					<Icon name="pencil" size={18} />
				</button>
			{/if}
			{@render menu?.()}
		</div>
	{/if}
</div>

<style>
	/* What decides a row's height, owned once: the album's + New song row wears
	   this frame too, so it stands exactly as high as a song box whatever font
	   the platform resolves — a length line height, not the font's "normal". */
	:global(.song-row-frame) {
		--song-row-inset-block: 0.65rem;
		--song-row-inset-inline: 0.8rem;
		--song-row-line-height: 1.4rem;
		border: 1px solid transparent;
		border-radius: var(--card-radius);
	}

	.song-row {
		--song-row-controls-gap: 0.5rem;
		display: grid;
		grid-template-areas: 'row';
		background: var(--surface);
		border-color: var(--border);
		color: var(--text);
		transition:
			background 0.15s,
			border-color 0.15s;
	}

	.song-row:hover {
		border-color: color-mix(in srgb, var(--accent) 30%, transparent);
		background: var(--surface-hover);
	}

	.song-row.current {
		border-color: var(--accent);
	}

	.song-row.current .song-row-title {
		color: var(--accent);
		font-weight: 600;
	}

	.song-row-body {
		grid-area: row;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		background: none;
		border: none;
		padding: var(--song-row-inset-block)
			calc(
				var(--song-row-inset-inline) + var(--song-row-controls) *
					(var(--hitbox-frequent) + var(--song-row-controls-gap))
			)
			var(--song-row-inset-block) var(--song-row-inset-inline);
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	/* The global press scale would shrink the target mid-press and send a release
	   near the box's edge to the box. */
	.song-row .song-row-body:active:not(:disabled) {
		transform: none;
	}

	.song-row-text {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
	}

	.song-row-title {
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 1rem;
		line-height: var(--song-row-line-height);
	}

	.picked-star {
		color: var(--accent);
	}

	.song-row-detail {
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.song-row-meta {
		flex-shrink: 0;
		font-size: 0.8rem;
		line-height: var(--song-row-line-height);
		color: var(--text-muted);
	}

	.song-row-controls {
		grid-area: row;
		justify-self: end;
		align-self: center;
		margin-right: var(--song-row-inset-inline);
		display: flex;
		align-items: center;
		gap: var(--song-row-controls-gap);
	}

	.song-row-edit {
		background: none;
		border: none;
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
	}

	.song-row-edit:hover {
		color: var(--accent);
	}

	@media (max-width: 768px) {
		:global(.song-row-frame) {
			--song-row-inset-block: 0.7rem;
			--song-row-inset-inline: 0.7rem;
			min-height: 62px;
		}

		.song-row {
			--song-row-controls-gap: 0.35rem;
		}
	}
</style>
