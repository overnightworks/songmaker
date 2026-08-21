<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { afterNavigate } from '$app/navigation';
	import { tick } from 'svelte';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import Icon from './Icon.svelte';
	import ThemeToggle from './ThemeToggle.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();

	const MENU_FOCUSABLE = 'a[href], button:not(:disabled)';
	const ACCOUNT_MENU_LABEL = 'Account menu';
	const ACCOUNT_NAV_LABEL = 'Account';

	let compact = $state(false);
	let menuOpen = $state(false);
	let triggerButton: HTMLButtonElement | undefined = $state();
	let menu: HTMLDivElement | undefined = $state();

	$effect(() => {
		return subscribeCompactLayout((value) => {
			compact = value;
			if (!value) closeMenu(false);
		});
	});

	afterNavigate(() => {
		closeMenu(false);
	});

	async function openMenu(): Promise<void> {
		menuOpen = true;
		await tick();
		const first = menu?.querySelector<HTMLElement>(MENU_FOCUSABLE);
		(first ?? menu)?.focus();
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
		if (event.key === 'Escape') {
			event.preventDefault();
			closeMenu();
			return;
		}
		if (event.key !== 'Tab') return;
		const focusable = Array.from(menu.querySelectorAll<HTMLElement>(MENU_FOCUSABLE));
		if (focusable.length === 0) {
			event.preventDefault();
			menu.focus();
			return;
		}
		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		const active = document.activeElement;
		if (event.shiftKey && (active === first || !menu.contains(active))) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && (active === last || !menu.contains(active))) {
			event.preventDefault();
			first.focus();
		}
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

{#snippet actions()}
	<span class="username">{username}</span>
	<ThemeToggle />
	<a href="/loras">Voices</a>
	<a href="/settings">Settings</a>
	<button class="logout" onclick={onlogout}>Logout</button>
{/snippet}

{#if compact}
	<div class="menu-root">
		<button
			bind:this={triggerButton}
			class="menu-trigger"
			data-hitbox="frequent"
			aria-haspopup="dialog"
			aria-expanded={menuOpen}
			aria-label={ACCOUNT_MENU_LABEL}
			onclick={toggleMenu}
		>
			<Icon name="more-horizontal" size={18} />
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
					aria-label={ACCOUNT_MENU_LABEL}
					tabindex="-1"
				>
					{@render actions()}
				</div>
			</div>
		{/if}
	</div>
{:else}
	<nav class="header-nav" aria-label={ACCOUNT_NAV_LABEL}>
		{@render actions()}
	</nav>
{/if}

<style>
	.header-nav {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 0.8rem;
		flex-shrink: 0;
	}

	.username {
		color: var(--text-subtle);
		max-width: 150px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.header-nav a,
	.account-menu a {
		color: var(--text-muted);
		text-decoration: none;
	}

	.header-nav a:hover,
	.account-menu a:hover {
		color: var(--text);
	}

	.logout {
		background: none;
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-muted);
		padding: 3px 8px;
		cursor: pointer;
		font-size: 0.75rem;
		font-family: var(--font-body);
	}

	.logout:hover {
		color: var(--score-bad);
		border-color: var(--score-bad);
	}

	.menu-root {
		flex-shrink: 0;
	}

	.menu-trigger {
		color: var(--text-muted);
		background: none;
		border: none;
	}

	.menu-trigger:hover {
		color: var(--text);
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
		top: var(--header-height);
		right: 8px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 200px;
		max-width: calc(100vw - 16px);
		padding: 0.5rem;
		background: var(--header-bg);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		z-index: 1;
	}

	.account-menu .username {
		max-width: none;
		padding: 0.4rem 0.75rem;
	}

	.account-menu a,
	.account-menu .logout {
		display: flex;
		align-items: center;
		min-height: var(--hitbox-frequent);
		padding: 0.6rem 0.75rem;
		border-radius: 4px;
		font-size: 0.9rem;
	}

	.account-menu .logout {
		justify-content: center;
		margin-top: 0.25rem;
	}

	.account-menu a:hover {
		background: var(--surface-hover);
	}
</style>
