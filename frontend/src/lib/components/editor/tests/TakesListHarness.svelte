<script lang="ts">
	import { untrack, type ComponentProps } from 'svelte';
	import { setGenerationActions, type GenerationActions } from '$lib/contexts/generation-actions';
	import TakesList from '../TakesList.svelte';

	let { actions, ...props }: ComponentProps<typeof TakesList> & { actions: GenerationActions } =
		$props();
	setGenerationActions(untrack(() => actions));
</script>

<TakesList {...props} />
