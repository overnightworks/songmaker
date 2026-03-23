<script lang="ts">
	import type { TrackScores } from '$lib/api/types';

	interface Props {
		scores: TrackScores | null;
	}

	let { scores }: Props = $props();
	let collapsed = $state(true);

	const SCORE_LABELS: Record<string, string> = {
		lyrical_coherence: 'Lyrical Coherence',
		lyrical_summary: 'Lyrical Summary',
		dynamics: 'Dynamics',
		text_accuracy: 'Text Accuracy',
		audiobox_enjoyment: 'Enjoyment',
		audiobox_understanding: 'Understanding',
		audiobox_complexity: 'Complexity',
		audiobox_quality: 'Production Quality',
		silence_gaps: 'Silence Gaps',
		spectral_artifacts: 'Artifacts'
	};

	const entries = $derived.by(() => {
		if (!scores) return [];
		return Object.entries(SCORE_LABELS)
			.filter(([key]) => scores[key as keyof TrackScores] !== undefined)
			.map(([key, label]) => {
				const raw = scores[key as keyof TrackScores];
				let display = String(raw);
				if (key === 'lyrical_coherence') display = `${raw}/10`;
				else if (typeof raw === 'number' && key !== 'silence_gaps' && key !== 'spectral_artifacts')
					display = raw.toFixed(1);
				return { key, label, display, raw };
			});
	});
</script>

{#if scores}
	<section class="panel" class:collapsed>
		<button class="panel-header" onclick={() => (collapsed = !collapsed)}>
			<h3>{collapsed ? '▸' : '▾'} Scores</h3>
		</button>
		{#if !collapsed}
			<div class="grid">
				{#each entries as { key, label, display, raw } (key)}
					<div class="item">
						{label}:
						{#if key === 'lyrical_summary' && typeof raw === 'string' && raw.length > 40}
							<span class="value summary" title={raw}>{raw.substring(0, 40)}...</span>
						{:else}
							<span class="value">{display}</span>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</section>
{/if}

<style>
	.panel {
		background: var(--surface);
		border: 1px solid #222;
		border-radius: 6px;
		padding: 10px 16px;
		margin: 4px 0 8px;
		flex-shrink: 0;
	}

	.panel-header {
		background: none;
		border: none;
		width: 100%;
		text-align: left;
		padding: 0;
	}

	.panel-header h3 {
		font-family: var(--font-display);
		font-size: 13px;
		color: var(--primary);
		text-transform: uppercase;
		letter-spacing: 1px;
		user-select: none;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 4px 16px;
		margin-top: 6px;
	}

	.item {
		font-size: 11px;
		color: var(--text-muted);
	}

	.value {
		color: #ccc;
	}

	.summary {
		cursor: help;
	}
</style>
