<script lang="ts">
	import type { SongItem, GenerationItem } from '$lib/api/types';
	import { playGeneration, togglePlayPause, isAudioPlaying, playback } from '$lib/stores/player';
	import { scoreColor } from '$lib/utils/scores';

	interface Props {
		song: SongItem;
		onselect: (gen: GenerationItem) => void;
		onscore: (genId: string) => void;
		onpick: (genId: string, picked: boolean) => void;
	}

	let { song, onselect, onscore, onpick }: Props = $props();

	const pb = $derived($playback);
	const audioPlaying = $derived($isAudioPlaying);

	interface VersionGroup {
		label: string;
		versionNumber: number | null;
		generations: GenerationItem[];
	}

	const groups = $derived.by((): VersionGroup[] => {
		const map: Record<string, VersionGroup> = {};
		for (const gen of song.generations) {
			const key = gen.version_number !== null ? `v${gen.version_number}` : 'unknown';
			if (!map[key]) {
				map[key] = {
					label: gen.version_number !== null ? `Version ${gen.version_number}` : 'Unknown version',
					versionNumber: gen.version_number,
					generations: []
				};
			}
			map[key].generations.push(gen);
		}
		const result = Object.values(map);
		result.sort((a, b) => (b.versionNumber ?? -1) - (a.versionNumber ?? -1));
		return result;
	});

	function isGenPlaying(gen: GenerationItem): boolean {
		return pb?.generation.id === gen.id;
	}

	function handlePlay(e: Event, gen: GenerationItem): void {
		e.stopPropagation();
		if (isGenPlaying(gen)) togglePlayPause();
		else playGeneration(gen, song);
	}
</script>

{#if song.generations.length === 0}
	<div class="empty">No generations yet — hit Generate to create some</div>
{:else}
	<div class="gen-list">
		{#each groups as group (group.label)}
			<div class="version-section">
				<div class="version-header">{group.label}</div>
				{#each group.generations as gen (gen.id)}
					<div
						class="gen-card"
						class:playing={isGenPlaying(gen)}
						onclick={() => onselect(gen)}
						onkeydown={(e) => e.key === 'Enter' && onselect(gen)}
						role="button"
						tabindex="0"
					>
						<button
							class="play-btn"
							onclick={(e) => handlePlay(e, gen)}
							aria-label={isGenPlaying(gen) && audioPlaying ? 'Pause' : 'Play'}
						>
							{#if isGenPlaying(gen) && audioPlaying}⏸{:else}▶{/if}
						</button>

						<div class="gen-info">
							<span class="gen-name">
								{#if gen.is_picked}<span class="picked-star">★</span>{/if}
								gen{gen.generation_number}
							</span>
							{#if gen.seed}
								<span class="gen-seed">seed:{gen.seed}</span>
							{/if}
						</div>

						<div class="gen-actions">
							{#if gen.scores?.user_rating !== undefined}
								<span class="score-badge {scoreColor('user_rating', gen.scores.user_rating)}">
									{gen.scores.user_rating.toFixed(0)}
								</span>
							{/if}
							{#if gen.scores?.audiobox_quality !== undefined}
								<span
									class="score-mini {scoreColor('audiobox_quality', gen.scores.audiobox_quality)}"
								>
									Q:{gen.scores.audiobox_quality.toFixed(1)}
								</span>
							{/if}
							{#if gen.scores?.audiobox_enjoyment !== undefined}
								<span
									class="score-mini {scoreColor(
										'audiobox_enjoyment',
										gen.scores.audiobox_enjoyment
									)}"
								>
									E:{gen.scores.audiobox_enjoyment.toFixed(1)}
								</span>
							{/if}
							<button
								class="pick-btn"
								class:picked={gen.is_picked}
								onclick={(e) => {
									e.stopPropagation();
									onpick(gen.id, !gen.is_picked);
								}}
								aria-label={gen.is_picked ? 'Unpick' : 'Pick for album'}
							>
								{gen.is_picked ? '★' : '☆'}
							</button>
							<button
								class="score-action"
								onclick={(e) => {
									e.stopPropagation();
									onscore(gen.id);
								}}
								aria-label="Score generation"
							>
								Score
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/each}
	</div>
{/if}

<style>
	.gen-list {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.version-section {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.version-header {
		font-size: 10px;
		color: var(--text-dim);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
		padding: 4px 0;
	}

	.gen-card {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		cursor: pointer;
		text-align: left;
		color: var(--text);
		font: inherit;
		width: 100%;
	}

	.gen-card:hover {
		border-color: rgba(160, 32, 240, 0.3);
		background: var(--surface-hover);
	}

	.gen-card.playing {
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
	}

	.play-btn {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		border: 2px solid var(--border);
		background: transparent;
		color: var(--text-muted);
		font-size: 14px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.play-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.gen-card.playing .play-btn {
		border-color: var(--accent);
		color: var(--accent);
	}

	.gen-info {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.gen-name {
		font-family: var(--font-display);
		font-size: 13px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.picked-star {
		color: var(--accent);
		text-shadow: 0 0 6px rgba(160, 32, 240, 0.4);
	}

	.gen-seed {
		font-size: 10px;
		color: var(--text-dim);
	}

	.gen-actions {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.score-badge {
		font-family: var(--font-display);
		font-size: 16px;
		min-width: 28px;
		text-align: center;
	}

	.score-badge.good {
		color: var(--score-good);
	}

	.score-badge.ok {
		color: var(--score-ok);
	}

	.score-badge.bad {
		color: var(--score-bad);
	}

	.score-mini {
		font-size: 10px;
		font-family: var(--font-display);
	}

	.score-mini.good {
		color: var(--score-good);
	}

	.score-mini.ok {
		color: var(--score-ok);
	}

	.score-mini.bad {
		color: var(--score-bad);
	}

	.pick-btn {
		background: none;
		border: none;
		font-size: 16px;
		cursor: pointer;
		color: var(--text-dim);
		padding: 2px;
	}

	.pick-btn:hover {
		color: var(--accent);
	}

	.pick-btn.picked {
		color: var(--accent);
		text-shadow: 0 0 6px rgba(160, 32, 240, 0.4);
	}

	.score-action {
		padding: 3px 8px;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: none;
		color: var(--text-dim);
		font-size: 10px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.score-action:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.empty {
		padding: 40px 20px;
		text-align: center;
		color: var(--text-dim);
		font-style: italic;
		font-size: 13px;
	}

	@media (max-width: 768px) {
		.gen-card {
			padding: 8px 10px;
			gap: 8px;
		}

		.score-mini {
			display: none;
		}

		.score-action {
			display: none;
		}
	}
</style>
