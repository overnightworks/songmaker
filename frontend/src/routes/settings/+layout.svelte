<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { page } from '$app/state';
	import { isAdmin } from '$lib/stores/auth';

	let { children } = $props();

	const admin = $derived($isAdmin);

	interface NavItem {
		href: string;
		label: string;
		adminOnly: boolean;
	}

	const NAV_ITEMS: NavItem[] = [
		{ href: '/settings/generation', label: 'Generation', adminOnly: true },
		{ href: '/settings/integrations', label: 'Integrations', adminOnly: false },
		{ href: '/settings/account', label: 'Account', adminOnly: false },
		{ href: '/settings/users', label: 'Admin', adminOnly: true }
	];

	const visibleItems = $derived(NAV_ITEMS.filter((item) => !item.adminOnly || admin));
	const currentPath = $derived(page.url.pathname);
</script>

<div class="settings-layout">
	<nav class="settings-sidebar">
		<a href="/" class="back-link">Back to Songmaker</a>
		<div class="nav-items">
			{#each visibleItems as item (item.href)}
				<a href={item.href} class="nav-link" class:active={currentPath === item.href}>
					{item.label}
				</a>
			{/each}
		</div>
	</nav>
	<main class="settings-content">
		{@render children()}
	</main>
</div>

<style>
	.settings-layout {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	.settings-sidebar {
		width: 200px;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 1.5rem 1rem;
		border-right: 1px solid var(--border);
		overflow-y: auto;
	}

	.back-link {
		color: var(--text-dim);
		text-decoration: none;
		font-size: 0.8rem;
		margin-bottom: 1rem;
	}

	.back-link:hover {
		color: var(--text);
	}

	.nav-items {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.nav-link {
		display: block;
		padding: 0.5rem 0.75rem;
		border-radius: 4px;
		color: var(--text-muted);
		text-decoration: none;
		font-size: 0.85rem;
	}

	.nav-link:hover {
		color: var(--text);
		background: var(--surface-hover);
	}

	.nav-link.active {
		color: var(--primary);
		background: var(--surface);
	}

	.settings-content {
		flex: 1;
		overflow-y: auto;
	}

	@media (max-width: 768px) {
		.settings-sidebar {
			width: auto;
			flex-shrink: 0;
			border-right: none;
			border-bottom: 1px solid var(--border);
			padding: 0.75rem 1rem;
		}

		.nav-items {
			flex-direction: row;
			gap: 4px;
			flex-wrap: wrap;
		}

		.settings-layout {
			flex-direction: column;
		}
	}
</style>
