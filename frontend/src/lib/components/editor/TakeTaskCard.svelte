<script lang="ts">
	import type { GenerationItem } from '#lib/api/types.ts';
	import type { RepaintMode } from '#lib/stores/recipe.ts';
	import { generateAction, isGenerateBusy, runSourceTask } from '#lib/stores/generateAction.ts';
	import {
		clearSource,
		coverNoiseStrength,
		coverStrength,
		repaintEnd,
		repaintMode,
		repaintStart,
		repaintStrength,
		seedFromTake,
		sourceMode,
		sourceTakeDurationSeconds
	} from '#lib/stores/recipe.ts';
	import { formatTime } from '#lib/utils/format.ts';
	import { pageText, type TextKey } from '#lib/utils/page-words.ts';
	import Icon from '../Icon.svelte';
	import WaveformRangePicker from '../WaveformRangePicker.svelte';

	interface Props {
		gen: GenerationItem;
		landingVersionNumber: number;
	}

	let { gen, landingVersionNumber }: Props = $props();

	const REPAINT_MODES: { value: RepaintMode; key: TextKey }[] = [
		{ value: 'conservative', key: 'takeTask.modeConservative' },
		{ value: 'balanced', key: 'takeTask.modeBalanced' },
		{ value: 'aggressive', key: 'takeTask.modeAggressive' }
	];
	const NOISE_MIN = 0;
	const NOISE_MAX = 1;

	const duration = $derived(sourceTakeDurationSeconds(gen));
	const takeDetail = $derived(
		gen.version_number === null
			? pageText('takeTask.detail', { duration: formatTime(duration) })
			: pageText('takeTask.detailVersioned', {
					version: String(gen.version_number),
					duration: formatTime(duration)
				})
	);
	const repainting = $derived($sourceMode === 'repaint');
	const verbLabel = $derived(pageText(repainting ? 'takeTask.repaint' : 'takeTask.cover'));
	const pressLabel = $derived(
		repainting
			? pageText('takeTask.repaintPress', {
					start: formatTime($repaintStart * duration),
					end: formatTime($repaintEnd * duration)
				})
			: verbLabel
	);
	let taskElement: HTMLElement | undefined;
	// The card opens under a take that may sit anywhere in the list: bring its
	// foot on screen, on open and when the verb swaps, but not while a slider moves.
	$effect(() => {
		void repainting;
		taskElement?.scrollIntoView?.({ block: 'nearest' });
	});
	const unavailable = $derived(
		$generateAction.kind === 'disabled' || isGenerateBusy($generateAction)
	);
</script>

