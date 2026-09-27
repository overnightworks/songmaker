<script lang="ts">
	import { detailTab, navigateToSongTab, type DetailTab } from '$lib/stores/navigation';
	import { DETAIL_TABS } from '$lib/stores/libraryContext';
	import {
		EDITOR_TAB_EDIT_LABEL,
		EDITOR_TAB_TAKES_LABEL,
		EDITOR_TABS_LABEL,
		EDITOR_VIEW_COWRITER_LABEL
	} from '$lib/constants';
	import { generateAction, isGenerateBusy } from '$lib/stores/generateAction';
	import { typingOnPhone } from '$lib/stores/ui';

	interface Props {
		takeCount: number;
	}

	let { takeCount }: Props = $props();
	const jobRunning = $derived(isGenerateBusy($generateAction));

	function tabAfter(current: DetailTab, step: number): DetailTab {
		const count = DETAIL_TABS.length;
		return DETAIL_TABS[(DETAIL_TABS.indexOf(current) + step + count) % count];
	}

	function onKeydown(event: KeyboardEvent): void {
		let tab: DetailTab;
		switch (event.key) {
			case 'ArrowLeft':
				tab = tabAfter($detailTab, -1);
				break;
			case 'ArrowRight':
				tab = tabAfter($detailTab, 1);
				break;
			case 'Home':
				tab = DETAIL_TABS[0];
				break;
			case 'End':
				tab = DETAIL_TABS[DETAIL_TABS.length - 1];
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

<div
	class="detail-tabs"
	class:pinned={!$typingOnPhone}
	role="tablist"
	aria-label={EDITOR_TABS_LABEL}
>
	{#each DETAIL_TABS as tab (tab)}
		<button
			type="button"
			role="tab"
			id={`song-tab-${tab}`}
			aria-controls="song-phone-panel"
			data-tab={tab}
			data-hitbox="text"
			class:active={$detailTab === tab}
			aria-selected={$detailTab === tab}
			tabindex={$detailTab === tab ? 0 : -1}
			onclick={() => navigateToSongTab(tab)}
			onkeydown={onKeydown}
		>
			{#if tab === 'edit'}
				{EDITOR_TAB_EDIT_LABEL}
			{:else if tab === 'cowriter'}
				{EDITOR_VIEW_COWRITER_LABEL}
			{:else}
				{EDITOR_TAB_TAKES_LABEL} <span class="count">({takeCount})</span>
				{#if jobRunning}<span class="ring" aria-hidden="true"></span>{/if}
			{/if}
		</button>
	{/each}
</div>

<style>
	.detail-tabs {
		display: flex;
		background: var(--header-bg);
		border-bottom: 1px solid var(--border);
	}

	/* While typing the text owns the screen, so the tabs scroll away with it. */
	.detail-tabs.pinned {
		position: sticky;
		top: 0;
		z-index: 1;
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

	.ring {
		width: 9px;
		height: 9px;
		flex: none;
		border: 2px solid var(--score-ok);
		border-radius: 50%;
	}

	button.active,
	button.active .count {
		color: var(--primary);
		border-color: var(--primary);
	}
</style>
