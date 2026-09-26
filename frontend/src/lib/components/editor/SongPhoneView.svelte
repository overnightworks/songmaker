<script lang="ts">
	import type { ComponentProps, Snippet } from 'svelte';
	import { coWriterOpen, type RecipeChip } from '$lib/stores/recipe';
	import { detailTab } from '$lib/stores/navigation';
	import { typingOnPhone } from '$lib/stores/ui';
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

	let actionBarEl: HTMLDivElement | undefined = $state();
	let generateBarHeight = $state<number | undefined>(undefined);

	// The action bar's own content decides its height (#993 fixed padding
	// undershot it once the failure state expanded the worker sentence); the
	// Write column reserves exactly that much, read back live instead of
	// guessed as a constant. A bar that stepped aside for the keyboard takes
	// no room at all.
	$effect(() => {
		const el = actionBarEl;
		if (!el) {
			generateBarHeight = 0;
			return;
		}
		const measure = () => {
			generateBarHeight = el.offsetHeight;
		};
		measure();
		const observer = new ResizeObserver(measure);
		observer.observe(el);
		return () => observer.disconnect();
	});
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
			<div
				class="write-scroll"
				style:--generate-bar-height={generateBarHeight !== undefined
					? `${generateBarHeight}px`
					: undefined}
			>
				{@render write()}
			</div>
			{#if !$typingOnPhone}
				<div class="write-actionbar" bind:this={actionBarEl}>
					<GenerateButton />
				</div>
			{/if}
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

	/* The Write tab's own content keeps growing the page (#993); the action
	   bar below it is what must stay put. A sticky box near the bottom of a
	   scrolling ancestor (`<main>`, per SongDetailView/LibraryWorkspace) stays
	   pinned to `bottom` for the whole scroll, not just once it is reached —
	   but that also means it visually renders above wherever the flow hasn't
	   scrolled to yet, so the lyrics need their own reserved gap the size of
	   the bar or its rendered box would sit over their last lines. */
	.write-scroll {
		padding-bottom: var(--generate-bar-height, var(--editor-generate-bar-height));
	}

	.write-actionbar {
		position: sticky;
		bottom: 0;
		z-index: 1;
		flex: none;
		min-height: var(--editor-generate-bar-height);
		display: flex;
		align-items: center;
		background: var(--header-bg);
		border-top: 1px solid var(--border);
	}
</style>
