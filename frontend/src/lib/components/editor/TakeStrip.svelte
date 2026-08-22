<script lang="ts">
	import type { GenerationItem, SongItem } from '$lib/api/types';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		playAlbumFromGeneration,
		playGeneration,
		playLibraryFromGeneration,
		queueContext,
		selectedAlbumId
	} from '$lib/stores/player';
	import { queuePlaybackMode, shouldUseQueueStream } from '$lib/stores/playbackSettings';
	import { addToast } from '$lib/stores/toast';
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

	// Mirrors TakesList's playOrToggle: a take-strip click plays the take
	// immediately — it never opens the take inspector. Every branch here
	// already surfaces its own failures via addToast (playLibraryFromGeneration
	// and playAlbumFromGeneration toast internally), so an archived or
	// otherwise unplayable take reports a toast instead of an unhandled error.
	async function playOrToggle(gen: GenerationItem): Promise<void> {
		if (playingGenId === gen.id && audioPlayer.status === 'playing') {
			audioPlayer.toggle();
			return;
		}
		try {
			const albumId = $selectedAlbumId;
			if (shouldUseQueueStream($queuePlaybackMode)) {
				if (albumId) {
					await playAlbumFromGeneration(albumId, song, gen);
					return;
				}
				await playLibraryFromGeneration(gen);
				return;
			}
			queueContext.set(albumId ? { type: 'album', albumId } : { type: 'library' });
			playGeneration(gen, song, { restart: true });
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Playback failed', 'error');
		}
	}
</script>

{#if sorted.length > 0}
	<div class="take-strip" aria-label="Takes">
		{#each sorted as gen (gen.id)}
			<button
				type="button"
				class="take-chip"
				class:playing={playingGenId === gen.id}
				onclick={() => void playOrToggle(gen)}
				title="v{gen.version_number ?? '—'} · take {gen.generation_number}"
			>
				<Icon name={playingGenId === gen.id ? 'pause' : 'play'} size={14} />
				{#if gen.is_picked}
					<span class="badge picked"><Icon name="star-filled" size={10} /></span>
				{:else if gen.is_kept}
					<span class="badge kept"><Icon name="heart-filled" size={10} /></span>
				{/if}
				<span class="take-chip-label">v{gen.version_number ?? '—'}-{gen.generation_number}</span>
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
	}

	.take-chip {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.25rem;
		flex-shrink: 0;
		width: 2.6rem;
		padding: 0.4rem 0.2rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 50%;
		aspect-ratio: 1;
		color: var(--text-muted);
		cursor: pointer;
	}

	.take-chip.playing {
		border-color: var(--accent);
		color: var(--accent);
	}

	.take-chip-label {
		font-size: 0.55rem;
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
