<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { page } from '$app/state';
	import { isAdmin } from '$lib/stores/auth';
	import {
		RAIL_SETTINGS_LABEL,
		RAIL_SETTINGS_OPEN_STORAGE_KEY,
		SETTINGS_NAV_LABEL
	} from '$lib/constants';
	import RailGroup from './RailGroup.svelte';

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
</script>

<RailGroup
	label={RAIL_SETTINGS_LABEL}
	groupId="rail-settings-group"
	storageKey={RAIL_SETTINGS_OPEN_STORAGE_KEY}
	expandTrigger={onSettingsRoute}
>
	{#snippet icon()}
		<svg
			width="14"
			height="14"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"
		>
			<path
				d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
			/>
			<circle cx="12" cy="12" r="3" />
		</svg>
	{/snippet}
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
</RailGroup>

<style>
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
		border-left-color: var(--primary);
		background: color-mix(in srgb, var(--primary) 8%, transparent);
	}
</style>
