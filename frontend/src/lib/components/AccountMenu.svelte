<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- the account console is another origin */
	import {
		ACCOUNT_MENU_CLOSE_LABEL,
		ACCOUNT_MENU_LABEL,
		ACCOUNT_MENU_LOGOUT_LABEL,
		RAIL_SETTINGS_LABEL,
		SIGN_OUT_FAILED_MESSAGE,
		THEME_SWITCH_TO_DARK_LABEL,
		THEME_SWITCH_TO_LIGHT_LABEL
	} from '#lib/constants.ts';
	import { page } from '$app/state';
	import { currentUser, signOutFailed } from '#lib/stores/auth.ts';
	import { leaveForLogout, openAppPage } from '#lib/stores/navigation.ts';
	import { theme, toggleTheme } from '#lib/stores/ui.ts';
	import { accountInitial } from '#lib/utils/format.ts';
	import Icon from './Icon.svelte';
	import LegalLinks from './LegalLinks.svelte';
	import MenuPopover from './MenuPopover.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	const initial = $derived(accountInitial(username));
	const offersLight = $derived($theme === 'dark');

	let popover: MenuPopover | undefined = $state();

	const SETTINGS_HREF = '/settings';
	const accountConsoleUrl = $derived($currentUser?.account_console_url ?? null);

	// A failed sign-out is told while the menu that tried it stays open; a
	// later opening shows the menu as it stands, not an old failure.
	function forgetFailureOnClose(): () => void {
		return () => signOutFailed.set(false);
	}

	function openSettings(): void {
		popover?.close();
		if (page.url.pathname === SETTINGS_HREF) return;
		void openAppPage(SETTINGS_HREF);
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
		{#if accountConsoleUrl}
			<a
				class="account-name"
				href={accountConsoleUrl}
				target="_blank"
				rel="noopener noreferrer"
				onclick={() => popover?.close(false)}
			>
				<span class="account-name-text">{username}</span>
				<Icon name="external-link" size={16} class="account-name-mark" />
			</a>
		{:else}
			<p class="account-name"><span class="account-name-text">{username}</span></p>
		{/if}
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
		<button class="menu-item logout" onclick={() => void leaveForLogout(onlogout)}>
			<Icon name="log-out" class="menu-item-icon" />{ACCOUNT_MENU_LOGOUT_LABEL}
		</button>
		{#if $signOutFailed}
			<p class="sign-out-failed" role="alert" {@attach forgetFailureOnClose}>
				{SIGN_OUT_FAILED_MESSAGE}
			</p>
		{/if}
		<div class="account-legal"><LegalLinks newTab /></div>
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

	.account-name {
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 52px;
		margin: 0 0 0.25rem;
		padding: 0 0.6rem;
		border-bottom: 1px solid var(--border);
		color: var(--text);
		font-weight: 600;
		font-size: 0.9rem;
		text-decoration: none;
	}

	a.account-name:hover {
		background: var(--surface-hover);
	}

	.account-name-text {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.account-name :global(.account-name-mark) {
		flex: none;
		color: var(--text-muted);
	}

	.account-legal {
		margin-top: 0.25rem;
		padding: 0.5rem 0.4rem 0.3rem;
		border-top: 1px solid var(--border);
		font-size: 0.72rem;
		color: var(--text-subtle);
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

	.sign-out-failed {
		margin: 0;
		padding: 0.3rem 0.6rem 0.4rem;
		font-size: 0.8rem;
		color: var(--score-bad);
	}
</style>
