<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { page } from '$app/state';
	import { isAdmin } from '$lib/stores/auth';
	import {
		RAIL_SETTINGS_LABEL,
		RAIL_SETTINGS_OPEN_STORAGE_KEY,
		SETTINGS_NAV_LABEL
	} from '$lib/constants';

	interface SettingsSection {
		href: string;
		label: string;
		adminOnly: boolean;
	}

	const SETTINGS_SECTIONS: SettingsSection[] = [
		{ href: '/settings/generation', label: 'Generation', adminOnly: false },
		{ href: '/settings/playback', label: 'Playback', adminOnly: false },
		{ href: '/settings/voices', label: 'Voices', adminOnly: false },
		{ href: '/settings/account', label: 'Account', adminOnly: false },
		{ href: '/settings/users', label: 'Admin', adminOnly: true },
		{ href: '/settings/cleanup', label: 'Cleanup', adminOnly: true },
		{ href: '/settings/legal', label: 'Legal', adminOnly: false }
	];

	const admin = $derived($isAdmin);
	const visibleSections = $derived(SETTINGS_SECTIONS.filter((item) => !item.adminOnly || admin));
	const pathname = $derived(page.url.pathname);
	const onSettingsRoute = $derived(pathname.startsWith('/settings'));

	function readPersistedOpen(): boolean {
		try {
			return localStorage.getItem(RAIL_SETTINGS_OPEN_STORAGE_KEY) === 'true';
		} catch {
			return false;
		}
	}

	function persistOpen(value: boolean): void {
		try {
			localStorage.setItem(RAIL_SETTINGS_OPEN_STORAGE_KEY, String(value));
		} catch {
			// Best-effort convenience only — the disclosure still works without it.
		}
	}

	let open = $state(readPersistedOpen());

	// A plain variable, not $state: it must not itself become a dependency
	// this effect reruns for, only a value the effect reads once per actual
	// run of *its own* trigger (onSettingsRoute) — the same "track the
	// previous value in an untracked local" idiom syncSongAddressToRename
	// uses in stores/navigation.ts. Landing directly on a /settings/* route
	// (a fresh visit, a reload, a shared link, or arriving from outside
	// Settings) always finds the section it points at already expanded,
	// regardless of what a previous session left in storage — but only on
	// that entry transition. Reading `open` here as well as writing it
	// would make every click that closes the panel while already on a
	// /settings/* route re-run this same effect, find `onSettingsRoute &&
	// !open` true again, and snap it back open, so a viewer could never
	// collapse it while browsing Settings. Moving between sections
	// (Generation → Voices) keeps whatever the viewer left it at, since
	// that is not an entry transition.
	let previousOnSettingsRoute = false;
	$effect(() => {
		const enteredSettings = onSettingsRoute && !previousOnSettingsRoute;
		previousOnSettingsRoute = onSettingsRoute;
		if (enteredSettings) {
			open = true;
			persistOpen(true);
		}
	});

	function toggleOpen(): void {
		open = !open;
		persistOpen(open);
	}
</script>

<div class="rail-settings">
	<button
		type="button"
		class="row disclose"
		aria-expanded={open}
		aria-controls="rail-settings-group"
		onclick={toggleOpen}
	>
		<svg
			class="caret"
			class:open
			width="10"
			height="10"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="3"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"
		>
			<polyline points="9 6 15 12 9 18" />
		</svg>
		<span>{RAIL_SETTINGS_LABEL}</span>
	</button>
	<div class="rail-settings-panel" data-open={open} id="rail-settings-group" inert={!open}>
		<nav class="rail-settings-nav" aria-label={SETTINGS_NAV_LABEL}>
			<ul>
				{#each visibleSections as section (section.href)}
					<li>
						<a href={section.href} class="row row-sub" class:row-active={pathname === section.href}>
							{section.label}
						</a>
					</li>
				{/each}
			</ul>
		</nav>
	</div>
</div>

<style>
	.rail-settings {
		flex-shrink: 0;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 16px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.85rem;
		text-align: left;
		text-decoration: none;
		cursor: pointer;
	}

	.row:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.disclose {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.caret {
		flex-shrink: 0;
		transition: transform 0.16s ease;
	}

	.caret.open {
		transform: rotate(90deg);
	}

	.rail-settings-panel {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows 0.2s ease;
	}

	.rail-settings-panel[data-open='true'] {
		grid-template-rows: 1fr;
	}

	.rail-settings-panel > .rail-settings-nav {
		overflow: hidden;
	}

	@media (prefers-reduced-motion: reduce) {
		.caret,
		.rail-settings-panel {
			transition: none;
		}
	}

	.rail-settings-nav ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.row-sub {
		padding-left: 32px;
		font-size: 0.8rem;
		font-family: inherit;
		text-transform: none;
		letter-spacing: normal;
		border-left: 3px solid transparent;
	}

	.row-active {
		color: var(--text);
		border-left-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}
</style>
