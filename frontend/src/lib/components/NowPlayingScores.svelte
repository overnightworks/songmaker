<script lang="ts">
	import type { GenerationItem } from '#lib/api/types.ts';
	import { rescoringTakeIds } from '#lib/stores/takeActions.ts';
	import { pageLanguage } from '#lib/utils/page-language.ts';
	import { pageText, type TextKey } from '#lib/utils/page-words.ts';
	import { formatScore, scoreColor, scoreReadings, type ScoreKey } from '#lib/utils/scores.ts';

	// The footer of the desktop lyrics column and the chips row of the phone and
	// the docked panel read the same scores; neither carries a control, since
	// Re-score is a row of the take menu and the judging card shows the rating.
	let { generation, look }: { generation: GenerationItem; look: 'footer' | 'chips' } = $props();

	const SCORE_LABEL_KEYS: Record<Exclude<ScoreKey, 'user_rating'>, TextKey> = {
		text_accuracy: 'nowPlayingScores.lyricsSung',
		dynamics: 'nowPlayingScores.dynamics',
		audiobox_quality: 'nowPlayingScores.quality',
		audiobox_enjoyment: 'nowPlayingScores.enjoyment',
		lyrical_coherence: 'nowPlayingScores.coherence'
	};

	interface ScoreEntry {
		label: string;
		value: string;
		color: string;
	}

	const rescoring = $derived($rescoringTakeIds.has(generation.id));

	const entries = $derived.by((): ScoreEntry[] => {
		const scores = generation.scores;
		const listed: ScoreEntry[] = scoreReadings(scores).flatMap(({ metric, value }) =>
			metric.key === 'user_rating'
				? []
				: [
						{
							label: pageText(SCORE_LABEL_KEYS[metric.key]),
							value: formatScore(metric, value, 'panel'),
							color: scoreColor(metric.key, value)
						}
					]
		);
		// BPM colours itself from how far the take drifted from the requested
		// tempo, not from a score threshold.
		if (scores?.bpm_detected !== undefined) {
			const deviation = scores.bpm_deviation ?? 0;
			listed.push({
				label: pageText('nowPlayingScores.bpm'),
				value: new Intl.NumberFormat(pageLanguage(), { maximumFractionDigits: 0 }).format(
					scores.bpm_detected
				),
				color: deviation < 5 ? 'good' : deviation < 15 ? 'ok' : 'bad'
			});
		}
		return listed;
	});
</script>

<section class="scores {look}" aria-label={pageText('nowPlayingScores.heading')}>
	{#if look === 'footer'}
		<h4 class="heading">{pageText('nowPlayingScores.heading')}</h4>
	{/if}
	<ul class="entries">
		{#each entries as entry (entry.label)}
			<li class="entry {entry.color}">
				<span class="label">{entry.label}</span>
				<span class="value"><span class="dot" aria-hidden="true"></span>{entry.value}</span>
			</li>
		{/each}
	</ul>
	{#if rescoring}
		<p class="note" role="status">{pageText('nowPlayingScores.rescoring')}</p>
	{:else if entries.length === 0}
		<p class="note">{pageText('nowPlayingScores.empty')}</p>
	{/if}
</section>

<style>
	.scores {
		flex-shrink: 0;
		display: flex;
		min-width: 0;
		gap: 0.4rem 0.8rem;
	}
	.scores.footer {
		flex-direction: column;
		padding-top: 0.7rem;
		border-top: 1px solid var(--border);
	}
	.scores.chips {
		flex-wrap: wrap;
		align-items: center;
	}
	.heading {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-subtle);
	}
	.entries {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem 1.4rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.entry {
		display: flex;
		flex-direction: column;
		font-size: 0.7rem;
		color: var(--text-muted);
	}
	.value {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		font-family: var(--font-display);
		font-size: 0.95rem;
		color: var(--text);
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--score-good);
	}
	.entry.ok .dot,
	.entry.bad .dot {
		background: transparent;
		border: 2px solid var(--score-ok);
	}
	.entry.bad .dot {
		border-color: var(--score-bad);
	}
	.chips .entries {
		gap: 0.4rem;
	}
	.chips .entry {
		flex-direction: row;
		align-items: center;
		gap: 0.4rem;
		padding: 0.25rem 0.65rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
	}
	.chips .value {
		font-size: 0.78rem;
	}
	.note {
		margin: 0;
		font-size: 0.78rem;
		color: var(--text-subtle);
	}
</style>
