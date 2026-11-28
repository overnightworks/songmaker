<script lang="ts">
	import type { GenerationItem, SongItem } from '#lib/api/types.ts';
	import { takeVersion } from '#lib/constants/now-playing.ts';
	import { appPageAddress, followAppPageLink } from '#lib/stores/navigation.ts';
	import { buildTakeRecipe } from '#lib/utils/recipe-summary.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import { formatTime } from '#lib/utils/format.ts';
	import Icon from './Icon.svelte';

	let {
		generation,
		song
	}: {
		generation: GenerationItem;
		song: SongItem;
	} = $props();

	const openableVersion = $derived(takeVersion(generation.version_id, generation.version_number));
	// "v · take · duration · mode": the duration shows only when the take has
	// one and the mode only when it names a model. An imported take has no
	// version and no model of ours to name.
	const takeHeading = $derived.by((): string => {
		if (!openableVersion) return pageText('nowPlayingTake.importedHeading');
		const durationSec = generation.audio_duration_sec ?? null;
		const gaps = {
			version: String(openableVersion.versionNumber),
			take: String(generation.generation_number),
			duration: durationSec !== null && durationSec > 0 ? formatTime(durationSec) : '',
			mode: generation.model_mode || ''
		};
		if (gaps.duration && gaps.mode) return pageText('nowPlayingTake.headingDurationMode', gaps);
		if (gaps.duration) return pageText('nowPlayingTake.headingDuration', gaps);
		if (gaps.mode) return pageText('nowPlayingTake.headingMode', gaps);
		return pageText('nowPlayingTake.heading', gaps);
	});

	const recipeGroups = $derived(buildTakeRecipe(generation, song));
</script>

<div
	class="np-take"
	aria-label={pageText('nowPlayingTake.label', { number: String(generation.generation_number) })}
>
	<div class="take-heading-row">
		<h3 class="take-heading">{takeHeading}</h3>
	</div>

	{#if recipeGroups.length > 0}
		<section class="take-section">
			<details class="recipe-section">
				<summary class="section-title recipe-summary-toggle">
					{pageText('nowPlayingTake.recipe')}
				</summary>
				<div class="recipe-groups">
					{#each recipeGroups as group (group.label)}
						<div class="recipe-group">
							<h5 class="recipe-group-label">{group.label}</h5>
							<dl class="recipe-list">
								{#each group.entries as entry (entry.label)}
									<div class="recipe-row">
										<dt>{entry.label}</dt>
										<dd>
											{#if entry.link}
												{@const link = entry.link}
												<!-- eslint-disable svelte/no-navigation-without-resolve -- appPageAddress resolves the route -->
												<a
													class="recipe-link"
													href={appPageAddress(link.route, link.query)}
													onclick={(event) => followAppPageLink(event, link.route, link.query)}
												>
													<span class="recipe-link-name">{entry.value}</span><Icon
														name="chevron-right"
														size={12}
														class="recipe-link-chevron"
													/>
												</a>
												<!-- eslint-enable svelte/no-navigation-without-resolve -->
											{:else}
												{entry.value}
											{/if}
										</dd>
									</div>
								{/each}
							</dl>
						</div>
					{/each}
				</div>
			</details>
		</section>
	{/if}
</div>

<style>
	.np-take {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		min-width: 0;
	}
	.take-heading-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.take-heading {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.72rem;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.take-section {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
	}
	.section-title {
		font-family: var(--font-display);
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-subtle);
	}
	.recipe-section {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
	}
	.recipe-summary-toggle {
		cursor: pointer;
		list-style: disclosure-closed;
	}
	.recipe-section[open] > .recipe-summary-toggle {
		list-style: disclosure-open;
	}
	.recipe-summary-toggle:hover {
		color: var(--text);
	}
	.recipe-groups {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		margin-top: 0.5rem;
	}
	.recipe-group-label {
		margin: 0 0 0.3rem;
		font-size: 0.64rem;
		text-transform: uppercase;
		letter-spacing: 0.4px;
		font-family: var(--font-display);
		color: var(--text-subtle);
	}
	.recipe-list {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
	}
	.recipe-row {
		display: flex;
		justify-content: space-between;
		gap: 0.6rem;
		font-size: 0.78rem;
		padding: 0.15rem 0;
		border-bottom: 1px solid var(--border);
	}
	.recipe-row:last-child {
		border-bottom: none;
	}
	.recipe-row dt {
		color: var(--text-subtle);
	}
	.recipe-row dd {
		margin: 0;
		color: var(--text);
		font-family: var(--font-display);
		text-align: right;
	}
	.recipe-link {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 2px;
		color: var(--accent);
		text-decoration: none;
	}
	.recipe-link :global(.recipe-link-chevron) {
		flex: none;
	}
</style>
