<script lang="ts">
	import { page } from '$app/state';

	const ADMIN_PATHNAME = '/settings/users';

	let { children } = $props();

	const pathname = $derived(page.url.pathname);
	// Admin carries tables, not forms; the reading width the other settings
	// pages share leaves the Models table too narrow for its five columns.
	const wide = $derived(pathname === ADMIN_PATHNAME);
</script>

<main class="settings-content" class:settings-content--wide={wide}>
	{@render children()}
</main>

<style>
	.settings-content {
		flex: 1;
		overflow-y: auto;
		min-width: 0;
		max-width: var(--settings-content-max-width);
		--settings-content-padding: 2rem;
		padding: var(--settings-content-padding);
		box-sizing: border-box;
	}

	.settings-content :global(h1) {
		margin: 0;
		font-family: var(--font-display);
		font-size: 22px;
		font-weight: 400;
		letter-spacing: 1px;
		text-transform: uppercase;
		color: var(--text);
	}

	.settings-content--wide {
		max-width: var(--settings-admin-content-max-width);
	}
</style>
