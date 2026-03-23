<script lang="ts">
	import type { GenerationInfo } from '$lib/api/types';

	interface Props {
		generation: GenerationInfo | null;
	}

	let { generation }: Props = $props();
	let collapsed = $state(true);

	const GEN_LABELS: Record<string, string> = {
		seed: 'Seed',
		acestep_model: 'Model',
		acestep_lm_model: 'LM Model',
		bpm: 'BPM',
		duration: 'Duration',
		key: 'Key',
		guidance_scale: 'Guidance',
		inference_steps: 'Steps',
		shift: 'Shift',
		think_mode: 'Think',
		lm_temperature: 'LM Temp',
		infer_method: 'Method',
		songmaker_version: 'Songmaker',
		generated_at: 'Generated'
	};

	const entries = $derived.by(() => {
		if (!generation) return [];
		return Object.entries(GEN_LABELS)
			.filter(([key]) => {
				const val = generation[key as keyof GenerationInfo];
				return val !== undefined && val !== null && val !== '';
			})
			.map(([key, label]) => {
				const val = generation[key as keyof GenerationInfo];
				let display = String(val);
				if (key === 'duration') display = `${val}s`;
				if (key === 'think_mode') display = val ? 'on' : 'off';
				return { label, display };
			});
	});
</script>

{#if generation}
	<section class="panel" class:collapsed>
		<button class="panel-header" onclick={() => (collapsed = !collapsed)}>
			<h3>{collapsed ? '▸' : '▾'} Generation Info</h3>
		</button>
		{#if !collapsed}
			<div class="grid">
				{#each entries as { label, display } (label)}
					<div class="item">{label}: <span class="value">{display}</span></div>
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
</style>
