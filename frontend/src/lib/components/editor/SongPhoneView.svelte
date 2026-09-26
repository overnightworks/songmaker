<script lang="ts">
	import type { ComponentProps, Snippet } from 'svelte';
	import { coWriterOpen, type RecipeChip } from '$lib/stores/recipe';
	import { detailTab } from '$lib/stores/navigation';
	import DetailTabs from './DetailTabs.svelte';
	import GenerateButton from './GenerateButton.svelte';
	import PhoneRecipeSection from './PhoneRecipeSection.svelte';
	import TakesList from './TakesList.svelte';

	interface Props {
		sharedLink: Snippet;
		write: Snippet;
		cowriter: Snippet;
		expiryDigest: Snippet;
		takeListProps: ComponentProps<typeof TakesList>;
		chips: RecipeChip[];
	}

	let { sharedLink, write, cowriter, expiryDigest, takeListProps, chips }: Props = $props();
</script>

{#if $coWriterOpen}
	{@render cowriter()}
{:else}
	<DetailTabs takeCount={takeListProps.song.generation_count} />
	<div
		id="song-phone-panel"
		class="phone-content"
		role="tabpanel"
		aria-labelledby={`song-tab-${$detailTab}`}
		tabindex="0"
	>
		{#if $detailTab === 'write'}
			{@render sharedLink()}
			<PhoneRecipeSection {chips} />
			{@render write()}
			<GenerateButton />
		{:else}
			{@render expiryDigest()}
			<TakesList {...takeListProps} />
		{/if}
	</div>
{/if}

<style>
	.phone-content {
		display: flex;
		flex-direction: column;
		gap: var(--row-gap);
		min-width: 0;
	}
</style>
