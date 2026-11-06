<script lang="ts">
	import { AccountMenu as AccountPanel, type ThemeChoice } from 'overnightworks-appkit';
	import {
		ACCOUNT_MENU_CLOSE_LABEL,
		ACCOUNT_MENU_LABEL,
		RAIL_SETTINGS_LABEL,
		SIGN_OUT_FAILED_MESSAGE
	} from '#lib/constants.ts';
	import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
	import { page } from '$app/state';
	import { signOutFailed } from '#lib/stores/auth.ts';
	import { leaveForLogout, openAppPage } from '#lib/stores/navigation.ts';
	import { chooseTheme, themeChoice } from '#lib/stores/ui.ts';
	import { accountInitial } from '#lib/utils/format.ts';
	import MenuPopover from './MenuPopover.svelte';

	let {
		username,
		accountHref,
		onlogout
	}: { username: string; accountHref: string; onlogout: () => void } = $props();

	const initial = $derived(accountInitial(username));

	let popover: MenuPopover | undefined = $state();

	const SETTINGS_HREF = '/settings';
	const KIT_CHOICE_BY_STORED = {
		system: 'follow-system',
		light: 'light',
		dark: 'dark'
	} as const;
	const STORED_CHOICE_BY_KIT = {
		'follow-system': 'system',
		light: 'light',
		dark: 'dark'
	} as const;

	// A failed log-out is told while the menu that tried it stays open; a
	// later opening shows the menu as it stands, not an old failure.
	function forgetFailureOnClose(): () => void {
		return () => signOutFailed.set(false);
	}

	function openSettings(): void {
		popover?.close();
		if (page.url.pathname === SETTINGS_HREF) return;
		void openAppPage(SETTINGS_HREF);
	}

	function chooseKitTheme(choice: ThemeChoice): void {
		void chooseTheme(STORED_CHOICE_BY_KIT[choice]);
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
		<div {@attach forgetFailureOnClose}>
			<AccountPanel
				name={username}
				{accountHref}
				onAccountOpen={() => popover?.close(false)}
				appRows={[{ label: RAIL_SETTINGS_LABEL, onSelect: openSettings }]}
				theme={{ choice: KIT_CHOICE_BY_STORED[$themeChoice], onChange: chooseKitTheme }}
				legalLinks={LEGAL_SECTIONS}
				onLogOut={() => void leaveForLogout(onlogout)}
				logOutFailure={$signOutFailed ? SIGN_OUT_FAILED_MESSAGE : undefined}
			/>
		</div>
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

	/* The kit's panel draws its own surface and border. */
	.account-menu :global(.menu-panel) {
		width: auto;
		padding: 0;
		gap: 0;
		background: none;
		border: none;
	}
</style>