<div class="task" bind:this={taskElement}>
	<div class="task-head">
		<span class="what">{verbLabel}</span>
		<span class="from"
			>{pageText('takeTask.fromTake', { number: String(gen.generation_number) })}
			<small>{takeDetail}</small></span
		>
		<button
			type="button"
			class="close"
			data-hitbox="frequent"
			title={pageText('takeTask.closeTitle')}
			aria-label={pageText('takeTask.close')}
			onclick={clearSource}
		>
			<Icon name="x" size={16} />
		</button>
	</div>
	<div class="task-body">
		{#if repainting}
			<div class="field-label range-caption">
				{pageText('takeTask.range')} <small>{pageText('takeTask.rangeCaption')}</small>
			</div>
			<WaveformRangePicker
				audioUrl={`/audio/${gen.mp3_path}`}
				{duration}
				startPercent={$repaintStart}
				endPercent={$repaintEnd}
				onchange={(start, end) => {
					repaintStart.set(start);
					repaintEnd.set(end);
				}}
			/>
			<div class="field-label">{pageText('takeTask.repaintAmount')}</div>
			<div class="segments">
				{#each REPAINT_MODES as mode (mode.value)}
					<button
						type="button"
						data-hitbox="frequent"
						aria-pressed={$repaintMode === mode.value}
						onclick={() => repaintMode.set(mode.value)}>{pageText(mode.key)}</button
					>
				{/each}
			</div>
			{#if $repaintMode === 'balanced'}
				<label class="slider"
					><span class="field-label">{pageText('takeTask.repaintStrength')}</span><input
						type="range"
						min="0"
						max="1"
						step="0.01"
						bind:value={$repaintStrength}
					/><output
						>{pageText('takeTask.strengthValue', {
							count: Math.round($repaintStrength * 100)
						})}</output
					></label
				>
			{/if}
		{:else}
			<label class="slider"
				><span class="field-label"
					>{pageText('takeTask.coverCloseness', { number: String(gen.generation_number) })}</span
				><span class="end">{pageText('takeTask.coverFree')}</span><input
					type="range"
					aria-label={pageText('takeTask.coverStrength')}
					min="0"
					max="1"
					step="0.01"
					bind:value={$coverStrength}
				/><span class="end">{pageText('takeTask.coverStrict')}</span></label
			>
			<label class="slider"
				><span class="field-label"
					>{pageText('takeTask.noise')} <small>{pageText('takeTask.noiseCaption')}</small></span
				><span class="end">{pageText('takeTask.noiseBound', { count: NOISE_MIN })}</span><input
					type="range"
					min={NOISE_MIN}
					max={NOISE_MAX}
					step="0.01"
					bind:value={$coverNoiseStrength}
				/><span class="end">{pageText('takeTask.noiseBound', { count: NOISE_MAX })}</span></label
			>
		{/if}
		<p class="hint">{pageText('takeTask.promptHint')}</p>
		{#if $seedFromTake}<p class="hint seed-line">
				{pageText('takeTask.seedLine', { number: String($seedFromTake.takeNumber) })}
			</p>{/if}
		<div class="task-foot">
			<span class="foot-note"
				><span class="hint"
					>{pageText('takeTask.landing', { number: String(landingVersionNumber) })}</span
				>
				<span class="hint">{pageText('takeTask.headerNote')}</span></span
			>
			<button
				type="button"
				class="press"
				data-hitbox="frequent"
				disabled={unavailable}
				onclick={() => void runSourceTask()}>{pressLabel}</button
			>
		</div>
	</div>
</div>

<style>
	.task {
		margin: -2px 0 6px;
		border: 1px solid var(--accent);
		border-top: none;
		border-radius: 0 0 6px 6px;
		background: var(--surface);
		overflow: hidden;
		min-width: 0;
	}

	.task-head {
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 46px;
		padding: 0 2px 0 12px;
		background: color-mix(in srgb, var(--accent) 8%, var(--surface));
		border-bottom: 1px solid var(--border);
	}

	.what {
		font-family: var(--font-display);
		font-size: 12.5px;
		letter-spacing: 0.7px;
		text-transform: uppercase;
		color: var(--accent);
	}

	.from {
		flex: 1;
		min-width: 0;
		font-size: 0.88rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.from small {
		color: var(--text-muted);
		font-size: 0.78rem;
	}

	.close {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 44px;
		min-height: 44px;
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
	}

	.close:hover {
		color: var(--text);
	}

	.task-body {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
	}

	.field-label {
		font-size: 0.78rem;
		color: var(--text-muted);
	}

	.segments {
		display: flex;
		gap: 4px;
	}

	.segments button {
		flex: 1;
		min-height: 44px;
		background: var(--surface-hover);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text);
		cursor: pointer;
	}

	.segments button[aria-pressed='true'] {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 15%, var(--surface));
	}

	.slider {
		display: grid;
		grid-template-columns: 3rem 1fr 3rem;
		align-items: center;
		gap: 8px;
	}

	.slider .field-label {
		grid-column: 1 / -1;
	}

	.slider input {
		grid-column: 2;
		min-width: 0;
		accent-color: var(--accent);
	}

	.slider output,
	.slider .end:last-child {
		grid-column: 3;
	}

	.slider output,
	.slider .end {
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.hint {
		font-size: 0.8rem;
		color: var(--text-muted);
		margin: 0;
	}

	.task-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding-top: 6px;
	}

	.press {
		min-height: 44px;
		padding: var(--btn-padding-pill);
		border: none;
		border-radius: var(--btn-radius-pill);
		background: var(--accent);
		color: var(--on-accent);
		font-size: var(--btn-font-size);
		cursor: pointer;
	}

	.press:disabled {
		background: var(--surface-hover);
		color: var(--text-disabled);
		cursor: not-allowed;
	}
</style>
