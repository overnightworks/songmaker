<script lang="ts">
	import type { GenerationItem } from '$lib/api/types';
	import { TAKE_COVER_LABEL, TAKE_REPAINT_LABEL } from '$lib/constants';
	import {
		TAKE_TASK_CLOSE_LABEL,
		TAKE_TASK_CLOSE_TITLE,
		TAKE_TASK_COVER_FREE_LABEL,
		TAKE_TASK_COVER_STRENGTH_LABEL,
		TAKE_TASK_COVER_STRICT_LABEL,
		TAKE_TASK_HEADER_GENERATE_NOTE,
		TAKE_TASK_NOISE_CAPTION,
		TAKE_TASK_NOISE_LABEL,
		TAKE_TASK_PROMPT_HINT,
		TAKE_TASK_RANGE_LABEL,
		TAKE_TASK_REPAINT_AMOUNT_LABEL,
		TAKE_TASK_REPAINT_MODES,
		TAKE_TASK_REPAINT_STRENGTH_LABEL,
		takeTaskCoverClosenessLabel,
		takeTaskLandingLabel,
		takeTaskRepaintButtonLabel
	} from '$lib/constants/take-task';
	import { generateAction, isGenerateBusy, runSourceTask } from '$lib/stores/generateAction';
	import {
		clearSource,
		coverNoiseStrength,
		coverStrength,
		repaintEnd,
		repaintMode,
		repaintStart,
		repaintStrength,
		sourceMode,
		sourceTakeDurationSeconds
	} from '$lib/stores/recipe';
	import { formatTime } from '$lib/utils/format';
	import Icon from '../Icon.svelte';
	import WaveformRangePicker from '../WaveformRangePicker.svelte';

	interface Props {
		gen: GenerationItem;
		landingVersionNumber: number;
	}

	let { gen, landingVersionNumber }: Props = $props();

	const duration = $derived(sourceTakeDurationSeconds(gen));
	const takeDetail = $derived(
		[gen.version_number === null ? null : `v${gen.version_number}`, formatTime(duration)]
			.filter((part) => part !== null)
			.join(' · ')
	);
	const repainting = $derived($sourceMode === 'repaint');
	const verbLabel = $derived(repainting ? TAKE_REPAINT_LABEL : TAKE_COVER_LABEL);
	const pressLabel = $derived(
		repainting
			? takeTaskRepaintButtonLabel(verbLabel, $repaintStart * duration, $repaintEnd * duration)
			: verbLabel
	);
	let taskElement: HTMLElement | undefined;
	// The card opens under a take that may sit anywhere in the list: bring its
	// foot on screen, on open and when the verb swaps, but not while a slider moves.
	$effect(() => {
		void repainting;
		taskElement?.scrollIntoView({ block: 'nearest' });
	});
	const unavailable = $derived(
		$generateAction.kind === 'disabled' || isGenerateBusy($generateAction)
	);
</script>

<div class="task" bind:this={taskElement}>
	<div class="task-head">
		<span class="what">{verbLabel}</span>
		<span class="from">take {gen.generation_number} <small>· {takeDetail}</small></span>
		<button
			type="button"
			class="close"
			data-hitbox="frequent"
			title={TAKE_TASK_CLOSE_TITLE}
			aria-label={TAKE_TASK_CLOSE_LABEL}
			onclick={clearSource}
		>
			<Icon name="x" size={16} />
		</button>
	</div>
	<div class="task-body">
		{#if repainting}
			<div class="field-label range-caption">{TAKE_TASK_RANGE_LABEL}</div>
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
			<div class="field-label">{TAKE_TASK_REPAINT_AMOUNT_LABEL}</div>
			<div class="segments">
				{#each TAKE_TASK_REPAINT_MODES as mode (mode.value)}
					<button
						type="button"
						data-hitbox="frequent"
						aria-pressed={$repaintMode === mode.value}
						onclick={() => repaintMode.set(mode.value)}>{mode.label}</button
					>
				{/each}
			</div>
			{#if $repaintMode === 'balanced'}
				<label class="slider"
					><span class="field-label">{TAKE_TASK_REPAINT_STRENGTH_LABEL}</span><input
						type="range"
						min="0"
						max="1"
						step="0.01"
						bind:value={$repaintStrength}
					/><output>{Math.round($repaintStrength * 100)}%</output></label
				>
			{/if}
		{:else}
			<label class="slider"
				><span class="field-label">{takeTaskCoverClosenessLabel(gen.generation_number)}</span><span
					class="end">{TAKE_TASK_COVER_FREE_LABEL}</span
				><input
					type="range"
					aria-label={TAKE_TASK_COVER_STRENGTH_LABEL}
					min="0"
					max="1"
					step="0.01"
					bind:value={$coverStrength}
				/><span class="end">{TAKE_TASK_COVER_STRICT_LABEL}</span></label
			>
			<label class="slider"
				><span class="field-label"
					>{TAKE_TASK_NOISE_LABEL} <small>{TAKE_TASK_NOISE_CAPTION}</small></span
				><input type="range" min="0" max="1" step="0.01" bind:value={$coverNoiseStrength} /><output
					>{$coverNoiseStrength}</output
				></label
			>
		{/if}
		<p class="hint">{TAKE_TASK_PROMPT_HINT}</p>
		<div class="task-foot">
			<span class="foot-note"
				><span class="hint">{takeTaskLandingLabel(landingVersionNumber)}</span>
				<span class="hint">{TAKE_TASK_HEADER_GENERATE_NOTE}</span></span
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
