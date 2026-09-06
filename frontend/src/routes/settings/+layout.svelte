<script lang="ts">
	import { page } from '$app/state';

	const ADMIN_PATHNAME = '/settings/users';

	let { children } = $props();

	const pathname = $derived(page.url.pathname);
	// LegalContent is also rendered outside /settings (standalone /legal route,
	// the shared-page footer dialog) and already owns its own padding there.
	// Inside settings it would otherwise double up with this layout's padding.
	const selfPadded = $derived(pathname === '/settings/legal');
	// Admin carries tables, not forms; the reading width the other settings
	// pages share leaves the Models table too narrow for its five columns.
	const wide = $derived(pathname === ADMIN_PATHNAME);
</script>

<main
	class="settings-content"
	class:settings-content--self-padded={selfPadded}
	class:settings-content--wide={wide}
>
	{@render children()}
</main>

<style>
	.settings-content {
		flex: 1;
		overflow-y: auto;
		min-width: 0;
		max-width: var(--settings-content-max-width);
		padding: 2rem;
		box-sizing: border-box;
	}

	.settings-content--self-padded {
		padding: 0;
	}

	.settings-content--wide {
		max-width: var(--settings-admin-content-max-width);
	}
</style>
