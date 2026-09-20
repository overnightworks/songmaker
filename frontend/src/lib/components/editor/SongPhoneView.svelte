<script lang="ts">
	import type { ComponentProps, Snippet } from 'svelte';
	import { detailTab } from '$lib/stores/navigation';
	import DetailTabs from './DetailTabs.svelte';
	import TakesList from './TakesList.svelte';

	interface Props {
		header: Snippet;
		sharedLink: Snippet;
		recipe: Snippet;
		write: Snippet;
		expiryDigest: Snippet;
		takeListProps: ComponentProps<typeof TakesList>;
	}

	let { header, sharedLink, recipe, write, expiryDigest, takeListProps }: Props = $props();
</script>

{@render header()}
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
		{@render recipe()}
		{@render write()}
	{:else}
		{@render expiryDigest()}
		<TakesList {...takeListProps} />
	{/if}
</div>

<style>
	.phone-content {
		display: flex;
		flex-direction: column;
		gap: var(--row-gap);
		min-width: 0;
	}
</style>
