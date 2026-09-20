<script lang="ts">
	import { detailTab, navigateToSongTab, type DetailTab } from '$lib/stores/navigation';
	import {
		EDITOR_TAB_TAKES_LABEL,
		EDITOR_TAB_WRITE_LABEL,
		EDITOR_TABS_LABEL
	} from '$lib/constants';

	interface Props {
		takeCount: number;
	}

	let { takeCount }: Props = $props();
	const tabs: readonly DetailTab[] = ['write', 'takes'];

	function onKeydown(event: KeyboardEvent): void {
		let tab: DetailTab;
		switch (event.key) {
			case 'ArrowLeft':
			case 'ArrowRight':
				tab = $detailTab === 'write' ? 'takes' : 'write';
				break;
			case 'Home':
				tab = 'write';
				break;
			case 'End':
				tab = 'takes';
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

<div class="detail-tabs" role="tablist" aria-label={EDITOR_TABS_LABEL}>
	{#each tabs as tab (tab)}
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
			{#if tab === 'write'}
				{EDITOR_TAB_WRITE_LABEL}
			{:else}
				{EDITOR_TAB_TAKES_LABEL} <span class="count">({takeCount})</span>
			{/if}
		</button>
	{/each}
</div>

<style>
	.detail-tabs {
		position: sticky;
		top: 0;
		z-index: 1;
		display: flex;
		background: var(--header-bg);
		border-bottom: 1px solid var(--border);
	}

	button {
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
</style>
