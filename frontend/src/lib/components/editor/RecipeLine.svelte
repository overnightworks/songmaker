<script lang="ts">
	import { tick } from 'svelte';
	import {
		editAudioDuration,
		editBpm,
		editGenParams,
		editKeyScale,
		editReference,
		setDraftAudioDuration,
		setDraftBpm,
		setDraftGenParams,
		setDraftKeyScale,
		setDraftReference
	} from '#lib/stores/editor.ts';
	import {
		activeModels,
		effectiveGenerationDefaults,
		loadBuiltins,
		loadGenerationDefaults,
		loadPresets
	} from '#lib/stores/presets.ts';
	import { recipeModel, recipeOpen, takesPerGenerate } from '#lib/stores/recipe.ts';
	import {
		engineParams,
		recipeDiffersFromStandard,
		type RecipeValues
	} from '#lib/utils/recipe-standard.ts';
	import { RECIPE_PANEL_LABEL } from '#lib/constants.ts';
	import { RECIPE_CHANGED_LABEL } from '#lib/constants/recipe.ts';
	import RecipeTabs from './RecipeTabs.svelte';

	const values = $derived<RecipeValues>({
		bpm: $editBpm,
		audioDuration: $editAudioDuration,
		keyScale: $editKeyScale,
		genParams: $editGenParams,
		reference: $editReference,
		model: $recipeModel,
		takes: $takesPerGenerate
	});
	const standard = $derived({
		model: $activeModels[0]?.id ?? null,
		engineDefaults: $effectiveGenerationDefaults
	});
	const differs = $derived(recipeDiffersFromStandard(values, standard));

	// The draft changes only through its own setters; a field that did not
	// change is not written, so no step marks the draft by accident.
	function apply(next: RecipeValues): void {
		if (next.bpm !== values.bpm) setDraftBpm(next.bpm);
		if (next.audioDuration !== values.audioDuration) setDraftAudioDuration(next.audioDuration);
		if (next.keyScale !== values.keyScale) setDraftKeyScale(next.keyScale);
		if (next.genParams !== values.genParams) setDraftGenParams(next.genParams);
		if (next.reference !== values.reference) setDraftReference(next.reference);
		if (next.model !== values.model) recipeModel.set(next.model);
		if (next.takes !== values.takes) takesPerGenerate.set(next.takes);
	}

	// A closed line costs no request unless the draft holds engine values, whose
	// dot needs the defaults; the card's own lists load when it first opens.
	const holdsEngineValues = $derived(Object.keys(engineParams(values)).length > 0);
	let defaultsRequested = false;
	let listsRequested = false;

	let lineButton: HTMLButtonElement | undefined = $state();

	// Opening and closing replace the focused button, so focus follows the
	// control that took its place.
	async function open(): Promise<void> {
		const host = lineButton?.parentElement;
		recipeOpen.set(true);
		await tick();
		host?.querySelector<HTMLElement>('[data-tab="song"]')?.focus();
	}

	async function close(): Promise<void> {
		recipeOpen.set(false);
		await tick();
		lineButton?.focus();
	}

	$effect(() => {
		if (($recipeOpen || holdsEngineValues) && !defaultsRequested) {
			defaultsRequested = true;
			void loadBuiltins();
			void loadGenerationDefaults();
		}
		if ($recipeOpen && !listsRequested) {
			listsRequested = true;
			void loadPresets();
		}
	});
</script>

{#if $recipeOpen}
	<RecipeTabs {values} {standard} onchange={apply} onclose={close} />
{:else}
	<button
		type="button"
		class="recipe-line"
		bind:this={lineButton}
		aria-expanded="false"
		aria-label={differs ? `${RECIPE_PANEL_LABEL}, ${RECIPE_CHANGED_LABEL}` : RECIPE_PANEL_LABEL}
		onclick={open}
	>
		<span class="label">{RECIPE_PANEL_LABEL}</span>
		{#if differs}<i class="dot" data-recipe-changed aria-hidden="true"></i>{/if}
		<span class="chevron" aria-hidden="true">›</span>
	</button>
{/if}

<style>
	.recipe-line {
		display: flex;
		align-items: center;
		gap: var(--row-gap);
		width: 100%;
		min-height: var(--hitbox-frequent);
		padding: 0 var(--row-padding);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		text-align: left;
		cursor: pointer;
	}

	.recipe-line:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.dot {
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 50%;
		background: var(--primary);
	}
</style>
