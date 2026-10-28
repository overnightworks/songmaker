<script lang="ts">
	import {
		editAudioDuration,
		editBpm,
		editGenParams,
		editKeyScale,
		setDraftAudioDuration,
		setDraftBpm,
		setDraftGenParams,
		setDraftKeyScale
	} from '$lib/stores/editor';
	import {
		activeModels,
		effectiveGenerationDefaults,
		loadBuiltins,
		loadGenerationDefaults,
		loadPresets
	} from '$lib/stores/presets';
	import { recipeModel, recipeOpen, takesPerGenerate } from '$lib/stores/recipe';
	import {
		engineParams,
		recipeDiffersFromStandard,
		type RecipeValues
	} from '$lib/utils/recipe-standard';
	import { RECIPE_PANEL_LABEL } from '$lib/constants';
	import { RECIPE_CHANGED_LABEL } from '$lib/constants/recipe';
	import RecipeTabs from './RecipeTabs.svelte';

	const values = $derived<RecipeValues>({
		bpm: $editBpm,
		audioDuration: $editAudioDuration,
		keyScale: $editKeyScale,
		genParams: $editGenParams,
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
		if (next.model !== values.model) recipeModel.set(next.model);
		if (next.takes !== values.takes) takesPerGenerate.set(next.takes);
	}

	// A closed line costs no request unless the draft holds engine values, whose
	// dot needs the defaults; the card's own lists load when it first opens.
	const holdsEngineValues = $derived(Object.keys(engineParams(values)).length > 0);
	let defaultsRequested = false;
	let listsRequested = false;

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
	<RecipeTabs {values} {standard} onchange={apply} onclose={() => recipeOpen.set(false)} />
{:else}
	<button
		type="button"
		class="recipe-line"
		aria-expanded="false"
		aria-label={differs ? `${RECIPE_PANEL_LABEL}, ${RECIPE_CHANGED_LABEL}` : RECIPE_PANEL_LABEL}
		onclick={() => recipeOpen.set(true)}
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
