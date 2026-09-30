<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		ACCOUNT_MENU_CLOSE_LABEL,
		ACCOUNT_MENU_LABEL,
		ACCOUNT_MENU_LOGOUT_LABEL,
		ACCOUNT_MENU_SIGNED_IN_PREFIX,
		RAIL_SETTINGS_LABEL,
		THEME_SWITCH_TO_DARK_LABEL,
		THEME_SWITCH_TO_LIGHT_LABEL
	} from '$lib/constants';
	import { theme, toggleTheme } from '$lib/stores/ui';
	import { accountInitial } from '$lib/utils/format';
	import Icon from './Icon.svelte';
	import MenuPopover from './MenuPopover.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	const initial = $derived(accountInitial(username));
	const offersLight = $derived($theme === 'dark');

	let popover: MenuPopover | undefined = $state();

	function openSettings(): void {
		popover?.close();
		void goto(resolve('/settings'));
	}
</script>

<div class="account-menu">
	<MenuPopover
		bind:this={popover}
		layer="account-menu"
		label="{ACCOUNT_MENU_LABEL} · {username}"
		closeLabel={ACCOUNT_MENU_CLOSE_LABEL}
	>
		{#snippet trigger()}<span class="account-initial">{initial}</span>{/snippet}
		<p class="account-heading">{ACCOUNT_MENU_SIGNED_IN_PREFIX} <b>{username}</b></p>
		<button class="menu-item" onclick={openSettings}>
			<Icon name="settings" class="menu-item-icon" />{RAIL_SETTINGS_LABEL}
		</button>
		<button class="menu-item" onclick={toggleTheme}>
			{#if offersLight}
				<Icon name="sun" class="menu-item-icon" />{THEME_SWITCH_TO_LIGHT_LABEL}
			{:else}
				<Icon name="moon" class="menu-item-icon" />{THEME_SWITCH_TO_DARK_LABEL}
			{/if}
		</button>
		<button class="menu-item logout" onclick={onlogout}>
			<Icon name="log-out" class="menu-item-icon" />{ACCOUNT_MENU_LOGOUT_LABEL}
		</button>
	</MenuPopover>
</div>

<style>
	.account-menu :global(.menu-trigger) {
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		padding: 0;
		border: none;
	}

	.account-initial {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border-radius: 50%;
		background: var(--surface-hover);
		border: 1px solid var(--border);
		color: var(--text);
		font-family: var(--font-display);
		font-size: 0.85rem;
		letter-spacing: 0.3px;
	}

	.account-menu :global(.menu-trigger[aria-expanded='true'] .account-initial) {
		border-color: var(--accent);
		color: var(--accent);
	}

	.account-menu :global(.menu-panel) {
		width: 238px;
	}

	.account-heading {
		margin: 0 0 0.25rem;
		padding: 0.3rem 0.6rem 0.5rem;
		font-size: 0.8rem;
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.account-heading b {
		color: var(--text);
		font-weight: 600;
	}

	.menu-item {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: var(--hitbox-frequent);
		padding: 0 0.6rem;
		border-radius: 4px;
		font-size: 0.87rem;
		color: var(--text);
		background: none;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.menu-item:hover {
		background: var(--surface-hover);
	}

	.menu-item :global(.menu-item-icon) {
		flex: none;
		color: var(--text-muted);
	}

	.menu-item.logout {
		color: var(--score-bad);
		border-top: 1px solid var(--border);
		border-radius: 0 0 4px 4px;
	}

	.menu-item.logout :global(.menu-item-icon) {
		color: var(--score-bad);
	}
</style>
