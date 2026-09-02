<script lang="ts">
	import type { SongItem } from '$lib/api/types';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { nowPlayingTakeLabel } from '$lib/constants/now-playing';
	import { playTake } from '$lib/stores/player';
	import { kineticScroll } from '$lib/actions/kineticScroll';
	import Icon from '../Icon.svelte';

	interface Props {
		song: SongItem;
	}

	let { song }: Props = $props();

	const sorted = $derived(
		[...song.generations].sort((a, b) => {
			const versionDiff = (b.version_number ?? -1) - (a.version_number ?? -1);
			if (versionDiff !== 0) return versionDiff;
			return b.generation_number - a.generation_number;
		})
	);

	const playingGenId = $derived(audioPlayer.current?.generation.id ?? null);

	function openTakeChip(item: HTMLElement) {
		const gen = sorted.find((candidate) => candidate.id === item.dataset.generationId);
		if (gen) void playTake(gen, song);
	}
</script>

{#if sorted.length > 0}
	<div
		class="take-strip"
		aria-label="Takes"
		use:kineticScroll={{ axis: 'x', itemSelector: '.take-chip', onOpen: openTakeChip }}
	>
		{#each sorted as gen (gen.id)}
			{@const label = nowPlayingTakeLabel(gen.version_number, gen.generation_number)}
			<button
				type="button"
				class="take-chip"
				class:playing={playingGenId === gen.id}
				data-generation-id={gen.id}
				title={label}
			>
				<Icon name={playingGenId === gen.id ? 'pause' : 'play'} size={14} />
				{#if gen.is_picked}
					<span class="badge picked"><Icon name="star-filled" size={10} /></span>
				{:else if gen.is_kept}
					<span class="badge kept"><Icon name="heart-filled" size={10} /></span>
				{/if}
				<span class="take-chip-label">{label}</span>
			</button>
		{/each}
	</div>
{/if}

<style>
	.take-strip {
		display: flex;
		gap: 0.5rem;
		overflow-x: auto;
		padding: 0.4rem 0.1rem;
		cursor: grab;
		user-select: none;
		-webkit-user-select: none;
		touch-action: pan-x;
	}

	.take-strip:global(.is-dragging) {
		cursor: grabbing;
	}

	.take-chip {
		position: relative;
		display: flex;
		align-items: center;
		gap: 0.3rem;
		flex-shrink: 0;
		padding: 0.35rem 0.6rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		color: var(--text-muted);
		cursor: pointer;
	}

	.take-chip.playing {
		border-color: var(--accent);
		color: var(--accent);
	}

	.take-chip-label {
		font-size: 0.65rem;
		font-family: var(--font-display);
		letter-spacing: 0.2px;
		white-space: nowrap;
	}

	.badge {
		position: absolute;
		top: -2px;
		right: -2px;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 1rem;
		height: 1rem;
		border-radius: 50%;
		background: var(--bg);
	}

	.badge.picked {
		color: var(--accent);
	}

	.badge.kept {
		color: var(--keep);
	}
</style>
