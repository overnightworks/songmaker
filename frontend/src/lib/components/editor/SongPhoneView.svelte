<script lang="ts">
	import type { ComponentProps, Snippet } from 'svelte';
	import type { RecipeChip } from '$lib/stores/recipe';
	import { detailTab } from '$lib/stores/navigation';
	import { typingOnPhone } from '$lib/stores/ui';
	import DetailTabs from './DetailTabs.svelte';
	import GenerateButton from './GenerateButton.svelte';
	import PhoneRecipeSection from './PhoneRecipeSection.svelte';
	import TakesList from './TakesList.svelte';

	interface Props {
		sharedLink: Snippet;
		edit: Snippet;
		cowriter: Snippet;
		expiryDigest: Snippet;
		takeListProps: ComponentProps<typeof TakesList>;
		chips: RecipeChip[];
	}

	let { sharedLink, edit, cowriter, expiryDigest, takeListProps, chips }: Props = $props();

	let actionBarEl: HTMLDivElement | undefined = $state();
	let cowriterOpened = $state(false);
	const cowriterShown = $derived($detailTab === 'cowriter');

	// The co-writer mounts the first time its tab opens and then stays
	// mounted, only hidden, so its unsent draft, its scroll position and a
	// running turn survive a look at Edit or Takes (#1016): remounting it would
	// drop the draft and open a second reader on the running turn.
	$effect(() => {
		if (cowriterShown) cowriterOpened = true;
	});
	let generateBarHeight = $state<number | undefined>(undefined);

	// The action bar's own content decides its height (#993 fixed padding
	// undershot it once the failure state expanded the worker sentence); the
	// Edit tab reserves exactly that much, read back live instead of
	// guessed as a constant. A bar that stepped aside for the keyboard measures
	// zero and so takes no room at all; it stays mounted so the Generate
	// button keeps its own state across the typing.
	$effect(() => {
		const el = actionBarEl;
		if (!el) return;
		const measure = () => {
			generateBarHeight = el.offsetHeight;
		};
		measure();
		const observer = new ResizeObserver(measure);
		observer.observe(el);
		return () => observer.disconnect();
	});
</script>

<DetailTabs takeCount={takeListProps.song.generation_count} />
<div
	id="song-phone-panel"
	class="phone-content"
	class:cowriter-shown={cowriterShown}
	role="tabpanel"
	aria-labelledby={`song-tab-${$detailTab}`}
	tabindex="0"
>
	{#if $detailTab === 'edit'}
		{@render sharedLink()}
		<PhoneRecipeSection {chips} />
		<div
			class="edit-scroll"
			style:--generate-bar-height={generateBarHeight !== undefined
				? `${generateBarHeight}px`
				: undefined}
		>
			{@render edit()}
		</div>
		<div class="edit-actionbar" hidden={$typingOnPhone} bind:this={actionBarEl}>
			<GenerateButton reasonInside />
		</div>
	{:else if $detailTab === 'takes'}
		{@render expiryDigest()}
		<TakesList {...takeListProps} />
	{/if}
	{#if cowriterOpened || cowriterShown}
		<div class="cowriter-pane" hidden={!cowriterShown}>
			{@render cowriter()}
		</div>
	{/if}
</div>

<style>
	.phone-content {
		display: flex;
		flex-direction: column;
		gap: var(--row-gap);
		min-width: 0;
	}

	/* The Edit tab's own content keeps growing the page (#993); the action
	   bar below it is what must stay put. A sticky box near the bottom of a
	   scrolling ancestor (`<main>`, per SongDetailView/LibraryWorkspace) stays
	   pinned to `bottom` for the whole scroll, not just once it is reached —
	   but that also means it visually renders above wherever the flow hasn't
	   scrolled to yet, so the lyrics need their own reserved gap the size of
	   the bar or its rendered box would sit over their last lines. */
	.edit-scroll {
		padding-bottom: var(--generate-bar-height, var(--editor-generate-bar-height));
	}

	.edit-actionbar {
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

	.edit-actionbar[hidden] {
		display: none;
	}

	/* The conversation fills the page under the tabs, its composer at the
	   bottom, like the pushed screen it replaces filled the whole page. */
	.phone-content.cowriter-shown {
		flex: 1;
		min-height: 0;
	}

	.cowriter-pane {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}

	.cowriter-pane[hidden] {
		display: none;
	}
</style>
