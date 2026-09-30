<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { goto } from '$app/navigation';
	import Icon from '$lib/components/Icon.svelte';
	import { RAIL_SETTINGS_LABEL, SETTINGS_NAV_LABEL } from '$lib/constants';
	import { visibleSettingsSections } from '$lib/settingsSections';
	import { currentUser, isAdmin } from '$lib/stores/auth';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	let compact = $state<boolean | null>(null);

	const admin = $derived($isAdmin);
	const sections = $derived(visibleSettingsSections(admin));

	$effect(() =>
		subscribeCompactLayout((isCompact) => {
			compact = isCompact;
		})
	);

	const railListsSections = $derived(compact === false);

	$effect(() => {
		if (!railListsSections) return;
		const target = admin ? '/settings/generation' : '/settings/playback';
		goto(target, { replaceState: true });
	});
</script>

{#if compact}
	<h1 class="settings-index-title">{RAIL_SETTINGS_LABEL}</h1>
	<nav aria-label={SETTINGS_NAV_LABEL}>
		<ul class="settings-list">
			{#each sections as section (section.href)}
				<li>
					<a href={section.href} class="settings-row">
						<Icon name={section.icon} size={20} class="settings-row-icon" />
						<span class="settings-row-label">{section.label}</span>
						{#if section.id === 'account'}
							<span class="settings-row-value">{$currentUser?.username}</span>
						{/if}
						<Icon name="chevron-right" class="settings-row-chevron" />
					</a>
				</li>
			{/each}
		</ul>
	</nav>
{/if}

<style>
	.settings-index-title {
		margin: 0 0 0.5rem;
		font-family: var(--font-display);
		font-size: 1.4rem;
		font-weight: 400;
		letter-spacing: 1px;
		text-transform: uppercase;
		color: var(--text);
	}

	.settings-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		overflow: hidden;
	}

	.settings-list li + li {
		border-top: 1px solid var(--border);
	}

	.settings-row {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 52px;
		padding: 0 12px 0 14px;
		color: var(--text);
		font-size: 0.93rem;
		text-decoration: none;
	}

	.settings-row:hover {
		background: var(--surface-hover);
	}

	.settings-row :global(.settings-row-icon),
	.settings-row :global(.settings-row-chevron) {
		flex: none;
		color: var(--text-muted);
	}

	.settings-row-label {
		flex: 1;
		min-width: 0;
	}

	.settings-row-value {
		font-size: 0.78rem;
		color: var(--text-subtle);
	}
</style>
