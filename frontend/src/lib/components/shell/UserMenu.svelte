<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { tick } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { focusFirstIn, handleFocusTrapKeydown } from '$lib/utils/focus-trap';
	import ThemeToggle from '../ThemeToggle.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	const MENU_LABEL = 'Account menu';

	let menuOpen = $state(false);
	let triggerButton: HTMLButtonElement | undefined = $state();
	let menu: HTMLDivElement | undefined = $state();

	afterNavigate(() => {
		closeMenu(false);
	});

	async function openMenu(): Promise<void> {
		menuOpen = true;
		await tick();
		if (menu) focusFirstIn(menu);
	}

	function closeMenu(restoreFocus = true): void {
		if (!menuOpen) return;
		menuOpen = false;
		if (restoreFocus) queueMicrotask(() => triggerButton?.focus());
	}

	function toggleMenu(): void {
		if (menuOpen) closeMenu();
		else void openMenu();
	}

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!menuOpen || !menu) return;
		handleFocusTrapKeydown(menu, event, () => closeMenu());
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="user-row">
	<button
		bind:this={triggerButton}
		class="user-trigger"
		data-hitbox="frequent"
		aria-haspopup="dialog"
		aria-expanded={menuOpen}
		aria-label={MENU_LABEL}
		onclick={toggleMenu}
	>
		<span class="username">{username}</span>
	</button>
	{#if menuOpen}
		<div class="menu-modal">
			<button
				class="menu-backdrop"
				tabindex="-1"
				onclick={() => closeMenu()}
				aria-label="Close menu"
			></button>
			<div
				bind:this={menu}
				class="account-menu"
				role="dialog"
				aria-modal="true"
				aria-label={MENU_LABEL}
				tabindex="-1"
			>
				<ThemeToggle />
				<a href="/loras">Voices</a>
				<button class="logout" onclick={onlogout}>Logout</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.user-row {
		position: relative;
	}

	.user-trigger {
		display: flex;
		align-items: center;
		width: 100%;
		padding: 8px 16px;
		background: none;
		border: none;
		color: var(--text);
		text-align: left;
		cursor: pointer;
	}

	.user-trigger:hover {
		background: var(--surface-hover);
	}

	.username {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.85rem;
	}

	.menu-modal {
		position: fixed;
		inset: 0;
		z-index: 300;
	}

	.menu-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		border: 0;
		background: color-mix(in srgb, #000 42%, transparent);
		cursor: default;
	}

	.account-menu {
		position: fixed;
		left: 16px;
		bottom: 60px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 200px;
		max-width: calc(100vw - 32px);
		padding: 0.5rem;
		background: var(--header-bg);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		z-index: 1;
	}

	.account-menu a,
	.account-menu .logout {
		display: flex;
		align-items: center;
		min-height: var(--hitbox-frequent);
		padding: 0.6rem 0.75rem;
		border-radius: 4px;
		font-size: 0.9rem;
		color: var(--text-muted);
		text-decoration: none;
		background: none;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.account-menu a:hover,
	.account-menu .logout:hover {
		background: var(--surface-hover);
		color: var(--text);
	}
</style>
