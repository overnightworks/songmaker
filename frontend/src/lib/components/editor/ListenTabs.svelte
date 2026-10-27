<script lang="ts">
	import type { ComponentProps, Snippet } from 'svelte';
	import { detailTab, navigateToSongTab } from '$lib/stores/navigation';
	import {
		EDITOR_TAB_TAKES_LABEL,
		EDITOR_TABS_LABEL,
		EDITOR_VIEW_COWRITER_LABEL
	} from '$lib/constants';
	import TakesList from './TakesList.svelte';

	interface Props {
		expiryDigest: Snippet;
		cowriter: Snippet;
		takeListProps: ComponentProps<typeof TakesList>;
	}

	let { expiryDigest, cowriter, takeListProps }: Props = $props();

	const LISTEN_TABS = ['takes', 'cowriter'] as const;
	type ListenTab = (typeof LISTEN_TABS)[number];

	const selected = $derived<ListenTab>($detailTab === 'cowriter' ? 'cowriter' : 'takes');
	let cowriterOpened = $state(false);

	// The co-writer mounts the first time its tab opens and then stays
	// mounted, only hidden, so its unsent draft, its scroll position and a
	// running turn survive a look at Takes (#1016).
	$effect(() => {
		if (selected === 'cowriter') cowriterOpened = true;
	});

	function onKeydown(event: KeyboardEvent): void {
		let tab: ListenTab;
		switch (event.key) {
			case 'ArrowLeft':
			case 'ArrowRight':
				tab = selected === 'takes' ? 'cowriter' : 'takes';
				break;
			case 'Home':
				tab = LISTEN_TABS[0];
				break;
			case 'End':
				tab = LISTEN_TABS[LISTEN_TABS.length - 1];
				break;
			default:
				return;
		}
		event.preventDefault();
		navigateToSongTab(tab);
		const button = event.currentTarget as HTMLButtonElement;
		button.parentElement?.querySelector<HTMLButtonElement>(`[data-tab="${tab}"]`)?.focus();
	}
</script>

<div class="listen-tabs">
	<div class="tablist" role="tablist" aria-label={EDITOR_TABS_LABEL}>
		{#each LISTEN_TABS as tab (tab)}
			<button
				type="button"
				role="tab"
				id={`listen-tab-${tab}`}
				aria-controls={`listen-panel-${tab}`}
				data-tab={tab}
				data-hitbox="text"
				class:active={selected === tab}
				aria-selected={selected === tab}
				tabindex={selected === tab ? 0 : -1}
				onclick={() => navigateToSongTab(tab)}
				onkeydown={onKeydown}
			>
				{#if tab === 'takes'}
					{EDITOR_TAB_TAKES_LABEL} <span class="count">{takeListProps.song.generation_count}</span>
				{:else}
					{EDITOR_VIEW_COWRITER_LABEL}
				{/if}
			</button>
		{/each}
	</div>
	{#if selected === 'takes'}
		<div
			class="takes-pane"
			id="listen-panel-takes"
			role="tabpanel"
			aria-labelledby="listen-tab-takes"
		>
			{@render expiryDigest()}
			<TakesList {...takeListProps} />
		</div>
	{/if}
	{#if cowriterOpened || selected === 'cowriter'}
		<div
			class="cowriter-pane"
			id="listen-panel-cowriter"
			role="tabpanel"
			aria-labelledby="listen-tab-cowriter"
			hidden={selected !== 'cowriter'}
		>
			{@render cowriter()}
		</div>
	{/if}
</div>

<style>
	.listen-tabs,
	.takes-pane {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}

	.tablist {
		display: flex;
		border-bottom: 1px solid var(--border);
	}

	button {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		min-height: var(--hitbox-frequent);
		padding: var(--btn-padding-pill);
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--btn-font-size-sm);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
	}

	.count {
		color: var(--text-disabled);
	}

	button.active,
	button.active .count {
		color: var(--primary);
		border-color: var(--primary);
	}

	/* The message list scrolls inside the pane and the composer stays on
	   screen. The bound is relative to the viewport because the pane sits in a
	   page that scrolls as one: 441px is the chrome above it (header, panel
	   padding, recipe chips) plus the player bar. */
	.cowriter-pane {
		display: flex;
		flex-direction: column;
		min-height: 16rem;
		height: min(60dvh, calc(100dvh - 441px));
	}

	.cowriter-pane[hidden] {
		display: none;
	}

	.cowriter-pane :global(.cowriter) {
		flex: 1;
		min-height: 0;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
	}
</style>
